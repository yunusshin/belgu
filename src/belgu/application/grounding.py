"""Expose the actual citation fields for analyst review, without certifying claims."""
from belgu.application.service import NotFoundError

FIELDS = ('title','text','visible_text','ocr_text','text_source','credential_form','forms','inputs','status_code','requested_url','final_url','hops','answer','observed_ip','rrtype','rcode','cert_sha256','js_sha256','script_url','scan_source','failure','error_type','reason','certificate_id','issuer','names','not_before','not_after','relationship','domain','signals','rule_version','kit_signals','favicon_sha256')


def evidence_fields(evidence):
    payload=evidence.payload
    result=[]
    for key in FIELDS:
        if key in payload:
            value=payload[key]
            if isinstance(value,str):value=value[:2400]
            if isinstance(value,list):value=value[:10]
            result.append({'path':key,'value':value})
    return result


def grounding(service, investigation_id, analysis_id=None):
    analyses=service.list_analyses(investigation_id)
    analysis=next((a for a in analyses if a.id==analysis_id),None) if analysis_id else next(iter(analyses),None)
    if analysis_id and analysis is None:raise NotFoundError('analysis not found')
    if analysis is None:return {'analysis_id':None,'summary':'','claims':[],'limitations':['Henüz kayıtlı model analizi yok.']}
    evidence={e.id:e for e in service.list_evidence(investigation_id)}
    claims=[]
    for index,claim in enumerate(analysis.output.get('claims',[])):
        support=[];warnings=[]
        for evidence_id in dict.fromkeys(claim.get('evidence_ids',[])):
            item=evidence.get(evidence_id)
            if item is None:
                warnings.append('Atıf bu incelemede bulunamadı.');continue
            support.append({'id':item.id,'subject':item.subject.model_dump(),'provider':item.provider,'observed_at':item.observed_at,'retrieved_at':item.retrieved_at,'fields':evidence_fields(item)})
            if item.payload.get('credential_form') is False:warnings.append('Bu kayıtta parola alanı tespit edilmedi; dinamik ekranlar ve veri gönderimi doğrulanmış değil.')
            if item.provider in ('urlscan','crtsh') or item.kind=='passive_dns':warnings.append('Arşiv kaydı: gözlem zamanı ile kaydın alınma zamanı farklı olabilir.')
            if item.observed_at is None:warnings.append('Kaynağın gözlem zamanı belirtilmemiş.')
            if item.kind=='page_capture_failed':warnings.append('Görüntü alınamadı; sayfa içeriği bu kayıttan çıkarılamaz.')
        if not support:warnings.append('Gösterilebilir kanıt dayanağı yok.')
        claims.append({'index':index,'text':claim.get('text',''),'kind':claim.get('kind','unknown'),'support':support,'warnings':list(dict.fromkeys(warnings))})
    return {'analysis_id':analysis.id,'summary':analysis.output.get('summary',''),'claims':claims,'limitations':['Model metin kanıtlarını değerlendirdi; görsel benzerlik analizi yapmadı.','Atıflar ve alanlar incelemeyi kolaylaştırır; iddianın doğruluğunu otomatik olarak onaylamaz.']+(['Bu analizden sonra kanıtlar değişti.'] if analysis.stale else [])}
