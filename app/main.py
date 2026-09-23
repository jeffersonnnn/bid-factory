import io
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import ai, engine, rules
from .db import init, transaction, rows, one, insert, uid, now, encode, invalidate, invalidate_company, event
from .documents import parse, sha, safe_filename, MAX_BYTES, INJECTION
from .models import (CompanyInput, BidInput, RequirementInput, EvidenceInput, ReviewInput,
    EvidenceReview, MappingInput, AnswerInput, ControlsInput, AuditInput, ExportInput)
from .render import package, render_input, render_proposal

STATIC = Path(__file__).parent / 'static'
security = HTTPBasic(auto_error=False)


@asynccontextmanager
async def lifespan(app):
    if os.getenv('APP_MODE', 'local') != 'local' and len(os.getenv('APP_PASSWORD', '')) < 16:
        raise RuntimeError('Production mode requires APP_PASSWORD of at least 16 characters.')
    if ai.provider() not in ('offline', 'anthropic', 'openai', 'openrouter'):
        raise RuntimeError('AI_PROVIDER must be offline, anthropic, openai or openrouter.')
    init()
    yield


app = FastAPI(title='Bid Factory', version='0.1.0', lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(','))


def authenticate(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    password = os.getenv('APP_PASSWORD', '')
    if not password and os.getenv('APP_MODE', 'local') == 'local':
        if request.client and request.client.host not in ('127.0.0.1', '::1', 'testclient'):
            raise HTTPException(403, 'Local mode only accepts loopback connections.')
        return 'local operator'
    if not credentials or not (secrets.compare_digest(credentials.username.encode(), os.getenv('APP_USER', 'operator').encode())
                                and secrets.compare_digest(credentials.password.encode(), password.encode())):
        raise HTTPException(401, 'Sign in to the review desk.', headers={'WWW-Authenticate': 'Basic realm="Bid Factory"'})
    return credentials.username


@app.middleware('http')
async def safety_headers(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and urlparse(origin).netloc != request.headers.get('host')):
            return JSONResponse({'detail': 'Cross-site changes are not allowed.'}, status_code=403)
        size = request.headers.get('content-length')
        if size and (not size.isdigit() or int(size) > MAX_BYTES + 1024 * 64):
            return JSONResponse({'detail': 'The request exceeds the upload limit.'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail': 'This change violates an immutable record or a required source link.'}, status_code=409)


app.mount('/static', StaticFiles(directory=STATIC), name='static')


@app.get('/health')
def health():
    return {'status': 'ok', 'version': '0.1.0'}


@app.get('/', dependencies=[Depends(authenticate)])
@app.get('/companies/{path:path}', dependencies=[Depends(authenticate)])
@app.get('/bids/{path:path}', dependencies=[Depends(authenticate)])
def index(path=''):
    return FileResponse(STATIC / 'index.html')


@app.get('/api/workspace', dependencies=[Depends(authenticate)])
def workspace():
    with transaction() as db:
        return {'companies': rows(db, 'SELECT * FROM companies ORDER BY created_at DESC'),
                'bids': rows(db, 'SELECT b.*,c.name company_name FROM bids b JOIN companies c ON c.id=b.company_id ORDER BY b.created_at DESC'),
                'ai': {'provider': ai.provider(), 'configured': ai.available(),
                       'model': ai.model(), 'audit_model': ai.model('audit')}, 'mode': os.getenv('APP_MODE','local')}


@app.post('/api/companies', dependencies=[Depends(authenticate)])
def create_company(body: CompanyInput):
    with transaction() as db:
        ident = uid('CO')
        insert(db, 'companies', id=ident, organization_id='local', name=body.name,
               profile=encode(body.profile), created_at=now())
        return one(db, 'companies', ident)


@app.get('/api/companies/{company_id}', dependencies=[Depends(authenticate)])
def get_company(company_id: str):
    with transaction() as db:
        company = one(db, 'companies', company_id)
        docs = rows(db, 'SELECT id,name,kind,sha256,pages,warnings,extracted,reviewed FROM documents WHERE company_id=? AND bid_id IS NULL', (company_id,))
        return {'company': company, 'documents': docs,
                'evidence': rows(db, 'SELECT e.*,d.name document_name FROM evidence e LEFT JOIN documents d ON d.id=e.document_id WHERE e.company_id=? ORDER BY e.created_at', (company_id,))}


def upload(db, company_id, bid_id, file, kind, sequence):
    one(db, 'companies', company_id)
    name = safe_filename(file.filename or 'document')
    content = file.file.read(MAX_BYTES + 1)
    pages, warnings = parse(name, content, allow_scanned=kind == 'response_attachment')
    if kind != 'response_attachment' and any('little or no text' in w for w in warnings):
        raise HTTPException(422, 'The PDF has unreadable pages. Run OCR and upload the complete readable file.')
    digest = sha(content)
    old = db.execute('SELECT id FROM documents WHERE company_id=? AND bid_id IS ? AND kind=? AND sequence=? AND sha256=?',
        (company_id, bid_id, kind, sequence, digest)).fetchone()
    if old:
        return {'id': old['id'], 'duplicate': True}
    ident = uid('DOC')
    insert(db, 'documents', id=ident, company_id=company_id, bid_id=bid_id, name=name, kind=kind,
           sequence=sequence, sha256=digest, content=content, pages=encode(pages), warnings=encode(warnings), created_at=now())
    if bid_id:
        invalidate(db, bid_id, 'DOCUMENTS_UPLOADED')
    else:
        invalidate_company(db, company_id)
    return {'id': ident, 'name': name, 'warnings': warnings, 'blocks': len(pages)}


@app.post('/api/companies/{company_id}/documents', dependencies=[Depends(authenticate)])
def company_upload(company_id: str, file: UploadFile = File(...)):
    with transaction() as db:
        return upload(db, company_id, None, file, 'company', 0)


@app.post('/api/companies/{company_id}/extract', dependencies=[Depends(authenticate)])
def company_extract(company_id: str):
    with transaction() as db:
        one(db, 'companies', company_id)
        return {'added': engine.extract_company(db, company_id)}


@app.post('/api/companies/{company_id}/evidence', dependencies=[Depends(authenticate)])
def manual_evidence(company_id: str, body: EvidenceInput):
    with transaction() as db:
        return {'id': engine.add_evidence(db, company_id, body)}


@app.post('/api/evidence/{evidence_id}/review', dependencies=[Depends(authenticate)])
def evidence_review(evidence_id: str, body: EvidenceReview):
    if body.expires_at:
        try:
            if datetime.fromisoformat(body.expires_at.replace('Z','+00:00')).tzinfo is None:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'Use an expiration date with a time zone.')
    with transaction() as db:
        e = one(db, 'evidence', evidence_id)
        if body.approved and INJECTION.search(e['statement']):
            raise HTTPException(422, 'AI instructions cannot be approved as evidence.')
        db.execute('UPDATE evidence SET verified=?,approved=?,rejected=?,expires_at=? WHERE id=?',
                   (int(body.approved), int(body.approved), int(not body.approved), body.expires_at, evidence_id))
        invalidate_company(db, e['company_id'])
        event(db, e['bid_id'], 'EVIDENCE_REVIEW', body.reviewer,
              encode({'id': evidence_id, 'approved': body.approved, 'reason': body.reason}), body.duration_seconds)
        return {'id': evidence_id, 'approved': body.approved}


@app.post('/api/bids', dependencies=[Depends(authenticate)])
def create_bid(body: BidInput):
    with transaction() as db:
        one(db, 'companies', body.company_id)
        ident = uid('BID')
        insert(db, 'bids', id=ident, company_id=body.company_id, title=body.title, created_at=now())
        return one(db, 'bids', ident)


@app.post('/api/bids/{bid_id}/documents', dependencies=[Depends(authenticate)])
def bid_upload(bid_id: str, file: UploadFile = File(...), kind: str = Form('solicitation'), sequence: int = Form(0)):
    if kind not in ('solicitation','amendment','response_attachment') or not 0 <= sequence <= 9999:
        raise HTTPException(422, 'Select a valid document role and amendment number.')
    if (kind == 'amendment' and sequence == 0) or (kind != 'amendment' and sequence != 0):
        raise HTTPException(422, 'Only an amendment has a number greater than zero.')
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        return upload(db, bid['company_id'], bid_id, file, kind, sequence)


@app.get('/api/documents/{document_id}', dependencies=[Depends(authenticate)])
def get_document(document_id: str):
    with transaction() as db:
        doc = one(db, 'documents', document_id)
        del doc['content']
        return doc


@app.get('/api/documents/{document_id}/download', dependencies=[Depends(authenticate)])
def download_document(document_id: str):
    with transaction() as db:
        doc = one(db, 'documents', document_id)
        return StreamingResponse(io.BytesIO(doc['content']), media_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{doc["name"]}"'})


@app.post('/api/documents/{document_id}/review', dependencies=[Depends(authenticate)])
def review_document(document_id: str, body: ReviewInput):
    with transaction() as db:
        doc = one(db, 'documents', document_id)
        if not doc['extracted'] or not doc['bid_id'] or doc['kind'] == 'response_attachment':
            raise HTTPException(409, 'Extract this source document before confirming coverage.')
        db.execute('UPDATE documents SET reviewed=1 WHERE id=?', (document_id,))
        invalidate(db, doc['bid_id'])
        event(db, doc['bid_id'], 'SOURCE_COVERAGE_REVIEW', body.reviewer,
              encode({'document_id': document_id, 'reason': body.reason}), body.duration_seconds)
        return {'reviewed': True}


@app.post('/api/documents/{document_id}/acknowledge', dependencies=[Depends(authenticate)])
def acknowledge(document_id: str, body: ReviewInput):
    with transaction() as db:
        doc = one(db, 'documents', document_id)
        if doc['kind'] != 'amendment':
            raise HTTPException(422, 'This document is not an amendment.')
        db.execute('UPDATE documents SET acknowledged=1 WHERE id=?', (document_id,))
        invalidate(db, doc['bid_id'])
        event(db, doc['bid_id'], 'AMENDMENT_ACKNOWLEDGED', body.reviewer,
              encode({'document_id': document_id, 'reason': body.reason}), body.duration_seconds)
        return {'acknowledged': True}


@app.post('/api/documents/{document_id}/extract-evidence', dependencies=[Depends(authenticate)])
def attachment_evidence(document_id: str):
    with transaction() as db:
        doc = one(db, 'documents', document_id)
        if doc['kind'] != 'response_attachment':
            raise HTTPException(422, 'Select a response attachment.')
        added = []
        for raw in ai.extract_evidence(doc):
            item = EvidenceInput.model_validate({**raw, 'document_id': document_id})
            added.append(engine.add_evidence(db, doc['company_id'], item))
        db.execute('UPDATE documents SET extracted=1 WHERE id=?', (document_id,))
        return {'evidence_ids': added}


@app.post('/api/bids/{bid_id}/extract', dependencies=[Depends(authenticate)])
def extract(bid_id: str):
    with transaction() as db:
        return {'added': engine.extract(db, bid_id)}


@app.post('/api/bids/{bid_id}/requirements', dependencies=[Depends(authenticate)])
def manual_requirement(bid_id: str, body: RequirementInput):
    with transaction() as db:
        one(db, 'bids', bid_id)
        return {'id': engine.add_requirement(db, bid_id, body)}


@app.post('/api/bids/{bid_id}/controls', dependencies=[Depends(authenticate)])
def save_controls(bid_id: str, body: ControlsInput):
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        current = {r['id']: r for r in engine.active_requirements(db, bid_id)}
        for field, kind in [('deadline_requirement_id','deadline'),('submission_requirement_id','submission'),('page_limit_requirement_id','page_limit')]:
            ident = getattr(body, field)
            if ident is not None and (ident not in current or current[ident]['kind'] != kind):
                raise HTTPException(422, f'Select the current {kind} requirement.')
        if any(r['kind'] == 'page_limit' for r in current.values()) and not body.page_limit_requirement_id:
            raise HTTPException(422, 'Select the source page-limit requirement.')
        data = body.model_dump()
        data['source_signature'] = engine.source_signature(db, bid_id)
        db.execute('UPDATE bids SET controls=? WHERE id=?', (encode(data), bid_id))
        invalidate(db, bid_id)
        event(db, bid_id, 'SUBMISSION_SETTINGS', body.reviewer, body.reason, body.duration_seconds)
        return {'saved': True}


@app.post('/api/bids/{bid_id}/map-evidence', dependencies=[Depends(authenticate)])
def map_evidence(bid_id: str):
    with transaction() as db:
        return {'suggested': engine.map_suggestions(db, bid_id)}


@app.post('/api/requirements/{requirement_id}/mapping', dependencies=[Depends(authenticate)])
def approve_mapping(requirement_id: str, body: MappingInput):
    with transaction() as db:
        req = one(db, 'requirements', requirement_id)
        bid = one(db, 'bids', req['bid_id'])
        if requirement_id not in {r['id'] for r in engine.active_requirements(db, bid['id'])}:
            raise HTTPException(409, 'This requirement was superseded.')
        available = {e['id']: e for e in engine.evidence_for(db, bid)}
        for eid in body.evidence_ids:
            if eid not in available:
                raise HTTPException(422, 'Evidence belongs to another company, bid, or superseded record.')
            if body.approved and not engine.eligible_evidence(db, available[eid]):
                raise HTTPException(409, 'Approve and verify the selected evidence first.')
        db.execute('DELETE FROM mappings WHERE requirement_id=?', (requirement_id,))
        for eid in set(body.evidence_ids):
            db.execute('INSERT INTO mappings VALUES(?,?,?,?)', (requirement_id, eid, int(body.approved), body.reason))
        invalidate(db, bid['id'])
        event(db, bid['id'], 'MAPPING_REVIEW', body.reviewer,
              encode({'requirement_id': requirement_id, 'evidence_ids': body.evidence_ids, 'reason': body.reason}), body.duration_seconds)
        return {'saved': True}


@app.post('/api/bids/{bid_id}/questions', dependencies=[Depends(authenticate)])
def get_questions(bid_id: str):
    with transaction() as db:
        return {'questions': engine.questions(db, bid_id)}


@app.post('/api/bids/{bid_id}/answers', dependencies=[Depends(authenticate)])
def answer(bid_id: str, body: AnswerInput):
    if INJECTION.search(body.text):
        raise HTTPException(422, 'Record a factual answer, not instructions directed at an AI.')
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        req = one(db, 'requirements', body.requirement_id)
        if req['bid_id'] != bid_id or req['id'] not in {r['id'] for r in engine.active_requirements(db, bid_id)}:
            raise HTTPException(422, 'Answer a current requirement from this bid.')
        if body.supersedes:
            old = one(db, 'evidence', body.supersedes)
            if old['company_id'] != bid['company_id'] or old['bid_id'] not in (None,bid_id):
                raise HTTPException(422, 'Cannot replace evidence from another company or bid.')
            if db.execute('SELECT 1 FROM evidence WHERE supersedes=? AND approved=1', (old['id'],)).fetchone():
                raise HTTPException(409, 'Replace the current evidence version only.')
        if body.attachment_document_id:
            attachment = one(db, 'documents', body.attachment_document_id)
            if attachment['bid_id'] != bid_id or attachment['kind'] != 'response_attachment':
                raise HTTPException(422, 'Select an actual response attachment from this bid.')
        ident = uid('EVD')
        insert(db, 'evidence', id=ident, company_id=bid['company_id'], bid_id=bid_id, document_id=body.attachment_document_id,
            locator=f'Customer answer by {body.customer_name}', quote=body.text, statement=body.text,
            kind=req['kind'], fact_key=(body.fact_key or req['key']).lower(), source_type='client',
            verified=1, approved=1, customer_name=body.customer_name, supersedes=body.supersedes, created_at=now())
        insert(db, 'answers', id=uid('ANS'), bid_id=bid_id, requirement_id=req['id'], evidence_id=ident,
            customer_name=body.customer_name, text=body.text, created_at=now())
        db.execute('INSERT INTO mappings VALUES(?,?,0,?)', (req['id'], ident, 'Customer answer. Confirm requirement coverage.'))
        # A correction to reusable company evidence invalidates every affected bid.
        if body.supersedes:
            invalidate_company(db, bid['company_id'])
        else:
            invalidate(db, bid_id)
        event(db, bid_id, 'CUSTOMER_ANSWER', body.customer_name, encode({'evidence_id': ident, 'requirement_id': req['id']}))
        return {'evidence_id': ident}


@app.post('/api/bids/{bid_id}/qualify', dependencies=[Depends(authenticate)])
def qualify(bid_id: str):
    with transaction() as db:
        return rules.qualification(db, bid_id)


@app.post('/api/bids/{bid_id}/generate', dependencies=[Depends(authenticate)])
def generate(bid_id: str):
    with transaction() as db:
        return {'sections': engine.generate(db, bid_id)}


@app.post('/api/bids/{bid_id}/audit', dependencies=[Depends(authenticate)])
def audit(bid_id: str, body: AuditInput):
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        if body.expected_revision != bid['revision']:
            raise HTTPException(409, 'The bid changed or the reviewed revision is missing. Reload before auditing.')
        if bid['draft_revision'] != bid['revision']:
            raise HTTPException(409, 'Generate a current draft before the independent audit.')
        db.execute("UPDATE bids SET state='AUDITING',approved_revision=NULL WHERE id=?", (bid_id,))
        issues = rules.blockers(db, bid_id)
        for note in body.findings:
            issues.append(rules.finding('RED-TEAM', note, 'Resolve this finding and run a new audit.'))
        if body.mode == 'ai':
            try:
                _, _, rendered_pages = render_proposal(render_input(db, bid))
            except (RuntimeError, OSError, TimeoutError) as exc:
                raise HTTPException(503, 'Restore the document renderer before AI audit.') from exc
            payload = {'source_documents': rows(db, "SELECT name,sequence,pages FROM documents WHERE bid_id=? AND kind!='response_attachment'", (bid_id,)),
                       'response_attachments': rows(db, "SELECT id,name,sha256,pages,warnings FROM documents WHERE bid_id=? AND kind='response_attachment'", (bid_id,)),
                       'company_sources': rows(db, 'SELECT id,name,pages FROM documents WHERE company_id=? AND bid_id IS NULL', (bid['company_id'],)),
                       'rendered_proposal_pages': rendered_pages,
                       'export_behavior': 'The export includes every listed response_attachment as a separate original file. Submission controls appear in the separate internal checklist.',
                       'requirements': engine.active_requirements(db, bid_id), 'proposal': engine.draft_sections(db, bid),
                       'evidence': engine.evidence_for(db, bid), 'controls': json.loads(bid['controls'])}
            result = ai.ask('You are the independent red-team reviewer. You did not write the proposal. '
                'Compare the ORIGINAL sources, all amendments, every mandatory obligation, evidence and finished draft. '
                'Find omissions in extraction, compound requirements, insufficient references, invented claims, '
                'unsupported certification, wrong prices, missing signed forms and contradictions. Do not improve prose. '
                'Report only defects tied to source obligations or unsupported factual claims. Do not invent federal requirements. '
                'Deadline, delivery method and page limit are operational controls, not required narrative attestations unless the source says so. '
                'Compare the actual rendered page count to the source limit. Do not infer missing sections from nonconsecutive position numbers. '
                'Check linked response attachments using their IDs. Require signatures only where the sources require signatures. '
                'A named customer answer is traceable evidence, not independent verification; require additional documentary proof only when '
                'the source requires it or the supplied evidence is conflicting or explicitly unverified. '
                'Return {"findings":[{"finding":"specific issue","action":"specific correction","requirement_id":null}]}. '
                'Use an empty list only if you found no issues. Findings are blocking pending correction.', payload, purpose='audit')
            if not isinstance(result.get('findings'), list):
                raise HTTPException(422, 'The independent AI audit returned no valid findings list.')
            for f in result['findings']:
                if not isinstance(f, dict) or not isinstance(f.get('finding'), str) or not f['finding'].strip():
                    raise HTTPException(422, 'The independent AI audit returned an invalid finding.')
                issues.append(rules.finding('RED-TEAM', f['finding'], str(f.get('action','Resolve and audit again.')), f.get('requirement_id')))
        run = uid('AUD')
        insert(db, 'audit_runs', id=run, bid_id=bid_id, revision=bid['revision'], content_hash=engine.draft_hash(db, bid),
            reviewer=body.reviewer, mode=body.mode, notes=body.reason, status='FAILED' if issues else 'PASSED', created_at=now())
        for f in issues:
            insert(db, 'audit_findings', id=uid('FND'), run_id=run, **f)
        db.execute('UPDATE bids SET state=? WHERE id=?', ('NEEDS_REVISION' if issues else 'DRAFTED', bid_id))
        event(db, bid_id, 'INDEPENDENT_AUDIT', body.reviewer, body.reason, body.duration_seconds)
        return {'run_id': run, 'status': 'FAILED' if issues else 'PASSED', 'findings': issues}


@app.post('/api/bids/{bid_id}/approve', dependencies=[Depends(authenticate)])
def approve(bid_id: str, body: ReviewInput):
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        if body.expected_revision != bid['revision']:
            raise HTTPException(409, 'The bid changed or the reviewed revision is missing. Reload before approval.')
        issues = rules.blockers(db, bid_id, include_audit=True)
        if issues:
            raise HTTPException(409, {'message': 'Final approval is blocked.', 'blockers': issues})
        db.execute("UPDATE bids SET approved_revision=revision,state='APPROVED' WHERE id=?", (bid_id,))
        event(db, bid_id, 'FINAL_APPROVAL', body.reviewer, body.reason, body.duration_seconds)
        db.execute("UPDATE bids SET state='SUBMISSION_READY' WHERE id=?", (bid_id,))
        return {'state': 'SUBMISSION_READY'}


@app.post('/api/findings/{finding_id}/resolve', dependencies=[Depends(authenticate)])
def resolve_finding(finding_id: str, body: ReviewInput):
    with transaction() as db:
        f = one(db, 'audit_findings', finding_id)
        run = one(db, 'audit_runs', f['run_id'])
        bid = one(db, 'bids', run['bid_id'])
        if f['rule_id'] != 'RED-TEAM':
            raise HTTPException(422, 'Deterministic findings clear only when the underlying condition is corrected.')
        if bid['revision'] <= run['revision']:
            raise HTTPException(409, 'Correct the source, evidence or settings before resolving this finding.')
        db.execute('''UPDATE audit_findings SET resolved_revision=?,resolution=?,resolved_by=?
            WHERE rule_id='RED-TEAM' AND finding=? AND run_id IN (SELECT id FROM audit_runs WHERE bid_id=?)''',
            (bid['revision'],body.reason,body.reviewer,f['finding'],bid['id']))
        event(db,bid['id'],'RED_TEAM_RESOLUTION',body.reviewer,body.reason,body.duration_seconds)
        return {'resolved': True, 'next': 'Run a new independent audit.'}


@app.post('/api/bids/{bid_id}/export', dependencies=[Depends(authenticate)])
def export(bid_id: str, body: ExportInput):
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        issues = rules.blockers(db, bid_id, include_audit=body.final)
        if body.final and (issues or bid['approved_revision'] != bid['revision']):
            raise HTTPException(409, {'message': 'Final export requires zero blockers and current human approval.', 'blockers': issues})
        if bid['draft_revision'] is None:
            raise HTTPException(409, 'Generate a draft before export.')
        try:
            binary = package(db, bid, body.final, issues)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(503, str(exc)) from exc
        # Rendering can cross a deadline. Recheck time and all rules before delivery.
        if body.final:
            issues = rules.blockers(db, bid_id, include_audit=True)
            if issues:
                raise HTTPException(409, {'message': 'The bid became blocked during export.', 'blockers': issues})
        insert(db, 'exports', id=uid('EXP'), bid_id=bid_id, revision=bid['revision'],
            content_hash=engine.draft_hash(db, bid), final=int(body.final), sha256=sha(binary), created_at=now())
        return StreamingResponse(io.BytesIO(binary), media_type='application/zip',
            headers={'Content-Disposition': f'attachment; filename="{bid_id}-{"FINAL" if body.final else "DRAFT"}.zip"'})


@app.get('/api/bids/{bid_id}/preview.pdf', dependencies=[Depends(authenticate)])
def preview(bid_id: str):
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        if bid['draft_revision'] is None:
            raise HTTPException(409, 'Generate a draft first.')
        try:
            _, pdf, _ = render_proposal(render_input(db, bid), draft=True)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(503, str(exc)) from exc
        return StreamingResponse(io.BytesIO(pdf), media_type='application/pdf', headers={'Content-Disposition': 'inline; filename="Draft.pdf"'})


@app.get('/api/bids/{bid_id}', dependencies=[Depends(authenticate)])
def get_bid(bid_id: str):
    with transaction() as db:
        bid = one(db, 'bids', bid_id)
        ev = engine.evidence_for(db, bid)
        reqs = engine.active_requirements(db, bid_id)
        for r in reqs:
            r['status'], approved = engine.requirement_status(db, bid, r, ev)
            r['mappings'] = rows(db, 'SELECT * FROM mappings WHERE requirement_id=?', (r['id'],))
        issues = rules.blockers(db, bid_id, include_audit=True)
        ready = not issues and bid['approved_revision'] == bid['revision']
        if ready:
            state = 'SUBMISSION_READY'
        elif bid['state'] in ('SUBMISSION_READY','APPROVED'):
            state = 'NEEDS_REVISION'
        elif bid['draft_revision'] is not None and bid['draft_revision'] != bid['revision']:
            state = 'NEEDS_REVISION'
        elif bid['draft_revision'] is None and reqs:
            state = 'AWAITING_CLIENT_INPUT' if rules.blockers(db, bid_id, include_draft=False) else 'READY_TO_DRAFT'
        else:
            state = bid['state']
        if state != bid['state']:
            db.execute('UPDATE bids SET state=? WHERE id=?', (state,bid_id))
            bid['state'] = state
        q = engine.questions(db, bid_id)
        audits = rows(db, 'SELECT * FROM audit_runs WHERE bid_id=? ORDER BY rowid DESC', (bid_id,))
        return {'bid': bid, 'company': one(db,'companies',bid['company_id']), 'requirements': reqs,
                'ledger': rows(db, 'SELECT * FROM requirements WHERE bid_id=? ORDER BY created_at', (bid_id,)),
                'documents': rows(db, 'SELECT id,name,kind,sequence,sha256,pages,warnings,extracted,reviewed,acknowledged FROM documents WHERE bid_id=? ORDER BY sequence,created_at', (bid_id,)),
                'evidence': ev, 'conflicts': engine.conflicts(ev), 'questions': q,
                'qualification': rules.qualification(db,bid_id), 'blockers': issues,
                'draft': engine.draft_sections(db,bid), 'audits': audits,
                'audit_findings': rows(db,'SELECT f.* FROM audit_findings f JOIN audit_runs a ON a.id=f.run_id WHERE a.bid_id=? ORDER BY a.rowid DESC', (bid_id,)),
                'ready': ready, 'can_generate': not rules.blockers(db,bid_id,include_draft=False),
                'review_events': rows(db,'SELECT * FROM review_events WHERE bid_id=? ORDER BY created_at DESC', (bid_id,))}
