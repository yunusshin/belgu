from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from belgu.analysis.assistant import AssistantError, ask_assistant, list_assistant_turns
from belgu.application.memory import cross_investigation_memory


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)

    @field_validator('message')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Soru boş olamaz.')
        return value.strip()


def router(service, settings):
    r = APIRouter(prefix='/api/investigations/{investigation_id}', tags=['intelligence'])

    @r.get('/memory')
    def memory(investigation_id: str, limit: int = Query(20, ge=1, le=100), cursor: str | None = None):
        return cross_investigation_memory(service, investigation_id, limit=limit, cursor=cursor)

    @r.get('/assistant')
    def history(investigation_id: str, limit: int = Query(50, ge=1, le=100), before: str | None = None):
        return list_assistant_turns(service, investigation_id, limit=limit, before=before)

    @r.post('/assistant', status_code=201)
    def ask(investigation_id: str, body: AssistantRequest):
        try:
            return ask_assistant(service, investigation_id, body.message, body.evidence_ids,
                                 recorded_demo=settings.mode == 'demo')
        except AssistantError as exc:
            return JSONResponse(status_code=503, content={'error': {'code': exc.code, 'message': str(exc), 'retryable': exc.retryable}})
        except ValueError as exc:
            return JSONResponse(status_code=422, content={'error': {'code': 'invalid_assistant_request', 'message': str(exc), 'retryable': False}})
    return r
