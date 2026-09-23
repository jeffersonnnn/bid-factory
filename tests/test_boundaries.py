import io
import json
import sqlite3
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from reportlab.pdfgen import canvas
from app import ai, engine
from app.db import transaction
from app.documents import parse
from conftest import post, upload, base, prepared, ready, state, REVIEW


def test_one_reference_cannot_disappear_from_finished_draft(client):
    _,bid,_=prepared(client)
    post(client,f'/bids/{bid}/generate')
    with transaction() as db:
        db.execute('''DELETE FROM proposal_claims WHERE id=(SELECT c.id FROM proposal_claims c
            JOIN proposal_sections s ON s.id=c.section_id JOIN requirements r ON r.id=s.requirement_id
            WHERE r.kind='past_performance' LIMIT 1)''')
    assert any('mapped evidence is missing' in b['finding'] for b in state(client,bid)['blockers'])


def test_expired_evidence_is_not_eligible(client):
    _,bid,_=prepared(client)
    data=state(client,bid)
    ev=next(e for e in data['evidence'] if e['kind']=='eligibility')
    post(client,f"/evidence/{ev['id']}/review",{**REVIEW,'approved':True,'expires_at':'2020-01-01T00:00:00+00:00'})
    assert state(client,bid)['qualification']['status']=='NO-GO'


def test_clock_expiry_revokes_ready_without_an_edit(client,monkeypatch):
    _,bid,_=ready(client)
    from datetime import datetime,timezone
    class Later(datetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2028,1,1,tzinfo=timezone.utc)
    monkeypatch.setattr('app.rules.datetime',Later)
    assert not state(client,bid)['ready']
    assert client.post(f'/api/bids/{bid}/export',json={'final':True}).status_code==409


def test_page_limit_uses_the_rendered_page_count(client):
    _,bid,_=prepared(client)
    data=state(client,bid)
    controls=json.loads(data['bid']['controls'])
    del controls['source_signature']
    controls['page_limit']=1
    post(client,f'/bids/{bid}/controls',controls)
    tech=next(r for r in data['requirements'] if r['kind']=='technical')
    e=post(client,f'/bids/{bid}/answers',{'requirement_id':tech['id'],
        'text':('We will follow the approved cleaning schedule and document completed tasks. '*100),
        'fact_key':'long_technical_response','customer_name':'Synthetic customer','confirmed':True})
    post(client,f"/requirements/{tech['id']}/mapping",{**REVIEW,'evidence_ids':[e['evidence_id']]})
    post(client,f'/bids/{bid}/generate')
    data=state(client,bid)
    assert any(f['rule_id']=='RULE-006' and 'rendered proposal' in f['finding'] for f in data['blockers'])


def test_blank_scanned_source_rejected_but_signed_attachment_preserved(client):
    co,bid,_=base(client)
    f=io.BytesIO();c=canvas.Canvas(f);c.rect(50,50,100,100);c.showPage();c.save()
    result=client.post(f'/api/bids/{bid}/documents',files={'file':('scan.pdf',f.getvalue())},data={'kind':'solicitation','sequence':0})
    assert result.status_code==422
    result=client.post(f'/api/bids/{bid}/documents',files={'file':('signed-scan.pdf',f.getvalue())},data={'kind':'response_attachment','sequence':0})
    assert result.status_code==200


def test_ai_invented_source_quote_rolls_back_the_entire_step(client,monkeypatch):
    co=post(client,'/companies',{'name':'AI extraction test'})['id']
    bid=post(client,'/bids',{'title':'AI output validation','company_id':co})['id']
    upload(client,f'/bids/{bid}/documents','source.txt',b'Offeror must provide its UEI.',kind='solicitation')
    monkeypatch.setattr(ai,'extract_requirements',lambda doc:[
        {'page':1,'quote':'Offeror must provide its UEI.','text':'Provide UEI','kind':'administrative','key':'uei'},
        {'page':1,'quote':'Made up certification requirement.','text':'Made up','kind':'certification','key':'fake'}])
    r=client.post(f'/api/bids/{bid}/extract',json={})
    assert r.status_code==422
    assert not state(client,bid)['ledger']


def test_ai_review_uses_original_sources_in_a_separate_context(client,monkeypatch):
    _,bid,_=prepared(client)
    post(client,f'/bids/{bid}/generate')
    calls=[]
    def fake(task,payload):
        calls.append((task,payload))
        return {'findings':[{'finding':'Reference comparability needs a reviewer check.','action':'Verify reference scope.','requirement_id':None}]}
    monkeypatch.setattr(ai,'ask',fake)
    result=post(client,f'/bids/{bid}/audit',{**REVIEW,'mode':'ai','independent_review_complete':True})
    assert result['status']=='FAILED'
    assert len(calls)==1 and 'independent red-team reviewer' in calls[0][0]
    assert {'source_documents','proposal','requirements','evidence'}<=set(calls[0][1])
    assert 'messages' not in calls[0][1]


def test_malformed_ai_audit_does_not_create_passed_run(client,monkeypatch):
    _,bid,_=prepared(client)
    post(client,f'/bids/{bid}/generate')
    monkeypatch.setattr(ai,'ask',lambda *args:{'score':100})
    r=client.post(f'/api/bids/{bid}/audit',json={**REVIEW,'expected_revision':state(client,bid)['bid']['revision'],'mode':'ai','independent_review_complete':True})
    assert r.status_code==422
    assert state(client,bid)['audits']==[]


def test_correction_invalidates_all_bids_using_shared_company_evidence(client):
    co,bid,_=prepared(client)
    other=post(client,'/bids',{'title':'Another bid','company_id':co})['id']
    before=state(client,other)['bid']['revision']
    e=state(client,bid)['evidence'][0]
    post(client,f"/evidence/{e['id']}/review",{**REVIEW,'approved':False})
    assert state(client,other)['bid']['revision']>before


def test_render_failure_is_a_blocker_not_a_false_pass(client,monkeypatch):
    _,bid,_=prepared(client)
    post(client,f'/bids/{bid}/generate')
    def fail(*args,**kwargs):
        raise RuntimeError('Renderer unavailable for test.')
    monkeypatch.setattr('app.render.render_proposal',fail)
    assert any(f['rule_id']=='RULE-006' for f in state(client,bid)['blockers'])


def test_source_bytes_and_page_anchors_cannot_be_changed(client):
    _,_,source=base(client)
    with transaction() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE documents SET pages=? WHERE id=?',('[]',source))


def test_naive_deadline_is_rejected(client):
    _,bid,_=prepared(client)
    controls=json.loads(state(client,bid)['bid']['controls'])
    del controls['source_signature']
    controls['deadline']='2027-11-30T17:00:00'
    assert client.post(f'/api/bids/{bid}/controls',json=controls).status_code==422


def test_stale_browser_revision_cannot_approve_an_unseen_draft(client):
    _,bid,_=ready(client)
    revision=state(client,bid)['bid']['revision']
    r=client.post(f'/api/bids/{bid}/approve',json={**REVIEW,'expected_revision':revision-1})
    assert r.status_code==409
    r=client.post(f'/api/bids/{bid}/audit',json={**REVIEW,'expected_revision':revision-1,'mode':'human','independent_review_complete':True})
    assert r.status_code==409
