"""Idempotent, explicitly fictional memory and device examples for demo mode."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import select

from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult, RelationDraft
from belgu.persistence.models import Decision, Investigation, Submission

OLDER_TITLE = 'Kurgusal önceki marka incelemesi'
TRACE = sha256(b'belgu-distinct-device-flow-v1').hexdigest()
TARGET = 'guvenli-giris-kuzey.test'
URL = 'https://' + TARGET + '/Mobil/Giris'


def seed_intelligence(service, investigation_id):
    inv = service.get_investigation(investigation_id)
    if not inv.demo:
        raise ValueError('Intelligence fixtures require a demo investigation')
    older = next((case for case in service.list_investigations() if case.demo and case.title == OLDER_TITLE), None)
    if older is None:
        brand = service.create_brand('Ada Finans · Kurgusal geçmiş marka', ['ada-finans.test'])
        older = service.create_investigation(brand.id, OLDER_TITLE, demo=True)
        service.add_submission(older.id, 'https://ada-dogrulama.test/hesap', 'analyst_discovery', 'Kurmaca geçmiş kaynak; canlı bir hedef değildir.')
        at = datetime(2026, 8, 22, 9, tzinfo=timezone.utc)
        subject = EntityRef('domain', 'ada-dogrulama.test')
        service.record_result(older.id, ProviderResult('recorded_demo', 'ok', (
            EvidenceDraft(subject, 'javascript_content', 'urn:belgu:demo:older:script', at, at,
                {'js_sha256': TRACE, 'script_url': 'https://ada-dogrulama.test/flow.js', 'bytes': 18421, 'fictional': True}),
            EvidenceDraft(subject, 'dns_a', 'urn:belgu:demo:older:dns', at, at,
                {'answer': '198.51.100.1', 'observed_ip': '198.51.100.1', 'fictional': True}),
        ), (
            RelationDraft(subject, EntityRef('js_hash', TRACE), 'loads_script', (0,)),
            RelationDraft(subject, EntityRef('ip', '198.51.100.1'), 'resolves_to', (1,)),
        )))
        service.set_disposition(older.id, 'needs_review', 'Kurgusal örnek: betik izi kaydedildi. Paylaşımlı IP tek başına sahiplik kanıtı sayılmadı; ek kaynak bekleniyor.')
        with service.repo.transaction() as session:
            row = session.get(Investigation, older.id)
            row.workflow = 'closed'
            row.created_at = at
            row.updated_at = datetime(2026, 8, 23, 10, tzinfo=timezone.utc)
            for sub in session.scalars(select(Submission).where(Submission.investigation_id == older.id)):
                sub.created_at = at
            for decision in session.scalars(select(Decision).where(Decision.investigation_id == older.id)):
                decision.created_at = row.updated_at
    evidence = service.list_evidence(investigation_id)
    changed = False
    if not any(e.payload.get('js_sha256') == TRACE for e in evidence):
        when = datetime(2026, 9, 7, 20, 16, tzinfo=timezone.utc)
        subject = EntityRef('domain', TARGET)
        service.record_result(investigation_id, ProviderResult('recorded_demo', 'ok', (
            EvidenceDraft(subject, 'javascript_content', 'urn:belgu:demo:current:memory-script', when, when,
                {'js_sha256': TRACE, 'script_url': URL + '/flow.js', 'bytes': 18421, 'fictional': True}),
        ), (RelationDraft(subject, EntityRef('js_hash', TRACE), 'loads_script', (0,)),)))
        changed = True
    assets = Path(__file__).with_name('assets')
    manifest = json.loads((assets / 'fictional-device-manifest.json').read_text())
    for profile, captured in manifest.items():
        if any(e.payload.get('fixture_version') == 'device-v1' and e.payload.get('profile') == profile for e in evidence):
            continue
        image = service.attach_to_investigation(investigation_id, (assets / f'fictional-device-{profile}.png').read_bytes(), 'image/png')
        at = datetime.fromisoformat(captured['observed_at'])
        payload = {**captured, 'url': URL, 'requested_url': URL, 'final_url': URL, 'artifact_id': image.id,
            'status_code': 200, 'fictional': True, 'ocr_text': captured['ocr']['text'],
            'ocr_status': captured['ocr']['status'], 'limitations': [
                'Paketlenmiş kurmaca HTML, bu profilde Chromium ile yerel olarak görüntülendi; canlı banka sayfası değildir.',
                'Cihaz görünümleri örnek için farklı tasarlanmıştır; görünüm farkı kasıtlı gizleme kanıtı değildir.',
                'Kutular statik tasarım öğeleridir; gerçek form alanı veya veri gönderimi yoktur.',
            ]}
        subject = EntityRef('url', URL)
        service.record_result(investigation_id, ProviderResult('recorded_demo', 'ok', (
            EvidenceDraft(subject, 'page_browser', f'urn:belgu:demo:device-v1:{profile}', at, at, payload),
        ), (RelationDraft(subject, EntityRef('domain', TARGET), 'url_host', (0,)),)))
        changed = True
    if changed:
        analyses = service.list_analyses(investigation_id)
        if analyses:
            output = dict(analyses[0].output)
            output['prompt_version'] = 'belgu-demo-v4'
            output['evidence_ids'] = [e.id for e in service.list_evidence(investigation_id)]
            output['uncertainties'] = list(dict.fromkeys([*output.get('uncertainties', []),
                'Cihaz profilleri ayrı kaydedilmiş kurmaca sayfa gözlemleridir; yerel metin modeli görüntüleri okumaz.']))
            service.save_analysis(investigation_id, output, recorded_demo=True)
