"""Deterministic readiness. The model cannot suppress or resolve these findings."""
import json
import re
from datetime import datetime, timezone
from .db import rows, one
from .documents import sha, source_page
from .engine import (active_requirements, evidence_for, conflicts, requirement_status,
                     controls_valid, draft_sections, draft_hash, eligible_evidence)


def finding(rule, text, action, requirement=None):
    return {'severity': 'BLOCKING', 'rule_id': rule, 'finding': text, 'action': action, 'requirement_id': requirement}


def blockers(db, bid_id, include_draft=True, include_audit=False):
    bid = one(db, 'bids', bid_id)
    reqs = active_requirements(db, bid_id)
    all_reqs = rows(db, 'SELECT * FROM requirements WHERE bid_id=?', (bid_id,))
    docs = rows(db, "SELECT * FROM documents WHERE bid_id=? AND kind!='response_attachment'", (bid_id,))
    ev = evidence_for(db, bid)
    result = []
    def add(rule, text, action, rid=None):
        result.append(finding(rule, text, action, rid))
    if not docs or not reqs:
        add('RULE-001', 'No extracted solicitation requirements.', 'Upload and extract the full solicitation package.')
    for doc in docs:
        if not doc['extracted'] or not doc['reviewed']:
            add('RULE-011', f"Source coverage is not confirmed: {doc['name']}.", 'Review every source block and add any omitted obligation.')
        if sha(doc['content']) != doc['sha256']:
            add('RULE-011', f"Source integrity failed: {doc['name']}.", 'Restore the immutable source from a trusted backup.')
        if any('little or no text' in w for w in json.loads(doc['warnings'])):
            add('RULE-011', f"Unreadable source page in {doc['name']}.", 'Use a complete text-readable source package.')
        if doc['kind'] == 'amendment' and not doc['acknowledged']:
            add('RULE-008', f"Amendment {doc['sequence']:04d} is not acknowledged.", 'Record customer acknowledgment and include any required signed form.')
    for req in all_reqs:
        try:
            source_page(one(db, 'documents', req['document_id']), req['page'], req['quote'])
        except Exception:
            add('RULE-001', 'A requirement has lost its source.', 'Restore the source link.', req['id'])
    grouped = {}
    for r in reqs:
        grouped.setdefault(r['key'], []).append(r)
    for key, group in grouped.items():
        if len(group) > 1:
            add('RULE-007', f"Multiple current requirements use topic '{key}'.", 'Link explicit replacements or assign separate topics with sourced revisions.')
    for key in conflicts(ev):
        add('RULE-011', f"Conflicting evidence for '{key}'.", 'Reject the incorrect source with a reason, or record a customer correction that replaces it.')
    controls = controls_valid(db, bid)
    if not controls:
        add('RULE-011', 'Submission settings and package completeness are not confirmed for these source versions.',
            'Confirm the deadline, method, page limit, supported scope and complete source package.')
    else:
        try:
            deadline = datetime.fromisoformat(controls['deadline'].replace('Z', '+00:00'))
            if deadline.tzinfo is None or deadline <= datetime.now(timezone.utc):
                add('RULE-004', 'The submission deadline has passed or has no time zone.', 'Upload an official deadline extension or stop this bid.')
        except (KeyError, ValueError):
            add('RULE-004', 'No valid deadline.', 'Confirm a deadline with an explicit time zone.')
        current = {r['id']: r for r in reqs}
        for field, kind in [('deadline_requirement_id','deadline'),('submission_requirement_id','submission'),('page_limit_requirement_id','page_limit')]:
            rid = controls.get(field)
            if (rid is None and kind != 'page_limit') or (rid is not None and (rid not in current or current[rid]['kind'] != kind)):
                add('RULE-007', f'The confirmed {kind} uses a superseded or invalid source.', 'Confirm the settings from the current requirement.')
    for req in reqs:
        status, _ = requirement_status(db, bid, req, ev)
        if req['mandatory'] and status != 'SATISFIED':
            rule = 'RULE-009' if req['kind'] == 'pricing' else 'RULE-010' if req['key'] == 'uei' else 'RULE-001'
            add(rule, f"{status}: {req['text']}", 'Answer the targeted question and approve sufficient evidence.', req['id'])
        c = json.loads(req['constraints'])
        if req['kind'] == 'page_limit' and controls and c.get('max_pages') and controls.get('page_limit', 999) > c['max_pages']:
            add('RULE-006', 'The confirmed page limit exceeds the source limit.', 'Apply the current source page limit.', req['id'])
        if req['kind'] == 'deadline' and controls and c.get('deadline'):
            try:
                actual = datetime.fromisoformat(c['deadline'].replace('Z', '+00:00'))
                entered = datetime.fromisoformat(controls['deadline'].replace('Z', '+00:00'))
                if actual != entered:
                    add('RULE-004', 'The confirmed deadline differs from the source deadline.', 'Correct the confirmed deadline.', req['id'])
            except ValueError:
                add('RULE-004', 'The extracted deadline is ambiguous.', 'Add a corrected sourced requirement.', req['id'])
    if include_draft:
        for old in rows(db, '''SELECT DISTINCT f.finding,f.action,f.requirement_id FROM audit_findings f
                JOIN audit_runs a ON a.id=f.run_id WHERE a.bid_id=? AND f.rule_id='RED-TEAM' AND f.resolved_revision IS NULL''', (bid_id,)):
            add('RED-TEAM', old['finding'], old['action'], old['requirement_id'])
        sections = draft_sections(db, bid)
        if bid['draft_revision'] != bid['revision'] or not sections:
            add('RULE-012', 'No current proposal draft.', 'Generate a draft from the current approved evidence.')
        else:
            by_id = {e['id']: e for e in ev}
            req_ids = {r['id'] for r in reqs}
            for s in sections:
                if s['requirement_id'] not in req_ids:
                    add('RULE-001', 'A proposal section uses a superseded requirement.', 'Generate the proposal again.', s['requirement_id'])
                for c in s['claims']:
                    e = by_id.get(c['evidence_id'])
                    mapping = db.execute('SELECT approved FROM mappings WHERE requirement_id=? AND evidence_id=?', (s['requirement_id'], c['evidence_id'])).fetchone()
                    if not e or not eligible_evidence(db, e) or c['text'] != e['statement'] or not mapping or not mapping['approved']:
                        add('RULE-002', 'A proposal claim has no valid approved evidence.', 'Remove the claim or record and approve its source.', s['requirement_id'])
            for r in reqs:
                if r['mandatory'] and r['kind'] not in ('deadline','page_limit','submission','formatting'):
                    matched = [s for s in sections if s['requirement_id'] == r['id']]
                    if not matched or not any(s['claims'] for s in matched):
                        add('RULE-001', 'A mandatory requirement is absent from the proposal.', 'Generate a complete response.', r['id'])
                    _, required_evidence = requirement_status(db, bid, r, ev)
                    included = {claim['evidence_id'] for s in matched for claim in s['claims']}
                    if not {e['id'] for e in required_evidence}.issubset(included):
                        add('RULE-001', 'Required mapped evidence is missing from the proposal.', 'Regenerate the complete requirement response.', r['id'])
            from .render import render_input, render_proposal
            try:
                _, _, count = render_proposal(render_input(db, bid))
                if count > controls.get('page_limit', 0):
                    add('RULE-006', f"The rendered proposal has {count} pages; limit {controls.get('page_limit', 0)}.", 'Shorten the approved response or correct a sourced limit.')
            except (RuntimeError, OSError, TimeoutError) as exc:
                add('RULE-006', str(exc), 'Restore the document renderer before final export.')
    if include_audit:
        audit = db.execute('SELECT * FROM audit_runs WHERE bid_id=? ORDER BY rowid DESC LIMIT 1', (bid_id,)).fetchone()
        if not audit or audit['revision'] != bid['revision'] or audit['content_hash'] != draft_hash(db, bid):
            add('RULE-003', 'No independent audit exists for this exact draft.', 'Run the independent audit.')
        elif audit['status'] != 'PASSED':
            stored = rows(db, 'SELECT severity,rule_id,finding,action,requirement_id FROM audit_findings WHERE run_id=?', (audit['id'],))
            result.extend(stored or [finding('RULE-003', 'The independent audit did not pass.', 'Resolve the findings and audit again.')])
    # Stable de-duplication makes the blocker count meaningful.
    return list({(r['rule_id'],r['requirement_id'],r['finding']): r for r in result}.values())


def qualification(db, bid_id):
    bid = one(db, 'bids', bid_id)
    dimensions = {}
    for r in active_requirements(db, bid_id):
        status, _ = requirement_status(db, bid, r)
        if r['kind'] in ('eligibility','certification','staffing','past_performance','deadline'):
            dimensions.setdefault(r['kind'], []).append({'requirement_id': r['id'], 'status': status, 'reason': r['text']})
    no_go = any(r['mandatory'] and r['kind'] in ('eligibility','certification') and requirement_status(db, bid, r)[0] != 'SATISFIED'
                for r in active_requirements(db, bid_id))
    issues = blockers(db, bid_id, include_draft=False)
    no_go = no_go or any(f['rule_id'] == 'RULE-004' and 'passed' in f['finding'] for f in issues)
    return {'status': 'NO-GO' if no_go else 'REVIEW' if issues else 'GO', 'dimensions': dimensions}
