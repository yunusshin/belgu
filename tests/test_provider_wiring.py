import json
from datetime import datetime, timezone

import httpx
import pytest

from belgu.analysis import service as analysis
from belgu.core.providers.base import Budget, CollectionContext
from belgu.core.providers.reverse_ip import ReverseIpProvider
from belgu.core.providers.urlscan import UrlscanProvider
from belgu.core.feeds.threatfox import ThreatFoxProvider
from belgu.core.network import FetchResult
from belgu.domain.contracts import EntityRef, Limits
from belgu.integrations import defaults


def completion(backend, raw):
    if backend == 'openai':
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': raw}]}], 'usage': {'input_tokens': 111, 'output_tokens': 40}}
    if backend == 'anthropic':
        return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': raw}], 'usage': {'input_tokens': 111, 'output_tokens': 40}}
    if backend == 'gemini':
        return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': raw}]}}], 'usageMetadata': {'promptTokenCount': 111, 'candidatesTokenCount': 40}}
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': raw}}], 'usage': {'prompt_tokens': 111, 'completion_tokens': 40}}


def mock_client_factory(monkeypatch, backend, output, seen):
    original = httpx.Client
    def handler(request):
        seen.append(request)
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json=({'models': [{'name': 'models/model-test', 'supportedGenerationMethods': ['generateContent']}]} if backend == 'gemini'
                                           else {'data': [{'id': 'model-test'}]}))
        if request.url.path.endswith(('/input_tokens', '/count_tokens', ':countTokens')):
            assert backend not in ('openrouter', 'openai_compatible')
            return httpx.Response(200, json={'input_tokens': 500, 'totalTokens': 500})
        return httpx.Response(200, json=completion(backend, json.dumps(output)))
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(**{**kwargs, 'transport': httpx.MockTransport(handler)}))


@pytest.mark.parametrize('backend', ['openai', 'anthropic', 'gemini', 'openrouter', 'openai_compatible'])
def test_analysis_runs_through_each_provider_with_real_validation_and_usage(monkeypatch, backend):
    output = {'summary': 'Kanıt özeti.', 'claims': [{'text': 'Başlık banka giriş ifadesi içeriyor.', 'kind': 'observation', 'evidence_ids': ['E001']}], 'uncertainties': [], 'next_steps': []}
    seen = []
    mock_client_factory(monkeypatch, backend, output, seen)
    evidence = [{'id': f'actual-evidence-{index}', 'subject': {'kind': 'domain', 'value': 'aday.test'},
                 'provider': 'page', 'source_ref': 'https://source.test/', 'payload': {'title': 'Banka giriş', 'visible_text': 'x' * 2000}} for index in range(40)]
    result = analysis.analyze_evidence(evidence, connection={'base_url': 'https://provider.test/v1', 'backend': backend, 'model_id': 'model-test', 'api_key': 'private-test-key'})
    assert result['claims'][0]['evidence_ids'] == ['actual-evidence-0']
    assert result['metrics']['input_tokens'] == 111
    assert all('private-test-key' not in request.content.decode() for request in seen)
    if backend in ('openrouter', 'openai_compatible'):
        assert result['metrics']['input_budget_kind'] == 'serialized_bytes'
        assert result['metrics']['input_budget_units'] <= 32 * 1024
        assert result['omitted_count'] > 0
    else:
        assert result['metrics']['input_budget_kind'] == 'tokens'
        assert result['metrics']['input_budget_units'] == 500


def test_saved_cloud_profile_is_used_by_assistant_and_nullable_filters_are_normalized(service, monkeypatch):
    from test_memory import case, record
    from belgu.analysis.assistant import ask_assistant, list_assistant_turns
    inv = case(service)
    evidence_id = record(service, inv)
    filters = {'q': None, 'kind': 'domain', 'hasCapture': True, 'shared': None, 'recent': None, 'sort': 'priority'}
    output = {'answer': 'Görseli olan alanları inceleyin.', 'claims': [{'text': 'Betik kaydı var.', 'kind': 'observation', 'evidence_aliases': ['E001']}],
              'actions': [{'type': 'apply_filters', 'label': 'Filtrele', 'filters': filters}], 'uncertainties': []}
    seen = []
    mock_client_factory(monkeypatch, 'openai', output, seen)
    service.integrations.update({'active_llm': 'openai', 'llm': {'openai': {'model_id': 'model-test', 'api_key': 'saved-key'}}})
    result = ask_assistant(service, inv.id, 'Hangi kanıtı incelemeliyim?')
    assert seen[0].url.host == 'api.openai.com'
    assert seen[0].headers['authorization'] == 'Bearer saved-key'
    assert result['claims'][0]['evidence_refs'][0]['evidence_id'] == evidence_id
    assert result['actions'][0]['filters'] == {'kind': 'domain', 'hasCapture': True, 'sort': 'priority'}
    assert list_assistant_turns(service, inv.id)['items'][0]['model']['input_tokens'] == 111


class Upstream:
    def __init__(self, data):
        self.calls = []
        self.data = data

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FetchResult(url, 200, {}, self.data, ())

    def post(self, url, **kwargs):
        return self.get(url, **kwargs)


@pytest.mark.parametrize('provider,name,header,payload', [
    (ReverseIpProvider('hackertarget'), 'hackertarget', 'X-API-Key', b'candidate.test'),
    (ReverseIpProvider('mnemonic'), 'mnemonic', 'Argus-API-Key', b'{"data":[]}'),
    (UrlscanProvider(), 'urlscan', 'API-Key', b'{"results":[]}'),
])
def test_discovery_uses_saved_provider_key_in_header_only(provider, name, header, payload):
    config = defaults()['sources']
    config[name]['api_key'] = 'private-source-key'
    http = Upstream(payload)
    context = CollectionContext(http, Budget(Limits()), lambda: datetime.now(timezone.utc), config)
    target = EntityRef('domain', 'candidate.test') if name == 'urlscan' else EntityRef('ip', '1.1.1.1')
    result = provider.collect(target, context)
    assert result.status == 'ok'
    assert http.calls[0][1]['headers'][header] == 'private-source-key'
    assert 'private-source-key' not in str(result)
    assert 'private-source-key' not in http.calls[0][0]


def test_threatfox_filters_lookalikes_and_preserves_observed_time():
    rows = [{'id': 12, 'ioc': 'https://candidate.test/login', 'ioc_type': 'url', 'first_seen': '2026-09-01 09:10:23 UTC'},
            {'id': 13, 'ioc': 'https://notcandidate.test/login', 'ioc_type': 'url'}]
    http = Upstream(json.dumps({'query_status': 'ok', 'data': rows}).encode())
    config = defaults()['sources']
    config['threatfox']['api_key'] = 'private-source-key'
    context = CollectionContext(http, Budget(Limits()), lambda: datetime.now(timezone.utc), config)
    result = ThreatFoxProvider().collect(EntityRef('domain', 'candidate.test'), context)
    assert result.status == 'ok'
    assert len(result.observations) == 1
    assert result.observations[0].observed_at.isoformat() == '2026-09-01T09:10:23+00:00'
    assert http.calls[0][1]['json_body'] == {'query': 'search_ioc', 'search_term': 'candidate.test', 'exact_match': False}
    assert http.calls[0][1]['headers'] == {'Auth-Key': 'private-source-key'}


def test_discovery_does_not_call_disabled_sources(monkeypatch):
    from belgu.core import discovery
    from belgu.domain.contracts import ProviderResult
    calls = []
    for cls in (discovery.DnsProvider, discovery.ReverseIpProvider, discovery.UrlscanProvider):
        def collect(self, target, context):
            calls.append(self.name)
            return ProviderResult(self.name, 'ok')
        monkeypatch.setattr(cls, 'collect', collect)
    config = defaults()['sources']
    config['mnemonic']['enabled'] = False
    config['urlscan']['enabled'] = False
    discovery.discover('1.1.1.1', provider_settings=config)
    assert sorted(calls) == ['dns', 'reverse_ip.hackertarget']
