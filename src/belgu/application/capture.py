"""Persist screenshots, separately attributed OCR and explicit capture failures."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from belgu.core import browser_capture
from belgu.core.network import FetchLimitExceeded
from belgu.core.providers.base import Budget
from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult, RelationDraft
from belgu.domain.targets import parse_target


def capture_status() -> dict:
    return browser_capture.capabilities()


def capture_target(service, investigation_id, url, *, cancelled=None, progress=None, profile='desktop') -> dict:
    settings = browser_capture.profile_settings(profile)
    investigation = service.get_investigation(investigation_id)
    target = parse_target(url)
    if target.kind == 'domain':
        url = 'https://' + target.canonical_value + '/'
    elif target.kind == 'url':
        url = target.canonical_value
    else:
        raise ValueError('Görsel yakalama için HTTP(S) adresi veya alan adı gerekli.')
    budget = Budget(browser_capture.CAPTURE_LIMITS, cancelled=cancelled)
    counts = {'requests': 0, 'entities': 0, 'observations': 0, 'captures': 0}
    if cancelled and cancelled():
        return {'status': 'cancelled', 'counts': counts, 'evidence_ids': [], 'message': 'İptal edildi'}
    if investigation.demo:
        return {'status': 'failed', 'counts': counts, 'evidence_ids': [],
                'error': 'demo_network_disabled', 'message': 'Demo araştırmasında ağ yakalaması kapalı.'}
    if progress:
        progress({'requests': 0, 'message': 'Görsel kanıt yakalaması başlıyor'})
    try:
        png, payload, observed_at = browser_capture.capture_browser(
            url, budget=budget, cancelled=cancelled, progress=progress, profile=profile)
        if cancelled and cancelled():
            raise browser_capture.CaptureCancelled('Görsel yakalama iptal edildi.')
        if progress:
            progress({**budget.snapshot(), 'message': 'Görsel kaydediliyor; yerel OCR çalıştırılıyor'})
        ocr = browser_capture.extract_ocr(png, cancelled=cancelled)
        if cancelled and cancelled():
            raise browser_capture.CaptureCancelled('Görsel yakalama iptal edildi.')
        artifact = service.attach_to_investigation(investigation_id, png, 'image/png')
        payload.update({**settings, 'artifact_id': artifact.id, 'image_sha256': sha256(png).hexdigest(),
            'ocr': ocr, 'ocr_text': ocr['text'], 'ocr_status': ocr['status']})
        payload['limitations'].extend(ocr['limitations'])
        if ocr['status'] == 'unavailable':
            payload['limitations'].append('Yerel OCR kurulu olmadığı için görüntüden metin çıkarılmadı.')
        elif ocr['status'] == 'error':
            payload['limitations'].append('Yerel OCR başarısız oldu; DOM metni OCR sonucu değildir.')
        final = parse_target(payload['final_url'])
        subject = EntityRef('url', final.canonical_value)
        hostname = parse_target(final.hostname)
        partial = payload['status_code'] >= 400 or bool(payload['failed_requests'])
        truncated = any(item['error_type'] == 'FetchLimitExceeded' for item in payload['failed_requests'])
        observation = EvidenceDraft(subject, 'page_browser', final.canonical_value, observed_at,
            datetime.now(timezone.utc), payload)
        result = ProviderResult('browser_capture', 'partial' if partial else 'ok', (observation,),
            (RelationDraft(subject, EntityRef(hostname.kind, hostname.canonical_value), 'url_host', (0,)),),
            truncated=truncated)
        saved = service.record_result(investigation_id, result)
        counts.update({'requests': budget.requests, 'entities': 1, 'observations': 1, 'captures': 1})
        return {'status': 'partial' if partial else 'completed', 'counts': counts,
            'evidence_ids': saved.evidence_ids, 'truncated': truncated,
            'message': ('Görsel kanıt kaydedildi; bazı sayfa kaynakları alınamadı.' if partial
                        else 'Görsel kanıt, görünür metin ve form alanları kaydedildi.'),
            'ocr_status': ocr['status']}
    except Exception as exc:
        is_cancelled = isinstance(exc, browser_capture.CaptureCancelled) or bool(cancelled and cancelled())
        status = 'cancelled' if is_cancelled else 'failed'
        timestamp = datetime.now(timezone.utc)
        payload = {**settings, 'url': url, 'requested_url': url, 'status': status,
            'error_type': type(exc).__name__, 'reason': str(exc)[:1000],
            'observed_at': timestamp.isoformat(), 'requests': budget.requests}
        saved = service.record_result(investigation_id, ProviderResult('browser_capture', 'error', (
            EvidenceDraft(EntityRef('url', url), 'page_capture_failed', url, timestamp, timestamp, payload),
        ), error_code=type(exc).__name__))
        counts.update({'requests': budget.requests, 'observations': 1})
        return {'status': status, 'counts': counts, 'evidence_ids': saved.evidence_ids,
            'truncated': isinstance(exc, FetchLimitExceeded),
            'error': f'{type(exc).__name__}: {str(exc)[:1000]}',
            'message': 'Görsel yakalama iptal edildi.' if is_cancelled else 'Görsel yakalama başarısız; önceki kanıtlar korunuyor.'}
