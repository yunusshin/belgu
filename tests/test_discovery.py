"""Behavioral checks for discovery using recorded upstream responses, no live targets."""
from datetime import datetime, timezone
import json
import httpcore

from belgu.domain.contracts import EntityRef, Limits
from belgu.core.providers.base import Budget, CollectionContext, parse_time
from belgu.core.providers.reverse_ip import ReverseIpProvider
from belgu.core.providers.urlscan import UrlscanProvider
from belgu.core.providers.page import PageParser, PageProvider
from belgu.core.network import FetchResult


class FixtureHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ScriptedHttp:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def context(body, status=200):
    http = FixtureHttp(FetchResult('https://fixture.test/', status, {}, body, ()))
    return CollectionContext(http, Budget(Limits()), lambda: datetime.now(timezone.utc))


def test_reverse_ip_keeps_upstream_source_and_observation_date():
    ctx = context(json.dumps({'data': [{'rrtype': 'a', 'answer': '203.0.113.4',
        'query': 'candidate.test', 'lastSeenTimestamp': 1700000000000}]}).encode())
    result = ReverseIpProvider('mnemonic').collect(EntityRef('ip', '203.0.113.4'), ctx)
    assert result.status == 'ok'
    assert result.provider == 'reverse_ip.mnemonic'
    assert result.observations[0].subject.value == 'candidate.test'
    assert result.observations[0].observed_at.year == 2023
    assert result.relations[0].kind == 'observed_on'
    assert result.relations[0].evidence_indexes == (0,)


def test_rate_limit_is_visible_and_not_an_empty_success():
    result = UrlscanProvider().collect(EntityRef('domain', 'candidate.test'), context(b'{}', 429))
    assert result.status == 'rate_limited'
    assert result.error_code == 'upstream_rate_limited'


def test_urlscan_preserves_full_url_and_scan_reference():
    ctx = context(json.dumps({'results': [{'_id': 'scan-1',
        'task': {'time': '2026-09-07T10:00:00Z'},
        'page': {'domain': 'candidate.test', 'ip': '203.0.113.4',
                 'url': 'https://candidate.test/Giris?ref=A%2Fb', 'title': 'Destek'}}]}).encode())
    result = UrlscanProvider().collect(EntityRef('domain', 'candidate.test'), ctx)
    assert ctx.http.calls[0][1]['params']['q'] == 'page.domain.keyword:"candidate.test"'
    assert result.observations[0].payload['url'].endswith('/Giris?ref=A%2Fb')
    assert result.observations[0].source_ref.endswith('/scan-1/')
    assert result.observations[0].observed_at is not None


def test_urlscan_skips_unrelated_primary_page_even_if_search_returns_it():
    ctx = context(json.dumps({'results': [
        {'_id': 'unrelated', 'task': {'time': '2026-09-07T10:00:00Z'},
         'page': {'domain': 'third-party.test', 'ip': '203.0.113.90', 'url': 'https://third-party.test/'}},
        {'_id': 'matched', 'task': {'time': '2026-09-07T10:01:00Z'},
         'page': {'domain': 'candidate.test', 'ip': '203.0.113.4', 'url': 'https://candidate.test/login'}},
    ]}).encode())
    result = UrlscanProvider().collect(EntityRef('domain', 'candidate.test'), ctx)
    assert [item.subject.value for item in result.observations] == ['candidate.test']
    assert result.observations[0].source_ref.endswith('/matched/')
    assert all('third-party.test' not in str(item) for item in result.relations)


def test_urlscan_ipv6_query_is_escaped_and_only_matching_primary_ip_is_kept():
    ctx = context(json.dumps({'results': [
        {'_id': 'wrong-ip', 'task': {'time': '2026-09-07T10:00:00Z'},
         'page': {'domain': 'wrong.test', 'ip': '2001:db8::2', 'url': 'https://wrong.test/'}},
        {'_id': 'right-ip', 'task': {'time': '2026-09-07T10:01:00Z'},
         'page': {'domain': 'right.test', 'ip': '2001:0db8:0:0:0:0:0:1', 'url': 'https://right.test/Giris?ref=A%2Fb'}},
    ]}).encode())
    result = UrlscanProvider().collect(EntityRef('ip', '2001:db8::1'), ctx)
    assert ctx.http.calls[0][1]['params']['q'] == 'page.ip:"2001\\:db8\\:\\:1"'
    assert [item.subject.value for item in result.observations] == ['right.test']
    assert result.observations[0].payload['url'].endswith('/Giris?ref=A%2Fb')
    observed = next(edge for edge in result.relations if edge.kind == 'observed_on')
    assert observed.dst == EntityRef('ip', '2001:db8::1')


def test_page_parser_extracts_visible_copy_and_form_without_running_scripts():
    parser = PageParser()
    parser.feed('<title>Destek</title><script>ignore()</script><h1>Giriş</h1>'
                '<form action="/check"><input type="password"></form><script src="/app.js"></script>')
    assert parser.title == 'Destek'
    assert 'ignore()' not in parser.text
    assert parser.credential_form
    assert parser.scripts == ['/app.js']


def test_budget_does_not_restart_after_limit():
    budget = Budget(Limits(max_requests=2))
    assert budget.take_request()
    assert budget.take_request()
    assert not budget.take_request()
    assert budget.snapshot()['requests'] == 2


def test_provider_observation_offset_is_converted_to_utc():
    observed = parse_time('2026-09-08T10:00:00+03:00')
    assert observed == datetime(2026, 9, 8, 7, 0, tzinfo=timezone.utc)


def test_redirect_certificate_belongs_to_final_host():
    ctx = context(b'')
    ctx.http.response = FetchResult('https://landing.test/signin', 200,
        {'content-type': 'text/html'}, b'<title>Landing</title>',
        ('https://original.test/start',), 'a' * 64)
    result = PageProvider().collect(EntityRef('url', 'https://original.test/start'), ctx)
    certificate = next(edge for edge in result.relations if edge.kind == 'certificate')
    assert certificate.src == EntityRef('domain', 'landing.test')
    page = next(item for item in result.observations if item.kind == 'page_content')
    assert page.subject.value == 'https://landing.test/signin'
    assert page.payload['requested_url'] == 'https://original.test/start'
    assert any(edge.kind == 'redirects_to' and edge.dst.value == 'https://landing.test/signin'
               for edge in result.relations)


def test_bare_domain_records_failed_https_then_http_redirect_400(service):
    final = 'http://198.51.100.8/landpage?origin=fixture%2Ftest'
    http = ScriptedHttp([
        httpcore.ConnectError('[SSL: WRONG_VERSION_NUMBER] fixture'),
        FetchResult(final, 400, {'content-type': 'text/html'}, b'',
                    ('http://fallback.test/',), None),
    ])
    ctx = CollectionContext(http, Budget(Limits(max_requests=5)), lambda: datetime.now(timezone.utc))
    result = PageProvider().collect(EntityRef('domain', 'fallback.test'), ctx)

    assert [call[0] for call in http.calls] == ['https://fallback.test/', 'http://fallback.test/']
    assert result.status == 'partial'
    failed = next(item for item in result.observations if item.kind == 'page_attempt_failed')
    assert failed.subject == EntityRef('url', 'https://fallback.test/')
    assert failed.source_ref == 'https://fallback.test/'
    assert failed.observed_at is not None
    assert failed.payload['failure'] == 'transport'
    assert 'WRONG_VERSION_NUMBER' in failed.payload['reason']
    page = next(item for item in result.observations if item.kind == 'page_content')
    assert page.subject == EntityRef('url', final)
    assert page.payload['requested_url'] == 'http://fallback.test/'
    assert page.payload['status_code'] == 400
    assert page.payload['redirects'] == ['http://fallback.test/']
    assert any(edge.kind == 'redirects_to' and edge.src == EntityRef('url', 'http://fallback.test/')
               and edge.dst == EntityRef('url', final) for edge in result.relations)
    assert any(edge.kind == 'url_host' and edge.src == EntityRef('url', final)
               and edge.dst == EntityRef('ip', '198.51.100.8') for edge in result.relations)
    brand = service.create_brand('Fixture', ['fixture.test'])
    investigation = service.create_investigation(brand.id, 'HTTP fallback fixture')
    service.record_result(investigation.id, result)
    assert len(service.list_evidence(investigation.id)) == 3
    assert any(item.kind == 'ip' and item.canonical_value == '198.51.100.8'
               for item in service.list_entities(investigation.id, limit=100).items)


def test_explicit_https_transport_failure_is_recorded_without_http_fallback():
    http = ScriptedHttp([httpcore.ConnectTimeout('fixture timeout')])
    ctx = CollectionContext(http, Budget(Limits()), lambda: datetime.now(timezone.utc))
    result = PageProvider().collect(EntityRef('url', 'https://explicit.test/Giris?x=1'), ctx)
    assert [call[0] for call in http.calls] == ['https://explicit.test/Giris?x=1']
    assert result.status == 'error'
    assert result.observations[0].kind == 'page_attempt_failed'
    assert result.observations[0].subject.value.endswith('/Giris?x=1')


def test_http_fallback_read_timeout_preserves_both_attempt_failures():
    http = ScriptedHttp([
        httpcore.ConnectError('fixture TLS failure'),
        httpcore.ReadTimeout('fixture HTTP read timeout'),
    ])
    ctx = CollectionContext(http, Budget(Limits()), lambda: datetime.now(timezone.utc))
    result = PageProvider().collect(EntityRef('domain', 'twice-failed.test'), ctx)
    failures = [item for item in result.observations if item.kind == 'page_attempt_failed']
    assert result.status == 'error'
    assert [item.subject.value for item in failures] == [
        'https://twice-failed.test/', 'http://twice-failed.test/',
    ]
    assert [item.payload['error_type'] for item in failures] == ['ConnectError', 'ReadTimeout']
    assert all(item.observed_at is not None for item in failures)


def test_http_403_metadata_is_evidence_and_does_not_fetch_scripts():
    http = ScriptedHttp([
        FetchResult('https://denied.test/login', 403, {'content-type': 'text/html'},
                    b'<title>Denied</title><script src="/must-not-fetch.js"></script>', (), 'a' * 64),
    ])
    ctx = CollectionContext(http, Budget(Limits()), lambda: datetime.now(timezone.utc))
    result = PageProvider().collect(EntityRef('url', 'https://denied.test/login'), ctx)
    assert result.status == 'partial'
    assert result.error_code == 'upstream_http_403'
    assert len(http.calls) == 1
    page = next(item for item in result.observations if item.kind == 'page_content')
    assert page.payload['status_code'] == 403
    assert page.payload['title'] == 'Denied'
    assert any(item.kind == 'tls_certificate' for item in result.observations)
    assert not any(item.kind == 'javascript_content' for item in result.observations)


def test_https_failure_does_not_attempt_http_after_budget_or_cancel_stops():
    for stopped_by in ('budget', 'deadline', 'cancel'):
        calls = []
        max_requests = 1 if stopped_by == 'budget' else 2
        budget = Budget(Limits(max_requests=max_requests, max_seconds=1),
                        cancelled=lambda: stopped_by == 'cancel' and bool(calls))

        class SpendingHttp:
            def get(self, url, **kwargs):
                assert budget.take_request()
                calls.append(url)
                if stopped_by == 'deadline':
                    budget.started -= 2
                raise httpcore.ConnectError('fixture failure')

        ctx = CollectionContext(SpendingHttp(), budget, lambda: datetime.now(timezone.utc))
        result = PageProvider().collect(EntityRef('domain', 'bounded.test'), ctx)
        assert calls == ['https://bounded.test/']
        assert result.status == 'partial'
        assert result.truncated is True
        assert result.error_code == ('cancelled' if stopped_by == 'cancel' else 'collection_limit')
        assert result.observations[0].kind == 'page_attempt_failed'
