"""Deterministic, case-scoped comparisons and evidence-backed investigation priorities."""
from __future__ import annotations

from collections import defaultdict
from datetime import timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from sqlalchemy import select

from belgu.application.service import NotFoundError
from belgu.persistence.models import (
    CollectionRun, Entity, Investigation, InvestigationEntity, Job, Observation, Submission,
)


_DISCOVERY_KINDS = {'collect', 'expand'}
_TERMINAL = {'completed', 'partial', 'failed', 'cancelled'}
_VOLATILE = {'ttl', 'retrieved_at', 'retrieval_time', 'retrieved_time', 'fetched_at'}
_STATUS_LABELS = {'queued': 'sırada', 'running': 'çalışıyor', 'completed': 'tamamlandı',
                  'partial': 'kısmi', 'failed': 'başarısız', 'cancelled': 'iptal edildi',
                  'ok': 'tamamlandı', 'error': 'hata', 'unavailable': 'kullanılamıyor',
                  'rate_limited': 'istek sınırına ulaşıldı'}
_TEXT_CHAR_LIMIT = 12000
_TEXT_PAGES_PER_HOST = 4
_TEXT_SEED_PAGES = 16
_COMMON_SCRIPT = re.compile(
    r'(?:^|[/_.@-])(?:jquery|bootstrap|react|react-dom|angular|vue|lodash|moment|'
    r'polyfill|core-js|webpack-runtime|vendor|vendors)(?:[/_.@-]|\d|$)', re.I,
)


def _time(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


def _run_view(job, evidence_ids, approximate):
    return {'id': job.id, 'created_at': _time(job.created_at), 'status': job.status,
            'evidence_count': len(set(evidence_ids)), 'approximate': approximate}


def record_run(service, job_id: str, evidence_ids: list[str]) -> dict:
    """Save the complete observation membership, including deduplicated saved observations."""
    ids = list(dict.fromkeys(evidence_ids))
    with service.repo.transaction() as session:
        job = service._required(session, Job, job_id)
        if job.kind not in _DISCOVERY_KINDS:
            raise ValueError('Yalnızca keşif ve genişletme işleri toplama kaydı oluşturabilir.')
        available = set(session.scalars(select(Observation.id).where(
            Observation.investigation_id == job.investigation_id, Observation.id.in_(ids),
        ))) if ids else set()
        if available != set(ids):
            raise ValueError('Toplama kanıtları aynı araştırmada kayıtlı olmalıdır.')
        row = session.get(CollectionRun, job.id)
        if row is None:
            row = CollectionRun(id=job.id, investigation_id=job.investigation_id,
                                evidence_ids=ids, created_at=job.created_at)
            session.add(row)
        else:
            row.evidence_ids = ids
        session.flush()
        return _run_view(job, ids, False)


def _load_runs(service, session, investigation_id):
    service._required(session, Investigation, investigation_id)
    jobs = session.scalars(select(Job).where(
        Job.investigation_id == investigation_id, Job.kind.in_(_DISCOVERY_KINDS),
    ).order_by(Job.created_at.desc(), Job.id.desc())).all()
    recorded = {row.id: row for row in session.scalars(select(CollectionRun).where(
        CollectionRun.investigation_id == investigation_id,
    ))}
    legacy = [job for job in jobs if job.id not in recorded and job.status in _TERMINAL]
    # Old jobs never stored observation membership. Retrieval intervals are a best-effort
    # reconstruction and can overlap; do not persist this guess as an exact run.
    observations = session.execute(select(Observation.id, Observation.retrieved_at).where(
        Observation.investigation_id == investigation_id,
    )).all() if legacy else []
    result = []
    for job in jobs:
        if job.id in recorded:
            ids = list(dict.fromkeys(recorded[job.id].evidence_ids))
            approximate = False
        elif job.status in _TERMINAL:
            start, end = _time(job.created_at), _time(job.updated_at)
            ids = [row.id for row in observations if start <= _time(row.retrieved_at) <= end]
            approximate = True
        else:
            continue
        result.append((_run_view(job, ids, approximate), job, ids))
    return result


def list_runs(service, investigation_id: str) -> dict:
    with service.sessions() as session:
        runs = _load_runs(service, session, investigation_id)
        return {'items': [view for view, _, _ in runs], 'total_unique': len(runs)}


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items()) if key.lower() not in _VOLATILE}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _scope(observation):
    payload = observation.payload
    if observation.kind == 'existing_scan':
        return f"existing_scan[{payload.get('scan_id') or observation.source_ref}]"
    if observation.kind == 'certificate_transparency':
        return f"certificate_transparency[{payload.get('certificate_id') or observation.source_ref}]"
    if observation.kind in {'javascript_content', 'script_unavailable'}:
        return f"{observation.kind}[{payload.get('script_url') or observation.source_ref}]"
    return observation.kind


def _snapshot(session, investigation_id, evidence_ids):
    # Field values form sets: repeated retrievals neither add votes nor change state.
    fields = defaultdict(dict)
    if not evidence_ids:
        return fields
    rows = session.execute(select(Observation, Entity).join(Entity, Entity.id == Observation.subject_id).where(
        Observation.investigation_id == investigation_id, Observation.id.in_(evidence_ids),
    )).all()
    for observation, subject in rows:
        payload = _canonical(observation.payload)
        if payload.get('answer') == payload.get('observed_ip') and 'observed_ip' in payload:
            payload.pop('answer', None)
        for field, value in payload.items():
            if field == 'names' and isinstance(value, list):
                value = sorted(set(value))
            key = (subject.canonical_value, observation.provider, _scope(observation), field)
            encoded = _encoded(value)
            entry = fields[key].setdefault(encoded, {'value': value, 'evidence_ids': set()})
            entry['evidence_ids'].add(observation.id)
    return fields


def _values(entries, keys):
    values = [entries[key]['value'] for key in sorted(keys)]
    return values[0] if len(values) == 1 else values or None


def watch_state(service, investigation_id: str, run_id: str) -> dict[str, str]:
    """Return only observed semantic fields from an exact run, without absence claims."""
    with service.sessions() as session:
        service._required(session, Investigation, investigation_id)
        run = session.scalar(select(CollectionRun).where(
            CollectionRun.id == run_id, CollectionRun.investigation_id == investigation_id,
        ))
        if run is None:
            raise NotFoundError('Bu araştırmada kesin toplama kaydı bulunamadı.')
        snapshot = _snapshot(session, investigation_id, run.evidence_ids)
        state = {}
        for key, entries in sorted(snapshot.items()):
            values = [entries[value]['value'] for value in sorted(entries)
                      if entries[value]['value'] not in (None, '', [], {})]
            if values:
                state[_encoded(key)] = _encoded(values)
        return state


def _coverage_limitations(view, job):
    limitations = []
    label = f'{_time(job.created_at)} tarihli toplama'
    if view['approximate']:
        limitations.append(f'{label} yaklaşık olarak yeniden oluşturuldu. Alma zamanları kullanıldığı için çakışan işler ve yinelenen kayıtlar yanlış eşleşebilir.')
    if job.status != 'completed' or job.truncated:
        status = _STATUS_LABELS.get(job.status, 'bilinmiyor')
        limitations.append(f"{label}: {status}{'; toplama sınırına ulaşıldı' if job.truncated else ''}. Kapsam eksik olabilir.")
    for provider in job.progress.get('providers', []):
        if not isinstance(provider, dict):
            continue
        if provider.get('status') != 'ok' or provider.get('truncated'):
            source = provider.get('provider', 'bilinmeyen kaynak')
            status = _STATUS_LABELS.get(provider.get('status'), 'bilinmiyor')
            limitations.append(f'{label}, {source} kaynağı: {status}. Eksik gözlemler kaybolmayı kanıtlamaz.')
    return limitations


def _incomplete_source(job, provider):
    if job.status != 'completed' or job.truncated:
        return True
    return any(item.get('status') != 'ok' or item.get('truncated')
               for item in job.progress.get('providers', [])
               if isinstance(item, dict) and item.get('provider') == provider)


def compare_runs(service, investigation_id: str, before=None, after=None) -> dict:
    with service.sessions() as session:
        runs = _load_runs(service, session, investigation_id)
        by_id = {view['id']: (view, job, ids) for view, job, ids in runs}
        for selected in (before, after):
            if selected is not None and selected not in by_id:
                raise NotFoundError('Bu araştırmada toplama kaydı bulunamadı.')
        after = after or (runs[0][0]['id'] if runs else None)
        if before is None and after:
            index = next(index for index, run in enumerate(runs) if run[0]['id'] == after)
            before = runs[index + 1][0]['id'] if index + 1 < len(runs) else None
        result = {'before': before, 'after': after, 'changes': [],
                  'counts': {'new': 0, 'changed': 0, 'not_observed': 0}, 'limitations': []}
        if not before or not after or before == after:
            result['limitations'].append('Karşılaştırma için iki farklı toplama kaydı gerekir.')
            return result
        old_view, old_job, old_ids = by_id[before]
        new_view, new_job, new_ids = by_id[after]
        result['limitations'].extend(_coverage_limitations(old_view, old_job))
        result['limitations'].extend(_coverage_limitations(new_view, new_job))
        old, new = _snapshot(session, investigation_id, old_ids), _snapshot(session, investigation_id, new_ids)
        for key in sorted(old.keys() | new.keys()):
            old_entries, new_entries = old.get(key, {}), new.get(key, {})
            removed, added = old_entries.keys() - new_entries.keys(), new_entries.keys() - old_entries.keys()
            if not removed and not added:
                continue
            # DNS answers are a potentially partial set. Positive replacement values
            # cannot imply an old answer stopped resolving when coverage was incomplete.
            partial_dns = key[2].startswith('dns_') and _incomplete_source(new_job, key[1])
            if removed and added and not partial_dns:
                changes = [('changed', old_entries.keys(), new_entries.keys())]
            else:
                changes = ([('new', set(), added)] if added else []) + ([('not_observed', removed, set())] if removed else [])
            messages = {'changed': 'İki toplamada gözlenen değerler farklı.',
                        'new': 'Bu değer sonraki toplamada gözlendi.',
                        'not_observed': 'Bu toplamada gözlenmedi. Bu durum kaldırıldığını veya kaybolduğunu kanıtlamaz.'}
            for kind, old_keys, new_keys in changes:
                ids = set().union(*(old_entries[k]['evidence_ids'] for k in old_keys),
                                  *(new_entries[k]['evidence_ids'] for k in new_keys))
                result['changes'].append({'kind': kind, 'subject': key[0], 'field': f'{key[2]}.{key[3]}',
                                          'before': _values(old_entries, old_keys), 'after': _values(new_entries, new_keys),
                                          'evidence_ids': sorted(ids), 'message': messages[kind]})
                result['counts'][kind] += 1
        if result['counts']['not_observed']:
            result['limitations'].append('Gözlenmedi ifadesi, bu toplamanın kayıtlarında bulunmadığı anlamına gelir. Tamamlanmış toplamanın da sınırları vardır; kaybolmayı kanıtlamaz.')
        return result


def _host(entity):
    if entity.kind == 'domain':
        return entity.canonical_value.lower().rstrip('.')
    if entity.kind == 'url':
        return (urlsplit(entity.canonical_value).hostname or '').lower().rstrip('.')
    return None


def _text_similarity(pages, seed_pages):
    """Compare bounded word sets; this is lexical overlap, not semantic verification."""
    best = None
    for page in pages:
        for seed in seed_pages:
            if page['digest'] == seed['digest']:
                continue
            common = len(page['tokens'] & seed['tokens'])
            if common < 15:
                continue
            overlap = common / len(page['tokens'] | seed['tokens'])
            if overlap >= .72 and (best is None or overlap > best['overlap']):
                best = {'overlap': overlap, 'common': common,
                        'evidence_ids': page['evidence_ids'] | seed['evidence_ids']}
    return best


def _candidate_ranking(service, investigation_id: str) -> dict:
    """Rank collected domains using shared evidence, without attributing ownership."""
    with service.sessions() as session:
        service._required(session, Investigation, investigation_id)
        entities = session.scalars(select(Entity).join(InvestigationEntity, InvestigationEntity.entity_id == Entity.id).where(
            InvestigationEntity.investigation_id == investigation_id,
        )).all()
        domains = {entity.canonical_value: entity for entity in entities if entity.kind == 'domain'}
        submissions = session.scalars(select(Submission).where(Submission.investigation_id == investigation_id)).all()
        submitted = {(row.hostname or row.canonical_value).lower().rstrip('.') for row in submissions}
        rows = session.execute(select(Observation, Entity).join(Entity, Entity.id == Observation.subject_id).where(
            Observation.investigation_id == investigation_id,
        ).order_by(Observation.retrieved_at.desc(), Observation.id)).all()
        features = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
        text_pages = defaultdict(dict)
        common_hashes, historical, unknown_time = set(), set(), set()

        def add(host, family, value, observation):
            if host and isinstance(value, (str, int)) and value != '':
                features[host][family][str(value)].add(observation.id)

        for observation, subject in rows:
            host, payload = _host(subject), observation.payload
            if not host:
                continue
            for field, family in (('observed_ip', 'ip'), ('cert_sha256', 'certificate'),
                                  ('js_sha256', 'javascript'), ('body_sha256', 'content')):
                if family in {'javascript', 'content'} and (
                        payload.get('bytes') == 0 or payload.get(field) == sha256(b'').hexdigest()):
                    continue
                add(host, family, payload.get(field), observation)
            if observation.kind in {'dns_a', 'dns_aaaa', 'passive_dns'} and not payload.get('observed_ip'):
                add(host, 'ip', payload.get('answer'), observation)
            if observation.kind == 'certificate_transparency':
                # Certificate names are positive evidence only when present on the same
                # certificate, not merely returned by a search for the submitted host.
                certificate_id = payload.get('certificate_id')
                names = payload.get('names', [])
                if certificate_id is not None and isinstance(names, list) and host in names:
                    for name in names:
                        if name in domains or name in submitted:
                            add(name, 'certificate', f'CT:{certificate_id}', observation)
            if observation.kind in {'page_content', 'page_browser'}:
                text = payload.get('text')
                if isinstance(text, str):
                    normalized = ' '.join(text.split())
                    digest = sha256(normalized.encode()).hexdigest()
                    if len(normalized) >= 80:
                        add(host, 'content', 'text:' + digest, observation)
                    tokens = set(re.findall(r'[^\W_]+', normalized[:_TEXT_CHAR_LIMIT].casefold().replace('\u0307', '')))
                    if len(tokens) >= 20:
                        pages = text_pages[host]
                        if digest in pages:
                            pages[digest]['evidence_ids'].add(observation.id)
                        elif len(pages) < _TEXT_PAGES_PER_HOST:
                            pages[digest] = {'digest': digest, 'tokens': tokens, 'evidence_ids': {observation.id}}
            if payload.get('js_sha256') and (payload.get('common_library') or
                    _COMMON_SCRIPT.search(str(payload.get('script_url') or observation.source_ref))):
                common_hashes.add(str(payload['js_sha256']))
            if observation.kind in {'existing_scan', 'certificate_transparency', 'passive_dns', 'passive_dns_context'}:
                historical.add(observation.id)
            if observation.observed_at is None:
                unknown_time.add(observation.id)
        seed_features = defaultdict(lambda: defaultdict(set))
        for host in submitted:
            for family, values in features[host].items():
                for value, ids in values.items():
                    seed_features[family][value].update(ids)
        for submission in submissions:
            if submission.kind == 'ip':
                # The submitted address is the comparison baseline; the candidate's
                # actual DNS observation supplies the evidence for the relationship.
                seed_features['ip'][submission.canonical_value]
        seed_pages = [page for host in sorted(submitted) for page in text_pages[host].values()][:_TEXT_SEED_PAGES]
        frequencies = defaultdict(set)
        for host, families in features.items():
            for family, values in families.items():
                for value in values:
                    frequencies[(family, value)].add(host)
        items = []
        labels = {'ip': 'Aynı gözlenen IP', 'certificate': 'Aynı sertifika kimliği',
                  'javascript': 'Aynı JavaScript içerik özeti', 'content': 'Aynı sayfa içeriği'}
        weights = {'ip': 6, 'certificate': 25, 'javascript': 30, 'content': 30}
        for domain, entity in sorted(domains.items()):
            if domain in submitted:
                continue
            reasons, limitations, all_ids, family_weights = [], [], set(), {}
            for family in ('ip', 'certificate', 'javascript', 'content'):
                values = features[domain].get(family, {})
                matches = sorted(values.keys() & seed_features[family].keys())
                if not matches:
                    continue
                family_ids, descriptions, weight = set(), [], 0
                for value in matches:
                    ids = values[value] | seed_features[family][value]
                    family_ids.update(ids)
                    members = frequencies[(family, value)]
                    common = family == 'javascript' and value in common_hashes
                    widespread = family in {'javascript', 'content', 'certificate'} and len(members) >= 5
                    strength_weight = 4 if common else 5 if widespread else weights[family]
                    weight = max(weight, strength_weight)
                    descriptions.append(value)
                    if common:
                        limitations.append('Yaygın bir betik kütüphanesi bu özet eşleşmesini açıklayabilir; puana katkısı azaltıldı.')
                    if widespread:
                        widespread_ids = set().union(*(features[host][family][value] for host in members))
                        limitations.append(f'Bu değer toplanan {len(members)} alan adında görülüyor. Yaygın içerik veya paylaşılan altyapı olasılığı nedeniyle puana katkısı azaltıldı.')
                        all_ids.update(widespread_ids)
                if family == 'ip':
                    limitations.append('Paylaşımlı barındırma, içerik dağıtım ağları veya farklı gözlem tarihleri aynı IP’yi açıklayabilir. Tek başına zayıf bir bulgudur.')
                strength = 'weak' if weight < 20 else 'moderate' if family == 'certificate' else 'strong'
                reasons.append({'label': f"{labels[family]}: {', '.join(descriptions)}", 'strength': strength,
                                'evidence_ids': sorted(family_ids)})
                all_ids.update(family_ids)
                family_weights[family] = weight
            # Exact and approximate text matches remain one content family. In
            # particular, similarity must not undo a widespread exact-hash discount.
            if 'content' not in family_weights:
                similar = _text_similarity(text_pages[domain].values(), seed_pages)
                if similar:
                    reasons.append({'label': f"Benzer sayfa metni: {similar['common']} ortak sözcük",
                                    'strength': 'moderate', 'evidence_ids': sorted(similar['evidence_ids'])})
                    family_weights['content'] = 25
                    all_ids.update(similar['evidence_ids'])
                    limitations.append('Sözcük örtüşmesi yalnızca inceleme önceliğini destekler; metnin doğruluğunu veya ortak sahipliği göstermez.')
                    limitations.append('Metin karşılaştırması ilk 12.000 karakterle, alan adı başına en yeni dört farklı metinle ve bildirilen hedeflerden en fazla 16 metinle sınırlıdır.')
            if not reasons:
                continue
            independent = sum(value >= 20 for value in family_weights.values())
            score = min(100, sum(family_weights.values()) + (10 if independent >= 2 else 0))
            if all_ids & historical:
                limitations.append('Geçmiş kayıtları farklı tarihleri yansıtabilir; güncel altyapıyı veya eşzamanlı kullanımı kanıtlamaz.')
            if all_ids & unknown_time:
                limitations.append('Bazı kaynakların gözlem zamanı bilinmiyor. Kaydın alındığı zaman, gözlem zamanı değildir.')
            limitations.append('Bu puan inceleme önceliğidir. Olasılık hesabı, kampanya, aktör veya sahiplik atfı değildir. Farklı bulgu türleri de birbiriyle ilişkili olabilir.')
            items.append({'entity_id': entity.id, 'domain': domain, 'score': score,
                          'priority': 'high' if score >= 60 else 'medium' if score >= 25 else 'low',
                          'reasons': reasons, 'limitations': limitations, 'evidence_ids': sorted(all_ids)})
        items.sort(key=lambda item: (-item['score'], item['domain'], item['entity_id']))
        return {'items': items, 'total_unique': len(items)}


def rank_candidates(service, investigation_id: str, limit: int = 30, cursor: str | None = None) -> dict:
    from .groups import _decode_cursor, _encode_cursor
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Sonuç sınırı 1 ile 100 arasında olmalıdır.')
    expected = {'kind':'candidates', 'investigation_id':investigation_id, 'limit':limit}
    offset = _decode_cursor(cursor, expected)
    ranking = _candidate_ranking(service, investigation_id)
    items = ranking['items']
    return {'items':items[offset:offset+limit], 'total_unique':len(items),
            'next_cursor':_encode_cursor({**expected,'offset':offset+limit}) if offset+limit<len(items) else None}
