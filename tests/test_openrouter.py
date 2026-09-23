import json
import httpx
import pytest
from fastapi import HTTPException
from app import ai


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-secret-not-a-real-key')
    monkeypatch.setenv('AI_MODEL', 'analysis-model')
    monkeypatch.setenv('AI_AUDIT_MODEL', 'review-model')
    calls = []
    real_client = httpx.Client
    def install(body, status=200):
        def respond(request):
            calls.append(request)
            return httpx.Response(status, json=body)
        monkeypatch.setattr(ai.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    return calls, install


def response(content='{"findings": []}', finish='stop'):
    return {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}


def test_routing_keeps_secret_server_side_and_uses_separate_audit_model(router):
    calls, install = router
    install(response())
    assert ai.available()
    assert ai.ask('Extract JSON', {'text': 'Source'}) == {'findings': []}
    ai.ask('Review JSON', {'text': 'Source'}, purpose='audit')
    first, second = [json.loads(r.content) for r in calls]
    assert str(calls[0].url) == 'https://openrouter.ai/api/v1/chat/completions'
    assert calls[0].headers['Authorization'] == 'Bearer test-secret-not-a-real-key'
    assert 'test-secret' not in calls[0].content.decode()
    assert first['model'] == 'analysis-model' and second['model'] == 'review-model'
    assert first['provider'] == {'require_parameters': True, 'data_collection': 'deny', 'zdr': True}
    assert len(first['messages']) == len(second['messages']) == 2
    assert second['messages'][1]['content'] == json.dumps({'source_data': {'text': 'Source'}})


@pytest.mark.parametrize('body', [response(finish='length'), response(finish='content_filter'),
    response('not json'), response('[]'), response(None), {'choices': []},
    {'choices': [{'finish_reason': 'stop', 'message': {'refusal': 'No', 'content': '{}'}}]},
    {'error': {'message': 'test-secret-not-a-real-key'}}])
def test_incomplete_or_malformed_response_fails_closed(router, body):
    _, install = router
    install(body)
    with pytest.raises(HTTPException) as exc:
        ai.ask('Return JSON', {})
    assert exc.value.status_code == 502
    assert 'test-secret' not in exc.value.detail


def test_insufficient_credit_never_falls_back_to_offline(router):
    _, install = router
    install({'error': {'message': 'secret response'}}, status=402)
    with pytest.raises(HTTPException) as exc:
        ai.ask('Return JSON', {})
    assert exc.value.status_code == 502 and 'secret response' not in exc.value.detail


def test_missing_output_field_is_not_treated_as_empty_extraction(router):
    _, install = router
    install(response('{}'))
    with pytest.raises(HTTPException) as exc:
        ai.extract_requirements({'pages': '[{"number":1,"text":"Offeror must provide its UEI."}]'})
    assert exc.value.status_code == 422


def test_missing_key_fails_without_network(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openrouter')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    assert not ai.available()
    with pytest.raises(HTTPException) as exc:
        ai.ask('Return JSON', {})
    assert exc.value.status_code == 503


def test_model_cannot_drop_an_explicit_price_sheet_constraint(client, monkeypatch):
    from conftest import post, upload, state
    co = post(client, '/companies', {'name': 'Price sheet test'})['id']
    bid = post(client, '/bids', {'company_id': co, 'title': 'Explicit attachment'})['id']
    upload(client, f'/bids/{bid}/documents', 'source.txt', b'Offeror must provide a completed price sheet.', kind='solicitation')
    monkeypatch.setattr(ai, 'extract_requirements', lambda doc: [dict(page=1,
        quote='Offeror must provide a completed price sheet.', text='Provide a completed price sheet.',
        kind='pricing', key='price', constraints={})])
    post(client, f'/bids/{bid}/extract')
    assert json.loads(state(client, bid)['requirements'][0]['constraints'])['attachment'] is True


def test_model_cannot_misclassify_explicit_uei_as_eligibility(client, monkeypatch):
    from conftest import post, upload, state
    co = post(client, '/companies', {'name': 'UEI type test'})['id']
    bid = post(client, '/bids', {'company_id': co, 'title': 'Explicit UEI'})['id']
    upload(client, f'/bids/{bid}/documents', 'source.txt', b'Offeror must provide its UEI.', kind='solicitation')
    monkeypatch.setattr(ai, 'extract_requirements', lambda doc: [dict(page=1,
        quote='Offeror must provide its UEI.', text='Offeror must provide its UEI.',
        kind='eligibility', key='uei', constraints={})])
    post(client, f'/bids/{bid}/extract')
    req = state(client, bid)['requirements'][0]
    assert req['kind'] == 'administrative'
    assert json.loads(req['constraints'])['uei'] is True
