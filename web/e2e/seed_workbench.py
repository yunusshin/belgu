"""Synthetic evidence in the temporary browser-test database only; never imported by the app."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult
from belgu.persistence.models import Job, WatchAlert
from belgu.application.insights import record_run
from belgu.application.watches import WatchService


def seed_workbench(service):
    brand = service.create_brand('Tarayıcı çalışma masası', ['official-browser.test'])
    case = service.create_investigation(brand.id, 'Çalışma masası tarayıcı doğrulaması')
    service.add_submission(case.id, 'https://browser-workbench.test/login', 'analyst_discovery')
    start = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
    image = (Path(__file__).resolve().parents[2] / 'src/belgu/demo/assets/fictional-login.png').read_bytes()
    artifact = service.attach_to_investigation(case.id, image, 'image/png')

    def evidence(host, kind, payload, minute=0, provider='browser_fixture'):
        at = start + timedelta(minutes=minute)
        return service.record_result(case.id, ProviderResult(provider, 'ok', (
            EvidenceDraft(EntityRef('url' if '://' in host else 'domain', host), kind,
                          'https://browser-workbench.test/login', at, at, payload),
        ))).evidence_ids[0]

    capture = evidence('https://browser-workbench.test/login', 'page_browser', {
        'artifact_id': artifact.id, 'url': 'https://browser-workbench.test/login',
        'final_url': 'https://browser-workbench.test/login', 'status_code': 200,
        'text': 'Kurmaca tarayıcı kanıtı. Giriş yapın.', 'credential_form': True,
        'ocr_text': 'Kurmaca giriş ekranı', 'ocr_status': 'ok',
        'ocr': {'engine': 'fixture', 'languages': 'tur', 'source': 'screenshot', 'limitations': []},
        'forms': [{'action': 'https://browser-workbench.test/login', 'method': 'post',
                   'inputs': [{'name': 'parola', 'type': 'password', 'required': True, 'visible': True}]}],
        'limitations': ['Yalıtılmış test verisi; canlı yakalama değildir.'],
    }, provider='browser_capture')
    old = evidence('browser-workbench.test', 'dns_a', {'answer': '198.51.100.21', 'observed_ip': '198.51.100.21'}, provider='dns')
    new = evidence('browser-workbench.test', 'dns_a', {'answer': '198.51.100.22', 'observed_ip': '198.51.100.22'}, minute=5, provider='dns')
    evidence('related-browser.test', 'dns_a', {'observed_ip': '198.51.100.22'}, provider='dns')
    for host in ['browser-workbench.test', 'related-browser.test']:
        evidence(host, 'javascript_content', {'js_sha256': 'e' * 64})
    for minute, ids in [(0, [old, capture]), (5, [new, capture])]:
        with service.repo.transaction() as session:
            job = Job(investigation_id=case.id, kind='collect', status='completed',
                      created_at=start + timedelta(minutes=minute), updated_at=start + timedelta(minutes=minute + 1))
            session.add(job); session.flush(); job_id = job.id
        record_run(service, job_id, ids)
    service.save_analysis(case.id, {'summary': 'Yalıtılmış test gözlemi.', 'claims': [
        {'text': 'Yakalanan sayfada parola alanı gözlendi.', 'kind': 'observation', 'evidence_ids': [capture]},
        {'text': 'Desteksiz test hipotezi.', 'kind': 'hypothesis', 'evidence_ids': ['missing-fixture-evidence']},
    ]}, recorded_demo=True)
    watch = WatchService(service).create(case.id, interval_minutes=60, enabled=False)
    with service.repo.transaction() as session:
        session.add(WatchAlert(watch_id=watch['id'], investigation_id=case.id, kind='change',
                               message='Test kaydında DNS adresi değişti.', job_id=job_id, read=False))
