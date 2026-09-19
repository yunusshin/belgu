from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, event, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from belgu.application.assessment import assess
from belgu.domain.contracts import (
    AnalysisView,
    ArtifactView,
    AssessmentView,
    BrandView,
    DecisionView,
    EntityPage,
    EntityRef,
    EntityRefView,
    EvidenceView,
    GraphView,
    GroupPage,
    InvestigationView,
    JobView,
    NoteView,
    ProviderResult,
    RelationView,
    SavedResult,
    SubmissionView,
    TargetView,
)
from belgu.domain.targets import canonicalize_entity, parse_target
from belgu.persistence.models import (
    Analysis,
    Artifact,
    CollectionRun,
    Base,
    Brand,
    Decision,
    Entity,
    Investigation,
    InvestigationEntity,
    Job,
    Note,
    Observation,
    Relation,
    Submission,
    relation_evidence,
    observation_fingerprint,
    utcnow,
)
from belgu.persistence.repository import Repository


class NotFoundError(LookupError):
    pass


class InvalidRelationEvidence(ValueError):
    pass


class InvalidArtifact(ValueError):
    pass


class BelguService:
    def __init__(self, engine, factory: sessionmaker[Session], evidence_dir: Path):
        self.engine = engine
        self.sessions = factory
        self.repo = Repository(factory)
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        from belgu.integrations import IntegrationStore
        self.integrations = IntegrationStore(self.evidence_dir.parent / 'integrations.json')

    @classmethod
    def open(cls, db_url: str, evidence_dir: str | Path | None = None) -> "BelguService":
        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        engine = create_engine(db_url, connect_args=connect_args)
        if db_url.startswith("sqlite"):
            @event.listens_for(engine, "connect")
            def configure_sqlite(connection, _record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
        Base.metadata.create_all(engine)
        path = Path(evidence_dir or ".belgu/evidence")
        return cls(engine, sessionmaker(engine, expire_on_commit=False), path)

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _required(session: Session, model, object_id: str):
        value = session.get(model, object_id)
        if value is None:
            raise NotFoundError(f"{model.__name__.lower()} not found")
        return value

    def create_brand(self, name: str, official_domains: list[str]) -> BrandView:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("brand name cannot be empty")
        domains = [parse_target(value).canonical_value for value in official_domains]
        if any(parse_target(value).kind != "domain" for value in official_domains):
            raise ValueError("official domains must be domains")
        with self.repo.transaction() as session:
            row = Brand(name=clean_name, official_domains=sorted(set(domains)))
            session.add(row)
            session.flush()
            return BrandView(id=row.id, name=row.name, official_domains=row.official_domains)

    def list_brands(self) -> list[BrandView]:
        with self.sessions() as session:
            rows = session.scalars(select(Brand).order_by(Brand.name, Brand.id)).all()
            return [BrandView(id=r.id, name=r.name, official_domains=r.official_domains) for r in rows]

    def create_investigation(self, brand_id: str, title: str, *, demo: bool = False) -> InvestigationView:
        if not title.strip():
            raise ValueError("title cannot be empty")
        with self.repo.transaction() as session:
            self._required(session, Brand, brand_id)
            row = Investigation(brand_id=brand_id, title=title.strip(), demo=demo)
            session.add(row)
            session.flush()
            investigation_id = row.id
        return self.get_investigation(investigation_id)

    def _ensure_entity(self, session: Session, ref: EntityRef, investigation_id: str, role: str = "observed") -> Entity:
        canonical = canonicalize_entity(ref)
        entity = session.scalar(select(Entity).where(Entity.kind == canonical.kind, Entity.canonical_value == canonical.value))
        if entity is None:
            entity = Entity(kind=canonical.kind, canonical_value=canonical.value)
            session.add(entity)
            session.flush()
        linked = session.scalar(select(InvestigationEntity).where(InvestigationEntity.investigation_id == investigation_id, InvestigationEntity.entity_id == entity.id))
        if linked is None:
            session.add(InvestigationEntity(investigation_id=investigation_id, entity_id=entity.id, role=role))
        return entity

    def add_submission(self, investigation_id: str, value: str, source: str, note: str = "") -> SubmissionView:
        if source not in {"customer_report", "analyst_discovery", "automated_discovery"}:
            raise ValueError("invalid submission source")
        target = parse_target(value)
        with self.repo.transaction() as session:
            self._required(session, Investigation, investigation_id)
            row = Submission(
                investigation_id=investigation_id,
                source=source,
                note=note,
                raw_value=target.raw_value,
                kind=target.kind,
                canonical_value=target.canonical_value,
                hostname=target.hostname,
            )
            session.add(row)
            self._ensure_entity(session, EntityRef(target.kind, target.canonical_value), investigation_id, "seed")
            if target.kind == "url" and target.hostname:
                self._ensure_entity(session, EntityRef("domain", target.hostname), investigation_id, "seed_host")
            session.flush()
            result = self._submission_view(row)
        return result

    @staticmethod
    def _submission_view(row: Submission) -> SubmissionView:
        return SubmissionView(
            id=row.id,
            source=row.source,
            note=row.note,
            target=TargetView(raw_value=row.raw_value, kind=row.kind, canonical_value=row.canonical_value, hostname=row.hostname),
        )

    def record_result(self, investigation_id: str, result: ProviderResult, *, job_id: str | None = None) -> SavedResult:
        for relation in result.relations:
            if not relation.evidence_indexes or any(index < 0 or index >= len(result.observations) for index in relation.evidence_indexes):
                raise InvalidRelationEvidence("relation references missing observation")
        evidence_ids: list[str] = []
        relation_ids: list[str] = []
        with self.repo.transaction() as session:
            investigation = self._required(session, Investigation, investigation_id)
            observation_rows: list[Observation] = []
            for draft in result.observations:
                subject = self._ensure_entity(session, draft.subject, investigation_id)
                fingerprint = observation_fingerprint(
                    result.provider,
                    draft.source_ref,
                    subject.id,
                    draft.kind,
                    draft.observed_at,
                    draft.retrieved_at,
                    draft.payload,
                )
                existing = session.scalar(select(Observation).where(
                    Observation.investigation_id == investigation_id,
                    Observation.fingerprint == fingerprint,
                ))
                if existing is None:
                    existing = Observation(
                        investigation_id=investigation_id,
                        subject_id=subject.id,
                        kind=draft.kind,
                        provider=result.provider,
                        source_ref=draft.source_ref,
                        observed_at=draft.observed_at,
                        retrieved_at=draft.retrieved_at,
                        payload=draft.payload,
                        fingerprint=fingerprint,
                    )
                    session.add(existing)
                    session.flush()
                observation_rows.append(existing)
                evidence_ids.append(existing.id)
            for draft in result.relations:
                src = self._ensure_entity(session, draft.src, investigation_id)
                dst = self._ensure_entity(session, draft.dst, investigation_id)
                relation = session.scalar(select(Relation).where(
                    Relation.investigation_id == investigation_id,
                    Relation.src_id == src.id,
                    Relation.dst_id == dst.id,
                    Relation.kind == draft.kind,
                ))
                if relation is None:
                    relation = Relation(investigation_id=investigation_id, src_id=src.id, dst_id=dst.id, kind=draft.kind)
                    session.add(relation)
                    session.flush()
                for index in draft.evidence_indexes:
                    session.execute(insert(relation_evidence).prefix_with("OR IGNORE").values(relation_id=relation.id, observation_id=observation_rows[index].id))
                relation_ids.append(relation.id)
            if job_id:
                job=self._required(session,Job,job_id)
                if job.investigation_id!=investigation_id or job.kind not in ('collect','expand'):
                    raise ValueError('Observation job must belong to this investigation')
                run=session.get(CollectionRun,job_id)
                if run is None:
                    run=CollectionRun(id=job_id,investigation_id=investigation_id,evidence_ids=[],created_at=job.created_at)
                    session.add(run)
                run.evidence_ids=list(dict.fromkeys([*run.evidence_ids,*evidence_ids]))
            investigation.updated_at = utcnow()
        return SavedResult(evidence_ids=evidence_ids, relation_ids=relation_ids, status=result.status, truncated=result.truncated)

    def list_evidence(self, investigation_id: str) -> list[EvidenceView]:
        with self.sessions() as session:
            self._required(session, Investigation, investigation_id)
            rows = session.execute(
                select(Observation, Entity)
                .join(Entity, Entity.id == Observation.subject_id)
                .where(Observation.investigation_id == investigation_id)
                .order_by(Observation.retrieved_at, Observation.id)
            ).all()
            return [self._evidence_view(obs, entity) for obs, entity in rows]

    @staticmethod
    def _evidence_view(row: Observation, entity: Entity) -> EvidenceView:
        return EvidenceView(
            id=row.id,
            investigation_id=row.investigation_id,
            subject=EntityRefView(kind=entity.kind, value=entity.canonical_value),
            kind=row.kind,
            provider=row.provider,
            source_ref=row.source_ref,
            observed_at=row.observed_at,
            retrieved_at=row.retrieved_at,
            payload=row.payload,
        )

    def get_evidence(self, investigation_id: str, evidence_id: str) -> EvidenceView:
        with self.sessions() as session:
            result = session.execute(select(Observation, Entity).join(Entity, Entity.id == Observation.subject_id).where(Observation.id == evidence_id, Observation.investigation_id == investigation_id)).first()
            if result is None:
                raise NotFoundError("evidence not found")
            return self._evidence_view(*result)

    def list_relations(self, investigation_id: str) -> list[RelationView]:
        with self.sessions() as session:
            rows = session.scalars(select(Relation).where(Relation.investigation_id == investigation_id).order_by(Relation.id)).all()
            views = []
            for row in rows:
                evidence_ids = list(session.scalars(select(relation_evidence.c.observation_id).where(relation_evidence.c.relation_id == row.id)))
                views.append(RelationView(id=row.id, src_id=row.src_id, dst_id=row.dst_id, kind=row.kind, evidence_ids=evidence_ids))
            return views

    def get_entity(self, investigation_id: str, entity_id: str):
        with self.sessions() as session:
            row = session.scalar(
                select(Entity)
                .join(InvestigationEntity, InvestigationEntity.entity_id == Entity.id)
                .where(InvestigationEntity.investigation_id == investigation_id, Entity.id == entity_id)
            )
            if row is None:
                raise NotFoundError("entity not found")
            return EntityRef(row.kind, row.canonical_value)

    def add_note(self, investigation_id: str, text: str) -> NoteView:
        if not text.strip():
            raise ValueError("note cannot be empty")
        with self.repo.transaction() as session:
            self._required(session, Investigation, investigation_id)
            row = Note(investigation_id=investigation_id, text=text.strip())
            session.add(row)
            session.flush()
            return NoteView.model_validate(row)

    def set_disposition(self, investigation_id: str, value: str, note: str) -> DecisionView:
        if value not in {"unreviewed", "confirmed_phishing", "benign", "needs_review"}:
            raise ValueError("invalid disposition")
        with self.repo.transaction() as session:
            self._required(session, Investigation, investigation_id)
            row = Decision(investigation_id=investigation_id, value=value, note=note)
            session.add(row)
            session.flush()
            return DecisionView.model_validate(row)

    def list_decisions(self, investigation_id: str) -> list[DecisionView]:
        with self.sessions() as session:
            rows = session.scalars(select(Decision).where(Decision.investigation_id == investigation_id).order_by(Decision.created_at, Decision.id)).all()
            return [DecisionView.model_validate(row) for row in rows]

    def set_workflow(self, investigation_id: str, value: str) -> InvestigationView:
        if value not in {"open", "closed"}:
            raise ValueError("invalid workflow")
        with self.repo.transaction() as session:
            row = self._required(session, Investigation, investigation_id)
            row.workflow = value
            row.updated_at = utcnow()
        return self.get_investigation(investigation_id)

    def get_assessment(self, investigation_id: str) -> AssessmentView:
        return assess(self.list_evidence(investigation_id))

    def _investigation_summary(self, session: Session, row: Investigation, *, detail: bool) -> InvestigationView:
        brand = self._required(session, Brand, row.brand_id)
        entity_count = session.scalar(select(func.count()).select_from(InvestigationEntity).where(InvestigationEntity.investigation_id == row.id)) or 0
        evidence_count = session.scalar(select(func.count()).select_from(Observation).where(Observation.investigation_id == row.id)) or 0
        submission_rows = session.scalars(select(Submission).where(Submission.investigation_id == row.id).order_by(Submission.created_at, Submission.id)).all()
        decision_rows = session.scalars(select(Decision).where(Decision.investigation_id == row.id).order_by(Decision.created_at, Decision.id)).all()
        disposition = decision_rows[-1].value if decision_rows else "unreviewed"
        source = submission_rows[0].source if submission_rows else None
        assessment = assess(self._list_evidence_session(session, row.id))
        data: dict[str, Any] = dict(
            id=row.id, title=row.title, brand_id=brand.id, brand_name=brand.name,
            workflow=row.workflow, disposition=disposition, priority=assessment.priority,
            created_at=row.created_at, updated_at=row.updated_at, entity_count=entity_count,
            evidence_count=evidence_count, source=source, demo=row.demo,
        )
        if detail:
            note_rows = session.scalars(select(Note).where(Note.investigation_id == row.id).order_by(Note.created_at, Note.id)).all()
            artifact_rows = session.scalars(select(Artifact).where(Artifact.investigation_id == row.id).order_by(Artifact.created_at, Artifact.id)).all()
            job_rows = session.scalars(select(Job).where(Job.investigation_id == row.id).order_by(Job.created_at.desc())).all()
            data.update(
                submissions=[self._submission_view(item) for item in submission_rows],
                notes=[NoteView.model_validate(item) for item in note_rows],
                decisions=[DecisionView.model_validate(item) for item in decision_rows],
                attachments=[ArtifactView.model_validate(item) for item in artifact_rows],
                jobs=[self._job_view(item) for item in job_rows],
                assessment=assessment,
            )
        return InvestigationView(**data)

    def _list_evidence_session(self, session: Session, investigation_id: str) -> list[EvidenceView]:
        rows = session.execute(select(Observation, Entity).join(Entity, Entity.id == Observation.subject_id).where(Observation.investigation_id == investigation_id)).all()
        return [self._evidence_view(obs, entity) for obs, entity in rows]

    def get_investigation(self, investigation_id: str) -> InvestigationView:
        with self.sessions() as session:
            return self._investigation_summary(session, self._required(session, Investigation, investigation_id), detail=True)

    def list_investigations(self) -> list[InvestigationView]:
        with self.sessions() as session:
            rows = session.scalars(select(Investigation).order_by(Investigation.updated_at.desc(), Investigation.id)).all()
            return [self._investigation_summary(session, row, detail=False) for row in rows]

    @staticmethod
    def _validate_artifact(content: bytes, mime: str, *, brand: bool = False) -> None:
        if len(content) > 10 * 1024 * 1024:
            raise InvalidArtifact("attachment exceeds 10 MiB")
        valid = False
        if mime == "image/png":
            valid = content.startswith(b"\x89PNG\r\n\x1a\n")
        elif mime == "image/jpeg":
            valid = content.startswith(b"\xff\xd8\xff")
        elif mime == "text/plain" and not brand:
            try:
                content.decode("utf-8")
                valid = True
            except UnicodeDecodeError:
                valid = False
        if not valid:
            raise InvalidArtifact("unsupported attachment content")

    def _attach(self, content: bytes, mime: str, *, investigation_id: str | None = None, brand_id: str | None = None, submission_id: str | None = None) -> ArtifactView:
        self._validate_artifact(content, mime, brand=brand_id is not None)
        storage_name = f"{uuid.uuid4().hex}.bin"
        digest = hashlib.sha256(content).hexdigest()
        path = self.evidence_dir / storage_name
        path.write_bytes(content)
        try:
            with self.repo.transaction() as session:
                if investigation_id:
                    self._required(session, Investigation, investigation_id)
                if brand_id:
                    self._required(session, Brand, brand_id)
                if submission_id:
                    sub = self._required(session, Submission, submission_id)
                    if sub.investigation_id != investigation_id:
                        raise NotFoundError("submission not found")
                row = Artifact(investigation_id=investigation_id, brand_id=brand_id, submission_id=submission_id, sha256=digest, mime=mime, size_bytes=len(content), storage_name=storage_name)
                session.add(row)
                session.flush()
                return ArtifactView.model_validate(row)
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def attach_to_investigation(self, investigation_id: str, content: bytes, mime: str, submission_id: str | None = None) -> ArtifactView:
        return self._attach(content, mime, investigation_id=investigation_id, submission_id=submission_id)

    def attach_to_brand(self, brand_id: str, content: bytes, mime: str) -> ArtifactView:
        return self._attach(content, mime, brand_id=brand_id)

    def get_artifact(self, artifact_id: str, *, investigation_id: str | None = None, brand_id: str | None = None) -> tuple[ArtifactView, Path]:
        with self.sessions() as session:
            row = session.get(Artifact, artifact_id)
            if row is None or (investigation_id is not None and row.investigation_id != investigation_id) or (brand_id is not None and row.brand_id != brand_id):
                raise NotFoundError("attachment not found")
            return ArtifactView.model_validate(row), self.evidence_dir / row.storage_name

    @staticmethod
    def _job_view(row: Job) -> JobView:
        return JobView.model_validate(row)

    def list_jobs(self, investigation_id: str) -> list[JobView]:
        with self.sessions() as session:
            rows = session.scalars(select(Job).where(Job.investigation_id == investigation_id).order_by(Job.created_at.desc())).all()
            return [self._job_view(row) for row in rows]

    def save_analysis(
        self,
        investigation_id: str,
        output: dict[str, Any],
        *,
        recorded_demo: bool = False,
        snapshot_evidence_ids: list[str] | None = None,
    ) -> AnalysisView:
        current_ids = [item.id for item in self.list_evidence(investigation_id)]
        snapshot_ids = list(snapshot_evidence_ids) if snapshot_evidence_ids is not None else current_ids
        snapshot_id = hashlib.sha256(json.dumps(snapshot_ids, sort_keys=True).encode()).hexdigest()
        with self.repo.transaction() as session:
            self._required(session, Investigation, investigation_id)
            row = Analysis(
                investigation_id=investigation_id,
                output=output,
                model_id=output.get("model_id", "recorded-belgu-demo"),
                runtime_version=output.get("runtime_version", "recorded"),
                prompt_version=output.get("prompt_version", "belgu-demo-v1"),
                snapshot_id=snapshot_id,
                evidence_ids=snapshot_ids,
                recorded_demo=recorded_demo,
                metrics=output.get("metrics", {}),
            )
            session.add(row)
            session.flush()
            return self._analysis_view(row, current_ids)

    @staticmethod
    def _analysis_view(row: Analysis, current_ids: list[str]) -> AnalysisView:
        return AnalysisView(
            id=row.id, status=row.status, output=row.output, model_id=row.model_id,
            prompt_version=row.prompt_version, snapshot_id=row.snapshot_id,
            stale=set(row.evidence_ids) != set(current_ids), created_at=row.created_at,
            recorded_demo=row.recorded_demo, metrics=row.metrics,
        )

    def list_analyses(self, investigation_id: str) -> list[AnalysisView]:
        current_ids = [item.id for item in self.list_evidence(investigation_id)]
        with self.sessions() as session:
            rows = session.scalars(select(Analysis).where(Analysis.investigation_id == investigation_id).order_by(Analysis.created_at.desc())).all()
            return [self._analysis_view(row, current_ids) for row in rows]

    def list_groups(self, investigation_id: str, by: str, limit: int = 50, cursor: str | None = None) -> GroupPage:
        from belgu.application.groups import GroupService
        return GroupService(self).list_groups(investigation_id, by, limit, cursor)

    def list_entities(self, investigation_id: str, kind: str | None = None, group_key: str | None = None, limit: int = 50, cursor: str | None = None, *, q: str = '', has_capture: bool = False, shared: str | None = None, recent_hours: int | None = None, sort: str = 'name') -> EntityPage:
        from belgu.application.groups import GroupService
        return GroupService(self).list_entities(investigation_id, kind, group_key, limit, cursor, q=q, has_capture=has_capture, shared=shared, recent_hours=recent_hours, sort=sort)

    def graph(self, investigation_id: str, root_id: str | None = None, limit: int = 100, cursor: str | None = None) -> GraphView:
        from belgu.application.groups import GroupService
        return GroupService(self).graph(investigation_id, root_id, limit, cursor)
