from __future__ import annotations

import base64
import json

from sqlalchemy import select

from belgu.domain.contracts import EntityPage, EntityView, GraphView, GroupPage, GroupView, RelationView
from belgu.persistence.models import Entity, Investigation, InvestigationEntity, Observation, Relation, relation_evidence


GROUP_FIELDS = {
    "observed_ip": ("observed_ip", "Aynı gözlenen IP"),
    "cert_sha256": ("cert_sha256", "Aynı sertifika özeti"),
    "js_sha256": ("js_sha256", "Aynı JavaScript özeti"),
}


def _encode_cursor(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None, expected: dict) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError("cursor does not match query")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("invalid cursor")
    return offset


class GroupService:
    def __init__(self, service):
        self.service = service

    @staticmethod
    def _limit(value: int, maximum: int) -> int:
        if value <= 0 or value > maximum:
            raise ValueError(f"limit must be between 1 and {maximum}")
        return value

    def _memberships(self, session, investigation_id: str, criterion: str) -> dict[str, dict[str, set[str]]]:
        field, _ = GROUP_FIELDS[criterion]
        rows = session.execute(
            select(Observation, Entity)
            .join(Entity, Entity.id == Observation.subject_id)
            .where(Observation.investigation_id == investigation_id)
            .order_by(Observation.id)
        ).all()
        memberships: dict[str, dict[str, set[str]]] = {}
        for observation, subject in rows:
            value = observation.payload.get(field)
            if not isinstance(value, str) or not value:
                continue
            group = memberships.setdefault(value, {"entities": set(), "evidence": set()})
            group["entities"].add(subject.id)
            group["evidence"].add(observation.id)
        return memberships

    def list_groups(self, investigation_id: str, by: str, limit: int = 50, cursor: str | None = None) -> GroupPage:
        limit = self._limit(limit, 50)
        if by not in GROUP_FIELDS:
            raise ValueError("unknown group criterion")
        offset = _decode_cursor(cursor, {"kind": "groups", "by": by, "investigation_id": investigation_id})
        with self.service.sessions() as session:
            self.service._required(session, Investigation, investigation_id)
            memberships = self._memberships(session, investigation_id, by)
            ordered = sorted(memberships.items(), key=lambda item: (-len(item[1]["entities"]), item[0]))
            page = ordered[offset:offset + limit]
            _, label = GROUP_FIELDS[by]
            items = [
                GroupView(
                    key=key,
                    criterion=by,
                    label=f"{label}: {key}",
                    entity_count=len(value["entities"]),
                    evidence_ids=sorted(value["evidence"]),
                )
                for key, value in page
            ]
            unique_entities = set().union(*(item[1]["entities"] for item in ordered)) if ordered else set()
            next_cursor = _encode_cursor({"kind": "groups", "by": by, "investigation_id": investigation_id, "offset": offset + limit}) if offset + limit < len(ordered) else None
            return GroupPage(items=items, next_cursor=next_cursor, total_unique=len(unique_entities), total_groups=len(ordered))

    def list_entities(self, investigation_id: str, kind: str | None = None, group_key: str | None = None, limit: int = 50, cursor: str | None = None, **filters) -> EntityPage:
        from .entity_search import list_entities
        return list_entities(self.service, investigation_id, kind, group_key, limit, cursor, **filters)

    def graph(self, investigation_id: str, root_id: str | None = None, limit: int = 100, cursor: str | None = None) -> GraphView:
        limit = self._limit(limit, 100)
        offset = _decode_cursor(cursor, {"kind": "graph", "root_id": root_id, "investigation_id": investigation_id})
        with self.service.sessions() as session:
            self.service._required(session, Investigation, investigation_id)
            if root_id and session.scalar(select(InvestigationEntity.id).where(
                    InvestigationEntity.investigation_id == investigation_id,
                    InvestigationEntity.entity_id == root_id)) is None:
                from .service import NotFoundError
                raise NotFoundError('graph root not found in investigation')
            statement = select(Relation).where(Relation.investigation_id == investigation_id).order_by(Relation.kind, Relation.id)
            if root_id:
                statement = statement.where((Relation.src_id == root_id) | (Relation.dst_id == root_id))
            relations = session.scalars(statement).all()
            page = relations[offset:offset + limit]
            node_ids = {value for relation in page for value in (relation.src_id, relation.dst_id)}
            entity_rows = session.scalars(select(Entity).where(Entity.id.in_(node_ids))).all() if node_ids else []
            nodes = [EntityView(id=row.id, kind=row.kind, canonical_value=row.canonical_value) for row in entity_rows]
            relation_views = []
            for row in page:
                evidence_ids = list(session.scalars(select(relation_evidence.c.observation_id).where(relation_evidence.c.relation_id == row.id)))
                relation_views.append(RelationView(id=row.id, src_id=row.src_id, dst_id=row.dst_id, kind=row.kind, evidence_ids=evidence_ids))
            has_more = offset + limit < len(relations)
            next_cursor = _encode_cursor({"kind": "graph", "root_id": root_id, "investigation_id": investigation_id, "offset": offset + limit}) if has_more else None
            return GraphView(nodes=nodes, relations=relation_views, has_more=has_more, next_cursor=next_cursor)
