import json
import stat

import httpx
import pytest

from belgu.integrations import IntegrationStore
from belgu.analysis.client import ModelClient, ModelClientError


def test_settings_preserve_secrets_across_partial_edits_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('BELGU_URLSCAN_KEY', 'environment-secret')
    path = tmp_path / 'integrations.json'
    store = IntegrationStore(path)
    store.update({'llm': {'openai': {'api_key': 'private-key', 'model_id': 'test-model'}}})
    store.update({'active_llm': 'openai', 'llm': {'openai': {'api_key': '', 'timeout_seconds': 45}}})
    reopened = IntegrationStore(path)
    assert reopened.connection()['api_key'] == 'private-key'
    assert reopened.connection()['timeout_seconds'] == 45
    public = reopened.public()
    assert public['llm']['openai']['key_configured'] is True
    assert 'private-key' not in json.dumps(public)
    assert 'environment-secret' not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    reopened.update({'llm': {'openai': {'clear_key': True}}})
    assert reopened.connection()['api_key'] == ''
    reopened.update({'sources': {'urlscan': {'clear_key': True}}})
    assert reopened.snapshot()['sources']['urlscan']['api_key'] == ''


def test_invalid_settings_do_not_overwrite_working_configuration(tmp_path):
    store = IntegrationStore(tmp_path / 'integrations.json')
    store.update({'llm': {'local': {'model_id': 'working'}}})
    for patch in [
        {'active_llm': 'unknown'},
        {'llm': {'local': {'base_url': 'http://user:secret@localhost:30000/v1'}}},
        {'llm': {'local': {'base_url': 'https://example.com/v1?key=secret'}}},
        {'sources': {'mnemonic': {'unknown_field': 'ignored?'}}},
        {'llm': {'openai': {'base_url': 'http://different.example'}}},
    ]:
        with pytest.raises(ValueError):
            store.update(patch)
    assert store.connection()['model_id'] == 'working'


@pytest.mark.parametrize('backend,base,auth,path,response', [
    ('openai', 'https://api.openai.com/v1', 'authorization', '/v1/responses',
     {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}], 'usage': {'input_tokens': 23, 'output_tokens': 5}}),
    ('anthropic', 'https://api.anthropic.com/v1', 'x-api-key', '/v1/messages',
     {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{"ok":true}'}], 'usage': {'input_tokens': 23, 'output_tokens': 5}}),
    ('gemini', 'https://generativelanguage.googleapis.com/v1beta', 'x-goog-api-key', '/v1beta/models/test-model:generateContent',
     {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"ok":true}'}]}}], 'usageMetadata': {'promptTokenCount': 23, 'candidatesTokenCount': 5}}),
    ('openrouter', 'https://openrouter.ai/api/v1', 'authorization', '/api/v1/chat/completions',
     {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}], 'usage': {'prompt_tokens': 23, 'completion_tokens': 5}}),
])
def test_native_llm_requests_and_usage(backend, base, auth, path, response):
    def upstream(request):
        assert request.url.path == path
        assert 'provider-secret' in request.headers[auth]
        assert 'provider-secret' not in str(request.url)
        body = json.loads(request.content)
        assert 'chat_template_kwargs' not in body
        assert 'reasoning_format' not in body
        if backend == 'openai':
            assert body['store'] is False
            assert body['text']['format']['type'] == 'json_schema'
        elif backend == 'anthropic':
            assert request.headers['anthropic-version'] == '2023-06-01'
            assert body['system'] == 'system instruction'
            assert 'maxLength' not in body['output_config']['format']['schema']['properties']['ok']
        elif backend == 'gemini':
            assert body['systemInstruction']['parts'][0]['text'] == 'system instruction'
            assert body['generationConfig']['responseMimeType'] == 'application/json'
        else:
            assert body['provider']['require_parameters'] is True
        return httpx.Response(200, json=response)
    client = ModelClient(base, 'test-model', backend=backend, api_key='provider-secret', transport=httpx.MockTransport(upstream))
    try:
        completion = client.complete([{'role': 'system', 'content': 'system instruction'}, {'role': 'user', 'content': 'test'}],
            {'type': 'object', 'properties': {'ok': {'type': 'string', 'maxLength': 12}}, 'required': ['ok'], 'additionalProperties': False})
        assert completion.text == '{"ok":true}'
        assert (completion.input_tokens, completion.output_tokens) == (23, 5)
    finally:
        client.close()


@pytest.mark.parametrize('backend,path,reply', [
    ('openai', '/v1/responses/input_tokens', {'input_tokens': 12}),
    ('anthropic', '/v1/messages/count_tokens', {'input_tokens': 12}),
    ('gemini', '/v1/models/test-model:countTokens', {'totalTokens': 12}),
])
def test_native_token_count_uses_provider_endpoint(backend, path, reply):
    def upstream(request):
        assert request.url.path == path
        assert request.method == 'POST'
        return httpx.Response(200, json=reply)
    with_client = ModelClient('https://provider.example/v1', 'test-model', backend=backend, api_key='secret', transport=httpx.MockTransport(upstream))
    try:
        assert with_client.count_prompt_tokens([{'role': 'user', 'content': 'test'}]) == 12
    finally:
        with_client.close()


def test_generic_api_does_not_invent_a_tokenizer_endpoint():
    client = ModelClient('http://localhost:1234/v1', 'local-model', backend='openai_compatible',
        transport=httpx.MockTransport(lambda request: pytest.fail('No token endpoint exists in this protocol')))
    try:
        assert client.budget_kind == 'serialized_bytes'
        with pytest.raises(ModelClientError, match='token'):
            client.count_prompt_tokens([{'role': 'user', 'content': 'test'}])
    finally:
        client.close()


def test_provider_errors_do_not_expose_response_body_or_key():
    client = ModelClient('https://api.openai.com/v1', 'test', backend='openai', api_key='secret',
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={'error': {'message': 'secret echoed'}})))
    try:
        with pytest.raises(ModelClientError) as error:
            client.models()
        assert error.value.code == 'model_auth_failed'
        assert 'secret' not in str(error.value)
    finally:
        client.close()
