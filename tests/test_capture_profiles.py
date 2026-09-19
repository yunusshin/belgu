import struct
import threading
import time
import httpcore
from belgu.core.network import SafeHttpClient, FetchResult
from test_capture import capture_case, require_browser

PROFILE_HTML = b'''<meta name="viewport" content="width=device-width, initial-scale=1"><style>
body{background:#345;color:white}.mobile{display:none}@media(max-width:500px){body{background:#a64}.mobile{display:block}.desktop{display:none}}</style>
<h1 class="desktop">Desktop layout</h1><h1 class="mobile">Mobile layout</h1><p id="ua"></p>
<script>document.querySelector('#ua').textContent=navigator.userAgent+' / touch '+navigator.maxTouchPoints;</script>'''


def test_real_chromium_profile_changes_page_viewport_user_agent_and_touch(service, capture_case, monkeypatch):
    from belgu.application.capture import capture_target
    from belgu.core import browser_capture
    require_browser()
    requests = []
    def get(self, url, **kwargs):
        assert self.budget.take_request()
        requests.append(kwargs.get('headers', {}))
        return FetchResult(url, 200, {'content-type': 'text/html'}, PROFILE_HTML, ())
    monkeypatch.setattr(SafeHttpClient, 'get', get)
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: None)
    payloads = []
    for profile in ('desktop', 'mobile'):
        result = capture_target(service, capture_case.id, 'https://fixture.test/', profile=profile)
        assert result['status'] == 'completed', result
        payload = service.get_evidence(capture_case.id, result['evidence_ids'][0]).payload
        _, path = service.get_artifact(payload['artifact_id'], investigation_id=capture_case.id)
        size = (1365, 900) if profile == 'desktop' else (390, 844)
        assert struct.unpack('>II', path.read_bytes()[16:24]) == size
        assert payload['profile'] == profile
        assert payload['viewport'] == dict(zip(('width', 'height'), size))
        assert f'{profile.title()} layout' in payload['text']
        assert ('Mobile' in payload['user_agent']) == (profile == 'mobile')
        assert payload['user_agent'] in payload['text']
        assert payload['has_touch'] == (profile == 'mobile')
        assert f"/ touch {1 if profile == 'mobile' else 0}" in payload['text']
        assert any(h.get('User-Agent') == payload['user_agent'] for h in requests)
        payloads.append(payload)
    assert payloads[0]['image_sha256'] != payloads[1]['image_sha256']


def test_mobile_failure_keeps_requested_profile(service, capture_case, monkeypatch):
    from belgu.application.capture import capture_target
    def fail(*args, **kwargs):
        raise httpcore.ConnectTimeout('fixture offline')
    monkeypatch.setattr(SafeHttpClient, 'get', fail)
    result = capture_target(service, capture_case.id, 'https://fixture.test/', profile='mobile')
    payload = service.get_evidence(capture_case.id, result['evidence_ids'][0]).payload
    assert payload['profile'] == 'mobile'
    assert payload['viewport'] == {'width': 390, 'height': 844}
    assert 'Mobile' in payload['user_agent']
    assert not payload.get('artifact_id')


def test_cancellation_stops_active_mobile_page(service, capture_case, monkeypatch):
    from belgu.application.capture import capture_target
    require_browser()
    stop = threading.Event()
    def get(self, url, **kwargs):
        self.budget.take_request()
        threading.Timer(.4, stop.set).start()
        return FetchResult(url, 200, {'content-type': 'text/html'}, b'<script>while(true){}</script>', ())
    monkeypatch.setattr(SafeHttpClient, 'get', get)
    started = time.monotonic()
    result = capture_target(service, capture_case.id, 'https://fixture.test/', profile='mobile', cancelled=stop.is_set)
    assert time.monotonic() - started < 6
    assert result['status'] == 'cancelled'
    assert result['counts']['captures'] == 0


def test_api_two_profiles_are_independent_jobs_with_real_worker_observations(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from belgu.api.app import create_app
    from belgu.application.jobs import Worker
    from belgu.settings import Settings
    from belgu.core import browser_capture
    require_browser()
    def get(self, url, **kwargs):
        assert self.budget.take_request()
        return FetchResult(url, 200, {'content-type': 'text/html'}, PROFILE_HTML, ())
    monkeypatch.setattr(SafeHttpClient, 'get', get)
    monkeypatch.setattr(browser_capture, 'ocr_executable', lambda: None)
    app = create_app(Settings(db_url=f'sqlite:///{tmp_path}/profiles.db', evidence_dir=tmp_path/'images', start_worker=False, mode='operational'))
    with TestClient(app) as client:
        service = app.state.service
        brand = service.create_brand('Profiles', ['fixture.test'])
        case = service.create_investigation(brand.id, 'Profile jobs')
        base = f'/api/investigations/{case.id}'
        jobs = [client.post(base+'/captures', json={'url': 'https://fixture.test/', 'profile': profile}).json() for profile in ('desktop', 'mobile')]
        assert len({j['id'] for j in jobs}) == 2
        assert client.post(base+'/captures', json={'url':'fixture.test','profile':'both'}).status_code == 422
        worker = Worker(service)
        for _ in jobs:
            worker._execute(worker.jobs.claim(worker.worker_id))
        assert all(worker.jobs.get(j['id']).status == 'completed' for j in jobs)
        captures = client.get(base+'/captures').json()['items']
        assert {c['profile'] for c in captures} == {'desktop', 'mobile'}
        assert all(c['legacy_profile'] is False for c in captures)
        default = client.post(base+'/captures', json={'url': 'fixture.test'}).json()
        assert worker.jobs.cancel(default['id']).status == 'cancelled'
        assert worker.jobs.claim(worker.worker_id) is None


def test_legacy_profile_does_not_invent_a_user_agent():
    from belgu.core.browser_capture import observation_profile
    result = observation_profile({})
    assert result['profile'] == 'desktop'
    assert result['legacy_profile'] is True
    assert 'eski kayıt' in result['profile_label']
    assert result['user_agent'] is None
