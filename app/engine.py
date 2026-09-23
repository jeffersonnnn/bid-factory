"""Source-preserving workflow operations. No model can grant approval."""
import json
import re
from datetime import datetime, timezone
from fastapi import HTTPException
from . import ai
from .db import rows, one, insert, uid, now, encode, invalidate, invalidate_company, event
from .documents import sha, source_page, INJECTION
from .models import RequirementInput, EvidenceInput


def active_requirements(db, bid_id):
    return rows(db, '''SELECT r.*,d.name document_name,d.sequence,d.reviewed source_reviewed FROM requirements r
        JOIN documents d ON d.id=r.document_id WHERE r.bid_id=? AND NOT EXISTS
        (SELECT 1 FROM requirements n WHERE n.supersedes=r.id) ORDER BY d.sequence,r.created_at,r.id''', (bid_id,))


def source_signature(db, bid_id):
    docs = rows(db, "SELECT id,sha256,sequence FROM documents WHERE bid_id=? AND kind!='response_attachment' ORDER BY id", (bid_id,))
    return sha(encode(docs).encode())


def add_requirement(db, bid_id, req: RequirementInput):
    doc = one(db, 'documents', req.document_id)
    if doc['bid_id'] != bid_id or doc['kind'] == 'response_attachment':
        raise HTTPException(422, 'Select a source document from this bid.')
    page = source_page(doc, req.page, req.quote)
    if INJECTION.search(req.quote):
        raise HTTPException(422, 'This quote contains instructions directed at an AI. It cannot become a requirement automatically.')
    if req.supersedes:
        old = one(db, 'requirements', req.supersedes)
        old_doc = one(db, 'documents', old['document_id'])
        if old['bid_id'] != bid_id or old['kind'] != req.kind or old['key'] != req.key:
            raise HTTPException(422, 'A replacement must preserve the bid, requirement type and topic key.')
        if doc['sequence'] < old_doc['sequence'] or (doc['sequence'] == old_doc['sequence'] and doc['id'] != old_doc['id']):
            raise HTTPException(422, 'An older or unrelated document cannot override this requirement.')
        if not req.supersession_reason or db.execute('SELECT 1 FROM requirements WHERE supersedes=?', (req.supersedes,)).fetchone():
            raise HTTPException(422, 'Give a replacement reason and replace the current version only.')
        if old['mandatory'] and not req.mandatory:
            raise HTTPException(422, 'V0 cannot remove a mandatory obligation. Keep it mandatory and seek reviewer guidance.')
    constraints = req.constraints
    if set(constraints) - {'count', 'max_pages', 'deadline', 'attachment', 'uei'}:
        raise HTTPException(422, 'Unknown requirement constraint. Record it in the requirement text for human review.')
    for key in ('count', 'max_pages'):
        if key in constraints and (type(constraints[key]) is not int or not 1 <= constraints[key] <= 150):
            raise HTTPException(422, f'{key} must be an integer from 1 to 150.')
    fingerprint = sha(encode({'doc': doc['id'], **req.model_dump()}).encode())
    exists = db.execute('SELECT id FROM requirements WHERE fingerprint=?', (fingerprint,)).fetchone()
    if exists:
        return exists['id']
    ident = uid('REQ')
    insert(db, 'requirements', id=ident, bid_id=bid_id, document_id=doc['id'], page=req.page,
        locator=page['locator'], quote=req.quote, text=req.text, kind=req.kind, scope=req.scope,
        mandatory=int(req.mandatory), key=req.key, constraints=encode(constraints), confidence=req.confidence,
        evaluation_factor=req.evaluation_factor, component=req.component, supersedes=req.supersedes,
        supersession_reason=req.supersession_reason, fingerprint=fingerprint, created_at=now())
    db.execute('UPDATE documents SET reviewed=0 WHERE id=?', (doc['id'],))
    invalidate(db, bid_id)
    return ident


def extract(db, bid_id):
    one(db, 'bids', bid_id)
    docs = rows(db, "SELECT * FROM documents WHERE bid_id=? AND kind!='response_attachment' AND extracted=0 ORDER BY sequence,created_at", (bid_id,))
    if not docs and not active_requirements(db, bid_id):
        raise HTTPException(409, 'Upload a readable solicitation first.')
    db.execute("UPDATE bids SET state='EXTRACTING' WHERE id=?", (bid_id,))
    total = 0
    for doc in docs:
        candidates = ai.extract_requirements(doc)
        if not isinstance(candidates, list) or len(candidates) > 800:
            raise HTTPException(422, 'Invalid extraction output. No requirements were committed.')
        for raw in candidates:
            try:
                req = RequirementInput.model_validate({**raw, 'document_id': doc['id']})
            except Exception as exc:
                raise HTTPException(422, 'Invalid requirement suggestion. Review the source and retry.') from exc
            # Suggest explicit lineage only for singular, identical controlled topics.
            # Other amendment changes must be linked by the reviewer, not guessed.
            if req.kind in ('page_limit', 'deadline') and doc['sequence'] > 0:
                old = [r for r in active_requirements(db, bid_id) if r['kind'] == req.kind and r['sequence'] < doc['sequence']]
                if len(old) == 1 and re.search(r'revis|replac|supersed|extend|chang', req.quote, re.I):
                    req.key = old[0]['key']
                    req.supersedes = old[0]['id']
                    req.supersession_reason = 'Explicit amendment revision. Reviewer must confirm source coverage.'
            add_requirement(db, bid_id, req)
            total += 1
        db.execute('UPDATE documents SET extracted=1 WHERE id=?', (doc['id'],))
    db.execute("UPDATE bids SET state='ANALYZED' WHERE id=?", (bid_id,))
    insert(db, 'workflow_runs', id=uid('RUN'), bid_id=bid_id, stage='EXTRACTING', status='COMPLETED',
           detail=encode({'provider': ai.provider(), 'requirements_added': total}), created_at=now())
    return total


def add_evidence(db, company_id, item: EvidenceInput):
    doc = one(db, 'documents', item.document_id)
    if doc['company_id'] != company_id or (doc['bid_id'] and doc['kind'] != 'response_attachment'):
        raise HTTPException(422, 'Evidence must come from this company or a response attachment.')
    p = source_page(doc, item.page, item.quote)
    if INJECTION.search(item.quote):
        raise HTTPException(422, 'Instructions directed at an AI cannot become proposal evidence.')
    existing = db.execute('SELECT id FROM evidence WHERE document_id=? AND page=? AND quote=?', (doc['id'], item.page, item.quote)).fetchone()
    if existing:
        return existing['id']
    ident = uid('EVD')
    insert(db, 'evidence', id=ident, company_id=company_id, document_id=doc['id'], bid_id=doc['bid_id'],
        page=item.page, locator=p['locator'], quote=item.quote, statement=item.quote, kind=item.kind,
        fact_key=item.fact_key.lower(), source_type='document', created_at=now())
    invalidate_company(db, company_id)
    return ident


def extract_company(db, company_id):
    count = 0
    for doc in rows(db, 'SELECT * FROM documents WHERE company_id=? AND bid_id IS NULL AND extracted=0', (company_id,)):
        candidates = ai.extract_evidence(doc)
        if not isinstance(candidates, list) or len(candidates) > 1000:
            raise HTTPException(422, 'Invalid evidence output.')
        for raw in candidates:
            try:
                item = EvidenceInput.model_validate({**raw, 'document_id': doc['id']})
            except Exception as exc:
                raise HTTPException(422, 'Invalid evidence suggestion. No evidence was approved.') from exc
            add_evidence(db, company_id, item)
            count += 1
        db.execute('UPDATE documents SET extracted=1 WHERE id=?', (doc['id'],))
    return count


def evidence_for(db, bid):
    return rows(db, '''SELECT e.*,d.name document_name FROM evidence e LEFT JOIN documents d ON d.id=e.document_id
        WHERE e.company_id=? AND (e.bid_id IS NULL OR e.bid_id=?) AND e.rejected=0
        AND NOT EXISTS (SELECT 1 FROM evidence n WHERE n.supersedes=e.id AND n.approved=1)
        ORDER BY e.created_at''', (bid['company_id'], bid['id']))


def conflicts(evidence):
    grouped = {}
    for e in evidence:
        if e['fact_key']:
            grouped.setdefault(e['fact_key'], []).append(e)
    # Include unapproved source candidates: silently approving just one is not resolution.
    return {key: group for key, group in grouped.items()
            if len({e['statement'].strip().lower() for e in group}) > 1}


def eligible_evidence(db, e):
    if not e['approved'] or not e['verified'] or e['rejected'] or INJECTION.search(e['statement']):
        return False
    if e['expires_at']:
        try:
            exp = datetime.fromisoformat(e['expires_at'].replace('Z', '+00:00'))
            if exp.tzinfo is None or exp <= datetime.now(timezone.utc):
                return False
        except ValueError:
            return False
    if e['source_type'] == 'document':
        doc = one(db, 'documents', e['document_id'])
        try:
            source_page(doc, e['page'], e['quote'])
        except HTTPException:
            return False
        return e['statement'] == e['quote'] and doc['company_id'] == e['company_id']
    answer = db.execute('SELECT * FROM answers WHERE evidence_id=?', (e['id'],)).fetchone()
    return bool(answer and answer['text'] == e['statement'] and answer['customer_name'] == e['customer_name'])


def controls_valid(db, bid):
    c = json.loads(bid['controls'])
    return c if c.get('source_signature') == source_signature(db, bid['id']) else {}


def requirement_status(db, bid, req, evidence=None):
    ev = evidence if evidence is not None else evidence_for(db, bid)
    by_id = {e['id']: e for e in ev}
    mapped = rows(db, 'SELECT * FROM mappings WHERE requirement_id=?', (req['id'],))
    conflict_ids = {e['id'] for g in conflicts(ev).values() for e in g}
    approved = [by_id[m['evidence_id']] for m in mapped if m['approved'] and m['evidence_id'] in by_id
                and m['evidence_id'] not in conflict_ids and eligible_evidence(db, by_id[m['evidence_id']])]
    constraints = json.loads(req['constraints'])
    c = controls_valid(db, bid)
    if req['kind'] in ('deadline', 'page_limit', 'submission'):
        key = {'deadline': 'deadline_requirement_id', 'page_limit': 'page_limit_requirement_id', 'submission': 'submission_requirement_id'}[req['kind']]
        valid = c.get(key) == req['id'] and req['source_reviewed']
        return ('SATISFIED' if valid else 'CLIENT_CONFIRMATION_REQUIRED'), approved
    if req['kind'] == 'pricing' and not any(e['source_type'] == 'client' and re.search(r'(?:\$|\bUSD\s+)\s*\d', e['statement'], re.I) for e in approved):
        approved = []
    if constraints.get('uei') or req['key'] == 'uei':
        approved = [e for e in approved if re.search(r'\b[A-Z0-9]{12}\b', e['statement'])]
    if req['kind'] == 'eligibility' and any(re.search(r'\b(not eligible|not a small business|ineligible|does not qualify)\b', e['statement'], re.I) for e in approved):
        return 'FAILED', approved
    unique = {e['fact_key'] or e['statement'].lower() for e in approved}
    needed = constraints.get('count', 1)
    attachment_ok = not (constraints.get('attachment') or req['kind'] in ('attachment', 'form', 'signature')) or any(
        e['document_id'] and one(db, 'documents', e['document_id'])['kind'] == 'response_attachment' for e in approved)
    if len(unique) >= needed and attachment_ok:
        return 'SATISFIED', approved
    if approved:
        return 'PARTIAL', approved
    if mapped:
        return 'CLIENT_CONFIRMATION_REQUIRED', approved
    return 'MISSING', approved


def map_suggestions(db, bid_id):
    bid = one(db, 'bids', bid_id)
    ev = evidence_for(db, bid)
    reqs = active_requirements(db, bid_id)
    pairs = []
    if ai.provider() != 'offline':
        result = ai.ask('Suggest evidence matches. Return {"mappings":[{"requirement_id":"REQ-id","evidence_ids":["EVD-id"]}]}. '
            'Use only supplied IDs. Never infer that evidence is sufficient. Do not use pricing from company documents.',
            {'requirements': reqs, 'evidence': [{k: e[k] for k in ('id','statement','kind')} for e in ev]})
        for m in result.get('mappings', []):
            if m.get('requirement_id') not in {r['id'] for r in reqs}:
                raise HTTPException(422, 'AI suggested a requirement outside this bid.')
            for eid in m.get('evidence_ids', []):
                if eid not in {e['id'] for e in ev}:
                    raise HTTPException(422, 'AI suggested evidence outside this company.')
                pairs.append((m['requirement_id'], eid))
    else:
        for req in reqs:
            for e in ev:
                if e['kind'] == req['kind'] and req['kind'] not in ('other','pricing','deadline','submission','page_limit'):
                    pairs.append((req['id'], e['id']))
    added = 0
    for rid, eid in pairs:
        added += db.execute('INSERT OR IGNORE INTO mappings(requirement_id,evidence_id,rationale) VALUES(?,?,?)',
                           (rid, eid, 'Suggested match. Human review required.')).rowcount
    if added:
        invalidate(db, bid_id)
    return added


def questions(db, bid_id):
    bid = one(db, 'bids', bid_id)
    ev = evidence_for(db, bid)
    reqs = active_requirements(db, bid_id)
    current = {r['id'] for r in reqs}
    for q in rows(db, 'SELECT * FROM questions WHERE bid_id=?', (bid_id,)):
        if q['requirement_id'] not in current:
            db.execute("UPDATE questions SET status='SUPERSEDED' WHERE id=?", (q['id'],))
    for req in reqs:
        status, approved = requirement_status(db, bid, req, ev)
        missing = max(0, json.loads(req['constraints']).get('count', 1) - len(approved))
        text = f"Provide evidence for: {req['text']}"
        if req['kind'] == 'pricing':
            text = f"Customer input required: provide the actual price, units and period for: {req['text']}"
        elif req['kind'] in ('deadline', 'page_limit', 'submission'):
            text = f"Confirm the submission settings from {req['document_name']}, {req['locator']}: {req['text']}"
        elif req['kind'] == 'past_performance':
            text = f"Provide {missing} more distinct, comparable project reference(s). Required details: {req['text']}"
        elif status == 'CLIENT_CONFIRMATION_REQUIRED':
            text = f"Review the proposed evidence and resolve any conflicts for: {req['text']}"
        db.execute('''INSERT INTO questions(id,bid_id,requirement_id,text,status) VALUES(?,?,?,?,?)
            ON CONFLICT(requirement_id) DO UPDATE SET text=excluded.text,status=excluded.status''',
            (uid('Q'), bid_id, req['id'], text, 'RESOLVED' if status == 'SATISFIED' else 'OPEN'))
    return rows(db, "SELECT * FROM questions WHERE bid_id=? AND status='OPEN'", (bid_id,))


def draft_sections(db, bid):
    sections = rows(db, 'SELECT * FROM proposal_sections WHERE bid_id=? AND revision=? ORDER BY position', (bid['id'], bid['draft_revision']))
    for s in sections:
        s['claims'] = rows(db, 'SELECT * FROM proposal_claims WHERE section_id=? ORDER BY rowid', (s['id'],))
    return sections


def draft_hash(db, bid):
    return sha(encode({'revision': bid['revision'], 'draft_revision': bid['draft_revision'],
                      'sections': draft_sections(db, bid), 'controls': bid['controls'],
                      'sources': source_signature(db, bid['id'])}).encode())


def generate(db, bid_id):
    from .rules import blockers
    bid = one(db, 'bids', bid_id)
    findings = blockers(db, bid_id, include_draft=False)
    if findings:
        raise HTTPException(409, {'message': 'Resolve the blockers before drafting.', 'blockers': findings})
    reqs = active_requirements(db, bid_id)
    ev = evidence_for(db, bid)
    db.execute("UPDATE bids SET state='DRAFTING',approved_revision=NULL WHERE id=?", (bid_id,))
    # A new generation has its own revision, even if the evidence did not change.
    invalidate(db, bid_id, 'DRAFTING')
    bid = one(db, 'bids', bid_id)
    for i, req in enumerate(reqs):
        if req['kind'] in ('deadline', 'page_limit', 'submission', 'formatting'):
            continue
        _, approved = requirement_status(db, bid, req, ev)
        approved.sort(key=lambda e: (e['fact_key'], e['statement']))
        section = uid('SEC')
        titles = {'technical':'Technical approach', 'past_performance':'Past performance',
                  'eligibility':'Company eligibility', 'administrative':'Company information',
                  'pricing':'Pricing', 'staffing':'Staffing', 'key_personnel':'Key personnel',
                  'certification':'Certifications', 'management':'Management approach',
                  'attachment':'Required attachment', 'form':'Required form', 'signature':'Signature',
                  'amendment':'Amendment acknowledgment', 'representation':'Representations'}
        insert(db, 'proposal_sections', id=section, bid_id=bid_id, revision=bid['revision'],
               requirement_id=req['id'], title=titles.get(req['kind'],'Response'), position=i)
        for e in approved:
            # Exact evidence text is the claim boundary. No free-text factual prose.
            insert(db, 'proposal_claims', id=uid('CLM'), section_id=section, evidence_id=e['id'],
                   text=e['statement'], claim_type='CLIENT_CONFIRMED' if e['source_type'] == 'client' else 'FACTUAL')
    db.execute("UPDATE bids SET draft_revision=revision,state='DRAFTED' WHERE id=?", (bid_id,))
    insert(db, 'workflow_runs', id=uid('RUN'), bid_id=bid_id, stage='DRAFTING', status='COMPLETED',
           detail='Evidence-only assembly. No invented factual prose.', created_at=now())
    return draft_sections(db, one(db, 'bids', bid_id))
