"""Create one clearly labelled fictional demo through the public API. Never reset data."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app

ROOT=Path(__file__).resolve().parents[1]


def main():
    with TestClient(app) as client:
        existing=client.get('/api/workspace').json()
        if any(b['title']=='Field office janitorial services (Demo)' for b in existing['bids']):
            print('The fictional demo already exists. No data changed.')
            return
        def post(path,body=None):
            r=client.post('/api'+path,json=body or {})
            r.raise_for_status()
            return r.json()
        def upload(path,name,data,extra=None):
            r=client.post('/api'+path,files={'file':(name,data)},data=extra or {})
            r.raise_for_status()
            return r.json()
        co=post('/companies',{'name':'Example Services (Fictional demo)'})['id']
        bid=post('/bids',{'company_id':co,'title':'Field office janitorial services (Demo)'})['id']
        source=upload(f'/bids/{bid}/documents','simple-rfq.txt',(ROOT/'fixtures/simple-rfq.txt').read_bytes(),{'kind':'solicitation','sequence':'0'})['id']
        post(f'/bids/{bid}/extract')
        text=(ROOT/'fixtures/company.txt').read_text()
        text='\n'.join(line for line in text.splitlines() if not line.startswith(('UEI:', 'Reference 3:')))
        upload(f'/companies/{co}/documents','demo-company-profile.txt',text.encode())
        post(f'/companies/{co}/extract')
        review={'reviewer':'Fictional demo setup','reason':'Synthetic fixture only. This is not real contractor verification.'}
        ev=client.get('/api/companies/'+co).json()['evidence']
        for e in ev:
            post(f"/evidence/{e['id']}/review",{**review,'approved':True})
        post(f'/documents/{source}/review',review)
        data=client.get('/api/bids/'+bid).json()
        by_kind={r['kind']:r for r in data['requirements']}
        post(f'/bids/{bid}/controls',{**review,'deadline':'2027-11-30T17:00:00-05:00',
            'deadline_requirement_id':by_kind['deadline']['id'],'page_limit':25,
            'page_limit_requirement_id':by_kind['page_limit']['id'],'submission_method':'Email to bids@example.gov (fictional)',
            'submission_requirement_id':by_kind['submission']['id'],'scope_confirmed':True,'package_complete':True})
        for req in data['requirements']:
            ids=[e['id'] for e in ev if e['kind']==req['kind']]
            if ids:
                post(f"/requirements/{req['id']}/mapping",{**review,'evidence_ids':ids})
        print('Created a fictional demo with missing UEI, pricing and one reference.')
        print('Open http://127.0.0.1:8765/bids/'+bid)


if __name__=='__main__':
    main()
