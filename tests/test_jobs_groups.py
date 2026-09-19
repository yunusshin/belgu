from datetime import datetime, timedelta, timezone
import time
from sqlalchemy import text

from belgu.application.jobs import JobService, Worker
from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult, RelationDraft


def test_job_claim_cancel_and_recovery(service):
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "İş")
    jobs = JobService(service)
    queued = jobs.enqueue(inv.id, "collect", {"limits": {"max_requests": 2}})
    claimed = jobs.claim("worker-test")
    assert claimed.id == queued.id and claimed.status == "running"
    cancelled = jobs.cancel(queued.id)
    assert cancelled.cancel_requested is True
    finished = jobs.finish(queued.id, {"status": "cancelled", "counts": {"requests": 0}, "truncated": False})
    assert finished.status == "cancelled"


def test_partial_source_result_does_not_claim_a_collection_limit(service):
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "HTTP yanıtı")
    jobs = JobService(service)
    job = jobs.enqueue(inv.id, "collect")
    source = {"provider": "page", "status": "partial", "error_code": "upstream_http_403", "observations": 1}
    finished = jobs.finish(job.id, {
        "status": "partial", "truncated": False,
        "counts": {"requests": 1, "observations": 1}, "providers": [source],
    })
    assert finished.status == "partial" and finished.truncated is False
    assert finished.progress["message"] == "Kısmi sonuçlarla tamamlandı"
    assert finished.progress["providers"] == [source]


def test_groups_and_graph_are_investigation_scoped_and_paginated(service):
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Gruplar")
    now = datetime.now(timezone.utc)
    for index in range(3):
        domain = EntityRef("domain", f"site-{index}.test")
        ip = EntityRef("ip", "203.0.113.9")
        service.record_result(
            inv.id,
            ProviderResult(
                "fixture",
                "ok",
                (EvidenceDraft(domain, "dns_a", f"urn:fixture:{index}", now, now, {"observed_ip": ip.value}),),
                (RelationDraft(domain, ip, "resolves_to", (0,)),),
            ),
        )
    groups = service.list_groups(inv.id, "observed_ip")
    assert groups.total_unique == 3
    assert groups.items[0].entity_count == 3
    first = service.list_entities(inv.id, limit=2)
    second = service.list_entities(inv.id, limit=2, cursor=first.next_cursor)
    assert len(first.items) == 2 and len(second.items) == 2
    assert {e.id for e in first.items}.isdisjoint(e.id for e in second.items)
    graph = service.graph(inv.id, limit=2)
    assert graph.has_more is True
    assert graph.relations[0].evidence_ids


def test_worker_restart_before_lease_expiry_recovers_job_when_it_later_expires(service):
    from belgu.persistence.models import Job, utcnow

    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Lease kurtarma")
    jobs = JobService(service)
    queued = jobs.enqueue(inv.id, "collect", {})
    claimed = jobs.claim("crashed-worker")
    assert claimed.id == queued.id
    with service.repo.transaction() as session:
        row = session.get(Job, queued.id)
        row.lease_expires_at = utcnow() + timedelta(milliseconds=80)

    replacement = Worker(service, "replacement-worker")
    replacement.recovery_interval = 0.02
    replacement.start()
    try:
        for _ in range(100):
            current = jobs.get(queued.id)
            if current.status in {"completed", "partial", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        assert current.status == "failed"
        assert "submitted target" in current.error
    finally:
        replacement.stop()


def test_entity_evidence_join_uses_investigation_subject_index(service):
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Sorgu planı")
    service.add_submission(inv.id, "indexed.test", "analyst_discovery")
    with service.sessions() as session:
        plan = session.execute(text("""
            EXPLAIN QUERY PLAN
            SELECT entities.id, count(observations.id)
            FROM entities
            JOIN investigation_entities
              ON investigation_entities.entity_id = entities.id
            LEFT JOIN observations
              ON observations.subject_id = entities.id
             AND observations.investigation_id = :investigation_id
            WHERE investigation_entities.investigation_id = :investigation_id
            GROUP BY entities.id
        """), {"investigation_id": inv.id}).all()
    detail = " ".join(str(column) for row in plan for column in row)
    assert "ix_observation_inv_subject" in detail
