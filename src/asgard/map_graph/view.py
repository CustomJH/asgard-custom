"""자립형 그래프 뷰 — 외부 리소스 0 의 단일 HTML 로 관계 그래프를 그린다.

`asgard map`(bare) / `asgard map view` 가 연다. 산출물은 런타임 상태
(`.asgard/state/map-view.html`) 로, git 에 추적되지 않는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .bridge import related_records
from .graph import GraphError, _atomic_state_write, _state_file, graph_state

_VIEW_RELATIVE = Path(".asgard") / "state" / "map-view.html"

_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<link rel="icon" href="data:,">
<title>Asgard Map — relation graph</title>
<style>
  :root { --bg:#0b0e14; --panel:#11151f; --line:#1d2433; --ink:#e6e1d3;
          --dim:#8b90a0; --gold:#d4af37; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--ink); font:14px/1.5 "SF Mono",Menlo,monospace;
         display:grid; grid-template-columns:1fr 340px; height:100vh; overflow:hidden; }
  #stage { position:relative; }
  canvas { display:block; width:100%; height:100%; }
  aside { border-left:1px solid var(--line); background:var(--panel); padding:16px;
          overflow-y:auto; }
  h1 { font-size:15px; letter-spacing:.08em; color:var(--gold); margin-bottom:4px; }
  h1::before { content:"◭ "; }
  .sub { color:var(--dim); font-size:12px; margin-bottom:12px; }
  input { width:100%; background:var(--bg); border:1px solid var(--line); color:var(--ink);
          padding:7px 10px; border-radius:6px; font:inherit; margin-bottom:10px; }
  select { width:100%; background:var(--bg); border:1px solid var(--line); color:var(--ink);
           padding:7px 10px; border-radius:6px; font:inherit; margin-bottom:10px; }
  input:focus, select:focus, .chip:focus-visible { outline:2px solid var(--gold); outline-offset:1px; }
  .sr { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden;
        clip:rect(0,0,0,0); white-space:nowrap; border:0; }
  .legend { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:14px; }
  .chip { border:1px solid var(--line); border-radius:999px; padding:2px 10px; font-size:11px;
          cursor:pointer; color:var(--dim); user-select:none; background:transparent; font-family:inherit; }
  .chip.on { color:var(--ink); border-color:var(--gold); }
  .chip i { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }
  #detail { border-top:1px solid var(--line); padding-top:12px; font-size:12.5px; }
  #detail .id { color:var(--gold); word-break:break-all; }
  #detail .cand { color:#c58f4a; }
  #detail ul { list-style:none; margin-top:8px; }
  #detail li { padding:3px 0; color:var(--dim); word-break:break-all; }
  #detail li b { color:var(--ink); font-weight:600; }
  .records { margin-top:10px; }
  .records h3 { font-size:11px; color:var(--gold); letter-spacing:.1em; }
  .stat { color:var(--dim); font-size:11.5px; margin-top:14px; border-top:1px solid var(--line);
          padding-top:10px; }
  @media (max-width:720px) {
    body { display:block; height:auto; min-height:100vh; overflow:auto; }
    #stage { height:55vh; min-height:320px; }
    aside { border-left:0; border-top:1px solid var(--line); }
  }
</style>
</head>
<body>
<div id="stage"><canvas id="c" aria-hidden="true"></canvas></div>
<aside>
  <h1>ASGARD MAP</h1>
  <div class="sub">relation graph · 후보(?)는 소스에서 재확인</div>
  <label class="sr" for="q">노드 검색</label>
  <input id="q" placeholder="filter nodes… (예: stripe, GET /)">
  <label class="sr" for="nodeSelect">노드 선택</label>
  <select id="nodeSelect"><option value="">노드를 선택해 증거 보기</option></select>
  <div class="legend" id="legend"></div>
  <div id="detail" aria-live="polite"><span class="sub">노드를 선택하면 증거 위치가 표시된다.</span></div>
  <div class="stat" id="stat"></div>
</aside>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const COLORS = { file:"#5b6377", route:"#d4af37", command:"#e0c060", model:"#7aa2f7",
  db_access:"#9ece6a", api_call:"#f7768e", event:"#bb9af7", job:"#7dcfff", external_service:"#ff9e64" };
const canvas = document.getElementById("c"), ctx = canvas.getContext("2d");
let nodes = DATA.nodes.map((n,i)=>({ ...n,
  x: Math.cos(i*2.399963)*(60+Math.sqrt(i)*22), y: Math.sin(i*2.399963)*(60+Math.sqrt(i)*22),
  vx:0, vy:0 }));
const byId = Object.fromEntries(nodes.map(n=>[n.id,n]));
const edges = DATA.edges.filter(e=>byId[e.source]&&byId[e.target]);
const degree = {}; edges.forEach(e=>{ degree[e.source]=(degree[e.source]||0)+1; degree[e.target]=(degree[e.target]||0)+1; });
let off={x:0,y:0}, scale=1, active=new Set(Object.keys(COLORS)), query="", selected=null,
  hot=matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 200;
function radius(n){ return n.kind==="file" ? 3.5 : Math.min(11, 5+(degree[n.id]||0)*0.6); }
function visible(n){ if(!active.has(n.kind)) return false;
  if(!query) return true; return (n.id+" "+n.name).toLowerCase().includes(query); }
function tick(){
  for(const n of nodes){ n.vx*= .82; n.vy*= .82; n.vx-=n.x*0.0018; n.vy-=n.y*0.0018; }
  // ponytail: 큰 그래프는 근접 인덱스 80개만 반발; 전역 공간 인덱스는 실제 병목이 확인되면 추가한다.
  const repelSpan=nodes.length>800 ? 80 : nodes.length;
  for(let i=0;i<nodes.length;i++) for(let j=i+1;j<Math.min(nodes.length,i+repelSpan);j++){
    const a=nodes[i],b=nodes[j]; let dx=b.x-a.x, dy=b.y-a.y;
    const d2=dx*dx+dy*dy+0.01; if(d2>16000) continue;
    const f=140/d2; dx*=f; dy*=f; a.vx-=dx; a.vy-=dy; b.vx+=dx; b.vy+=dy; }
  for(const e of edges){ const a=byId[e.source], b=byId[e.target];
    const dx=b.x-a.x, dy=b.y-a.y, d=Math.hypot(dx,dy)||1, f=(d-46)*0.004;
    a.vx+=dx/d*f; a.vy+=dy/d*f; b.vx-=dx/d*f; b.vy-=dy/d*f; }
  for(const n of nodes){ n.x+=n.vx; n.y+=n.vy; }
}
function draw(){
  const w=canvas.width=canvas.clientWidth*devicePixelRatio, h=canvas.height=canvas.clientHeight*devicePixelRatio;
  ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,w,h);
  ctx.translate(w/2+off.x, h/2+off.y); ctx.scale(scale*devicePixelRatio, scale*devicePixelRatio);
  ctx.lineWidth=0.6;
  for(const e of edges){ const a=byId[e.source], b=byId[e.target];
    if(!visible(a)&&!visible(b)) continue;
    const dim = selected && e.source!==selected.id && e.target!==selected.id;
    ctx.strokeStyle = dim ? "rgba(60,68,90,.25)" : "rgba(138,144,160,.35)";
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); }
  for(const n of nodes){ if(!visible(n)) continue;
    const r=radius(n), dim = selected && selected!==n && !edges.some(e=>
      (e.source===selected.id&&e.target===n.id)||(e.target===selected.id&&e.source===n.id));
    ctx.globalAlpha = dim? .25 : 1;
    ctx.fillStyle = COLORS[n.kind]||"#888";
    ctx.beginPath(); ctx.arc(n.x,n.y,r,0,7); ctx.fill();
    if(n.confidence==="candidate"){ ctx.strokeStyle="#0b0e14"; ctx.lineWidth=1.4;
      ctx.beginPath(); ctx.arc(n.x,n.y,r*0.45,0,7); ctx.stroke(); }
    if(n===selected||scale>1.6&&n.kind!=="file"){ ctx.fillStyle="#e6e1d3"; ctx.font="10px monospace";
      ctx.fillText(n.name.slice(0,32), n.x+r+3, n.y+3); }
    ctx.globalAlpha=1; }
}
function loop(){ if(hot-- > 0){ tick(); draw(); requestAnimationFrame(loop); } else draw(); }
canvas.addEventListener("wheel", e=>{ e.preventDefault(); scale=Math.max(.3,Math.min(4,scale*(e.deltaY<0?1.1:0.9))); draw(); });
window.addEventListener("resize", draw);
let drag=null;
canvas.addEventListener("pointerdown", e=>{ drag={x:e.clientX,y:e.clientY}; });
window.addEventListener("pointermove", e=>{ if(drag){ off.x+=(e.clientX-drag.x)*devicePixelRatio; off.y+=(e.clientY-drag.y)*devicePixelRatio; drag={x:e.clientX,y:e.clientY}; draw(); }});
window.addEventListener("pointerup", ()=>{ drag=null; });
canvas.addEventListener("click", e=>{
  const rect=canvas.getBoundingClientRect();
  const px=((e.clientX-rect.left)*devicePixelRatio-canvas.width/2-off.x)/(scale*devicePixelRatio);
  const py=((e.clientY-rect.top)*devicePixelRatio-canvas.height/2-off.y)/(scale*devicePixelRatio);
  let best=null, bd=15;
  for(const n of nodes){ if(!visible(n)) continue; const d=Math.hypot(n.x-px,n.y-py);
    if(d<bd){ bd=d; best=n; } }
  selected=best; renderDetail(); draw(); });
function esc(v){ const e=document.createElement("span"); e.textContent=String(v??""); return e.innerHTML; }
function renderDetail(){
  const el=document.getElementById("detail");
  if(!selected){ el.innerHTML='<span class="sub">노드를 선택하면 증거 위치가 표시된다.</span>'; return; }
  const n=selected, recs=DATA.records[n.id]||[];
  el.innerHTML = '<div class="id">'+esc(n.id)+'</div>'
    + '<div>'+esc(n.kind)+(n.confidence==="candidate"?' <span class="cand">candidate — 소스 재확인 필요</span>':'')+'</div>'
    + '<ul>'+n.files.map(f=>'<li><b>'+esc(f.file)+':'+esc(f.line)+'</b>'
        +(f.confidence==="candidate"?' <span class="cand">?</span>':'')
        +(f.detail?' · '+esc(f.detail):'')+'</li>').join("")+'</ul>'
    + (recs.length? '<div class="records"><h3>관련 기록 (프로젝트 메모리)</h3><ul>'
        + recs.map(r=>'<li>'+esc(r.title)+' <span class="cand">['+esc(r.match)+']</span></li>').join("")+'</ul></div>' : '');
}
const legend=document.getElementById("legend");
for(const kind of Object.keys(COLORS)){
  const chip=document.createElement("button"); chip.type="button"; chip.className="chip on";
  chip.setAttribute("aria-pressed","true");
  chip.innerHTML='<i style="background:'+COLORS[kind]+'"></i>'+kind;
  chip.onclick=()=>{ active.has(kind)?active.delete(kind):active.add(kind);
    chip.classList.toggle("on"); chip.setAttribute("aria-pressed",String(active.has(kind)));
    selected=null; renderDetail(); draw(); };
  legend.appendChild(chip); }
document.getElementById("q").addEventListener("input", e=>{ query=e.target.value.trim().toLowerCase(); draw(); });
const picker=document.getElementById("nodeSelect");
for(const n of nodes.filter(n=>n.kind!=="file").sort((a,b)=>a.id.localeCompare(b.id))){
  const option=document.createElement("option"); option.value=n.id; option.textContent=n.id; picker.appendChild(option); }
picker.addEventListener("change", ()=>{ selected=byId[picker.value]||null; renderDetail(); draw(); });
document.getElementById("stat").textContent =
  DATA.counts.files_scanned+" files · "+DATA.counts.nodes+" nodes · "+DATA.counts.edges+" edges · "+DATA.revision;
loop();
</script>
</body>
</html>
"""


def build_view(root: str | os.PathLike[str]) -> str:
    state = graph_state(root)
    if state is None:
        raise GraphError("relation graph state missing — run `asgard map scan` first")
    records: dict[str, list[dict]] = {}
    for node in state["nodes"]:
        if node["kind"] == "file":
            continue
        found = related_records(root, node)
        if found:
            records[node["id"]] = [{"title": r.title, "file": r.file, "match": r.match} for r in found]
    payload = {
        "counts": state["counts"],
        "revision": state.get("revision", ""),
        "nodes": state["nodes"],
        "edges": state["edges"],
        "records": records,
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data)


def write_view(root: str | os.PathLike[str]) -> str:
    base = Path(root).resolve()
    path = _state_file(base, _VIEW_RELATIVE.name, create=True)
    _atomic_state_write(base, path, build_view(base))
    return str(path)
