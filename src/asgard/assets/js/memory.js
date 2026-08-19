"use strict";
/* 기억 화면 — 껍데기와 성좌.
 *
 * 옛 위그드라실 창(`assets/memory_dashboard.html`)은 자기 서버(8765)로 뜨는 별개의 페이지였다.
 * 옮기면서 버린 것은 껍데기뿐이다 — 자체 헤더·스플래시·폭 조절·해시 라우팅·⌘K 팔레트·언어 전환은
 * 스튜디오가 이미 갖고 있고, 두 벌이면 ⌘K 가 두 곳에서 잡힌다. 관측 표면(탭 일곱, 상태 넷,
 * 물리 시뮬 성좌)은 그대로 왔다.
 *
 * **색 값은 이 파일에 없다.** 옛 캔버스는 색을 직접 적었고(24자리), 그래서 라이트 테마로 넘어가면
 * 화면만 밝아지고 성좌는 검게 남았다. 지금은 `ui/memory.css` 의 `--mem-*` 토큰을
 * `getComputedStyle` 로 읽어 그리고, `data-theme` 이 바뀌면 캐시를 버리고 다시 그린다(`watchTheme`).
 * 알파를 섞던 자리는 `ctx.globalAlpha` 로 옮겼다 — 색 문자열을 조립하지 않으면 값이 새어 들어올
 * 자리도 없다.
 *
 * 파일이 셋인 이유는 크기다. `health.py` 의 크기 게이트가 1000행을 하드 블록으로 잡고 옛 스크립트는
 * 2,172행이었다. 이 파일이 창구·공용 도구·껍데기·성좌를, `memory-search.js` 가 개요·서고·검색을,
 * `memory-log.js` 가 전달·정리·연대기·열지도를 갖는다. 개요가 서고 쪽에 붙은 것은 크기 때문이고,
 * 둘이 같은 자료(`catalog`·`usage`)를 읽어서이기도 하다. 셋은 `window.MEM` 한 곳에서 만난다.
 *
 * 판은 `MEM.panels[<탭>] = { html, render }` 로 등록된다. 스크립트가 `<head>` 에서 defer 없이
 * 실리므로 어느 파일도 적재 시점에 DOM 을 건드리지 않는다 — 등록만 하고, 그리기는 스튜디오가
 * `initMemoryView()` 를 부른 뒤에 시작한다.
 */
(function(){
const MEM = window.MEM = window.MEM || {};
MEM.panels = MEM.panels || {};

/* ── 공용 도구 — 세 파일이 같은 것을 쓴다 ─────────────────────────────────────── */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
const truncate = (s, n) => { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
let REDUCED = false;
try{ REDUCED = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches; }catch(e){}

function debounce(fn, ms){
  let t = null;
  return function(){ const a = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, a), ms); };
}
// 한글 조합 중에는 검색을 걸지 않는다 — 자모 단위로 질의가 나가면 결과가 튄다.
function bindImeSafeSearch(input, ms, onSearch){
  if(!input) return;
  let composing = false, justCommitted = false;
  const run = debounce((v) => onSearch(v), ms);
  input.addEventListener("compositionstart", () => { composing = true; });
  input.addEventListener("compositionend", () => {
    composing = false; justCommitted = true;
    onSearch(input.value);
    setTimeout(() => { justCommitted = false; }, 0);
  });
  input.addEventListener("input", (e) => {
    if(composing || e.isComposing || justCommitted) return;
    run(input.value);
  });
}
// 목록을 다시 그리면 포커스와 커서가 날아간다 — 그리기 전에 잡아 두고 그린 뒤 되돌린다.
function captureFocus(ids){
  const a = document.activeElement;
  if(!a || ids.indexOf(a.id) < 0) return null;
  return { id: a.id, start: a.selectionStart, end: a.selectionEnd };
}
function restoreFocus(f){
  if(!f) return;
  const el = $(f.id);
  if(!el) return;
  el.focus();
  if(typeof el.setSelectionRange === "function"){ try{ el.setSelectionRange(f.start, f.end); }catch(e){} }
}
function daysAgo(iso){
  if(!iso) return "";
  const d = new Date(iso + (iso.length <= 10 ? "T00:00:00" : ""));
  if(isNaN(d)) return esc(iso);
  const n = Math.floor((Date.now() - d.getTime()) / 86400000);
  return n <= 0 ? "오늘" : n + "일 전";
}
function fmtBytes(n){
  n = Number(n) || 0;
  if(n < 1024) return n + " B";
  if(n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

/* ── 창구 — 다섯 문 전부 `/api/memory/` 아래다 ────────────────────────────────── */

async function api(door, params){
  const q = params ? "?" + new URLSearchParams(params).toString() : "";
  const res = await fetch("/api/memory/" + door + q, { cache: "no-store" });
  if(!res.ok) throw new Error(door + " " + res.status);
  return await res.json();
}
const fetchSnapshot = () => api("snapshot");
const fetchInjection = () => api("injection");
const fetchSearch = (q, k) => api("search", { q: q, k: String(k || 12) });
const fetchPage = (slug) => api("page", { slug: slug });
const fetchLog = (p) => api("log", p);

/* ── 상태 넷 — 로딩 · 빈 서고 · 오류 · 결과 없음 ─────────────────────────────── */

const skeleton = (rows) => '<div class="mem-skel" aria-hidden="true">'
  + new Array(rows || 3).fill('<span class="ak-skeleton"></span>').join("") + '</div>';
const empty = (msg) => '<p class="ak-empty mem-empty">' + esc(msg) + '</p>';
// 빈 서고는 빈 표가 아니라 다음 손짓이다 — 첫 페이지를 만드는 한 줄을 같이 준다.
const onboard = (msg) => '<div class="mem-onboard"><p>' + esc(msg)
  + '</p><code>asgard memory add "오늘 결정한 것 — 근거 한 줄"</code></div>';
const errorCard = (why) => '<div class="ak-error mem-err" role="alert">'
  + '<strong class="ak-error__title">기억을 불러오지 못했어요</strong><span>' + esc(why)
  + ' — 서고가 살아 있는지 <code>asgard memory list</code> 로 확인해 보세요.</span>'
  + '<button type="button" class="ak-btn" data-mem="retry">다시 시도</button></div>';

/* ── 종류 — 색과 모양 두 축으로 구분한다(색만으로는 구분되지 않는 눈이 있다) ──── */

const KINDS = ["note", "user", "decision", "insight", "reference", "feedback"];
const SHAPE = { note:"circle", user:"tri", decision:"diamond", insight:"hexagon", reference:"rect", feedback:"tridown" };
const KIND_KO = { note:"노트", user:"사용자", decision:"결정", insight:"통찰", reference:"참조", feedback:"피드백" };
const kindVar = (k) => "var(--mem-kind-" + (SHAPE[k] ? k : "note") + ")";
const kindName = (k) => KIND_KO[k] || k;
// 종류 표식 — 채움은 style 로 넣는다. 표현 속성 `fill="var(--x)"` 는 해석되지 않는다.
function swatch(kind){
  const f = ' style="fill:' + kindVar(kind) + '"';
  const inner = {
    circle: '<circle cx="7" cy="7" r="5"' + f + '/>',
    rect: '<rect x="2" y="3.5" width="10" height="7"' + f + '/>',
    diamond: '<path d="M7 1.5L12.5 7 7 12.5 1.5 7z"' + f + '/>',
    hexagon: '<path d="M7 1.5l4.8 2.75v5.5L7 12.5 2.2 9.75v-5.5z"' + f + '/>',
    tri: '<path d="M7 2l5.5 10h-11z"' + f + '/>',
    tridown: '<path d="M1.5 2h11L7 12z"' + f + '/>',
  }[SHAPE[kind] || "circle"];
  return '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">' + inner + '</svg>';
}
const kchip = (k) => '<span class="mem-kchip">' + swatch(k) + esc(k) + '</span>';
const slugBtn = (slug) => '<button type="button" class="mem-link mono" data-mem="goto" data-slug="'
  + esc(slug) + '">' + esc(slug) + '</button>';

// 작업 갈래 — 연대기·활동·개요가 같은 색과 글리프를 쓴다.
const OPS = {
  add:    { v:"var(--ok)",     d:"M5 1.5v7M1.5 5h7" },
  ingest: { v:"var(--info)",   d:"M5 1v5M2.6 3.9L5 6.3l2.4-2.4M1.5 8.5h7" },
  merge:  { v:"var(--gold)",   d:"M1.5 1.5L5 5l3.5-3.5M5 5v3.5" },
  remove: { v:"var(--danger)", d:"M2 2l6 6M8 2L2 8" },
  other:  { v:"var(--muted)",  d:"M2.5 5h5" },
};
const opStyle = (op) => OPS[String(op || "").split(":")[0]] || OPS.other;
const opGlyph = (op) => '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="'
  + opStyle(op).d + '" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>';
function logRow(l){
  return '<li><span class="ts">' + esc(l.ts) + '</span>'
    + '<span class="op" style="color:' + opStyle(l.op).v + '">' + opGlyph(l.op) + ' ' + esc(l.op) + '</span>'
    + '<span class="sl">' + slugBtn(l.slug)
    + (l.detail ? ' <span class="di">' + esc(l.detail) + '</span>' : "") + '</span></li>';
}

/* ── 화면 상태 ──────────────────────────────────────────────────────────────── */

const TABS = [["overview","개요"], ["graph","성좌"], ["library","서고"], ["inject","전달"],
  ["tend","정리"], ["chronicle","연대기"], ["activity","활동"]];
const APP = { mounted:false, active:"overview", loaded:{}, snap:null, inj:null,
  graphReady:false, graphSig:"", kind:"", op:"", q:"", sort:"updated", day:"",
  chronOffset:0, inline:null, poll:null };

/* ── 캔버스 물감 — 값은 CSS 가 갖고 여기서는 이름만 읽는다 ────────────────────── */

let PAINT = null;
function paint(){
  if(PAINT) return PAINT;
  // 캔버스에서 읽는다 — 토큰이 `.mem` 에 걸려 있어 문서 뿌리에서는 안 보인다(map-draw.js 와 같은 규율).
  const cs = getComputedStyle(G.canvas || document.documentElement);
  const v = (n) => (cs.getPropertyValue(n) || "").trim();
  PAINT = { grid:v("--mem-grid"), link:v("--mem-link"), sem:v("--mem-sem"), dead:v("--mem-dead"),
    orphan:v("--mem-orphan"), hit:v("--mem-hit"), labelBg:v("--mem-label-bg"),
    labelLine:v("--mem-label-line"), labelInk:v("--mem-label-ink"), labelDim:v("--mem-label-dim"),
    faint:v("--mem-empty-ink"), kind:{} };
  KINDS.forEach((k) => { PAINT.kind[k] = v("--mem-kind-" + k); });
  return PAINT;
}
// 테마가 바뀌어도 캔버스는 스스로 다시 칠하지 않는다 — CSS 는 DOM 만 따라간다.
function watchTheme(){
  const repaint = () => { PAINT = null; if(G.ctx) renderGraph(); };
  new MutationObserver(repaint).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-theme"] });
  try{ matchMedia("(prefers-color-scheme: dark)").addEventListener("change", repaint); }catch(e){}
}

/* ══ 성좌 — 캔버스 물리 시뮬 ═══════════════════════════════════════════════════
   물리 값(노드수 적응 반발력, 스프링 목표 100px, 틱 냉각 감쇠, RMS 파킹)은 옛 창에서
   실전 검증된 것을 그대로 옮겼다. 바뀐 것은 색을 읽는 자리뿐이다. */

const G = { nodes:[], liveEdges:[], deadEdges:[], adj:{}, canvas:null, ctx:null, raf:null,
  running:false, bound:false, panX:0, panY:0, zoom:1, drag:null, mx:-1e4, my:-1e4,
  tick:0, quiet:0, filters:{}, term:"", sel:null };
const FONT_SANS = '-apple-system, "Apple SD Gothic Neo", "Segoe UI", sans-serif';
const FONT_MONO = '"SF Mono", ui-monospace, Menlo, monospace';

function angleOf(str){
  let h = 0;
  for(let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return (h % 360) * Math.PI / 180;
}
function shapePath(ctx, x, y, r, shape){
  ctx.beginPath();
  if(shape === "rect"){ ctx.rect(x - r, y - r * 0.75, r * 2, r * 1.5); }
  else if(shape === "diamond"){ ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); }
  else if(shape === "hexagon"){
    for(let i = 0; i < 6; i++){
      const a = (Math.PI / 3) * i - Math.PI / 2;
      const hx = x + r * Math.cos(a), hy = y + r * Math.sin(a);
      if(i === 0) ctx.moveTo(hx, hy); else ctx.lineTo(hx, hy);
    }
    ctx.closePath();
  }
  else if(shape === "tri"){ ctx.moveTo(x, y - r); ctx.lineTo(x + r * 0.9, y + r * 0.75); ctx.lineTo(x - r * 0.9, y + r * 0.75); ctx.closePath(); }
  else if(shape === "tridown"){ ctx.moveTo(x, y + r); ctx.lineTo(x + r * 0.9, y - r * 0.75); ctx.lineTo(x - r * 0.9, y - r * 0.75); ctx.closePath(); }
  else { ctx.arc(x, y, r, 0, Math.PI * 2); }
}
const visNodes = () => G.nodes.filter((n) => G.filters[n.kind]);
const nodeMatches = (n) => (n.title + " " + n.slug).toLowerCase().includes(G.term);

function tickPhysics(){
  const nodes = G.nodes, count = nodes.length;
  G.tick++;
  const damping = 0.9 - Math.min(0.4, G.tick / 1500);
  const repulsion = count > 1000 ? 3000 : count > 100 ? 2000 : count > 50 ? 1200 : 800;
  const attraction = count > 100 ? 0.002 : 0.005;
  const gravity = count > 1000 ? 0.012 : count > 100 ? 0.005 : 0.01;
  const cap = count > 1000 ? 6 : count > 200 ? 12 : 24;
  const map = {};
  nodes.forEach((n) => { map[n.slug] = n; });
  for(let i = 0; i < count; i++){
    const n = nodes[i];
    if(G.drag === n) continue;
    let fx = 0, fy = 0;
    for(let j = 0; j < count; j++){
      if(i === j) continue;
      const dx = n.x - nodes[j].x, dy = n.y - nodes[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = repulsion / (dist * dist);
      fx += (dx / dist) * force; fy += (dy / dist) * force;
    }
    fx -= n.x * gravity; fy -= n.y * gravity;
    n.vx = Math.max(-cap, Math.min(cap, (n.vx + fx) * damping));
    n.vy = Math.max(-cap, Math.min(cap, (n.vy + fy) * damping));
  }
  G.liveEdges.forEach((e) => {
    const s = map[e.from], t = map[e.to];
    if(!s || !t) return;
    const dx = t.x - s.x, dy = t.y - s.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const f = (dist - 100) * attraction; // 스프링 목표 길이 100px
    const fx = (dx / dist) * f, fy = (dy / dist) * f;
    if(G.drag !== s){ s.vx += fx; s.vy += fy; }
    if(G.drag !== t){ t.vx -= fx; t.vy -= fy; }
  });
  let ke = 0;
  nodes.forEach((n) => {
    if(G.drag === n) return;
    n.x += n.vx; n.y += n.vy;
    ke += n.vx * n.vx + n.vy * n.vy;
  });
  const rms = count > 0 ? Math.sqrt(ke / count) : 0;
  if(rms < 0.05 && G.tick > 60 && !G.drag) G.quiet++; else G.quiet = 0;
}
function simLoop(){
  if(!G.running) return;
  tickPhysics();
  renderGraph();
  if(G.quiet > 30){ G.raf = null; return; } // 정착하면 rAF 를 놓는다 — 멈춘 그림에 CPU 를 안 태운다
  G.raf = requestAnimationFrame(simLoop);
}
function wakeSim(){ G.quiet = 0; if(G.running && !G.raf) G.raf = requestAnimationFrame(simLoop); }
function canvasSize(){
  const dpr = window.devicePixelRatio || 1;
  return { w: G.canvas.width / dpr, h: G.canvas.height / dpr };
}
function resizeCanvas(){
  if(!G.canvas || !G.canvas.parentElement) return;
  const dpr = window.devicePixelRatio || 1;
  const r = G.canvas.parentElement.getBoundingClientRect();
  G.canvas.width = r.width * dpr; G.canvas.height = r.height * dpr;
  G.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function renderGraph(){
  const ctx = G.ctx, canvas = G.canvas;
  if(!ctx || !canvas) return;
  const P = paint();
  const { w, h } = canvasSize();
  ctx.clearRect(0, 0, w, h);

  ctx.save(); // 미세 그리드 — 계기판 바닥. 옅기는 globalAlpha 가 든다.
  ctx.globalAlpha = 0.35; ctx.strokeStyle = P.grid; ctx.lineWidth = 0.5;
  for(let gx = 0; gx < w; gx += 24){ ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke(); }
  for(let gy = 0; gy < h; gy += 24){ ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke(); }
  ctx.restore();

  if(!G.nodes.length){
    ctx.fillStyle = P.faint; ctx.font = "14px " + FONT_SANS; ctx.textAlign = "center";
    ctx.fillText("아직 별이 없어요 — asgard memory add 로 첫 기억을 남겨 보세요", w / 2, h / 2);
    return;
  }

  ctx.save();
  ctx.translate(G.panX, G.panY);
  ctx.scale(G.zoom, G.zoom);

  const map = {};
  G.nodes.forEach((n) => { map[n.slug] = n; });
  const searching = G.term.length > 0;
  const dense = visNodes().length > 40;
  const labelZoom = dense ? 1.5 : 0.5;
  const edgeLabelZoom = dense ? 2.5 : 1.2;
  const selId = G.sel ? G.sel.slug : null;

  let hoverId = null; // 호버 탐지 — 역순 선형(위에 그려진 것이 먼저 잡힌다)
  if(!G.drag){
    const rect = canvas.getBoundingClientRect();
    const hx = (G.mx - rect.left - G.panX) / G.zoom, hy = (G.my - rect.top - G.panY) / G.zoom;
    for(let i = G.nodes.length - 1; i >= 0; i--){
      const n = G.nodes[i];
      if(!G.filters[n.kind]) continue;
      const dx = n.x - hx, dy = n.y - hy;
      if(dx * dx + dy * dy < n.r * n.r + 25){ hoverId = n.slug; break; }
    }
  }
  const focusId = selId || hoverId;

  G.liveEdges.forEach((e) => {
    const s = map[e.from], t = map[e.to];
    if(!s || !t) return;
    if(!G.filters[s.kind] || !G.filters[t.kind]) return;
    const dim = searching && !(nodeMatches(s) || nodeMatches(t));
    const conn = focusId && (e.from === focusId || e.to === focusId);
    const weight = e.sem ? e.w : 0.5;
    const lw = conn ? 2 + weight * 2 : 1 + weight * 1.5;
    const dx = t.x - s.x, dy = t.y - s.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const off = dense ? 12 : 18;
    const cpx = (s.x + t.x) / 2 + (-dy / len * off), cpy = (s.y + t.y) / 2 + (dx / len * off);
    let alpha = dim ? 0.06 : (focusId ? (conn ? 0.65 : 0.06) : (dense ? 0.15 : 0.25));
    if(e.sem && !dim && !(focusId && !conn)) alpha = Math.min(0.75, alpha + 0.08);

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.quadraticCurveTo(cpx, cpy, t.x, t.y);
    if(e.sem){ ctx.setLineDash([5, 5]); ctx.strokeStyle = P.sem; } else { ctx.strokeStyle = P.link; }
    ctx.lineWidth = lw; ctx.stroke();
    ctx.restore();

    if(!e.sem && (!dense || conn)){ // 링크는 방향이 있다 — 화살촉
      const ang = Math.atan2(t.y - cpy, t.x - cpx), al = 5 + lw;
      ctx.save();
      ctx.globalAlpha = dim ? 0.06 : conn ? 0.6 : 0.2; ctx.fillStyle = P.link;
      ctx.beginPath();
      ctx.moveTo(t.x - t.r * Math.cos(ang), t.y - t.r * Math.sin(ang));
      ctx.lineTo(t.x - (t.r + al) * Math.cos(ang - 0.3), t.y - (t.r + al) * Math.sin(ang - 0.3));
      ctx.lineTo(t.x - (t.r + al) * Math.cos(ang + 0.3), t.y - (t.r + al) * Math.sin(ang + 0.3));
      ctx.closePath(); ctx.fill();
      ctx.restore();
    }
    if(e.sem && !dim && (conn ? G.zoom > 0.6 : G.zoom > edgeLabelZoom)){
      const zi = 1 / G.zoom;
      ctx.save();
      ctx.globalAlpha = conn ? 0.95 : 0.7; ctx.fillStyle = P.sem; ctx.textAlign = "center";
      ctx.font = "500 " + (10 * zi).toFixed(1) + "px " + FONT_MONO;
      ctx.fillText("cos " + e.w.toFixed(2), cpx, cpy - 4 * zi);
      ctx.restore();
    }
  });

  G.deadEdges.forEach((de) => { // 끊어진 링크 — 절단선 + 십자
    const s = map[de.from];
    if(!s || !G.filters[s.kind]) return;
    const dim = searching && !nodeMatches(s), conn = focusId === de.from;
    const alpha = dim ? 0.08 : (focusId ? (conn ? 0.8 : 0.08) : 0.45);
    const x1 = s.x + Math.cos(de.a) * (s.r + 4), y1 = s.y + Math.sin(de.a) * (s.r + 4);
    const x2 = s.x + Math.cos(de.a) * (s.r + 34), y2 = s.y + Math.sin(de.a) * (s.r + 34);
    ctx.save();
    ctx.globalAlpha = alpha; ctx.strokeStyle = P.dead; ctx.lineWidth = 1.2;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(x2 - 3.5, y2 - 3.5); ctx.lineTo(x2 + 3.5, y2 + 3.5);
    ctx.moveTo(x2 + 3.5, y2 - 3.5); ctx.lineTo(x2 - 3.5, y2 + 3.5);
    ctx.stroke();
    if(conn || G.zoom > 1.4){
      const zi = 1 / G.zoom;
      ctx.globalAlpha = Math.min(1, alpha + 0.2); ctx.fillStyle = P.dead; ctx.textAlign = "left";
      ctx.font = (10 * zi).toFixed(1) + "px " + FONT_MONO;
      ctx.fillText(truncate(de.ref, 20), x2 + 6 * zi, y2 + 3 * zi);
    }
    ctx.restore();
  });

  const placed = []; // 라벨 충돌 — 겹치는 보조 라벨은 접는다(선택·호버·적중은 항상 그린다)
  G.nodes.forEach((n) => {
    if(!G.filters[n.kind]) return;
    const color = P.kind[n.kind] || P.kind.note;
    const shape = SHAPE[n.kind] || "circle";
    const isSel = selId === n.slug, isHov = hoverId === n.slug;
    const m = !searching || nodeMatches(n);
    const faded = focusId && n.slug !== focusId && !(G.adj[focusId] && G.adj[focusId].has(n.slug));
    const alpha = !m ? 0.12 : (faded ? 0.2 : 1);

    ctx.save();
    ctx.globalAlpha = alpha;
    if(m && !faded && (isSel || isHov || !searching)){
      ctx.shadowColor = color;
      ctx.shadowBlur = isSel ? 20 : isHov ? 16 : (dense ? 4 : 8);
    }
    shapePath(ctx, n.x, n.y, n.r, shape);
    ctx.fillStyle = color; ctx.fill();
    ctx.restore();

    if(isSel){
      ctx.save();
      shapePath(ctx, n.x, n.y, n.r + 3, shape);
      ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.shadowColor = color; ctx.shadowBlur = 12;
      ctx.stroke();
      ctx.restore();
    } else if(isHov || (searching && m)){
      shapePath(ctx, n.x, n.y, n.r + 2, shape);
      ctx.strokeStyle = isHov ? color : P.hit; ctx.lineWidth = 2; ctx.stroke();
    }
    if(n.orphan){ // 연결 없는 페이지 — 점선 궤도
      ctx.save();
      ctx.globalAlpha = Math.max(alpha, 0.4); ctx.strokeStyle = P.orphan; ctx.lineWidth = 1.2;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 6, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    }
    if(n.poisoned){ // 위험 감지 격리 — 링 + 사선
      ctx.save();
      ctx.globalAlpha = Math.max(alpha, 0.6); ctx.strokeStyle = P.dead; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 4, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(n.x - n.r - 4, n.y + n.r + 4); ctx.lineTo(n.x + n.r + 4, n.y - n.r - 4);
      ctx.stroke();
      ctx.restore();
    }

    const priority = isSel || isHov || (searching && m);
    if(!(m && !faded && (priority || (G.zoom > labelZoom && (!dense || n.r > 10))))) return;
    const zi = 1 / G.zoom;
    ctx.save();
    ctx.font = (isSel || isHov ? "600 " : "500 ") + (13 * zi).toFixed(1) + "px " + FONT_SANS;
    ctx.textAlign = "center";
    const label = truncate(n.title, 18);
    const labelW = ctx.measureText(label).width + 16 * zi, labelH = 20 * zi;
    let labelY = n.y + n.r + 8 * zi;
    const worldBottom = (h - G.panY) / G.zoom; // 아래에서 잘리면 노드 위로 뒤집는다
    if(labelY + labelH > worldBottom - 4 * zi) labelY = n.y - n.r - 8 * zi - labelH;
    const box = { x: n.x - labelW / 2, y: labelY, w: labelW, h: labelH };
    const clash = placed.some((p) => box.x < p.x + p.w && p.x < box.x + box.w && box.y < p.y + p.h && p.y < box.y + box.h);
    if(clash && !priority){ ctx.restore(); return; }
    placed.push(box);
    ctx.fillStyle = P.labelBg;
    ctx.beginPath();
    if(ctx.roundRect) ctx.roundRect(box.x, labelY, labelW, labelH, 4 * zi);
    else ctx.rect(box.x, labelY, labelW, labelH);
    ctx.fill();
    ctx.strokeStyle = P.labelLine; ctx.lineWidth = 1 * zi; ctx.stroke();
    ctx.fillStyle = isSel || isHov ? P.labelInk : P.labelDim;
    ctx.fillText(label, n.x, labelY + 14 * zi);
    ctx.restore();
  });

  ctx.restore();
}

function canvasCoords(e){
  const rect = G.canvas.getBoundingClientRect();
  return { x: (e.clientX - rect.left - G.panX) / G.zoom, y: (e.clientY - rect.top - G.panY) / G.zoom };
}
function findNode(cx, cy){
  for(let i = G.nodes.length - 1; i >= 0; i--){
    const n = G.nodes[i];
    if(!G.filters[n.kind]) continue;
    const dx = n.x - cx, dy = n.y - cy;
    if(dx * dx + dy * dy < n.r * n.r + 25) return n;
  }
  return null;
}
function zoomBy(f){ G.zoom = Math.max(0.1, Math.min(5, G.zoom * f)); wakeSim(); }
function recenter(){
  const { w, h } = canvasSize();
  G.zoom = 1; G.panX = w / 2; G.panY = h / 2;
  wakeSim();
}
function announce(msg){ const el = $("mem-gsay"); if(el) el.textContent = msg; }
function selectNode(n, center){
  G.sel = n;
  if(center){
    const { w, h } = canvasSize();
    G.panX = w / 2 - n.x * G.zoom; G.panY = h / 2 - n.y * G.zoom;
  }
  loadDetail(n.slug);
  announce(n.title + " 선택 — " + kindName(n.kind) + ", 연결 " + n.degree + "개"
    + (n.orphan ? ", 연결 없음" : "") + (n.poisoned ? ", 위험 감지 격리" : ""));
  wakeSim();
}
function clearSelection(){
  const box = $("mem-gdetail");
  G.sel = null;
  if(box) box.innerHTML = "";
  announce("선택을 풀었어요");
  wakeSim();
}
function cycleNode(dir){
  const vs = visNodes().slice().sort((a, b) => (b.degree - a.degree) || (a.slug < b.slug ? -1 : 1));
  if(!vs.length) return;
  const i = G.sel ? vs.findIndex((n) => n.slug === G.sel.slug) : -1;
  selectNode(vs[((i + dir) % vs.length + vs.length) % vs.length], true);
}
async function loadDetail(slug){
  const box = $("mem-gdetail");
  if(!box) return;
  box.innerHTML = '<div class="mem-det">' + empty("불러오는 중이에요…") + '</div>';
  try{
    box.innerHTML = MEM.detailHtml(await fetchPage(slug), { slug: slug });
  }catch(e){
    box.innerHTML = '<div class="mem-det">' + errorCard(String(e)) + '</div>';
  }
  box.scrollIntoView({ block: "nearest", behavior: REDUCED ? "auto" : "smooth" });
}
// 어느 탭에서든 별을 지목하면 성좌로 건너가 그 별을 비춘다.
async function gotoSlug(slug){
  await switchTab("graph");
  const n = G.nodes.find((x) => x.slug === slug);
  if(!n){ loadDetail(slug); return; } // 성좌 밖 참조 — 창구가 없는 페이지라고 알려 준다
  if(!G.filters[n.kind]){ // 꺼진 종류를 지목하면 필터를 되켠다 — 숨은 채 선택되는 모순 방지
    G.filters[n.kind] = true;
    const cb = document.querySelector('#mem-gfilters input[data-kind="' + n.kind + '"]');
    if(cb) cb.checked = true;
  }
  selectNode(n, true);
  const c = $("mem-canvas");
  if(c) c.focus();
}

function showTip(canvas, e, hover){
  const tip = $("mem-gtip");
  if(!tip) return;
  if(!hover){
    tip.classList.remove("on");
    return;
  }
  tip.innerHTML = '<div class="tt-t">' + esc(hover.title) + '</div>'
    + '<div class="tt-k" style="color:' + kindVar(hover.kind) + '">' + esc(kindName(hover.kind))
    + ' · ' + esc(hover.kind) + '</div>'
    + '<div class="tt-m">연결 ' + hover.degree + ' · 회수 ' + hover.uses + '회'
    + (hover.orphan ? ' · 연결 없음' : '') + (hover.poisoned ? ' · 위험 감지' : '') + '</div>';
  const rect = canvas.getBoundingClientRect();
  tip.style.left = Math.min(e.clientX - rect.left + 12, rect.width - 200) + "px";
  tip.style.top = (e.clientY - rect.top + 12) + "px";
  tip.classList.add("on");
}
function bindGraph(){
  const canvas = G.canvas;
  let panning = false, lastX = 0, lastY = 0;
  canvas.addEventListener("mousedown", (e) => {
    const c = canvasCoords(e), node = findNode(c.x, c.y);
    if(node) G.drag = node; else panning = true;
    lastX = e.clientX; lastY = e.clientY;
    wakeSim();
  });
  canvas.addEventListener("mousemove", (e) => {
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    if(G.drag){
      G.drag.x += dx / G.zoom; G.drag.y += dy / G.zoom;
      G.drag.vx = 0; G.drag.vy = 0;
      wakeSim();
    } else if(panning){
      G.panX += dx; G.panY += dy;
      wakeSim();
    }
    lastX = e.clientX; lastY = e.clientY;
    G.mx = e.clientX; G.my = e.clientY;
    const c = canvasCoords(e);
    const hover = G.drag || panning ? null : findNode(c.x, c.y);
    showTip(canvas, e, hover);
    canvas.style.cursor = hover ? "pointer" : (G.drag || panning ? "grabbing" : "grab");
    if(!G.raf) renderGraph(); // 파킹 중에도 호버는 응답한다
  });
  canvas.addEventListener("mouseleave", () => {
    G.mx = -1e4; G.my = -1e4;
    showTip(canvas, null, null);
    if(!G.raf) renderGraph();
  });
  canvas.addEventListener("mouseup", () => {
    if(G.drag && !panning) selectNode(G.drag, false);
    G.drag = null; panning = false;
  });
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); zoomBy(e.deltaY > 0 ? 0.9 : 1.1); }, { passive: false });
  canvas.addEventListener("dblclick", (e) => {
    const c = canvasCoords(e), node = findNode(c.x, c.y);
    if(node){ G.zoom = Math.max(G.zoom, 1.6); selectNode(node, true); }
  });
  // 캔버스는 role=application 이다 — 팬·줌·순회·상세 진입이 전부 키로 끝나야 한다.
  canvas.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 120 : 40;
    let used = true;
    if(e.key === "ArrowLeft") G.panX += step;
    else if(e.key === "ArrowRight") G.panX -= step;
    else if(e.key === "ArrowUp") G.panY += step;
    else if(e.key === "ArrowDown") G.panY -= step;
    else if(e.key === "+" || e.key === "=") zoomBy(1.25);
    else if(e.key === "-" || e.key === "_") zoomBy(0.8);
    else if(e.key === "0") recenter();
    else if(e.key === "]") cycleNode(1);
    else if(e.key === "[") cycleNode(-1);
    else if(e.key === "Enter"){ const btn = $("mem-gdetail").querySelector("button"); if(btn) btn.focus(); }
    else if(e.key === "Escape") clearSelection();
    else used = false;
    if(used){ e.preventDefault(); wakeSim(); }
  });
  window.addEventListener("resize", () => {
    if(!G.canvas || !G.canvas.isConnected) return;
    resizeCanvas(); wakeSim();
  });
}

function buildFilters(){
  const counts = {};
  G.nodes.forEach((n) => { counts[n.kind] = (counts[n.kind] || 0) + 1; });
  const el = $("mem-gfilters");
  if(!el) return;
  el.innerHTML = Object.keys(counts).sort().map((k) =>
    '<label class="mem-fitem"><input type="checkbox" checked data-kind="' + esc(k) + '">'
    + swatch(k) + esc(kindName(k)) + ' <span class="mono">' + esc(k) + '</span>'
    + '<span class="cnt">' + counts[k] + '</span></label>').join("");
  el.querySelectorAll("input").forEach((cb) => {
    cb.addEventListener("change", function(){
      G.filters[this.dataset.kind] = this.checked;
      renderAltList();
      wakeSim();
    });
  });
}
// 캔버스는 스크린리더에 안 읽힌다 — 같은 자료를 목록으로 한 벌 더 낸다(장식이 아니라 대체 경로).
function renderAltList(){
  const el = $("mem-galt");
  if(!el) return;
  const rows = visNodes().slice().sort((a, b) => (b.degree - a.degree) || a.title.localeCompare(b.title, "ko"));
  el.innerHTML = rows.length
    ? rows.slice(0, 40).map((n) => '<li><button type="button" class="mem-link" data-mem="goto" data-slug="'
        + esc(n.slug) + '">' + swatch(n.kind) + esc(n.title) + '</button>'
        + '<span class="cnt">연결 ' + n.degree + '</span></li>').join("")
      + (rows.length > 40 ? '<li class="mem-more">외 ' + (rows.length - 40) + '장은 서고 탭에서 볼 수 있어요</li>' : "")
    : '<li class="ak-empty">보이는 별이 없어요 — 종류 필터를 풀어 보세요</li>';
}
function renderGraphStats(g){
  const sem = g.edges.filter((e) => e.type === "semantic").length;
  const link = g.edges.filter((e) => !e.dead && e.type !== "semantic").length;
  const cell = (v, l, bad) => '<div class="cell' + (bad ? " bad" : "") + '"><div class="v">' + v
    + '</div><div class="l">' + l + '</div></div>';
  $("mem-gstats").innerHTML = cell(g.nodes.length, "페이지") + cell(link, "직접 링크")
    + cell(sem, "의미 연결선") + cell(g.dead, "끊어진 링크", g.dead);
  $("mem-gcount").textContent = "· 별 " + g.nodes.length + " · 선 " + g.edges.length;
}
function initGraph(g, poison){
  const canvas = $("mem-canvas");
  if(!canvas) return;
  G.canvas = canvas;
  G.ctx = canvas.getContext("2d");
  resizeCanvas();
  const { w, h } = canvasSize();
  G.panX = w / 2; G.panY = h / 2;
  G.zoom = g.nodes.length <= 15 ? 1.5 : g.nodes.length <= 40 ? 1.2 : 1;
  G.tick = 0; G.quiet = 0; G.sel = null;
  G.nodes = g.nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(g.nodes.length, 1);
    const radius = Math.min(w, h) * 0.3;
    return { slug:n.slug, kind:n.kind, title:n.title, uses:n.uses, degree:n.degree,
      orphan:n.orphan, poisoned:!!poison[n.slug],
      x: Math.cos(angle) * radius + (Math.random() - 0.5) * 50,
      y: Math.sin(angle) * radius + (Math.random() - 0.5) * 50,
      vx: 0, vy: 0,
      r: Math.max(8, Math.min(22, 8 + n.degree * 2.5)) }; // 반경 = 차수
  });
  G.liveEdges = []; G.deadEdges = [];
  g.edges.forEach((e) => {
    if(e.dead) G.deadEdges.push({ from: e.from, ref: e.to, a: angleOf(e.from + ">" + e.to) });
    else G.liveEdges.push({ from: e.from, to: e.to, sem: e.type === "semantic",
      w: typeof e.w === "number" ? e.w : 0.5 });
  });
  G.adj = {};
  G.liveEdges.forEach((e) => {
    (G.adj[e.from] = G.adj[e.from] || new Set()).add(e.to);
    (G.adj[e.to] = G.adj[e.to] || new Set()).add(e.from);
  });
  G.filters = {};
  G.nodes.forEach((n) => { G.filters[n.kind] = true; });
  buildFilters();
  renderAltList();
  renderGraphStats(g);
  if(!G.bound){ bindGraph(); G.bound = true; }
  G.running = true;
  if(REDUCED){
    // 움직임을 줄여 달라고 했으면 정착 과정을 보이지 않는다 — 결과 배치만 한 번 그린다.
    for(let i = 0; i < 600 && G.quiet <= 30; i++) tickPhysics();
    renderGraph();
  } else wakeSim();
}
const graphSig = (g) => JSON.stringify({
  n: g.nodes.map((n) => [n.slug, n.kind, n.degree, n.orphan]),
  e: g.edges.map((e) => [e.from, e.to, !!e.dead, e.type || "", e.w || 0]),
});
function renderOrphans(s){
  const cap = $("mem-gsem");
  if(cap){
    cap.innerHTML = s.graph.sem_capped
      ? '<p class="mem-hint">페이지가 ' + s.graph.sem_cap + '장을 넘어 의미 연결선 계산을 건너뛰었어요. 직접 링크만 그립니다.</p>'
      : s.meta.semantic ? ""
      : '<p class="mem-hint">의미가 비슷한 선은 <code>[memory] semantic=local</code> 설정으로 켜져요 — 지금은 직접 링크만 보입니다.</p>';
  }
  $("mem-orphan-count").textContent = "· " + s.graph.orphans.length;
  $("mem-orphans").innerHTML = s.graph.orphans.slice(0, 12).map((o) => '<li>' + slugBtn(o) + '</li>').join("")
    || (s.graph.nodes.length ? '<li class="mem-ok">모두 어딘가와 이어져 있어요</li>'
        : '<li class="ak-empty">아직 페이지가 없어요</li>');
}
function seedGraph(s){
  const poison = {};
  s.catalog.forEach((p) => { if(p.poisoned) poison[p.slug] = true; });
  initGraph(s.graph, poison); // 판이 보일 때만 — display:none 캔버스는 치수가 0 이다
  APP.graphReady = true;
  APP.graphSig = graphSig(s.graph);
  renderOrphans(s);
}
function refreshGraph(s){
  if(!APP.graphReady){ seedGraph(s); return; }
  resizeCanvas();
  if(graphSig(s.graph) === APP.graphSig){
    // 자료가 그대로면 다시 뿌리지 않는다 — 손으로 끌어다 놓은 배치를 부순다.
    const um = {};
    s.graph.nodes.forEach((n) => { um[n.slug] = n.uses; });
    G.nodes.forEach((n) => { n.uses = um[n.slug] || 0; });
    renderOrphans(s);
    wakeSim();
    if(REDUCED) renderGraph();
    return;
  }
  APP.graphReady = false;
  seedGraph(s);
}

/* ══ 껍데기 — 탭 · 갱신 · 판 배치 ══════════════════════════════════════════════ */

const GRAPH_HTML =
    '<section class="ak-card mem-constellation" aria-label="기억 성좌 그래프">'
  + '<h3 class="ak-card__title">기억 성좌 <span class="mem-dim" id="mem-gcount"></span></h3>'
  + '<div class="mem-gbody"><div class="mem-gwrap">'
  + '<canvas id="mem-canvas" tabindex="0" role="application" aria-describedby="mem-ghelp"'
  + ' aria-label="기억 성좌 — 페이지가 별이고 직접 링크와 의미가 비슷한 관계가 별자리 선이에요. 옆의 별 목록에 같은 내용이 글로 있습니다."></canvas>'
  + '<div class="mem-gctrl" role="group" aria-label="성좌 보기 조절">'
  + '<button type="button" class="ak-btn" data-mem="zoom-in" aria-label="확대">+</button>'
  + '<button type="button" class="ak-btn" data-mem="zoom-out" aria-label="축소">−</button>'
  + '<button type="button" class="ak-btn" data-mem="recenter" aria-label="처음 위치로">◎</button></div>'
  + '<div class="mem-gtip" id="mem-gtip" aria-hidden="true"></div>'
  + '<p class="mem-ghint" id="mem-ghelp">끌어서 이동 · 휠로 확대 · 키보드: 화살표 이동 / + − 확대 / ] [ 별 순회 / Enter 상세 / Esc 해제 / 0 처음으로</p>'
  + '</div><aside class="mem-gside" aria-label="성좌 조절">'
  + '<label class="mem-vh" for="mem-gq">성좌에서 페이지 찾기</label>'
  + '<input id="mem-gq" class="ak-input" type="search" placeholder="페이지 검색 — 제목·이름" autocomplete="off">'
  + '<div id="mem-gdetail"></div>'
  + '<div class="mem-gstats" id="mem-gstats" aria-label="성좌 통계"></div>'
  + '<p class="mem-sectitle">종류 — 색과 모양 두 축으로 구분해요</p><div id="mem-gfilters"></div>'
  + '<p class="mem-sectitle">선의 뜻</p><ul class="mem-legend">'
  + '<li><span class="ln link"></span>직접 링크 — 금색 실선</li>'
  + '<li><span class="ln sem"></span>의미가 비슷함 — 초록 점선</li>'
  + '<li><span class="ln dead"></span>끊어진 링크 — 붉은 절단선</li></ul>'
  + '<div id="mem-gsem"></div>'
  + '<p class="mem-sectitle">연결 없는 페이지 <span id="mem-orphan-count"></span></p>'
  + '<ul class="mem-glist" id="mem-orphans"></ul>'
  + '<p class="mem-sectitle" id="mem-galt-title">별 목록 — 캔버스와 같은 내용</p>'
  + '<ul class="mem-glist mem-alt" id="mem-galt" aria-labelledby="mem-galt-title"></ul>'
  + '</aside></div>'
  + '<div id="mem-gsay" class="mem-vh" role="status" aria-live="polite"></div></section>';

function panelHtml(id){
  if(id === "graph") return GRAPH_HTML;
  if(MEM.panels[id]) return MEM.panels[id].html;
  return '<div class="ak-error"><strong class="ak-error__title">이 판을 그리는 코드가 없어요</strong>'
    + '<span>memory-search.js · memory-log.js 가 이 창에 실렸는지 확인해 주세요.</span></div>';
}
function shellHtml(){
  return '<div class="mem">'
    + '<div class="mem-bar"><div class="mem-meta" id="mem-meta">불러오는 중이에요…</div>'
    + '<button type="button" class="ak-btn" data-mem="refresh" id="mem-refresh">지금 새로고침</button>'
    + '<span class="ak-badge" id="mem-live">30초마다 갱신</span></div>'
    + '<div class="ak-tabs" role="tablist" aria-label="기억 화면 목록" id="mem-tabs">'
    + TABS.map(([id, label], i) => '<button type="button" class="ak-tab" role="tab" id="mem-tab-' + id
        + '" data-mem="tab" data-tab="' + id + '" aria-controls="mem-p-' + id + '" aria-selected="'
        + (i === 0) + '" tabindex="' + (i === 0 ? 0 : -1) + '">' + label + '</button>').join("")
    + '</div><div class="mem-panels">'
    + TABS.map(([id]) => '<section class="mem-panel" id="mem-p-' + id + '" role="tabpanel" aria-labelledby="mem-tab-'
        + id + '"' + (id === "overview" ? "" : " hidden") + '>' + panelHtml(id) + '</section>').join("")
    + '</div></div>';
}

function renderMeta(s){
  const m = s.meta;
  $("mem-meta").innerHTML = '<span>서고 <b class="mono" title="' + esc(m.dir) + '">' + esc(m.dir) + '</b></span>'
    + '<span>페이지 <b>' + m.pages + '</b></span>'
    + '<span>의미 검색 <b class="' + (m.semantic ? "on" : "off") + '">'
    + (m.semantic ? "켜짐" : m.semantic_mode === "off" ? "꺼짐" : "준비 안 됨") + '</b></span>'
    + '<span>' + esc(m.generated) + '</span>';
}
function setLive(ok){
  const b = $("mem-live");
  if(!b) return;
  b.className = "ak-badge " + (ok ? "ak-badge--ok" : "ak-badge--danger");
  b.textContent = ok ? "30초마다 갱신 · " + new Date().toTimeString().slice(0, 8) : "갱신 실패 — 다시 시도해요";
}
async function snapshot(force){
  if(APP.snap && !force) return APP.snap;
  const s = await fetchSnapshot();
  APP.snap = s;
  renderMeta(s);
  setLive(true);
  return s;
}
async function renderTab(tab, s){
  if(tab === "graph"){ refreshGraph(s); return; }
  if(MEM.panels[tab]){ await MEM.panels[tab].render(s); APP.loaded[tab] = true; }
}
async function loadTab(tab){
  const panel = $("mem-p-" + tab);
  if(!panel) return;
  try{
    const s = await snapshot(false);
    if(tab !== "graph" && APP.loaded[tab]) return; // 재진입은 캐시 — 성좌만 배치를 이어 그린다
    await renderTab(tab, s);
  }catch(e){
    if(!panel.querySelector(".mem-err")) panel.insertAdjacentHTML("afterbegin", errorCard(String(e)));
    setLive(false);
  }
}
function switchTab(tab){
  if(!TABS.some(([id]) => id === tab)) tab = APP.active;
  APP.active = tab;
  TABS.forEach(([id]) => {
    const btn = $("mem-tab-" + id), on = id === tab;
    if(btn){
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.tabIndex = on ? 0 : -1; // APG roving tabindex
    }
    const p = $("mem-p-" + id);
    if(p) p.hidden = !on;
  });
  return loadTab(tab);
}
async function refreshNow(){
  const btn = $("mem-refresh");
  if(btn) btn.disabled = true;
  try{
    const s = await snapshot(true);
    APP.inj = null; // 전달도 같이 낡는다 — 캐시를 버려야 다음 진입이 새 블록을 본다
    APP.loaded = {};
    await renderTab(APP.active, s);
    setLive(true);
  }catch(e){
    setLive(false);
  }finally{
    if(btn) btn.disabled = false;
  }
}

function bindShell(root){
  root.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-mem]");
    if(!t) return;
    const act = t.getAttribute("data-mem");
    if(act === "tab") switchTab(t.getAttribute("data-tab"));
    else if(act === "refresh") refreshNow();
    else if(act === "retry"){
      root.querySelectorAll(".mem-err").forEach((n) => n.remove());
      APP.loaded[APP.active] = false;
      loadTab(APP.active);
    }
    else if(act === "zoom-in") zoomBy(1.25);
    else if(act === "zoom-out") zoomBy(0.8);
    else if(act === "recenter") recenter();
    else if(act === "close-detail"){
      clearSelection();
      const c = $("mem-canvas");
      if(c) c.focus(); // 상세를 닫으면 연 표면으로 포커스가 돌아온다
    }
    else if(act === "goto") gotoSlug(t.getAttribute("data-slug"));
    else if(MEM.onAction) MEM.onAction(act, t);
  });
  // 목록 행이 button 이 아닌 자리(role=button)의 키보드 완주 — 클릭 위임과 같은 길로 보낸다.
  root.addEventListener("keydown", (ev) => {
    const t = ev.target;
    if((ev.key !== "Enter" && ev.key !== " ") || !(t instanceof HTMLElement)) return;
    if(t.tagName === "BUTTON" || !t.hasAttribute("data-mem")) return;
    ev.preventDefault();
    t.click();
  });
  // 탭 바 키보드 — APG 화살표 순회, 자동 활성.
  $("mem-tabs").addEventListener("keydown", (e) => {
    const tabs = Array.from($("mem-tabs").querySelectorAll('[role="tab"]'));
    const i = tabs.indexOf(document.activeElement);
    if(i < 0) return;
    let j = -1;
    if(e.key === "ArrowRight") j = (i + 1) % tabs.length;
    else if(e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
    else if(e.key === "Home") j = 0;
    else if(e.key === "End") j = tabs.length - 1;
    if(j < 0) return;
    e.preventDefault();
    tabs[j].focus();
    switchTab(tabs[j].dataset.tab);
  });
  bindImeSafeSearch($("mem-gq"), 200, (v) => {
    G.term = v.trim().toLowerCase();
    wakeSim();
    if(!G.raf) renderGraph();
  });
  if(MEM.bind) MEM.bind(root);
}

/* ── 스튜디오가 부르는 문 ───────────────────────────────────────────────────── */

function startPoll(){
  if(APP.poll) return;
  APP.poll = setInterval(() => { if(!document.hidden) refreshNow(); }, 30000);
}
function stopPoll(){
  if(APP.poll){ clearInterval(APP.poll); APP.poll = null; }
}
// 스튜디오는 판에 들어올 때마다 이 함수를 부른다 — 두 번째부터는 다시 짓지 않는다.
function initMemoryView(body){
  const root = body || $("memory-body");
  if(!root) return;
  if(!APP.mounted){
    root.innerHTML = shellHtml();
    APP.mounted = true;
    bindShell(root);
    watchTheme();
    document.addEventListener("visibilitychange", () => {
      if(document.hidden) stopPoll(); // 숨은 창에 폴링을 태우지 않는다
      else if(root.isConnected){ startPoll(); refreshNow(); }
    });
  } else if(APP.active === "graph"){
    resizeCanvas(); // 판이 숨었다 돌아오면 치수를 다시 잰다
    wakeSim();
  }
  startPoll();
  return switchTab(APP.active);
}

/* ── 다른 두 파일에 넘기는 것 ───────────────────────────────────────────────── */

Object.assign(MEM, {
  $: $, esc: esc, truncate: truncate, daysAgo: daysAgo, fmtBytes: fmtBytes, reduced: REDUCED,
  APP: APP, api: api, fetchInjection: fetchInjection, fetchSearch: fetchSearch,
  fetchPage: fetchPage, fetchLog: fetchLog,
  skeleton: skeleton, empty: empty, onboard: onboard, errorCard: errorCard,
  kchip: kchip, swatch: swatch, kindName: kindName, kindVar: kindVar,
  opStyle: opStyle, opGlyph: opGlyph, logRow: logRow, slugBtn: slugBtn,
  bindImeSafeSearch: bindImeSafeSearch, captureFocus: captureFocus, restoreFocus: restoreFocus,
  switchTab: switchTab, gotoSlug: gotoSlug,
});
window.initMemoryView = initMemoryView;
})();
