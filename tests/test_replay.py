import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from belgu.application.service import NotFoundError
from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult, RelationDraft
from belgu.persistence.models import Analysis, Decision, Job, Observation, Submission


START = datetime(2026, 8, 12, 9, tzinfo=timezone.utc)


def recorded_case(service):
    brand = service.create_brand("Gizli Banka", ["official-secret.test"])
    investigation = service.create_investigation(brand.id, "Gizli vaka başlığı")
    submission = service.add_submission(
        investigation.id,
        "https://replay-secret.test/login?token=raw",
        "customer_report",
        "müşteri serbest metin notu",
    )
    observed_at = datetime(2021, 4, 3, 7, tzinfo=timezone.utc)
    saved = service.record_result(
        investigation.id,
        ProviderResult(
            "dns-secret-provider",
            "partial",
            (
                EvidenceDraft(
                    EntityRef("domain", "replay-secret.test"),
                    "dns_a",
                    "https://source-secret.test/query/replay-secret.test",
                    observed_at,
                    START + timedelta(minutes=20),
                    {
                        "answer": "198.51.100.77",
                        "note": "ham kanıt serbest metni",
                        "source_url": "https://payload-secret.test/raw",
                    },
                ),
            ),
            (
                RelationDraft(
                    EntityRef("domain", "replay-secret.test"),
                    EntityRef("ip", "198.51.100.77"),
                    "secret-relation-replay-secret.test",
                    (0,),
                ),
            ),
        ),
    )
    analysis = service.save_analysis(
        investigation.id,
        {
            "summary": "model serbest metin özeti",
            "model_id": "secret/model-v9",
            "claims": [
                {
                    "text": "gizli model iddiası",
                    "kind": "observation",
                    "evidence_ids": saved.evidence_ids,
                }
            ],
        },
        snapshot_evidence_ids=saved.evidence_ids,
    )
    decision = service.set_disposition(investigation.id, "needs_review", "analist serbest metin notu")
    with service.repo.transaction() as session:
        session.get(Submission, submission.id).created_at = START
        session.get(Analysis, analysis.id).created_at = START + timedelta(minutes=40)
        session.get(Decision, decision.id).created_at = START + timedelta(minutes=50)
        job = Job(
            investigation_id=investigation.id,
            kind="capture",
            status="failed",
            error="https://failed-secret.test/raw hata ayrıntısı",
            progress={"message": "özel yakalama mesajı"},
            created_at=START + timedelta(minutes=25),
            updated_at=START + timedelta(minutes=30),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    return {
        "investigation": investigation,
        "submission_id": submission.id,
        "evidence_id": saved.evidence_ids[0],
        "relation_id": saved.relation_ids[0],
        "analysis_id": analysis.id,
        "decision_id": decision.id,
        "job_id": job_id,
        "observed_at": observed_at,
    }


def test_replay_orders_recorded_rows_and_never_places_relation_before_its_evidence(service):
    from belgu.application.replay import build_replay

    case = recorded_case(service)
    replay = build_replay(service, case["investigation"].id, redact=False)

    assert [event["kind"] for event in replay["events"]] == [
        "submission",
        "observation",
        "relation",
        "job",
        "analysis",
        "decision",
    ]
    assert [event["known_at"] for event in replay["events"]] == sorted(
        event["known_at"] for event in replay["events"]
    )
    observation = next(event for event in replay["events"] if event["kind"] == "observation")
    relation = next(event for event in replay["events"] if event["kind"] == "relation")
    assert observation["observed_at"] == case["observed_at"].isoformat()
    assert observation["known_at"] == (START + timedelta(minutes=20)).isoformat()
    assert relation["known_at"] == observation["known_at"]
    assert relation["evidence_refs"] == [case["evidence_id"]]
    assert replay["events"].index(observation) < replay["events"].index(relation)
    assert relation["graph_additions"]["edges"][0]["evidence_refs"] == [case["evidence_id"]]
    assert all(event["scope"] == case["investigation"].id for event in replay["events"])
    failed = next(event for event in replay["events"] if event["kind"] == "job")
    assert failed["status"] == "failed"
    assert failed["known_at"] == (START + timedelta(minutes=30)).isoformat()
    assert "failed-secret.test" in failed["detail"]


def test_replay_excludes_uncited_relations_and_reports_event_and_graph_limits(service):
    from belgu.application.replay import build_replay
    from belgu.persistence.models import Entity, Relation

    brand = service.create_brand("Limit", ["limit.test"])
    investigation = service.create_investigation(brand.id, "Limit vaka")
    for index in range(165):
        service.add_submission(investigation.id, f"node-{index:03}.limit.test", "analyst_discovery")
    with service.repo.transaction() as session:
        entities = session.scalars(select(Entity).where(Entity.canonical_value.like("node-%.limit.test"))).all()
        session.add(
            Relation(
                investigation_id=investigation.id,
                src_id=entities[0].id,
                dst_id=entities[1].id,
                kind="unsupported_fixture",
            )
        )

    replay = build_replay(service, investigation.id, redact=False)

    assert len(replay["events"]) == 160
    assert replay["coverage"] == {
        "available_events": 165,
        "included_events": 160,
        "omitted_events": 5,
        "event_limit": 160,
        "available_graph_nodes": 165,
        "included_graph_nodes": 60,
        "omitted_graph_nodes": 105,
        "graph_node_limit": 60,
        "relation_records": 1,
        "supported_relation_events": 0,
        "included_relation_events": 0,
        "rendered_graph_edges": 0,
        "omitted_graph_edges": 0,
        "included_relations": 0,
        "unsupported_relations": 1,
        "omitted_evidence_lifecycle_events": 0,
        "events_truncated": True,
        "graph_truncated": True,
    }
    assert len(replay["graph"]["nodes"]) == 60
    assert replay["graph"]["edges"] == []
    assert any("deterministik" in item for item in replay["limitations"])
    assert all("ilk 160" not in item for item in replay["limitations"])


def test_bounded_replay_retains_recorded_opening_and_later_conclusion(service):
    from belgu.application.replay import build_replay

    brand = service.create_brand("Uzun", ["long.test"])
    investigation = service.create_investigation(brand.id, "Uzun vaka")
    submission = service.add_submission(investigation.id, "seed.long.test", "customer_report")
    evidence_ids = []
    for index in range(170):
        at = START + timedelta(minutes=index + 1)
        evidence_ids.extend(
            service.record_result(
                investigation.id,
                ProviderResult(
                    "fixture",
                    "ok",
                    (
                        EvidenceDraft(
                            EntityRef("domain", f"observed-{index:03}.long.test"),
                            "dns_a",
                            f"urn:fixture:{index}",
                            None,
                            at,
                            {"answer": f"192.0.2.{index % 255}"},
                        ),
                    ),
                ),
            ).evidence_ids
        )
    analysis = service.save_analysis(
        investigation.id,
        {
            "summary": "Son kayıtlı değerlendirme",
            "claims": [{"text": "Son kanıt", "evidence_ids": [evidence_ids[-1]]}],
        },
        snapshot_evidence_ids=[evidence_ids[-1]],
    )
    decision = service.set_disposition(investigation.id, "needs_review", "Kapanış kararı")
    with service.repo.transaction() as session:
        session.get(Submission, submission.id).created_at = START
        session.get(Analysis, analysis.id).created_at = START + timedelta(minutes=180)
        session.get(Decision, decision.id).created_at = START + timedelta(minutes=181)

    replay = build_replay(service, investigation.id, redact=False)

    assert len(replay["events"]) == 160
    assert replay["events"][0]["kind"] == "submission"
    assert [event["kind"] for event in replay["events"][-2:]] == ["analysis", "decision"]
    analysis_event = replay["events"][-2]
    assert analysis_event["evidence_refs"] == [evidence_ids[-1]]
    assert any(event.get("record_ref") == evidence_ids[-1] for event in replay["events"])


def test_retained_analysis_keeps_all_citations_or_is_explicitly_omitted(service):
    from belgu.application.replay import build_replay

    brand = service.create_brand("Atıf", ["citations.test"])
    investigation = service.create_investigation(brand.id, "Atıf sınırı")
    service.add_submission(investigation.id, "seed.citations.test", "customer_report")
    drafts = tuple(
        EvidenceDraft(
            EntityRef("domain", f"evidence-{index:03}.citations.test"),
            "dns_a",
            f"urn:citation:{index}",
            None,
            START + timedelta(minutes=index + 1),
            {"answer": f"192.0.2.{index % 255}"},
        )
        for index in range(200)
    )
    evidence_ids = service.record_result(
        investigation.id, ProviderResult("fixture", "ok", drafts)
    ).evidence_ids
    earlier = service.save_analysis(
        investigation.id,
        {"summary": "Önceki", "claims": [{"text": "A", "evidence_ids": evidence_ids[:100]}]},
        snapshot_evidence_ids=evidence_ids[:100],
    )
    later = service.save_analysis(
        investigation.id,
        {"summary": "Sonraki", "claims": [{"text": "B", "evidence_ids": evidence_ids[100:]}]},
        snapshot_evidence_ids=evidence_ids[100:],
    )
    with service.repo.transaction() as session:
        session.get(Analysis, earlier.id).created_at = START + timedelta(minutes=210)
        session.get(Analysis, later.id).created_at = START + timedelta(minutes=220)

    replay = build_replay(service, investigation.id, redact=False)
    analyses = [event for event in replay["events"] if event["kind"] == "analysis"]

    assert [event["record_ref"] for event in analyses] == [later.id]
    assert analyses[0]["evidence_refs"] == evidence_ids[100:]
    replayed_observations = {
        event["record_ref"] for event in replay["events"] if event["kind"] == "observation"
    }
    assert set(analyses[0]["evidence_refs"]) <= replayed_observations
    assert replay["coverage"]["omitted_evidence_lifecycle_events"] == 1


def test_citation_closure_that_fills_cap_does_not_force_an_extra_observation(service):
    from belgu.application.replay import build_replay

    brand = service.create_brand("Tam sınır", ["exact-cap.test"])
    investigation = service.create_investigation(brand.id, "Tam sınır vaka")
    for index in range(157):
        service.add_submission(
            investigation.id, f"seed-{index:03}.exact-cap.test", "analyst_discovery"
        )
    drafts = tuple(
        EvidenceDraft(
            EntityRef("domain", f"observed-{index}.exact-cap.test"),
            "dns_a",
            f"urn:exact-cap:{index}",
            None,
            START + timedelta(minutes=index),
            {"answer": f"192.0.2.{index + 1}"},
        )
        for index in range(3)
    )
    saved = service.record_result(
        investigation.id,
        ProviderResult(
            "fixture",
            "ok",
            drafts,
            (
                RelationDraft(
                    EntityRef("domain", "observed-2.exact-cap.test"),
                    EntityRef("ip", "192.0.2.3"),
                    "observed_ip",
                    (2,),
                ),
            ),
        ),
    )
    analysis = service.save_analysis(
        investigation.id,
        {"summary": "Sınır", "claims": [{"text": "İki kanıt", "evidence_ids": saved.evidence_ids[:2]}]},
        snapshot_evidence_ids=saved.evidence_ids[:2],
    )
    with service.repo.transaction() as session:
        session.get(Analysis, analysis.id).created_at = START + timedelta(minutes=10)

    replay = build_replay(service, investigation.id, redact=False)

    assert len(replay["events"]) == replay["coverage"]["included_events"] == 160
    assert replay["coverage"]["event_limit"] == 160
    analysis_event = next(event for event in replay["events"] if event["kind"] == "analysis")
    assert analysis_event["evidence_refs"] == saved.evidence_ids[:2]
    assert all(event.get("record_ref") != saved.evidence_ids[2] for event in replay["events"])
    assert replay["coverage"]["included_relation_events"] == 0


def test_graph_coverage_distinguishes_relation_event_from_rendered_edge(service):
    from belgu.application.replay import build_replay

    brand = service.create_brand("Graf", ["graph-cap.test"])
    investigation = service.create_investigation(brand.id, "Graf sınırı")
    drafts = tuple(
        EvidenceDraft(
            EntityRef("domain", f"node-{index:02}.graph-cap.test"),
            "dns_a",
            f"urn:graph:{index}",
            None,
            START + timedelta(minutes=index),
            {"answer": "192.0.2.1"},
        )
        for index in range(62)
    )
    relations = tuple(
        RelationDraft(
            EntityRef("domain", f"node-{index:02}.graph-cap.test"),
            EntityRef("domain", f"node-{index + 1:02}.graph-cap.test"),
            "related_fixture",
            (index + 1,),
        )
        for index in range(0, 62, 2)
    )
    service.record_result(
        investigation.id,
        ProviderResult("fixture", "ok", drafts, relations),
    )

    replay = build_replay(service, investigation.id, redact=False)

    assert replay["coverage"]["supported_relation_events"] == 31
    assert replay["coverage"]["included_relation_events"] == 31
    assert replay["coverage"]["rendered_graph_edges"] == 30
    assert replay["coverage"]["omitted_graph_edges"] == 1
    assert replay["coverage"]["included_relations"] == 30
    assert len(replay["graph"]["edges"]) == 30


def test_demo_replay_prioritizes_real_relation_endpoints_within_graph_cap(service):
    from belgu.application.replay import build_replay
    from belgu.demo.fixtures import seed_demo

    seed_demo(service)
    investigation = max(service.list_investigations(), key=lambda item: item.evidence_count)

    replay = build_replay(service, investigation.id, redact=False)

    assert len(replay["events"]) <= 160
    assert len(replay["graph"]["nodes"]) <= 60
    assert replay["coverage"]["supported_relation_events"] > 0
    assert replay["coverage"]["included_relation_events"] > 0
    assert replay["coverage"]["rendered_graph_edges"] == len(replay["graph"]["edges"])
    assert replay["coverage"]["rendered_graph_edges"] > 0
    observation_positions = {
        evidence: index
        for index, event in enumerate(replay["events"])
        if event["kind"] == "observation"
        for evidence in event["evidence_refs"]
    }
    for index, event in enumerate(replay["events"]):
        for edge in event["graph_additions"]["edges"]:
            assert edge["evidence_refs"]
            assert all(observation_positions[evidence] <= index for evidence in edge["evidence_refs"])


def test_replay_handles_empty_and_single_record_cases(service):
    from belgu.application.replay import build_replay

    brand = service.create_brand("Boş", ["empty.test"])
    empty = service.create_investigation(brand.id, "Boş vaka")
    assert build_replay(service, empty.id)["events"] == []
    service.add_submission(empty.id, "only.empty.test", "analyst_discovery")
    single = build_replay(service, empty.id)
    assert len(single["events"]) == 1
    assert single["events"][0]["kind"] == "submission"
    assert len(single["events"][0]["graph_additions"]["nodes"]) == 1


def test_masked_replay_payload_and_html_contain_no_identifiers_or_free_text(service):
    from belgu.reporting.replay import export_replay, save_replay_preview

    case = recorded_case(service)
    preview = save_replay_preview(service, case["investigation"].id, redact=True)
    html = export_replay(service, case["investigation"].id, preview["preview_id"], redact=True)
    serialized = json.dumps(preview, ensure_ascii=False)
    saved_path = service.evidence_dir / "replay-previews" / f'{preview["preview_id"]}.json'
    saved_serialized = saved_path.read_text()
    secrets = [
        "replay-secret.test",
        "official-secret.test",
        "source-secret.test",
        "payload-secret.test",
        "failed-secret.test",
        "198.51.100.77",
        "Gizli Banka",
        "Gizli vaka başlığı",
        "müşteri serbest metin notu",
        "ham kanıt serbest metni",
        "model serbest metin özeti",
        "gizli model iddiası",
        "analist serbest metin notu",
        "secret/model-v9",
        case["investigation"].id,
        case["submission_id"],
        case["evidence_id"],
        case["relation_id"],
        case["analysis_id"],
        case["decision_id"],
        case["job_id"],
    ]
    for secret in secrets:
        assert secret not in serialized
        assert secret not in html
        assert secret not in saved_serialized
    assert set(json.loads(saved_serialized)) == {"case_binding", "payload"}
    assert "https://" not in html
    assert "data:image" not in html
    assert "Maskeli kayıt" in html
    assert "Kaydı oynat" in html and "Önceki kayıt" in html and "Sonraki kayıt" in html
    assert "Hız" in html and 'type="range"' in html
    assert "fetch(" not in html and "<script src=" not in html and "<link " not in html


def test_saved_replay_export_uses_exact_snapshot_and_enforces_case_and_masking(service):
    from belgu.reporting.replay import export_replay, save_replay_preview

    case = recorded_case(service)
    preview = save_replay_preview(service, case["investigation"].id, redact=False)
    saved_path = service.evidence_dir / "replay-previews" / f'{preview["preview_id"]}.json'
    saved_payload = json.loads(saved_path.read_text())["payload"]
    assert {key: value for key, value in preview.items() if key != "preview_id"} == saved_payload
    service.add_submission(
        case["investigation"].id,
        "later-edit-secret.test",
        "analyst_discovery",
        "sonradan eklendi",
    )
    html = export_replay(service, case["investigation"].id, preview["preview_id"], redact=False)
    assert "replay-secret.test" in html
    assert "later-edit-secret.test" not in html
    other = service.create_investigation(case["investigation"].brand_id, "Başka vaka")
    with pytest.raises(NotFoundError):
        export_replay(service, other.id, preview["preview_id"], redact=False)
    with pytest.raises(ValueError, match="Gizleme seçimi"):
        export_replay(service, case["investigation"].id, preview["preview_id"], redact=True)


def test_replay_router_previews_and_exports_saved_recording(service):
    from belgu.api.routes.replay import router

    case = recorded_case(service)
    app = FastAPI()
    app.include_router(router(service, object()))
    with TestClient(app) as client:
        preview_response = client.post(f'/api/investigations/{case["investigation"].id}/replay/preview', json={})
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["redacted"] is True
        export_response = client.post(
            f'/api/investigations/{case["investigation"].id}/replay/export',
            json={"preview_id": preview["preview_id"], "redact": True},
        )
        assert export_response.status_code == 200
        assert export_response.headers["content-type"].startswith("text/html")
        assert export_response.headers["content-disposition"].endswith('"belgu-kayitli-inceleme.html"')
