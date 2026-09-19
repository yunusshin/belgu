from datetime import datetime, timedelta, timezone

import pytest

from belgu.application.insights import rank_candidates
from belgu.application.service import NotFoundError
from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult


def case(service, target='seed.test'):
    brand = service.create_brand('Query fixture', ['official.test'])
    inv = service.create_investigation(brand.id, 'Query fixture')
    service.add_submission(inv.id, target, 'analyst_discovery')
    return inv.id


def record(service, inv, subject, payload, kind='dns_a', when=None):
    now = datetime.now(timezone.utc)
    return service.record_result(inv, ProviderResult('fixture', 'ok', (
        EvidenceDraft(EntityRef('url' if '://' in subject else 'domain', subject),
                      kind, 'urn:fixture:'+subject, when or now, now, payload),
    )))


def test_search_finds_entity_beyond_first_page_and_binds_cursor(service):
    inv = case(service)
    for i in range(105):
        record(service, inv, f'candidate-{i:03}.test', {'answer':'198.51.100.1'})
    found = service.list_entities(inv, kind='domain', q='CANDIDATE-104')
    assert found.total_unique == 1
    assert found.items[0].canonical_value == 'candidate-104.test'
    page = service.list_entities(inv, kind='domain', q='candidate-', limit=25)
    assert page.total_unique == 105 and page.next_cursor
    with pytest.raises(ValueError):
        service.list_entities(inv, kind='domain', q='seed', limit=25, cursor=page.next_cursor)
    other = case(service, 'other.test')
    with pytest.raises(ValueError):
        service.list_entities(other, kind='domain', q='candidate-', limit=25, cursor=page.next_cursor)


def test_capture_and_shared_filters_join_exact_url_host_not_substrings(service):
    inv = case(service)
    record(service, inv, 'seed.test', {'observed_ip':'198.51.100.1'})
    record(service, inv, 'other.test', {'observed_ip':'198.51.100.1'})
    record(service, inv, 'seed.test.attacker.test', {'answer':'198.51.100.2'})
    record(service, inv, 'https://seed.test/login', {'artifact_id':'fixture-artifact','js_sha256':'same'}, 'page_browser')
    record(service, inv, 'https://other.test/page', {'js_sha256':'same'}, 'javascript_content')
    capture = service.list_entities(inv, kind='domain', has_capture=True)
    assert [x.canonical_value for x in capture.items] == ['seed.test']
    assert capture.items[0].has_capture is True
    shared = service.list_entities(inv, kind='domain', shared='javascript')
    assert {x.canonical_value for x in shared.items} == {'seed.test','other.test'}
    both = service.list_entities(inv, kind='domain', shared='javascript', has_capture=True)
    assert [x.canonical_value for x in both.items] == ['seed.test']
    foreign = case(service,'foreign.test')
    record(service, foreign, 'https://foreign.test/', {'artifact_id':'foreign','js_sha256':'different'}, 'page_browser')
    assert service.list_entities(inv, kind='domain', q='foreign').total_unique == 0


def test_recent_is_observation_time_and_latest_sort_is_paged(service):
    inv = case(service)
    now = datetime.now(timezone.utc)
    record(service, inv, 'old.test', {'answer':'198.51.100.1'}, when=now-timedelta(days=90))
    record(service, inv, 'new.test', {'answer':'198.51.100.2'}, when=now-timedelta(hours=1))
    record(service, inv, 'newer.test', {'answer':'198.51.100.3'}, when=now)
    page = service.list_entities(inv, kind='domain', recent_hours=24, sort='latest', limit=1)
    assert page.total_unique == 2
    assert page.items[0].canonical_value == 'newer.test'
    second = service.list_entities(inv, kind='domain', recent_hours=24, sort='latest', limit=1, cursor=page.next_cursor)
    assert second.items[0].canonical_value == 'new.test'
    assert second.next_cursor is None


def test_priority_and_candidates_are_scoped_and_paginated(service):
    inv = case(service)
    record(service, inv, 'seed.test', {'observed_ip':'198.51.100.1','cert_sha256':'cert'})
    for i in range(35):
        record(service, inv, f'candidate-{i:02}.test', {'observed_ip':'198.51.100.1'})
    record(service, inv, 'strong.test', {'cert_sha256':'cert'})
    first = rank_candidates(service, inv, 30)
    assert first['total_unique'] == 36 and first['next_cursor']
    second = rank_candidates(service, inv, 30, cursor=first['next_cursor'])
    assert len(second['items']) == 6 and second['next_cursor'] is None
    assert not ({x['entity_id'] for x in first['items']} & {x['entity_id'] for x in second['items']})
    page = service.list_entities(inv, kind='domain', sort='priority', limit=1)
    assert page.items[0].canonical_value == 'strong.test'
    assert page.items[0].priority_score == 25
    with pytest.raises(ValueError):
        rank_candidates(service, case(service,'foreign.test'), 30, cursor=first['next_cursor'])


@pytest.mark.parametrize('options',[{'sort':'bad'},{'shared':'bad'},{'recent_hours':0},{'recent_hours':9000},{'q':'a'*501}])
def test_query_values_are_validated(service,options):
    with pytest.raises(ValueError):
        service.list_entities(case(service), **options)


def test_graph_rejects_foreign_root(service):
    inv = case(service)
    other = case(service,'other.test')
    entity = service.list_entities(other).items[0]
    with pytest.raises(NotFoundError):
        service.graph(inv, root_id=entity.id)


def test_http_filters_and_candidate_cursor_are_exposed(api):
    service = api.app.state.service
    inv = case(service)
    for i in range(32):
        record(service, inv, f'candidate-{i:02}.test', {'observed_ip':'198.51.100.1'})
    record(service, inv, 'seed.test', {'observed_ip':'198.51.100.1'})
    record(service, inv, 'https://candidate-31.test/login', {'artifact_id':'fixture'}, 'page_browser')
    base = f'/api/investigations/{inv}'
    page = api.get(base+'/entities', params={'q':'candidate-31','has_capture':'true','recent_hours':24,'sort':'latest'})
    assert page.status_code == 200
    assert {x['canonical_value'] for x in page.json()['items']} == {'candidate-31.test','https://candidate-31.test/login'}
    assert all(x['has_capture'] for x in page.json()['items'])
    for invalid in ({'sort':'bad'}, {'shared':'bad'}, {'recent_hours':0}, {'has_capture':'bad'}):
        assert api.get(base+'/entities', params=invalid).status_code == 422
    first = api.get(base+'/candidates', params={'limit':30}).json()
    assert len(first['items']) == 30 and first['total_unique'] == 32
    second = api.get(base+'/candidates', params={'limit':30,'cursor':first['next_cursor']})
    assert second.status_code == 200
    assert len(second.json()['items']) == 2 and second.json()['next_cursor'] is None


def test_capture_filter_keeps_uncaptured_url_paths_out(api):
    service = api.app.state.service
    inv = case(service)
    service.add_submission(inv, 'https://seed.test/uncaptured', 'analyst_discovery')
    record(service, inv, 'https://seed.test/captured', {'artifact_id':'fixture'}, 'page_browser')
    response = api.get(f'/api/investigations/{inv}/entities', params={'kind':'url','has_capture':'true'})
    assert [item['canonical_value'] for item in response.json()['items']] == ['https://seed.test/captured']
    assert service.list_entities(inv, kind='domain', has_capture=True).items[0].canonical_value == 'seed.test'
