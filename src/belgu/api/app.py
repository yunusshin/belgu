from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from belgu.application.jobs import JobService, Worker
from belgu.application.service import BelguService, InvalidArtifact, NotFoundError
from belgu.domain.contracts import (
    AnalysisPage,
    ArtifactView,
    BrandPage,
    BrandView,
    DecisionView,
    EntityPage,
    EvidenceView,
    GraphView,
    GroupPage,
    InvestigationPage,
    InvestigationView,
    JobView,
    ModelPage,
    NoteView,
    SubmissionView,
)
from belgu.reporting.export import export_report
from belgu.settings import Settings


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    official_domains: list[str] = Field(default_factory=list, max_length=100)


class InvestigationCreate(BaseModel):
    brand_id: str
    title: str = Field(min_length=1, max_length=300)


class InvestigationPatch(BaseModel):
    workflow: Literal["open", "closed"]


class SubmissionCreate(BaseModel):
    value: str = Field(min_length=1, max_length=4096)
    source: Literal["customer_report", "analyst_discovery", "automated_discovery"]
    note: str = Field(default="", max_length=10000)


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class DecisionCreate(BaseModel):
    value: Literal["unreviewed", "confirmed_phishing", "benign", "needs_review"]
    note: str = Field(default="", max_length=10000)


class JobCreate(BaseModel):
    kind: Literal["collect", "expand"]
    entity_id: str | None = None
    limits: dict | None = None


class AnalysisCreate(BaseModel):
    model_id: str | None = None


def _error(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "retryable": retryable}}, status_code=status)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.bind_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Belgü v1 only serves on loopback")
    service = BelguService.open(settings.db_url, settings.evidence_dir)
    jobs = JobService(service)
    worker = Worker(service, network_enabled=settings.mode != "demo", demo_mode=settings.mode == "demo")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.start_worker:
            worker.start()
        yield
        worker.stop()
        service.close()

    app = FastAPI(title="Belgü", version="0.5.0", lifespan=lifespan)
    app.state.service = service
    app.state.worker = worker
    app.state.settings = settings

    def model_status():
        if settings.mode == "demo":
            return {
                "status": "recorded_demo",
                "model_id": "recorded-belgu-demo",
                "endpoint": None,
                "text_supported": True,
                "vision_supported": False,
                "message": "Kurgusal kayıtlı analiz; canlı model çağrısı yapılmaz.",
                "recorded_demo": True,
            }
        try:
            from belgu.analysis.service import get_model_status
            connection = service.integrations.configured_connection()
            return get_model_status(connection) if connection is not None else get_model_status()
        except Exception as exc:
            return {"status": "unavailable", "message": str(exc), "model_id": None, "endpoint": None, "text_supported": False, "vision_supported": False}

    @app.exception_handler(NotFoundError)
    async def not_found(_request: Request, exc: NotFoundError):
        return _error(404, "not_found", str(exc))

    @app.exception_handler(InvalidArtifact)
    async def bad_artifact(_request: Request, exc: InvalidArtifact):
        status = 413 if "10 MiB" in str(exc) else 415
        return _error(status, "attachment_rejected", str(exc))

    @app.exception_handler(ValueError)
    async def bad_value(_request: Request, exc: ValueError):
        return _error(422, "invalid_request", str(exc))

    @app.exception_handler(RequestValidationError)
    async def bad_request(_request: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "; ".join(error["msg"] for error in exc.errors()))

    @app.get("/api/session")
    def local_session():
        return {"mode": "local", "csrf_token": None, "authentication": "disabled"}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": settings.mode, "worker": "running" if worker.thread and worker.thread.is_alive() else "stopped", "model": model_status()}

    @app.get("/api/models", response_model=ModelPage)
    def models():
        model = model_status()
        return {"items": [model], "status": model["status"]}

    @app.get("/api/brands", response_model=BrandPage)
    def list_brands():
        items = service.list_brands()
        return {"items": items, "next_cursor": None, "total_unique": len(items)}

    @app.post("/api/brands", status_code=201, response_model=BrandView)
    def create_brand(body: BrandCreate):
        return service.create_brand(body.name, body.official_domains)

    @app.post("/api/brands/{brand_id}/attachments", status_code=201, response_model=ArtifactView)
    async def attach_brand(brand_id: str, file: UploadFile = File(...)):
        return service.attach_to_brand(brand_id, await file.read(10 * 1024 * 1024 + 1), file.content_type or "")

    @app.get("/api/brands/{brand_id}/attachments/{artifact_id}")
    def brand_attachment(brand_id: str, artifact_id: str):
        item, path = service.get_artifact(artifact_id, brand_id=brand_id)
        return FileResponse(path, media_type=item.mime, headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/api/investigations", response_model=InvestigationPage)
    def list_investigations():
        items = service.list_investigations()
        return {"items": items, "next_cursor": None, "total_unique": len(items)}

    @app.post("/api/investigations", status_code=201, response_model=InvestigationView)
    def create_investigation(body: InvestigationCreate):
        return service.create_investigation(body.brand_id, body.title)

    @app.get("/api/investigations/{investigation_id}", response_model=InvestigationView)
    def get_investigation(investigation_id: str):
        return service.get_investigation(investigation_id)

    @app.patch("/api/investigations/{investigation_id}", response_model=InvestigationView)
    def patch_investigation(investigation_id: str, body: InvestigationPatch):
        return service.set_workflow(investigation_id, body.workflow)

    @app.post("/api/investigations/{investigation_id}/submissions", status_code=201, response_model=SubmissionView)
    def add_submission(investigation_id: str, body: SubmissionCreate):
        return service.add_submission(investigation_id, body.value, body.source, body.note)

    @app.post("/api/investigations/{investigation_id}/notes", status_code=201, response_model=NoteView)
    def add_note(investigation_id: str, body: NoteCreate):
        return service.add_note(investigation_id, body.text)

    @app.post("/api/investigations/{investigation_id}/decisions", status_code=201, response_model=DecisionView)
    def add_decision(investigation_id: str, body: DecisionCreate):
        return service.set_disposition(investigation_id, body.value, body.note)

    @app.post("/api/investigations/{investigation_id}/attachments", status_code=201, response_model=ArtifactView)
    async def attach_investigation(investigation_id: str, file: UploadFile = File(...), submission_id: str | None = Form(default=None)):
        return service.attach_to_investigation(investigation_id, await file.read(10 * 1024 * 1024 + 1), file.content_type or "", submission_id)

    @app.get("/api/investigations/{investigation_id}/attachments/{artifact_id}")
    def investigation_attachment(investigation_id: str, artifact_id: str):
        item, path = service.get_artifact(artifact_id, investigation_id=investigation_id)
        headers = {"X-Content-Type-Options": "nosniff"}
        if item.mime == "text/plain":
            headers["Content-Disposition"] = f'attachment; filename="{item.id}.txt"'
        return FileResponse(path, media_type=item.mime, headers=headers)

    @app.post("/api/investigations/{investigation_id}/jobs", status_code=202, response_model=JobView)
    def create_job(investigation_id: str, body: JobCreate):
        return jobs.enqueue(investigation_id, body.kind, {"entity_id": body.entity_id, "limits": body.limits or {}})

    @app.get("/api/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: str):
        return jobs.get(job_id)

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobView)
    def cancel_job(job_id: str):
        return jobs.cancel(job_id)

    @app.get("/api/investigations/{investigation_id}/groups", response_model=GroupPage)
    def groups(investigation_id: str, by: str = "observed_ip", limit: int = Query(50, ge=1, le=50), cursor: str | None = None):
        return service.list_groups(investigation_id, by, limit, cursor)

    @app.get("/api/investigations/{investigation_id}/entities", response_model=EntityPage)
    def entities(investigation_id: str, kind: str | None = None, group_key: str | None = None, limit: int = Query(50, ge=1, le=100), cursor: str | None = None, q: str = Query('', max_length=500), has_capture: bool = False, shared: Literal['javascript','certificate'] | None = None, recent_hours: int | None = Query(None, ge=1, le=8760), sort: Literal['name','latest','priority'] = 'name'):
        return service.list_entities(investigation_id, kind, group_key, limit, cursor, q=q, has_capture=has_capture, shared=shared, recent_hours=recent_hours, sort=sort)

    @app.get("/api/investigations/{investigation_id}/graph", response_model=GraphView)
    def graph(investigation_id: str, root_id: str | None = None, limit: int = Query(100, ge=1, le=100), cursor: str | None = None):
        return service.graph(investigation_id, root_id, limit, cursor)

    @app.get("/api/investigations/{investigation_id}/evidence/{evidence_id}", response_model=EvidenceView)
    def evidence(investigation_id: str, evidence_id: str):
        return service.get_evidence(investigation_id, evidence_id)

    @app.post("/api/investigations/{investigation_id}/analyses", status_code=202, response_model=JobView)
    def create_analysis(investigation_id: str, body: AnalysisCreate):
        return jobs.enqueue(investigation_id, "analysis", {"model_id": body.model_id})

    @app.get("/api/investigations/{investigation_id}/analyses", response_model=AnalysisPage)
    def analyses(investigation_id: str):
        items = service.list_analyses(investigation_id)
        return AnalysisPage(items=items, total_unique=len(items))

    @app.get("/api/investigations/{investigation_id}/report")
    def report(investigation_id: str, format: Literal["markdown", "json"] = "markdown", redact: bool = True):
        content = export_report(service, investigation_id, format, redact)
        mime = "application/json" if format == "json" else "text/markdown; charset=utf-8"
        return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="belgu-{investigation_id}.{"json" if format == "json" else "md"}"'})

    from belgu.api.routes.workbench import router as workbench_router
    app.include_router(workbench_router(service, settings))
    from belgu.api.routes.intelligence import router as intelligence_router
    from belgu.api.routes.replay import router as replay_router
    from belgu.api.routes.settings import router as settings_router
    app.include_router(intelligence_router(service, settings))
    app.include_router(replay_router(service, settings))
    app.include_router(settings_router(service, settings))

    web_dist = settings.web_dist.resolve()
    if web_dist.is_dir() and (web_dist / "index.html").is_file():
        assets = web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            candidate = (web_dist / path).resolve()
            if path and candidate.is_file() and web_dist in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(web_dist / "index.html")

    return app
