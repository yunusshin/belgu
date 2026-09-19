import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from belgu.analysis.client import ModelClient
from test_memory import case, record


def response(alias='E001', actions=None):
    return {'answer': 'Kayıtlı betik izini inceleyin.',
            'claims': [{'text': 'Betik özeti kayıtta mevcut.', 'kind': 'observation', 'evidence_aliases': [alias]}],
            'actions': actions or [], 'uncertainties': ['Bu iz tek başına atıf sağlamaz.']}


def model(output=None, *, overflow=False, fail=False, prompts=None):
    def transport(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'fixture-local'}]})
        if request.url.path.endswith('/props'):
            return httpx.Response(200, json={'build_info': 'fixture-v1'})
        if request.url.path.endswith('/input_tokens'):
            data = json.loads(body['messages'][1]['content'])
            return httpx.Response(200, json={'input_tokens': 7000 if overflow and len(data['evidence']) > 1 else 500})
        assert body['max_tokens'] <= 1024
        if prompts is not None:
            prompts.append(json.loads(body['messages'][1]['content']))
        if fail:
            return httpx.Response(503)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output or response())}}], 'usage': {'prompt_tokens': 500, 'completion_tokens': 100}})
    return ModelClient('http://local.test/v1', '', timeout_seconds=30, transport=httpx.MockTransport(transport))


def ask(service, inv, **kwargs):
    from belgu.analysis.assistant import ask_assistant
    return ask_assistant(service, inv.id, 'Hangi kanıtı incelemeliyim?', **kwargs)


def turns(service, inv):
    from belgu.analysis.assistant import list_assistant_turns
    return list_assistant_turns(service, inv.id)['items']


def test_fabricated_alias_rejected_and_no_success_persisted(service):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    with pytest.raises(AssistantError) as error:
        ask(service, inv, client=model(response('E999')))
    assert error.value.code == 'invalid_model_output'
    assert turns(service, inv) == []


def test_foreign_citation_resolves_only_from_server_memory_and_snapshot_survives(service):
    from belgu.persistence.models import Observation
    inv, old, unrelated = case(service), case(service), case(service)
    record(service, inv)
    foreign = record(service, old)
    other = record(service, unrelated, value='b' * 64)
    result = ask(service, inv, client=model(response('E002', [{'type': 'open_evidence', 'label': 'Geçmiş kanıt', 'evidence_alias': 'E002'}])))
    ref = result['claims'][0]['evidence_refs'][0]
    assert (ref['investigation_id'], ref['evidence_id']) == (old.id, foreign)
    assert result['actions'][0]['investigation_id'] == old.id
    assert other not in {x['evidence_id'] for x in result['snapshot']['evidence_refs']}
    with service.repo.transaction() as session:
        session.get(Observation, foreign).payload = {'js_sha256': 'changed'}
    saved = turns(service, inv)[0]
    source = next(x for x in saved['snapshot']['evidence_refs'] if x['evidence_id'] == foreign)
    assert source['payload']['js_sha256'] == 'a' * 64
    assert source['source_ref'] == 'https://source.test/app.js' and source['observed_at']


def test_overflow_shrinks_verified_context_with_omissions(service):
    inv, old = case(service), case(service)
    record(service, inv)
    record(service, old)
    result = ask(service, inv, client=model(overflow=True))
    assert len(result['snapshot']['evidence_refs']) == 1
    assert result['snapshot']['omissions']['token_budget_evidence'] == 1
    assert result['model']['input_tokens'] <= 6144


def test_model_failure_is_retryable_and_history_comes_from_persistence(service):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    with pytest.raises(AssistantError) as error:
        ask(service, inv, client=model(fail=True))
    assert error.value.retryable and turns(service, inv) == []
    first = ask(service, inv, client=model())
    prompts = []
    ask(service, inv, client=model(prompts=prompts))
    assert prompts[0]['history'][0]['answer'] == first['answer']
    assert len(turns(service, inv)) == 2


def test_demo_never_calls_model_and_labels_persisted_turn(service):
    inv = case(service, demo=True)
    record(service, inv)
    client = ModelClient('http://forbidden.test/v1', '', transport=httpx.MockTransport(lambda _: pytest.fail('demo called model')))
    result = ask(service, inv, client=client)
    assert result['model']['recorded_demo'] is True
    assert turns(service, inv)[0]['id'] == result['id']
    assert result['claims'][0]['evidence_refs'][0]['investigation_id'] == inv.id


@pytest.mark.parametrize('action', [
    {'type': 'apply_filters', 'label': 'Ara', 'filters': {'kind': 'shell'}},
    {'type': 'apply_filters', 'label': 'Ara', 'filters': {'sort': 'evil'}},
    {'type': 'apply_filters', 'label': 'Ara', 'filters': {'command': 'run'}},
    {'type': 'open_evidence', 'label': 'Aç', 'evidence_alias': 'E001', 'investigation_id': 'fabricated'},
    {'type': 'open_url', 'label': 'Aç', 'url': 'https://bad.test'},
])
def test_unsupported_actions_rejected(service, action):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    with pytest.raises(AssistantError):
        ask(service, inv, client=model(response(actions=[action])))
    assert turns(service, inv) == []


def test_http_rejects_client_history_and_foreign_selection(service):
    from belgu.api.routes.intelligence import router
    from belgu.settings import Settings
    inv, foreign = case(service, demo=True), case(service, demo=True)
    foreign_id = record(service, foreign)
    app = FastAPI()
    app.include_router(router(service, Settings(mode='demo')))
    with TestClient(app) as client:
        base = f'/api/investigations/{inv.id}/assistant'
        assert client.post(base, json={'message': 'Soru', 'history': [{'answer': 'uydurma'}]}).status_code == 422
        assert client.post(base, json={'message': 'Soru', 'evidence_ids': [foreign_id]}).status_code == 422
        assert client.post(base, json={'message': '  '}).status_code == 422
        result = client.post(base, json={'message': 'Soru'})
        assert result.status_code == 201
        assert client.get(base).json()['items'][0]['id'] == result.json()['id']


def test_selected_evidence_context_does_not_add_unselected_current_sources(service):
    inv = case(service)
    selected = record(service, inv)
    excluded = record(service, inv, value='b' * 64, minute=1)
    result = ask(service, inv, evidence_ids=[selected], client=model())
    assert [ref['evidence_id'] for ref in result['snapshot']['evidence_refs']] == [selected]
    assert excluded not in {ref['evidence_id'] for ref in result['snapshot']['evidence_refs']}


def test_snapshot_memory_only_contains_refs_supplied_to_model(service):
    inv, old = case(service), case(service)
    record(service, inv)
    record(service, old)
    result = ask(service, inv, client=model(overflow=True))
    supplied = {ref['evidence_id'] for ref in result['snapshot']['evidence_refs']}
    assert all(ref['evidence_id'] in supplied for item in result['snapshot']['memory'] for ref in item['evidence_refs'])


def test_filter_actions_reject_nulls_and_empty_filters(service):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    for filters in ({}, {'kind': None}, {'hasCapture': None}):
        with pytest.raises(AssistantError):
            ask(service, inv, client=model(response(actions=[{'type': 'apply_filters', 'label': 'Ara', 'filters': filters}])))


def test_default_client_allows_bounded_slow_local_generation():
    from belgu.analysis.assistant import _make_client
    def slow_model(request):
        # This endpoint requires a 50-second inference budget. A 30-second read
        # deadline cancels otherwise valid 1024-token local output.
        if request.extensions['timeout']['read'] < 50:
            raise httpx.ReadTimeout('generation still running', request=request)
        assert request.extensions['timeout']['read'] <= 90
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
    with_client = _make_client(transport=httpx.MockTransport(slow_model))
    try:
        assert with_client.complete([], {}, max_output_tokens=1024).text == '{}'
    finally:
        with_client.close()


def test_timeout_has_specific_retryable_message(service):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    def timeout(request):
        raise httpx.ReadTimeout('still generating', request=request)
    with pytest.raises(AssistantError) as error:
        ask(service, inv, client=ModelClient('http://local.test/v1', '', transport=httpx.MockTransport(timeout)))
    assert error.value.code == 'model_timeout' and error.value.retryable
    assert 'süre' in str(error.value).lower()
    assert turns(service, inv) == []


def test_known_aliases_become_subject_descriptions_in_prose(service):
    inv = case(service)
    record(service, inv)
    raw = response()
    raw['uncertainties'] = ['E001 tek başına atıf sağlamaz.']
    result = ask(service, inv, client=model(raw))
    assert 'E001' not in result['uncertainties'][0]
    assert f'{inv.id}.test' in result['uncertainties'][0]


def test_oversized_sources_are_omitted_before_tokenizer_request(service):
    inv = case(service)
    record(service, inv, extra_detail={str(index): 'x' * 2000 for index in range(30)})
    raw = {'answer': 'Kanıt bağlamı sınırlı.', 'claims': [], 'actions': [], 'uncertainties': ['Kaynak dışarıda.']}
    result = ask(service, inv, client=model(raw))
    assert result['snapshot']['evidence_refs'] == []
    assert result['snapshot']['omissions']['context_evidence'] == 1


def test_demo_shared_trace_uses_both_case_scopes_and_offers_foreign_source(service):
    inv, old = case(service, demo=True), case(service, demo=True)
    record(service, inv)
    foreign = record(service, old)
    result = ask(service, inv)
    assert any({ref['investigation_id'] for ref in claim['evidence_refs']} == {inv.id, old.id} for claim in result['claims'])
    assert any(action.get('evidence_id') == foreign and action.get('investigation_id') == old.id for action in result['actions'])


def test_related_ip_name_search_becomes_scoped_source_action(service):
    inv = case(service)
    evidence_id = record(service, inv, 'answer', '198.51.100.15')
    action = {'type': 'apply_filters', 'label': "Ortak IP'li alan adlarını listele", 'filters': {'q': '198.51.100.15', 'kind': 'domain'}}
    result = ask(service, inv, client=model(response(actions=[action])))
    assert result['actions'] == [{'type': 'open_evidence', 'label': '198.51.100.15 IP gözlemini aç', 'investigation_id': inv.id, 'evidence_id': evidence_id}]


def test_unobserved_related_ip_filter_cannot_be_offered(service):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    action = {'type': 'apply_filters', 'label': "Ortak IP'li alan adlarını listele", 'filters': {'q': '198.51.100.15', 'kind': 'domain'}}
    with pytest.raises(AssistantError):
        ask(service, inv, client=model(response(actions=[action])))


def test_older_current_memory_support_survives_recent_evidence_window(service):
    inv, old = case(service), case(service)
    current = record(service, inv)
    foreign = record(service, old)
    for minute in range(1, 30):
        record(service, inv, value='b' * 64, minute=minute)
    prompts = []
    result = ask(service, inv, client=model(prompts=prompts))
    ids = {ref['evidence_id'] for ref in result['snapshot']['evidence_refs']}
    assert {current, foreign} <= ids
    assert prompts[0]['memory'][0]['evidence_aliases']


def test_candidate_priorities_come_from_real_ranking_with_snapshot_aliases(service):
    from belgu.domain.contracts import ProviderResult, EvidenceDraft, EntityRef
    from test_memory import AT
    inv = case(service)
    service.add_submission(inv.id, 'seed.test', 'analyst_discovery')
    for host in ('seed.test', 'strong.test'):
        service.record_result(inv.id, ProviderResult('page', 'ok', (
            EvidenceDraft(EntityRef('domain', host), 'javascript_content', f'https://{host}/app.js', AT, AT, {'js_sha256': 'a' * 64}),
        )))
    prompts = []
    result = ask(service, inv, client=model(prompts=prompts))
    candidate = prompts[0]['candidates'][0]
    assert candidate['domain'] == 'strong.test' and candidate['score'] == 30
    assert candidate['reasons'][0]['evidence_aliases']
    assert {alias for reason in candidate['reasons'] for alias in reason['evidence_aliases']} <= {ref['alias'] for ref in prompts[0]['evidence']}
    assert result['snapshot']['candidates'][0]['domain'] == 'strong.test'


def test_demo_high_cardinality_claim_reserves_foreign_citation(service):
    from belgu.domain.contracts import ProviderResult, EvidenceDraft, EntityRef
    from test_memory import AT
    inv, old = case(service, demo=True), case(service, demo=True)
    selected = []
    for index in range(12):
        selected.extend(service.record_result(inv.id, ProviderResult('page', 'ok', (
            EvidenceDraft(EntityRef('domain', f'current-{index}.test'), 'javascript_content',
                          f'https://current-{index}.test/app.js', AT, AT, {'js_sha256': 'a' * 64}),
        ))).evidence_ids)
    foreign = record(service, old)
    result = ask(service, inv, evidence_ids=selected)
    claim = result['claims'][0]
    assert len(claim['evidence_refs']) <= 12
    assert {ref['investigation_id'] for ref in claim['evidence_refs']} == {inv.id, old.id}
    assert foreign in {ref['evidence_id'] for ref in claim['evidence_refs']}
    assert turns(service, inv)[0]['claims'] == result['claims']


@pytest.mark.parametrize('filters', [
    {'kind': 'ip', 'shared': 'javascript'},
    {'kind': 'ip', 'shared': 'certificate'},
    {'kind': 'ip', 'hasCapture': True},
])
def test_assistant_rejects_ip_kind_combined_with_page_filters(service, filters):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    with pytest.raises(AssistantError):
        ask(service, inv, client=model(response(actions=[{'type': 'apply_filters', 'label': 'Filtrele', 'filters': filters}])))
    assert turns(service, inv) == []


def test_capture_priority_action_is_supported_without_ranked_candidates(service):
    inv = case(service)
    record(service, inv)
    filters = {'kind': 'domain', 'hasCapture': True, 'sort': 'priority'}
    result = ask(service, inv, client=model(response(actions=[{'type': 'apply_filters', 'label': 'Görsel kayıtlı alanlar', 'filters': filters}])))
    assert result['snapshot']['candidates'] == []
    assert result['actions'][0]['filters'] == filters


def test_evidence_action_label_describes_actual_source_not_model_promise(service):
    inv = case(service)
    evidence_id = record(service, inv)
    action = {'type': 'open_evidence', 'label': 'Geçmiş araştırma kararını ve notlarını incele', 'evidence_alias': 'E001'}
    result = ask(service, inv, client=model(response(actions=[action])))
    assert result['actions'] == [{'type': 'open_evidence', 'label': f'{inv.id}.test · page kanıtını aç',
                                  'investigation_id': inv.id, 'evidence_id': evidence_id}]
    assert turns(service, inv)[0]['actions'] == result['actions']


@pytest.mark.parametrize('count,accepted', [(3, True), (4, False)])
def test_assistant_action_limit_is_three(service, count, accepted):
    from belgu.analysis.assistant import AssistantError
    inv = case(service)
    record(service, inv)
    actions = [{'type': 'open_evidence', 'label': f'Kaynak {index}', 'evidence_alias': 'E001'} for index in range(count)]
    if accepted:
        assert len(ask(service, inv, client=model(response(actions=actions)))['actions']) == 3
    else:
        with pytest.raises(AssistantError):
            ask(service, inv, client=model(response(actions=actions)))
        assert turns(service, inv) == []


@pytest.mark.parametrize('ct_count', [13, 30])
def test_kind_diversity_keeps_older_a_record_when_repeated_ct_overflows_tokens(service, ct_count):
    from datetime import timedelta
    from belgu.domain.contracts import ProviderResult, EvidenceDraft, EntityRef
    from test_memory import AT
    inv = case(service)
    def observe(kind, minute, payload, subject=EntityRef('domain', 'target.test')):
        return service.record_result(inv.id, ProviderResult('fixture', 'ok', (
            EvidenceDraft(subject, kind, f'urn:fixture:{kind}:{minute}', AT + timedelta(minutes=minute),
                          AT + timedelta(minutes=minute), payload),
        ))).evidence_ids[0]
    a_id = observe('dns_a', 0, {'rrtype': 'A', 'rcode': 'NOERROR', 'answer': '192.0.2.15'})
    observe('redirect_chain', 1, {'requested_url': 'http://target.test/', 'final_url': 'http://target.test/next'})
    observe('page_capture_failed', 2, {'error_type': 'tls_error'})
    for index in range(ct_count):
        observe('certificate_transparency', 3 + index,
                {'certificate_id': index, 'names': ['target.test'], 'issuer': 'x' * 1800})
    observe('dns_ptr', 40, {'rrtype': 'PTR', 'answer': 'node.example.test'}, EntityRef('ip', '192.0.2.15'))
    ask(service, inv, recorded_demo=True)  # Persisted history must also be fitted.
    def transport(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'fixture-local'}]})
        if request.url.path.endswith('/props'):
            return httpx.Response(200, json={'build_info': 'fixture-v1'})
        context = json.loads(body['messages'][1]['content'])
        # The external tokenizer seam reports a large CT record's token cost.
        # Exercise production fitting, rather than directly arranging its result.
        tokens = 1800 + (2000 if context['history'] else 0) + sum(800 if item['kind'] == 'certificate_transparency' else 100
                            for item in context['evidence'])
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': tokens})
        assert tokens <= 6144
        output = {'answer': 'Kayıtlı kaynaklar hazır.', 'claims': [], 'actions': [], 'uncertainties': []}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]})
    client = ModelClient('http://fixture.test/v1', '', transport=httpx.MockTransport(transport))
    try:
        result = ask(service, inv, client=client)
    finally:
        client.close()
    assert a_id in {ref['evidence_id'] for ref in result['snapshot']['evidence_refs']}
    assert {'dns_a', 'dns_ptr', 'redirect_chain', 'page_capture_failed', 'certificate_transparency'} <= {
        ref['kind'] for ref in result['snapshot']['evidence_refs']}
    assert result['snapshot']['omissions']['token_budget_evidence'] > 0
    assert result['snapshot']['omissions']['token_budget_history'] == 1
    assert result['model']['input_tokens'] <= 6144


def test_kind_representatives_precede_repeated_candidate_ct_support_during_fit(service):
    from datetime import timedelta
    from belgu.application.insights import rank_candidates
    from belgu.domain.contracts import ProviderResult, EvidenceDraft, EntityRef
    from test_memory import AT
    inv = case(service)
    service.add_submission(inv.id, 'seed.test', 'analyst_discovery')
    def observe(kind, minute, payload, host='candidate.test'):
        return service.record_result(inv.id, ProviderResult('fixture', 'ok', (
            EvidenceDraft(EntityRef('domain', host), kind, f'urn:fixture:{kind}:{minute}',
                          AT + timedelta(minutes=minute), AT + timedelta(minutes=minute), payload),
        ))).evidence_ids[0]
    a_id = observe('dns_a', 0, {'rrtype': 'A', 'rcode': 'NOERROR', 'answer': '192.0.2.15'})
    ct_ids = {observe('certificate_transparency', index + 1,
                      {'certificate_id': index, 'names': ['seed.test', 'candidate.test'], 'issuer': 'x' * 1800},
                      host='seed.test') for index in range(4)}
    observe('page_content', 10, {'text': 'Kayıtlı örnek içerik.'})
    observe('redirect_chain', 11, {'final_url': 'https://candidate.test/next'})
    observe('dns_ptr', 12, {'rrtype': 'PTR', 'answer': 'node.example.test'})
    for index in range(6):
        observe('page_capture_failed', 20 + index, {'error_type': 'tls_error', 'attempt': index})
    ranking = rank_candidates(service, inv.id)
    assert ranking['items'][0]['domain'] == 'candidate.test'
    assert set(ranking['items'][0]['evidence_ids']) == ct_ids
    def transport(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'fixture-local'}]})
        if request.url.path.endswith('/props'):
            return httpx.Response(200, json={})
        context = json.loads(body['messages'][1]['content'])
        tokens = 1800 + sum(1000 if item['kind'] == 'certificate_transparency' else 100
                            for item in context['evidence'])
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': tokens})
        assert tokens <= 6144
        output = {'answer': 'Kayıtlı gözlemler hazır.', 'claims': [], 'actions': [], 'uncertainties': []}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]})
    client = ModelClient('http://fixture.test/v1', '', transport=httpx.MockTransport(transport))
    try:
        result = ask(service, inv, client=client)
    finally:
        client.close()
    assert a_id in {ref['evidence_id'] for ref in result['snapshot']['evidence_refs']}
    assert {'dns_a', 'dns_ptr', 'redirect_chain', 'page_content', 'page_capture_failed', 'certificate_transparency'} <= {
        ref['kind'] for ref in result['snapshot']['evidence_refs']}
    assert result['snapshot']['omissions']['token_budget_evidence'] > 0
    assert result['snapshot']['candidates'] == []
    assert result['snapshot']['omissions']['candidates_omitted'] == 1
