from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel,Field
from sqlalchemy import select
from belgu.application.service import NotFoundError
from belgu.application.jobs import JobService
from belgu.application.watches import WatchService
from belgu.domain.contracts import JobView,ArtifactView
from belgu.domain.targets import parse_target
from belgu.persistence.models import Artifact,Brand


class CaptureCreate(BaseModel):
    url:str=Field(min_length=1,max_length=4096)
    profile:Literal["desktop","mobile"]="desktop"

class WatchCreate(BaseModel):
    entity_id:str|None=None
    interval_minutes:int=Field(default=60,ge=5,le=10080)
    enabled:bool=True

class WatchPatch(BaseModel):
    interval_minutes:int|None=Field(default=None,ge=5,le=10080)
    enabled:bool|None=None

class StoryCreate(BaseModel):
    evidence_ids:list[str]=Field(default_factory=list,max_length=12)
    redact:bool=True
    preview_id:str|None=None


def router(service,settings):
    r=APIRouter();jobs=JobService(service);watches=WatchService(service)
    def live():
        if settings.mode=='demo':raise HTTPException(409,'Demo kayıtlı verilerle çalışır; canlı çalışma alanını açın.')
    def references(brand_id):
        with service.sessions() as session:
            service._required(session,Brand,brand_id)
            rows=session.scalars(select(Artifact).where(Artifact.brand_id==brand_id,Artifact.mime.in_(["image/png","image/jpeg"])).order_by(Artifact.created_at.desc())).all()
            return [{**ArtifactView.model_validate(a).model_dump(mode='json'),'image_url':f'/api/brands/{brand_id}/attachments/{a.id}'} for a in rows]

    @r.get('/api/brands/{brand_id}/attachments')
    def brand_references(brand_id:str):
        items=references(brand_id);return {'items':items,'total_unique':len(items),'next_cursor':None}

    @r.get('/api/investigations/{investigation_id}/evidence')
    def evidence_list(investigation_id:str,limit:int=Query(25,ge=1,le=100),cursor:str|None=None):
        service.get_investigation(investigation_id)
        items=sorted(service.list_evidence(investigation_id),key=lambda e:(e.retrieved_at,e.id),reverse=True)
        start=0
        if cursor:
            positions=[i for i,e in enumerate(items) if e.id==cursor]
            if not positions:raise ValueError('Kanıt sayfa işareti bulunamadı.')
            start=positions[0]+1
        selected=items[start:start+limit]
        return {'items':selected,'total_unique':len(items),'next_cursor':selected[-1].id if selected and start+limit<len(items) else None}

    @r.get('/api/investigations/{investigation_id}/captures')
    def captures(investigation_id:str):
        from belgu.application.capture import capture_status
        inv=service.get_investigation(investigation_id)
        from belgu.core.browser_capture import observation_profile
        items=[]; failures=[]
        for e in sorted(service.list_evidence(investigation_id), key=lambda e:(e.retrieved_at,e.id), reverse=True):
            if e.kind == "page_capture_failed":
                failures.append({**e.payload, **observation_profile(e.payload), "evidence_id":e.id, "retrieved_at":e.retrieved_at})
            if e.kind!='page_browser' or not e.payload.get('artifact_id'):continue
            p=e.payload
            items.append({**p,**observation_profile(p),'retrieved_at':e.retrieved_at,'id':e.id,'evidence_id':e.id,'observed_at':e.observed_at,'image_url':f'/api/investigations/{investigation_id}/attachments/{p["artifact_id"]}'})

        capabilities=capture_status()
        if settings.mode=='demo':capabilities={**capabilities,'status':'recorded_demo','message':'Kayıtlı görsel kanıtlar; canlı görüntü toplama demo içinde kapalı.'}
        return {'items':items,'failures':failures,'references':references(inv.brand_id),'capabilities':capabilities}

    @r.post('/api/investigations/{investigation_id}/captures',status_code=202,response_model=JobView)
    def create_capture(investigation_id:str,body:CaptureCreate):
        live();service.get_investigation(investigation_id)
        target=parse_target(body.url)
        if target.kind not in ('domain','url'):raise ValueError('Görsel kanıt için alan adı veya HTTP(S) URL gerekli.')
        url=target.canonical_value if target.kind=='url' else 'https://'+target.canonical_value+'/'
        return jobs.enqueue(investigation_id,'capture',{'url':url,'profile':body.profile,'limits':{'max_requests':40,'max_seconds':60}})

    @r.get('/api/investigations/{investigation_id}/visual-similarity')
    def visual_similarity(investigation_id:str, reference_id:str=Query(min_length=1)):
        from belgu.application.visual_similarity import rank_captures
        return rank_captures(service, investigation_id, reference_id)

    @r.get('/api/investigations/{investigation_id}/candidates')
    def candidates(investigation_id:str,limit:int=Query(30,ge=1,le=100),cursor:str|None=None):
        from belgu.application.insights import rank_candidates
        return rank_candidates(service,investigation_id,limit,cursor)

    @r.get('/api/investigations/{investigation_id}/runs')
    def runs(investigation_id:str):
        from belgu.application.insights import list_runs
        return list_runs(service,investigation_id)

    @r.get('/api/investigations/{investigation_id}/changes')
    def changes(investigation_id:str,before:str|None=None,after:str|None=None):
        from belgu.application.insights import compare_runs
        return compare_runs(service,investigation_id,before,after)

    @r.get('/api/investigations/{investigation_id}/grounding')
    def claim_grounding(investigation_id:str,analysis_id:str|None=None):
        from belgu.application.grounding import grounding
        service.get_investigation(investigation_id)
        return grounding(service,investigation_id,analysis_id)

    @r.get('/api/investigations/{investigation_id}/watches')
    def watch_list(investigation_id:str):return watches.list(investigation_id)

    @r.post('/api/investigations/{investigation_id}/watches',status_code=201)
    def create_watch(investigation_id:str,body:WatchCreate):
        live();return watches.create(investigation_id,**body.model_dump())

    @r.patch('/api/investigations/{investigation_id}/watches/{watch_id}')
    def patch_watch(investigation_id:str,watch_id:str,body:WatchPatch):
        live();return watches.patch(investigation_id,watch_id,**body.model_dump(exclude_unset=True))

    @r.post('/api/investigations/{investigation_id}/watches/{watch_id}/run',status_code=202,response_model=JobView)
    def run_watch(investigation_id:str,watch_id:str):
        live();return watches.run_now(investigation_id,watch_id)

    @r.post('/api/investigations/{investigation_id}/alerts/{alert_id}/read')
    def read_alert(investigation_id:str,alert_id:str):return watches.read_alert(investigation_id,alert_id)

    @r.post('/api/investigations/{investigation_id}/story/preview')
    def story_preview(investigation_id:str,body:StoryCreate):
        from belgu.reporting.story import save_story_preview
        return save_story_preview(service,investigation_id,body.evidence_ids,body.redact)

    @r.post('/api/investigations/{investigation_id}/story/export')
    def story_export(investigation_id:str,body:StoryCreate):
        from belgu.reporting.story import export_story
        return Response(export_story(service,investigation_id,body.evidence_ids,body.redact,body.preview_id),media_type='text/html; charset=utf-8',headers={'Content-Disposition':'attachment; filename="belgu-inceleme-hikayesi.html"'})
    return r
