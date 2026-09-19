"""Self-contained selected-evidence presentation, with true data minimization."""
import base64
from datetime import datetime,timezone
from html import escape
import json
import uuid
from belgu.application.service import NotFoundError

LABELS={'dns_a':'DNS gözlemi','dns_ptr':'Ters DNS','page_content':'Sayfa gözlemi','page_browser':'Görsel kanıt','page_attempt_failed':'Bağlantı gözlemi','page_capture_failed':'Görüntü alma sonucu','redirect_chain':'Yönlendirme','existing_scan':'Arşiv gözlemi','passive_dns':'Altyapı bağlantısı','tls_certificate':'Sertifika gözlemi','javascript_content':'Betik izi'}


def build_story(service, investigation_id, evidence_ids=None, redact=True):
    inv=service.get_investigation(investigation_id)
    all_evidence=service.list_evidence(investigation_id)
    by_id={e.id:e for e in all_evidence}
    ids=list(dict.fromkeys(evidence_ids or []))
    if len(ids)>12:raise ValueError('En fazla 12 kanıt seçin.')
    if not ids:
        direct={s.target.hostname or s.target.canonical_value for s in inv.submissions}
        from urllib.parse import urlsplit
        def key(e):
            host=urlsplit(e.subject.value).hostname if e.subject.kind=='url' else e.subject.value
            return (host not in direct,e.kind not in ('page_browser','page_content','redirect_chain','dns_a'),e.retrieved_at)
        ids=[e.id for e in sorted(all_evidence,key=key)[:6]]
    if any(i not in by_id for i in ids):raise NotFoundError('story evidence not found')
    title='Belgü · İnceleme hikâyesi' if redact else inv.title
    steps=[{'title':'Bir bildirimden kanıta','subtitle':'BELGÜ / İNCELEME','body':f'{len(ids)} seçili kanıtın araştırma akışı. '+('Paylaşım için kaynak kimlikleri ve ham içerik gizlendi.' if redact else 'Kaynak ve gözlem bilgileriyle analist sunumu.'),'fields':[{'label':'Görünüm','value':'Maskeli' if redact else 'Açık'},{'label':'Değerlendirme','value':'Analist incelemesi'}]}]
    subjects={};image_bytes=0
    for item_id in ids:
        e=by_id[item_id];p=e.payload
        alias=subjects.setdefault(e.subject.value,f'Hedef {len(subjects)+1}')
        date=e.observed_at.isoformat() if e.observed_at else 'Gözlem zamanı bilinmiyor'
        fields=[{'label':'Gözlem zamanı','value':date}]
        label=LABELS.get(e.kind,'Kanıt gözlemi')
        if redact:
            # Whitelist generated language and typed status only. Raw fields are
            # never embedded in hidden HTML, script data, captions or images.
            body={'dns_a':'Alan adının çözümlendiği adres kaydedildi.','page_content':'Sayfa yanıtı ve metin gözlemi kaydedildi.','page_browser':'Ekran görüntüsü ve sayfa alanları yerel olarak kaydedildi.','redirect_chain':'Başlangıç ve son adres arasında yönlendirme gözlendi.','existing_scan':'Önceki bir taramanın kaynak kaydı incelemeye eklendi.'}.get(e.kind,'Kaynak gözlemi ve dayanağı incelemeye eklendi.')
            if type(p.get('status_code')) is int and 100<=p['status_code']<=599:fields.append({'label':'HTTP yanıtı','value':str(p['status_code'])})
            if type(p.get('credential_form')) is bool:fields.append({'label':'Parola alanı','value':'Tespit edildi' if p['credential_form'] else 'Tespit edilmedi'})
            step={'title':label,'subtitle':alias,'body':body,'fields':fields}
        else:
            body=str(p.get('title') or p.get('text') or p.get('reason') or label)[:1500]
            fields.extend([{'label':'Kaynak','value':e.source_ref},{'label':'Sağlayıcı','value':e.provider}])
            for key in ('answer','status_code','final_url','credential_form','js_sha256'):
                if key in p:fields.append({'label':key.replace('_',' '),'value':str(p[key])[:500]})
            step={'title':label,'subtitle':e.subject.value,'body':body,'fields':fields}
            if p.get('artifact_id'):
                try:
                    artifact,path=service.get_artifact(p['artifact_id'],investigation_id=investigation_id)
                    if artifact.mime in ('image/png','image/jpeg') and artifact.size_bytes<=4*1024*1024 and image_bytes+artifact.size_bytes<=12*1024*1024:
                        content=path.read_bytes();image_bytes+=len(content)
                        step['image_url']=f'data:{artifact.mime};base64,'+base64.b64encode(content).decode()
                except (NotFoundError,OSError):
                    step['fields'].append({'label':'Görüntü','value':'Yerel dosya bulunamadı'})
        steps.append(step)
    steps.append({'title':'Kanıtlar ve değerlendirme','subtitle':'ARAŞTIRMA SONUCU','body':'Ortak altyapı araştırılacak bir bağlantıdır; tek başına aynı kampanya veya saldırganı kanıtlamaz. Son değerlendirme analiste aittir.','fields':[{'label':'Seçili kanıt','value':str(len(ids))}]})
    return {'title':title,'redacted':redact,'steps':steps,'created_at':datetime.now(timezone.utc).isoformat()}


def render_story(payload):
    cards=[]
    for index,step in enumerate(payload['steps']):
        image=f'<img alt="Seçili sayfa görüntüsü" src="{escape(step["image_url"],quote=True)}">' if step.get('image_url') else ''
        fields=''.join(f'<div><dt>{escape(str(f["label"]))}</dt><dd>{escape(str(f["value"]))}</dd></div>' for f in step['fields'])
        cards.append(f'<section class="slide" {"" if index==0 else "hidden"}><p class="eyebrow">{escape(step["subtitle"])}</p><h1>{escape(step["title"])}</h1><p class="body">{escape(step["body"])}</p>{image}<dl>{fields}</dl></section>')
    return '''<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+escape(payload['title'])+'''</title><style>
*{box-sizing:border-box}body{margin:0;background:#0d151b;color:#eaf5f1;font-family:system-ui,sans-serif}header,footer{display:flex;justify-content:space-between;align-items:center;padding:24px 5vw;border-bottom:1px solid #26343c}header strong{font-size:24px;letter-spacing:3px;color:#8ae1c1}main{max-width:1200px;margin:auto;padding:5vh 5vw;min-height:70vh}.eyebrow{color:#8ae1c1;letter-spacing:2px;font-size:12px;overflow-wrap:anywhere}h1{font-size:clamp(26px,5vw,54px);line-height:1.1}p.body{line-height:1.8;color:#afc4c3;max-width:850px;white-space:pre-wrap;overflow-wrap:anywhere}dl{display:flex;flex-wrap:wrap;gap:28px}dt{font-size:11px;text-transform:uppercase;color:#8ea3a8}dd{margin:8px 0;max-width:800px;overflow-wrap:anywhere}img{display:block;max-width:100%;max-height:55vh;object-fit:contain;border-radius:14px;border:1px solid #344a50}button{background:#18272e;color:#eaf5f1;border:1px solid #38524f;padding:12px 20px;border-radius:8px;cursor:pointer}button:focus-visible{outline:2px solid #8ae1c1}.slide[hidden]{display:none}@media print{body{background:white;color:black}header,footer{display:none}.slide[hidden]{display:block}.slide{break-after:page}p.body,.eyebrow{color:#333}main{padding:0}img{max-height:50vh}}
</style><header><strong>BELGÜ</strong><span>'''+('Maskeli sunum' if payload['redacted'] else 'Kaynakları içeren sunum')+'''</span></header><main>'''+''.join(cards)+'''</main><footer><button id="prev">← Önceki</button><span id="position" aria-live="polite"></span><button id="next">Sonraki →</button></footer><script>
const slides=[...document.querySelectorAll('.slide')];let index=0;function show(n){index=Math.max(0,Math.min(slides.length-1,n));slides.forEach((s,i)=>s.hidden=i!==index);document.getElementById('position').textContent=(index+1)+' / '+slides.length;document.getElementById('prev').disabled=index===0;document.getElementById('next').disabled=index===slides.length-1;}document.getElementById('prev').onclick=()=>show(index-1);document.getElementById('next').onclick=()=>show(index+1);document.addEventListener('keydown',e=>{if(e.key==='ArrowRight')show(index+1);if(e.key==='ArrowLeft')show(index-1);});show(0);
</script></html>'''


def save_story_preview(service, investigation_id, evidence_ids=None, redact=True):
    payload=build_story(service,investigation_id,evidence_ids,redact)
    preview_id=str(uuid.uuid4())
    directory=service.evidence_dir/'story-previews';directory.mkdir(exist_ok=True)
    path=directory/(preview_id+'.json')
    path.write_text(json.dumps({'investigation_id':investigation_id,'payload':payload},ensure_ascii=False))
    # Previews are derived caches; retain the most recent 20, independently of evidence.
    for obsolete in sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[20:]:
        obsolete.unlink(missing_ok=True)
    return {**payload,'preview_id':preview_id}


def export_story(service, investigation_id, evidence_ids=None, redact=True, preview_id=None):
    if preview_id:
        try:
            identifier=str(uuid.UUID(preview_id))
            saved=json.loads((service.evidence_dir/'story-previews'/(identifier+'.json')).read_text())
        except (ValueError,OSError,json.JSONDecodeError):
            raise NotFoundError('Sunum önizlemesi bulunamadı; yeniden önizleyin.')
        if saved.get('investigation_id')!=investigation_id:raise NotFoundError('story preview not found')
        payload=saved['payload']
        if payload['redacted']!=redact:raise ValueError('Gizleme seçimi değişti; sunumu yeniden önizleyin.')
        return render_story(payload)
    return render_story(build_story(service,investigation_id,evidence_ids,redact))
