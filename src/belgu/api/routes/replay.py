from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from belgu.reporting.replay import export_replay, save_replay_preview


class ReplayPreviewRequest(BaseModel):
    redact: bool = True


class ReplayExportRequest(BaseModel):
    preview_id: str
    redact: bool = True


def router(service, settings):
    replay_router = APIRouter()

    @replay_router.post("/api/investigations/{investigation_id}/replay/preview")
    def preview(investigation_id: str, body: ReplayPreviewRequest):
        return save_replay_preview(service, investigation_id, redact=body.redact)

    @replay_router.post("/api/investigations/{investigation_id}/replay/export")
    def export(investigation_id: str, body: ReplayExportRequest):
        html = export_replay(service, investigation_id, body.preview_id, redact=body.redact)
        return Response(
            html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="belgu-kayitli-inceleme.html"'},
        )

    return replay_router
