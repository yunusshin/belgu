import json

import httpx


def test_settings_api_persists_masks_and_clear_key(api):
    response = api.patch('/api/settings', json={'llm': {'openai': {'model_id': 'test-model', 'api_key': 'private-openai-key'}},
                                               'sources': {'mnemonic': {'api_key': 'private-dns-key'}}})
    assert response.status_code == 200
    assert 'private-' not in response.text
    assert response.json()['llm']['openai']['key_configured']
    assert api.get('/api/settings').json()['sources']['mnemonic']['key_configured']
    assert api.patch('/api/settings', json={'sources': {'mnemonic': {'api_key': ''}}}).json()['sources']['mnemonic']['key_configured']
    assert not api.patch('/api/settings', json={'sources': {'mnemonic': {'clear_key': True}}}).json()['sources']['mnemonic']['key_configured']


def test_draft_connection_test_does_not_save_or_send_case_contents(api, monkeypatch):
    seen = []
    real_client = httpx.Client
    def upstream(request):
        assert request.headers['authorization'] == 'Bearer draft-secret'
        seen.append(request)
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'test-model'}]})
        if request.url.path == '/v1/responses/input_tokens':
            return httpx.Response(200, json={'input_tokens': 20})
        return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(**{**kwargs, 'transport': httpx.MockTransport(upstream)}))
    result = api.post('/api/settings/llm/test', json={'provider': 'openai', 'settings': {'model_id': 'test-model', 'api_key': 'draft-secret'}})
    assert result.status_code == 200
    assert result.json()['status'] == 'ok'
    assert [r.url.path for r in seen] == ['/v1/models', '/v1/responses/input_tokens', '/v1/responses']
    assert all('evidence' not in r.content.decode() for r in seen)
    assert not api.get('/api/settings').json()['llm']['openai']['key_configured']


def test_saved_connection_reaches_health_without_restart(api, monkeypatch):
    real_client = httpx.Client
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={'data': [{'id': 'test-model'}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(**{**kwargs, 'transport': httpx.MockTransport(upstream)}))
    api.patch('/api/settings', json={'active_llm': 'openai', 'llm': {'openai': {'model_id': 'test-model', 'api_key': 'saved-secret'}}})
    health = api.get('/api/health').json()
    assert health['model']['model_id'] == 'test-model'
    assert seen[0].url.host == 'api.openai.com'
    assert seen[0].headers['authorization'] == 'Bearer saved-secret'


def test_api_rejects_bad_fields_without_echoing_secrets(api):
    result = api.patch('/api/settings', json={'llm': {'local': {'base_url': 'http://user:secret@localhost/v1'}}})
    assert result.status_code == 422
    assert 'user:secret' not in result.text
