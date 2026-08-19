"use strict";
/* 기억 화면 — 개요와 서고(검색·카탈로그·페이지 보기).
 *
 * 두 판이 한 파일에 있는 것은 같은 자료를 읽어서다: 개요는 `catalog`·`usage` 를 세어 요약하고,
 * 서고는 같은 두 배열을 표로 편다. 페이지 상세(`detailHtml`)는 성좌 옆 패널과 서고 행 아래
 * 펼침이 함께 쓰므로 여기서 만들어 `MEM` 에 걸어 둔다.
 *
 * 검색은 서버가 판단한다 — 전문(FTS)·본문 훑기·의미·그래프 네 경로의 결과를 `/api/memory/search`
 * 가 합쳐 주고, 화면은 어느 경로가 이 결과를 물어 왔는지만 표시한다. 그래서 검색 중에는 정렬
 * 칩을 감춘다: 순위를 정하는 것이 점수이지 갱신일이 아니다.
 *
 * 색 값은 이 파일에도 없다. 상태 색은 전부 `var(--...)` 토큰이고, 종류 표식은 `MEM.swatch()` 가
 * `ui/memory.css` 의 `--mem-kind-*` 를 읽어 그린다.
 */
(function(){
const MEM = window.MEM = window.MEM || {};
MEM.panels = MEM.panels || {};

const q = (id) => document.getElementById(id);

/* ══ 개요 — 통계 띠 + 계기 격자 + 원본·파생 표 ═══════════════════════════════ */

function gauge(b){
  const pct = Math.max(0, Math.min(100, b.pct));
  const C = 2 * Math.PI * 44, off = C * (1 - pct / 100);
  const col = b.state === "crit" ? "var(--danger)" : b.state === "warn" ? "var(--warn)" : "var(--gold-mark)";
  return '<svg width="104" height="104" viewBox="0 0 112 112" role="img" aria-label="카탈로그 분량 '
    + b.size + ' / ' + b.budget + '자, ' + pct + '퍼센트">'
    + '<circle cx="56" cy="56" r="44" fill="none" stroke="var(--surface-3)" stroke-width="7"/>'
    + '<circle cx="56" cy="56" r="44" fill="none" stroke="' + col + '" stroke-width="7" stroke-linecap="round"'
    + ' stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' + off.toFixed(1) + '" transform="rotate(-90 56 56)"/>'
    + '<text x="56" y="60" text-anchor="middle" fill="var(--ink)" font-family="monospace" font-size="18"'
    + ' font-weight="600">' + pct + '%</text></svg>';
}
const statCard = (v, label, sub, cls) => '<div class="mem-stat ' + cls + '"><div class="v">' + v
  + '</div><div class="l">' + MEM.esc(label) + '</div><div class="s">' + MEM.esc(sub) + '</div></div>';

function renderOverview(s){
  const g = s.graph, cat = s.catalog, b = s.meta.budget;
  q("mem-onboard").innerHTML = cat.length ? ""
    : MEM.onboard("서고가 비어 있어요 — 첫 페이지를 기록하면 개요·성좌·연대기가 함께 깨어나요.");
  const kinds = {};
  cat.forEach((p) => { kinds[p.kind] = (kinds[p.kind] || 0) + 1; });
  const kn = Object.keys(kinds).sort((a, x) => kinds[x] - kinds[a]);
  const uses = s.usage.reduce((acc, u) => acc + (u.uses || 0), 0);
  q("mem-stats").innerHTML =
      statCard(cat.length, "페이지", "서고에 쌓인 기록", "")
    + statCard(kn.length, "종류", kn.slice(0, 3).map((k) => k + " " + kinds[k]).join(" · ") || "비어 있음", "")
    + statCard(uses, "꺼내 쓴 횟수", "검색이 이 기억을 실제로 꺼내 쓴 횟수", "")
    + statCard(g.dead, "끊어진 링크", g.dead ? "가리키는 페이지가 없는 링크" : "끊어진 링크 없음", g.dead ? "crit" : "")
    + statCard(g.orphans.length, "연결 없는 페이지",
        g.orphans.length ? "어떤 페이지와도 이어지지 않음" : "모두 연결됨", g.orphans.length ? "warn" : "");

  q("mem-gauge").innerHTML = gauge(b);
  q("mem-budget").innerHTML = '<b class="num">' + b.size + '</b> / ' + b.budget + '자<br>'
    + '<span style="color:' + (b.state === "crit" ? "var(--danger)" : b.state === "warn" ? "var(--warn)" : "var(--muted)")
    + '">' + (b.state === "crit" ? "한도 초과 — 넘친 종류는 뒷부분이 전달에서 잘려요. 페이지를 합쳐 주세요"
       : b.state === "warn" ? "한도 임박" : "여유") + '</span>';

  q("mem-findings").innerHTML = s.health.findings.length
    ? s.health.findings.slice(0, 40).map((f) => '<li><span class="mem-fchip f-'
        + (f.level === "error" ? "crit" : f.level === "warn" ? "warn" : "info") + '">' + MEM.esc(f.level) + '</span>'
        + '<span><span class="sl">' + MEM.esc(f.slug) + '</span> ' + MEM.esc(f.code) + ' — '
        + MEM.esc(f.msg) + '</span></li>').join("")
    : '<li class="mem-ok">건강해요 — 발견된 문제 없음</li>';
  q("mem-ovlog").innerHTML = s.log.slice(0, 8).map(MEM.logRow).join("") || '<li class="ak-empty">기록 없음</li>';
  const top = s.usage.filter((u) => u.uses > 0).slice(0, 8);
  q("mem-topuse").innerHTML = top.length
    ? top.map((u) => '<li><span class="ti">' + MEM.slugBtn(u.slug) + '</span><span class="u">' + u.uses
        + '회</span><span class="du">' + MEM.daysAgo(u.last_used) + '</span></li>').join("")
    : '<li class="ak-empty">아직 꺼내 쓴 기록 없음</li>';
  renderOvInject(s);
  renderOvSemantic(s);
  renderDerived(s);
}
// 저장량이 아니라 전송량을 말한다 — 서고에 있는 것과 프롬프트로 나가는 것은 다르다.
function renderOvInject(s){
  const b = s.meta.budget, on = s.meta.inject !== false;
  const over = (b.sections || []).filter((x) => x.state === "crit").length;
  q("mem-ovinject").innerHTML =
      '<div class="mem-sw-row"><span class="mem-sw ' + (on ? "on" : "off") + '">'
    + (on ? "전달 켜짐" : "전달 꺼짐") + '</span><span class="note">'
    + (on ? "대화가 시작될 때 목록이 한 번 고정되어 함께 전달돼요."
          : "전달이 꺼져 있어 어떤 모델에게도 나가지 않아요.") + '</span></div>'
    + '<ul class="mem-uselist"><li><span class="ti">전달 분량</span><span class="u">' + b.size
    + '</span><span class="du">/ ' + b.budget + '</span></li>'
    + '<li><span class="ti">한도를 넘은 종류</span><span class="u" style="color:'
    + (over ? "var(--danger)" : "var(--ok)") + '">' + over + '</span><span class="du">'
    + (b.sections || []).length + '개 종류</span></li></ul>'
    + '<p><button type="button" class="mem-link" data-mem="tab" data-tab="inject">전달 전체 보기 →</button></p>';
}
// "켜짐"과 "이 서고에 벡터가 있음"은 다른 말이다 — 셋을 갈라 적지 않으면 원인을 못 찾는다.
function renderOvSemantic(s){
  const el = q("mem-ovsem");
  const sem = s.semantic || { state:"off", mode:"off", vectors:0, pages:0, pct:0 };
  if(sem.state !== "ready"){
    el.innerHTML = sem.mode === "off"
      ? MEM.empty("꺼져 있어요. 지금은 제목과 본문 검색만 씁니다.")
      : '<div class="mem-sw-row"><span class="mem-sw off">켜져 있지만 동작하지 않아요</span><span class="note">'
        + (sem.blocked === "library"
            ? "의미 검색에 필요한 구성 요소가 설치되어 있지 않아요. 기본으로 함께 설치되는 항목이라, 설치본이 오래된 경우예요."
            : sem.blocked === "model"
            ? "모델을 아직 내려받지 않았어요. 한 번만 받아 두면 이후에는 바로 씁니다."
            : "설정은 켜짐인데 준비가 안 됐어요.") + '</span></div>'
        + (sem.fix ? '<code class="mem-cmd">' + MEM.esc(sem.fix) + '</code>' : "");
    return;
  }
  const gap = Math.max(0, (sem.pages || 0) - (sem.vectors || 0));
  el.innerHTML = '<ul class="mem-meter"><li class="' + (sem.pct >= 100 ? "" : sem.pct >= 60 ? "warn" : "crit") + '">'
    + '<div class="row"><span class="nm">의미로 찾을 수 있는 페이지</span><span class="pc">'
    + sem.vectors + ' / ' + sem.pages + ' · ' + sem.pct + '%</span></div>'
    + '<span class="track"><i style="width:' + Math.min(100, sem.pct) + '%"></i></span>'
    + (gap ? '<p class="drop">' + gap + '장은 아직 의미로 찾을 수 없어요. <code>asgard memory reindex</code> 를 돌리면 채워져요</p>' : "")
    + (sem.dim_mixed ? '<p class="drop">벡터 차원이 섞였어요. 모델을 바꾼 뒤 재색인을 하지 않은 상태예요.</p>' : "")
    + '</li></ul>';
}
// 무엇을 잃으면 기억이 사라지는가 — 원본과 다시 만들어지는 것을 갈라 적는다.
function renderDerived(s){
  const rows = (s.derived && s.derived.rows) || [];
  q("mem-derived").innerHTML = rows.map((r) => {
    const qty = !r.exists ? "없음" : r.kind === "dir" ? r.n + "개" : MEM.fmtBytes(r.n);
    return '<li class="' + (r.exists ? "" : "gone") + '"><span class="tag ' + (r.canon ? "canon" : "derived") + '">'
      + (r.canon ? "원본" : "자동생성") + '</span><span class="nm">' + MEM.esc(r.name) + '</span>'
      + '<span class="qty">' + qty + '</span><span class="nt">' + MEM.esc(r.note) + '</span></li>';
  }).join("") || '<li class="ak-empty">—</li>';
}

/* ══ 페이지 상세 — 성좌 옆 패널과 서고 펼침이 같은 카드를 쓴다 ═══════════════ */

function detailHtml(p, opts){
  opts = opts || {};
  const close = '<button type="button" class="mem-gclose" data-mem="' + (opts.close || "close-detail")
    + '" aria-label="상세 닫기">닫기</button>';
  if(p.error){
    return '<div class="mem-det"><div class="mem-det-head"><span class="mono bad">'
      + MEM.esc(p.slug || opts.slug || "") + '</span>' + close + '</div>'
      + MEM.empty("페이지를 찾을 수 없어요 — 끊어진 링크가 가리키던 자리예요.") + '</div>';
  }
  const row = (k, v) => v ? "<dt>" + k + "</dt><dd>" + MEM.esc(v) + "</dd>" : "";
  let html = '<div class="mem-det"><div class="mem-det-head">' + MEM.kchip(p.kind) + close + '</div>'
    + '<h4 class="mem-det-title">' + MEM.esc(p.title) + '</h4>'
    + '<p class="mem-det-slug mono">' + MEM.esc(p.slug) + '</p>'
    + '<dl class="mem-det-meta">' + row("생성", p.created) + row("갱신", p.updated)
    + row("회수", (p.uses || 0) + "회") + row("최근 회수", p.last_used) + '</dl>';
  if(p.poisoned){
    html += '<p class="mem-poison">위험이 감지돼 본문을 숨겼어요. 확인하려면:'
      + (p.quarantine_cmd ? '<code class="mem-cmd">' + MEM.esc(p.quarantine_cmd) + '</code>' : "") + '</p>';
  } else {
    if(p.body) html += '<pre class="mem-det-body">' + MEM.esc(MEM.truncate(p.body, 1200)) + '</pre>';
    const outs = [];
    (p.refs || []).concat(p.links || []).forEach((s) => { if(outs.indexOf(s) < 0) outs.push(s); });
    if(outs.length){
      html += '<p class="mem-sectitle">연결된 페이지</p><div class="mem-det-links">'
        + outs.map((s) => '<button type="button" class="mem-lchip" data-mem="goto" data-slug="'
            + MEM.esc(s) + '">' + MEM.esc(s) + '</button>').join("") + '</div>';
    }
  }
  if(opts.star){
    html += '<p><button type="button" class="mem-lchip" data-mem="goto" data-slug="' + MEM.esc(p.slug)
      + '">성좌에서 보기</button></p>';
  }
  return html + '</div>';
}

/* ══ 서고 — 카탈로그 표 + 검색 결과 ══════════════════════════════════════════ */

const SORTS = [["updated", "갱신순"], ["uses", "회수순"], ["title", "제목순"]];

function renderKindChips(s){
  const APP = MEM.APP;
  const counts = {};
  s.catalog.forEach((p) => { counts[p.kind] = (counts[p.kind] || 0) + 1; });
  if(APP.kind && !counts[APP.kind]) APP.kind = ""; // 갱신 뒤 사라진 종류의 필터는 스스로 풀린다
  if(!s.catalog.length){ // 빈 서고에서 "전체 0" 칩과 정렬 토글은 소음이다 — 온보딩만 남긴다
    q("mem-kind-chips").innerHTML = "";
    q("mem-sort-chips").innerHTML = "";
    q("mem-cat-count").textContent = "";
    q("mem-sem-note").innerHTML = "";
    return;
  }
  const chip = (k, label) => {
    const on = (k || "") === APP.kind;
    return '<button type="button" class="ak-chip" data-mem="kind" data-kind="' + MEM.esc(k)
      + '" aria-pressed="' + (on ? "true" : "false") + '">' + label + '</button>';
  };
  q("mem-kind-chips").innerHTML = chip("", '전체 <span class="cnt">' + s.catalog.length + '</span>')
    + Object.keys(counts).sort().map((k) => chip(k, MEM.swatch(k) + MEM.esc(MEM.kindName(k))
        + ' <span class="cnt">' + counts[k] + '</span>')).join("");
  renderSortChips();
  q("mem-cat-count").textContent = "· " + s.catalog.length;
  q("mem-sem-note").innerHTML = s.meta.semantic ? "" : "의미 검색은 아직 쓰지 않아요";
}
function renderSortChips(){
  q("mem-sort-chips").innerHTML = '<span class="mem-sectitle">정렬</span>'
    + SORTS.map(([key, ko]) => '<button type="button" class="ak-chip" data-mem="sort" data-sort="' + key
        + '" aria-pressed="' + (MEM.APP.sort === key ? "true" : "false") + '">' + ko + '</button>').join("");
}
function sortCatalog(rows){
  const upd = (a, b) => String(b.updated || "").localeCompare(String(a.updated || ""));
  if(MEM.APP.sort === "uses") return rows.sort((a, b) => ((b.uses || 0) - (a.uses || 0)) || upd(a, b));
  if(MEM.APP.sort === "title") return rows.sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), "ko"));
  return rows.sort(upd);
}
function renderLibrary(){
  const APP = MEM.APP, s = APP.snap;
  if(!s) return;
  if(APP.q){ // 검색 중에는 정렬 칩을 감춘다 — 순위를 정하는 것은 점수이지 갱신일이 아니다
    q("mem-sort-chips").hidden = true;
    doSearch(APP.q);
    return;
  }
  q("mem-sort-chips").hidden = false;
  closeInline(false);
  const focus = MEM.captureFocus(["mem-q"]);
  const rows = sortCatalog(s.catalog.filter((p) => !APP.kind || p.kind === APP.kind).slice());
  const maxU = Math.max(1, s.catalog.reduce((m, p) => Math.max(m, p.uses || 0), 0));
  q("mem-lib").innerHTML = rows.length
    ? '<div class="mem-tablewrap"><table class="ak-table"><caption>제목을 누르면 상세가 펼쳐져요</caption>'
      + '<thead><tr><th scope="col">페이지</th><th scope="col">종류</th>'
      + '<th scope="col" class="rt">회수</th><th scope="col">갱신</th></tr></thead><tbody>'
      + rows.map((p) => '<tr><td class="ti">'
          + (p.poisoned ? '<span class="mem-poison-tag">위험 감지</span>' : "")
          + '<button type="button" class="mem-link" data-mem="detail" data-slug="' + MEM.esc(p.slug)
          + '" aria-expanded="false">' + MEM.esc(p.title) + '</button>'
          + '<div class="di mono">' + MEM.esc(p.slug) + '</div>'
          + (p.desc ? '<div class="di">' + MEM.esc(MEM.truncate(p.desc, 90)) + '</div>' : "")
          + '</td><td>' + MEM.kchip(p.kind) + '</td>'
          + '<td class="rt"><span class="mem-ubar" aria-hidden="true"><i style="width:'
          + Math.round(100 * (p.uses || 0) / maxU) + '%"></i></span>' + (p.uses || 0) + '</td>'
          + '<td class="di">' + MEM.daysAgo(p.updated) + '</td></tr>').join("")
      + '</tbody></table></div>'
    : (APP.kind ? MEM.empty("이 종류의 페이지가 없어요")
       : MEM.onboard("서고가 비어 있어요 — 아래 한 줄이면 첫 페이지가 만들어져요."));
  MEM.restoreFocus(focus);
}
// 이미 이스케이프된 글자 위에 표시만 입힌다 — 원문에 태그를 넣는 것이 아니다.
function markHl(safe, term){
  if(!term || term.length < 2) return safe;
  try{
    return safe.replace(new RegExp("(" + term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi"), "<mark>$1</mark>");
  }catch(e){ return safe; }
}
async function doSearch(term){
  try{
    renderHits(await MEM.fetchSearch(term, 12));
  }catch(e){
    q("mem-lib").innerHTML = MEM.errorCard("검색에 실패했어요: " + String(e));
  }
}
const lane = (name, on, cls) => '<div class="mem-lane ' + (on ? "on " : "off ") + cls + '"><span>'
  + name + '</span><span class="bar"></span></div>';
function renderHits(data){
  const APP = MEM.APP;
  if(APP.q !== data.q) return; // 늦게 도착한 응답은 버린다 — 연타해도 화면이 뒤로 가지 않는다
  closeInline(false);
  const focus = MEM.captureFocus(["mem-q"]);
  const hits = data.hits.filter((h) => !APP.kind || h.kind === APP.kind);
  q("mem-lib").innerHTML = hits.length
    ? hits.map((h) => {
        const st = h.streams || {};
        return '<div class="mem-qrow" tabindex="0" role="button" data-mem="detail" data-slug="' + MEM.esc(h.slug)
          + '" aria-expanded="false" aria-label="' + MEM.esc(h.title) + ' — 상세 펼치기">'
          + '<div class="t">' + MEM.kchip(h.kind) + ' ' + markHl(MEM.esc(h.title), data.q)
          + '<span class="sub">' + MEM.esc(h.slug) + ' · 점수 ' + MEM.esc(h.score) + '</span>'
          + (h.snippet ? '<span class="snip">' + markHl(MEM.esc(h.snippet), data.q) + '</span>' : "")
          + '</div><div class="mem-lanes" aria-hidden="true">'
          + lane("FTS", st.fts, "fts") + lane("SCAN", st.scan, "scan")
          + lane("SEM", st.semantic, "sem") + lane("PPR", st.graph, "fts")
          + '</div></div>';
      }).join("")
    : MEM.empty('"' + data.q + '" 검색 결과가 없어요' + (APP.kind ? " (종류 필터가 걸려 있어요)" : ""));
  MEM.restoreFocus(focus);
}

/* ── 행 아래 펼침 — 닫으면 연 요소로 포커스가 돌아온다 ────────────────────── */

async function toggleInline(slug, opener){
  const APP = MEM.APP;
  if(APP.inline && APP.inline.slug === slug){ closeInline(true); return; }
  closeInline(false);
  const tr = opener.closest("tr");
  let mount;
  if(tr){
    mount = document.createElement("tr");
    mount.className = "mem-dtr";
    mount.innerHTML = '<td colspan="4"><div class="mem-dwrap">' + MEM.empty("불러오는 중이에요…") + '</div></td>';
    tr.after(mount);
  } else {
    const row = opener.closest(".mem-qrow");
    if(!row) return;
    mount = document.createElement("div");
    mount.className = "mem-dbox";
    mount.innerHTML = '<div class="mem-dwrap">' + MEM.empty("불러오는 중이에요…") + '</div>';
    row.after(mount);
  }
  opener.setAttribute("aria-expanded", "true");
  APP.inline = { slug: slug, opener: opener, mount: mount };
  try{
    const p = await MEM.fetchPage(slug);
    if(APP.inline && APP.inline.mount === mount){
      mount.querySelector(".mem-dwrap").innerHTML = detailHtml(p, { close: "close-inline", star: true, slug: slug });
    }
  }catch(e){
    if(mount.isConnected) mount.querySelector(".mem-dwrap").innerHTML = MEM.errorCard(String(e));
  }
}
function closeInline(refocus){
  const APP = MEM.APP;
  if(!APP.inline) return;
  const it = APP.inline;
  APP.inline = null;
  if(it.mount && it.mount.isConnected) it.mount.remove();
  if(it.opener && it.opener.isConnected){
    it.opener.setAttribute("aria-expanded", "false");
    if(refocus) it.opener.focus();
  }
}
function setKind(btn){
  MEM.APP.kind = btn.dataset.kind || "";
  document.querySelectorAll('#mem-kind-chips .ak-chip').forEach((c) => {
    c.setAttribute("aria-pressed", (c.dataset.kind || "") === MEM.APP.kind ? "true" : "false");
  });
  renderLibrary();
}
function setSort(btn){
  MEM.APP.sort = btn.dataset.sort || "updated";
  renderSortChips();
  renderLibrary();
}

/* ── 판 등록 ────────────────────────────────────────────────────────────────── */

MEM.detailHtml = detailHtml;
MEM.panels.overview = {
  html:
      '<div class="mem-stats" id="mem-stats" aria-label="서고 통계"></div>'
    + '<div id="mem-onboard"></div>'
    + '<div class="mem-grid">'
    + '<figure class="ak-card mem-gauge-card"><div id="mem-gauge"></div>'
    + '<figcaption><div class="lab">카탈로그 분량</div><div id="mem-budget">—</div></figcaption></figure>'
    + '<section class="ak-card" aria-label="전달 요약"><h3 class="ak-card__title">모델에게 가는 분량</h3>'
    + '<div id="mem-ovinject"></div></section>'
    + '<section class="ak-card" aria-label="의미 검색 준비"><h3 class="ak-card__title">의미 검색 준비</h3>'
    + '<div id="mem-ovsem"></div></section>'
    + '<section class="ak-card" aria-label="건강 진단"><h3 class="ak-card__title">건강 진단</h3>'
    + '<ul class="mem-flist" id="mem-findings"></ul></section>'
    + '<section class="ak-card" aria-label="연대기 발췌"><h3 class="ak-card__title">연대기 발췌</h3>'
    + '<ul class="mem-log" id="mem-ovlog"></ul>'
    + '<p><button type="button" class="mem-link" data-mem="tab" data-tab="chronicle">연대기 전체 보기 →</button></p></section>'
    + '<section class="ak-card" aria-label="자주 꺼내 쓴 기억"><h3 class="ak-card__title">자주 꺼내 쓴 기억</h3>'
    + '<ul class="mem-uselist" id="mem-topuse"></ul></section>'
    + '</div>'
    + '<section class="ak-card mem-derived-card" aria-label="원본과 다시 만들어지는 파일">'
    + '<h3 class="ak-card__title">원본과 다시 만들어지는 파일</h3>'
    + '<p class="ak-card__note">원본은 pages/ 와 당신의 손이 남긴 기록이에요. 나머지는 다시 만들어지거나 정리가'
    + ' 남긴 것이라, 지워도 내용은 사라지지 않아요.</p>'
    + '<ul class="mem-drv" id="mem-derived"></ul></section>',
  render: renderOverview,
};
MEM.panels.library = {
  html:
      '<section class="ak-card" aria-label="서고 카탈로그">'
    + '<h3 class="ak-card__title">서고 <span class="mem-dim" id="mem-cat-count"></span></h3>'
    + '<form class="mem-search" id="mem-search" role="search">'
    + '<label for="mem-q" class="mem-vh">서고 검색어</label>'
    + '<input id="mem-q" class="ak-input" name="q" type="search" autocomplete="off"'
    + ' placeholder="검색 — 제목·본문·의미까지 한 번에 (읽기 전용)">'
    + '<button type="submit" class="ak-btn ak-btn--primary">검색</button></form>'
    + '<div class="mem-legend-row"><span class="mem-sectitle">검색 경로</span>'
    + '<span class="mem-lg fts">전문 검색</span><span class="mem-lg scan">본문 훑기</span>'
    + '<span class="mem-lg sem">의미 검색</span><span class="mem-dim" id="mem-sem-note"></span></div>'
    + '<div id="mem-kind-chips" class="mem-chips" role="group" aria-label="종류 필터"></div>'
    + '<div id="mem-sort-chips" class="mem-chips" role="group" aria-label="정렬 기준"></div>'
    + '<div id="mem-lib" aria-live="polite"></div></section>',
  render: function(s){
    renderKindChips(s);
    renderLibrary();
  },
};

// 셸이 모르는 행동은 여기로 넘어온다 — 판마다 리스너를 따로 달지 않는다.
const prevAction = MEM.onAction;
MEM.onAction = function(act, target){
  if(act === "kind") setKind(target);
  else if(act === "sort") setSort(target);
  else if(act === "detail") toggleInline(target.getAttribute("data-slug"), target);
  else if(act === "close-inline") closeInline(true);
  else if(prevAction) prevAction(act, target);
};
const prevBind = MEM.bind;
MEM.bind = function(root){
  const form = q("mem-search");
  if(form){
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      MEM.APP.q = q("mem-q").value.trim();
      renderLibrary();
    });
  }
  MEM.bindImeSafeSearch(q("mem-q"), 200, (v) => {
    MEM.APP.q = (v || "").trim();
    renderLibrary();
  });
  if(prevBind) prevBind(root);
};
})();
