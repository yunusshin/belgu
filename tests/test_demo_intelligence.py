from collections import Counter
from pathlib import Path

from belgu.demo.fixtures import seed_demo


def test_demo_has_historical_memory_sources_and_independently_rendered_profiles(service):
    active_id = seed_demo(service)
    cases = service.list_investigations()
    older = next((case for case in cases if case.title == 'Kurgusal önceki marka incelemesi'), None)
    assert older is not None
    assert older.demo and older.workflow == 'closed'
    previous = service.get_investigation(older.id)
    assert previous.decisions and previous.decisions[-1].note
    active = service.list_evidence(active_id)
    old = service.list_evidence(older.id)
    active_hashes = {e.payload.get('js_sha256') for e in active if e.kind == 'javascript_content'}
    older_hashes = {e.payload.get('js_sha256') for e in old if e.kind == 'javascript_content'}
    assert active_hashes & older_hashes
    profile_records = [e for e in active if e.payload.get('fixture_version') == 'device-v1']
    assert Counter(e.payload['profile'] for e in profile_records) == {'desktop': 1, 'mobile': 1}
    image_bytes = []
    for evidence in profile_records:
        p = evidence.payload
        assert p['requested_url'] == 'https://guvenli-giris-kuzey.test/Mobil/Giris'
        assert p['text_source'] == 'recorded_browser_dom'
        assert p['ocr']['source'] == 'screenshot'
        assert p['credential_form'] is False
        artifact, image_path = service.get_artifact(p['artifact_id'], investigation_id=active_id)
        raw = image_path.read_bytes()
        assert raw.startswith(b'\x89PNG') and artifact.size_bytes == len(raw)
        image_bytes.append(raw)
    assert image_bytes[0] != image_bytes[1]
    before = {case.id: len(service.list_evidence(case.id)) for case in cases}
    assert seed_demo(service) == active_id
    assert {case.id: len(service.list_evidence(case.id)) for case in service.list_investigations()} == before
    assert not service.list_analyses(active_id)[0].stale


def test_recorded_device_manifest_matches_packaged_rasters():
    import hashlib
    import json

    assets = Path(__file__).parents[1] / 'src/belgu/demo/assets'
    manifest = assets / 'fictional-device-manifest.json'
    assert manifest.is_file()
    for profile, item in json.loads(manifest.read_text()).items():
        raw = (assets / f'fictional-device-{profile}.png').read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item['image_sha256']
        assert item['profile'] == profile
        assert item['viewport']['width'] == (1365 if profile == 'desktop' else 390)
