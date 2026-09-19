"""Recorded workbench example. Called only for an explicitly fictional demo case."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from hashlib import sha256
from sqlalchemy import select
from belgu.domain.contracts import EntityRef,EvidenceDraft,ProviderResult
from belgu.persistence.models import Artifact,Watch,WatchAlert,utcnow


def seed_workbench(service,investigation_id):
    inv=service.get_investigation(investigation_id)
    if not inv.demo:raise ValueError('Workbench fixtures require a demo investigation')
    assets=Path(__file__).with_name('assets')
    reference=(assets/'fictional-reference.png').read_bytes()
    # Backfill existing demo cases before the recorded-capture early return.
    with service.sessions() as session:
        existing_reference=session.scalar(select(Artifact.id).where(
            Artifact.brand_id==inv.brand_id, Artifact.sha256==sha256(reference).hexdigest()))
    if existing_reference is None:
        service.attach_to_brand(inv.brand_id,reference,'image/png')
    evidence=service.list_evidence(investigation_id)
    if any(e.kind=='page_browser' and e.payload.get('fictional') for e in evidence):return
    from belgu.application.jobs import JobService
    from belgu.application.insights import record_run
    from belgu.core.providers.page import PageParser
    from belgu.core.browser_capture import extract_ocr
    png=(assets/'fictional-login.png').read_bytes()
    image=service.attach_to_investigation(investigation_id,png,'image/png')
    parser=PageParser();parser.feed((assets/'fictional-login.html').read_text())
    ocr=extract_ocr(png)
    when=datetime(2026,9,8,10,0,tzinfo=timezone.utc)
    target='guvenli-giris-kuzey.test';url='https://'+target+'/Mobil/Giris'
    captured=service.record_result(investigation_id,ProviderResult('recorded_demo','ok',(
        EvidenceDraft(EntityRef('url',url),'page_browser','urn:belgu:demo:recorded-image',when,when,
            {'url':url,'final_url':url,'requested_url':url,'artifact_id':image.id,'title':parser.title,
             'text':parser.text,'text_source':'recorded_fixture','forms':parser.forms,'inputs':[],
             'credential_form':parser.credential_form,'status_code':200,'ocr_text':ocr['text'],
             'ocr_status':ocr['status'],'ocr':ocr,'fictional':True,
             'limitations':['Kurgusal statik gösterim ekranıdır; canlı hedef görüntüsü değildir.','Bu görseldeki kutular tasarım öğesidir; HTML giriş alanı bulunmaz.']}),)))
    jobs=JobService(service)
    first=jobs.enqueue(investigation_id,'collect');record_run(service,first.id,[e.id for e in evidence]+captured.evidence_ids)
    jobs.finish(first.id,{'status':'completed','message':'Kayıtlı kurmaca ilk keşif'})
    changed=service.record_result(investigation_id,ProviderResult('recorded_demo','ok',(
        EvidenceDraft(EntityRef('domain',target),'dns_a','urn:belgu:demo:dns:changed',when+timedelta(hours=2),when+timedelta(hours=2),
            {'answer':'198.51.100.2','observed_ip':'198.51.100.2','fictional':True,'confidence_note':'Ortak IP, tek başına ortak kampanya kanıtı değildir.'}),)))
    old=[e.id for e in evidence if e.subject.value==target and e.kind=='dns_a']
    second=jobs.enqueue(investigation_id,'collect')
    record_run(service,second.id,[e.id for e in evidence if e.id not in old]+captured.evidence_ids+changed.evidence_ids)
    jobs.finish(second.id,{'status':'completed','message':'Kayıtlı kurmaca ikinci keşif'})
    with service.repo.transaction() as session:
        watch=Watch(investigation_id=investigation_id,interval_minutes=60,enabled=False,next_run_at=when+timedelta(hours=3),last_job_id=second.id,last_completed_job_id=second.id)
        session.add(watch);session.flush()
        session.add(WatchAlert(watch_id=watch.id,investigation_id=investigation_id,kind='change',message='Kurgusal örnek: hedefin DNS gözlemindeki adres değişti.',job_id=second.id))
    analyses=service.list_analyses(investigation_id)
    output=dict(analyses[0].output) if analyses else {}
    output.update(summary='Kurgusal örnekte 120 alan adı için altyapı bağlantıları bulunuyor. İki kayıtlı keşif arasında hedefin DNS adresi farklı. Görsel masadaki ekran statik bir tasarım örneğidir; gerçek giriş alanı veya veri toplama kanıtı değildir.',claims=[
        {'text':'Hedefe ait iki kayıtlı DNS gözlemindeki adresler farklıdır.','kind':'observation','evidence_ids':old+changed.evidence_ids},
        {'text':'Kurgusal referans görüntüsünün HTML kaynağında parola giriş alanı bulunmaz.','kind':'observation','evidence_ids':captured.evidence_ids}],
        prompt_version='belgu-demo-v2',evidence_ids=[e.id for e in service.list_evidence(investigation_id)],
        uncertainties=['Tüm örnekler kurmacadır; canlı banka veya müşteri verisi kullanılmaz.','Ortak altyapı tek başına aynı saldırganı göstermez.'])
    service.save_analysis(investigation_id,output,recorded_demo=True)
