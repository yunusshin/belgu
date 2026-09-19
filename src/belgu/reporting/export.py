from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme not in {"http", "https"} or not parts.query:
        return value
    query = urlencode([(key, "[REDACTED]") for key, _ in parse_qsl(parts.query, keep_blank_values=True)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_url(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in {"email", "phone", "telephone", "token", "password"}:
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact(item)
        return result
    return value


def export_report(service, investigation_id: str, format: str = "markdown", redact: bool = True) -> bytes:
    investigation = service.get_investigation(investigation_id)
    evidence = [item.model_dump(mode="json") for item in service.list_evidence(investigation_id)]
    analyses = [item.model_dump(mode="json") for item in service.list_analyses(investigation_id)]
    report = {
        "report_version": "belgu-report-v1",
        "investigation": investigation.model_dump(mode="json"),
        "evidence": evidence,
        "analyses": analyses,
        "provenance": {
            "evidence_count": len(evidence),
            "sources": sorted({item["source_ref"] for item in evidence}),
        },
    }
    if redact:
        report = _redact(report)
    if format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2).encode()
    if format != "markdown":
        raise ValueError("format must be markdown or json")

    inv = report["investigation"]
    assessment = inv.get("assessment") or {}
    lines = [
        f"# Belgü İnceleme Raporu: {inv['title']}",
        "",
        f"- İnceleme: `{inv['id']}`",
        f"- Marka: {inv['brand_name']}",
        f"- İş akışı: {inv['workflow']}",
        f"- Analist kararı: {inv['disposition']}",
        f"- Otomatik değerlendirme: {assessment.get('automated_verdict', 'insufficient_evidence')}",
        f"- Öncelik: {assessment.get('priority', 'normal')}",
        f"- Gerekçeler: {', '.join(assessment.get('reasons', []))}",
        "",
        "## Gönderimler",
        "",
    ]
    for submission in inv.get("submissions", []):
        lines.append(f"- **{submission['source']}** — `{submission['target']['canonical_value']}` — {submission['note']}")
    lines.extend(["", "## Kanıt", ""])
    for item in report["evidence"]:
        observed = item["observed_at"] or "kaynakta yok"
        lines.append(f"- `{item['id']}` {item['kind']} — {item['provider']} — {item['source_ref']} — gözlem {observed}, alım {item['retrieved_at']}")
    lines.extend(["", "## Yerel analiz", ""])
    if not report["analyses"]:
        lines.append("Model analizi bulunmuyor; kanıt ve analist kararı bağımsız olarak kullanılabilir.")
    for analysis in report["analyses"]:
        label = "kayıtlı kurmaca demo" if analysis["recorded_demo"] else analysis["model_id"]
        lines.append(f"### {label} / snapshot `{analysis['snapshot_id']}`")
        lines.append(f"- Güncellik: {'eski snapshot — yeni kanıt geldi' if analysis['stale'] else 'güncel snapshot'}")
        output = analysis["output"]
        omitted = output.get("omitted_count", 0)
        included = len(output.get("evidence_ids", []))
        if output.get("analysis_scope") == "submitted_targets":
            lines.append(f"- Hedef analizi: {included} kanıt değerlendirildi.")
            excluded = output.get("scope_excluded_count", 0)
            if excluded:
                lines.append(f"- İlişkili varlıklara ait {excluded} kayıt bu değerlendirmenin dışında.")
            budget_omitted = output.get("budget_omitted_count", 0)
            if budget_omitted:
                lines.append(f"- Bağlam sınırı nedeniyle {budget_omitted} hedef kaydı bu analize alınmadı.")
        elif omitted:
            lines.append(f"- Analiz kapsamı: {included} kanıt değerlendirildi; bağlam sınırı nedeniyle {omitted} kayıt bu analize alınmadı.")
        lines.append(analysis["output"].get("summary", ""))
        for claim in analysis["output"].get("claims", []):
            lines.append(f"- {claim['text']} (dayanak: {', '.join(claim['evidence_ids'])})")
        for uncertainty in analysis["output"].get("uncertainties", []):
            lines.append(f"- Belirsizlik: {uncertainty}")
    lines.extend(["", "## Analist notları ve karar geçmişi", ""])
    for note in inv.get("notes", []):
        lines.append(f"- {note['created_at']}: {note['text']}")
    for decision in inv.get("decisions", []):
        lines.append(f"- {decision['created_at']}: **{decision['value']}** — {decision['note']}")
    return ("\n".join(lines) + "\n").encode()
