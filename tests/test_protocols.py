import asyncio
import time

import httpx

from maintainer.db import Usage
from maintainer.providers import OpenAICompatible
from maintainer.sandboxes import ShipyardConnection
from test_foundation import app, client


def test_validation_does_not_reflect_input(client):
    response = client.post('/api/providers', json={'name': 'x', 'base_url': 'https://user:plaintext@example.com', 'api_key': {'secret': 'plaintext'}})
    assert response.status_code == 422
    assert 'plaintext' not in response.text


def test_openai_wire_protocol():
    seen = []
    def handle(request):
        seen.append(request)
        assert request.headers['Authorization'] == 'Bearer fixture'
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'test'}]})
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}], 'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}})
    provider = OpenAICompatible('https://example.com/v1', 'fixture')
    provider.client = lambda timeout=15: httpx.AsyncClient(base_url='https://example.com/v1/', headers={'Authorization': 'Bearer fixture'}, transport=httpx.MockTransport(handle))
    assert asyncio.run(provider.models()) == ['test']
    result = asyncio.run(provider.complete('test', 'system', 'prompt', 5))
    assert result.total_tokens == 5 and result.usage_reported
    assert [r.url.path for r in seen] == ['/v1/models', '/v1/chat/completions']


def test_shipyard_probe_validates_schema(monkeypatch):
    original = httpx.AsyncClient
    def handle(request):
        assert request.url.path == '/v1/sandboxes'
        assert request.headers['Authorization'] == 'Bearer fixture'
        assert request.url.params['limit'] == '1'
        return httpx.Response(200, json={'items': [], 'next_cursor': None})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    assert asyncio.run(ShipyardConnection().test('https://sandbox.example', 'fixture'))['ok']


def test_token_windows(client, app):
    with app.state.sessions.begin() as db:
        for age, total in [(0, 1), (2, 10), (10, 100), (40, 1000)]:
            db.add(Usage(run_id='fixture', timestamp=time.time() - age*86400, data={'provider': 'provider', 'model': 'model', 'total_tokens': total}))
    windows = client.get('/api/dashboard').json()['tokens']
    assert [windows[w]['total'] for w in ['24h', '7d', '30d']] == [1, 11, 111]
