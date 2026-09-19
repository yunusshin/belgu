from datetime import timedelta
from sqlalchemy import select
from belgu.application.watches import WatchService
from belgu.persistence.models import Job, Watch, utcnow


def case(service):
    b=service.create_brand('Fixture', ['official.test'])
    i=service.create_investigation(b.id,'Watch fixture')
    service.add_submission(i.id,'candidate.test','analyst_discovery')
    return i.id


def test_watch_persists_and_pauses_without_duplicate_pending_jobs(service):
    s=WatchService(service);i=case(service)
    w=s.create(i,None,5,True)
    assert s.schedule_due(now=utcnow()+timedelta(minutes=6)) == 1
    assert s.schedule_due(now=utcnow()+timedelta(minutes=6)) == 0
    assert WatchService(service).list(i)['items'][0]['last_job_id']
    s.patch(i,w['id'],enabled=False)
    assert s.schedule_due(now=utcnow()+timedelta(days=1)) == 0


def test_watch_checks_scope_and_interval(service):
    import pytest
    s=WatchService(service);i=case(service);other=case(service)
    with pytest.raises(ValueError):s.create(i,None,1,True)
    w=s.create(i,None,5,False)
    from belgu.application.service import NotFoundError
    with pytest.raises(NotFoundError):s.patch(other,w['id'],enabled=True)
    assert s.list(other)['items']==[]


def test_unchanged_result_is_quiet_and_repeated_failure_is_not_duplicated(service, monkeypatch):
    from belgu.application.jobs import JobService
    s=WatchService(service);i=case(service);w=s.create(i,None,5,True)
    # The first run establishes a baseline; subsequent same-state runs are quiet.
    monkeypatch.setattr(s,'_changes',lambda *args: {'counts':{'new':0,'changed':0}})
    for _ in range(2):
        j=s.run_now(i,w['id']);JobService(service).finish(j.id,{'status':'completed'});s.complete(j.id)
    assert s.list(i)['alerts']==[]
    for _ in range(2):
        j=s.run_now(i,w['id']);JobService(service).finish(j.id,{'status':'failed','error':'timed out'});s.complete(j.id)
    assert len(s.list(i)['alerts'])==1
    j=s.run_now(i,w['id']);JobService(service).finish(j.id,{'status':'completed'});s.complete(j.id)
    assert {a['kind'] for a in s.list(i)['alerts']}=={'failure','recovered'}


def test_new_change_emits_one_alert_and_can_be_acknowledged(service,monkeypatch):
    from belgu.application.jobs import JobService
    s=WatchService(service);i=case(service);w=s.create(i,None,5,True)
    monkeypatch.setattr(s,'_changes',lambda *args: {'counts':{'new':1,'changed':1}})
    for _ in range(2):
        j=s.run_now(i,w['id']);JobService(service).finish(j.id,{'status':'completed'});s.complete(j.id)
    alert=s.list(i)['alerts'][0]
    assert alert['kind']=='change'
    s.read_alert(i,alert['id'])
    assert s.list(i)['alerts'][0]['read'] is True


def test_partial_gap_and_dns_subset_recovery_do_not_report_same_ip_as_new(service):
    from belgu.application.jobs import JobService
    from belgu.domain.contracts import ProviderResult,EvidenceDraft,EntityRef
    from belgu.application.insights import record_run
    s=WatchService(service);i=case(service);w=s.create(i,None,5,True)
    for answers,status in [(['198.51.100.1','198.51.100.2'],'completed'),([], 'partial'),(['198.51.100.1'],'partial'),(['198.51.100.1','198.51.100.2'],'completed')]:
        j=s.run_now(i,w['id'])
        result=ProviderResult('dns','ok',tuple(EvidenceDraft(EntityRef('domain','candidate.test'),'dns_a','dns:fixture',utcnow(),utcnow(),{'observed_ip':ip,'rrtype':'A'}) for ip in answers))
        saved=service.record_result(i,result,job_id=j.id)
        record_run(service,j.id,saved.evidence_ids)
        JobService(service).finish(j.id,{'status':status});s.complete(j.id)
    assert not [a for a in s.list(i)['alerts'] if a['kind']=='change']


def test_new_source_failure_is_distinct_and_partial_http_error_is_reported(service):
    from belgu.application.jobs import JobService
    from belgu.application.insights import record_run
    s=WatchService(service);i=case(service);w=s.create(i,None,5,True)
    for provider,status,code in [('dns','error','timeout'),('crtsh','error','timeout'),('page','partial','upstream_http_403')]:
        j=s.run_now(i,w['id']);record_run(service,j.id,[])
        JobService(service).finish(j.id,{'status':'partial','providers':[{'provider':provider,'status':status,'error_code':code}]});s.complete(j.id)
    assert len([a for a in s.list(i)['alerts'] if a['kind']=='failure'])==3


def test_overdue_closed_cases_do_not_starve_eligible_watches(service):
    s=WatchService(service)
    for _ in range(20):
        i=case(service);s.create(i,None,5,True);service.set_workflow(i,'closed')
    active=case(service);s.create(active,None,5,True)
    assert s.schedule_due(utcnow()+timedelta(days=1))==1
    assert s.list(active)['items'][0]['last_job_id']


def test_reducing_failed_sources_does_not_create_new_failure_alert(service):
    from belgu.application.jobs import JobService
    from belgu.application.insights import record_run
    s=WatchService(service);i=case(service);w=s.create(i,None,5,True)
    for names in [('dns','crtsh'),('dns',)]:
        j=s.run_now(i,w['id']);record_run(service,j.id,[])
        JobService(service).finish(j.id,{'status':'partial','providers':[{'provider':n,'status':'error','error_code':'timeout'} for n in names]});s.complete(j.id)
    alerts=s.list(i)['alerts']
    assert len([a for a in alerts if a['kind']=='failure'])==1
    assert len([a for a in alerts if a['kind']=='recovered'])==1
