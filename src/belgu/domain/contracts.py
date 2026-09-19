from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EntityKind = Literal["url", "domain", "ip", "cert", "js_hash", "favicon_hash"]
SubmissionSource = Literal["customer_report", "analyst_discovery", "automated_discovery"]
ProviderStatus = Literal["ok", "partial", "unavailable", "rate_limited", "error"]
Disposition = Literal["unreviewed", "confirmed_phishing", "benign", "needs_review"]


@dataclass(frozen=True)
class Target:
    raw_value: str
    kind: EntityKind
    canonical_value: str
    hostname: str | None


@dataclass(frozen=True)
class EntityRef:
    kind: EntityKind
    value: str


@dataclass(frozen=True)
class EvidenceDraft:
    subject: EntityRef
    kind: str
    source_ref: str
    observed_at: datetime | None
    retrieved_at: datetime
    payload: dict[str, object]


@dataclass(frozen=True)
class RelationDraft:
    src: EntityRef
    dst: EntityRef
    kind: str
    evidence_indexes: tuple[int, ...]


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    status: ProviderStatus
    observations: tuple[EvidenceDraft, ...] = ()
    relations: tuple[RelationDraft, ...] = ()
    truncated: bool = False
    error_code: str | None = None


@dataclass(frozen=True)
class Limits:
    max_depth: int = 2
    max_entities: int = 500
    max_requests: int = 200
    max_seconds: int = 120
    provider_concurrency: int = 4


class View(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def normalize_utc_datetimes(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value


class TargetView(View):
    raw_value: str
    kind: EntityKind
    canonical_value: str
    hostname: str | None = None


class EntityRefView(View):
    kind: EntityKind
    value: str


class BrandView(View):
    id: str
    name: str
    official_domains: list[str]


class BrandPage(View):
    items: list[BrandView]
    next_cursor: str | None = None
    total_unique: int


class SubmissionView(View):
    id: str
    source: SubmissionSource
    note: str
    target: TargetView


class NoteView(View):
    id: str
    text: str
    created_at: datetime


class DecisionView(View):
    id: str
    value: Disposition
    note: str
    created_at: datetime


class ArtifactView(View):
    id: str
    sha256: str
    mime: str
    size_bytes: int
    investigation_id: str | None = None
    brand_id: str | None = None
    submission_id: str | None = None
    created_at: datetime


class AssessmentView(View):
    priority: Literal["normal", "review"]
    reasons: list[str]
    automated_verdict: Literal["insufficient_evidence", "candidate", "likely_phishing"]
    version: str = "assessment-v1"


class EvidenceView(View):
    id: str
    investigation_id: str
    subject: EntityRefView
    kind: str
    provider: str
    source_ref: str
    observed_at: datetime | None
    retrieved_at: datetime
    payload: dict[str, Any]


class RelationView(View):
    id: str
    src_id: str
    dst_id: str
    kind: str
    evidence_ids: list[str]


class SavedResult(View):
    evidence_ids: list[str]
    relation_ids: list[str]
    status: str
    truncated: bool = False


class InvestigationView(View):
    id: str
    title: str
    brand_id: str
    brand_name: str
    workflow: Literal["open", "closed"]
    disposition: Disposition
    priority: Literal["normal", "review"]
    created_at: datetime
    updated_at: datetime
    entity_count: int = 0
    evidence_count: int = 0
    source: str | None = None
    demo: bool = False
    submissions: list[SubmissionView] = Field(default_factory=list)
    notes: list[NoteView] = Field(default_factory=list)
    decisions: list[DecisionView] = Field(default_factory=list)
    attachments: list[ArtifactView] = Field(default_factory=list)
    jobs: list["JobView"] = Field(default_factory=list)
    assessment: AssessmentView | None = None


class InvestigationPage(View):
    items: list[InvestigationView]
    next_cursor: str | None = None
    total_unique: int


class EntityView(View):
    id: str
    kind: EntityKind
    canonical_value: str
    evidence_count: int = 0
    last_seen: datetime | None = None
    has_capture: bool = False
    shared_signals: list[str] = Field(default_factory=list)
    priority_score: int | None = None


class GroupView(View):
    key: str
    criterion: Literal["observed_ip", "cert_sha256", "js_sha256"]
    label: str
    entity_count: int
    evidence_ids: list[str]


class GroupPage(View):
    items: list[GroupView]
    next_cursor: str | None
    total_unique: int
    total_groups: int


class EntityPage(View):
    items: list[EntityView]
    next_cursor: str | None
    total_unique: int


class GraphView(View):
    nodes: list[EntityView]
    relations: list[RelationView]
    has_more: bool
    next_cursor: str | None


class JobView(View):
    id: str
    investigation_id: str
    kind: Literal["collect", "expand", "analysis", "capture"]
    status: Literal["queued", "running", "completed", "partial", "failed", "cancelled"]
    progress: dict[str, Any]
    limits: dict[str, Any]
    truncated: bool
    error: str | None
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime


class AnalysisView(View):
    id: str
    status: str
    output: dict[str, Any]
    model_id: str
    prompt_version: str
    snapshot_id: str
    stale: bool
    created_at: datetime
    recorded_demo: bool
    metrics: dict[str, Any]


class AnalysisPage(View):
    items: list[AnalysisView]
    next_cursor: str | None = None
    total_unique: int


class ModelStatusView(View):
    status: str
    model_id: str | None = None
    endpoint: str | None = None
    text_supported: bool
    vision_supported: bool | None = None
    message: str
    recorded_demo: bool = False


class ModelPage(View):
    items: list[ModelStatusView]
    status: str


InvestigationView.model_rebuild()
