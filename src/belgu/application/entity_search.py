"""Case-wide entity filters, exact URL/host matching and source-time sorting."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from belgu.domain.contracts import EntityPage, EntityView
from belgu.persistence.models import Entity, Investigation, InvestigationEntity, Observation


def _host(entity):
    if entity.kind == 'url':
        return (urlsplit(entity.canonical_value).hostname or '').lower().rstrip('.')
    if entity.kind in ('domain', 'ip'):
        return entity.canonical_value.lower().rstrip('.')
    return None


def list_entities(service, investigation_id, kind=None, group_key=None, limit=50,
                  cursor=None, *, q='', has_capture=False, shared=None,
                  recent_hours=None, sort='name'):
    from .groups import GROUP_FIELDS, GroupService, _decode_cursor, _encode_cursor
    GroupService._limit(limit, 100)
    if not isinstance(q, str) or len(q) > 500:
        raise ValueError('Arama en fazla 500 karakter olabilir.')
    if sort not in ('name', 'latest', 'priority') or shared not in (None, 'javascript', 'certificate'):
        raise ValueError('Geçersiz sıralama veya ortak iz filtresi.')
    if recent_hours is not None and (type(recent_hours) is not int or not 1 <= recent_hours <= 8760):
        raise ValueError('Gözlem aralığı 1 ile 8760 saat arasında olmalıdır.')
    if type(has_capture) is not bool:
        raise ValueError('Görsel filtresi doğru/yanlış olmalıdır.')
    q = q.strip().casefold()
    expected = {'kind':'entities', 'investigation_id':investigation_id, 'entity_kind':kind,
                'group_key':group_key, 'q':q, 'has_capture':has_capture, 'shared':shared,
                'recent_hours':recent_hours, 'sort':sort, 'limit':limit}
    offset = _decode_cursor(cursor, expected)
    priorities = {}
    if sort == 'priority':
        from .insights import _candidate_ranking
        priorities = {x['entity_id']:x['score'] for x in _candidate_ranking(service, investigation_id)['items']}
    with service.sessions() as session:
        service._required(session, Investigation, investigation_id)
        entities = session.scalars(select(Entity).join(InvestigationEntity,
            InvestigationEntity.entity_id == Entity.id).where(
            InvestigationEntity.investigation_id == investigation_id)).all()
        observations = session.execute(select(Observation, Entity).join(Entity,
            Entity.id == Observation.subject_id).where(Observation.investigation_id == investigation_id)).all()
        counts = defaultdict(int)
        last, host_last = {}, {}
        captures = set()
        captured_urls = set()
        values = defaultdict(lambda: defaultdict(set))
        memberships = defaultdict(set)
        for observation, subject in observations:
            counts[subject.id] += 1
            observed = observation.observed_at
            if observed and observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if observed and (subject.id not in last or observed > last[subject.id]):
                last[subject.id] = observed
            host = _host(subject)
            if host and observed and (host not in host_last or observed > host_last[host]):
                host_last[host] = observed
            payload = observation.payload
            for field, _ in GROUP_FIELDS.values():
                value = payload.get(field)
                if isinstance(value, str) and value:
                    memberships[value].add(subject.id)
            if not host:
                continue
            if observation.kind == 'page_browser' and payload.get('artifact_id'):
                captures.add(host)
                if subject.kind == 'url':
                    captured_urls.add(subject.id)
            for field, family in (('js_sha256','javascript'), ('cert_sha256','certificate')):
                value = payload.get(field)
                if isinstance(value, str) and value:
                    values[family][value].add(host)
        shared_hosts = defaultdict(set)
        for family, groups in values.items():
            for hosts in groups.values():
                if len(hosts) > 1:
                    shared_hosts[family].update(hosts)
        cutoff = datetime.now(timezone.utc)-timedelta(hours=recent_hours) if recent_hours else None
        result = []
        for entity in entities:
            if kind and entity.kind != kind:
                continue
            if group_key and entity.id not in memberships[group_key]:
                continue
            if q and q not in entity.canonical_value.casefold():
                continue
            host = _host(entity)
            # A domain's captured page lives on a full URL; only its exact host matches.
            seen = host_last.get(host) if entity.kind == 'domain' else last.get(entity.id)
            captured = (host in captures if entity.kind == 'domain' else
                        entity.id in captured_urls if entity.kind == 'url' else False)
            if has_capture and not captured:
                continue
            if shared and host not in shared_hosts[shared]:
                continue
            if cutoff and (seen is None or seen < cutoff):
                continue
            result.append(EntityView(id=entity.id, kind=entity.kind,
                canonical_value=entity.canonical_value, evidence_count=counts[entity.id],
                last_seen=seen, has_capture=captured,
                shared_signals=[f for f in ('javascript','certificate') if host in shared_hosts[f]],
                priority_score=priorities.get(entity.id)))
        def name(item):
            return (item.kind,item.canonical_value,item.id)
        if sort == 'latest':
            result.sort(key=lambda x:(x.last_seen is None,-x.last_seen.timestamp() if x.last_seen else 0,*name(x)))
        elif sort == 'priority':
            result.sort(key=lambda x:(x.priority_score is None,-(x.priority_score or 0),*name(x)))
        else:
            result.sort(key=name)
        next_cursor = _encode_cursor({**expected,'offset':offset+limit}) if offset+limit < len(result) else None
        return EntityPage(items=result[offset:offset+limit], next_cursor=next_cursor, total_unique=len(result))
