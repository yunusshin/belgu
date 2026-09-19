import json

import pytest

from belgu.analysis.contracts import analysis_output_schema
from belgu.analysis.validation import AnalysisValidationError, validate_output


def valid_payload(**updates):
    payload = {
        "summary": "İki kayıt aynı IP adresini bildiriyor.",
        "claims": [
            {
                "text": "İki alan adı aynı IP ile gözlendi.",
                "evidence_ids": ["E01", "E02"],
                "kind": "observation",
            }
        ],
        "uncertainties": ["IP paylaşımlı barındırmaya ait olabilir."],
        "next_steps": ["Sayfa içeriklerini karşılaştır."],
    }
    payload.update(updates)
    return payload


def test_foreign_evidence_is_rejected():
    raw = json.dumps(
        {
            "summary": "İlişki bulundu",
            "claims": [
                {
                    "text": "Aynı IP",
                    "evidence_ids": ["foreign-id"],
                    "kind": "observation",
                }
            ],
            "uncertainties": [],
            "next_steps": [],
        }
    )
    with pytest.raises(AnalysisValidationError, match="foreign-id"):
        validate_output(raw, allowed_ids={"local-id"})


def test_schema_rejects_extra_fields_and_blank_claim_text():
    payload = valid_payload(disposition="confirmed_phishing")
    with pytest.raises(AnalysisValidationError):
        validate_output(json.dumps(payload), {"E01", "E02"})

    payload = valid_payload()
    payload["claims"][0]["text"] = " "
    with pytest.raises(AnalysisValidationError):
        validate_output(json.dumps(payload), {"E01", "E02"})


def test_empty_snapshot_requires_uncertainty_and_no_claims():
    empty = valid_payload(claims=[], uncertainties=[])
    with pytest.raises(AnalysisValidationError, match="uncertainty"):
        validate_output(json.dumps(empty), set())

    empty["uncertainties"] = ["Değerlendirilecek kanıt sağlanmadı."]
    assert validate_output(json.dumps(empty), set()).claims == []


def test_valid_output_is_strictly_parsed():
    result = validate_output(json.dumps(valid_payload()), {"E01", "E02"})
    assert result.claims[0].kind == "observation"
    assert result.claims[0].evidence_ids == ["E01", "E02"]


def test_report_shape_caps_representative_claims_and_sections():
    payload = valid_payload()
    payload["claims"] = payload["claims"] * 5
    with pytest.raises(AnalysisValidationError):
        validate_output(json.dumps(payload), {"E01", "E02"})

    schema = analysis_output_schema()
    assert schema["properties"]["claims"]["maxItems"] == 4
    assert schema["properties"]["uncertainties"]["maxItems"] == 3
    assert schema["properties"]["next_steps"]["maxItems"] == 3


@pytest.mark.parametrize("text", ["HTTP200 alındı.", "HTTP 200 alındı.", "HTTP/1.1 200 alındı.", "HTTP durum kodu200 alındı."])
@pytest.mark.parametrize("section", ["summary", "claim"])
def test_explicit_http_status_requires_structured_evidence(text, section):
    payload = valid_payload()
    if section == "summary":
        payload["summary"] = text
    else:
        payload["claims"][0]["text"] = text
    evidence = [{"id": "E01", "provider": "urlscan", "payload": {"title": "HTTP 200", "text": "HTTP 200", "upstream_http_status": 200}}]

    with pytest.raises(AnalysisValidationError, match="HTTP 200 kanıtta yok"):
        validate_output(json.dumps(payload), {"E01", "E02"}, evidence)


@pytest.mark.parametrize("status", [200, "200"])
def test_explicit_page_status_grounds_summary_and_citing_claim(status):
    payload = valid_payload(summary="HTTP 200 yanıtı alındı.")
    payload["claims"][0]["text"] = "HTTP durum kodu 200 gözlendi."
    evidence = [{"id": "E01", "provider": "page", "payload": {"status_code": status}}]

    assert validate_output(json.dumps(payload), {"E01", "E02"}, evidence).summary == "HTTP 200 yanıtı alındı."


@pytest.mark.parametrize("status", [True, False, None, 200.0, "200 OK", " 200", 99, 600, "0200", 404])
def test_invalid_or_different_status_value_cannot_ground_http_200(status):
    payload = valid_payload(summary="HTTP 200 yanıtı alındı.")
    evidence = [{"id": "E01", "provider": "page", "payload": {"status_code": status}}]

    with pytest.raises(AnalysisValidationError, match="HTTP 200 kanıtta yok"):
        validate_output(json.dumps(payload), {"E01", "E02"}, evidence)


def test_uncited_neighbor_status_does_not_ground_a_claim():
    payload = valid_payload(summary="HTTP 200 yanıtı bir kayıtta var.")
    payload["claims"][0].update(text="HTTP 200 yanıtı alındı.", evidence_ids=["E01"])
    evidence = [
        {"id": "E01", "provider": "dns", "payload": {"answer": "203.0.113.10"}},
        {"id": "E02", "provider": "page", "payload": {"status_code": 200}},
    ]

    with pytest.raises(AnalysisValidationError, match="HTTP 200 kanıtta yok"):
        validate_output(json.dumps(payload), {"E01", "E02"}, evidence)


def test_evidence_outside_allowed_snapshot_does_not_ground_summary():
    payload = valid_payload(summary="HTTP 200 yanıtı alındı.")
    evidence = [{"id": "OUTSIDE", "provider": "page", "payload": {"status_code": 200}}]

    with pytest.raises(AnalysisValidationError, match="HTTP 200 kanıtta yok"):
        validate_output(json.dumps(payload), {"E01", "E02"}, evidence)


def test_http_guard_does_not_scan_generic_numbers_or_uncertainties_and_next_steps():
    payload = valid_payload(
        summary="200 kayıt 2026 yılında 203.0.113.200 IP adresinde gözlendi.",
        uncertainties=["HTTP 200 yanıtı doğrulanmadı."],
        next_steps=["HTTP 200 alınıp alınmadığını kontrol et."],
    )

    assert validate_output(json.dumps(payload), {"E01", "E02"}, []).summary == payload["summary"]
