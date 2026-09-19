import json

import httpx
import pytest

from belgu.analysis.client import ModelClient, ModelClientError
from belgu.analysis.contracts import ModelInfo
from belgu.analysis import service


def evidence_item(evidence_id="E01", payload=None):
    return {
        "id": evidence_id,
        "subject": {"kind": "domain", "value": "aday.test"},
        "provider": "fixture",
        "source_ref": "urn:fixture:1",
        "observed_at": "2026-09-08T00:00:00Z",
        "retrieved_at": "2026-09-08T00:01:00Z",
        "payload": payload or {"title": "Banka giriş"},
    }


def response(raw, finish_reason="stop"):
    return httpx.Response(
        200,
        json={
            "model": "fixture-model",
            "choices": [
                {"finish_reason": finish_reason, "message": {"content": raw}}
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 25},
        },
    )


def valid_raw(evidence_id="E01"):
    return json.dumps(
        {
            "summary": "Kanıt özeti.",
            "claims": [
                {
                    "text": "Başlık banka giriş ifadesi içeriyor.",
                    "evidence_ids": [evidence_id],
                    "kind": "observation",
                }
            ],
            "uncertainties": ["Sayfanın sahibi doğrulanmadı."],
            "next_steps": ["Alan adı kaydını incele."],
        }
    )


def fixture_client(handler):
    client = ModelClient(
        "http://127.0.0.1:8080/v1",
        "fixture-model",
        transport=httpx.MockTransport(handler),
    )
    client.models = lambda: [
        ModelInfo(id="fixture-model", runtime_version="fixture-runtime")
    ]
    return client


def test_analyze_uses_same_snapshot_ids_and_reports_metrics(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        return response(valid_raw())

    client = fixture_client(handler)
    monkeypatch.setattr(service, "_make_client", lambda: client)
    result = service.analyze_evidence([evidence_item()])

    assert result["claims"][0]["evidence_ids"] == ["E01"]
    assert result["evidence_ids"] == ["E01"]
    assert result["omitted_count"] == 0
    assert result["metrics"]["input_tokens"] == 100
    assert result["prompt_version"] == "v9"
    assert result["runtime_version"] == "fixture-runtime"


def test_invalid_output_gets_one_repair_attempt(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        calls += 1
        if calls == 1:
            return response(valid_raw("FOREIGN"))
        return response(valid_raw())

    monkeypatch.setattr(
        service,
        "_make_client",
        lambda: fixture_client(handler),
    )
    result = service.analyze_evidence([evidence_item()])
    assert calls == 2
    assert result["metrics"]["repair_attempted"] is True


def test_two_invalid_outputs_fail_honestly(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        calls += 1
        return response(valid_raw("FOREIGN"))

    monkeypatch.setattr(
        service,
        "_make_client",
        lambda: fixture_client(handler),
    )
    with pytest.raises(service.AnalysisError) as exc:
        service.analyze_evidence([evidence_item()])
    assert exc.value.code == "invalid_model_output"
    assert calls == 2


def test_unsupported_http_status_uses_existing_single_repair(monkeypatch):
    completions = []

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        completions.append(body["messages"])
        payload = json.loads(valid_raw())
        payload["summary"] = (
            "HTTP 200 yanıtı alındı." if len(completions) == 1 else "HTTP yanıt durumu bilinmiyor."
        )
        return response(json.dumps(payload))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    evidence = evidence_item(payload={"title": "HTTP 200 park sayfası", "scan_id": "historical-scan"})
    evidence["provider"] = "urlscan"

    result = service.analyze_evidence([evidence])

    assert result["summary"] == "HTTP yanıt durumu bilinmiyor."
    assert result["metrics"]["repair_attempted"] is True
    assert len(completions) == 2
    assert "HTTP 200 kanıtta yok" in completions[1][-1]["content"]


def test_repeated_unsupported_http_status_fails_after_one_repair(monkeypatch):
    completions = 0

    def handler(request):
        nonlocal completions
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        completions += 1
        payload = json.loads(valid_raw())
        payload["claims"][0]["text"] = "HTTP/1.1 200 yanıtı gözlendi."
        return response(json.dumps(payload))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))

    with pytest.raises(service.AnalysisError, match="HTTP 200 kanıtta yok") as error:
        service.analyze_evidence([evidence_item()])
    assert error.value.code == "invalid_model_output"
    assert completions == 2


def test_oversized_evidence_omits_whole_records(monkeypatch):
    token_calls = 0

    def handler(request):
        nonlocal token_calls
        if request.url.path.endswith("/input_tokens"):
            token_calls += 1
            request_body = json.loads(request.content)
            evidence_count = request_body["messages"][1]["content"].count('"id"')
            return httpx.Response(
                200, json={"input_tokens": 7000 if evidence_count > 1 else 900}
            )
        return response(valid_raw("E01"))

    monkeypatch.setattr(
        service,
        "_make_client",
        lambda: fixture_client(handler),
    )
    result = service.analyze_evidence([evidence_item(), evidence_item("E02")])
    assert result["evidence_ids"] == ["E01"]
    assert result["omitted_count"] == 1
    assert token_calls >= 2


def test_large_snapshot_uses_logarithmic_token_checks(monkeypatch):
    token_calls = 0

    def handler(request):
        nonlocal token_calls
        if request.url.path.endswith("/input_tokens"):
            token_calls += 1
            body = json.loads(request.content)
            count = body["messages"][1]["content"].count('"id"')
            return httpx.Response(200, json={"input_tokens": 300 + count * 50})
        return response(valid_raw("E000"))

    monkeypatch.setattr(
        service,
        "_make_client",
        lambda: fixture_client(handler),
    )
    evidence = [evidence_item(f"E{index:03d}") for index in range(128)]
    result = service.analyze_evidence(evidence)
    assert result["omitted_count"] == 12
    assert token_calls <= 10


def test_page_evidence_is_selected_before_bulk_dns(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/input_tokens"):
            body = json.loads(request.content)
            count = body["messages"][1]["content"].count('"id"')
            return httpx.Response(200, json={"input_tokens": 7000 if count > 1 else 500})
        return response(valid_raw("PAGE"))

    monkeypatch.setattr(
        service,
        "_make_client",
        lambda: fixture_client(handler),
    )
    dns = evidence_item("DNS", {"observed_ip": "203.0.113.1"})
    dns["provider"] = "dns"
    page = evidence_item("PAGE", {"visible_text": "Banka giriş", "credential_form": True})
    page["provider"] = "page_content"
    result = service.analyze_evidence([dns, page])
    assert result["evidence_ids"] == ["PAGE"]


def test_primary_dns_and_history_survive_neighbor_page_flood(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        snapshot = json.loads(body["messages"][1]["content"].split("\n")[-1])
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(
                200, json={"input_tokens": 7000 if len(snapshot) > 2 else 500}
            )
        return response(valid_raw(snapshot[0]["id"]))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    neighbors = []
    for index in range(300):
        neighbor = evidence_item(f"N{index:03d}", {"visible_text": "Komşu sayfa"})
        neighbor["subject"] = {"kind": "url", "value": f"https://neighbor{index}.test/"}
        neighbor["provider"] = "page_content"
        neighbors.append(neighbor)
    current_dns = evidence_item("DNS_CURRENT", {"observed_ip": "203.0.113.10"})
    current_dns["provider"] = "dns"
    history = evidence_item("HISTORY", {"observed_ip": "203.0.113.20"})
    history["provider"] = "urlscan"
    history["observed_at"] = "2024-01-01T00:00:00Z"
    extra_primary = evidence_item("EXTRA", {"record_type": "TXT", "value": "example"})
    extra_primary["provider"] = "passive_metadata"

    result = service.analyze_evidence(
        neighbors + [current_dns, history, extra_primary],
        {"targets": [{"kind": "domain", "canonical_value": "aday.test", "hostname": "aday.test"}]},
    )

    assert result["evidence_ids"] == ["DNS_CURRENT", "HISTORY"]
    assert result["claims"][0]["evidence_ids"] == ["DNS_CURRENT"]
    assert result["omitted_count"] == 301
    assert result["analysis_scope"] == "submitted_targets"
    assert result["scope_excluded_count"] == 300
    assert result["budget_omitted_count"] == 1
    assert result["metrics"]["input_budget_units"] == 500
    assert result["metrics"]["input_tokens"] == 100  # Usage reported by the completion.


def test_current_primary_dns_and_page_precede_same_host_scan_archive(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        snapshot = json.loads(body["messages"][1]["content"].split("\n")[-1])
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(
                200, json={"input_tokens": 7000 if len(snapshot) > 2 else 500}
            )
        return response(valid_raw(snapshot[0]["id"]))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    archive = []
    for index in range(100):
        scan = evidence_item(
            f"SCAN{index:03d}",
            {
                "url": "https://aday.test/login",
                "title": "Geçmiş banka giriş sayfası",
                "answer": "203.0.113.20",
                "observed_ip": "203.0.113.20",
                "country": "TR",
                "asn": "AS64500",
                "scan_id": f"fixture-scan-{index}",
                "scan_source": "api",
            },
        )
        scan["provider"] = "urlscan"
        scan["source_ref"] = f"https://urlscan.io/result/fixture-scan-{index}/"
        scan["observed_at"] = "2024-01-01T00:00:00Z"
        archive.append(scan)
    dns = evidence_item(
        "DNS_CURRENT", {"answer": "203.0.113.10", "observed_ip": "203.0.113.10", "rrtype": "A", "ttl": 300}
    )
    dns["provider"] = "dns"
    page = evidence_item(
        "PAGE_CURRENT", {"title": "Erişim engellenmiştir", "visible_text": "Bu adrese erişim engellenmiştir."}
    )
    page["provider"] = "page"
    page["subject"] = {"kind": "url", "value": "https://aday.test/"}

    result = service.analyze_evidence(
        archive + [dns, page],
        {"targets": [{"kind": "domain", "canonical_value": "aday.test", "hostname": "aday.test"}]},
    )

    assert result["evidence_ids"] == ["DNS_CURRENT", "PAGE_CURRENT"]
    assert result["claims"][0]["evidence_ids"] == ["DNS_CURRENT"]
    assert result["omitted_count"] == 100
    assert result["scope_excluded_count"] == 0
    assert result["budget_omitted_count"] == 100


@pytest.mark.parametrize(
    ("target", "direct_subject"),
    [
        (
            {"kind": "url", "canonical_value": "https://ADAY.test./login?next=other.test", "hostname": "aday.test"},
            {"kind": "domain", "value": "AdAy.Test."},
        ),
        (
            {"kind": "domain", "canonical_value": "aday.test", "hostname": "aday.test"},
            {"kind": "url", "value": "https://ADAY.test.:8443/different/path"},
        ),
        (
            {"kind": "ip", "canonical_value": "2001:db8::1", "hostname": None},
            {"kind": "url", "value": "https://[2001:0db8:0:0:0:0:0:1]/login"},
        ),
    ],
)
def test_primary_matching_normalizes_exact_host_or_ip_without_lookalikes(
    monkeypatch, target, direct_subject
):
    def handler(request):
        body = json.loads(request.content)
        snapshot = json.loads(body["messages"][1]["content"].split("\n")[-1])
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        return response(valid_raw(snapshot[0]["id"]))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    related = []
    for index, hostname in enumerate(("xaday.test", "aday.test.evil.test", "sub.aday.test")):
        neighbor = evidence_item(f"OTHER{index}", {"visible_text": "İlgisiz sayfa"})
        neighbor["subject"] = {"kind": "url", "value": f"https://{hostname}/"}
        neighbor["provider"] = "page_content"
        related.append(neighbor)
    direct = evidence_item("DIRECT", {"record_type": "A", "value": "203.0.113.1"})
    direct["provider"] = "dns"
    direct["subject"] = direct_subject

    result = service.analyze_evidence(related + [direct], {"targets": [target]})

    assert result["evidence_ids"] == ["DIRECT"]
    assert result["omitted_count"] == 3
    assert result["scope_excluded_count"] == 3
    assert result["budget_omitted_count"] == 0


def test_submitted_target_scope_excludes_neighbor_form_even_when_everything_fits(monkeypatch):
    delivered = []

    def handler(request):
        body = json.loads(request.content)
        message = body["messages"][1]["content"].split("\n")
        prompt_context = json.loads(message[1])
        snapshot = json.loads(message[-1])
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        delivered.append((prompt_context, snapshot))
        return response(valid_raw(snapshot[0]["id"]))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    neighbor = evidence_item("NEIGHBOR", {"visible_text": "Parolanızı girin", "credential_form": True})
    neighbor["subject"] = {"kind": "url", "value": "https://neighbor.test/login"}
    neighbor["provider"] = "page"
    direct = evidence_item("DIRECT", {"answer": "203.0.113.10", "rrtype": "A"})
    direct["provider"] = "dns"
    context = {
        "targets": [{"kind": "domain", "canonical_value": "aday.test"}],
        "analysis_scope": "provided_evidence",
    }
    evidence = [neighbor, direct]
    original_evidence = json.loads(json.dumps(evidence))

    result = service.analyze_evidence(evidence, context)

    assert result["evidence_ids"] == ["DIRECT"]
    assert result["analysis_scope"] == "submitted_targets"
    assert result["scope_excluded_count"] == 1
    assert result["budget_omitted_count"] == 0
    assert result["omitted_count"] == 1
    assert delivered[0][0]["analysis_scope"] == "submitted_targets"
    assert [item["id"] for item in delivered[0][1]] == ["DIRECT"]
    assert context["analysis_scope"] == "provided_evidence"
    assert evidence == original_evidence


def test_scope_and_record_byte_limits_report_separate_omission_reasons(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        return response(valid_raw("ROOT000"))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    direct = [evidence_item(f"ROOT{index:03d}") for index in range(205)]
    oversized_direct = evidence_item("ROOT_LARGE", {"visible_text": "x" * 40000})
    neighbors = [evidence_item("OTHER"), evidence_item("OTHER_LARGE", {"visible_text": "x" * 40000})]
    for item in neighbors:
        item["subject"] = {"kind": "domain", "value": "neighbor.test"}

    result = service.analyze_evidence(
        neighbors + direct + [oversized_direct],
        {"targets": [{"kind": "domain", "canonical_value": "aday.test"}]},
    )

    assert len(result["evidence_ids"]) == 200
    assert result["scope_excluded_count"] == 2
    assert result["budget_omitted_count"] == 6
    assert result["omitted_count"] == 8


@pytest.mark.parametrize(
    "context",
    [None, {"targets": []}, {"targets": [{"kind": "url", "canonical_value": "invalid"}], "analysis_scope": "submitted_targets"}],
)
def test_without_valid_targets_uses_all_provided_evidence(monkeypatch, context):
    delivered_context = []

    def handler(request):
        body = json.loads(request.content)
        delivered_context.append(json.loads(body["messages"][1]["content"].split("\n")[1]))
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        return response(valid_raw("E01"))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    other = evidence_item("OTHER")
    other["subject"] = {"kind": "domain", "value": "neighbor.test"}

    result = service.analyze_evidence([evidence_item(), other], context)

    assert result["evidence_ids"] == ["E01", "OTHER"]
    assert result["analysis_scope"] == "provided_evidence"
    assert result["scope_excluded_count"] == result["budget_omitted_count"] == result["omitted_count"] == 0
    assert all(item["analysis_scope"] == "provided_evidence" for item in delivered_context)


def test_valid_target_with_no_eligible_observations_keeps_empty_snapshot_contract(monkeypatch):
    delivered = []

    def handler(request):
        body = json.loads(request.content)
        snapshot = json.loads(body["messages"][1]["content"].split("\n")[-1])
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        delivered.append(snapshot)
        return response(json.dumps({
            "summary": "Gönderilen hedef için kanıt bulunmuyor.",
            "claims": [],
            "uncertainties": ["Hedefin mevcut durumu doğrulanamıyor."],
            "next_steps": ["Hedef için kanıt topla."],
        }))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    neighbor = evidence_item()
    neighbor["subject"] = {"kind": "domain", "value": "neighbor.test"}

    result = service.analyze_evidence(
        [neighbor], {"targets": [{"kind": "domain", "canonical_value": "aday.test"}]}
    )

    assert delivered == [[]]
    assert result["evidence_ids"] == result["claims"] == []
    assert result["uncertainties"]
    assert result["analysis_scope"] == "submitted_targets"
    assert result["scope_excluded_count"] == result["omitted_count"] == 1
    assert result["budget_omitted_count"] == 0


def test_repair_request_must_fit_verified_input_budget(monkeypatch):
    completions = 0

    def handler(request):
        nonlocal completions
        if request.url.path.endswith("/input_tokens"):
            body = json.loads(request.content)
            return httpx.Response(
                200, json={"input_tokens": 7000 if len(body["messages"]) > 2 else 500}
            )
        completions += 1
        return response(valid_raw("FOREIGN"))

    monkeypatch.setattr(
        service,
        "_make_client",
        lambda: fixture_client(handler),
    )
    with pytest.raises(service.AnalysisError) as exc:
        service.analyze_evidence([evidence_item()])
    assert exc.value.code == "token_budget_unverified"
    assert completions == 1


def test_oversized_context_is_rejected_before_tokenization(monkeypatch):
    monkeypatch.setattr(
        service,
        "_make_client",
        lambda: fixture_client(
            lambda request: pytest.fail("oversized context reached HTTP transport")
        ),
    )
    with pytest.raises(service.AnalysisError) as exc:
        service.analyze_evidence([evidence_item()], {"note": "x" * 40000})
    assert exc.value.code == "invalid_context"


def test_serialized_snapshot_is_bounded_before_tokenization(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/input_tokens"):
            body = json.loads(request.content)
            assert len(body["messages"][1]["content"].encode()) <= 530000
            return httpx.Response(200, json={"input_tokens": 500})
        return response(valid_raw("E000"))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    evidence = [
        evidence_item(f"E{index:03d}", {"visible_text": "x" * 20000})
        for index in range(40)
    ]
    result = service.analyze_evidence(evidence)
    assert result["omitted_count"] > 0
    assert result["budget_omitted_count"] == result["omitted_count"]
    assert result["scope_excluded_count"] == 0


def test_long_snapshot_ids_are_aliased_then_restored(monkeypatch):
    actual_id = "285a4056-1c3c-46da-a53a-5fbd9850171d"

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/input_tokens"):
            prompt = body["messages"][1]["content"]
            assert '"id":"E001"' in prompt
            assert actual_id not in prompt
            return httpx.Response(200, json={"input_tokens": 400})
        return response(valid_raw("E001"))

    monkeypatch.setattr(service, "_make_client", lambda: fixture_client(handler))
    result = service.analyze_evidence([evidence_item(actual_id)])
    assert result["claims"][0]["evidence_ids"] == [actual_id]
    assert result["evidence_ids"] == [actual_id]


def test_status_is_honest_when_model_is_unavailable(monkeypatch):
    class Offline:
        base_url = "http://127.0.0.1:8080/v1"

        def models(self):
            raise ModelClientError("model_unavailable", "bağlantı kurulamadı")

    monkeypatch.setattr(service, "_make_client", Offline)
    status = service.get_model_status()
    assert status["status"] == "unavailable"
    assert status["model_id"] is None
    assert "bağlantı" in status["message"]


def test_browser_evidence_projection_preserves_form_signal_without_duplicate_large_payload():
    import copy
    raw=evidence_item('BROWSER', {'text':'Görünür metin '*1000,'ocr_text':'OCR metni '*1000,
        'text_source':'rendered_dom','credential_form':True,'status_code':200,'ocr_status':'ok',
        'inputs':[{'type':'text','name':'search'}]*200+[{'type':'password','name':'password'}],
        'forms':[{'action':'/session','method':'post','inputs':[{'type':'text'}]*100}]*20})
    raw['provider']='browser_capture';raw['kind']='page_browser';original=copy.deepcopy(raw)
    normalized,omitted,scope=service._normalize_evidence([raw],{'targets':[{'kind':'domain','canonical_value':'aday.test'}]})
    assert len(normalized)==1 and omitted==0
    p=normalized[0]['payload']
    assert p['credential_form'] is True and p['text_source']=='rendered_dom'
    assert p['inputs'][0]['type']=='password'
    assert p['analysis_projection']['inputs_total']==201
    assert len(p['text'])<=4000 and len(p['ocr_text'])<=2000
    assert raw==original


def test_browser_capture_is_prioritized_before_bulk_archives():
    browser=evidence_item('BROWSER',{'text':'Rendered content','text_source':'rendered_dom'})
    browser['provider']='browser_capture'
    archive=evidence_item('ARCHIVE');archive['provider']='urlscan'
    rows,_,_=service._normalize_evidence([archive,browser],{'targets':[{'kind':'domain','canonical_value':'aday.test'}]})
    assert [r['id'] for r in rows]==['BROWSER','ARCHIVE']
