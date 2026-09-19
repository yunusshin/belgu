from datetime import datetime, timedelta, timezone

import pytest

from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult, RelationDraft


def test_evidence_is_scoped_and_relation_provenance_is_atomic(service):
    brand = service.create_brand("Örnek Finans", ["ornek.test"])
    one = service.create_investigation(brand.id, "Birinci inceleme")
    two = service.create_investigation(brand.id, "İkinci inceleme")
    submission = service.add_submission(one.id, "https://ornek-destek.test/Giris?x=1", "customer_report")
    assert submission.target.raw_value.endswith("/Giris?x=1")

    domain = EntityRef("domain", "ornek-destek.test")
    ip = EntityRef("ip", "203.0.113.1")
    result = ProviderResult(
        "dns",
        "ok",
        (EvidenceDraft(domain, "dns_a", "urn:test:dns", None, datetime.now(timezone.utc), {"observed_ip": ip.value}),),
        (RelationDraft(domain, ip, "resolves_to", (0,)),),
    )
    saved = service.record_result(one.id, result)
    assert len(saved.evidence_ids) == 1
    assert len(service.list_evidence(one.id)) == 1
    assert service.list_evidence(two.id) == []
    assert service.get_assessment(one.id).automated_verdict == "candidate"

    bad = ProviderResult("dns", "ok", (), (RelationDraft(domain, ip, "resolves_to", (4,)),))
    with pytest.raises(ValueError):
        service.record_result(one.id, bad)
    assert len(service.list_relations(one.id)) == 1


def test_notes_workflow_decisions_and_reopen_persist(service):
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Karar")
    service.add_note(inv.id, "İlk analist notu")
    service.set_disposition(inv.id, "confirmed_phishing", "İçerik doğrulandı")
    service.set_disposition(inv.id, "needs_review", "Yeni kanıt geldi")
    service.set_workflow(inv.id, "closed")
    reopened = service.set_workflow(inv.id, "open")
    assert reopened.workflow == "open"
    assert [d.value for d in service.list_decisions(inv.id)] == ["confirmed_phishing", "needs_review"]
    assert service.get_investigation(inv.id).notes[0].text == "İlk analist notu"


def test_distinct_dns_answers_persist_while_exact_retry_is_idempotent(service):
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Birden çok A kaydı")
    now = datetime.now(timezone.utc)
    domain = EntityRef("domain", "multi.test")
    first_ip = EntityRef("ip", "203.0.113.10")
    second_ip = EntityRef("ip", "203.0.113.11")
    result = ProviderResult(
        "dns",
        "ok",
        (
            EvidenceDraft(domain, "dns_a", "dns:multi.test", now, now, {"answer": first_ip.value, "observed_ip": first_ip.value}),
            EvidenceDraft(domain, "dns_a", "dns:multi.test", now, now, {"answer": second_ip.value, "observed_ip": second_ip.value}),
        ),
        (
            RelationDraft(domain, first_ip, "resolves_to", (0,)),
            RelationDraft(domain, second_ip, "resolves_to", (1,)),
        ),
    )
    service.record_result(inv.id, result)
    service.record_result(inv.id, result)
    evidence = service.list_evidence(inv.id)
    assert len(evidence) == 2
    assert {item.payload["answer"] for item in evidence} == {first_ip.value, second_ip.value}
    assert len(service.list_relations(inv.id)) == 2
    groups = service.list_groups(inv.id, "observed_ip")
    assert {item.key for item in groups.items} == {first_ip.value, second_ip.value}


def test_changed_page_reread_is_new_evidence_and_marks_analysis_stale(service):
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Sayfa değişimi")
    now = datetime.now(timezone.utc)
    subject = EntityRef("domain", "changed.test")
    service.record_result(inv.id, ProviderResult("page", "ok", (
        EvidenceDraft(subject, "page_content", "https://changed.test/", now, now, {"title": "İlk içerik"}),
    )))
    analysis = service.save_analysis(inv.id, {
        "summary": "İlk snapshot", "claims": [], "uncertainties": [], "next_steps": [],
        "model_id": "fixture", "runtime_version": "fixture", "prompt_version": "v1", "metrics": {},
    })
    service.record_result(inv.id, ProviderResult("page", "ok", (
        EvidenceDraft(subject, "page_content", "https://changed.test/", now, now + timedelta(seconds=30), {"title": "Değişen içerik"}),
    )))
    assert len(service.list_evidence(inv.id)) == 2
    assert service.list_analyses(inv.id)[0].id == analysis.id
    assert service.list_analyses(inv.id)[0].stale is True
    from belgu.reporting.export import export_report
    assert "Güncellik: eski snapshot" in export_report(service, inv.id).decode()


def test_markdown_report_discloses_evidence_omitted_from_analysis(service):
    from belgu.reporting.export import export_report
    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Bağlam sınırı")
    now = datetime.now(timezone.utc)
    saved = service.record_result(inv.id, ProviderResult("page", "ok", (
        EvidenceDraft(EntityRef("domain", "first.test"), "page_content", "https://first.test/", now, now, {"title": "Birinci"}),
        EvidenceDraft(EntityRef("domain", "second.test"), "page_content", "https://second.test/", now, now, {"title": "İkinci"}),
    )))
    service.save_analysis(inv.id, {
        "summary": "Sınırlı kapsam", "claims": [], "uncertainties": [], "next_steps": [],
        "model_id": "fixture", "runtime_version": "fixture", "prompt_version": "v4", "metrics": {},
        "evidence_ids": [saved.evidence_ids[0]], "omitted_count": 1,
    })
    report = export_report(service, inv.id).decode()
    assert "Güncellik: güncel snapshot" in report
    assert "Analiz kapsamı: 1 kanıt değerlendirildi; bağlam sınırı nedeniyle 1 kayıt bu analize alınmadı." in report


@pytest.mark.parametrize("scope_excluded,budget_omitted", [(1, 0), (1, 1), (0, 0)])
def test_markdown_report_distinguishes_target_scope_from_context_limit(service, scope_excluded, budget_omitted):
    from belgu.reporting.export import export_report

    brand = service.create_brand("Örnek", ["ornek.test"])
    inv = service.create_investigation(brand.id, "Hedefe ait kanıtlar")
    service.add_submission(inv.id, "target.test", "analyst_discovery")
    now = datetime.now(timezone.utc)
    drafts = [EvidenceDraft(EntityRef("domain", "target.test"), "page_content", "https://target.test/", now, now, {"title": "Hedef"})]
    if scope_excluded:
        drafts.append(EvidenceDraft(EntityRef("domain", "neighbor.test"), "page_content", "https://neighbor.test/", now, now, {"title": "Komşu"}))
    if budget_omitted:
        drafts.append(EvidenceDraft(EntityRef("domain", "target.test"), "dns_a", "dns:target.test", now, now, {"observed_ip": "203.0.113.1"}))
    saved = service.record_result(inv.id, ProviderResult("fixture", "ok", tuple(drafts)))
    service.save_analysis(inv.id, {
        "summary": "Hedef kapsamı", "claims": [], "uncertainties": [], "next_steps": [],
        "model_id": "fixture", "runtime_version": "fixture", "prompt_version": "v6", "metrics": {},
        "evidence_ids": [saved.evidence_ids[0]],
        "analysis_scope": "submitted_targets", "scope_excluded_count": scope_excluded,
        "budget_omitted_count": budget_omitted, "omitted_count": scope_excluded + budget_omitted,
    })

    report = export_report(service, inv.id).decode()
    assert "Hedef analizi: 1 kanıt değerlendirildi." in report
    if scope_excluded:
        assert "İlişkili varlıklara ait 1 kayıt bu değerlendirmenin dışında." in report
    if budget_omitted:
        assert "Bağlam sınırı nedeniyle 1 hedef kaydı bu analize alınmadı." in report
    else:
        assert "bağlam sınırı" not in report.lower()
