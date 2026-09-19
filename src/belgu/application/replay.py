"""Build a bounded chronological projection from persisted investigation records."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy import select

from belgu.persistence.models import (
    Analysis,
    CollectionRun,
    Decision,
    Entity,
    Investigation,
    InvestigationEntity,
    Job,
    Observation,
    Relation,
    Submission,
    relation_evidence,
)


EVENT_LIMIT = 160
GRAPH_NODE_LIMIT = 60
_ORDER = {"submission": 0, "observation": 1, "relation": 2, "job": 3, "analysis": 4, "decision": 5}
_TITLES = {
    "submission": "Başlangıç kaydı",
    "observation": "Kaynak gözlemi",
    "relation": "Kanıtlı bağlantı",
    "job": "Çalışma sonucu",
    "analysis": "Model analizi",
    "decision": "Analist kararı",
}
_MASKED_DETAILS = {
    "submission": "İncelemeye bir başlangıç kaydı eklendi.",
    "observation": "Bir kaynak gözlemi kayda alındı.",
    "relation": "Kanıtla desteklenen bir bağlantı kayda alındı.",
    "job": "Çalışmanın kaydedilmiş durumu zaman çizelgesine eklendi.",
    "analysis": "Kayıtlı kanıtlara dayanan model analizi kayda alındı.",
    "decision": "Analist değerlendirmesi kayda alındı.",
}
_SAFE_ENTITY_KINDS = {"url", "domain", "ip", "cert", "js_hash", "favicon_hash"}
_SAFE_STATUSES = {
    "recorded",
    "queued",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "unreviewed",
    "confirmed_phishing",
    "benign",
    "needs_review",
}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _terminal_known_at(row: Job) -> datetime:
    return row.updated_at if row.status in {"completed", "partial", "failed", "cancelled"} else row.created_at


def _analysis_evidence(row: Analysis) -> list[str]:
    claims = row.output.get("claims", []) if isinstance(row.output, dict) else []
    cited: list[str] = []
    for claim in claims if isinstance(claims, list) else []:
        if not isinstance(claim, dict):
            continue
        values = claim.get("evidence_ids", [])
        if isinstance(values, list):
            cited.extend(value for value in values if isinstance(value, str))
    return list(dict.fromkeys(cited or row.evidence_ids or []))


def _spread(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Choose chronological coverage deterministically, retaining both ends."""
    if count <= 0:
        return []
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[-1]]
    indexes = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[index] for index in indexes]


def _bounded_events(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only lifecycle events whose complete evidence closure fits the cap."""
    if len(candidates) <= EVENT_LIMIT:
        return list(candidates)
    observations = [item for item in candidates if item["kind"] == "observation"]
    observations_by_id = {item["record_id"]: item for item in observations}
    relations = [item for item in candidates if item["kind"] == "relation"]
    lifecycle = [item for item in candidates if item["kind"] not in {"observation", "relation"}]
    independent_lifecycle = [item for item in lifecycle if not item["evidence_ids"]]
    evidence_lifecycle = [item for item in lifecycle if item["evidence_ids"]]
    if len(independent_lifecycle) >= EVENT_LIMIT:
        return _spread(independent_lifecycle, EVENT_LIMIT)

    selected = list(independent_lifecycle)
    chosen_observations: list[dict[str, Any]] = []
    chosen_ids: set[str] = set()
    # Prefer the latest recorded evidence-bearing conclusions. An event is
    # retained only when every cited observation can be retained with it.
    for item in reversed(evidence_lifecycle):
        dependencies = [
            observations_by_id[value]
            for value in item["evidence_ids"]
            if value in observations_by_id and value not in chosen_ids
        ]
        if len(selected) + len(chosen_observations) + len(dependencies) + 1 > EVENT_LIMIT:
            continue
        selected.append(item)
        chosen_observations.extend(dependencies)
        chosen_ids.update(dependency["record_id"] for dependency in dependencies)

    remaining = EVENT_LIMIT - len(selected) - len(chosen_observations)
    observation_budget = 0 if remaining == 0 else remaining if not relations else max(1, remaining * 3 // 4)
    pool = [item for item in observations if item["record_id"] not in chosen_ids]
    for item in _spread(pool, observation_budget):
        if item["record_id"] not in chosen_ids:
            chosen_observations.append(item)
            chosen_ids.add(item["record_id"])
    selected.extend(chosen_observations)

    eligible_relations = [
        item for item in relations if item["evidence_ids"] and all(value in chosen_ids for value in item["evidence_ids"])
    ]
    selected.extend(_spread(eligible_relations, EVENT_LIMIT - len(selected)))
    if len(selected) < EVENT_LIMIT:
        unselected_observations = [item for item in observations if item["record_id"] not in chosen_ids]
        selected.extend(_spread(unselected_observations, EVENT_LIMIT - len(selected)))
    return sorted(selected, key=lambda item: (item["known_at_value"], _ORDER[item["kind"]], item["record_id"]))


def _raw_detail(kind: str, row: Any, entities: dict[str, Entity]) -> str:
    if kind == "submission":
        suffix = f" · {row.note}" if row.note else ""
        return f"{row.source} · {row.canonical_value}{suffix}"
    if kind == "observation":
        subject = entities[row.subject_id].canonical_value
        payload = json.dumps(row.payload, ensure_ascii=False, sort_keys=True, default=str)
        return f"{row.provider} · {subject} · {row.source_ref} · {payload}"
    if kind == "relation":
        return f"{entities[row.src_id].canonical_value} → {entities[row.dst_id].canonical_value} · {row.kind}"
    if kind == "job":
        message = row.error or (row.progress.get("message") if isinstance(row.progress, dict) else "") or ""
        return f"{row.kind} · {message}"
    if kind == "analysis":
        summary = row.output.get("summary", "") if isinstance(row.output, dict) else ""
        return f"{row.model_id} · {summary}"
    return f"{row.value} · {row.note}" if row.note else row.value


def build_replay(service, investigation_id: str, *, redact: bool = True) -> dict[str, Any]:
    """Return replay data derived only from rows already recorded for one investigation."""
    with service.sessions() as session:
        investigation = service._required(session, Investigation, investigation_id)
        submissions = session.scalars(
            select(Submission)
            .where(Submission.investigation_id == investigation_id)
            .order_by(Submission.created_at, Submission.id)
        ).all()
        observations = session.scalars(
            select(Observation)
            .where(Observation.investigation_id == investigation_id)
            .order_by(Observation.retrieved_at, Observation.id)
        ).all()
        relations = session.scalars(
            select(Relation).where(Relation.investigation_id == investigation_id).order_by(Relation.id)
        ).all()
        analyses = session.scalars(
            select(Analysis)
            .where(Analysis.investigation_id == investigation_id)
            .order_by(Analysis.created_at, Analysis.id)
        ).all()
        decisions = session.scalars(
            select(Decision)
            .where(Decision.investigation_id == investigation_id)
            .order_by(Decision.created_at, Decision.id)
        ).all()
        jobs = session.scalars(
            select(Job).where(Job.investigation_id == investigation_id).order_by(Job.created_at, Job.id)
        ).all()
        runs = {
            row.id: row
            for row in session.scalars(
                select(CollectionRun).where(CollectionRun.investigation_id == investigation_id)
            ).all()
        }
        entities = {
            row.id: row
            for row in session.scalars(
                select(Entity)
                .join(InvestigationEntity, InvestigationEntity.entity_id == Entity.id)
                .where(InvestigationEntity.investigation_id == investigation_id)
            ).all()
        }
        relation_refs = {
            relation.id: list(
                session.scalars(
                    select(relation_evidence.c.observation_id)
                    .where(relation_evidence.c.relation_id == relation.id)
                    .order_by(relation_evidence.c.observation_id)
                )
            )
            for relation in relations
        }

    observations_by_id = {row.id: row for row in observations}
    evidence_alias = {row.id: f"evidence-{index:03}" for index, row in enumerate(observations, 1)}
    candidates: list[dict[str, Any]] = []

    def add(kind: str, row: Any, known_at: datetime, *, evidence_ids=(), node_ids=(), edge=None, status="recorded"):
        candidates.append(
            {
                "kind": kind,
                "row": row,
                "record_id": row.id,
                "known_at_value": known_at,
                "observed_at_value": row.observed_at if kind == "observation" else None,
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
                "node_ids": list(dict.fromkeys(node_ids)),
                "edge": edge,
                "status": status,
            }
        )

    entity_identity = {(row.kind, row.canonical_value): row.id for row in entities.values()}
    for row in submissions:
        node_id = entity_identity.get((row.kind, row.canonical_value))
        add("submission", row, row.created_at, node_ids=[node_id] if node_id else (), status="recorded")
    for row in observations:
        add(
            "observation",
            row,
            row.retrieved_at,
            evidence_ids=[row.id],
            node_ids=[row.subject_id],
            status="recorded",
        )

    unsupported_relations = 0
    for row in relations:
        supported = [observations_by_id[item] for item in relation_refs[row.id] if item in observations_by_id]
        if not supported:
            unsupported_relations += 1
            continue
        earliest = min(item.retrieved_at for item in supported)
        available_refs = [item.id for item in supported if item.retrieved_at == earliest]
        add(
            "relation",
            row,
            earliest,
            evidence_ids=available_refs,
            node_ids=[row.src_id, row.dst_id],
            edge=(row.src_id, row.dst_id, row.kind),
            status="recorded",
        )
    for row in jobs:
        known_at = _terminal_known_at(row)
        run_ids = runs[row.id].evidence_ids if row.id in runs else []
        available = [
            item
            for item in run_ids
            if item in observations_by_id and observations_by_id[item].retrieved_at <= known_at
        ]
        add("job", row, known_at, evidence_ids=available, status=row.status)
    for row in analyses:
        available = [
            item
            for item in _analysis_evidence(row)
            if item in observations_by_id and observations_by_id[item].retrieved_at <= row.created_at
        ]
        add("analysis", row, row.created_at, evidence_ids=available, status=row.status)
    for row in decisions:
        add("decision", row, row.created_at, status=row.value)

    candidates.sort(key=lambda item: (item["known_at_value"], _ORDER[item["kind"]], item["record_id"]))
    all_node_ids: list[str] = []
    for item in candidates:
        all_node_ids.extend(node_id for node_id in item["node_ids"] if node_id in entities)
    all_node_ids = list(dict.fromkeys(all_node_ids))
    node_alias = {node_id: f"node-{index:03}" for index, node_id in enumerate(all_node_ids, 1)}

    selected = _bounded_events(candidates)
    selected_observation_ids = {item["record_id"] for item in selected if item["kind"] == "observation"}
    graph_node_ids: list[str] = []
    graph_node_set: set[str] = set()
    # Reserve complete endpoint pairs for selected relations before unrelated
    # observations consume the node budget. Events still introduce each node
    # only when that persisted record becomes known in the chronology below.
    for item in selected:
        if not item["edge"]:
            continue
        endpoints = [node_id for node_id in item["edge"][:2] if node_id in entities]
        new_endpoints = [node_id for node_id in endpoints if node_id not in graph_node_set]
        if len(graph_node_ids) + len(new_endpoints) > GRAPH_NODE_LIMIT:
            continue
        graph_node_ids.extend(new_endpoints)
        graph_node_set.update(new_endpoints)
    for item in selected:
        for node_id in item["node_ids"]:
            if node_id not in entities or node_id in graph_node_set or len(graph_node_ids) >= GRAPH_NODE_LIMIT:
                continue
            graph_node_ids.append(node_id)
            graph_node_set.add(node_id)

    included_nodes: dict[str, dict[str, Any]] = {}
    graph_edges: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    included_relation_event_count = sum(item["kind"] == "relation" for item in selected)
    for event_index, item in enumerate(selected, 1):
        additions: list[dict[str, Any]] = []
        for node_id in item["node_ids"]:
            if node_id not in graph_node_set or node_id in included_nodes:
                continue
            entity = entities[node_id]
            node = {
                "id": node_alias[node_id] if redact else node_id,
                "kind": entity.kind if not redact or entity.kind in _SAFE_ENTITY_KINDS else "entity",
                "label": f"Hedef {len(included_nodes) + 1:02}" if redact else entity.canonical_value,
            }
            included_nodes[node_id] = node
            additions.append(node)
        event_evidence_ids = [value for value in item["evidence_ids"] if value in selected_observation_ids]
        edge_additions: list[dict[str, Any]] = []
        if item["edge"]:
            src_id, dst_id, relation_kind = item["edge"]
            if src_id in included_nodes and dst_id in included_nodes:
                edge = {
                    "id": f"edge-{len(graph_edges) + 1:03}",
                    "src_id": included_nodes[src_id]["id"],
                    "dst_id": included_nodes[dst_id]["id"],
                    "kind": "recorded_relation" if redact else relation_kind,
                    "evidence_refs": [evidence_alias[value] if redact else value for value in event_evidence_ids],
                }
                if not redact:
                    edge["record_ref"] = item["record_id"]
                graph_edges.append(edge)
                edge_additions.append(edge)
        event = {
            "id": f"event-{event_index:03}",
            "kind": item["kind"],
            "title": _TITLES[item["kind"]],
            "known_at": _iso(item["known_at_value"]),
            "observed_at": _iso(item["observed_at_value"]),
            "scope": "active_case" if redact else investigation_id,
            "status": item["status"] if not redact or item["status"] in _SAFE_STATUSES else "recorded",
            "evidence_refs": [evidence_alias[value] if redact else value for value in event_evidence_ids],
            "detail": _MASKED_DETAILS[item["kind"]]
            if redact
            else _raw_detail(item["kind"], item["row"], entities),
            "graph_additions": {"nodes": additions, "edges": edge_additions},
        }
        if not redact:
            event["record_ref"] = item["record_id"]
        events.append(event)

    available_counts = Counter(item["kind"] for item in candidates)
    included_counts = Counter(item["kind"] for item in selected)
    selected_ids = {item["record_id"] for item in selected}
    omitted_evidence_lifecycle = sum(
        item["kind"] not in {"observation", "relation"}
        and bool(item["evidence_ids"])
        and item["record_id"] not in selected_ids
        for item in candidates
    )
    supported_relation_events = len(relations) - unsupported_relations
    coverage = {
        "available_events": len(candidates),
        "included_events": len(selected),
        "omitted_events": max(0, len(candidates) - len(selected)),
        "event_limit": EVENT_LIMIT,
        "available_graph_nodes": len(all_node_ids),
        "included_graph_nodes": len(included_nodes),
        "omitted_graph_nodes": max(0, len(all_node_ids) - len(included_nodes)),
        "graph_node_limit": GRAPH_NODE_LIMIT,
        "relation_records": len(relations),
        "supported_relation_events": supported_relation_events,
        "included_relation_events": included_relation_event_count,
        "rendered_graph_edges": len(graph_edges),
        "omitted_graph_edges": max(0, supported_relation_events - len(graph_edges)),
        "included_relations": len(graph_edges),
        "unsupported_relations": unsupported_relations,
        "omitted_evidence_lifecycle_events": omitted_evidence_lifecycle,
        "events_truncated": len(candidates) > EVENT_LIMIT,
        "graph_truncated": len(all_node_ids) > GRAPH_NODE_LIMIT,
    }
    limitations = [
        "Bu oynatma kayıtlardan yeniden oluşturulur; canlı keşif veya model çağrısı yapmaz.",
        "Bilinen zaman kaydın sisteme alındığı zamanı, gözlem zamanı ise varsa kaynağın tarihsel zamanını gösterir.",
        "Eksik gözlem, yokluğun kanıtı değildir. Bağlantılar yalnızca kayıtlı destekleyici kanıtla gösterilir.",
    ]
    if coverage["events_truncated"]:
        limitations.append(
            f"Oynatma {EVENT_LIMIT} kayıtla sınırlandı; sınıra sığan başlangıç ve sonuç kayıtları tam kanıtlarıyla "
            f"korundu, ara gözlemler deterministik örneklendi. {coverage['omitted_events']} kayıt gösterilmedi."
        )
    if omitted_evidence_lifecycle:
        limitations.append(
            f"Tam kanıt kümesi sınıra sığmayan {omitted_evidence_lifecycle} çalışma veya analiz kaydı gösterilmedi."
        )
    if coverage["graph_truncated"]:
        limitations.append(
            f"Grafik {GRAPH_NODE_LIMIT} düğümle sınırlandı; kanıtlı bağlantı uçlarına öncelik verildi; {coverage['omitted_graph_nodes']} düğüm gösterilmedi."
        )
    if unsupported_relations:
        limitations.append(f"Kanıt bağlantısı bulunmayan {unsupported_relations} ilişki oynatmaya alınmadı.")
    return {
        "title": "Belgü · Kayıtlı inceleme" if redact else investigation.title,
        "redacted": redact,
        "recorded": True,
        "timing_basis": "known_at",
        "events": events,
        "graph": {"nodes": list(included_nodes.values()), "edges": graph_edges},
        "counts": {"available": dict(available_counts), "included": dict(included_counts)},
        "coverage": coverage,
        "limitations": limitations,
    }
