"""Persist replay previews and render their exact snapshots as offline HTML."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import hashlib
import hmac
import json
import uuid

from belgu.application.replay import build_replay
from belgu.application.service import NotFoundError


def _case_binding(investigation_id: str) -> str:
    material = b"belgu-replay-case-v1\0" + investigation_id.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def save_replay_preview(service, investigation_id: str, *, redact: bool = True) -> dict:
    payload = {
        **build_replay(service, investigation_id, redact=redact),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    preview_id = str(uuid.uuid4())
    directory = service.evidence_dir / "replay-previews"
    directory.mkdir(exist_ok=True)
    path = directory / f"{preview_id}.json"
    path.write_text(
        json.dumps({"case_binding": _case_binding(investigation_id), "payload": payload}, ensure_ascii=False),
        encoding="utf-8",
    )
    for obsolete in sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[20:]:
        obsolete.unlink(missing_ok=True)
    return {**payload, "preview_id": preview_id}


def _saved_replay(service, investigation_id: str, preview_id: str, redact: bool) -> dict:
    try:
        identifier = str(uuid.UUID(preview_id))
        saved = json.loads(
            (service.evidence_dir / "replay-previews" / f"{identifier}.json").read_text(encoding="utf-8")
        )
    except (ValueError, OSError, json.JSONDecodeError):
        raise NotFoundError("Oynatma önizlemesi bulunamadı; yeniden önizleyin.")
    if not hmac.compare_digest(str(saved.get("case_binding", "")), _case_binding(investigation_id)):
        raise NotFoundError("replay preview not found")
    payload = saved.get("payload")
    if not isinstance(payload, dict):
        raise NotFoundError("Oynatma önizlemesi bulunamadı; yeniden önizleyin.")
    if payload.get("redacted") is not redact:
        raise ValueError("Gizleme seçimi değişti; oynatmayı yeniden önizleyin.")
    return payload


def export_replay(service, investigation_id: str, preview_id: str, *, redact: bool = True) -> str:
    return render_replay(_saved_replay(service, investigation_id, preview_id, redact))


def render_replay(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = escape(str(payload.get("title") or "Belgü · Kayıtlı inceleme"))
    mode = "Maskeli kayıt" if payload.get("redacted") else "Açık kayıt"
    return f'''<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
*{{box-sizing:border-box}}:root{{color-scheme:dark}}body{{margin:0;background:#0b1419;color:#edf6f2;font-family:system-ui,sans-serif}}button,select,input{{font:inherit}}button,select{{background:#14242b;color:#edf6f2;border:1px solid #365049;border-radius:8px;padding:9px 13px}}button:focus-visible,select:focus-visible,input:focus-visible{{outline:2px solid #7bd8b6;outline-offset:2px}}button:disabled{{opacity:.45}}header{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 4vw;border-bottom:1px solid #26383e}}header strong{{color:#7bd8b6;letter-spacing:3px}}header span{{font-size:12px;color:#a9bcb8}}main{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);gap:20px;max-width:1400px;margin:auto;padding:24px 4vw}}.panel{{border:1px solid #293c42;border-radius:14px;background:#101d23;overflow:hidden}}.graph{{min-height:480px;position:relative;padding:24px}}.graph h1{{font-size:clamp(22px,3vw,38px);margin:0 0 4px}}.graph p{{color:#9db1ae;font-size:12px;margin:0}}svg{{display:block;width:100%;height:400px;margin-top:14px}}line{{stroke:#59736c;stroke-width:1.5}}circle{{fill:#17362f;stroke:#7bd8b6;stroke-width:1.5}}text{{fill:#d9ebe5;font-size:9px}}.step{{padding:25px;min-height:480px;display:flex;flex-direction:column}}.eyebrow{{font-size:10px;letter-spacing:1.5px;color:#7bd8b6}}.step h2{{font-size:25px;margin:15px 0 8px}}.detail{{color:#afc1be;line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere}}dl{{margin-top:auto}}dl div{{display:grid;grid-template-columns:110px 1fr;gap:12px;border-top:1px solid #293c42;padding:9px 0;font-size:11px}}dt{{color:#8fa5a1}}dd{{margin:0;overflow-wrap:anywhere}}.empty{{display:grid;place-items:center;min-height:300px;color:#9db1ae}}.controls{{grid-column:1/-1;display:grid;grid-template-columns:auto auto 1fr auto;align-items:center;gap:12px;padding:16px}}.buttons{{display:flex;gap:7px}}label{{font-size:10px;color:#9db1ae}}input[type=range]{{width:100%;accent-color:#7bd8b6}}.coverage{{grid-column:1/-1;color:#9db1ae;font-size:10px;line-height:1.7}}.coverage strong{{color:#edf6f2}}@media(max-width:760px){{main{{grid-template-columns:1fr;padding:14px}}.graph,.step{{min-height:390px}}svg{{height:300px}}.controls{{grid-template-columns:1fr}}.buttons{{justify-content:space-between}}}}@media print{{body{{background:#fff;color:#111}}header,.controls{{display:none}}main{{display:block;padding:0}}.panel{{border:0;background:#fff;break-inside:avoid}}.detail,.coverage,.graph p{{color:#333}}}}
</style></head><body><header><strong>BELGÜ</strong><span>{escape(mode)} · Kayıtlardan yeniden oluşturuldu</span></header>
<main><section class="panel graph" aria-label="Büyüyen inceleme grafiği"><h1>{title}</h1><p>Kaydedilmiş adımlar ilerledikçe grafik büyür.</p><svg id="graph" role="img" aria-label="Kayıtlı inceleme grafiği"></svg></section>
<section class="panel step" aria-live="polite"><span class="eyebrow" id="position"></span><div id="event"></div></section>
<section class="panel controls" aria-label="Oynatma denetimleri"><div class="buttons"><button id="prev" aria-label="Önceki kayıt">← Önceki kayıt</button><button id="play" aria-label="Kaydı oynat">Kaydı oynat</button><button id="next" aria-label="Sonraki kayıt">Sonraki kayıt →</button></div><label>Hız <select id="speed"><option value="0.5">0,5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label><input id="seek" type="range" min="0" value="0" aria-label="Kayıtta ara"><span id="count"></span></section>
<p class="coverage" id="coverage"></p></main><script id="replay-data" type="application/json">{data}</script><script>
const replay=JSON.parse(document.getElementById('replay-data').textContent),events=replay.events||[],svg=document.getElementById('graph'),eventBox=document.getElementById('event'),seek=document.getElementById('seek');let index=0,timer=null,speed=1;seek.max=String(Math.max(0,events.length-1));
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
function visibleGraph(){{const nodes=new Map(),edges=[];for(let i=0;i<=index&&i<events.length;i++){{for(const node of events[i].graph_additions.nodes)nodes.set(node.id,node);edges.push(...events[i].graph_additions.edges)}}return{{nodes:[...nodes.values()],edges}}}}
function graph(){{const state=visibleGraph(),width=640,height=380,r=Math.min(width,height)*.37,dense=state.nodes.length>16,columns=10,rows=Math.max(1,Math.ceil(state.nodes.length/columns)),positions=new Map();state.nodes.forEach((node,i)=>{{if(dense){{const column=i%columns,row=Math.floor(i/columns);positions.set(node.id,[36+column*(width-72)/(columns-1),32+row*(height-64)/Math.max(1,rows-1)])}}else{{const angle=(Math.PI*2*i/Math.max(1,state.nodes.length))-Math.PI/2;positions.set(node.id,[width/2+Math.cos(angle)*r,height/2+Math.sin(angle)*r])}}}});svg.setAttribute('viewBox',`0 0 ${{width}} ${{height}}`);svg.innerHTML=state.edges.map(edge=>{{const a=positions.get(edge.src_id),b=positions.get(edge.dst_id);return a&&b?`<line x1="${{a[0]}}" y1="${{a[1]}}" x2="${{b[0]}}" y2="${{b[1]}}"/>`:''}}).join('')+state.nodes.map(node=>{{const p=positions.get(node.id),label=dense&&node.label.length>11?node.label.slice(0,10)+'…':node.label;return`<g><title>${{esc(node.label)}}</title><circle cx="${{p[0]}}" cy="${{p[1]}}" r="${{dense?7:15}}"/><text x="${{p[0]}}" y="${{p[1]+(dense?17:29)}}" text-anchor="middle" style="font-size:${{dense?6.5:9}}px">${{esc(label)}}</text></g>`}}).join('')}}
function show(value){{index=Math.max(0,Math.min(Math.max(0,events.length-1),value));seek.value=String(index);document.getElementById('position').textContent=events.length?`KAYITLI ADIM ${{index+1}} / ${{events.length}}`:'KAYITLI ADIM YOK';document.getElementById('count').textContent=events.length?`${{index+1}} / ${{events.length}}`:'0 / 0';document.getElementById('prev').disabled=!events.length||index===0;document.getElementById('next').disabled=!events.length||index===events.length-1;document.getElementById('play').disabled=events.length<2;if(!events.length)eventBox.innerHTML='<div class="empty">Bu incelemede oynatılacak kayıt yok.</div>';else{{const item=events[index],refs=item.evidence_refs.length?item.evidence_refs.join(', '):'Kayıtlı kanıt bağlantısı yok';eventBox.innerHTML=`<h2>${{esc(item.title)}}</h2><p class="detail">${{esc(item.detail)}}</p><dl><div><dt>Bilinen zaman</dt><dd>${{esc(item.known_at)}}</dd></div><div><dt>Gözlem zamanı</dt><dd>${{esc(item.observed_at||'Kaydedilmedi')}}</dd></div><div><dt>Durum</dt><dd>${{esc(item.status)}}</dd></div><div><dt>Kanıt</dt><dd>${{esc(refs)}}</dd></div></dl>`}}graph()}}
function stop(){{if(timer)clearInterval(timer);timer=null;document.getElementById('play').textContent='Kaydı oynat'}}function play(){{if(timer){{stop();return}}if(index>=events.length-1)show(0);document.getElementById('play').textContent='Duraklat';timer=setInterval(()=>{{if(index>=events.length-1)stop();else show(index+1)}},1500/speed)}}
document.getElementById('prev').onclick=()=>{{stop();show(index-1)}};document.getElementById('next').onclick=()=>{{stop();show(index+1)}};document.getElementById('play').onclick=play;seek.oninput=()=>{{stop();show(Number(seek.value))}};document.getElementById('speed').onchange=e=>{{speed=Number(e.target.value);if(timer){{stop();play()}}}};document.addEventListener('keydown',e=>{{if(e.key==='ArrowLeft'){{stop();show(index-1)}}if(e.key==='ArrowRight'){{stop();show(index+1)}}if(e.key===' '){{e.preventDefault();play()}}}});const c=replay.coverage;document.getElementById('coverage').innerHTML=`<strong>Kapsam:</strong> ${{c.included_events}} / ${{c.available_events}} kayıt · ${{c.included_graph_nodes}} / ${{c.available_graph_nodes}} grafik düğümü · ${{c.rendered_graph_edges}} gösterilen kenar · ${{c.omitted_graph_edges}} grafik dışında kalan kenar.${{c.omitted_events?' Kayıt sınırı nedeniyle '+c.omitted_events+' adım gösterilmedi.':''}}`;show(0);
</script></body></html>'''
