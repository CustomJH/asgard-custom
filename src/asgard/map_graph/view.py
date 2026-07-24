"""자립형 그래프 뷰 — 외부 리소스 0 의 단일 HTML 로 관계 그래프를 그린다.

`asgard map`(bare) / `asgard map view` 가 연다. 산출물은 런타임 상태
(`.asgard/state/map-view.html`) 로, git 에 추적되지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
from importlib.resources import files
from pathlib import Path

from .bridge import related_records
from .graph import GraphError, _atomic_state_write, _state_file, graph_state

_VIEW_RELATIVE = Path(".asgard") / "state" / "map-view.html"

_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<link rel="icon" href="data:,">
<title>Asgard Map — 관계 그래프</title>
<style>
  :root{
    --vault:#0C0A07; --surface:#14110C; --surface-2:#1B160E; --surface-3:#241C11;
    --line:rgba(230,208,150,.10); --line-strong:rgba(230,208,150,.20);
    --gold:#C6A45E; --gold-lit:#E8C87E; --warn:#D2933F;
    --ink:#E9E0CA; --dim:#9C9179;
    --mono:"SF Mono",ui-monospace,"JetBrains Mono",Menlo,"Cascadia Code",Consolas,monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Segoe UI",Roboto,sans-serif;
  }
  *{box-sizing:border-box;margin:0}
  html{color-scheme:dark;-webkit-text-size-adjust:100%}
  body{background:var(--vault);color:var(--ink);font:14px/1.55 var(--sans);
       height:100vh;display:grid;grid-template-rows:auto minmax(0,1fr);overflow:hidden}
  button{font:inherit;color:inherit;cursor:pointer}
  .sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
      clip:rect(0,0,0,0);white-space:nowrap;border:0}
  input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--gold);outline-offset:1px}

  /* ── 헤더 — 브랜드 로고 + 카운트 계기 ── */
  header{display:flex;justify-content:space-between;align-items:center;gap:8px 22px;flex-wrap:wrap;
         padding:10px 18px;border-bottom:1px solid var(--line);background:var(--surface)}
  .brand{display:flex;align-items:center;gap:11px;min-width:0}
  .mark{color:var(--gold);flex:none}
  img.mark{height:42px;width:auto;display:block}
  h1{font:600 13px var(--mono);letter-spacing:.3em;color:var(--gold-lit)}
  .sub{font-size:11.5px;color:var(--dim);margin-top:1px}
  .stats{font:11.5px var(--mono);font-variant-numeric:tabular-nums;color:var(--dim);
         display:flex;gap:5px 14px;flex-wrap:wrap;align-items:baseline}
  .stats b{color:var(--ink);font-weight:500}
  .stats .rev{color:var(--dim)}

  main{display:grid;grid-template-columns:minmax(0,1fr) 360px;min-height:0}

  /* ── 무대 — 계기판 바닥(라디얼 글로우 + 24px 마이크로 그리드) ── */
  #stage{position:relative;min-height:0;background:
    radial-gradient(90% 75% at 50% 18%, rgba(198,164,94,.055), transparent 65%),
    repeating-linear-gradient(0deg, rgba(230,208,150,.028) 0, rgba(230,208,150,.028) 1px, transparent 1px, transparent 24px),
    repeating-linear-gradient(90deg, rgba(230,208,150,.028) 0, rgba(230,208,150,.028) 1px, transparent 1px, transparent 24px),
    var(--vault)}
  canvas{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab;touch-action:none}
  canvas:focus-visible{outline:2px solid var(--gold);outline-offset:-2px}
  .zoombar{position:absolute;top:12px;right:12px;display:flex;flex-direction:column;gap:6px}
  .zoombar button{width:44px;height:44px;display:flex;align-items:center;justify-content:center;padding:0;
    background:rgba(20,17,12,.88);border:1px solid var(--line-strong);border-radius:8px;color:var(--gold-lit);
    transition:border-color .15s ease,transform .12s ease}
  .zoombar button:hover{border-color:var(--gold)}
  .zoombar button:active{transform:scale(.96)}
  .hint{position:absolute;left:14px;bottom:8px;font:10.5px var(--mono);color:var(--dim);
        pointer-events:none;max-width:72%}
  #tip{position:absolute;left:0;top:0;z-index:5;pointer-events:none;background:rgba(12,10,7,.94);
       border:1px solid var(--line-strong);border-radius:7px;padding:6px 9px;
       font:11.5px var(--mono);max-width:260px;word-break:break-all}
  #tip .k{color:var(--dim);font-size:10px;margin-top:1px}

  /* ── 조작반 ── */
  aside{border-left:1px solid var(--line);background:var(--surface);min-height:0;overflow-y:auto;
        scrollbar-gutter:stable;padding:14px 16px 18px;display:flex;flex-direction:column;gap:12px}
  input[type=search],select{width:100%;background:var(--surface-2);border:1px solid var(--line-strong);
    border-radius:8px;color:var(--ink);font:12.5px var(--mono);padding:9px 11px;min-height:40px}
  input[type=search]::placeholder{color:var(--dim)}
  .qhint{font:11px var(--mono);color:var(--dim);margin-top:-6px}
  .sectitle{font:10px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold);margin-bottom:6px}

  #detail{border-top:1px solid var(--line);padding-top:12px;font-size:12.5px}
  .d-empty{color:var(--dim)}
  .d-empty code{font-family:var(--mono);color:var(--ink)}
  .d-kind{display:flex;align-items:center;gap:7px;font:11px var(--mono);color:var(--dim);margin-bottom:6px;flex-wrap:wrap}
  .d-kind i{width:9px;height:9px;border-radius:50%;flex:none}
  .d-deg{margin-left:auto;font-size:10.5px}
  .badge-cand{color:var(--warn);border:1px solid color-mix(in oklab,var(--warn) 45%,transparent);
              border-radius:5px;padding:1px 7px;font-size:10.5px}
  .d-id{font-family:var(--mono);font-size:13px;color:var(--gold-lit);word-break:break-all;
        user-select:all;margin-bottom:4px}
  .d-h{font:10px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold);margin:12px 0 4px}
  .d-ev,.d-rec{list-style:none}
  .d-ev li{padding:4px 0;border-bottom:1px solid var(--line);color:var(--dim);word-break:break-all;line-height:1.5}
  .d-ev li:last-child{border-bottom:0}
  .d-ev b{font:500 12px var(--mono);color:var(--ink)}
  .cand{color:var(--warn);font-weight:600}
  .d-det{color:var(--dim)}
  .d-rec li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 8px;
            padding:5px 0;border-bottom:1px solid var(--line);font-size:12px}
  .d-rec li:last-child{border-bottom:0}
  .d-rec .rt{color:var(--ink)}
  .d-rec .rm{color:var(--warn);font:10.5px var(--mono);align-self:start;
             border:1px solid color-mix(in oklab,var(--warn) 40%,transparent);border-radius:5px;padding:1px 6px}
  .d-rec .rf{grid-column:1/-1;color:var(--dim);font:11px var(--mono);word-break:break-all}
  .d-code{display:block;background:var(--surface-2);border:1px solid var(--line);border-radius:7px;
          padding:8px 10px;font:11.5px var(--mono);color:var(--ink);word-break:break-all;user-select:all}
  .d-rel{list-style:none}
  .d-rel li{border-bottom:1px solid var(--line)}
  .d-rel li:last-child{border-bottom:0}
  .d-rel button{display:flex;align-items:center;gap:7px;width:100%;background:none;border:0;
                padding:5px 0;text-align:left;font-size:12px;color:var(--ink);min-height:28px}
  .d-rel i{width:8px;height:8px;border-radius:50%;flex:none}
  .d-rel .rk{font:10px var(--mono);color:var(--dim);flex:none}
  .d-rel .rn{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .d-rel button:hover .rn{color:var(--gold-lit)}
  .d-rel .rv{margin-left:auto;font:10px var(--mono);color:var(--dim);flex:none;max-width:38%;
             overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .d-rel .more{padding:5px 0;color:var(--dim);font:11px var(--mono)}

  .chips{display:flex;flex-wrap:wrap;gap:6px}
  .chip{display:inline-flex;align-items:center;gap:6px;background:transparent;color:var(--dim);
        border:1px solid var(--line-strong);border-radius:999px;padding:5px 11px;min-height:30px;
        font:11px var(--mono);transition:border-color .15s ease,color .15s ease}
  .chip:hover{border-color:var(--gold)}
  .chip.on{color:var(--ink);border-color:color-mix(in oklab,var(--gold) 55%,transparent);
           background:color-mix(in oklab,var(--gold) 8%,transparent)}
  .chip i{width:8px;height:8px;border-radius:50%;flex:none;opacity:.35}
  .chip.on i{opacity:1}
  .chip .n{color:var(--dim);font-size:10px}
  .subhint{font:10.5px var(--mono);color:var(--dim);margin-top:7px}

  .ekl{list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:4px 14px;
       font:11px var(--mono);color:var(--dim)}
  .ekl li{display:flex;align-items:center;gap:7px;min-height:22px}
  .ekl li.zero{opacity:.35}
  .ekl svg{flex:none}
  .ekl b{margin-left:auto;color:var(--ink);font-weight:500;font-variant-numeric:tabular-nums}

  .foot{border-top:1px solid var(--line);padding-top:10px;color:var(--dim);font-size:11.5px;margin-top:auto}
  .foot code{font-family:var(--mono);color:var(--ink)}

  @media (max-width:1080px){
    main{grid-template-columns:minmax(0,1fr) 300px}
    aside{padding:12px 14px 16px}
  }
  @media (max-width:720px){
    body{display:block;height:auto;min-height:100vh;overflow:auto}
    main{display:block}
    #stage{height:58vh;min-height:340px}
    aside{border-left:0;border-top:1px solid var(--line-strong);overflow:visible}
    .zoombar{top:auto;bottom:12px}
    .hint{display:none}
    input[type=search],select{min-height:44px;font-size:13px}
    .chip{min-height:36px;padding:7px 13px}
  }
  @media (prefers-reduced-motion: reduce){
    *,*::before,*::after{transition:none!important;animation:none!important}
    html{scroll-behavior:auto}
  }
</style>
</head>
<body>
<header>
  <div class="brand">
    <!-- 구 삼중 아치 마크 — 정식 로고 교체로 보류(백업: ref/map-view-legacy-mark.svg)
    <svg class="mark" viewBox="0 0 120 96" width="27" height="22" aria-hidden="true">
      <path d="M18 90V52a42 42 0 0 1 84 0v38" fill="none" stroke="currentColor" stroke-width="7"/>
      <path d="M33 90V55a27 27 0 0 1 54 0v35" fill="none" stroke="currentColor" stroke-width="5.5"/>
      <path d="M48 90V58a12 12 0 0 1 24 0v32" fill="none" stroke="currentColor" stroke-width="4.5"/>
      <path d="M10 90h100" stroke="currentColor" stroke-width="7"/>
    </svg>
    -->
    <img class="mark" src="__LOGO__" alt="Asgard" onerror="this.hidden=true">
    <div>
      <h1>ASGARD MAP</h1>
      <p class="sub">관계 그래프 — 빈 원은 구문 미증명 후보, 단정 전 소스 확인</p>
    </div>
  </div>
  <p class="stats" id="stats"></p>
</header>
<main>
  <div id="stage">
    <canvas id="c" tabindex="0" role="application" aria-describedby="hint"
      aria-label="관계 그래프 캔버스 — 노드를 클릭하면 증거가 열린다. 화살표 키 이동, 더하기·빼기 줌, 0 전체 보기, Esc 해제. 캔버스 없이도 노드 선택 목록으로 탐색할 수 있다."></canvas>
    <div class="zoombar" role="group" aria-label="보기 조절">
      <button type="button" id="zoomIn" aria-label="확대"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M7.5 2.5v10M2.5 7.5h10" stroke="currentColor" stroke-width="1.6"/></svg></button>
      <button type="button" id="zoomOut" aria-label="축소"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M2.5 7.5h10" stroke="currentColor" stroke-width="1.6"/></svg></button>
      <button type="button" id="zoomFit" aria-label="전체 보기"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><circle cx="7.5" cy="7.5" r="4.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M7.5 .8v3M7.5 11.2v3M.8 7.5h3M11.2 7.5h3" stroke="currentColor" stroke-width="1.3"/></svg></button>
    </div>
    <p class="hint" id="hint">드래그 팬 · 휠·핀치 줌 · 노드 클릭 선택 · 키: 화살표 팬 / + − 줌 / 0 전체 / Esc 해제</p>
    <div id="tip" hidden></div>
  </div>
  <aside aria-label="그래프 조작과 상세">
    <div>
      <label class="sr" for="q">노드 검색</label>
      <input id="q" type="search" placeholder="노드 검색 — 이름·id" autocomplete="off" spellcheck="false">
    </div>
    <p class="qhint" id="qhint" hidden></p>
    <div>
      <label class="sr" for="nodeSelect">노드 선택 — 증거 보기</label>
      <select id="nodeSelect"></select>
    </div>
    <section id="detail" aria-live="polite"></section>
    <section>
      <h2 class="sectitle">종류 필터</h2>
      <div class="chips" id="legend" role="group" aria-label="노드 종류 필터"></div>
      <p class="subhint">클릭 = 토글 · Alt(⌥)+클릭 = 단독 보기 · 올리면 해당 종류만 밝게</p>
    </section>
    <section id="ekinds" aria-label="엣지 종류"></section>
    <p class="foot">깊은 추적 — <code>asgard map trace --from &lt;node-id&gt;</code></p>
  </aside>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("data").textContent);
const KIND_COLORS = { file:"#737D8C", route:"#E8C87E", page:"#EFA987", store:"#C9A7EF", composable:"#9FD0A8",
  component:"#C4A484", command:"#D98E4A", model:"#8FB6E8",
  db_access:"#96C08A", api_call:"#E38B8B", event:"#B99CE8", job:"#72C6C6", external_service:"#DD9AC2" };
const KIND_ORDER = ["route","page","component","store","composable","command","model","db_access","api_call","event","job","external_service","file"];
const EDGE_KINDS = ["declares","calls","touches","uses","emits"];
const EDGE_DASH = { declares:[], calls:[7,4], touches:[2,4], uses:[11,3,2,3], emits:[4,3,1,3] };
const FONT = '"SF Mono",Menlo,Consolas,monospace';
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const MOBILE = matchMedia("(max-width:720px)");
const stage = document.getElementById("stage");
const canvas = document.getElementById("c"), ctx = canvas.getContext("2d");
const tip = document.getElementById("tip");
const picker = document.getElementById("nodeSelect");
const legend = document.getElementById("legend");

const nodes = DATA.nodes.map((n,i)=>({ ...n,
  x: Math.cos(i*2.399963)*(60+Math.sqrt(i)*22), y: Math.sin(i*2.399963)*(60+Math.sqrt(i)*22),
  vx:0, vy:0 }));
const byId = Object.fromEntries(nodes.map(n=>[n.id,n]));
const edges = DATA.edges.filter(e=>byId[e.source]&&byId[e.target]);
const degree = {}; edges.forEach(e=>{ degree[e.source]=(degree[e.source]||0)+1; degree[e.target]=(degree[e.target]||0)+1; });
const kindCount = {}; nodes.forEach(n=>{ kindCount[n.kind]=(kindCount[n.kind]||0)+1; });
const edgeKindCount = {}; edges.forEach(e=>{ edgeKindCount[e.kind]=(edgeKindCount[e.kind]||0)+1; });
const topLabel = new Set(nodes.filter(n=>n.kind!=="file")
  .sort((a,b)=>(degree[b.id]||0)-(degree[a.id]||0)).slice(0,14).map(n=>n.id));

let off={x:0,y:0}, scale=1, active=new Set(KIND_ORDER.filter(k=>kindCount[k])), query="",
  selected=null, hover=null, neighbors=new Set(), bridges=new Set(), previewKind=null,
  userCam=false, hot = REDUCED ? 0 : 260;

function esc(v){ const e=document.createElement("span"); e.textContent=String(v??""); return e.innerHTML.replace(/"/g,"&quot;"); }
function radius(n){ return n.kind==="file" ? 3.2 : Math.min(11, 5+(degree[n.id]||0)*0.55); }
function matches(n){ return !query || (n.id+" "+n.name).toLowerCase().includes(query); }
// 노드 상태: 0 숨김(kind off) · 1 유령(검색 불일치) · 2 표시
function state(n){ if(!active.has(n.kind)) return 0; if(query && !matches(n)) return 1; return 2; }

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

function sizeCanvas(){
  canvas.width = stage.clientWidth*devicePixelRatio;
  canvas.height = stage.clientHeight*devicePixelRatio;
}
function fit(){
  if(!nodes.length) return;
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,seen=false;
  for(const n of nodes){ if(!active.has(n.kind)) continue; seen=true;
    if(n.x<x0)x0=n.x; if(n.x>x1)x1=n.x; if(n.y<y0)y0=n.y; if(n.y>y1)y1=n.y; }
  if(!seen) return;
  const bw=Math.max(60,x1-x0), bh=Math.max(60,y1-y0);
  scale=Math.max(.25, Math.min(2.5,
    Math.min(canvas.width*0.84/(bw*devicePixelRatio), canvas.height*0.8/(bh*devicePixelRatio))));
  off.x=-(x0+x1)/2*scale*devicePixelRatio;
  off.y=-(y0+y1)/2*scale*devicePixelRatio;
}

function strokeEdges(list, style, width){
  ctx.strokeStyle=style; ctx.lineWidth=width;
  for(const k of EDGE_KINDS){
    ctx.setLineDash(EDGE_DASH[k].map(v=>v/scale));
    ctx.beginPath();
    for(const e of list){ if(e.kind!==k) continue;
      const a=byId[e.source], b=byId[e.target];
      ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); }
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

function draw(){
  const w=canvas.width, h=canvas.height;
  ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,w,h);
  if(!nodes.length){
    ctx.textAlign="center"; ctx.font=(13*devicePixelRatio)+"px "+FONT;
    ctx.fillStyle="#E9E0CA"; ctx.fillText("그래프가 비어 있다", w/2, h/2-12*devicePixelRatio);
    ctx.fillStyle="#9C9179"; ctx.fillText("asgard map scan 으로 관계를 수집한다", w/2, h/2+14*devicePixelRatio);
    ctx.textAlign="left"; return;
  }
  ctx.translate(w/2+off.x, h/2+off.y); ctx.scale(scale*devicePixelRatio, scale*devicePixelRatio);
  ctx.textBaseline="middle";
  const focus=selected;
  // 월드 좌표 뷰포트 — 노드·라벨 패스는 화면 밖(여유 60)을 건너뛴다
  const vx0=(-w/2-off.x)/(scale*devicePixelRatio)-60, vy0=(-h/2-off.y)/(scale*devicePixelRatio)-60;
  const vx1=vx0+w/(scale*devicePixelRatio)+120, vy1=vy0+h/(scale*devicePixelRatio)+120;
  const inView=n=>n.x>vx0&&n.x<vx1&&n.y>vy0&&n.y<vy1;
  const lit=[], lit2=[], base=[], ghost=[], via=[], viaN={};
  for(const e of edges){ const a=byId[e.source], b=byId[e.target];
    const sa=state(a), sb=state(b);
    if(!sa||!sb){ // 파일이 필터로 꺼져도 파일 경유 연계(실제 구성)는 접점 스터브로 남긴다
      if(!sa && a.kind==="file" && sb===2){ via.push(e); viaN[a.id]=(viaN[a.id]||0)+1; }
      continue; }
    if(focus){ if(e.source===focus.id||e.target===focus.id) lit.push(e);
      else if(bridges.has(e.source)) lit2.push(e); // 선택 개념의 파일 경유 2-hop 구간
      else ghost.push(e); }
    else if(query && sa<2 && sb<2) ghost.push(e);
    else if(previewKind && a.kind!==previewKind && b.kind!==previewKind) ghost.push(e);
    else base.push(e); }
  strokeEdges(ghost, "rgba(156,145,121,.07)", 0.8/scale);
  strokeEdges(base, "rgba(156,145,121,.3)", 0.9/scale);
  strokeEdges(lit2, "rgba(232,200,126,.4)", 1.1/scale);
  strokeEdges(lit, "rgba(232,200,126,.75)", 1.5/scale);
  { // 은닉 파일 접점 — 연계 2개 이상만 의미가 있다(외줄 스터브 제외)
    const viaBase=[], viaLit=[];
    for(const e of via){ if(viaN[e.source]<2) continue;
      if(!focus) viaBase.push(e); else if(bridges.has(e.source)) viaLit.push(e); }
    if(viaBase.length||viaLit.length){
      ctx.setLineDash([2/scale,3.5/scale]);
      for(const [list,style,width] of [[viaBase,"rgba(156,145,121,.24)",0.8],[viaLit,"rgba(232,200,126,.55)",1.2]]){
        if(!list.length) continue;
        ctx.strokeStyle=style; ctx.lineWidth=width/scale; ctx.beginPath();
        for(const e of list){ const a=byId[e.source], b=byId[e.target];
          ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); }
        ctx.stroke(); }
      ctx.setLineDash([]);
      ctx.lineWidth=1/scale;
      for(const id in viaN){ if(viaN[id]<2) continue;
        if(focus && !bridges.has(id)) continue;
        const f=byId[id];
        ctx.strokeStyle = focus ? "rgba(232,200,126,.6)" : "rgba(156,145,121,.5)";
        ctx.beginPath(); ctx.arc(f.x,f.y,2.2,0,7); ctx.stroke(); }
    }
  }
  if(focus && lit.length){ // 방향(파일 → 개념)은 선택 시에만 화살촉으로 노출
    ctx.fillStyle="rgba(232,200,126,.8)";
    for(const e of lit){ const a=byId[e.source], b=byId[e.target];
      const dx=b.x-a.x, dy=b.y-a.y, d=Math.hypot(dx,dy)||1, ux=dx/d, uy=dy/d;
      const rr=radius(b)+2/scale, s=7/scale, tx=b.x-ux*rr, ty=b.y-uy*rr;
      ctx.beginPath(); ctx.moveTo(tx,ty);
      ctx.lineTo(tx-ux*s-uy*s*0.5, ty-uy*s+ux*s*0.5);
      ctx.lineTo(tx-ux*s+uy*s*0.5, ty-uy*s-ux*s*0.5);
      ctx.closePath(); ctx.fill(); } }
  for(const n of nodes){ const s=state(n); if(!s||!inView(n)) continue;
    const r=radius(n), dim=(s===1)||(focus&&n!==selected&&!neighbors.has(n.id))
      ||(previewKind&&n.kind!==previewKind);
    ctx.globalAlpha = dim ? .16 : 1;
    const col=KIND_COLORS[n.kind]||"#888888";
    ctx.beginPath(); ctx.arc(n.x,n.y,r,0,7);
    if(n.confidence==="candidate"){ ctx.strokeStyle=col; ctx.lineWidth=1.4/scale; ctx.stroke(); }
    else { ctx.fillStyle=col; ctx.fill(); }
    ctx.globalAlpha=1; }
  if(hover && hover!==selected){ ctx.strokeStyle="rgba(233,224,202,.6)"; ctx.lineWidth=1.2/scale;
    ctx.beginPath(); ctx.arc(hover.x,hover.y,radius(hover)+3/scale,0,7); ctx.stroke(); }
  if(selected){ ctx.strokeStyle="#E8C87E"; ctx.lineWidth=1.6/scale;
    ctx.beginPath(); ctx.arc(selected.x,selected.y,radius(selected)+3.5/scale,0,7); ctx.stroke(); }
  // 라벨 정책 — 기본 허브 14개, 검색 일치 30개, 줌인 시 개념 전체(1.4x)·파일까지(2.4x).
  // 우선순위(선택>호버>이웃>차수) 정렬 후 화면 공간 충돌 시 낮은 쪽을 접는다.
  const allConcept=scale>=1.4, allFiles=scale>=2.4;
  ctx.font=(11/scale).toFixed(2)+"px "+FONT;
  ctx.lineWidth=3/scale; ctx.strokeStyle="rgba(12,10,7,.85)";
  let qLabels=0;
  const cands=[];
  for(const n of nodes){ if(state(n)!==2||!inView(n)) continue;
    if(focus&&n!==selected&&!neighbors.has(n.id)) continue;
    const concept=n.kind!=="file";
    let show=n===selected||n===hover;
    if(!show&&focus&&concept&&neighbors.has(n.id)) show=true;
    if(!show&&concept&&(allConcept||topLabel.has(n.id))) show=true;
    if(!show&&!concept&&allFiles) show=true;
    if(!show&&query&&concept&&qLabels<30){ show=true; qLabels++; }
    if(!show) continue;
    const pri = n===selected ? 0 : n===hover ? 1 : (focus&&neighbors.has(n.id)) ? 2 : 3;
    cands.push({n, pri, deg:degree[n.id]||0, concept}); }
  cands.sort((a,b)=>a.pri-b.pri || b.deg-a.deg);
  const boxes=[], lh=13/scale;
  for(const c of cands){ const n=c.n;
    const t=n.name.length>26 ? n.name.slice(0,25)+"…" : n.name;
    const lx=n.x+radius(n)+5/scale;
    const x0=lx, x1=lx+ctx.measureText(t).width, y0=n.y-lh/2, y1=n.y+lh/2;
    let clash=false;
    for(const b of boxes){ if(x0<b.x1&&x1>b.x0&&y0<b.y1&&y1>b.y0){ clash=true; break; } }
    if(clash && c.pri>1) continue;
    boxes.push({x0,x1,y0,y1});
    ctx.strokeText(t,lx,n.y);
    ctx.fillStyle = n===selected ? "#E8C87E" : (c.concept ? "#E9E0CA" : "#9C9179");
    ctx.fillText(t,lx,n.y); }
  ctx.setTransform(1,0,0,1,0,0);
}
// 대규모 그래프는 프레임당 2틱으로 정착 벽시계를 절반으로 줄인다(물리 자체는 동일).
function loop(){ if(hot-- > 0){ tick(); if(nodes.length>400) tick(); if(!userCam) fit(); draw(); requestAnimationFrame(loop); } else { draw(); } }
let drawQueued=false;
function scheduleDraw(){ // 휠·팬·핀치·호버 폭주를 프레임당 1회로 코얼레싱
  if(drawQueued) return; drawQueued=true;
  requestAnimationFrame(()=>{ drawQueued=false; draw(); });
}

function renderDetail(){
  const el=document.getElementById("detail");
  if(!nodes.length){
    el.innerHTML='<p class="d-empty">그래프가 비어 있다 — <code>asgard map scan</code> 후 다시 연다.</p>'; return; }
  if(!selected){ el.innerHTML='<p class="d-empty">노드를 선택하면 file:line 증거가 나온다.</p>'; return; }
  const n=selected, recs=(DATA.records||{})[n.id]||[], col=KIND_COLORS[n.kind]||"#888888";
  let h='<div class="d-kind"><i style="background:'+col+'"></i>'+esc(n.kind)
    +(n.confidence==="candidate" ? ' <span class="badge-cand">candidate — 단정 전 소스 확인</span>' : '')
    +'<span class="d-deg">이웃 '+(degree[n.id]||0)+'</span></div>'
    +'<div class="d-id">'+esc(n.id)+'</div>'
    +'<h3 class="d-h">증거 '+n.files.length+'</h3>'
    +'<ul class="d-ev">'+n.files.map(f=>'<li><b>'+esc(f.file)+':'+esc(f.line)+'</b>'
      +(f.confidence==="candidate" ? ' <span class="cand">?</span>' : '')
      +(f.detail ? ' <span class="d-det">— '+esc(f.detail)+'</span>' : '')+'</li>').join("")+'</ul>';
  // 연계 노드 — 파일 증거를 공유하는 실제 구성(1-hop 파일에 갇히지 않는다)
  let rel=[];
  if(n.kind==="file"){
    rel=edges.filter(e=>e.source===n.id).map(e=>({o:byId[e.target], via:[n.name]}));
  } else {
    const bf=new Set(edges.filter(e=>e.target===n.id).map(e=>e.source));
    const acc={};
    for(const e of edges) if(bf.has(e.source)&&e.target!==n.id)
      (acc[e.target] ??= {o:byId[e.target], via:[]}).via.push(byId[e.source].name);
    rel=Object.values(acc);
  }
  rel.sort((a,b)=>KIND_ORDER.indexOf(a.o.kind)-KIND_ORDER.indexOf(b.o.kind)||a.o.name.localeCompare(b.o.name));
  if(rel.length){
    const cap=24;
    h+='<h3 class="d-h">연계 노드 '+rel.length+' — 파일 경유</h3><ul class="d-rel">'
      +rel.slice(0,cap).map(r=>{
        const vb=r.via[0].split("/").pop(), vt=r.via.length>1 ? vb+" +"+(r.via.length-1) : vb;
        return '<li><button type="button" data-nid="'+esc(r.o.id)+'" title="'+esc(r.via.join(", "))+'">'
          +'<i style="background:'+(KIND_COLORS[r.o.kind]||"#888888")+'"></i>'
          +'<span class="rk">'+esc(r.o.kind)+'</span><span class="rn">'+esc(r.o.name)+'</span>'
          +'<span class="rv">'+esc(vt)+'</span></button></li>'; }).join("")
      +(rel.length>cap ? '<li class="more">+'+(rel.length-cap)+' — trace 로 전체 추적</li>' : '')+'</ul>';
  }
  if(recs.length) h+='<h3 class="d-h">관련 기록 — 프로젝트 메모리</h3><ul class="d-rec">'
    +recs.map(r=>'<li><span class="rt">'+esc(r.title)+'</span><span class="rm">'+esc(r.match)+'</span>'
      +'<span class="rf">'+esc(r.file)+'</span></li>').join("")+'</ul>';
  h+='<h3 class="d-h">추적</h3><code class="d-code">asgard map trace --from '+esc(n.id)+'</code>';
  el.innerHTML=h;
}
document.getElementById("detail").addEventListener("click", e=>{
  const b=e.target.closest("[data-nid]"); if(!b) return;
  const n=byId[b.dataset.nid]; if(!n) return;
  ensureKind(n.kind); centerOn(n); select(n);
});
function select(n, scrollTo){
  selected=n||null; neighbors=new Set(); bridges=new Set();
  if(selected){
    for(const e of edges){
      if(e.source===selected.id) neighbors.add(e.target);
      if(e.target===selected.id){ neighbors.add(e.source);
        if(byId[e.source].kind==="file") bridges.add(e.source); } }
    // 실제 연계 — 같은 파일 증거를 공유하는 개념(파일 경유 2-hop)까지 이웃으로 편입
    if(bridges.size) for(const e of edges)
      if(bridges.has(e.source) && e.target!==selected.id) neighbors.add(e.target);
  }
  picker.value = selected && selected.kind!=="file" ? selected.id : "";
  renderDetail(); draw();
  if(selected && scrollTo && MOBILE.matches)
    document.getElementById("detail").scrollIntoView({behavior:REDUCED?"auto":"smooth", block:"nearest"});
}
function centerOn(n){ userCam=true;
  off.x=-n.x*scale*devicePixelRatio; off.y=-n.y*scale*devicePixelRatio; }

// ── 조작반 구성 ──
(function(){
  const c=DATA.counts||{};
  document.getElementById("stats").innerHTML =
    '<span><b>'+esc(c.files_scanned??0)+'</b> files</span><span><b>'+esc(c.evidence??0)+'</b> evidence</span>'
    +'<span><b>'+esc(c.nodes??nodes.length)+'</b> nodes</span><span><b>'+esc(c.edges??edges.length)+'</b> edges</span>'
    +(DATA.revision ? '<span class="rev" title="'+esc(DATA.revision)+'">rev '+esc((s=>s.includes(":")?s.split(":").pop().slice(0,8):s.slice(0,10))(String(DATA.revision)))+'</span>' : '');
  for(const k of KIND_ORDER){ if(!kindCount[k]) continue;
    const chip=document.createElement("button"); chip.type="button"; chip.className="chip on";
    chip.dataset.kind=k; chip.setAttribute("aria-pressed","true");
    chip.innerHTML='<i style="background:'+(KIND_COLORS[k]||"#888888")+'"></i>'+esc(k)+' <span class="n">'+kindCount[k]+'</span>';
    chip.onclick=e=>{
      if(e.altKey){ soloKind(k); return; }
      if(active.has(k)) active.delete(k); else active.add(k);
      syncChips();
      if(selected && !active.has(selected.kind)) select(null); else draw(); };
    // 호버 미리보기 — 해당 종류만 밝혀 색만으로 헷갈리는 구분을 즉석에서 푼다(터치는 무시)
    chip.addEventListener("pointerenter", e=>{
      if(e.pointerType==="touch") return; previewKind=k; scheduleDraw(); });
    chip.addEventListener("pointerleave", ()=>{
      if(previewKind===k){ previewKind=null; scheduleDraw(); } });
    legend.appendChild(chip); }
  document.getElementById("ekinds").innerHTML =
    '<h2 class="sectitle">엣지 언어</h2><ul class="ekl">'+EDGE_KINDS.map(k=>{
      const d=EDGE_DASH[k].join(" ");
      return '<li'+(edgeKindCount[k]?'':' class="zero"')+'>'
        +'<svg viewBox="0 0 28 6" width="28" height="6" aria-hidden="true"><line x1="1" y1="3" x2="27" y2="3" stroke="#C6A45E" stroke-width="1.6"'
        +(d?' stroke-dasharray="'+d+'"':'')+'></line></svg>'
        +esc(k)+' <b>'+(edgeKindCount[k]||0)+'</b></li>'; }).join("")+'</ul>';
})();
function syncChips(){
  for(const c of legend.children){ const on=active.has(c.dataset.kind);
    c.classList.toggle("on",on); c.setAttribute("aria-pressed",String(on)); }
}
function soloKind(k){ // 단독 보기 — 이미 단독이면 전체 복귀
  const all=KIND_ORDER.filter(x=>kindCount[x]);
  active = (active.size===1 && active.has(k)) ? new Set(all) : new Set([k]);
  syncChips();
  if(selected && !active.has(selected.kind)) select(null); else draw();
}
function ensureKind(k){ if(!active.has(k)){ active.add(k); syncChips(); } }
function buildOptions(){
  const cur=picker.value; picker.innerHTML="";
  const o0=document.createElement("option"); o0.value=""; o0.textContent="노드 선택 — 증거 보기";
  picker.appendChild(o0);
  for(const n of nodes.filter(n=>n.kind!=="file"&&matches(n)).sort((a,b)=>a.id.localeCompare(b.id))){
    const o=document.createElement("option"); o.value=n.id; o.textContent=n.id; picker.appendChild(o); }
  picker.value=cur;
}
picker.addEventListener("change", ()=>{
  const n=byId[picker.value]||null;
  if(n){ ensureKind(n.kind); centerOn(n); }
  select(n);
});
const qEl=document.getElementById("q"), qHint=document.getElementById("qhint");
qEl.addEventListener("input", ()=>{
  query=qEl.value.trim().toLowerCase(); buildOptions();
  if(query){ const m=nodes.filter(n=>active.has(n.kind)&&matches(n)).length;
    qHint.hidden=false;
    qHint.textContent = m ? m+"개 일치 — Enter 로 첫 노드 선택" : "일치하는 노드가 없다"; }
  else qHint.hidden=true;
  draw();
});
qEl.addEventListener("keydown", e=>{
  if(e.key!=="Enter"||!query) return;
  const n=nodes.find(n=>n.kind!=="file"&&active.has(n.kind)&&matches(n));
  if(n){ centerOn(n); select(n); }
});

// ── 카메라: 휠(커서 앵커)·핀치·드래그·키보드 ──
function zoomAt(px,py,ns){
  ns=Math.max(.25,Math.min(4,ns));
  const wx=(px-canvas.width/2-off.x)/(scale*devicePixelRatio);
  const wy=(py-canvas.height/2-off.y)/(scale*devicePixelRatio);
  scale=ns;
  off.x=px-canvas.width/2-wx*scale*devicePixelRatio;
  off.y=py-canvas.height/2-wy*scale*devicePixelRatio;
  userCam=true; scheduleDraw();
}
canvas.addEventListener("wheel", e=>{ e.preventDefault();
  const r=canvas.getBoundingClientRect();
  zoomAt((e.clientX-r.left)*devicePixelRatio,(e.clientY-r.top)*devicePixelRatio,
    scale*(e.deltaY<0?1.12:0.9)); }, {passive:false});
document.getElementById("zoomIn").onclick=()=>zoomAt(canvas.width/2,canvas.height/2,scale*1.25);
document.getElementById("zoomOut").onclick=()=>zoomAt(canvas.width/2,canvas.height/2,scale*0.8);
document.getElementById("zoomFit").onclick=()=>{ userCam=false; fit(); draw(); };

function hitTest(e){
  const r=canvas.getBoundingClientRect();
  const px=((e.clientX-r.left)*devicePixelRatio-canvas.width/2-off.x)/(scale*devicePixelRatio);
  const py=((e.clientY-r.top)*devicePixelRatio-canvas.height/2-off.y)/(scale*devicePixelRatio);
  let best=null, bd=9/scale;
  for(const n of nodes){ if(state(n)!==2) continue;
    const d=Math.hypot(n.x-px,n.y-py)-radius(n);
    if(d<bd){ bd=d; best=n; } }
  return best;
}
function showTip(e,n){
  tip.innerHTML='<div>'+esc(n.name)+'</div><div class="k">'+esc(n.kind)
    +(n.confidence==="candidate" ? ' · 후보 — 단정 전 소스 확인' : '')+'</div>';
  tip.hidden=false; moveTip(e);
}
function moveTip(e){
  const r=stage.getBoundingClientRect();
  let x=e.clientX-r.left+14, y=e.clientY-r.top+14;
  x=Math.min(x, r.width-tip.offsetWidth-8); y=Math.min(y, r.height-tip.offsetHeight-8);
  tip.style.left=x+"px"; tip.style.top=y+"px";
}
const pointers=new Map(); let pinch=null, downPt=null, moved=0;
canvas.addEventListener("pointerdown", e=>{
  canvas.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if(pointers.size===2){ const p=[...pointers.values()];
    pinch={d:Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)||1, s:scale}; downPt=null; }
  else { downPt={x:e.clientX,y:e.clientY}; moved=0; }
});
canvas.addEventListener("pointermove", e=>{
  if(pointers.size){
    const prev=pointers.get(e.pointerId); if(!prev) return;
    if(pointers.size===1 && downPt){
      moved+=Math.abs(e.clientX-prev.x)+Math.abs(e.clientY-prev.y);
      if(moved>4){ off.x+=(e.clientX-prev.x)*devicePixelRatio; off.y+=(e.clientY-prev.y)*devicePixelRatio;
        userCam=true; canvas.style.cursor="grabbing"; scheduleDraw(); } }
    pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pinch && pointers.size===2){ const p=[...pointers.values()];
      const d=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)||1, r=canvas.getBoundingClientRect();
      zoomAt(((p[0].x+p[1].x)/2-r.left)*devicePixelRatio, ((p[0].y+p[1].y)/2-r.top)*devicePixelRatio,
        pinch.s*d/pinch.d); }
    return;
  }
  const n=hitTest(e);
  if(n!==hover){ hover=n; scheduleDraw(); }
  canvas.style.cursor = hover ? "pointer" : "grab";
  if(hover){ showTip(e,hover); } else tip.hidden=true;
});
function endPointer(e){
  if(!pointers.has(e.pointerId)) return;
  pointers.delete(e.pointerId);
  if(pointers.size<2) pinch=null;
  canvas.style.cursor="grab";
  if(downPt && moved<=4 && e.type==="pointerup") select(hitTest(e), true);
  downPt=null;
}
canvas.addEventListener("pointerup", endPointer);
canvas.addEventListener("pointercancel", endPointer);
canvas.addEventListener("pointerleave", ()=>{ if(hover){ hover=null; tip.hidden=true; draw(); } });
canvas.addEventListener("keydown", e=>{
  const st=48*devicePixelRatio; let done=true;
  if(e.key==="ArrowLeft"){ off.x+=st; userCam=true; }
  else if(e.key==="ArrowRight"){ off.x-=st; userCam=true; }
  else if(e.key==="ArrowUp"){ off.y+=st; userCam=true; }
  else if(e.key==="ArrowDown"){ off.y-=st; userCam=true; }
  else if(e.key==="+"||e.key==="=") zoomAt(canvas.width/2,canvas.height/2,scale*1.25);
  else if(e.key==="-"||e.key==="_") zoomAt(canvas.width/2,canvas.height/2,scale*0.8);
  else if(e.key==="0"){ userCam=false; fit(); }
  else if(e.key==="Escape") select(null);
  else done=false;
  if(done){ e.preventDefault(); draw(); }
});

new ResizeObserver(()=>{ sizeCanvas(); if(!userCam) fit(); draw(); }).observe(stage);
sizeCanvas();
if(REDUCED){ // 모션 축소 — 애니메이션 없이 즉석 정착(시간 예산 450ms) 후 정적 렌더
  const t0=performance.now(); let i=0;
  while(i<260 && performance.now()-t0<450){ tick(); i++; }
}
fit(); buildOptions(); renderDetail(); loop();
</script>
</body>
</html>
"""


def _logo_data_uri() -> str:
    """위그드라실 엠블럼(yggdrasil-mark.png)을 데이터 URI 로 — 실패 시 빈 값(img 는 onerror 로 숨김)."""
    try:
        raw = (files("asgard") / "assets" / "yggdrasil-mark.png").read_bytes()
    except Exception:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


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
    return _TEMPLATE.replace("__DATA__", data).replace("__LOGO__", _logo_data_uri())


def write_view(root: str | os.PathLike[str]) -> str:
    base = Path(root).resolve()
    path = _state_file(base, _VIEW_RELATIVE.name, create=True)
    _atomic_state_write(base, path, build_view(base))
    return str(path)
