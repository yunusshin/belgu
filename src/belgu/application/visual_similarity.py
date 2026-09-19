"""Investigation-scoped ranking of stored images; no network or model calls."""
from hashlib import sha256

from belgu.application.service import NotFoundError
from belgu.core.browser_capture import observation_profile
from belgu.core.visual_similarity import MAX_BYTES, METHOD_VERSION, compare_images


def _bytes(service, artifact_id, **scope):
    if not artifact_id:
        raise NotFoundError('missing_artifact')
    _, path = service.get_artifact(artifact_id, **scope)
    with path.open('rb') as source:
        return source.read(MAX_BYTES + 1)


def rank_captures(service, investigation_id, reference_id):
    investigation = service.get_investigation(investigation_id)
    captures = sorted((e for e in service.list_evidence(investigation_id) if e.kind == 'page_browser'),
                      key=lambda e: (e.retrieved_at, e.id), reverse=True)
    reference_capture = next((e for e in captures if e.id == reference_id), None)
    if reference_capture:
        artifact_id = reference_capture.payload.get('artifact_id')
        scope = {'investigation_id': investigation_id}
        reference = {'id': reference_id, 'evidence_id': reference_id, 'artifact_id': artifact_id,
                     'image_url': f'/api/investigations/{investigation_id}/attachments/{artifact_id}',
                     **observation_profile(reference_capture.payload)}
    else:
        # Validate brand scope before handling missing bytes; never treat foreign evidence as a reference.
        service.get_artifact(reference_id, brand_id=investigation.brand_id)
        artifact_id = reference_id
        scope = {'brand_id': investigation.brand_id}
        reference = {'id': reference_id, 'artifact_id': artifact_id,
                     'image_url': f'/api/brands/{investigation.brand_id}/attachments/{artifact_id}'}
    reference_error = None
    try:
        reference_bytes = _bytes(service, artifact_id, **scope)
    except (NotFoundError, OSError):
        reference_bytes = b''
        reference_error = 'reference_artifact_unavailable'
    if reference_capture:
        captures = [e for e in captures if e.id != reference_id]
    items, unassessed, groups = [], [], {}
    duplicates = 0
    for evidence in captures:
        payload = evidence.payload
        item = {'evidence_id': evidence.id, 'evidence_ids': [evidence.id], 'investigation_id': investigation_id,
                'artifact_id': payload.get('artifact_id'), 'url': payload.get('final_url') or payload.get('url'),
                'observed_at': evidence.observed_at, 'retrieved_at': evidence.retrieved_at,
                'image_url': f'/api/investigations/{investigation_id}/attachments/{payload.get("artifact_id")}',
                **observation_profile(payload)}
        try:
            candidate = _bytes(service, payload.get('artifact_id'), investigation_id=investigation_id)
        except (NotFoundError, OSError):
            unassessed.append({**item, 'status': 'unassessed', 'score': None, 'reason': 'capture_artifact_unavailable'})
            continue
        result = compare_images(reference_bytes, candidate)
        if reference_error:
            result = {**result, 'status': 'unassessed', 'score': None, 'reason': reference_error}
        if reference_capture and reference['profile'] != item['profile']:
            result = {**result, 'status': 'unassessed', 'score': None, 'components': {}, 'reason': 'incompatible_profile'}
        if result['status'] != 'assessed':
            unassessed.append({**item, **result})
            continue
        digest = (sha256(candidate).hexdigest(), item['profile'])
        if digest in groups:
            groups[digest]['evidence_ids'].append(evidence.id)
            duplicates += 1
            continue
        item.update(result)
        groups[digest] = item
        items.append(item)
    items.sort(key=lambda item: (-item['score'], item['evidence_id']))
    return {'investigation_id': investigation_id, 'method_version': METHOD_VERSION, 'reference': reference,
            'items': items, 'unassessed': unassessed,
            'coverage': {'captures': len(captures), 'assessed_unique': len(items),
                         'unassessed': len(unassessed), 'duplicates': duplicates},
            'limitations': ['Puan yerel görüntü işleme sezgisidir; marka tanıma, atıf veya zararlılık olasılığı değildir.',
                            'Farklı profil veya uyumsuz en-boy oranlarında sayısal karşılaştırma yapılmaz.',
                            'Aynı görüntü baytları tek puanda gruplanır; tüm gözlem kanıtları korunur.']}
