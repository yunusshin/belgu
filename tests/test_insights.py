from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from belgu.application import insights
from belgu.application.service import NotFoundError
from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult
from belgu.persistence.models import CollectionRun, Job


T0 = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)


def case(service, target='seed.test'):
    brand = service.create_brand('Fixture', ['official.test'])
    investigation = service.create_investigation(brand.id, 'Insights fixture')
    service.add_submission(investigation.id, target, 'customer_report')
    return investigation.id


def evidence(service, investigation_id, subject, kind, payload, *, provider='fixture', minute=1,
             observed_at=None, source_ref=None):
    subject = EntityRef('url' if '://' in subject else 'domain', subject)
    return service.record_result(investigation_id, ProviderResult(provider, 'ok', (
        EvidenceDraft(subject, kind, source_ref or f'urn:fixture:{subject.value}:{kind}',
                      observed_at or T0, T0 + timedelta(minutes=minute), payload),
    ))).evidence_ids[0]


def job(service, investigation_id, minute, *, status='completed', kind='collect', providers=None):
    with service.repo.transaction() as session:
        row = Job(investigation_id=investigation_id, kind=kind, status=status,
                  created_at=T0 + timedelta(minutes=minute),
                  updated_at=T0 + timedelta(minutes=minute + 2),
                  progress={'providers': providers or []})
        session.add(row)
        session.flush()
        return row.id


def run(service, investigation_id, minute, evidence_ids, **kwargs):
    job_id = job(service, investigation_id, minute, **kwargs)
    insights.record_run(service, job_id, evidence_ids)
    return job_id


def test_record_run_keeps_exact_unique_case_evidence_and_actual_job_status(service):
    investigation_id = case(service)
    item = evidence(service, investigation_id, 'seed.test', 'dns_a', {'observed_ip': '198.51.100.1'})
    job_id = run(service, investigation_id, 0, [item, item], status='running')
    insights.record_run(service, job_id, [item])
    with service.repo.transaction() as session:
        saved = session.get(CollectionRun, job_id)
        assert saved.evidence_ids == [item]
        session.get(Job, job_id).status = 'partial'
    page = insights.list_runs(service, investigation_id)
    assert page['total_unique'] == 1
    assert page['items'][0] == {'id': job_id, 'created_at': T0.isoformat(), 'status': 'partial',
                                 'evidence_count': 1, 'approximate': False}


def test_record_and_compare_reject_foreign_case_ids(service):
    first, second = case(service), case(service, 'other.test')
    foreign = evidence(service, second, 'other.test', 'dns_a', {'answer': '198.51.100.2'})
    first_job, second_job = job(service, first, 0), run(service, second, 3, [foreign])
    with pytest.raises(ValueError):
        insights.record_run(service, first_job, [foreign])
    with pytest.raises(NotFoundError):
        insights.compare_runs(service, first, before=first_job, after=second_job)
    with pytest.raises(ValueError):
        insights.record_run(service, job(service, first, 6, kind='analysis'), [])
    with pytest.raises(ValueError):
        insights.record_run(service, first_job, ['missing'])


def test_retrieval_time_dns_ttl_and_duplicate_archive_hits_do_not_change_state(service):
    investigation_id = case(service)
    initial = [evidence(service, investigation_id, 'seed.test', 'dns_a',
                        {'answer': '198.51.100.1', 'observed_ip': '198.51.100.1', 'ttl': 300}, provider='dns')]
    scan = {'scan_id': 'archived-scan', 'title': 'Login', 'observed_ip': '198.51.100.1'}
    initial.append(evidence(service, investigation_id, 'seed.test', 'existing_scan', scan, provider='urlscan'))
    repeated = [evidence(service, investigation_id, 'seed.test', 'dns_a',
                         {'answer': '198.51.100.1', 'observed_ip': '198.51.100.1', 'ttl': 45},
                         provider='dns', minute=4, observed_at=T0 + timedelta(minutes=4))]
    repeated.extend(evidence(service, investigation_id, 'seed.test', 'existing_scan', scan,
                             provider='urlscan', minute=minute) for minute in (4, 5))
    before, after = run(service, investigation_id, 0, initial), run(service, investigation_id, 3, repeated)
    result = insights.compare_runs(service, investigation_id)
    assert (result['before'], result['after']) == (before, after)
    assert result['changes'] == []
    assert result['counts'] == {'new': 0, 'changed': 0, 'not_observed': 0}


def test_actual_ip_and_page_values_change_with_both_sources_cited(service):
    investigation_id = case(service)
    old_ip = evidence(service, investigation_id, 'seed.test', 'dns_a', {'observed_ip': '198.51.100.1'}, provider='dns')
    old_page = evidence(service, investigation_id, 'https://seed.test/', 'page_content', {'text': 'Old content'}, provider='page')
    new_ip = evidence(service, investigation_id, 'seed.test', 'dns_a', {'observed_ip': '198.51.100.2'}, provider='dns', minute=4)
    new_page = evidence(service, investigation_id, 'https://seed.test/', 'page_content', {'text': 'New content'}, provider='page', minute=4)
    run(service, investigation_id, 0, [old_ip, old_page])
    run(service, investigation_id, 3, [new_ip, new_page])
    result = insights.compare_runs(service, investigation_id)
    assert result['counts'] == {'new': 0, 'changed': 2, 'not_observed': 0}
    ip_change = next(change for change in result['changes'] if change['subject'] == 'seed.test')
    assert ip_change['before'] == '198.51.100.1'
    assert ip_change['after'] == '198.51.100.2'
    assert set(ip_change['evidence_ids']) == {old_ip, new_ip}


@pytest.mark.parametrize('status', ['partial', 'failed', 'completed'])
def test_missing_values_are_not_observed_never_removed(service, status):
    investigation_id = case(service)
    first = evidence(service, investigation_id, 'seed.test', 'dns_a', {'observed_ip': '198.51.100.1'}, provider='dns')
    second = evidence(service, investigation_id, 'seed.test', 'dns_a', {'observed_ip': '198.51.100.2'}, provider='dns')
    run(service, investigation_id, 0, [first, second])
    run(service, investigation_id, 3, [first], status=status,
        providers=[{'provider': 'dns', 'status': 'partial' if status != 'completed' else 'ok'}])
    result = insights.compare_runs(service, investigation_id)
    assert result['counts'] == {'new': 0, 'changed': 0, 'not_observed': 1}
    assert result['changes'][0]['before'] == '198.51.100.2'
    assert result['changes'][0]['after'] is None
    assert result['limitations']
    if status != 'completed':
        expected_status = {'partial': 'kısmi', 'failed': 'başarısız'}[status]
        assert any(expected_status in limitation for limitation in result['limitations'])


def test_different_archive_records_are_new_and_not_observed_not_current_value_changes(service):
    investigation_id = case(service)
    old = evidence(service, investigation_id, 'seed.test', 'existing_scan',
                   {'scan_id': 'old-scan', 'observed_ip': '198.51.100.1'}, provider='urlscan')
    new = evidence(service, investigation_id, 'seed.test', 'existing_scan',
                   {'scan_id': 'new-scan', 'observed_ip': '198.51.100.2'}, provider='urlscan', minute=4)
    run(service, investigation_id, 0, [old])
    run(service, investigation_id, 3, [new])
    result = insights.compare_runs(service, investigation_id)
    assert result['counts']['changed'] == 0
    assert result['counts']['new'] > 0
    assert result['counts']['not_observed'] > 0


def test_legacy_retrieval_interval_is_scoped_and_labelled_approximate(service):
    investigation_id = case(service)
    other = case(service, 'other.test')
    evidence(service, investigation_id, 'seed.test', 'dns_a', {'answer': '198.51.100.1'}, minute=1)
    evidence(service, other, 'other.test', 'dns_a', {'answer': '198.51.100.9'}, minute=1)
    old, new = job(service, investigation_id, 0), job(service, investigation_id, 3)
    job(service, investigation_id, 6, status='queued')
    rows = insights.list_runs(service, investigation_id)['items']
    assert [row['id'] for row in rows] == [new, old]
    assert [row['evidence_count'] for row in rows] == [0, 1]
    assert all(row['approximate'] for row in rows)
    assert any('yaklaşık' in value for value in insights.compare_runs(service, investigation_id)['limitations'])
    with service.sessions() as session:
        assert session.scalars(select(CollectionRun)).all() == []


def test_comparison_requires_two_runs_and_can_select_preceding_run(service):
    investigation_id = case(service)
    assert insights.compare_runs(service, investigation_id)['limitations']
    first = run(service, investigation_id, 0, [])
    assert insights.compare_runs(service, investigation_id)['changes'] == []
    second = run(service, investigation_id, 3, [])
    run(service, investigation_id, 6, [])
    selected = insights.compare_runs(service, investigation_id, after=second)
    assert (selected['before'], selected['after']) == (first, second)


def signal(service, investigation_id, domain, field, value, **extra):
    kinds = {'observed_ip': 'dns_a', 'cert_sha256': 'tls_certificate',
             'js_sha256': 'javascript_content', 'body_sha256': 'page_content'}
    return evidence(service, investigation_id, domain, kinds[field], {field: value, **extra})


def test_multiple_independent_signals_outrank_shared_ip_and_exclude_exact_submitted_host(service):
    investigation_id = case(service, 'https://seed.test/Login')
    seed_ids = [signal(service, investigation_id, 'seed.test', field, value) for field, value in (
        ('observed_ip', '198.51.100.1'), ('cert_sha256', 'a' * 64), ('js_sha256', 'b' * 64))]
    weak = signal(service, investigation_id, 'weak.test', 'observed_ip', '198.51.100.1')
    strong = [signal(service, investigation_id, 'strong.test', field, value) for field, value in (
        ('observed_ip', '198.51.100.1'), ('cert_sha256', 'a' * 64), ('js_sha256', 'b' * 64))]
    signal(service, investigation_id, 'sub.seed.test', 'observed_ip', '198.51.100.1')
    page = insights.rank_candidates(service, investigation_id)
    assert page['total_unique'] == 3
    assert [item['domain'] for item in page['items']] == ['strong.test', 'sub.seed.test', 'weak.test']
    top, low = page['items'][0], page['items'][-1]
    assert top['score'] > low['score']
    assert top['priority'] == 'high'
    assert low['priority'] == 'low'
    assert len(top['reasons']) == 3
    assert low['reasons'][0]['strength'] == 'weak'
    assert set(top['evidence_ids']) == set(seed_ids + strong)
    assert weak in low['evidence_ids']
    assert all(reason['evidence_ids'] for reason in top['reasons'])
    assert all(item not in limitation for item in low['evidence_ids'] for limitation in low['limitations'])
    assert 'IP' in low['reasons'][0]['label']
    assert any('Paylaşımlı' in limitation for limitation in low['limitations'])


def test_common_script_and_widespread_hash_are_discounted_without_duplicate_inflation(service):
    investigation_id = case(service)
    signal(service, investigation_id, 'seed.test', 'js_sha256', 'a' * 64, script_url='https://cdn.test/jquery.min.js')
    signal(service, investigation_id, 'common.test', 'js_sha256', 'a' * 64, script_url='https://cdn.test/jquery.min.js')
    signal(service, investigation_id, 'seed.test', 'js_sha256', 'b' * 64, script_url='https://seed.test/login.js')
    for index in range(5):
        signal(service, investigation_id, f'widespread-{index}.test', 'js_sha256', 'b' * 64)
    signal(service, investigation_id, 'seed.test', 'js_sha256', 'c' * 64, script_url='https://seed.test/specific.js')
    custom_id = signal(service, investigation_id, 'custom.test', 'js_sha256', 'c' * 64)
    # Repeated retrievals of one host must not be counted as independent hosts.
    for minute in range(10, 16):
        evidence(service, investigation_id, 'custom.test', 'javascript_content', {'js_sha256': 'c' * 64}, minute=minute)
    items = {item['domain']: item for item in insights.rank_candidates(service, investigation_id)['items']}
    assert items['custom.test']['score'] > items['common.test']['score']
    assert items['custom.test']['score'] > items['widespread-0.test']['score']
    assert items['common.test']['reasons'][0]['strength'] == 'weak'
    assert items['widespread-0.test']['reasons'][0]['strength'] == 'weak'
    assert custom_id in items['custom.test']['evidence_ids']


def test_certificate_name_record_is_positive_link_without_query_hit_attribution(service):
    investigation_id = case(service)
    linked = evidence(service, investigation_id, 'linked.test', 'certificate_transparency',
                      {'certificate_id': 123, 'names': ['seed.test', 'linked.test']}, provider='crtsh')
    evidence(service, investigation_id, 'query-hit.test', 'certificate_transparency',
             {'certificate_id': 456, 'names': ['query-hit.test']}, provider='crtsh')
    page = insights.rank_candidates(service, investigation_id)
    assert page['total_unique'] == 1
    assert page['items'][0]['domain'] == 'linked.test'
    assert page['items'][0]['evidence_ids'] == [linked]


def test_candidates_use_only_case_evidence_and_bound_results(service):
    investigation_id, other = case(service), case(service)
    signal(service, investigation_id, 'seed.test', 'observed_ip', '198.51.100.1')
    signal(service, investigation_id, 'inside.test', 'observed_ip', '198.51.100.1')
    signal(service, investigation_id, 'another.test', 'observed_ip', '198.51.100.1')
    foreign = signal(service, other, 'outside.test', 'observed_ip', '198.51.100.1')
    page = insights.rank_candidates(service, investigation_id, limit=1)
    assert page['total_unique'] == 2
    assert len(page['items']) == 1
    assert page['items'][0]['domain'] == 'another.test'
    assert foreign not in str(page)
    with pytest.raises(ValueError):
        insights.rank_candidates(service, investigation_id, limit=0)


def test_submitted_ip_can_prioritize_collected_domain_with_cited_dns_record(service):
    investigation_id = case(service, '198.51.100.1')
    matching = signal(service, investigation_id, 'candidate.test', 'observed_ip', '198.51.100.1')
    signal(service, investigation_id, 'unrelated.test', 'observed_ip', '198.51.100.2')
    page = insights.rank_candidates(service, investigation_id)
    assert page['total_unique'] == 1
    assert page['items'][0]['domain'] == 'candidate.test'
    assert page['items'][0]['priority'] == 'low'
    assert page['items'][0]['reasons'][0]['evidence_ids'] == [matching]


def test_partial_dns_answer_replacement_keeps_unseen_answer_separate_from_new_answer(service):
    investigation_id = case(service)
    old = signal(service, investigation_id, 'seed.test', 'observed_ip', '198.51.100.1')
    new = signal(service, investigation_id, 'seed.test', 'observed_ip', '198.51.100.2')
    run(service, investigation_id, 0, [old])
    run(service, investigation_id, 3, [new], status='partial',
        providers=[{'provider': 'fixture', 'status': 'partial', 'truncated': True}])
    result = insights.compare_runs(service, investigation_id)
    assert result['counts'] == {'new': 1, 'changed': 0, 'not_observed': 1}
    assert next(item for item in result['changes'] if item['kind'] == 'new')['after'] == '198.51.100.2'
    assert next(item for item in result['changes'] if item['kind'] == 'not_observed')['before'] == '198.51.100.1'


def test_page_content_on_url_subject_supports_candidate_domain_without_double_counting_content(service):
    investigation_id = case(service)
    # One DNS record makes the domain a case entity but is not a shared signal.
    signal(service, investigation_id, 'candidate.test', 'observed_ip', '198.51.100.2')
    payload = {'body_sha256': 'a' * 64, 'text': 'A sufficiently long synthetic login description. ' * 4}
    seed = evidence(service, investigation_id, 'https://seed.test/login', 'page_content', payload)
    candidate = evidence(service, investigation_id, 'https://candidate.test/login', 'page_content', payload)
    page = insights.rank_candidates(service, investigation_id)
    assert page['items'][0]['domain'] == 'candidate.test'
    assert len(page['items'][0]['reasons']) == 1
    assert page['items'][0]['priority'] == 'medium'
    assert set(page['items'][0]['evidence_ids']) == {seed, candidate}


def test_empty_http_bodies_do_not_create_content_similarity_candidates(service):
    investigation_id = case(service)
    empty_sha256 = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    signal(service, investigation_id, 'seed.test', 'body_sha256', empty_sha256, bytes=0, text='', status_code=400)
    signal(service, investigation_id, 'empty.test', 'body_sha256', empty_sha256, bytes=0, text='', status_code=400)
    assert insights.rank_candidates(service, investigation_id) == {'items': [], 'total_unique': 0, 'next_cursor': None}


LEXICAL_TEXT = ('Müşteri hesabınıza erişim sürecinde güvenli bağlantı üzerinden kimliğinizi doğrulayın '
                'işlem geçmişinizi görüntüleyin ödeme talimatlarını düzenleyin iletişim bilgilerinizi '
                'güncelleyin destek ekibimiz mesai saatlerinde sorularınızı yanıtlamak için burada hizmet vermektedir')


@pytest.mark.parametrize('seed_kind,candidate_kind', [('page_content', 'page_browser'), ('page_browser', 'page_content')])
def test_small_page_text_changes_still_support_moderate_cited_similarity(service, seed_kind, candidate_kind):
    investigation_id = case(service)
    signal(service, investigation_id, 'similar.test', 'observed_ip', '198.51.100.2')
    seed = evidence(service, investigation_id, 'https://seed.test/login', seed_kind, {'text': LEXICAL_TEXT})
    candidate_text = LEXICAL_TEXT.replace('mesai', 'çalışma').replace('burada', 'çevrimiçi')
    candidate = evidence(service, investigation_id, 'https://similar.test/login', candidate_kind, {'text': candidate_text})
    page = insights.rank_candidates(service, investigation_id)
    assert page['total_unique'] == 1
    item = page['items'][0]
    assert item['domain'] == 'similar.test'
    assert item['priority'] == 'medium'
    assert len(item['reasons']) == 1
    assert item['reasons'][0]['strength'] == 'moderate'
    assert 'Benzer sayfa metni' in item['reasons'][0]['label']
    assert set(item['reasons'][0]['evidence_ids']) == {seed, candidate}
    assert set(item['evidence_ids']) == {seed, candidate}


@pytest.mark.parametrize('candidate_text', [
    'Güvenli müşteri girişi kullanıcı adı parola hesabınızı doğrulayın tekrar deneyin',
    LEXICAL_TEXT.replace('Müşteri', 'Danışman').replace('hesabınıza', 'başvurunuza')
        .replace('erişim', 'randevu').replace('sürecinde', 'etkinliğinde').replace('güvenli', 'açık')
        .replace('bağlantı', 'planlama').replace('üzerinden', 'kanalıyla').replace('kimliğinizi', 'belgelerinizi')
        .replace('doğrulayın', 'paylaşın').replace('işlem', 'seyahat'),
])
def test_short_generic_or_insufficiently_similar_text_does_not_create_candidate(service, candidate_text):
    investigation_id = case(service)
    signal(service, investigation_id, 'candidate.test', 'observed_ip', '198.51.100.2')
    evidence(service, investigation_id, 'https://seed.test/login', 'page_content', {'text': LEXICAL_TEXT})
    evidence(service, investigation_id, 'https://candidate.test/login', 'page_browser', {'text': candidate_text})
    assert insights.rank_candidates(service, investigation_id) == {'items': [], 'total_unique': 0, 'next_cursor': None}


def test_exact_and_similar_text_remain_one_content_signal(service):
    investigation_id = case(service)
    signal(service, investigation_id, 'candidate.test', 'observed_ip', '198.51.100.2')
    evidence(service, investigation_id, 'https://seed.test/login', 'page_content', {'text': LEXICAL_TEXT})
    evidence(service, investigation_id, 'https://candidate.test/login', 'page_content', {'text': LEXICAL_TEXT})
    before = insights.rank_candidates(service, investigation_id)['items'][0]
    evidence(service, investigation_id, 'https://candidate.test/login', 'page_browser',
             {'text': LEXICAL_TEXT.replace('mesai', 'çalışma')}, minute=2)
    after = insights.rank_candidates(service, investigation_id)['items'][0]
    assert after['score'] == before['score']
    assert len(after['reasons']) == 1
    assert after['reasons'][0]['strength'] == 'strong'


def test_watch_state_uses_stable_semantic_values_and_omits_unobserved_fields(service):
    investigation_id = case(service)
    old = evidence(service, investigation_id, 'seed.test', 'dns_a',
                   {'answer': '198.51.100.1', 'observed_ip': '198.51.100.1', 'ttl': 300}, provider='dns')
    new = evidence(service, investigation_id, 'seed.test', 'dns_a',
                   {'answer': '198.51.100.1', 'observed_ip': '198.51.100.1', 'ttl': 45}, provider='dns', minute=4)
    first = run(service, investigation_id, 0, [old])
    second = run(service, investigation_id, 3, [new])
    failed = run(service, investigation_id, 6, [], status='failed')
    assert insights.watch_state(service, investigation_id, first) == {
        '["seed.test","dns","dns_a","observed_ip"]': '["198.51.100.1"]',
    }
    assert insights.watch_state(service, investigation_id, second) == insights.watch_state(service, investigation_id, first)
    assert insights.watch_state(service, investigation_id, failed) == {}


def test_watch_state_requires_exact_run_in_same_case(service):
    first, second = case(service), case(service, 'other.test')
    foreign = run(service, second, 0, [])
    approximate = job(service, first, 0)
    for run_id in (foreign, approximate, 'missing'):
        with pytest.raises(NotFoundError):
            insights.watch_state(service, first, run_id)


def test_watch_state_omits_empty_values_but_preserves_false_and_zero(service):
    investigation_id = case(service)
    page = evidence(service, investigation_id, 'https://seed.test/', 'page_content',
                    {'text': '', 'title': None, 'forms': [], 'metadata': {}, 'credential_form': False, 'bytes': 0})
    run_id = run(service, investigation_id, 0, [page])
    assert insights.watch_state(service, investigation_id, run_id) == {
        '["https://seed.test/","fixture","page_content","bytes"]': '[0]',
        '["https://seed.test/","fixture","page_content","credential_form"]': '[false]',
    }
