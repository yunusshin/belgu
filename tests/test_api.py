import time
from datetime import datetime, timezone
import threading

from fastapi.testclient import TestClient


def create_case(client):
    brand = client.post("/api/brands", json={"name": "Örnek", "official_domains": ["ornek.test"]})
    assert brand.status_code == 201
    inv = client.post("/api/investigations", json={"brand_id": brand.json()["id"], "title": "Şüpheli destek"})
    assert inv.status_code == 201
    return brand.json(), inv.json()


def test_local_api_case_detail_and_report(api):
    _, inv = create_case(api)
    submitted = api.post(
        f"/api/investigations/{inv['id']}/submissions",
        json={"value": "https://destek.test/Giris?token=secret", "source": "customer_report", "note": "Analist aktardı"},
    )
    assert submitted.status_code == 201
    assert submitted.json()["target"]["raw_value"].endswith("token=secret")
    assert api.post(f"/api/investigations/{inv['id']}/notes", json={"text": "Takip gerekiyor"}).status_code == 201
    assert api.post(f"/api/investigations/{inv['id']}/decisions", json={"value": "needs_review", "note": "İnceleme açık"}).status_code == 201

    detail = api.get(f"/api/investigations/{inv['id']}").json()
    assert detail["created_at"].endswith("Z")
    assert datetime.fromisoformat(detail["created_at"]).utcoffset().total_seconds() == 0
    assert detail["source"] == "customer_report"
    assert detail["notes"][0]["text"] == "Takip gerekiyor"
    report = api.get(f"/api/investigations/{inv['id']}/report?format=markdown")
    assert report.status_code == 200
    assert "token=%5BREDACTED%5D" in report.text
    assert "secret" not in report.text


def test_collections_have_cursor_contract_and_errors_are_structured(api):
    _, inv = create_case(api)
    response = api.get(f"/api/investigations/{inv['id']}/entities?limit=50")
    assert response.json() == {"items": [], "next_cursor": None, "total_unique": 0}
    missing = api.get("/api/investigations/not-a-real-id")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_openapi_exposes_core_response_contracts(api):
    schema = api.get("/openapi.json").json()
    expected = {
        ("/api/brands", "get"): "BrandPage",
        ("/api/investigations", "get"): "InvestigationPage",
        ("/api/investigations/{investigation_id}", "get"): "InvestigationView",
        ("/api/investigations/{investigation_id}/entities", "get"): "EntityPage",
        ("/api/investigations/{investigation_id}/groups", "get"): "GroupPage",
        ("/api/investigations/{investigation_id}/graph", "get"): "GraphView",
        ("/api/investigations/{investigation_id}/evidence/{evidence_id}", "get"): "EvidenceView",
        ("/api/investigations/{investigation_id}/analyses", "get"): "AnalysisPage",
        ("/api/jobs/{job_id}", "get"): "JobView",
    }
    for (path, method), model in expected.items():
        response = schema["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert response["$ref"].endswith(f"/{model}")


def test_analysis_job_records_model_unavailable(api, monkeypatch):
    monkeypatch.setenv("BELGU_MODEL_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("BELGU_MODEL_TIMEOUT", "1")
    _, inv = create_case(api)
    queued = api.post(f"/api/investigations/{inv['id']}/analyses", json={})
    assert queued.status_code == 202
    job_id = queued.json()["id"]
    for _ in range(100):
        job = api.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"failed", "completed"}:
            break
        time.sleep(0.02)
    assert job["status"] == "failed"
    assert "model" in job["error"].lower()


def test_demo_mode_never_enters_live_discovery(tmp_path, monkeypatch):
    from belgu.api.app import create_app
    from belgu.settings import Settings
    import belgu.core.discovery

    def network_was_used(*args, **kwargs):
        raise AssertionError("network discovery path was called")

    monkeypatch.setattr(belgu.core.discovery, "discover", network_was_used)
    import belgu.analysis.service
    monkeypatch.setattr(belgu.analysis.service, "get_model_status", network_was_used)
    app = create_app(Settings(
        db_url=f"sqlite:///{tmp_path / 'demo.db'}",
        evidence_dir=tmp_path / "evidence",
        mode="demo",
        start_worker=True,
    ))
    with TestClient(app) as client:
        model = client.get("/api/models").json()
        assert model["status"] == "recorded_demo"
        assert model["items"][0]["recorded_demo"] is True
        _, inv = create_case(client)
        client.post(
            f"/api/investigations/{inv['id']}/submissions",
            json={"value": "https://offline.test/", "source": "analyst_discovery", "note": ""},
        )
        queued = client.post(f"/api/investigations/{inv['id']}/jobs", json={"kind": "collect"}).json()
        for _ in range(100):
            job = client.get(f"/api/jobs/{queued['id']}").json()
            if job["status"] == "failed":
                break
            time.sleep(0.01)
        assert "demo mode network is disabled" in job["error"]


def test_background_discovery_persists_results_and_provider_status(api, monkeypatch):
    import belgu.core.discovery
    from belgu.core.discovery import DiscoveryResult
    from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult, RelationDraft

    def recorded_discovery(value, limits=None, cancelled=None, progress=None, provider_settings=None):
        assert provider_settings['mnemonic']['enabled'] is True
        progress({"requests": 1, "entities": 2, "provider": "fixture", "message": "fixture loaded"})
        domain = EntityRef("domain", "recorded.test")
        ip = EntityRef("ip", "203.0.113.44")
        now = datetime.now(timezone.utc)
        result = ProviderResult(
            "fixture",
            "ok",
            (EvidenceDraft(domain, "dns_a", "urn:fixture:recorded", now, now, {"observed_ip": ip.value}),),
            (RelationDraft(domain, ip, "resolves_to", (0,)),),
        )
        unavailable = ProviderResult("optional.feed", "unavailable", error_code="not_configured")
        return DiscoveryResult([result, unavailable], "completed", {"requests": 1, "entities": 2, "observations": 1}, False)

    monkeypatch.setattr(belgu.core.discovery, "discover", recorded_discovery)
    _, inv = create_case(api)
    api.post(
        f"/api/investigations/{inv['id']}/submissions",
        json={"value": "recorded.test", "source": "analyst_discovery", "note": ""},
    )
    queued = api.post(f"/api/investigations/{inv['id']}/jobs", json={"kind": "collect"}).json()
    for _ in range(100):
        job = api.get(f"/api/jobs/{queued['id']}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert job["status"] == "completed"
    assert {item["status"] for item in job["progress"]["providers"]} == {"ok", "unavailable"}
    detail = api.get(f"/api/investigations/{inv['id']}").json()
    assert detail["evidence_count"] == 1


def test_background_analysis_saves_snapshot_and_becomes_stale(api, monkeypatch):
    import belgu.analysis.service
    from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult

    def recorded_analysis(evidence, context=None):
        return {
            "summary": "Kanıtla sınırlı kayıtlı test analizi.",
            "claims": [{"text": "DNS gözlemi var.", "evidence_ids": [evidence[0]["id"]], "kind": "observation"}],
            "uncertainties": ["İçerik bilinmiyor."],
            "next_steps": ["Sayfayı incele."],
            "model_id": "fixture-model",
            "runtime_version": "fixture-runtime",
            "prompt_version": "v1",
            "metrics": {"elapsed_ms": 1},
            "evidence_ids": [evidence[0]["id"]],
            "omitted_count": 0,
        }

    monkeypatch.setattr(belgu.analysis.service, "analyze_evidence", recorded_analysis)
    monkeypatch.setattr(belgu.analysis.service, "get_model_status", lambda: {
        "status": "ready", "model_id": "fixture-model", "endpoint": "http://127.0.0.1:9/v1",
        "text_supported": True, "vision_supported": False, "message": "fixture",
    })
    _, inv = create_case(api)
    now = datetime.now(timezone.utc)
    service = api.app.state.service
    service.record_result(inv["id"], ProviderResult("fixture", "ok", (
        EvidenceDraft(EntityRef("domain", "one.test"), "dns_a", "urn:one", now, now, {"observed_ip": "203.0.113.1"}),
    )))
    queued = api.post(f"/api/investigations/{inv['id']}/analyses", json={"model_id": "fixture-model"}).json()
    for _ in range(100):
        job = api.get(f"/api/jobs/{queued['id']}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert job["status"] == "completed"
    first = api.get(f"/api/investigations/{inv['id']}/analyses").json()["items"][0]
    assert first["model_id"] == "fixture-model" and first["stale"] is False

    service.record_result(inv["id"], ProviderResult("fixture", "ok", (
        EvidenceDraft(EntityRef("domain", "two.test"), "dns_a", "urn:two", now, now, {"observed_ip": "203.0.113.2"}),
    )))
    stale = api.get(f"/api/investigations/{inv['id']}/analyses").json()["items"][0]
    assert stale["stale"] is True


def test_analysis_rejects_a_model_id_other_than_the_local_runtime(api, monkeypatch):
    import belgu.analysis.service

    monkeypatch.setattr(belgu.analysis.service, "get_model_status", lambda: {
        "status": "ready", "model_id": "configured-model", "endpoint": "http://127.0.0.1:9/v1",
        "text_supported": True, "vision_supported": False, "message": "fixture",
    })
    monkeypatch.setattr(belgu.analysis.service, "analyze_evidence", lambda *args, **kwargs: {"summary": "must not run"})
    _, inv = create_case(api)
    queued = api.post(f"/api/investigations/{inv['id']}/analyses", json={"model_id": "other-model"}).json()
    for _ in range(100):
        job = api.get(f"/api/jobs/{queued['id']}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert job["status"] == "failed"
    assert "selected model" in job["error"]


def test_analysis_snapshot_is_captured_before_inference(api, monkeypatch):
    import belgu.analysis.service
    from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult
    from belgu.persistence.models import Brand, Investigation

    brand, inv = create_case(api)
    service = api.app.state.service
    service.add_submission(inv["id"], "https://before.test/Giris", "analyst_discovery", "Model bağlamına taşınmayan not")
    now = datetime.now(timezone.utc)
    service.record_result(inv["id"], ProviderResult("fixture", "ok", (
        EvidenceDraft(EntityRef("domain", "before.test"), "dns_a", "urn:before", now, now, {"observed_ip": "203.0.113.1"}),
    )))
    initial_evidence_ids = [item.id for item in service.list_evidence(inv["id"])]
    received_context = {}

    def evidence_arrives_during_inference(evidence, context=None):
        received_context.update(context or {})
        with service.repo.transaction() as session:
            session.get(Brand, brand["id"]).official_domains = ["changed.test"]
            session.get(Investigation, inv["id"]).title = "Sonradan değişen başlık"
        service.add_submission(inv["id"], "during.test", "analyst_discovery")
        service.record_result(inv["id"], ProviderResult("fixture", "ok", (
            EvidenceDraft(EntityRef("domain", "during.test"), "dns_a", "urn:during", now, now, {"observed_ip": "203.0.113.2"}),
        )))
        return {
            "summary": "Snapshot testi", "claims": [{"text": "İlk kanıt", "evidence_ids": [evidence[0]["id"]], "kind": "observation"}],
            "uncertainties": [], "next_steps": [], "model_id": "fixture-model", "runtime_version": "fixture",
            "prompt_version": "v1", "metrics": {}, "evidence_ids": [evidence[0]["id"]], "omitted_count": 0,
        }

    monkeypatch.setattr(belgu.analysis.service, "get_model_status", lambda: {
        "status": "ready", "model_id": "fixture-model", "endpoint": "fixture", "text_supported": True,
        "vision_supported": False, "message": "fixture",
    })
    monkeypatch.setattr(belgu.analysis.service, "analyze_evidence", evidence_arrives_during_inference)
    queued = api.post(f"/api/investigations/{inv['id']}/analyses", json={"model_id": "fixture-model"}).json()
    for _ in range(100):
        job = api.get(f"/api/jobs/{queued['id']}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    analysis = api.get(f"/api/investigations/{inv['id']}/analyses").json()["items"][0]
    assert job["status"] == "completed"
    assert analysis["stale"] is True
    assert analysis["output"]["evidence_ids"] == initial_evidence_ids
    assert analysis["output"]["claims"][0]["evidence_ids"] == initial_evidence_ids
    assert "analysis_time" in received_context
    analysis_time = datetime.fromisoformat(received_context.pop("analysis_time"))
    assert analysis_time.utcoffset().total_seconds() == 0
    assert now <= analysis_time <= datetime.now(timezone.utc)
    assert received_context == {
        "investigation_id": inv["id"],
        "model_id": "fixture-model",
        "investigation_title": "Şüpheli destek",
        "brand": {"name": "Örnek", "official_domains": ["ornek.test"]},
        "targets": [{"kind": "url", "canonical_value": "https://before.test/Giris", "hostname": "before.test"}],
    }


def test_cancel_during_inference_does_not_save_output(api, monkeypatch):
    import belgu.analysis.service

    started = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(belgu.analysis.service, "get_model_status", lambda: {
        "status": "ready", "model_id": "fixture-model", "endpoint": "fixture", "text_supported": True,
        "vision_supported": False, "message": "fixture",
    })

    def blocking_analysis(evidence, context=None):
        started.set()
        release.wait(2)
        return {
            "summary": "İptal edilen çıktı", "claims": [], "uncertainties": [], "next_steps": [],
            "model_id": "fixture-model", "runtime_version": "fixture", "prompt_version": "v1",
            "metrics": {}, "evidence_ids": [], "omitted_count": 0,
        }

    monkeypatch.setattr(belgu.analysis.service, "analyze_evidence", blocking_analysis)
    _, inv = create_case(api)
    queued = api.post(f"/api/investigations/{inv['id']}/analyses", json={"model_id": "fixture-model"}).json()
    assert started.wait(1)
    api.post(f"/api/jobs/{queued['id']}/cancel")
    release.set()
    for _ in range(100):
        job = api.get(f"/api/jobs/{queued['id']}").json()
        if job["status"] in {"cancelled", "failed", "completed"}:
            break
        time.sleep(0.01)
    assert job["status"] == "cancelled"
    assert api.get(f"/api/investigations/{inv['id']}/analyses").json()["items"] == []


def test_multiple_submissions_share_one_discovery_budget(api, monkeypatch):
    import belgu.core.discovery
    from belgu.core.discovery import DiscoveryResult
    from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult

    calls = []

    def budgeted_fixture(value, limits=None, cancelled=None, progress=None, provider_settings=None):
        calls.append((value, limits.max_requests, limits.max_entities))
        index = len(calls)
        now = datetime.now(timezone.utc)
        result = ProviderResult("fixture", "ok", (
            EvidenceDraft(EntityRef("domain", f"found-{index}.test"), "dns_a", f"urn:found:{index}", now, now, {"observed_ip": f"203.0.113.{index}"}),
        ))
        return DiscoveryResult([result], "completed", {"requests": 3 if index == 1 else 2, "entities": 2, "new_entities": 1, "observations": 1, "providers": 1}, False)

    monkeypatch.setattr(belgu.core.discovery, "discover", budgeted_fixture)
    _, inv = create_case(api)
    for value in ("first.test", "second.test"):
        api.post(f"/api/investigations/{inv['id']}/submissions", json={"value": value, "source": "analyst_discovery", "note": ""})
    queued = api.post(f"/api/investigations/{inv['id']}/jobs", json={
        "kind": "collect", "limits": {"max_requests": 5, "max_entities": 5, "max_seconds": 30},
    }).json()
    for _ in range(100):
        job = api.get(f"/api/jobs/{queued['id']}").json()
        if job["status"] in {"completed", "partial", "failed"}:
            break
        time.sleep(0.01)
    assert calls == [("first.test", 5, 5), ("second.test", 2, 3)]
    assert job["progress"]["requests"] == 5
    assert job["progress"]["entities"] == 4
