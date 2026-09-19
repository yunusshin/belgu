from fastapi.testclient import TestClient
from belgu.api.app import create_app
from belgu.settings import Settings
from belgu.domain.contracts import ProviderResult,EvidenceDraft,EntityRef
from belgu.persistence.models import utcnow


def test_workbench_endpoints_and_story_download(tmp_path):
    app=create_app(Settings(db_url=f'sqlite:///{tmp_path}/api.db',evidence_dir=tmp_path/'files',start_worker=False,mode='operational'))
    with TestClient(app) as c:
        b=c.post('/api/brands',json={'name':'Brand','official_domains':['official.test']}).json()
        i=c.post('/api/investigations',json={'brand_id':b['id'],'title':'Fixture'}).json()['id']
        base=f'/api/investigations/{i}'
        c.post(base+'/submissions',json={'value':'candidate.test','source':'analyst_discovery'})
        for suffix in ('captures','candidates','runs','changes','grounding','watches','evidence'):
            r=c.get(base+'/'+suffix);assert r.status_code==200,(suffix,r.text)
        capture=c.post(base+'/captures',json={'url':'candidate.test'})
        assert capture.status_code==202 and capture.json()['kind']=='capture'
        c.post('/api/jobs/'+capture.json()['id']+'/cancel')
        w=c.post(base+'/watches',json={'interval_minutes':5}).json()
        assert w['enabled']
        r=c.post(base+f'/watches/{w["id"]}/run');assert r.status_code==202
        assert c.post(base+f'/watches/{w["id"]}/run').status_code==422
        assert c.patch(base+f'/watches/{w["id"]}',json={'enabled':False}).json()['enabled'] is False
        r=c.post(base+'/story/export',json={'redact':True})
        assert r.status_code==200 and 'text/html' in r.headers['content-type']
        assert 'candidate.test' not in r.text
        assert 'Sonraki' in r.text
        png=b'\x89PNG\r\n\x1a\n'+b'fixture'
        assert c.post(f'/api/brands/{b["id"]}/attachments',files={'file':('ref.png',png,'image/png')}).status_code==201
        assert len(c.get(base+'/captures').json()['references'])==1


def test_demo_workbench_never_enqueues_network(tmp_path):
    app=create_app(Settings(db_url=f'sqlite:///{tmp_path}/demo.db',evidence_dir=tmp_path/'files',start_worker=False,mode='demo'))
    with TestClient(app) as c:
        b=app.state.service.create_brand('Demo',[]);i=app.state.service.create_investigation(b.id,'demo',demo=True)
        app.state.service.add_submission(i.id,'candidate.test','analyst_discovery')
        for suffix,payload in [('captures',{'url':'candidate.test'}),('watches',{'interval_minutes':5})]:
            assert c.post(f'/api/investigations/{i.id}/'+suffix,json=payload).status_code==409
        assert app.state.service.list_jobs(i.id)==[]


def test_discovery_records_exact_run_evidence_ids(service,monkeypatch):
    from belgu.application.jobs import JobService,Worker
    from belgu.core.discovery import DiscoveryResult
    from belgu.application.insights import list_runs
    b=service.create_brand('Fixture',[]);i=service.create_investigation(b.id,'Runs')
    service.add_submission(i.id,'candidate.test','analyst_discovery')
    result=ProviderResult('dns','ok',(EvidenceDraft(EntityRef('domain','candidate.test'),'dns_a','dns:fixture',utcnow(),utcnow(),{'answer':'198.51.100.9','rrtype':'A'}),))
    from types import SimpleNamespace
    monkeypatch.setattr('belgu.core.discovery.discover',lambda *a,**kw:SimpleNamespace(results=[result],counts={'requests':1,'entities':1,'observations':1},status='completed',truncated=False))
    j=JobService(service).enqueue(i.id,'collect');w=Worker(service);claimed=w.jobs.claim(w.worker_id);w._execute(claimed)
    runs=list_runs(service,i.id)
    assert runs['items'][0]['id']==j.id
    assert runs['items'][0]['evidence_count']==1 and not runs['items'][0]['approximate']


def test_observation_membership_is_committed_and_reused_after_worker_retry(service,monkeypatch):
    from belgu.application.jobs import JobService,Worker
    from belgu.persistence.models import CollectionRun
    from types import SimpleNamespace
    b=service.create_brand('Fixture',[]);i=service.create_investigation(b.id,'Retry')
    service.add_submission(i.id,'candidate.test','analyst_discovery')
    j=JobService(service).enqueue(i.id,'collect')
    def result(ip):return ProviderResult('dns','ok',(EvidenceDraft(EntityRef('domain','candidate.test'),'dns_a','dns:fixture',utcnow(),utcnow(),{'answer':ip}),))
    first=service.record_result(i.id,result('198.51.100.1'),job_id=j.id)
    with service.sessions() as session:assert session.get(CollectionRun,j.id).evidence_ids==first.evidence_ids
    monkeypatch.setattr('belgu.core.discovery.discover',lambda *a,**kw:SimpleNamespace(results=[result('198.51.100.2')],counts={'requests':1},status='completed',truncated=False))
    w=Worker(service);w._execute(w.jobs.claim(w.worker_id))
    with service.sessions() as session:
        ids=session.get(CollectionRun,j.id).evidence_ids
        assert set(first.evidence_ids)<set(ids) and len(ids)==2
