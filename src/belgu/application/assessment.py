from belgu.domain.contracts import AssessmentView, EvidenceView


def assess(evidence: list[EvidenceView]) -> AssessmentView:
    reasons: list[str] = []
    priority = "normal"
    verdict = "insufficient_evidence"
    for item in evidence:
        payload = item.payload
        if any(payload.get(key) for key in ("observed_ip", "cert_sha256", "js_sha256", "favicon_hash")):
            if "shared_infrastructure" not in reasons:
                reasons.append("shared_infrastructure")
            verdict = "candidate"
        if item.kind in {"feed_match", "threat_report"} or payload.get("feed_report"):
            if "feed_report" not in reasons:
                reasons.append("feed_report")
            priority = "review"
            verdict = "candidate"
        if payload.get("brand_impersonation") and payload.get("credential_form"):
            for reason in ("brand_impersonation", "credential_form"):
                if reason not in reasons:
                    reasons.append(reason)
            priority = "review"
            verdict = "likely_phishing"
    if not reasons:
        reasons = ["insufficient_evidence"]
    return AssessmentView(priority=priority, reasons=reasons, automated_verdict=verdict)
