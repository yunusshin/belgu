"""Bounded, computed cross-case leads. Repeated retrievals never add votes."""
from __future__ import annotations

from collections import defaultdict
from datetime import timezone
from hashlib import sha256
import ipaddress
import json
import re

from sqlalchemy import select

from belgu.persistence.models import Brand, Decision, Entity, Investigation, Observation

MAX_CURRENT_OBSERVATIONS = 1000
MAX_FOREIGN_OBSERVATIONS = 5000
MAX_CASES = 200
_COMMON_SCRIPT = re.compile(r'(?:^|[/_.@-])(?:jquery|bootstrap|react|react-dom|angular|vue|lodash|moment|polyfill|core-js|vendor|vendors)(?:[/_.@-]|\d|$)', re.I)
_LABELS = {'javascript': 'Aynı JavaScript içerik özeti', 'certificate': 'Aynı sertifika özeti', 'content': 'Aynı sayfa içerik özeti', 'ip': 'Aynı gözlenen IP', 'domain': 'Aynı kayıtlı alan adı', 'url': 'Aynı kayıtlı tam URL'}
_WEIGHTS = {'javascript': 30, 'certificate': 25, 'content': 30, 'ip': 6, 'domain': 1, 'url': 1}


def timestamp(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None


def evidence_ref(observation, subject):
    return {'investigation_id': observation.investigation_id, 'evidence_id': observation.id,
            'subject': {'kind': subject.kind, 'value': subject.canonical_value},
            'kind': observation.kind, 'provider': observation.provider,
            'source_ref': observation.source_ref, 'observed_at': timestamp(observation.observed_at),
            'retrieved_at': timestamp(observation.retrieved_at)}


def _features(observation, subject):
    # Identifier reuse is supported only by actual observations on both sides.
    # An entity/submission membership alone never supplies this feature.
    if subject.kind in {'domain', 'url'} and subject.canonical_value:
        yield subject.kind, subject.canonical_value
    payload = observation.payload
    for field, family in (('js_sha256', 'javascript'), ('cert_sha256', 'certificate'),
                          ('certificate_sha256', 'certificate'), ('body_sha256', 'content')):
        value = payload.get(field)
        if (isinstance(value, str) and re.fullmatch(r'[a-fA-F0-9]{64}', value)
                and value.lower() != sha256(b'').hexdigest() and payload.get('bytes') != 0):
            yield family, value.lower()
    if str(payload.get('rcode', 'NOERROR')).upper() not in {'NOERROR', '0'}:
        return
    value = payload.get('observed_ip')
    if value is None and observation.kind in {'dns_a', 'dns_aaaa', 'passive_dns'}:
        value = payload.get('answer')
    if isinstance(value, str):
        try:
            yield 'ip', ipaddress.ip_address(value).compressed
        except ValueError:
            pass


def cross_investigation_memory(service, investigation_id: str, *, limit=20, cursor=None) -> dict:
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Sayfa boyutu 1–100 arasında olmalıdır.')
    with service.sessions() as session:
        current = service._required(session, Investigation, investigation_id)
        cases = session.scalars(select(Investigation).where(
            Investigation.id != investigation_id, Investigation.demo == current.demo,
        ).order_by(Investigation.created_at.desc(), Investigation.id).limit(MAX_CASES + 1)).all()
        cases_capped = len(cases) > MAX_CASES
        cases = cases[:MAX_CASES]
        query = select(Observation, Entity).join(Entity, Entity.id == Observation.subject_id)
        order = (Observation.retrieved_at.desc(), Observation.id)
        current_rows = session.execute(query.where(Observation.investigation_id == investigation_id)
                                       .order_by(*order).limit(MAX_CURRENT_OBSERVATIONS + 1)).all()
        foreign_rows = session.execute(query.where(Observation.investigation_id.in_([case.id for case in cases]))
                                       .order_by(*order).limit(MAX_FOREIGN_OBSERVATIONS + 1)).all() if cases else []
        capped = cases_capped or len(current_rows) > MAX_CURRENT_OBSERVATIONS or len(foreign_rows) > MAX_FOREIGN_OBSERVATIONS
        current_rows, foreign_rows = current_rows[:MAX_CURRENT_OBSERVATIONS], foreign_rows[:MAX_FOREIGN_OBSERVATIONS]
        features = defaultdict(lambda: defaultdict(dict))
        common = set()
        for observation, subject in [*current_rows, *foreign_rows]:
            for family, value in _features(observation, subject):
                # Keep the newest supporting observation per subject and value. The
                # original observations remain available in the evidence inspector.
                features[observation.investigation_id][(family, value)].setdefault(subject.id, evidence_ref(observation, subject))
                if family == 'javascript' and (observation.payload.get('common_library') is True or
                        _COMMON_SCRIPT.search(str(observation.payload.get('script_url') or observation.source_ref))):
                    common.add(value)
        frequencies = defaultdict(set)
        for case_id, values in features.items():
            for key in values:
                frequencies[key].add(case_id)
        items = []
        for case in cases:
            reasons, family_weights, refs = [], {}, {}
            for family, value in sorted(features[investigation_id].keys() & features[case.id].keys()):
                widespread = len(frequencies[(family, value)]) >= 5
                discounted = family == 'javascript' and value in common
                weight = 2 if discounted else min(_WEIGHTS[family], 6) if widespread else _WEIGHTS[family]
                family_weights[family] = max(family_weights.get(family, 0), weight)
                support = [*features[investigation_id][(family, value)].values(), *features[case.id][(family, value)].values()]
                for ref in support:
                    refs[(ref['investigation_id'], ref['evidence_id'])] = ref
                reasons.append({'kind': family, 'value': value, 'label': _LABELS[family],
                                'weight': weight, 'discounted': discounted or widespread,
                                'detail': 'Yaygın kütüphane; ayırt ediciliği düşük.' if discounted else
                                          'Birçok araştırmada görülüyor; ayırt ediciliği düşük.' if widespread else
                                          'Paylaşımlı altyapı olabilir.' if family == 'ip' else
                                          'Yalnızca gözlemlerde tekrarlanan hedef kimliği; saldırı veya ortak sahiplik kanıtı değildir.' if family in {'domain', 'url'} else
                                          'İçerik eşleşmesi bir araştırma ipucudur.',
                                'evidence_refs': support})
            if not reasons:
                continue
            decision = session.scalar(select(Decision).where(Decision.investigation_id == case.id)
                                      .order_by(Decision.created_at.desc(), Decision.id.desc()).limit(1))
            score = sum(family_weights.values())
            items.append({'investigation_id': case.id, 'title': case.title, 'brand_name': session.get(Brand, case.brand_id).name, 'workflow': case.workflow,
                          'disposition': decision.value if decision else 'unreviewed',
                          'decision': {'value': decision.value, 'note': decision.note, 'created_at': timestamp(decision.created_at)} if decision else None,
                          'score': score, 'priority': 'high' if score >= 30 else 'medium' if score >= 20 else 'low',
                          'reasons': reasons, 'evidence_refs': list(refs.values())})
    items.sort(key=lambda item: (-item['score'], item['investigation_id']))
    signature = sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    offset = 0
    if cursor:
        try:
            previous, raw_offset = cursor.split(':')
            offset = int(raw_offset)
            if previous != signature:
                raise ValueError('Hafıza verileri değişti; ilk sayfadan yeniden yükleyin.')
            if offset < 0 or offset >= len(items):
                raise ValueError('Geçersiz hafıza sayfası.')
        except (AttributeError, TypeError):
            raise ValueError('Geçersiz hafıza sayfası.') from None
    end = offset + limit
    return {'items': items[offset:end], 'total_unique': len(items),
            'next_cursor': f'{signature}:{end}' if end < len(items) else None,
            'coverage': {'truncated': capped, 'cases_scanned': len(cases),
                         'current_observations_scanned': len(current_rows), 'foreign_observations_scanned': len(foreign_rows),
                         'case_limit': MAX_CASES, 'current_observation_limit': MAX_CURRENT_OBSERVATIONS,
                         'foreign_observation_limit': MAX_FOREIGN_OBSERVATIONS},
            'limitations': ['Eşleşmeler atıf veya zararlılık olasılığı değildir. Eksik gözlem, yokluk kanıtı değildir.'] +
                            (['Tarama sınırına ulaşıldı; sonuçlar kayıtların bir bölümünü kapsıyor.'] if capped else [])}
