"""자립형 그래프 뷰 — 외부 리소스 0의 단일 HTML로 관계 그래프를 그린다.

`asgard map`(bare) / `asgard map view`가 연다. 산출물은 런타임 상태
(`.asgard/state/map-view.html`)로, git에 추적되지 않는다.
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
  /* Freyja4 · designed-as-app · component: graph workbench — canvas stage + control rail
   * genre: modern-minimal (developer tool) · theme: custom "Asgard night + gold"
   * anchor hue: 40 (gold) · paper #0C0A07 · accent #C6A45E · display + body: system mono/sans
   * design system: the :root block below is the source of truth — the canvas reads it too,
   *   so a retune of a token moves the drawing with the DOM. No design.md (docs stay out of tree).
   * states shipped: default · hover · focus-visible · active · disabled.
   *   loading / error / success do not exist on this surface — it renders a local snapshot,
   *   it does not submit anything. Claiming them would be a checklist, not a state.
   * diversification: suspended. This is a product surface, not a page in rotation —
   *   a future Freyja4 run must not re-roll its macrostructure.
   */
  :root{
    --vault:#0C0A07; --surface:#14110C; --surface-2:#1B160E; --surface-3:#241C11;
    --hairline:#E6D096;
    --line:rgba(230,208,150,.10); --line-strong:rgba(230,208,150,.20);
    --gold:#C6A45E; --gold-lit:#E8C87E; --warn:#D2933F;
    --ink:#E9E0CA; --dim:#9C9179;
    /* 무대·부유 패널의 반투명 면 — 아래 캔버스가 비치는 곳은 전부 토큰으로 */
    --scrim:rgba(12,10,7,.92); --scrim-strong:rgba(12,10,7,.94); --panel:rgba(20,17,12,.88);
    --glow:rgba(198,164,94,.055); --grid-line:rgba(230,208,150,.028);
    /* 4pt 리듬 — 계기판은 조밀하지만 임의값은 쓰지 않는다 */
    --space-2xs:4px; --space-xs:8px; --space-sm:12px; --space-md:16px;
    --space-lg:20px; --space-xl:24px; --space-pull:-8px;
    /* 이름 있는 이징·지속 — 브라우저 기본 ease는 쓰지 않는다 */
    --ease-out:cubic-bezier(.22,1,.36,1); --dur-quick:120ms; --dur-short:160ms;
    --mono:"SF Mono",ui-monospace,"JetBrains Mono",Menlo,"Cascadia Code",Consolas,monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Segoe UI",Roboto,sans-serif;
  }
  *{box-sizing:border-box;margin:0}
  html{color-scheme:dark;-webkit-text-size-adjust:100%;overflow-x:clip}
  body{background:var(--vault);color:var(--ink);font:14px/1.55 var(--sans);
       height:100vh;display:grid;grid-template-rows:auto minmax(0,1fr);
       overflow-x:clip;overflow-y:hidden}
  button{font:inherit;color:inherit;cursor:pointer}
  .sr{position:absolute;width:1px;height:1px;padding:0;margin:0;overflow:hidden;
      clip:rect(0,0,0,0);white-space:nowrap;border:0}
  input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--gold);outline-offset:1px}

  /* ── 헤더 — 브랜드 로고 + 카운트 계기 ── */
  header{display:flex;justify-content:space-between;align-items:center;
         gap:var(--space-xs) var(--space-lg);flex-wrap:wrap;
         padding:var(--space-sm) var(--space-lg);border-bottom:1px solid var(--line);background:var(--surface)}
  .brand{display:flex;align-items:center;gap:var(--space-sm);min-width:0}
  .mark{color:var(--gold);flex:none}
  img.mark{height:42px;width:auto;display:block}
  h1{font:600 14.5px var(--mono);letter-spacing:.3em;color:var(--gold-lit);
     overflow-wrap:anywhere;min-width:0}
  .sub{font-size:12.5px;color:var(--dim)}
  /* 카운트 계기 — 큰 tabular 수치 + 미세 라벨(관측소 게이지) */
  .stats{display:flex;gap:4px 20px;flex-wrap:wrap;align-items:baseline}
  .stats .g{display:flex;flex-direction:column;align-items:flex-end}
  .stats b{font:500 18px var(--mono);font-variant-numeric:tabular-nums;color:var(--ink);line-height:1.15}
  .stats .link b{color:var(--gold-lit)}
  .stats i{font:10.5px var(--mono);font-style:normal;color:var(--dim);letter-spacing:.08em}
  .stats .rev{color:var(--dim);font:10.5px var(--mono);align-self:flex-end}

  main{display:grid;grid-template-columns:minmax(0,1fr) 360px;min-height:0}

  /* ── 무대 — 계기판 바닥(라디얼 글로우 + 24px 마이크로 그리드) ── */
  /* 성좌(3차원)는 성운 헤이즈만 깐다 — 평면 그리드는 부피를 부정한다.
     레인은 결정론 평면이라 그리드가 자리를 읽는 데 쓰인다(.flat 에서만 켠다). */
  #stage{position:relative;min-height:0;background:
    radial-gradient(120% 90% at 50% 40%, var(--glow), transparent 70%),
    var(--vault)}
  #stage.flat{background:
    radial-gradient(90% 75% at 50% 18%, var(--glow), transparent 65%),
    repeating-linear-gradient(0deg, var(--grid-line) 0, var(--grid-line) 1px, transparent 1px, transparent 24px),
    repeating-linear-gradient(90deg, var(--grid-line) 0, var(--grid-line) 1px, transparent 1px, transparent 24px),
    var(--vault)}
  canvas{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab;touch-action:none}
  canvas:focus-visible{outline:2px solid var(--gold);outline-offset:-2px}
  .zoombar{position:absolute;top:var(--space-sm);right:var(--space-sm);display:flex;flex-direction:column;
           gap:var(--space-xs);background:var(--scrim);border-radius:10px;padding:var(--space-2xs)}
  .zoombar button{width:44px;height:44px;display:flex;align-items:center;justify-content:center;padding:0;
    background:var(--panel);border:1px solid var(--line-strong);border-radius:8px;color:var(--gold-lit);
    transition:border-color var(--dur-short) var(--ease-out),transform var(--dur-quick) var(--ease-out)}
  .zoombar button:hover{border-color:var(--gold)}
  .zoombar button:active{transform:scale(.96)}
  /* 배치 모드 토글 — 성좌(물리) ⇄ 레인(계층 컬럼) */
  .modebar{position:absolute;top:var(--space-sm);left:var(--space-sm);display:flex;background:var(--panel);
           border:1px solid var(--line-strong);border-radius:8px;overflow:hidden}
  .modebar button{border:0;background:none;color:var(--dim);font:11.5px var(--mono);
                  letter-spacing:.06em;padding:0 var(--space-md);min-height:36px;
                  transition:color var(--dur-short) var(--ease-out)}
  .modebar button+button{border-left:1px solid var(--line)}
  .modebar button[aria-pressed="true"]{color:var(--vault);background:var(--gold);font-weight:600}
  .modebar button[aria-pressed="false"]:hover{color:var(--gold-lit)}
  .hint{position:absolute;left:var(--space-md);bottom:var(--space-xs);font:10.5px var(--mono);color:var(--dim);
        pointer-events:none;max-width:72%}
  /* 표시 카운터 — 필터 결과가 침묵하지 않게 하는 상시 미니 게이지 */
  .viscount{position:absolute;right:var(--space-sm);bottom:var(--space-xs);font:10.5px var(--mono);color:var(--dim);
            font-variant-numeric:tabular-nums;pointer-events:none}
  #visreset{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:4;
            background:var(--surface-2);border:1px solid var(--warn);border-radius:8px;
            color:var(--ink);font:12.5px var(--mono);padding:var(--space-sm) var(--space-lg);min-height:44px;
            transition:border-color var(--dur-short) var(--ease-out)}
  #visreset:hover{border-color:var(--gold)}
  #tip{position:absolute;left:0;top:0;z-index:5;pointer-events:none;background:var(--scrim-strong);
       border:1px solid var(--line-strong);border-radius:7px;padding:var(--space-xs) var(--space-sm);
       font:11.5px var(--mono);max-width:260px;word-break:break-all}
  #tip .k{color:var(--dim);font-size:10.5px}

  /* ── 조작반 ── */
  aside{border-left:1px solid var(--line);background:var(--surface);min-height:0;overflow-y:auto;
        scrollbar-gutter:stable;padding:var(--space-md) var(--space-md) var(--space-lg);
        display:flex;flex-direction:column;gap:var(--space-sm)}
  input[type=search],select{width:100%;background:var(--surface-2);border:1px solid var(--line-strong);
    border-radius:8px;color:var(--ink);font:12.5px var(--mono);
    padding:var(--space-xs) var(--space-sm);min-height:40px}
  input[type=search]::placeholder{color:var(--dim)}
  .qhint{font:11.5px var(--mono);color:var(--dim);margin-top:var(--space-pull)}
  .sectitle{font:10.5px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold);
            margin-bottom:var(--space-xs)}

  #detail{border-top:1px solid var(--line);padding-top:var(--space-sm);font-size:12.5px}
  .d-empty{color:var(--dim)}
  .d-empty code{font-family:var(--mono);color:var(--ink)}
  .d-kind{display:flex;align-items:center;gap:var(--space-xs);font:11.5px var(--mono);color:var(--dim);
          margin-bottom:var(--space-xs);flex-wrap:wrap}
  .d-kind i{width:9px;height:9px;border-radius:50%;flex:none}
  .d-deg{margin-left:auto;font-size:10.5px}
  .badge-cand{color:var(--warn);border:1px solid color-mix(in oklab,var(--warn) 45%,transparent);
              border-radius:5px;padding:0 var(--space-xs);font-size:10.5px;line-height:1.7}
  .d-id{font-family:var(--mono);font-size:14.5px;color:var(--gold-lit);word-break:break-all;
        user-select:all;margin-bottom:4px}
  .d-h{font:10.5px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold);margin:12px 0 4px}
  .d-ev,.d-rec{list-style:none}
  .d-ev li{padding:4px 0;border-bottom:1px solid var(--line);color:var(--dim);word-break:break-all;line-height:1.5}
  .d-ev li:last-child{border-bottom:0}
  .d-ev b{font:500 12px var(--mono);color:var(--ink)}
  .cand{color:var(--warn);font-weight:600}
  .d-det{color:var(--dim)}
  .d-rec li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:var(--space-2xs) var(--space-xs);
            padding:var(--space-2xs) 0;border-bottom:1px solid var(--line);font-size:12.5px}
  .d-rec li:last-child{border-bottom:0}
  .d-rec .rt{color:var(--ink)}
  .d-rec .rm{color:var(--warn);font:10.5px var(--mono);align-self:start;line-height:1.7;
             border:1px solid color-mix(in oklab,var(--warn) 40%,transparent);border-radius:5px;
             padding:0 var(--space-xs)}
  .d-rec .rf{grid-column:1/-1;color:var(--dim);font:11.5px var(--mono);word-break:break-all}
  .d-code{display:block;background:var(--surface-2);border:1px solid var(--line);border-radius:7px;
          padding:var(--space-xs) var(--space-sm);font:11.5px var(--mono);color:var(--ink);
          word-break:break-all;user-select:all}
  .d-rel{list-style:none}
  .d-rel li{border-bottom:1px solid var(--line)}
  .d-rel li:last-child{border-bottom:0}
  .d-rel button{display:flex;align-items:center;gap:var(--space-xs);width:100%;background:none;border:0;
                padding:var(--space-2xs) 0;text-align:left;font-size:12.5px;color:var(--ink);min-height:28px}
  .d-rel i{width:8px;height:8px;border-radius:50%;flex:none}
  .d-rel .rk{font:10.5px var(--mono);color:var(--dim);flex:none}
  .d-rel .rn{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .d-rel button:hover .rn{color:var(--gold-lit)}
  .d-rel .rv{margin-left:auto;font:10.5px var(--mono);color:var(--dim);flex:none;max-width:38%;
             overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .d-rel .more{padding:var(--space-2xs) 0;color:var(--dim);font:11.5px var(--mono)}
  /* 체인 추적 — 상·하류 플로우 경로 */
  .d-act{display:flex;gap:var(--space-xs);margin:var(--space-xs) 0 var(--space-2xs)}
  .d-act button{flex:1;background:var(--surface-2);border:1px solid var(--line-strong);border-radius:7px;
                padding:var(--space-xs) var(--space-sm);min-height:36px;font:11.5px var(--mono);color:var(--gold-lit);
                transition:border-color var(--dur-short) var(--ease-out),background-color var(--dur-short) var(--ease-out)}
  .d-act button:hover{border-color:var(--gold)}
  .d-act button[aria-pressed="true"]{background:color-mix(in oklab,var(--gold) 13%,transparent);
                                     border-color:var(--gold)}
  .d-rel .dep{font:10.5px var(--mono);color:var(--gold);flex:none;min-width:20px}
  /* 검색 결과 — 순회 가능한 진입 리스트(수천 옵션 select의 상위 동선) */
  .results{max-height:224px;overflow-y:auto;margin-top:var(--space-pull)}
  .results button{padding:var(--space-2xs) var(--space-xs);border-radius:6px}
  .results li.act button{background:color-mix(in oklab,var(--gold) 10%,transparent)}
  .results .deg{margin-left:auto;color:var(--dim);font:10.5px var(--mono);flex:none}

  .chips{display:flex;flex-wrap:wrap;gap:var(--space-xs)}
  .chip{display:inline-flex;align-items:center;gap:var(--space-xs);background:transparent;color:var(--dim);
        border:1px solid var(--line-strong);border-radius:999px;
        padding:var(--space-2xs) var(--space-sm);min-height:30px;
        font:11.5px var(--mono);
        transition:border-color var(--dur-short) var(--ease-out),color var(--dur-short) var(--ease-out)}
  .chip:disabled{opacity:.4;cursor:not-allowed}
  .chip:hover{border-color:var(--gold)}
  .chip.on{color:var(--ink);border-color:color-mix(in oklab,var(--gold) 55%,transparent);
           background:color-mix(in oklab,var(--gold) 8%,transparent)}
  .chip i{width:8px;height:8px;border-radius:50%;flex:none;opacity:.35}
  .chip.on i{opacity:1}
  .chip .n{color:var(--dim);font-size:10.5px}
  .subhint{font:10.5px var(--mono);color:var(--dim);margin-top:var(--space-xs)}

  /* 엣지 언어 — 범례가 곧 필터(클릭 토글) */
  .ekl{list-style:none;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
       gap:var(--space-2xs) var(--space-md);font:11.5px var(--mono);color:var(--dim)}
  .ekl button{display:flex;align-items:center;gap:var(--space-xs);min-height:26px;width:100%;
              background:none;border:0;padding:0;color:inherit;font:inherit;
              transition:color var(--dur-short) var(--ease-out)}
  .ekl button:hover{color:var(--ink)}
  .ekl button[aria-pressed="false"]{opacity:.35}
  .ekl button:disabled{opacity:.25;cursor:default}
  .ekl svg{flex:none}
  .ekl b{margin-left:auto;color:var(--ink);font-weight:500;font-variant-numeric:tabular-nums}

  .foot{border-top:1px solid var(--line);padding-top:var(--space-sm);color:var(--dim);
        font-size:11.5px;margin-top:auto}
  .foot code{font-family:var(--mono);color:var(--ink)}

  @media (max-width:1080px){
    main{grid-template-columns:minmax(0,1fr) 300px}
    aside{padding:var(--space-sm) var(--space-sm) var(--space-md)}
  }
  @media (max-width:720px){
    body{display:block;height:auto;min-height:100vh;overflow-x:clip;overflow-y:auto}
    main{display:block}
    #stage{height:58vh;min-height:340px}
    aside{border-left:0;border-top:1px solid var(--line-strong);overflow:visible}
    .zoombar{top:auto;bottom:var(--space-sm)}
    /* 줌바가 아래로 내려오면 오른쪽 아래는 줌바 차지다 — 표시 카운터는 비는 왼쪽으로.
       (힌트가 여기서 숨으므로 자리는 비어 있다) */
    .viscount{right:auto;left:var(--space-md)}
    .hint{display:none}
    .stats b{font-size:15px}
    .modebar button{min-height:42px;padding:0 var(--space-md)}
    input[type=search],select{min-height:44px;font-size:12.5px}
    .chip{min-height:36px;padding:var(--space-xs) var(--space-sm)}
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
    <p class="viscount" id="viscount" aria-hidden="true"></p>
    <button type="button" id="visreset" hidden>필터로 모두 숨겨졌다 — 필터 초기화</button>
    <canvas id="c" tabindex="0" role="application" aria-describedby="hint"
      aria-label="관계 그래프 캔버스 — 성좌는 3차원 공간이다. 노드를 클릭하면 증거가 열린다. 화살표 키로 궤도를 돌리고 Shift+화살표로 평면 이동, 더하기·빼기 줌, 0 전체 보기, v 배치 전환, t 체인 추적, Esc 해제. 캔버스 없이도 노드 선택 목록으로 탐색할 수 있다."></canvas>
    <div class="modebar" role="group" aria-label="배치 모드">
      <button type="button" id="modeStar" aria-pressed="true">성좌</button>
      <button type="button" id="modeLane" aria-pressed="false">레인</button>
    </div>
    <div class="zoombar" role="group" aria-label="보기 조절">
      <button type="button" id="zoomIn" aria-label="확대"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M7.5 2.5v10M2.5 7.5h10" stroke="currentColor" stroke-width="1.6"/></svg></button>
      <button type="button" id="zoomOut" aria-label="축소"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M2.5 7.5h10" stroke="currentColor" stroke-width="1.6"/></svg></button>
      <button type="button" id="zoomFit" aria-label="전체 보기"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><circle cx="7.5" cy="7.5" r="4.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M7.5 .8v3M7.5 11.2v3M.8 7.5h3M11.2 7.5h3" stroke="currentColor" stroke-width="1.3"/></svg></button>
    </div>
    <p class="hint" id="hint">드래그 궤도 · Shift+드래그 팬 · 휠·핀치 줌 · 클릭 선택 · 키: 화살표 궤도 / + − / 0 전체 / v 성좌⇄레인 / t 체인 / Esc</p>
    <div id="tip" hidden></div>
  </div>
  <aside aria-label="그래프 조작과 상세">
    <div>
      <label class="sr" for="q">노드 검색</label>
      <input id="q" type="search" placeholder="노드 검색 — 이름·id" autocomplete="off" spellcheck="false">
    </div>
    <p class="qhint" id="qhint" hidden></p>
    <ul class="d-rel results" id="results" hidden aria-label="검색 결과 — 위아래 화살표로 이동, Enter로 선택"></ul>
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
// 종류 팔레트 — 나이트+골드 세계에 귀화: 다수 종류(page·component·route)는 웜 톤이 지배,
// 쿨 톤은 데이터·인프라 계열에 배정. 동색권 충돌(composable↔db_access, store↔event) 분리.
const KIND_COLORS = { file:"#6E7787", route:"#E8C87E", page:"#F0A268", store:"#D093EE", composable:"#97D695",
  component:"#C9AD8C", command:"#D98E4A", model:"#85AEE8",
  db_access:"#4FB8AE", api_call:"#E88585", event:"#7B7BE0", job:"#B9C167", external_service:"#E08FB8" };
const KIND_ORDER = ["route","page","component","store","composable","command","model","db_access","api_call","event","job","external_service","file"];
// 팔레트 단일 출처 — 캔버스는 DOM과 같은 :root 토큰을 읽는다. 하드코딩 사본을 남기면
// 토큰을 손봤을 때 그림만 옛 색으로 남아 조용히 어긋난다. 폴백은 토큰 부재 시에만 쓰인다.
const CSSVAR = getComputedStyle(document.documentElement);
const tok = (n,fb)=>((CSSVAR.getPropertyValue(n)||"").trim()||fb);
const PAL = { vault:tok("--vault","#0C0A07"), ink:tok("--ink","#E9E0CA"), dim:tok("--dim","#9C9179"),
  gold:tok("--gold","#C6A45E"), goldLit:tok("--gold-lit","#E8C87E"), hair:tok("--hairline","#E6D096") };
const UNKNOWN_KIND = "#888888"; // 종류 팔레트에 없는 노드 — 중립 회색(스캐너 결함 신호)
// 캔버스는 알파를 따로 받지 않는다 — 그릴 색을 미리 합성해 둔다(프레임당 문자열 조립 없음)
function alpha(hex,a){ const h=hex.replace("#","");
  const v = h.length===3 ? h.split("").map(c=>c+c).join("") : h.slice(0,6);
  return "rgba("+parseInt(v.slice(0,2),16)+","+parseInt(v.slice(2,4),16)+","+parseInt(v.slice(4,6),16)+","+a+")"; }
const EDGE_GHOST=alpha(PAL.dim,.07), EDGE_BASE=alpha(PAL.dim,.3),
      EDGE_BASE_SPACE=alpha(PAL.dim,.44), // 3차원은 깊이 밴드가 알파를 나눠 먹는다 — 바닥을 올려둔다
      EDGE_LIT2=alpha(PAL.goldLit,.4), EDGE_LIT=alpha(PAL.goldLit,.75),
      PATH_LINE=alpha(PAL.goldLit,.85), PATH_HEAD=alpha(PAL.goldLit,.9), ARROW=alpha(PAL.goldLit,.8),
      VIA_BASE=alpha(PAL.dim,.24), VIA_LIT=alpha(PAL.goldLit,.55),
      VIA_RING=alpha(PAL.goldLit,.6), VIA_RING_DIM=alpha(PAL.dim,.5),
      HOVER_RING=alpha(PAL.ink,.6), LABEL_HALO=alpha(PAL.vault,.85),
      LANE_LABEL=alpha(PAL.goldLit,.9), LANE_COUNT=alpha(PAL.dim,.9), LANE_TIER=alpha(PAL.dim,.75),
      LANE_RULE=alpha(PAL.hair,.18), LANE_DIV=alpha(PAL.hair,.06);
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

// 성좌는 3차원이다 — 황금각 나선을 구면으로 올려 초기 부피를 준다(물리가 여기서 부푼다).
// 레인 모드는 z=0 평면으로 접힌다.
const nodes = DATA.nodes.map((n,i)=>{
  const t=(i+0.5)/Math.max(1,DATA.nodes.length), zz=1-2*t, rr=Math.sqrt(Math.max(0,1-zz*zz));
  const th=i*2.399963, span=60+Math.sqrt(i)*22;
  return { ...n, x: Math.cos(th)*span*rr||Math.cos(th)*span, y: Math.sin(th)*span*rr||Math.sin(th)*span,
    z: zz*span*0.55, vx:0, vy:0, vz:0 };
});
const byId = Object.fromEntries(nodes.map(n=>[n.id,n]));
const edges = DATA.edges.filter(e=>byId[e.source]&&byId[e.target]);
const degree = {}; edges.forEach(e=>{ degree[e.source]=(degree[e.source]||0)+1; degree[e.target]=(degree[e.target]||0)+1; });
const kindCount = {}; nodes.forEach(n=>{ kindCount[n.kind]=(kindCount[n.kind]||0)+1; });
const edgeKindCount = {}; edges.forEach(e=>{ edgeKindCount[e.kind]=(edgeKindCount[e.kind]||0)+1; });
// 상시 라벨 — 차수에 종류 가중(아키텍처 종류 우대): 순수 차수는 UI 킷 원자(Button·Card)가 독점한다
const KIND_BOOST={page:400,route:400,store:300,command:220,job:220,event:220,model:220,
  api_call:160,db_access:160,external_service:160,composable:120,component:0};
const topLabel = new Set(nodes.filter(n=>n.kind!=="file")
  .sort((a,b)=>((KIND_BOOST[b.kind]||0)+(degree[b.id]||0))-((KIND_BOOST[a.kind]||0)+(degree[a.id]||0)))
  .slice(0,14).map(n=>n.id));

// ── 플로우 인접(개념→개념) — 체인 추적·레인 정렬의 재료 ──
const OUT={}, IN={};
for(const e of edges){ if(byId[e.source].kind==="file") continue;
  (OUT[e.source] ??= []).push(e); (IN[e.target] ??= []).push(e); }

// ── 레인(계층 컬럼) — 아키텍처 흐름 순서, 비어 있는 레인은 접힌다 ──
const LANES=[
  {label:"page",kinds:["page"]},
  {label:"component",kinds:["component"],tiered:true},
  {label:"composable · store",kinds:["composable","store"]},
  {label:"service",kinds:["service"]},
  {label:"api_call",kinds:["api_call"]},
  {label:"route",kinds:["route"]},
  {label:"command · job · event",kinds:["command","job","event"]},
  {label:"model",kinds:["model"]},
  {label:"db · external",kinds:["db_access","external_service"]},
];
const laneOf={}; LANES.forEach((l,i)=>l.kinds.forEach(k=>laneOf[k]=i));
const TIER_NAMES=["atoms","molecules","organisms","etc"];
function tier(n){ const f=(n.files&&n.files[0]&&n.files[0].file)||"";
  if(f.includes("/atoms/")) return 0;
  if(f.includes("/molecules/")) return 1;
  if(f.includes("/organisms/")) return 2;
  return 3; }

let off={x:0,y:0}, scale=1, active=new Set(KIND_ORDER.filter(k=>kindCount[k])), query="",
  selected=null, hover=null, neighbors=new Set(), bridges=new Set(), previewKind=null,
  userCam=false, hot = REDUCED ? 0 : 260;
let laneMode=false, laneHeads=[], laneH=0, morph=null, starSaved=false, settled=false, fileWasOn=true;
let space=true, orbiting=false; // space = 성좌(3차원 시냅스 공간) · 레인은 평면으로 접힌다
let trace=null, traceT=0, traceRaf=0, showCand=true, activeEdge=new Set(EDGE_KINDS);
let cvx0=-1e9, cvy0=-1e9, cvx1=1e9, cvy1=1e9;

function esc(v){ const e=document.createElement("span"); e.textContent=String(v??""); return e.innerHTML.replace(/"/g,"&quot;"); }
function radius(n){ return n.kind==="file" ? 3.2 : Math.min(11, 5+(degree[n.id]||0)*0.55); }
function matches(n){ return !query || (n.id+" "+n.name).toLowerCase().includes(query); }
// 노드 상태: 0 숨김(kind off·후보 off) · 1 유령(검색 불일치) · 2 표시
// 체인 추적 중인 노드는 필터와 무관하게 표시 — 체인은 전체 플로우를 따른다
function state(n){
  if(trace && trace.nodes.has(n.id)) return 2;
  if(!active.has(n.kind)) return 0;
  if(!showCand && n.confidence==="candidate") return 0;
  if(query && !matches(n)) return 1; return 2;
}

function tick(){
  for(const n of nodes){ n.vx*= .82; n.vy*= .82; n.vz*= .82;
    n.vx-=n.x*0.0018; n.vy-=n.y*0.0018; n.vz-=n.z*0.0024; } // z는 살짝 더 조여 납작하지 않게 유지
  // ponytail: 큰 그래프는 근접 인덱스 80개만 반발; 전역 공간 인덱스는 실제 병목이 확인되면 추가한다.
  const repelSpan=nodes.length>800 ? 80 : nodes.length;
  for(let i=0;i<nodes.length;i++) for(let j=i+1;j<Math.min(nodes.length,i+repelSpan);j++){
    const a=nodes[i],b=nodes[j]; let dx=b.x-a.x, dy=b.y-a.y, dz=b.z-a.z;
    const d2=dx*dx+dy*dy+dz*dz+0.01; if(d2>16000) continue;
    const f=140/d2; dx*=f; dy*=f; dz*=f;
    a.vx-=dx; a.vy-=dy; a.vz-=dz; b.vx+=dx; b.vy+=dy; b.vz+=dz; }
  for(const e of edges){ const a=byId[e.source], b=byId[e.target];
    const dx=b.x-a.x, dy=b.y-a.y, dz=b.z-a.z;
    const d=Math.hypot(dx,dy,dz)||1, f=(d-46)*0.004;
    a.vx+=dx/d*f; a.vy+=dy/d*f; a.vz+=dz/d*f;
    b.vx-=dx/d*f; b.vy-=dy/d*f; b.vz-=dz/d*f; }
  for(const n of nodes){ n.x+=n.vx; n.y+=n.vy; n.z+=n.vz; }
}

// ── 카메라 — 궤도(요·피치) + 원근. 투영은 월드 단위로 끝나므로 아래 ctx 변환(팬·줌·fit)이 그대로 산다 ──
// 초점거리는 결정이다: 1100은 깊이가 읽히되 가장자리가 어안으로 휘지 않는 지점.
const FOCAL=1100;
// 시작 앵글도 결정이다 — 정면 데드센터는 미결정이다. 살짝 틀어 부피를 먼저 읽힌다.
let yaw=0.42, pitch=-0.26, drift=0;
function project(){
  if(!space){ for(const n of nodes){ n.px=n.x; n.py=n.y; n.pz=0; n.k=1; } return; }
  const cy=Math.cos(yaw), sy=Math.sin(yaw), cp=Math.cos(pitch), sp=Math.sin(pitch);
  for(const n of nodes){
    const xr=n.x*cy - n.z*sy;          // 요 회전
    const zt=n.x*sy + n.z*cy;
    const yr=n.y*cp - zt*sp;           // 피치 회전
    const zr=n.y*sp + zt*cp;
    const k=FOCAL/(FOCAL+zr);          // 원근 — 가까울수록 크고 밝다
    n.px=xr*k; n.py=yr*k; n.pz=zr; n.k=k;
  }
}
// 깊이 안개 — 먼 것은 금고색으로 잠긴다. 이것이 3D를 읽히게 하는 유일한 장치다(블룸 스택 금지).
function depth(k){ return Math.max(0.16, Math.min(1, (k-0.72)/0.62)); }

function sizeCanvas(){
  canvas.width = stage.clientWidth*devicePixelRatio;
  canvas.height = stage.clientHeight*devicePixelRatio;
}
function fit(){
  if(!nodes.length) return;
  project(); // 투영된 자리로 재야 궤도를 돌린 뒤에도 전경이 맞는다
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,seen=false;
  for(const n of nodes){ if(!state(n)) continue; seen=true;
    if(n.px<x0)x0=n.px; if(n.px>x1)x1=n.px; if(n.py<y0)y0=n.py; if(n.py>y1)y1=n.py; }
  if(!seen) return;
  const bw=Math.max(60,x1-x0), bh=Math.max(60,y1-y0);
  // 레인 모드는 가로 전폭이 크다 — 좁은 뷰포트에서도 전경이 들어오게 플로어를 낮춘다
  scale=Math.max(laneMode?0.06:.25, Math.min(2.5,
    Math.min(canvas.width*0.84/(bw*devicePixelRatio), canvas.height*0.8/(bh*devicePixelRatio))));
  off.x=-(x0+x1)/2*scale*devicePixelRatio;
  off.y=-(y0+y1)/2*scale*devicePixelRatio;
}

// ── 레인 배치 — 결정론(물리 없음): 바리센터 2스윕 정렬 후 계층 컬럼 그리드 ──
function laneLayout(){
  const vis=nodes.filter(n=>n.kind!=="file"&&laneOf[n.kind]!=null);
  laneHeads=[];
  if(!vis.length) return;
  const H=Math.max(380, Math.min(1700, Math.ceil(Math.sqrt(vis.length))*38));
  const rowH=17, rows=Math.max(6,Math.floor(H/rowH));
  const pos={};
  let order=vis.slice().sort((a,b)=>a.id.localeCompare(b.id));
  order.forEach((n,i)=>pos[n.id]=i);
  for(let s=0;s<2;s++){ // 이웃 평균 순위로 레인 내 순서를 정해 교차를 줄인다
    const avg={};
    for(const n of order){ let sum=0,c=0;
      for(const e of (OUT[n.id]||[])) if(pos[e.target]!=null){ sum+=pos[e.target]; c++; }
      for(const e of (IN[n.id]||[]))  if(pos[e.source]!=null){ sum+=pos[e.source]; c++; }
      avg[n.id]=c ? sum/c : pos[n.id]; }
    order=order.slice().sort((a,b)=>avg[a.id]-avg[b.id]||a.id.localeCompare(b.id));
    order.forEach((n,i)=>pos[n.id]=i);
  }
  const colW=34, gapG=18, laneGap=96; let x=0;
  for(let li=0;li<LANES.length;li++){
    const lane=LANES[li];
    const members=order.filter(n=>laneOf[n.kind]===li);
    if(!members.length) continue;
    const groups=lane.tiered
      ? [0,1,2,3].map(t=>({t,g:members.filter(n=>tier(n)===t)})).filter(o=>o.g.length)
      : [{t:-1,g:members}];
    const x0=x, tiers=[];
    for(const o of groups){
      const gx0=x;
      o.g.forEach((n,i)=>{ const col=Math.floor(i/rows);
        n.tx=x+col*colW; n.ty=-H/2+(i%rows)*rowH+((col%2)*rowH*0.5); n.tz=0; });
      x+=Math.ceil(o.g.length/rows)*colW;
      if(o.t>=0) tiers.push({name:TIER_NAMES[o.t], x0:gx0, n:o.g.length});
      x+=gapG;
    }
    x-=gapG;
    laneHeads.push({label:lane.label, x0, x1:x, n:members.length, tiers});
    x+=laneGap;
  }
  const w=x-laneGap;
  for(const n of vis){ n.tx-=w/2; }
  for(const h of laneHeads){ h.x0-=w/2; h.x1-=w/2;
    for(const t of h.tiers) t.x0-=w/2; }
  laneH=H;
}

// ── 배치 모드 전환 — 성좌(물리) ⇄ 레인, 220ms 위치 보간(reduced-motion은 즉시) ──
function startMorph(){
  for(const n of nodes){ n.mx=n.x; n.my=n.y; n.mz=n.z;
    if(n.tx==null){ n.tx=n.x; n.ty=n.y; n.tz=n.z; } }
  morph={t0:performance.now()};
  requestAnimationFrame(morphStep);
}
function morphStep(now){
  if(!morph) return;
  let k=Math.min(1,(now-morph.t0)/220); k=1-Math.pow(1-k,3);
  for(const n of nodes){ n.x=n.mx+(n.tx-n.mx)*k; n.y=n.my+(n.ty-n.my)*k;
    n.z=n.mz+((n.tz??0)-n.mz)*k; }
  if(!userCam) fit();
  draw();
  if(k<1) requestAnimationFrame(morphStep); else morph=null;
}
function setMode(lane, opt){
  if(lane===laneMode) return;
  laneMode=lane;
  space=!lane; // 레인은 결정론 평면 — 원근·성진·신호는 성좌의 것이다
  stage.classList.toggle("flat", lane);
  document.getElementById("modeStar").setAttribute("aria-pressed",String(!lane));
  document.getElementById("modeLane").setAttribute("aria-pressed",String(lane));
  const fchip=[...legend.children].find(x=>x.dataset.kind==="file");
  if(lane){
    if(!starSaved){ for(const n of nodes){ n.sx=n.x; n.sy=n.y; n.sz=n.z; } starSaved=true; }
    hot=0;
    fileWasOn=active.has("file"); active.delete("file");
    if(fchip){ fchip.disabled=true; fchip.title="레인 모드 — 파일 노드는 접어둔다(증거·연계는 패널에)"; }
    laneLayout();
  } else {
    if(fchip){ fchip.disabled=false; fchip.removeAttribute("title"); }
    if(fileWasOn) active.add("file");
    if(!starSaved){ for(const n of nodes){ n.sx=n.x; n.sy=n.y; n.sz=n.z; } starSaved=true; }
    if(!settled){ // 성좌를 아직 정착시킨 적이 없다 — 레인 좌표를 잠시 치우고 시간 예산 정착
      for(const n of nodes){ n.lx=n.x; n.ly=n.y; n.lz=n.z; n.x=n.sx; n.y=n.sy; n.z=n.sz; }
      const t0=performance.now(); let i=0;
      while(i<260 && performance.now()-t0<450){ tick(); i++; }
      for(const n of nodes){ n.sx=n.x; n.sy=n.y; n.sz=n.z; n.x=n.lx; n.y=n.ly; n.z=n.lz; }
      settled=true;
    }
    for(const n of nodes){ n.tx=n.sx; n.ty=n.sy; n.tz=n.sz; }
  }
  const hintEl=document.getElementById("hint");
  if(hintEl) hintEl.textContent = lane
    ? "드래그 팬 · 휠·핀치 줌 · 클릭 선택 · 키: 화살표 / + − / 0 전체 / v 성좌⇄레인 / t 체인 / Esc"
    : "드래그 궤도 · Shift+드래그 팬 · 휠·핀치 줌 · 클릭 선택 · 키: 화살표 궤도 / + − / 0 전체 / v 성좌⇄레인 / t 체인 / Esc";
  syncChips(); writeHash();
  if(selected && !state(selected)) select(null);
  userCam=false;
  if((opt&&opt.snap)||REDUCED){
    for(const n of nodes){ if(n.tx!=null){ n.x=n.tx; n.y=n.ty; n.z=n.tz??0; } }
    fit(); draw();
  } else startMorph();
  if(space) startLoop(); // 성좌로 돌아오면 신호·표류가 다시 산다
}

// 깊이 밴드 — 시냅스 섬유가 앞뒤로 갈라져 보이게 알파를 3단으로. 평면(레인)에서는 1단.
const DEPTH_BANDS=[[0,0.93,0.34],[0.93,1.07,0.72],[1.07,9,1]];
function strokeEdges(list, style, width){
  ctx.strokeStyle=style; ctx.lineWidth=width;
  const bands = space ? DEPTH_BANDS : [[-9,9,1]];
  for(const [lo,hi,ba] of bands){
    ctx.globalAlpha=ba;
    for(const k of EDGE_KINDS){
      // 저줌 LOD — 대시 패턴은 판독 불가 구간(0.5x 미만)에서 실선으로 접는다
      ctx.setLineDash(scale<0.5 ? [] : EDGE_DASH[k].map(v=>v/scale));
      ctx.beginPath();
      for(const e of list){ if(e.kind!==k) continue;
        const a=byId[e.source], b=byId[e.target];
        if(space){ const mk=(a.k+b.k)/2; if(mk<lo||mk>=hi) continue; }
        if((a.px<cvx0&&b.px<cvx0)||(a.px>cvx1&&b.px>cvx1)||(a.py<cvy0&&b.py<cvy0)||(a.py>cvy1&&b.py>cvy1)) continue;
        ctx.moveTo(a.px,a.py); ctx.lineTo(b.px,b.py); }
      ctx.stroke();
    }
  }
  ctx.globalAlpha=1;
  ctx.setLineDash([]);
}

// ── 우주 배경 — 화면 공간 시차 성진(줌에 딸려 커지지 않는다). 결정론 LCG라 렌더가 재현된다 ──
const STARS=(()=>{ let s=20260726;
  const rnd=()=>{ s=(s*1103515245+12345)&0x7fffffff; return s/0x7fffffff; };
  return Array.from({length:260},()=>({ux:rnd(),uy:rnd(),layer:1+Math.floor(rnd()*3),a:.22+rnd()*.5,r:rnd()}));
})();
function drawStars(w,h){
  const mod=(v,m)=>((v%m)+m)%m;
  // 앞 층일수록 크고 밝고 더 많이 흐른다 — 시차가 깊이를 말한다
  for(const st of STARS){
    const px=mod(st.ux + yaw*st.layer*0.055 + off.x/(w*14), 1)*w;
    const py=mod(st.uy + pitch*st.layer*0.045 + off.y/(h*14), 1)*h;
    ctx.globalAlpha=st.a*(0.42+st.layer*0.19);
    ctx.fillStyle = st.r>0.93 ? PAL.goldLit : PAL.ink; // 드물게 금빛 하나 — 단색 점묘가 되지 않게
    ctx.beginPath(); ctx.arc(px,py,(0.45+st.r*0.95)*(0.6+st.layer*0.3)*devicePixelRatio,0,7); ctx.fill();
  }
  ctx.globalAlpha=1;
}

// ── 소마 글로우 — 종류색 스프라이트 1장을 캐시해 재사용(프레임당 그라디언트 생성 금지) ──
const glowCache={};
function glowSprite(col){
  if(glowCache[col]) return glowCache[col];
  const S=64, c=document.createElement("canvas"); c.width=c.height=S;
  const g=c.getContext("2d"), grd=g.createRadialGradient(S/2,S/2,0,S/2,S/2,S/2);
  grd.addColorStop(0, alpha(col,.5)); grd.addColorStop(.4, alpha(col,.14)); grd.addColorStop(1, alpha(col,0));
  g.fillStyle=grd; g.fillRect(0,0,S,S);
  return glowCache[col]=c;
}
// 시냅스 신호 — 허브 사이 상위 엣지 일부에만 신호점이 흐른다(전 엣지에 걸면 프레임을 먹는다)
const PULSE_EDGES=edges.filter(e=>byId[e.source].kind!=="file")
  .sort((a,b)=>((degree[b.source]||0)+(degree[b.target]||0))-((degree[a.source]||0)+(degree[a.target]||0)))
  .slice(0,42).map((e,i)=>({e,phase:i/42}));

// ── 체인 추적 — 선택 노드에서 플로우 상·하류 BFS(깊이 4) ──
function traceLoop(ts){
  if(!trace){ traceRaf=0; return; }
  traceT=(ts/34)%600;
  draw();
  traceRaf=requestAnimationFrame(traceLoop);
}
function runTrace(n){
  const eset=new Set(), nset=new Set([n.id]), up=[], down=[];
  for(const dir of [{adj:OUT,rev:false,acc:down},{adj:IN,rev:true,acc:up}]){
    let frontier=[n.id];
    for(let d=1; d<=4 && frontier.length; d++){
      const next=[];
      for(const id of frontier) for(const e of (dir.adj[id]||[])){
        if(eset.has(e)) continue; eset.add(e);
        const o=dir.rev ? e.source : e.target;
        if(!nset.has(o)){ nset.add(o); next.push(o); dir.acc.push({id:o,d,up:dir.rev}); } }
      frontier=next;
    }
  }
  trace={eset, nodes:nset, up, down,
    cam:{x:off.x, y:off.y, s:scale, u:userCam}}; // 해제 시 카메라 복원용
  fitTrace();
  // 저자 모션 — 유방향 대시 흐름은 350엣지 이하·모션 허용에서만(그 외 정적 화살촉)
  if(!REDUCED && eset.size<=350 && !traceRaf) traceRaf=requestAnimationFrame(traceLoop);
}
function fitTrace(){ // 체인 범위로 카메라 — 추적한 이야기가 화면에 들어온다
  if(!trace||trace.nodes.size<2) return;
  project();
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  for(const id of trace.nodes){ const n=byId[id]; if(!n) continue;
    if(n.px<x0)x0=n.px; if(n.px>x1)x1=n.px; if(n.py<y0)y0=n.py; if(n.py>y1)y1=n.py; }
  const bw=Math.max(120,x1-x0), bh=Math.max(120,y1-y0);
  scale=Math.max(laneMode?0.06:.25, Math.min(2.2,
    Math.min(canvas.width*0.78/(bw*devicePixelRatio), canvas.height*0.72/(bh*devicePixelRatio))));
  off.x=-(x0+x1)/2*scale*devicePixelRatio;
  off.y=-(y0+y1)/2*scale*devicePixelRatio;
  userCam=true;
}
function clearTrace(){
  if(trace&&trace.cam){ off.x=trace.cam.x; off.y=trace.cam.y; scale=trace.cam.s; userCam=trace.cam.u; }
  trace=null; traceT=0;
}

// ── 뷰 상태 영속 — URL hash: 리로드 생존 + 공유 앵커(카메라는 제외, fit이 소유) ──
let hashT=0;
function writeHash(){
  clearTimeout(hashT);
  hashT=setTimeout(()=>{
    const allK=KIND_ORDER.filter(k=>kindCount[k]);
    const koff=allK.filter(k=>!active.has(k));
    const eoff=EDGE_KINDS.filter(k=>!activeEdge.has(k));
    const p=["m="+(laneMode?"lane":"star")];
    if(koff.length) p.push("koff="+koff.join(","));
    if(eoff.length) p.push("eoff="+eoff.join(","));
    if(!showCand) p.push("cand=0");
    if(query) p.push("q="+encodeURIComponent(query));
    if(selected) p.push("sel="+encodeURIComponent(selected.id));
    try{ history.replaceState(null,"","#"+p.join("&")); }catch(e){ /* file:// 제약 등 — 영속만 포기 */ }
  },150);
}
function readHash(){
  if(!location.hash||location.hash.length<2) return null;
  const o={};
  for(const kv of location.hash.slice(1).split("&")){ const i=kv.indexOf("=");
    if(i>0){ try{ o[kv.slice(0,i)]=decodeURIComponent(kv.slice(i+1)); }catch(e){} } }
  return o;
}

function draw(){
  const w=canvas.width, h=canvas.height;
  ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,w,h);
  if(!nodes.length){
    ctx.textAlign="center"; ctx.font=(13*devicePixelRatio)+"px "+FONT;
    ctx.fillStyle=PAL.ink; ctx.fillText("그래프가 비어 있다", w/2, h/2-12*devicePixelRatio);
    ctx.fillStyle=PAL.dim; ctx.fillText("asgard map scan으로 관계를 수집한다", w/2, h/2+14*devicePixelRatio);
    ctx.textAlign="left"; return;
  }
  project();
  if(space) drawStars(w,h);
  let visN=0;
  for(const n of nodes) if(state(n)) visN++;
  updateVis(visN);
  if(!visN){ // 필터로 전멸 — 캔버스는 침묵하지 않는다(복구 버튼은 DOM #visreset)
    ctx.textAlign="center"; ctx.font=(13*devicePixelRatio)+"px "+FONT;
    ctx.fillStyle=PAL.dim;
    ctx.fillText("필터로 모든 노드가 숨겨졌다", w/2, h/2-40*devicePixelRatio);
    ctx.textAlign="left"; return;
  }
  ctx.translate(w/2+off.x, h/2+off.y); ctx.scale(scale*devicePixelRatio, scale*devicePixelRatio);
  ctx.textBaseline="middle";
  const focus=selected;
  // 월드 좌표 뷰포트 — 노드·라벨 패스는 화면 밖(여유 60)을 건너뛴다
  const vx0=(-w/2-off.x)/(scale*devicePixelRatio)-60, vy0=(-h/2-off.y)/(scale*devicePixelRatio)-60;
  const vx1=vx0+w/(scale*devicePixelRatio)+120, vy1=vy0+h/(scale*devicePixelRatio)+120;
  const inView=n=>n.px>vx0&&n.px<vx1&&n.py>vy0&&n.py<vy1;
  cvx0=vx0; cvy0=vy0; cvx1=vx1; cvy1=vy1; // 엣지 컬링 경계(strokeEdges 공유)
  const lit=[], lit2=[], base=[], ghost=[], via=[], viaN={}, path=[];
  for(const e of edges){
    // 엣지 kind 필터 — 단 체인 추적 경로는 필터와 무관하게 남긴다
    if(!activeEdge.has(e.kind) && !(trace&&trace.eset.has(e))) continue;
    const a=byId[e.source], b=byId[e.target];
    const sa=state(a), sb=state(b);
    if(!sa||!sb){ // 파일이 필터로 꺼져도 파일 경유 연계(실제 구성)는 접점 스터브로 남긴다
      if(!sa && !laneMode && a.kind==="file" && sb===2){ via.push(e); viaN[a.id]=(viaN[a.id]||0)+1; }
      continue; }
    if(trace){ if(trace.eset.has(e)) path.push(e); else ghost.push(e); }
    else if(focus){ if(e.source===focus.id||e.target===focus.id) lit.push(e);
      else if(bridges.has(e.source)) lit2.push(e); // 선택 개념의 파일 경유 2-hop 구간
      else ghost.push(e); }
    else if(query && sa<2 && sb<2) ghost.push(e);
    else if(previewKind && a.kind!==previewKind && b.kind!==previewKind) ghost.push(e);
    else base.push(e); }
  strokeEdges(ghost, EDGE_GHOST, 0.8/scale);
  strokeEdges(base, space?EDGE_BASE_SPACE:EDGE_BASE, 0.9/scale);
  strokeEdges(lit2, EDGE_LIT2, 1.1/scale);
  strokeEdges(lit, EDGE_LIT, 1.5/scale);
  if(trace && path.length){ // 체인 경로 — 유방향 대시가 하류 방향으로 흐른다(모션 불가 시 정적)
    ctx.strokeStyle=PATH_LINE; ctx.lineWidth=1.6/scale;
    ctx.setLineDash([7/scale,5/scale]); ctx.lineDashOffset=-traceT/scale;
    ctx.beginPath();
    for(const e of path){ const a=byId[e.source], b=byId[e.target];
      ctx.moveTo(a.px,a.py); ctx.lineTo(b.px,b.py); }
    ctx.stroke();
    ctx.setLineDash([]); ctx.lineDashOffset=0;
    ctx.fillStyle=PATH_HEAD;
    for(const e of path){ const a=byId[e.source], b=byId[e.target];
      const dx=b.px-a.px, dy=b.py-a.py, d=Math.hypot(dx,dy)||1, ux=dx/d, uy=dy/d;
      const rr=radius(b)*b.k+2/scale, s=7/scale, tx=b.px-ux*rr, ty=b.py-uy*rr;
      ctx.beginPath(); ctx.moveTo(tx,ty);
      ctx.lineTo(tx-ux*s-uy*s*0.5, ty-uy*s+ux*s*0.5);
      ctx.lineTo(tx-ux*s+uy*s*0.5, ty-uy*s-ux*s*0.5);
      ctx.closePath(); ctx.fill(); }
  }
  { // 은닉 파일 접점 — 연계 2개 이상만 의미가 있다(외줄 스터브 제외)
    const viaBase=[], viaLit=[];
    for(const e of via){ if(viaN[e.source]<2) continue;
      if(!focus) viaBase.push(e); else if(bridges.has(e.source)) viaLit.push(e); }
    if(viaBase.length||viaLit.length){
      ctx.setLineDash([2/scale,3.5/scale]);
      for(const [list,style,width] of [[viaBase,VIA_BASE,0.8],[viaLit,VIA_LIT,1.2]]){
        if(!list.length) continue;
        ctx.strokeStyle=style; ctx.lineWidth=width/scale; ctx.beginPath();
        for(const e of list){ const a=byId[e.source], b=byId[e.target];
          ctx.moveTo(a.px,a.py); ctx.lineTo(b.px,b.py); }
        ctx.stroke(); }
      ctx.setLineDash([]);
      ctx.lineWidth=1/scale;
      for(const id in viaN){ if(viaN[id]<2) continue;
        if(focus && !bridges.has(id)) continue;
        const f=byId[id];
        ctx.strokeStyle = focus ? VIA_RING : VIA_RING_DIM;
        ctx.beginPath(); ctx.arc(f.px,f.py,2.2*f.k,0,7); ctx.stroke(); }
    }
  }
  if(focus && lit.length){ // 방향(파일 → 개념)은 선택 시에만 화살촉으로 노출
    ctx.fillStyle=ARROW;
    for(const e of lit){ const a=byId[e.source], b=byId[e.target];
      const dx=b.px-a.px, dy=b.py-a.py, d=Math.hypot(dx,dy)||1, ux=dx/d, uy=dy/d;
      const rr=radius(b)*b.k+2/scale, s=7/scale, tx=b.px-ux*rr, ty=b.py-uy*rr;
      ctx.beginPath(); ctx.moveTo(tx,ty);
      ctx.lineTo(tx-ux*s-uy*s*0.5, ty-uy*s+ux*s*0.5);
      ctx.lineTo(tx-ux*s+uy*s*0.5, ty-uy*s-ux*s*0.5);
      ctx.closePath(); ctx.fill(); } }
  // 시냅스 신호 — 허브 사이를 오가는 점. 정지 상태에서도 망이 살아 있다는 유일한 신호다.
  if(space && !REDUCED && PULSE_EDGES.length && !trace && !focus){
    ctx.fillStyle=PATH_HEAD;
    for(const p of PULSE_EDGES){
      const a=byId[p.e.source], b=byId[p.e.target];
      if(!state(a)||!state(b)) continue;
      const u=((pulseT+p.phase)%1);
      const x=a.px+(b.px-a.px)*u, y=a.py+(b.py-a.py)*u;
      if(x<cvx0||x>cvx1||y<cvy0||y>cvy1) continue;
      const kk=a.k+(b.k-a.k)*u;
      ctx.globalAlpha=depth(kk)*0.85*Math.sin(u*Math.PI); // 양 끝에서 사그라든다
      ctx.beginPath(); ctx.arc(x,y,1.7*kk/scale*Math.max(1,scale),0,7); ctx.fill();
    }
    ctx.globalAlpha=1;
  }
  // 페인터 순서 — 먼 것부터. 3차원에서 앞뒤가 뒤집히면 깊이가 통째로 무너진다.
  const drawList=[];
  for(const n of nodes){ const s=state(n); if(!s||!inView(n)) continue; drawList.push(n); }
  if(space) drawList.sort((a,b)=>b.pz-a.pz);
  const dimOf=(n,s)=>(s===1)
    ||(trace ? !trace.nodes.has(n.id) : (focus&&n!==selected&&!neighbors.has(n.id)))
    ||(previewKind&&n.kind!==previewKind);
  if(space){ // 소마 글로우 — 허브만, 가산 합성 1패스(블룸·플레어 스택 없음)
    ctx.globalCompositeOperation="lighter";
    for(const n of drawList){ const r=radius(n)*n.k;
      if(r<6.4||n.kind==="file") continue;
      if(dimOf(n,state(n))) continue;
      const g=glowSprite(KIND_COLORS[n.kind]||UNKNOWN_KIND), gr=r*3.4;
      ctx.globalAlpha=depth(n.k)*0.9;
      ctx.drawImage(g, n.px-gr, n.py-gr, gr*2, gr*2); }
    ctx.globalCompositeOperation="source-over"; ctx.globalAlpha=1;
  }
  for(const n of drawList){ const s=state(n);
    const r=radius(n)*n.k, dim=dimOf(n,s);
    ctx.globalAlpha = dim ? .16 : (space ? depth(n.k) : 1);
    const col=KIND_COLORS[n.kind]||UNKNOWN_KIND;
    ctx.beginPath(); ctx.arc(n.px,n.py,r,0,7);
    if(n.confidence==="candidate"){ ctx.strokeStyle=col; // 빈 원이 저줌에서 채운 원으로 뭉개지지 않게 링 폭을 화면 반지름에 비례 클램프
      ctx.lineWidth=Math.min(1.4, Math.max(0.7, r*scale*0.42))/scale; ctx.stroke(); }
    else { ctx.fillStyle=col; ctx.fill(); }
    ctx.globalAlpha=1; }
  if(hover && hover!==selected){ ctx.strokeStyle=HOVER_RING; ctx.lineWidth=1.2/scale;
    ctx.beginPath(); ctx.arc(hover.px,hover.py,radius(hover)*hover.k+3/scale,0,7); ctx.stroke(); }
  if(selected){ ctx.strokeStyle=PAL.goldLit; ctx.lineWidth=1.6/scale;
    ctx.beginPath(); ctx.arc(selected.px,selected.py,radius(selected)*selected.k+3.5/scale,0,7); ctx.stroke(); }
  // 라벨 정책 — 기본 허브 14개, 검색 일치 30개, 줌인 시 개념 전체(1.4x)·파일까지(2.4x).
  // 우선순위(선택>호버>이웃>차수) 정렬 후 화면 공간 충돌 시 낮은 쪽을 접는다.
  const allConcept=scale>=1.4, allFiles=scale>=2.4;
  ctx.font=(11/scale).toFixed(2)+"px "+FONT;
  ctx.lineWidth=3/scale; ctx.strokeStyle=LABEL_HALO;
  let qLabels=0;
  const cands=[];
  for(const n of nodes){ if(state(n)!==2||!inView(n)) continue;
    if(trace){ if(!trace.nodes.has(n.id)&&n!==hover) continue; }
    else if(focus&&n!==selected&&!neighbors.has(n.id)) continue;
    const concept=n.kind!=="file";
    let show=n===selected||n===hover;
    if(!show&&trace&&trace.nodes.has(n.id)) show=true;
    if(!show&&focus&&concept&&neighbors.has(n.id)) show=true;
    if(!show&&concept&&(allConcept||topLabel.has(n.id))) show=true;
    if(!show&&!concept&&allFiles) show=true;
    if(!show&&query&&concept&&qLabels<30){ show=true; qLabels++; }
    if(!show) continue;
    const pri = n===selected ? 0 : n===hover ? 1 : (focus&&neighbors.has(n.id)) ? 2 : 3;
    cands.push({n, pri, deg:degree[n.id]||0, concept}); }
  // 가까운 것이 라벨 자리를 이긴다 — 3차원에서 뒤에 있는 이름이 앞을 가리면 깊이가 거짓말이 된다
  cands.sort((a,b)=>a.pri-b.pri || (space ? b.n.k-a.n.k : 0) || b.deg-a.deg);
  const boxes=[], lh=13/scale;
  for(const c of cands){ const n=c.n;
    const t=n.name.length>26 ? n.name.slice(0,25)+"…" : n.name;
    const lx=n.px+radius(n)*n.k+5/scale;
    const x0=lx, x1=lx+ctx.measureText(t).width, y0=n.py-lh/2, y1=n.py+lh/2;
    let clash=false;
    for(const b of boxes){ if(x0<b.x1&&x1>b.x0&&y0<b.y1&&y1>b.y0){ clash=true; break; } }
    if(clash && c.pri>1) continue;
    boxes.push({x0,x1,y0,y1});
    ctx.globalAlpha = space ? Math.max(.45, depth(n.k)) : 1;
    ctx.strokeText(t,lx,n.py);
    ctx.fillStyle = n===selected ? PAL.goldLit : (c.concept ? PAL.ink : PAL.dim);
    ctx.fillText(t,lx,n.py);
    ctx.globalAlpha=1; }
  ctx.setTransform(1,0,0,1,0,0);
  // 레인 헤더 — 화면 공간(줌과 무관한 판독성): 라벨·카운트·베이스라인·밴드 구분선
  if(laneMode&&laneHeads.length){
    const SX=v=>v*scale*devicePixelRatio + w/2+off.x;
    const SY=v=>v*scale*devicePixelRatio + h/2+off.y;
    const hy=Math.max(56*devicePixelRatio, SY(-laneH/2)-24*devicePixelRatio);
    ctx.textBaseline="alphabetic";
    // 슬롯 분할 — 각 레인 라벨은 자기 레인 x0에 앵커되고 다음 레인 시작 전까지만 쓴다.
    // 좁으면 말줄임 → 카운트-온리로 축약하되 무명 레인은 만들지 않는다. 스태거·접힘 없음.
    const zbLeft=w-70*devicePixelRatio, zbBottom=176*devicePixelRatio; // 줌바 점유 영역 회피
    for(let i=0;i<laneHeads.length;i++){ const hd=laneHeads[i];
      const x0=SX(hd.x0), x1=SX(hd.x1);
      if(x1<-40||x0>w+40) continue;
      let slotEnd=(i+1<laneHeads.length ? SX(laneHeads[i+1].x0) : w) - 10*devicePixelRatio;
      if(hy<zbBottom) slotEnd=Math.min(slotEnd, zbLeft-6*devicePixelRatio);
      const avail=slotEnd-x0;
      if(avail>8*devicePixelRatio){
        ctx.font="600 "+(10.5*devicePixelRatio)+"px "+FONT;
        const cnt=" "+hd.n, cw=ctx.measureText(cnt).width;
        let lbl=hd.label.toUpperCase();
        while(lbl.length>2 && ctx.measureText(lbl+"…").width+cw>avail) lbl=lbl.slice(0,-1);
        if(lbl!==hd.label.toUpperCase()) lbl=lbl+"…";
        if(ctx.measureText(lbl).width+cw>avail) lbl=""; // 카운트-온리 축약
        const lw=lbl?ctx.measureText(lbl).width:0;
        if(lbl){ ctx.fillStyle=PATH_HEAD; ctx.fillText(lbl, x0, hy); }
        ctx.font=(10.5*devicePixelRatio)+"px "+FONT;
        ctx.fillStyle=LANE_COUNT;
        ctx.fillText(String(hd.n), x0+lw+(lbl?7*devicePixelRatio:0), hy);
      }
      ctx.strokeStyle=LANE_RULE; ctx.lineWidth=1*devicePixelRatio;
      ctx.beginPath(); ctx.moveTo(x0, hy+7*devicePixelRatio);
      ctx.lineTo(Math.max(x1,x0+30*devicePixelRatio), hy+7*devicePixelRatio); ctx.stroke();
      if(hd.tiers.length>1&&scale>0.55){ // 아토믹 서브밴드 — 확대 시에만
        ctx.font=(9.5*devicePixelRatio)+"px "+FONT; ctx.fillStyle=LANE_TIER;
        for(const t of hd.tiers) ctx.fillText(t.name, SX(t.x0), hy+20*devicePixelRatio);
      }
      if(i<laneHeads.length-1){ const nx=laneHeads[i+1];
        const mx=SX((hd.x1+nx.x0)/2);
        if(mx>-10&&mx<w+10){
          ctx.strokeStyle=LANE_DIV;
          ctx.beginPath(); ctx.moveTo(mx, Math.max(0,hy-12*devicePixelRatio));
          ctx.lineTo(mx, Math.min(h,SY(laneH/2)+14*devicePixelRatio)); ctx.stroke(); }
      }
    }
    ctx.textBaseline="middle"; ctx.textAlign="left";
  }
}
// 대규모 그래프는 프레임당 2틱으로 정착 벽시계를 절반으로 줄인다(물리 자체는 동일).
// 물리는 성좌 모드 전용 — 레인 모드는 결정론 배치라 정착 루프가 없다.
// 성좌가 살아 있는 동안만 프레임을 쓴다: 정착 중 · 신호 흐르는 중 · 도착 표류 중.
// 탭이 가려지면 멈추고(배터리), 모션 축소면 애초에 돌지 않는다.
let pulseT=0, raf=0, lastTs=0, lastDraw=0;
const DRIFT_TURNS=1400; // 도착 표류 — 부피를 한 번 읽히고 멈춘다(무한 턴테이블 아님)
function ambient(){ return space && !REDUCED && !document.hidden; }
function loop(ts){
  raf=0;
  const now=ts||performance.now();
  const dt=lastTs ? Math.min(50, now-lastTs) : 16; lastTs=now;
  let live=false, busy=false;
  if(!laneMode && hot-- > 0){ tick(); if(nodes.length>400) tick(); if(!userCam) fit(); live=busy=true; }
  else settled=settled||!laneMode;
  if(ambient()){
    pulseT=(pulseT+dt/5200)%1;                       // 신호 한 바퀴 ≈ 5.2초
    if(!orbiting && drift<DRIFT_TURNS){ yaw+=0.00042*(dt/16); drift++; busy=true; }
    live=true;
  }
  // 유휴 신호만 도는 구간은 30fps로 접는다 — 개발 도구를 열어둔 채 팬을 돌리지 않는다.
  // 정착·표류처럼 눈에 걸리는 구간은 전 프레임으로 그린다.
  if(busy || now-lastDraw >= 32){ lastDraw=now; draw(); }
  if(live) startLoop();
}
function startLoop(){ if(!raf) raf=requestAnimationFrame(loop); }
document.addEventListener("visibilitychange", ()=>{ lastTs=0; if(!document.hidden) startLoop(); });
let lastVis="";
function updateVis(v){
  const t="표시 "+v+" / "+nodes.length;
  if(t!==lastVis){ lastVis=t; document.getElementById("viscount").textContent=t; }
  const vr=document.getElementById("visreset"), show=!v&&nodes.length>0;
  if(vr.hidden===show) vr.hidden=!show;
}
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
  const n=selected, recs=(DATA.records||{})[n.id]||[], col=KIND_COLORS[n.kind]||UNKNOWN_KIND;
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
          +'<i style="background:'+(KIND_COLORS[r.o.kind]||UNKNOWN_KIND)+'"></i>'
          +'<span class="rk">'+esc(r.o.kind)+'</span><span class="rn">'+esc(r.o.name)+'</span>'
          +'<span class="rv">'+esc(vt)+'</span></button></li>'; }).join("")
      +(rel.length>cap ? '<li class="more">+'+(rel.length-cap)+' — trace로 전체 추적</li>' : '')+'</ul>';
  }
  // 체인 추적 — 플로우가 있는 개념만(파일은 증거 캐리어)
  const fIn=(IN[n.id]||[]).length, fOut=(OUT[n.id]||[]).length;
  if(n.kind!=="file" && (fIn||fOut)){
    h+='<h3 class="d-h">'+(trace
        ? '체인 — 노드 '+(trace.nodes.size-1)+' · 엣지 '+trace.eset.size+' · 깊이 4'
        : '체인 — 직결 상류 '+fIn+' · 하류 '+fOut)+'</h3>'
      +'<div class="d-act"><button type="button" id="traceBtn" aria-pressed="'+(trace?"true":"false")+'">'
      +(trace ? '체인 해제 (t)' : '상·하류 4단 추적 (t)')+'</button></div>';
    if(trace){
      const cap=30;
      const row=c=>{ const o=byId[c.id];
        return '<li><button type="button" data-nid="'+esc(c.id)+'">'
          +'<span class="dep">'+(c.up?"‹":"›").repeat(c.d)+'</span>'
          +'<i style="background:'+(KIND_COLORS[o.kind]||UNKNOWN_KIND)+'"></i>'
          +'<span class="rk">'+esc(o.kind)+'</span><span class="rn">'+esc(o.name)+'</span></button></li>'; };
      if(trace.up.length) h+='<ul class="d-rel">'+trace.up.slice(0,cap).map(row).join("")
        +(trace.up.length>cap ? '<li class="more">+'+(trace.up.length-cap)+' 상류 — trace로 전체' : '')+'</ul>';
      if(trace.down.length) h+='<ul class="d-rel">'+trace.down.slice(0,cap).map(row).join("")
        +(trace.down.length>cap ? '<li class="more">+'+(trace.down.length-cap)+' 하류 — trace로 전체' : '')+'</ul>';
      h+='<p class="subhint">체인은 필터와 무관하게 전체 플로우를 따른다 · 깊이 4 · 클릭 = 이동</p>';
    }
  }
  if(recs.length) h+='<h3 class="d-h">관련 기록 — 프로젝트 메모리</h3><ul class="d-rec">'
    +recs.map(r=>'<li><span class="rt">'+esc(r.title)+'</span><span class="rm">'+esc(r.match)+'</span>'
      +'<span class="rf">'+esc(r.file)+'</span></li>').join("")+'</ul>';
  h+='<h3 class="d-h">추적</h3><code class="d-code">asgard map trace --from '+esc(n.id)+'</code>';
  el.innerHTML=h;
}
document.getElementById("detail").addEventListener("click", e=>{
  const tb=e.target.closest("#traceBtn");
  if(tb){ if(trace) clearTrace(); else if(selected) runTrace(selected);
    renderDetail(); draw(); return; }
  const b=e.target.closest("[data-nid]"); if(!b) return;
  const n=byId[b.dataset.nid]; if(!n) return;
  // select가 체인 카메라를 복원하므로, 센터링은 select 이후에 건다
  ensureKind(n.kind); select(n); centerOn(n); scheduleDraw();
});
function select(n, scrollTo){
  clearTrace();
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
  writeHash();
  renderDetail(); draw();
  if(selected && scrollTo && MOBILE.matches)
    document.getElementById("detail").scrollIntoView({behavior:REDUCED?"auto":"smooth", block:"nearest"});
}
function centerOn(n){ userCam=true; project();
  off.x=-n.px*scale*devicePixelRatio; off.y=-n.py*scale*devicePixelRatio; }

// ── 조작반 구성 ──
(function(){
  const c=DATA.counts||{};
  const gauges=[["files",c.files_scanned??0,"스캔한 파일"],["evidence",c.evidence??0,"수집한 file:line 증거"],
    ["nodes",c.nodes??nodes.length,"그래프 노드 — 개념+파일"],["edges",c.edges??edges.length,"그래프 엣지"],
    ["flows",c.flows,"개념→개념 플로우 엣지 — touches·calls·uses·emits"]];
  document.getElementById("stats").innerHTML =
    gauges.filter(g=>g[1]!=null).map(g=>'<span class="g" title="'+g[2]+'"><b>'+esc(g[1])+'</b><i>'+g[0]+'</i></span>').join("")
    +((c.api_links|0)>0 ? '<span class="g link" title="FE api_call ↔ BE route 조인"><b>'+esc(c.api_links)+'</b><i>api-links</i></span>' : '')
    +(DATA.revision ? '<span class="rev" title="'+esc(DATA.revision)+'">rev '+esc((s=>s.includes(":")?s.split(":").pop().slice(0,8):s.slice(0,10))(String(DATA.revision)))+'</span>' : '');
  for(const k of KIND_ORDER){ if(!kindCount[k]) continue;
    const chip=document.createElement("button"); chip.type="button"; chip.className="chip on";
    chip.dataset.kind=k; chip.setAttribute("aria-pressed","true");
    chip.innerHTML='<i style="background:'+(KIND_COLORS[k]||UNKNOWN_KIND)+'"></i>'+esc(k)+' <span class="n">'+kindCount[k]+'</span>';
    chip.onclick=e=>{
      if(e.altKey){ soloKind(k); return; }
      if(active.has(k)) active.delete(k); else active.add(k);
      syncChips(); writeHash();
      if(selected && !active.has(selected.kind)) select(null); else draw(); };
    // 호버 미리보기 — 해당 종류만 밝혀 색만으로 헷갈리는 구분을 즉석에서 푼다(터치는 무시)
    chip.addEventListener("pointerenter", e=>{
      if(e.pointerType==="touch") return; previewKind=k; scheduleDraw(); });
    chip.addEventListener("pointerleave", ()=>{
      if(previewKind===k){ previewKind=null; scheduleDraw(); } });
    legend.appendChild(chip); }
  // 후보 토글 — 구문 미증명(candidate) 노드 표시/숨김
  const candN=nodes.filter(n=>n.confidence==="candidate").length;
  if(candN){
    const cb=document.createElement("button"); cb.type="button"; cb.className="chip on"; cb.id="candTog";
    cb.setAttribute("aria-pressed","true");
    cb.title="구문 미증명 후보 표시/숨김 — 단정 전 소스 확인";
    cb.innerHTML='<i style="background:transparent;border:1.5px solid var(--warn)"></i>후보 <span class="n">'+candN+'</span>';
    cb.onclick=()=>{ showCand=!showCand;
      cb.classList.toggle("on",showCand); cb.setAttribute("aria-pressed",String(showCand));
      writeHash();
      if(selected && !state(selected)) select(null); else draw(); };
    legend.appendChild(cb);
  }
  // 엣지 언어 — 범례가 곧 필터
  document.getElementById("ekinds").innerHTML =
    '<h2 class="sectitle">엣지 언어 — 클릭 = 필터</h2><ul class="ekl">'+EDGE_KINDS.map(k=>{
      const d=EDGE_DASH[k].join(" "), cnt=edgeKindCount[k]||0;
      return '<li><button type="button" data-ek="'+k+'" aria-pressed="true"'+(cnt?'':' disabled')+'>'
        +'<svg viewBox="0 0 28 6" width="28" height="6" aria-hidden="true"><line x1="1" y1="3" x2="27" y2="3" stroke="var(--gold)" stroke-width="1.6"'
        +(d?' stroke-dasharray="'+d+'"':'')+'></line></svg>'
        +esc(k)+' <b>'+cnt+'</b></button></li>'; }).join("")+'</ul>';
  document.getElementById("ekinds").addEventListener("click", e=>{
    const b=e.target.closest("[data-ek]"); if(!b||b.disabled) return;
    const k=b.dataset.ek;
    if(activeEdge.has(k)) activeEdge.delete(k); else activeEdge.add(k);
    b.setAttribute("aria-pressed",String(activeEdge.has(k)));
    writeHash(); draw(); });
  document.getElementById("modeStar").onclick=()=>setMode(false);
  document.getElementById("modeLane").onclick=()=>setMode(true);
})();
function syncChips(){
  for(const c of legend.children){ if(!c.dataset.kind) continue; // 후보 토글은 별도 상태
    const on=active.has(c.dataset.kind);
    c.classList.toggle("on",on); c.setAttribute("aria-pressed",String(on)); }
}
function soloKind(k){ // 단독 보기 — 이미 단독이면 전체 복귀
  const all=KIND_ORDER.filter(x=>kindCount[x]);
  active = (active.size===1 && active.has(k)) ? new Set(all) : new Set([k]);
  syncChips(); writeHash();
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
  if(n) ensureKind(n.kind);
  select(n);
  if(n){ centerOn(n); scheduleDraw(); }
});
const qEl=document.getElementById("q"), qHint=document.getElementById("qhint");
const resEl=document.getElementById("results");
let resIds=[], resIdx=-1;
// 검색 결과 리스트 — 접두 일치 우선, 아키텍처 종류 가중 정렬, 상위 50
function renderResults(){
  resIdx=-1;
  if(!query){ resEl.hidden=true; resEl.innerHTML=""; resIds=[]; return; }
  const q=query;
  resIds=nodes.filter(n=>n.kind!=="file"&&matches(n))
    .sort((a,b)=>{
      const ap=a.name.toLowerCase().startsWith(q)?0:1, bp=b.name.toLowerCase().startsWith(q)?0:1;
      return ap-bp
        || ((KIND_BOOST[b.kind]||0)+(degree[b.id]||0))-((KIND_BOOST[a.kind]||0)+(degree[a.id]||0))
        || a.id.localeCompare(b.id);
    }).slice(0,50).map(n=>n.id);
  resEl.innerHTML=resIds.map(id=>{ const n=byId[id];
    return '<li><button type="button" data-nid="'+esc(n.id)+'">'
      +'<i style="background:'+(KIND_COLORS[n.kind]||UNKNOWN_KIND)+'"></i>'
      +'<span class="rk">'+esc(n.kind)+'</span><span class="rn">'+esc(n.name)+'</span>'
      +'<span class="deg">이웃 '+(degree[n.id]||0)+'</span></button></li>'; }).join("");
  resEl.hidden=!resIds.length;
}
function setResIdx(i){
  resIdx=i;
  [...resEl.children].forEach((li,j)=>li.classList.toggle("act",j===resIdx));
  const li=resEl.children[resIdx]; if(li) li.scrollIntoView({block:"nearest"});
}
function pickResult(id){
  const n=byId[id]; if(!n) return;
  ensureKind(n.kind); select(n); centerOn(n); scheduleDraw();
}
resEl.addEventListener("click", e=>{
  const b=e.target.closest("[data-nid]"); if(b) pickResult(b.dataset.nid);
});
qEl.addEventListener("input", ()=>{
  query=qEl.value.trim().toLowerCase(); buildOptions(); renderResults();
  if(query){ const m=nodes.filter(n=>active.has(n.kind)&&matches(n)).length;
    qHint.hidden=false;
    qHint.textContent = m ? m+"개 일치 — ↑↓ 이동 · Enter 선택" : "일치하는 노드가 없다"; }
  else qHint.hidden=true;
  writeHash(); draw();
});
qEl.addEventListener("keydown", e=>{
  if(e.key==="ArrowDown"&&resIds.length){ e.preventDefault(); setResIdx(Math.min(resIdx+1,resIds.length-1)); return; }
  if(e.key==="ArrowUp"&&resIds.length){ e.preventDefault(); setResIdx(Math.max(resIdx-1,0)); return; }
  if(e.key==="Escape"&&query){ qEl.value=""; qEl.dispatchEvent(new Event("input")); return; }
  if(e.key!=="Enter"||!query) return;
  if(resIdx>=0){ pickResult(resIds[resIdx]); return; }
  if(resIds.length){ pickResult(resIds[0]); return; }
  const n=nodes.find(n=>n.kind!=="file"&&active.has(n.kind)&&matches(n));
  if(n){ select(n); centerOn(n); scheduleDraw(); }
});
document.getElementById("visreset").onclick=()=>{ // 필터 전멸 복구 — 종류·후보·엣지·검색 전부 초기값
  active=new Set(KIND_ORDER.filter(k=>kindCount[k]));
  if(laneMode) active.delete("file");
  showCand=true; activeEdge=new Set(EDGE_KINDS);
  query=""; qEl.value=""; qHint.hidden=true; renderResults();
  const ct=document.getElementById("candTog");
  if(ct){ ct.classList.add("on"); ct.setAttribute("aria-pressed","true"); }
  for(const b of document.querySelectorAll("#ekinds [data-ek]"))
    if(!b.disabled) b.setAttribute("aria-pressed","true");
  syncChips(); buildOptions(); userCam=false; fit(); draw(); writeHash();
};

// ── 카메라: 휠(커서 앵커)·핀치·드래그·키보드 ──
function zoomAt(px,py,ns){
  ns=Math.max(laneMode?0.06:.25,Math.min(4,ns));
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

// 궤도 — 첫 조작이 도착 표류를 끈다(자동 카메라를 멈출 수단이 조작 그 자체다)
function orbitBy(dx,dy){
  orbiting=true;
  yaw += dx*0.006;
  pitch = Math.max(-1.25, Math.min(1.25, pitch + dy*0.006));
}
function hitTest(e){
  const r=canvas.getBoundingClientRect();
  const px=((e.clientX-r.left)*devicePixelRatio-canvas.width/2-off.x)/(scale*devicePixelRatio);
  const py=((e.clientY-r.top)*devicePixelRatio-canvas.height/2-off.y)/(scale*devicePixelRatio);
  let best=null, bd=9/scale;
  // 앞에 있는 것이 먼저 집힌다 — 같은 거리면 카메라에 가까운(k가 큰) 쪽
  for(const n of nodes){ if(state(n)!==2) continue;
    const d=Math.hypot(n.px-px,n.py-py)-radius(n)*n.k;
    if(d<bd || (d<0 && best && n.k>best.k)){ bd=Math.min(bd,d); best=n; } }
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
      const dx=e.clientX-prev.x, dy=e.clientY-prev.y;
      moved+=Math.abs(dx)+Math.abs(dy);
      if(moved>4){
        // 성좌에서 끌기는 궤도다 — 평면 이동은 Shift(또는 두 손가락)로 남겨둔다
        if(space && !e.shiftKey) orbitBy(dx,dy);
        else { off.x+=dx*devicePixelRatio; off.y+=dy*devicePixelRatio; userCam=true; }
        canvas.style.cursor="grabbing"; scheduleDraw(); } }
    pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pinch && pointers.size===2){ const p=[...pointers.values()];
      const d=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)||1, r=canvas.getBoundingClientRect();
      const mx=(p[0].x+p[1].x)/2, my=(p[0].y+p[1].y)/2;
      // 두 손가락은 줌과 팬을 함께 — 터치에서도 평면 이동 수단이 남는다
      if(pinch.mx!=null){ off.x+=(mx-pinch.mx)*devicePixelRatio; off.y+=(my-pinch.my)*devicePixelRatio; userCam=true; }
      pinch.mx=mx; pinch.my=my;
      zoomAt((mx-r.left)*devicePixelRatio, (my-r.top)*devicePixelRatio, pinch.s*d/pinch.d); }
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
  // 성좌에서 화살표는 궤도를 돈다 — 평면 이동은 Shift+화살표
  const orbitKeys = space && !e.shiftKey;
  if(e.key==="ArrowLeft"){ if(orbitKeys) orbitBy(-34,0); else { off.x+=st; userCam=true; } }
  else if(e.key==="ArrowRight"){ if(orbitKeys) orbitBy(34,0); else { off.x-=st; userCam=true; } }
  else if(e.key==="ArrowUp"){ if(orbitKeys) orbitBy(0,-34); else { off.y+=st; userCam=true; } }
  else if(e.key==="ArrowDown"){ if(orbitKeys) orbitBy(0,34); else { off.y-=st; userCam=true; } }
  else if(e.key==="+"||e.key==="=") zoomAt(canvas.width/2,canvas.height/2,scale*1.25);
  else if(e.key==="-"||e.key==="_") zoomAt(canvas.width/2,canvas.height/2,scale*0.8);
  else if(e.key==="0"){ userCam=false; fit(); }
  else if(e.key==="v"||e.key==="V") setMode(!laneMode);
  else if(e.key==="t"||e.key==="T"){
    if(selected&&selected.kind!=="file"){ trace?clearTrace():runTrace(selected); renderDetail(); } }
  else if(e.key==="Escape"){ if(trace){ clearTrace(); renderDetail(); } else select(null); }
  else done=false;
  if(done){ e.preventDefault(); draw(); }
});

new ResizeObserver(()=>{ sizeCanvas(); if(!userCam) fit(); draw(); }).observe(stage);
sizeCanvas();
if(REDUCED){ // 모션 축소 — 애니메이션 없이 즉석 정착(시간 예산 450ms) 후 정적 렌더
  const t0=performance.now(); let i=0;
  while(i<260 && performance.now()-t0<450){ tick(); i++; }
  settled=true;
}
// URL hash 복원 — 명시 상태가 있으면 자동 레인 판단보다 우선한다
const H0=readHash();
if(H0){
  if(H0.koff) for(const k of H0.koff.split(",")) active.delete(k);
  if(H0.eoff) for(const k of H0.eoff.split(",")){
    if(!EDGE_KINDS.includes(k)) continue;
    activeEdge.delete(k);
    const b=document.querySelector('#ekinds [data-ek="'+k+'"]');
    if(b) b.setAttribute("aria-pressed","false");
  }
  if(H0.cand==="0"){ showCand=false;
    const ct=document.getElementById("candTog");
    if(ct){ ct.classList.remove("on"); ct.setAttribute("aria-pressed","false"); } }
  if(H0.q){ query=H0.q.toLowerCase(); qEl.value=H0.q; }
  syncChips();
}
// 대규모 그래프는 레인 모드로 시작 — 결정론 배치라 물리 정착 없이 첫 페인트가 즉시다
if(H0&&H0.m==="lane") setMode(true,{snap:true});
else if(!(H0&&H0.m==="star") && nodes.length>1200
        && Object.keys(kindCount).filter(k=>k!=="file").length>=3)
  setMode(true,{snap:true});
fit(); buildOptions(); renderDetail();
if(H0){
  if(H0.q){ renderResults();
    const m=nodes.filter(n=>active.has(n.kind)&&matches(n)).length;
    qHint.hidden=false;
    qHint.textContent = m ? m+"개 일치 — ↑↓ 이동 · Enter 선택" : "일치하는 노드가 없다"; }
  if(H0.sel&&byId[H0.sel]) select(byId[H0.sel]);
}
if(laneMode) draw(); else startLoop();
</script>
</body>
</html>
"""


# 원복 백업: view_legacy.py — `from .view_legacy import _TEMPLATE_LEGACY as _TEMPLATE`로 전환
def _logo_data_uri() -> str:
    """위그드라실 엠블럼(yggdrasil-mark.png)을 데이터 URI로 — 실패 시 빈 값(img는 onerror로 숨김)."""
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
