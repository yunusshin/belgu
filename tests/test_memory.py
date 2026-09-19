from datetime import datetime, timezone, timedelta

import pytest

from belgu.domain.contracts import ProviderResult, EvidenceDraft, EntityRef
from belgu.persistence.models import Decision, Investigation

AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


def case(service, title='Case', demo=False):
    brand = service.create_brand(title, [])
    return service.create_investigation(brand.id, title, demo=demo)


def record(service, inv, field='js_sha256', value='a' * 64, minute=0, **extra):
    return service.record_result(inv.id, ProviderResult('page', 'ok', (
        EvidenceDraft(EntityRef('domain', f'{inv.id}.test'),
                      'dns_a' if field == 'answer' else 'javascript_content', 'https://source.test/app.js',
                      AT, AT + timedelta(minutes=minute), {field: value, **extra}),
    ))).evidence_ids[0]


def memory(service, inv, **kwargs):
    from belgu.application.memory import cross_investigation_memory
    return cross_investigation_memory(service, inv.id, **kwargs)


def test_repeated_js_is_scoped_and_preserves_closed_decision(service):
    current, older = case(service), case(service, 'Older')
    a, b = record(service, current), record(service, older)
    with service.repo.transaction() as session:
        session.get(Investigation, older.id).workflow = 'closed'
        session.add(Decision(investigation_id=older.id, value='benign', note='Ortak tedarikçi doğrulandı.', created_at=AT))
    match = memory(service, current)['items'][0]
    assert {ref['investigation_id'] for ref in match['evidence_refs']} == {current.id, older.id}
    assert {ref['evidence_id'] for ref in match['evidence_refs']} == {a, b}
    assert all(ref['observed_at'] and ref['retrieved_at'] for ref in match['evidence_refs'])
    assert match['brand_name'] == 'Older'
    assert match['workflow'] == 'closed' and match['disposition'] == 'benign'
    assert match['decision']['note'] == 'Ortak tedarikçi doğrulandı.'
    assert match['decision']['created_at'].startswith('2026-09-01')


def test_ip_and_common_library_have_lower_priority_and_retrievals_do_not_vote(service):
    current, custom, ip, common = [case(service, title) for title in ('Current', 'Custom', 'IP', 'Common')]
    record(service, current)
    record(service, custom)
    record(service, current, 'answer', '198.51.100.9')
    record(service, ip, 'answer', '198.51.100.9')
    record(service, current, value='b' * 64)
    record(service, common, value='b' * 64, script_url='https://cdn.test/jquery.min.js')
    before = memory(service, current)
    for minute in range(1, 8):
        record(service, custom, minute=minute)
    after = memory(service, current)
    scores = {item['investigation_id']: item['score'] for item in after['items']}
    assert scores[custom.id] > scores[ip.id] > scores[common.id]
    assert scores == {item['investigation_id']: item['score'] for item in before['items']}
    assert len(next(item for item in after['items'] if item['investigation_id'] == custom.id)['reasons']) == 1


def test_demo_live_isolation_and_invalid_dns_never_match(service):
    current, old, demo = case(service), case(service), case(service, demo=True)
    record(service, current)
    record(service, demo)
    for value in ('', 'NXDOMAIN', None, 'not-an-ip'):
        record(service, current, 'answer', value)
        record(service, old, 'answer', value)
    assert memory(service, current)['items'] == []


def test_pagination_has_no_duplicates_and_rejects_stale_cursor(service):
    current = case(service)
    record(service, current)
    for index in range(3):
        record(service, case(service, str(index)))
    first = memory(service, current, limit=1)
    again = memory(service, current, limit=1)
    assert first == again
    second = memory(service, current, limit=2, cursor=first['next_cursor'])
    assert len(second['items']) == 2 and second['next_cursor'] is None
    assert first['items'][0]['investigation_id'] not in {x['investigation_id'] for x in second['items']}
    record(service, case(service, 'New'))
    with pytest.raises(ValueError, match='değişti'):
        memory(service, current, cursor=first['next_cursor'])


def test_coverage_explicit_when_server_caps_observations(service, monkeypatch):
    import belgu.application.memory as module
    current, old = case(service), case(service)
    record(service, current)
    for minute in range(3):
        record(service, old, minute=minute)
    monkeypatch.setattr(module, 'MAX_FOREIGN_OBSERVATIONS', 2)
    result = memory(service, current)
    assert result['coverage']['truncated'] is True
    assert result['limitations']


def test_negative_dns_response_does_not_become_shared_ip(service):
    inv, old = case(service), case(service)
    record(service, inv, 'answer', '198.51.100.9', rcode='NXDOMAIN')
    record(service, old, 'answer', '198.51.100.9', rcode='NXDOMAIN')
    assert memory(service, inv)['items'] == []


@pytest.mark.parametrize('kind,value', [('domain', 'repeated.test'), ('url', 'https://repeated.test/exact/path?q=1')])
def test_exact_observed_subject_match_is_scoped_weak_and_deduplicated(service, kind, value):
    current, previous, demo = case(service), case(service), case(service, demo=True)
    def observe(inv, minute):
        return service.record_result(inv.id, ProviderResult('page', 'ok', (
            EvidenceDraft(EntityRef(kind, value), 'page_content', value, AT,
                          AT + timedelta(minutes=minute), {'status_code': 200}),
        ))).evidence_ids[0]
    current_id, previous_id = observe(current, 0), observe(previous, 0)
    observe(demo, 0)
    first = memory(service, current)
    assert len(first['items']) == 1
    match = first['items'][0]
    assert match['investigation_id'] == previous.id
    assert {ref['investigation_id'] for ref in match['evidence_refs']} == {current.id, previous.id}
    assert {ref['evidence_id'] for ref in match['evidence_refs']} == {current_id, previous_id}
    assert match['priority'] == 'low' and 0 < match['score'] < 6
    assert match['reasons'][0]['value'] == value
    for minute in range(1, 4):
        observe(current, minute)
        observe(previous, minute)
    again = memory(service, current)['items'][0]
    assert again['score'] == match['score']
    assert len(again['reasons']) == 1 and len(again['evidence_refs']) == 2


def test_shared_submitted_entity_without_observations_is_not_memory_evidence(service):
    current, previous = case(service), case(service)
    for inv in (current, previous):
        service.add_submission(inv.id, 'unobserved.test', 'analyst_discovery')
    assert memory(service, current)['items'] == []
