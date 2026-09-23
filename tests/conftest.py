import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import app

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures'
REVIEW = {'reviewer':'Test reviewer', 'reason':'Checked the original source and complete requirement.', 'duration_seconds':12}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('BID_FACTORY_DB', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('AI_PROVIDER', 'offline')
    monkeypatch.setenv('APP_MODE', 'local')
    monkeypatch.delenv('APP_PASSWORD', raising=False)
    with TestClient(app) as c:
        yield c


def post(c,path,body=None):
    if path.endswith(('/audit','/approve')) and body is not None and 'expected_revision' not in body:
        body={**body,'expected_revision':c.get('/api'+path.rsplit('/',1)[0]).json()['bid']['revision']}
    r=c.post('/api'+path,json=body if body is not None else {})
    assert r.status_code==200, r.text
    return r.json()


def upload(c,path,name,data=None,kind=None,sequence=0):
    r=c.post('/api'+path, files={'file':(name,data if data is not None else (FIXTURES/name).read_bytes())},
             data={'kind':kind,'sequence':str(sequence)} if kind else {})
    assert r.status_code==200,r.text
    return r.json()


def base(c):
    co=post(c,'/companies',{'name':'Example Services'})['id']
    bid=post(c,'/bids',{'company_id':co,'title':'Synthetic janitorial RFQ'})['id']
    source=upload(c,f'/bids/{bid}/documents','simple-rfq.txt',kind='solicitation')['id']
    post(c,f'/bids/{bid}/extract')
    return co,bid,source


def state(c,bid):
    r=c.get('/api/bids/'+bid)
    assert r.status_code==200,r.text
    return r.json()


def prepared(c):
    co,bid,source=base(c)
    upload(c,f'/companies/{co}/documents','company.txt')
    post(c,f'/companies/{co}/extract')
    ev=c.get('/api/companies/'+co).json()['evidence']
    for e in ev:
        post(c,f"/evidence/{e['id']}/review",{**REVIEW,'approved':True})
    attachment=upload(c,f'/bids/{bid}/documents','price-sheet.txt',kind='response_attachment')['id']
    post(c,f'/documents/{source}/review',REVIEW)
    data=state(c,bid)
    by_kind={r['kind']:r for r in data['requirements']}
    assert len(by_kind)==8,data['requirements']
    post(c,f'/bids/{bid}/controls',{**REVIEW,'deadline':'2027-11-30T17:00:00-05:00',
        'deadline_requirement_id':by_kind['deadline']['id'],'page_limit':25,
        'page_limit_requirement_id':by_kind['page_limit']['id'],'submission_method':'Email to bids@example.gov',
        'submission_requirement_id':by_kind['submission']['id'],'scope_confirmed':True,'package_complete':True})
    answer=post(c,f'/bids/{bid}/answers',{'requirement_id':by_kind['pricing']['id'],
        'text':'Example Services offers the required services for $1200 per month for 12 months, total $14400.',
        'customer_name':'Taylor Example','confirmed':True,'attachment_document_id':attachment})
    for req in data['requirements']:
        if req['kind'] in ('deadline','page_limit','submission'):
            continue
        ids=[e['id'] for e in ev if e['kind']==req['kind']]
        if req['kind']=='pricing':
            ids=[answer['evidence_id']]
        post(c,f"/requirements/{req['id']}/mapping",{**REVIEW,'evidence_ids':ids,'approved':True})
    assert state(c,bid)['can_generate'],state(c,bid)['blockers']
    return co,bid,source


def ready(c):
    co,bid,source=prepared(c)
    post(c,f'/bids/{bid}/generate')
    result=post(c,f'/bids/{bid}/audit',{**REVIEW,'mode':'human','independent_review_complete':True})
    assert result['status']=='PASSED',result
    post(c,f'/bids/{bid}/approve',REVIEW)
    return co,bid,source
