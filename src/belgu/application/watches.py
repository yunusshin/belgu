"""Durable, opt-in local watch scheduling and change-only notifications."""
from datetime import timedelta, timezone
import json
from sqlalchemy import select
from belgu.application.service import NotFoundError
from belgu.domain.contracts import JobView
from belgu.persistence.models import Investigation, Job, Watch, WatchAlert, utcnow

LIMITS = {'max_depth': 1, 'max_entities': 100, 'max_requests': 30, 'max_seconds': 60, 'provider_concurrency': 4}


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class WatchService:
    def __init__(self, service):
        self.service = service

    def _view(self, row):
        target = 'Gönderilen hedefler'
        if row.entity_id:
            target = self.service.get_entity(row.investigation_id, row.entity_id).value
        return {k: getattr(row,k) for k in ('id','entity_id','enabled','interval_minutes','next_run_at','last_job_id','last_error')} | {'target':target}

    def _required(self, session, investigation_id, watch_id):
        row = self.service._required(session, Watch, watch_id)
        if row.investigation_id != investigation_id:
            raise NotFoundError('watch not found')
        return row

    @staticmethod
    def _interval(value):
        if type(value) is not int or not 5 <= value <= 10080:
            raise ValueError('İzleme aralığı 5 ile 10080 dakika arasında olmalı.')
        return value

    def list(self, investigation_id):
        self.service.get_investigation(investigation_id)
        with self.service.sessions() as session:
            rows=session.scalars(select(Watch).where(Watch.investigation_id==investigation_id).order_by(Watch.created_at.desc())).all()
            alerts=session.scalars(select(WatchAlert).where(WatchAlert.investigation_id==investigation_id).order_by(WatchAlert.created_at.desc()).limit(100)).all()
            return {'items':[self._view(r) for r in rows], 'alerts':[{k:getattr(a,k) for k in ('id','kind','message','job_id','read','created_at')} for a in alerts]}

    def create(self, investigation_id, entity_id=None, interval_minutes=60, enabled=True):
        self._interval(interval_minutes)
        inv=self.service.get_investigation(investigation_id)
        if entity_id:
            entity=self.service.get_entity(investigation_id,entity_id)
            if entity.kind not in ('domain','url','ip'):
                raise ValueError('Bu varlık izlenemez.')
        elif not inv.submissions:
            raise ValueError('İzlemek için bir hedef ekleyin.')
        with self.service.repo.transaction() as session:
            existing=session.scalar(select(Watch).where(Watch.investigation_id==investigation_id,Watch.entity_id==entity_id))
            if existing:
                existing.interval_minutes=interval_minutes;existing.enabled=enabled
                existing.next_run_at=utcnow()+timedelta(minutes=interval_minutes)
                row=existing
            else:
                row=Watch(investigation_id=investigation_id,entity_id=entity_id,interval_minutes=interval_minutes,enabled=enabled,next_run_at=utcnow()+timedelta(minutes=interval_minutes))
                session.add(row)
            session.flush()
            return self._view(row)

    def patch(self, investigation_id, watch_id, *, enabled=None, interval_minutes=None):
        if interval_minutes is not None:self._interval(interval_minutes)
        with self.service.repo.transaction() as session:
            row=self._required(session,investigation_id,watch_id)
            if enabled is not None:row.enabled=enabled
            if interval_minutes is not None:row.interval_minutes=interval_minutes
            if enabled is True or interval_minutes is not None:row.next_run_at=utcnow()+timedelta(minutes=row.interval_minutes)
            session.flush()
            return self._view(row)

    def _enqueue(self, session, row, now):
        active=session.scalar(select(Job).where(Job.investigation_id==row.investigation_id,Job.kind.in_(['collect','expand','capture']),Job.status.in_(['queued','running'])).limit(1))
        if active:return None
        inv=self.service._required(session,Investigation,row.investigation_id)
        if inv.workflow=='closed' or inv.demo:return None
        job=Job(investigation_id=row.investigation_id,kind='expand' if row.entity_id else 'collect',payload={'entity_id':row.entity_id,'watch_id':row.id},limits=dict(LIMITS),progress={'requests':0,'entities':0,'message':'İzleme kontrolü sırada'})
        session.add(job);session.flush()
        row.last_job_id=job.id;row.next_run_at=now+timedelta(minutes=row.interval_minutes)
        return JobView.model_validate(job)

    @staticmethod
    def _lock(session):
        # Manual runs and the scheduler share SQLite; serialize due-check/enqueue.
        if session.bind.dialect.name=='sqlite':session.connection().exec_driver_sql('BEGIN IMMEDIATE')

    def run_now(self, investigation_id, watch_id):
        with self.service.repo.transaction() as session:
            self._lock(session)
            row=self._required(session,investigation_id,watch_id)
            job=self._enqueue(session,row,utcnow())
            if job is None:raise ValueError('Bu incelemede süren bir keşif var veya inceleme kapalı.')
            return job

    def schedule_due(self, now=None):
        now=now or utcnow();count=0
        with self.service.repo.transaction() as session:
            self._lock(session)
            rows=session.scalars(select(Watch).join(Investigation,Investigation.id==Watch.investigation_id).where(Watch.enabled.is_(True),Watch.next_run_at<=now,Investigation.workflow=='open',Investigation.demo.is_(False)).order_by(Watch.next_run_at).limit(20)).all()
            for row in rows:
                count+=int(self._enqueue(session,row,now) is not None)
        return count

    def _changes(self, investigation_id, before, after):
        from belgu.application.insights import watch_state
        current=watch_state(self.service,investigation_id,after)
        previous=json.loads(before) if before else {}
        merged=dict(previous);counts={'new':0,'changed':0}
        with self.service.sessions() as session:
            job=self.service._required(session,Job,after)
            incomplete=job.status!='completed' or job.truncated
        for key,value in current.items():
            old=previous.get(key)
            if old is None:counts['new']+=1
            else:
                old_values={json.dumps(v,sort_keys=True,ensure_ascii=False) for v in json.loads(old)}
                new_values={json.dumps(v,sort_keys=True,ensure_ascii=False) for v in json.loads(value)}
                if new_values-old_values:counts['changed']+=1
                if incomplete and json.loads(key)[2].startswith('dns_'):
                    value=json.dumps([json.loads(v) for v in sorted(old_values|new_values)],ensure_ascii=False,separators=(',',':'))
            merged[key]=value
        return {'counts':counts,'state':json.dumps(merged,ensure_ascii=False,sort_keys=True) if merged else before}

    def complete(self, job_id):
        # Called only after terminal status is persisted, also reconciled on restart.
        with self.service.sessions() as session:
            job=session.get(Job,job_id)
            if job is None or job.status not in ('completed','partial','failed','cancelled'):return
            watch_id=job.payload.get('watch_id')
            watch=session.get(Watch,watch_id) if watch_id else None
            if watch is None or watch.last_completed_job_id==job.id:return
            before=watch.last_signature
            previous_error=watch.last_error
            errors=sorted({str(p.get('provider','Kaynak'))+': '+str(p.get('error_code') or p.get('status')) for p in job.progress.get('providers',[]) if (p.get('status') in ('error','rate_limited','unavailable') or p.get('status')=='partial' and p.get('error_code')) and p.get('error_code') not in ('feed_not_configured','feed_disabled','collection_limit')})
            error=('Kontrol: '+job.error.replace('\n',' ')) if job.error else ('\n'.join(errors) if errors else None)
            if job.status=='failed' and not error:error='Kontrol tamamlanamadı'
            case_id=job.investigation_id
            counts={};state=before
        if job.status in ('completed','partial'):
            change=self._changes(case_id,before,job_id)
            state=change.get('state',before or '{}')
            if before:counts=change.get('counts',{})
        with self.service.repo.transaction() as session:
            self._lock(session)
            row=session.get(Watch,watch_id)
            if row is None or row.last_completed_job_id==job_id:return
            def alert(kind,message):
                session.add(WatchAlert(watch_id=row.id,investigation_id=case_id,kind=kind,message=message,job_id=job_id))
            current_errors=set(error.splitlines()) if error else set()
            previous_errors=set(previous_error.splitlines()) if previous_error else set()
            added_errors=current_errors-previous_errors
            if added_errors:alert('failure','İzleme kaynağında sorun: '+'; '.join(sorted(added_errors))[:250])
            elif previous_errors-current_errors and job.status!='cancelled':alert('recovered','İzleme yeniden veri alabildi.' if not current_errors else 'Bazı izleme kaynakları yeniden veri alabildi; diğer kaynakların durumu korunuyor.')
            changed=int(counts.get('new',0))+int(counts.get('changed',0))
            if changed:alert('change',f"{counts.get('new',0)} yeni bulgu, {counts.get('changed',0)} değişen değer gözlendi.")
            if job.status!='cancelled':
                row.last_error=error
            row.last_completed_job_id=job_id
            if job.status in ('completed','partial'):
                row.last_signature=state
            row.next_run_at=utcnow()+timedelta(minutes=row.interval_minutes)

    def reconcile(self):
        with self.service.sessions() as session:
            ids=[w.last_job_id for w in session.scalars(select(Watch)).all() if w.last_job_id and w.last_job_id!=w.last_completed_job_id]
        for job_id in ids:self.complete(job_id)

    def read_alert(self,investigation_id,alert_id):
        with self.service.repo.transaction() as session:
            row=self.service._required(session,WatchAlert,alert_id)
            if row.investigation_id!=investigation_id:raise NotFoundError('alert not found')
            row.read=True
        return {'ok':True}
