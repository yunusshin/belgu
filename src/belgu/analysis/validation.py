import json
import re

from pydantic import ValidationError

from .contracts import AnalysisOutput


_HTTP_STATUS_MENTION = re.compile(
    r"\bHTTP(?:/[0-9]+(?:\.[0-9]+)?)?\s*"
    r"(?:(?:durum(?:\s+kodu)?|status(?:\s+code)?)\s*)?"
    r"[:=]?\s*([1-5][0-9]{2})(?![0-9])",
    re.IGNORECASE,
)


class AnalysisValidationError(ValueError):
    """The model returned JSON that cannot be accepted as analyst evidence."""


def validate_output(
    raw: str, allowed_ids: set[str], evidence: list[dict] | None = None
) -> AnalysisOutput:
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AnalysisValidationError(f"invalid JSON output: {exc}") from exc

    try:
        output = AnalysisOutput.model_validate(decoded)
    except ValidationError as exc:
        raise AnalysisValidationError(f"invalid analysis schema: {exc}") from exc

    cited = {
        evidence_id
        for claim in output.claims
        for evidence_id in claim.evidence_ids
    }
    foreign = sorted(cited - allowed_ids)
    if foreign:
        raise AnalysisValidationError(
            "output cited evidence outside this snapshot: " + ", ".join(foreign)
        )
    if not allowed_ids:
        if output.claims:
            raise AnalysisValidationError("claims are not allowed without evidence")
        if not output.uncertainties:
            raise AnalysisValidationError(
                "at least one uncertainty is required for an empty snapshot"
            )
    _validate_http_status_grounding(output, allowed_ids, evidence or [])
    return output


def _validate_http_status_grounding(
    output: AnalysisOutput, allowed_ids: set[str], evidence: list[dict]
) -> None:
    status_by_id = {}
    for item in evidence:
        if not isinstance(item, dict) or item.get("id") not in allowed_ids:
            continue
        payload = item.get("payload")
        status = payload.get("status_code") if isinstance(payload, dict) else None
        if type(status) is int and 100 <= status <= 599:
            status_by_id[item["id"]] = status
        elif isinstance(status, str) and re.fullmatch(r"[1-5][0-9]{2}", status):
            status_by_id[item["id"]] = int(status)

    _require_observed_http_status(output.summary, set(status_by_id.values()))
    for claim in output.claims:
        cited_statuses = {
            status_by_id[evidence_id]
            for evidence_id in claim.evidence_ids
            if evidence_id in status_by_id
        }
        _require_observed_http_status(claim.text, cited_statuses)


def _require_observed_http_status(text: str, observed_statuses: set[int]) -> None:
    # Deliberately narrow: explicit HTTP codes in summary/claims only. Even a
    # negated unsupported code must be rephrased without its numeric value;
    # uncertainties and next steps are not observation assertions.
    for match in _HTTP_STATUS_MENTION.finditer(text):
        status = int(match.group(1))
        if status not in observed_statuses:
            raise AnalysisValidationError(
                f"HTTP {status} kanıtta yok; HTTP yanıt durumunu bilinmiyor olarak "
                "belirt, bu sayısal kodu özete veya iddiaya ekleme."
            )
