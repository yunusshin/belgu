"""Real Chromium rendering with isolated databases and deterministic HTTP responses."""
from datetime import datetime, timezone
import struct
import time

import httpcore
import pytest

from belgu.core.network import FetchLimitExceeded, FetchResult, SafeHttpClient


HTML = b'''<!doctype html><html><head><title>Fixture visual evidence</title>
<style>body{font:24px Arial;padding:50px;background:#edf4fa}form{padding:20px;background:white}
.hidden{display:none}</style></head><body><h1>Fixture support desk</h1>
<p id="dynamic"></p><span class="hidden">Hidden text must not appear</span>
<form action="/submit" method="post"><label>Email<input name="email" type="email" required></label>
<label>Password<input id="secret" name="password" type="password" autocomplete="current-password"></label>
<button>Continue</button></form><script src="/app.js"></script></body></html>'''
SCRIPT = b'''document.querySelector('#dynamic').textContent = 'Rendered by JavaScript';
document.querySelector('form').submit();
fetch('/must-not-submit', {method:'POST',body:'no'});
fetch('/must-not-fetch');
new WebSocket('wss://fixture.test/socket');'''


@pytest.fixture
def capture_case(service):
    brand = service.create_brand('Capture fixture', ['fixture.test'])
    return service.create_investigation(brand.id, 'Isolated browser capture')


@pytest.fixture
def fixture_http(monkeypatch):
    """Replace only remote I/O; render and persist through production code."""
    calls = []

    def get(self, url, params=None, headers=None):
        if self.budget and not self.budget.take_request():
            raise FetchLimitExceeded('fixture request budget exhausted')
        calls.append(url)
        if url == 'https://fixture.test/start':
            return FetchResult('https://fixture.test/login', 200,
                {'content-type': 'text/html; charset=utf-8'}, HTML,
                ('https://fixture.test/start',))
        if url == 'https://fixture.test/app.js':
            return FetchResult(url, 200, {'content-type': 'text/javascript'}, SCRIPT, ())
        raise AssertionError(f'Unexpected outbound request: {url}')

    monkeypatch.setattr(SafeHttpClient, 'get', get)
    return calls


def require_browser():
    from belgu.application.capture import capture_status
    if capture_status()['status'] != 'ready':
        pytest.skip('Install Python Playwright and Chromium for the capture integration test')


def test_real_capture_preserves_png_rendered_forms_and_redirect_provenance(
        service, capture_case, fixture_http, monkeypatch):
    from belgu.application import capture
    from belgu.core import browser_capture
    require_browser()
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: None)
    started = datetime.now(timezone.utc)
    summary = capture.capture_target(service, capture_case.id, 'https://fixture.test/start')

    assert summary['status'] == 'completed', summary
    evidence = service.get_evidence(capture_case.id, summary['evidence_ids'][0])
    assert evidence.kind == 'page_browser'
    assert evidence.subject.value == 'https://fixture.test/login'
    assert evidence.source_ref == 'https://fixture.test/login'
    assert evidence.observed_at >= started
    assert evidence.retrieved_at >= evidence.observed_at
    payload = evidence.payload
    assert payload['final_url'] == 'https://fixture.test/login'
    assert payload['requested_url'] == 'https://fixture.test/start'
    assert payload['redirects'] == ['https://fixture.test/start']
    assert payload['status_code'] == 200
    assert 'Rendered by JavaScript' in payload['text']
    assert 'Hidden text must not appear' not in payload['text']
    assert payload['credential_form'] is True
    form = payload['forms'][0]
    assert form['action'] == 'https://fixture.test/submit'
    assert form['method'] == 'post'
    password = next(item for item in form['inputs'] if item['type'] == 'password')
    assert password['name'] == 'password'
    assert password['autocomplete'] == 'current-password'
    assert password['visible'] is True
    assert 'value' not in password
    assert payload['ocr_status'] == 'unavailable'
    assert payload['ocr_text'] == ''
    assert payload['ocr']['source'] == 'screenshot'
    assert payload['text_source'] == 'rendered_dom'
    artifact, path = service.get_artifact(payload['artifact_id'], investigation_id=capture_case.id)
    png = path.read_bytes()
    assert artifact.mime == 'image/png'
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', png[16:24]) == (1365, 900)
    assert len(png) > 1000
    assert set(fixture_http) == {'https://fixture.test/start', 'https://fixture.test/app.js'}


def test_failed_capture_records_attempt_without_erasing_prior_evidence(
        service, capture_case, fixture_http, monkeypatch):
    from belgu.application.capture import capture_target
    from belgu.core import browser_capture
    require_browser()
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: None)
    first = capture_target(service, capture_case.id, 'https://fixture.test/start')
    assert first['status'] == 'completed'
    previous = service.get_evidence(capture_case.id, first['evidence_ids'][0])

    def failed_get(self, *args, **kwargs):
        raise httpcore.ConnectTimeout('fixture could not connect')

    monkeypatch.setattr(SafeHttpClient, 'get', failed_get)
    failed = capture_target(service, capture_case.id, 'https://fixture.test/offline')
    assert failed['status'] == 'failed'
    assert failed['counts']['captures'] == 0
    assert 'ConnectTimeout' in failed['error']
    attempt = service.get_evidence(capture_case.id, failed['evidence_ids'][0])
    assert attempt.kind == 'page_capture_failed'
    assert attempt.payload['error_type'] == 'ConnectTimeout'
    assert 'artifact_id' not in attempt.payload
    assert service.get_evidence(capture_case.id, previous.id) == previous
    _, path = service.get_artifact(previous.payload['artifact_id'], investigation_id=capture_case.id)
    assert path.exists()


def test_pre_cancelled_and_demo_capture_do_not_read_network(service, capture_case, monkeypatch):
    from belgu.application.capture import capture_target

    def forbidden(*args, **kwargs):
        pytest.fail('A cancelled or demo capture must never use the network')

    monkeypatch.setattr(SafeHttpClient, 'get', forbidden)
    cancelled = capture_target(service, capture_case.id, 'https://fixture.test/', cancelled=lambda: True)
    assert cancelled['status'] == 'cancelled'
    assert cancelled['evidence_ids'] == []
    demo = service.create_investigation(capture_case.brand_id, 'Demo capture', demo=True)
    summary = capture_target(service, demo.id, 'https://fixture.test/')
    assert summary['status'] == 'failed'
    assert summary['counts']['requests'] == 0


def test_ocr_distinguishes_empty_output_failure_and_missing_engine(tmp_path, monkeypatch):
    from belgu.core import browser_capture
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: None)
    assert browser_capture.extract_ocr(b'png')['status'] == 'unavailable'

    # Local executable doubles model the external OCR engine, not capture behavior.
    engine = tmp_path / 'tesseract-fixture'
    engine.write_text('#!/bin/sh\ncat >/dev/null\nprintf ""\n')
    engine.chmod(0o755)
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: str(engine))
    result = browser_capture.extract_ocr(b'png')
    assert result['status'] == 'empty'
    assert result['text'] == ''
    assert result['engine'] == 'tesseract'
    assert result['source'] == 'screenshot'

    engine.write_text('#!/bin/sh\ncat >/dev/null\nprintf "Fixture OCR text"\n')
    result = browser_capture.extract_ocr(b'png')
    assert result['status'] == 'ok'
    assert result['text'] == 'Fixture OCR text'

    engine.write_text('#!/bin/sh\nprintf "invalid image" >&2\nexit 1\n')
    result = browser_capture.extract_ocr(b'png')
    assert result['status'] == 'error'
    assert result['text'] == ''
    assert result['error']


def test_status_reports_browser_and_ocr_independently(monkeypatch):
    from belgu.application.capture import capture_status
    from belgu.core import browser_capture
    monkeypatch.setattr(browser_capture, 'browser_executable', lambda: None)
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: '/usr/bin/tesseract')
    status = capture_status()
    assert status['status'] == 'unavailable'
    assert status['browser_available'] is False
    assert status['ocr_available'] is True


def test_request_budget_retains_partial_screenshot_and_records_missing_asset(
        service, capture_case, fixture_http, monkeypatch):
    from belgu.application.capture import capture_target
    from belgu.core import browser_capture
    from belgu.domain.contracts import Limits
    require_browser()
    monkeypatch.setattr(browser_capture, 'CAPTURE_LIMITS', Limits(max_requests=1, max_seconds=15))
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: None)
    summary = capture_target(service, capture_case.id, 'https://fixture.test/start')
    assert summary['status'] == 'partial', summary
    assert summary['truncated'] is True
    assert summary['counts']['requests'] == 1
    payload = service.get_evidence(capture_case.id, summary['evidence_ids'][0]).payload
    assert payload['artifact_id']
    assert payload['failed_requests'][0]['error_type'] == 'FetchLimitExceeded'
    assert 'Rendered by JavaScript' not in payload['text']
    assert fixture_http == ['https://fixture.test/start']


def test_http_error_for_asset_is_explicit_partial_evidence(service, capture_case, monkeypatch):
    from belgu.application.capture import capture_target
    from belgu.core import browser_capture
    require_browser()
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: None)

    def get(self, url, **kwargs):
        assert self.budget.take_request()
        if url == 'https://fixture.test/start':
            return FetchResult(url, 200, {'content-type': 'text/html'},
                               b'<h1>Support</h1><link rel="stylesheet" href="/missing.css">', ())
        return FetchResult(url, 404, {'content-type': 'text/css'}, b'', ())

    monkeypatch.setattr(SafeHttpClient, 'get', get)
    summary = capture_target(service, capture_case.id, 'https://fixture.test/start')
    assert summary['status'] == 'partial', summary
    payload = service.get_evidence(capture_case.id, summary['evidence_ids'][0]).payload
    assert payload['failed_requests'][0]['status_code'] == 404
    assert payload['failed_requests'][0]['url'] == 'https://fixture.test/missing.css'


def test_private_network_target_uses_existing_public_address_policy(service, capture_case):
    from belgu.application.capture import capture_target
    require_browser()
    summary = capture_target(service, capture_case.id, 'http://127.0.0.1:8765/')
    assert summary['status'] == 'failed'
    payload = service.get_evidence(capture_case.id, summary['evidence_ids'][0]).payload
    assert payload['error_type'] == 'NetworkPolicyError'
    assert summary['counts']['captures'] == 0


def test_runaway_page_script_cannot_exceed_capture_deadline(service, capture_case, monkeypatch):
    from belgu.application.capture import capture_target
    from belgu.core import browser_capture
    from belgu.domain.contracts import Limits
    require_browser()
    monkeypatch.setattr(browser_capture, 'CAPTURE_LIMITS', Limits(max_requests=3, max_seconds=2))

    def get(self, url, **kwargs):
        assert self.budget.take_request()
        return FetchResult(url, 200, {'content-type': 'text/html'},
                           b'<h1>Unresponsive page</h1><script>while(true){}</script>', ())

    monkeypatch.setattr(SafeHttpClient, 'get', get)
    started = time.monotonic()
    summary = capture_target(service, capture_case.id, 'https://fixture.test/start')
    assert time.monotonic() - started < 7
    assert summary['status'] == 'failed'
    assert summary['counts']['captures'] == 0


def test_configured_ocr_executable_and_languages_are_used(tmp_path, monkeypatch):
    from belgu.core import browser_capture
    engine = tmp_path / 'custom-tesseract'
    engine.write_text('#!/bin/sh\ncat >/dev/null\nprintf "Selected OCR engine"\n')
    engine.chmod(0o755)
    monkeypatch.setenv('BELGU_TESSERACT_PATH', str(engine))
    monkeypatch.setenv('BELGU_OCR_LANG', 'tur+eng')
    result = browser_capture.extract_ocr(b'png')
    assert result['status'] == 'ok'
    assert result['text'] == 'Selected OCR engine'
    assert result['languages'] == 'tur+eng'


def test_real_local_ocr_reads_the_captured_png(service, capture_case, fixture_http):
    from belgu.application.capture import capture_status, capture_target
    require_browser()
    if not capture_status()['ocr_available']:
        pytest.skip('Install local Tesseract to verify screenshot OCR')
    summary = capture_target(service, capture_case.id, 'https://fixture.test/start')
    assert summary['status'] == 'completed', summary
    payload = service.get_evidence(capture_case.id, summary['evidence_ids'][0]).payload
    assert payload['ocr_status'] == 'ok', payload['ocr']
    assert 'Fixture support desk' in payload['ocr_text']
    assert payload['ocr']['engine'] == 'tesseract'
    assert payload['ocr']['source'] == 'screenshot'
    assert payload['ocr_text'] != payload['text']
