from __future__ import annotations

import threading
import time
import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from belgu.domain.contracts import JobView, Limits
from belgu.persistence.models import Brand, CollectionRun, Investigation, Job, Submission, utcnow


TERMINAL = {"completed", "partial", "failed", "cancelled"}


class JobService:
    def __init__(self, service):
        self.service = service

    @staticmethod
    def _view(row: Job) -> JobView:
        return JobView.model_validate(row)

    def enqueue(self, investigation_id: str, kind: str, payload: dict[str, Any] | None = None) -> JobView:
        if kind not in {"collect", "expand", "analysis", "capture"}:
            raise ValueError("invalid job kind")
        payload = dict(payload or {})
        limits = dict(payload.pop("limits", {}) or {})
        defaults = Limits().__dict__
        normalized = {**defaults, **limits}
        caps = {"max_depth": 4, "max_entities": 5000, "max_requests": 1000, "max_seconds": 900, "provider_concurrency": 4}
        for key, maximum in caps.items():
            value = normalized.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
                raise ValueError(f"{key} must be between 1 and {maximum}")
        with self.service.repo.transaction() as session:
            self.service._required(session, Investigation, investigation_id)
            row = Job(investigation_id=investigation_id, kind=kind, payload=payload, limits=normalized, progress={"requests": 0, "entities": 0, "message": "Sırada"})
            session.add(row)
            session.flush()
            return self._view(row)

    def get(self, job_id: str) -> JobView:
        with self.service.sessions() as session:
            return self._view(self.service._required(session, Job, job_id))

    def claim(self, worker_id: str) -> JobView | None:
        with self.service.repo.transaction() as session:
            row = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id).limit(1))
            if row is None:
                return None
            row.status = "running"
            row.worker_id = worker_id
            row.lease_expires_at = utcnow() + timedelta(seconds=30)
            row.updated_at = utcnow()
            row.progress = {**row.progress, "message": "Çalışıyor"}
            session.flush()
            return self._view(row)

    def heartbeat(self, job_id: str, worker_id: str, progress: dict[str, Any] | None = None) -> JobView:
        with self.service.repo.transaction() as session:
            row = self.service._required(session, Job, job_id)
            if row.status != "running" or row.worker_id != worker_id:
                raise ValueError("job is not leased to this worker")
            row.lease_expires_at = utcnow() + timedelta(seconds=30)
            if progress is not None:
                row.progress = {**row.progress, **progress}
            row.updated_at = utcnow()
            session.flush()
            return self._view(row)

    def cancel(self, job_id: str) -> JobView:
        with self.service.repo.transaction() as session:
            row = self.service._required(session, Job, job_id)
            if row.status not in TERMINAL:
                row.cancel_requested = True
                if row.status == "queued":
                    row.status = "cancelled"
                    row.progress = {**row.progress, "message": "İptal edildi"}
                row.updated_at = utcnow()
            session.flush()
            return self._view(row)

    def recover_expired(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        with self.service.repo.transaction() as session:
            rows = session.scalars(select(Job).where(Job.status == "running", Job.lease_expires_at < now)).all()
            for row in rows:
                row.status = "queued"
                row.worker_id = None
                row.lease_expires_at = None
                row.progress = {**row.progress, "message": "Worker kesintisinden sonra yeniden sırada"}
            return len(rows)

    def finish(self, job_id: str, summary: dict[str, Any]) -> JobView:
        status = summary.get("status", "completed")
        if status not in TERMINAL:
            status = "completed"
        with self.service.repo.transaction() as session:
            row = self.service._required(session, Job, job_id)
            row.status = status
            row.truncated = bool(summary.get("truncated", False))
            row.error = summary.get("error")
            counts = summary.get("counts", {})
            provider_statuses = summary.get("providers")
            row.progress = {
                **row.progress,
                **counts,
                **({"providers": provider_statuses} if provider_statuses is not None else {}),
                "message": summary.get("message", {
                    "completed": "Tamamlandı", "partial": "Sınırda kısmi tamamlandı" if row.truncated else "Kısmi sonuçlarla tamamlandı",
                    "cancelled": "İptal edildi", "failed": "Başarısız",
                }.get(status, status)),
            }
            row.worker_id = None
            row.lease_expires_at = None
            row.updated_at = utcnow()
            session.flush()
            return self._view(row)


class Worker:
    """Single-process thread worker for the local POC."""

    def __init__(self, service, worker_id: str = "belgu-local-worker", *, network_enabled: bool = True, demo_mode: bool = False):
        self.service = service
        self.jobs = JobService(service)
        self.worker_id = worker_id
        self.network_enabled = network_enabled
        self.demo_mode = demo_mode
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.heartbeat_interval = 10.0
        self.recovery_interval = 5.0
        from belgu.application.watches import WatchService
        self.watches = WatchService(service)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.jobs.recover_expired()
        self.thread = threading.Thread(target=self.run_forever, name="belgu-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def run_forever(self) -> None:
        last_recovery = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now - last_recovery >= self.recovery_interval:
                self.jobs.recover_expired()
                if self.network_enabled:
                    try:
                        self.watches.reconcile()
                        self.watches.schedule_due()
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception("Watch scheduler will retry")
                last_recovery = now
            job = self.jobs.claim(self.worker_id)
            if job is None:
                self.stop_event.wait(0.05)
                continue
            self._execute(job)

    def _execute(self, job: JobView) -> None:
        try:
            if job.kind == "analysis":
                summary = self._analysis(job)
            elif job.kind == "capture":
                summary = self._capture(job)
            else:
                summary = self._discovery(job)
            self.jobs.finish(job.id, summary)
        except Exception as exc:
            self.jobs.finish(job.id, {"status": "failed", "error": str(exc), "message": "İş tamamlanamadı"})
        if self.network_enabled:
            try:
                self.watches.complete(job.id)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Watch completion will retry during reconciliation")

    def _cancelled(self, job_id: str) -> bool:
        return self.stop_event.is_set() or self.jobs.get(job_id).cancel_requested

    def _analysis(self, job: JobView) -> dict[str, Any]:
        if self.demo_mode:
            recorded = [item for item in self.service.list_analyses(job.investigation_id) if item.recorded_demo]
            if not recorded:
                raise RuntimeError("recorded demo analysis is not available for this investigation")
            return {
                "status": "completed",
                "counts": {"entities": len(self.service.list_evidence(job.investigation_id)), "recorded_demo": True},
                "message": "Kayıtlı kurmaca demo analizi hazır",
            }
        from belgu.analysis.service import analyze_evidence, get_model_status

        evidence = [item.model_dump(mode="json") for item in self.service.list_evidence(job.investigation_id)]
        snapshot_evidence_ids = [item["id"] for item in evidence]
        with self.service.sessions() as session:
            row = session.get(Job, job.id)
            model_id = row.payload.get("model_id") if row else None
            investigation = self.service._required(session, Investigation, job.investigation_id)
            brand = self.service._required(session, Brand, investigation.brand_id)
            submissions = session.scalars(
                select(Submission)
                .where(Submission.investigation_id == job.investigation_id)
                .order_by(Submission.created_at, Submission.id)
            ).all()
            context = {
                "investigation_id": job.investigation_id,
                "model_id": model_id,
                "investigation_title": investigation.title,
                "brand": {"name": brand.name, "official_domains": list(brand.official_domains)},
                "targets": [
                    {"kind": item.kind, "canonical_value": item.canonical_value, "hostname": item.hostname}
                    for item in submissions
                ],
                "analysis_time": utcnow().isoformat(),
            }
        connection = self.service.integrations.configured_connection()
        status = get_model_status(connection) if connection is not None else get_model_status()
        if status.get("status") != "ready":
            raise RuntimeError(f"model unavailable: {status.get('message', 'model is not ready')}")
        if model_id and model_id != status.get("model_id"):
            raise RuntimeError(f"selected model {model_id!r} is not the configured model")
        self.jobs.heartbeat(job.id, self.worker_id, {"entities": len(evidence), "model_id": status.get("model_id"), "message": "Kanıt anlık görüntüsü analiz ediliyor"})
        if self._cancelled(job.id):
            return {"status": "cancelled", "counts": {"entities": len(evidence)}}
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="belgu-analysis")
        future = executor.submit(analyze_evidence, evidence, context, **({'connection': connection} if connection is not None else {}))
        try:
            while True:
                try:
                    output = future.result(timeout=self.heartbeat_interval)
                    break
                except FutureTimeoutError:
                    message = "Model analizi sürüyor"
                    if self._cancelled(job.id):
                        message = "Model çağrısının bitmesi bekleniyor; sonuç kaydedilmeyecek"
                    self.jobs.heartbeat(job.id, self.worker_id, {"message": message})
        finally:
            executor.shutdown(wait=True)
        if self._cancelled(job.id):
            return {"status": "cancelled", "counts": {"entities": len(evidence)}}
        self.service.save_analysis(job.investigation_id, output, snapshot_evidence_ids=snapshot_evidence_ids)
        return {"status": "completed", "counts": {"entities": len(evidence)}}

    def _discovery(self, job: JobView) -> dict[str, Any]:
        if not self.network_enabled:
            raise RuntimeError("demo mode network is disabled; use the recorded fixture")
        from belgu.core.discovery import discover
        from belgu.domain.contracts import Limits

        investigation = self.service.get_investigation(job.investigation_id)
        roots = [submission.target.raw_value for submission in investigation.submissions]
        entity_id = None
        with self.service.sessions() as session:
            row = session.get(Job, job.id)
            entity_id = row.payload.get("entity_id") if row else None
        if entity_id:
            roots = [self.service.get_entity(job.investigation_id, entity_id).value]
        if not roots:
            raise ValueError("discovery requires a submitted target")
        limits = Limits(**job.limits)
        provider_settings = self.service.integrations.snapshot()['sources']
        with self.service.sessions() as session:
            existing_run = session.get(CollectionRun, job.id)
            collected_ids = list(existing_run.evidence_ids) if existing_run else []
        try:
            counts = {"requests": 0, "entities": 0, "new_entities": 0, "observations": 0, "provider_count": 0}
            providers: list[dict[str, Any]] = []
            truncated = False
            final_status = "completed"
            started_at = time.monotonic()
            for root_index, root in enumerate(roots):
                if self._cancelled(job.id):
                    return {"status": "cancelled", "counts": counts, "providers": providers, "truncated": truncated}

                remaining_requests = limits.max_requests - counts["requests"]
                remaining_entities = limits.max_entities - counts["entities"]
                remaining_seconds = limits.max_seconds - (time.monotonic() - started_at)
                if remaining_requests <= 0 or remaining_entities <= 0 or remaining_seconds <= 0:
                    truncated = True
                    final_status = "partial"
                    break
                root_limits = Limits(
                    max_depth=limits.max_depth,
                    max_entities=remaining_entities,
                    max_requests=remaining_requests,
                    max_seconds=max(1, math.ceil(remaining_seconds)),
                    provider_concurrency=limits.provider_concurrency,
                )
                base_requests = counts["requests"]
                base_entities = counts["entities"]

                def progress(value: dict) -> None:
                    cumulative = dict(value)
                    if "requests" in value:
                        cumulative["requests"] = base_requests + value["requests"]
                    if "entities" in value:
                        cumulative["entities"] = base_entities + value["entities"]
                    self.jobs.heartbeat(job.id, self.worker_id, cumulative)

                result = discover(root, limits=root_limits, cancelled=lambda: self._cancelled(job.id), progress=progress,
                                  provider_settings=provider_settings)
                for provider_result in result.results:
                    saved = self.service.record_result(job.investigation_id, provider_result, job_id=job.id)
                    collected_ids.extend(saved.evidence_ids)
                    providers.append({
                        "provider": provider_result.provider,
                        "status": provider_result.status,
                        "truncated": provider_result.truncated,
                        "error_code": provider_result.error_code,
                        "observations": len(provider_result.observations),
                    })
                for key in ("requests", "entities", "new_entities", "observations"):
                    counts[key] += int(result.counts.get(key, 0) or 0)
                counts["provider_count"] += int(result.counts.get("providers", len(result.results)) or 0)
                truncated = truncated or result.truncated
                if result.status in {"partial", "cancelled"}:
                    final_status = result.status
                budget_spent = counts["requests"] >= limits.max_requests or counts["entities"] >= limits.max_entities or (time.monotonic() - started_at) >= limits.max_seconds
                if budget_spent and root_index + 1 < len(roots):
                    truncated = True
                    final_status = "partial"
                    break
            return {"status": final_status, "counts": counts, "providers": providers, "truncated": truncated}
        finally:
            from belgu.application.insights import record_run
            record_run(self.service, job.id, collected_ids)


    def _capture(self, job):
        if not self.network_enabled:
            raise RuntimeError("Demo mode cannot capture live pages")
        from belgu.application.capture import capture_target
        with self.service.sessions() as session:
            payload=self.service._required(session, Job, job.id).payload
            url=payload['url']
            profile=payload.get('profile','desktop')
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="belgu-capture") as executor:
            future=executor.submit(capture_target,self.service,job.investigation_id,url,profile=profile,
                cancelled=lambda:self._cancelled(job.id),
                progress=lambda value:self.jobs.heartbeat(job.id,self.worker_id,value))
            while True:
                try:return future.result(timeout=self.heartbeat_interval)
                except FutureTimeoutError:
                    self.jobs.heartbeat(job.id,self.worker_id,{"message":"Görsel kanıt alınıyor"})
