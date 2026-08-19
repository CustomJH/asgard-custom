"use strict";
/* 기억 화면 — 전달 · 정리 · 연대기 · 활동.
 *
 * 네 판이 한 파일에 있는 것은 전부 "무슨 일이 있었는가"를 읽어서다. 전달은 지금 프롬프트로
 * 나가는 블록을, 정리는 노른이 남긴 기록을, 연대기는 작업 로그를, 활동은 그 로그를 날짜로 접은
 * 열지도를 낸다.
 *
 * 전달만 스냅샷이 아니라 자기 창구(`/api/memory/injection`)를 쓴다 — 블록 원문이 커서 그 탭을
 * 열 때만 받는다. 연대기도 마찬가지로 `/api/memory/log` 를 따로 부른다: 서버가 페이지를 나눠
 * 주므로 60건씩만 온다.
 *
 * 색 값은 이 파일에도 없다. 작업 갈래 색은 `MEM.opStyle()` 이 주는 `var(--...)` 이고, 열지도의
 * 다섯 단계는 `ui/memory.css` 의 `.mem-heat-cell.lv1..lv4` 가 갖는다.
 */
(function(){
const MEM = window.MEM = window.MEM || {};
MEM.panels = MEM.panels || {};

const q = (id) => document.getElementById(id);
const CHRON_LIMIT = 60; // 서버가 나눠 주는 한 쪽 크기

/* ══ 전달 — 프롬프트로 나가는 내용 원문 + 종류별 한도 ═══════════════════════ */

// 펜스·종류 머리글·잘림 경고만 물들인다. 내용은 원문 그대로여야 대조가 된다.
function highlight(text){
  // 앞뒤 이음 개행만 접는다 — 블록이 앞선 프롬프트에 눌어붙지 않게 하는 이음매라 내용이 아니다.
  return MEM.esc(String(text).replace(/^\n+/, "").replace(/\n+$/, "")).split("\n").map((line) => {
    if(/^&lt;\/?memory-context/.test(line)) return '<span class="fence">' + line + '</span>';
    if(/^## /.test(line)) return '<span class="head">' + line + '</span>';
    if(/^- … /.test(line)) return '<span class="warnline">' + line + '</span>';
    return line;
  }).join("\n");
}
function renderInjection(j){
  j = j || { enabled:false, text:"", chars:0, sections:[], excluded:[], excluded_total:0 };
  q("mem-inj-meta").textContent = j.chars + "자" + (j.truncated ? " · 잘림" : "");
  q("mem-inj-state").innerHTML = '<div class="mem-sw-row"><span class="mem-sw '
    + (j.enabled ? "on" : "off") + '">' + (j.enabled ? "전달 켜짐" : "전달 꺼짐") + '</span>'
    + '<span class="note">' + (j.enabled
        ? "대화가 시작될 때 한 번 고정되고, 그 대화 동안 바뀌지 않아요."
        : "전달이 꺼져 있어요. 아래 내용은 비어 있고, 어떤 모델도 이 기억을 볼 수 없어요.") + '</span>'
    + (j.total_budget != null ? '<span class="mem-sw">전체 한도 ' + j.total_budget + '</span>' : "")
    + '<span class="mem-sw">검색 결과 한도 ' + (j.recall_budget || 0) + '</span></div>';
  q("mem-inj-block").innerHTML = j.text ? highlight(j.text)
    : '<span class="mem-dim">전달되는 내용이 없어요. 저장된 페이지가 없거나 전달이 꺼져 있어요.</span>';
  q("mem-inj-meter").innerHTML = (j.sections || []).map((sec) => {
    const cls = sec.muted || sec.kept < sec.rows ? "crit" : sec.pct >= 85 ? "warn" : "";
    return '<li class="' + cls + '"><div class="row"><span class="nm">' + MEM.esc(sec.label) + '</span>'
      + '<span class="kd">' + MEM.esc(sec.kind) + '</span><span class="pc">' + sec.pct + '% · '
      + sec.full + '/' + sec.budget + '</span></div>'
      + '<span class="track"><i style="width:' + Math.min(100, sec.pct) + '%"></i></span>'
      + (sec.muted ? '<p class="drop">한도 0 — 저장은 되지만 전달되지 않아요</p>' : "")
      + (!sec.muted && sec.kept < sec.rows
          ? '<p class="drop">' + (sec.rows - sec.kept) + '행이 밀려났어요: '
            + sec.dropped.map(MEM.esc).join(" · ") + '</p>' : "")
      + (!sec.muted && sec.rows && sec.kept === sec.rows
          ? '<p class="mute">' + sec.kept + '행 전부 실렸어요</p>' : "")
      + '</li>';
  }).join("") || '<li class="ak-empty">전달할 내용이 없어요</li>';
  q("mem-inj-excluded").innerHTML = '<p class="mem-sectitle">전달에서 빠진 것</p>'
    + ((j.excluded || []).length
      ? '<ul class="mem-exlist">' + j.excluded.map((p) => '<li><span class="mem-poison-tag">위험 감지</span>'
          + '<button type="button" class="mem-link mono" data-mem="goto" data-slug="' + MEM.esc(p.slug)
          + '">' + MEM.esc(p.title || p.slug) + '</button></li>').join("") + '</ul>'
        + (j.excluded_total > j.excluded.length
            ? '<p class="mem-dim">외 ' + (j.excluded_total - j.excluded.length) + '장</p>' : "")
      : MEM.empty("없어요. 위험 감지로 빠진 페이지가 없습니다."));
}

/* ══ 정리 — 노른이 사람 없이 무엇까지 했는가 ════════════════════════════════ */

function renderNorn(s){
  const dr = (s && s.norn) || { reports:[], insights:[], auto_mode:"safe", insight_auto:false,
    contradictions:[], archive:[], backups:[], patterns:[] };
  q("mem-norn-meta").textContent = dr.insights.length + "통찰 · " + dr.reports.length + "리포트";

  // 자율 모드가 이 판의 첫 문장이어야 한다 — 승인 없이 무엇이 도는지가 먼저다.
  const auto = dr.auto_mode || "safe";
  q("mem-norn-modes").innerHTML =
      '<span class="mem-mode ' + (auto === "off" ? "off" : "on") + '"><b>자율 모드</b> ' + MEM.esc(auto) + '</span>'
    + '<span class="mem-mode ' + (dr.insight_auto ? "on" : "off") + '"><b>통찰 자동 승격</b> '
    + (dr.insight_auto ? "켜짐" : "꺼짐") + '</span>'
    + '<span class="mem-mode off">' + (auto === "off" ? "자동 없음 — 전부 사람이 실행해요"
        : auto === "full" ? "병합·보관·모순까지 자동이에요" : "모순 보고만 자동이에요") + '</span>'
    + (dr.insight_auto ? "" : '<span class="mem-mode off">통찰은 제안까지만 — 승격은 사람이 해요</span>');

  q("mem-norn-insights").innerHTML = dr.insights.length
    ? dr.insights.map((i) => {
        const c = (i.confidence || "").toLowerCase();
        return '<li><div class="row">'
          + '<button type="button" class="mem-link" data-mem="goto" data-slug="' + MEM.esc(i.slug) + '">'
          + MEM.esc(i.title) + '</button>'
          + (c ? '<span class="mem-conf conf-' + MEM.esc(c) + '">' + MEM.esc(c) + '</span>' : "")
          + '<span class="mem-dim">' + MEM.esc(i.created || "") + ' · ' + (i.uses || 0) + '회</span></div>'
          + (i.sources && i.sources.length
              ? '<div class="src"><span class="arrow">←</span>' + i.sources.map((sc) =>
                  '<button type="button" class="mem-lchip" data-mem="goto" data-slug="' + MEM.esc(sc) + '">'
                  + MEM.esc(sc) + '</button>').join("") + '</div>'
              : '<div class="src mem-dim">출처 링크 없음</div>') + '</li>';
      }).join("")
    : '<li class="ak-empty">아직 통찰이 없어요. 노른이 패턴을 승격하면 계보가 남아요.</li>';

  // 장부가 준 것만 그린다 — 사람이 "봤다"고 표시한 쌍은 여기 오지 않는다.
  q("mem-norn-contra").innerHTML = (dr.contradictions || []).length
    ? dr.contradictions.map((c) => {
        const marks = [];
        if(c.count > 1) marks.push(c.count + "회");
        if(c.last_seen) marks.push(MEM.esc(String(c.last_seen).slice(0, 10))); // 장부는 분까지 적지만 목록엔 날짜면 된다
        if(c.changed_since) marks.push("그 뒤 페이지가 바뀜");
        return '<li><div class="pair">'
          + '<button type="button" class="mem-link mono" data-mem="goto" data-slug="' + MEM.esc(c.a) + '">' + MEM.esc(c.a) + '</button>'
          + '<span>↔</span>'
          + '<button type="button" class="mem-link mono" data-mem="goto" data-slug="' + MEM.esc(c.b) + '">' + MEM.esc(c.b) + '</button>'
          + (marks.length ? '<span class="mem-dim">' + marks.join(" · ") + '</span>' : "")
          + '</div><p class="why">' + MEM.esc(c.why || "") + '</p></li>';
      }).join("")
    : '<li class="ak-empty">아직 넘어온 어긋남이 없어요.</li>';

  const sum = (c) => ["merge", "archive", "insight", "contradiction", "proposed", "dropped"]
    .map((k) => c[k] ? k + " " + c[k] : "").filter(Boolean).join(" · ") || "변경 없음";
  q("mem-norn-reports").innerHTML = (dr.reports || []).map((r) =>
      '<li><span class="ts">' + MEM.esc(r.name.replace(/^norn-|\.md$/g, "")) + '</span>'
      + '<span class="op">norn</span><span class="sl">' + MEM.esc(sum(r.counts)) + '</span></li>')
    .concat((dr.patterns || []).map((r) =>
      '<li><span class="ts">' + MEM.esc(r.name.replace(/^pattern-|\.md$/g, "")) + '</span>'
      + '<span class="op" style="color:var(--ok)">pattern</span>'
      + '<span class="sl">승격 ' + r.applied + ' · 기각 ' + r.dropped + '</span></li>')).join("")
    || '<li class="ak-empty">리포트가 없어요. <code>asgard memory norn</code> 으로 첫 정리를 실행해 보세요.</li>';

  q("mem-arc-meta").textContent = String((dr.archive || []).length);
  q("mem-norn-archive").innerHTML = (dr.archive || []).length
    ? dr.archive.map((a) => '<li><span class="sl">' + MEM.esc(a.slug) + '</span>'
        + '<span class="dt">' + MEM.esc(a.ts) + '</span>'
        + '<code class="mem-cmd">' + MEM.esc(a.restore) + '</code></li>').join("")
    : '<li class="ak-empty">보관함으로 옮긴 페이지가 없어요.</li>';

  q("mem-bk-meta").textContent = String((dr.backups || []).length);
  q("mem-norn-backups").innerHTML = (dr.backups || []).length
    ? dr.backups.map((b) => '<li><span class="sl">' + MEM.esc(b.name) + '</span>'
        + '<span class="dt">' + b.pages + '장</span></li>').join("")
    : '<li class="ak-empty">백업이 없어요. 병합·보관을 실행한 적이 없습니다.</li>';

  const peer = (s && s.peer) || { exists:false, rows:[], slug:"" };
  q("mem-peer-meta").textContent = peer.exists ? "카드 있음 · " + peer.rows.length
    : peer.rows.length ? "출처 " + peer.rows.length : "";
  q("mem-peer").innerHTML = peer.rows.length
    ? peer.rows.map((r) => '<li><span class="sl wrap">' + MEM.esc(r.text) + '</span>'
        + '<button type="button" class="mem-link mono dt" data-mem="goto" data-slug="' + MEM.esc(r.slug)
        + '">' + MEM.esc(r.slug) + '</button></li>').join("")
      + (peer.exists ? "" : '<li class="ak-empty">출처는 있는데 카드가 아직 없어요. <code>asgard memory pattern</code> 이 만들어요.</li>')
    : '<li class="ak-empty">소유자 관측(kind=user)이 아직 없어요.</li>';
}

/* ══ 연대기 — 좌우 교차 타임라인 + 갈래 필터 + 날짜 필터 ═══════════════════ */

function renderChronicle(s){
  const a = (s && s.activity) || { ops:{}, total:0 };
  const chip = (f, label) => '<button type="button" class="ak-chip" data-mem="op" data-op="' + MEM.esc(f)
    + '" aria-pressed="' + ((f || "") === MEM.APP.op ? "true" : "false") + '">' + label + '</button>';
  q("mem-op-chips").innerHTML = chip("", '전체 <span class="cnt">' + a.total + '</span>')
    + Object.keys(a.ops).sort((x, y) => a.ops[y] - a.ops[x]).map((f) =>
        chip(f, '<span style="color:' + MEM.opStyle(f).v + ';display:inline-flex">' + MEM.opGlyph(f) + '</span>'
          + MEM.esc(f) + ' <span class="cnt">' + a.ops[f] + '</span>')).join("");
  renderDayFilter();
  return loadChron();
}
function renderDayFilter(){
  q("mem-day-filter").innerHTML = MEM.APP.day
    ? '<span class="mem-dayflt"><span>' + MEM.esc(MEM.APP.day) + ' 하루만 보기</span>'
      + '<button type="button" class="ak-btn" data-mem="day-clear" aria-label="날짜 필터 해제">해제 ✕</button></span>'
    : "";
}
async function loadChron(){
  const APP = MEM.APP;
  const params = { offset: String(APP.chronOffset), limit: String(CHRON_LIMIT) };
  if(APP.op) params.op = APP.op;
  if(APP.day) params.day = APP.day;
  q("mem-chron").innerHTML = MEM.skeleton(4);
  try{
    renderChronList(await MEM.fetchLog(params));
  }catch(e){
    q("mem-chron").innerHTML = MEM.errorCard("연대기를 불러오지 못했어요: " + String(e));
    q("mem-chron-pgn").innerHTML = "";
  }
}
function renderChronList(data){
  const filtered = !!(MEM.APP.op || MEM.APP.day);
  q("mem-chron-count").textContent = "· 총 " + data.total + "건" + (filtered ? " (필터 적용)" : "");
  let html = "", lastDay = "";
  data.entries.forEach((l, i) => {
    const day = String(l.ts).slice(0, 10);
    if(day && day !== lastDay){ // 날짜 마커 — 타임라인 축 위의 눈금
      html += '<div class="mem-cdate"><span>' + MEM.esc(day) + '</span></div>';
      lastDay = day;
    }
    const oc = MEM.opStyle(l.op);
    html += '<article class="mem-citem ' + ((data.offset + i) % 2 ? "right" : "left") + '">'
      + '<span class="mem-cdot" style="background:' + oc.v + '" aria-hidden="true"></span>'
      + '<div class="mem-ccard"><div class="head">'
      + '<span class="obadge" style="color:' + oc.v + ';border-color:color-mix(in oklab,' + oc.v + ' 45%,transparent)">'
      + MEM.opGlyph(l.op) + MEM.esc(l.op) + '</span>'
      + '<button type="button" class="mem-link mono" data-mem="goto" data-slug="' + MEM.esc(l.slug) + '">'
      + MEM.esc(l.slug) + '</button>'
      + '<span class="time">' + MEM.esc(String(l.ts).slice(11, 16)) + '</span></div>'
      + (l.detail ? '<div class="det">' + MEM.esc(l.detail) + '</div>' : "") + '</div></article>';
  });
  q("mem-chron").innerHTML = html
    || (filtered ? MEM.empty("조건에 맞는 기록이 없어요 — 필터를 풀어 보세요.")
        : MEM.onboard("아직 기록이 없어요 — 첫 작업이 기록되면 여기에 나타나요."));
  const pages = Math.max(1, Math.ceil(data.total / CHRON_LIMIT));
  const cur = Math.floor(data.offset / CHRON_LIMIT);
  q("mem-chron-pgn").innerHTML = pages > 1
    ? '<nav class="mem-pgn" aria-label="연대기 쪽 넘김">'
      + '<button type="button" class="ak-btn" data-mem="chron-page" data-page="' + (cur - 1) + '"'
      + (cur <= 0 ? " disabled" : "") + '>← 최근</button>'
      + '<span>' + (cur + 1) + ' / ' + pages + ' 쪽 · 총 ' + data.total + '건</span>'
      + '<button type="button" class="ak-btn" data-mem="chron-page" data-page="' + (cur + 1) + '"'
      + (cur >= pages - 1 ? " disabled" : "") + '>과거 →</button></nav>'
    : "";
}

/* ══ 활동 — 52주 열지도 + 갈래 분포 + 최근 피드 ════════════════════════════ */

function renderActivity(s){
  const a = s.activity || { days:{}, ops:{}, total:0, first:"", last:"" };
  q("mem-act-meta").textContent = "· 총 " + a.total + "건" + (a.first ? " · " + a.first + " ~ " + a.last : "");
  if(!a.total){
    q("mem-heat").innerHTML = MEM.onboard("아직 활동 기록이 없어요 — 첫 기록이 이 열지도를 밝혀요.");
    q("mem-opbars").innerHTML = MEM.empty("기록 없음");
    q("mem-feed").innerHTML = '<li class="ak-empty">기록 없음</li>';
    return;
  }
  let max = 0;
  Object.keys(a.days).forEach((k) => { if(a.days[k] > max) max = a.days[k]; });
  let cells = "";
  const today = new Date();
  for(let w = 51; w >= 0; w--){ // 52주 × 7일 — 왼쪽이 옛날
    for(let d = 0; d < 7; d++){
      const cd = new Date(today);
      cd.setDate(cd.getDate() - (w * 7 + (6 - d)));
      const key = cd.toISOString().slice(0, 10);
      const c = a.days[key] || 0;
      const lv = !c ? 0 : c <= max * 0.25 ? 1 : c <= max * 0.5 ? 2 : c <= max * 0.75 ? 3 : 4;
      // 기록이 있는 날만 단추다 — 누르면 연대기의 그 하루로 간다.
      cells += c
        ? '<button type="button" class="mem-heat-cell lv' + lv + '" data-mem="heat" data-day="' + key
          + '" title="' + key + ' · ' + c + '건" aria-label="' + key + ' ' + c + '건 — 연대기에서 보기"></button>'
        : '<div class="mem-heat-cell" title="' + key + ' · 0건" aria-hidden="true"></div>';
    }
  }
  q("mem-heat").innerHTML = '<p class="mem-vh">지난 52주 일별 기록 열지도 — 총 ' + a.total
    + '건. 기록이 있는 날짜 칸을 고르면 연대기의 그 하루로 이동해요.</p>'
    + '<div class="mem-heatwrap"><div class="mem-heat-days" aria-hidden="true">'
    + '<span>월</span><span></span><span>수</span><span></span><span>금</span><span></span><span></span></div>'
    + '<div class="mem-heat-scroll"><div class="mem-heat-grid">' + cells + '</div></div></div>'
    + '<div class="mem-heat-legend" aria-hidden="true">적음 <span class="mem-heat-cell"></span>'
    + '<span class="mem-heat-cell lv1"></span><span class="mem-heat-cell lv2"></span>'
    + '<span class="mem-heat-cell lv3"></span><span class="mem-heat-cell lv4"></span> 많음</div>';
  // 최근이 오른쪽 끝이다 — 열자마자 빈 1년만 보이지 않게 스크롤을 끝으로 민다.
  const hs = q("mem-heat").querySelector(".mem-heat-scroll");
  if(hs) hs.scrollLeft = hs.scrollWidth;

  const tot = Math.max(1, a.total);
  q("mem-opbars").innerHTML = Object.keys(a.ops).sort((x, y) => a.ops[y] - a.ops[x]).map((o) =>
      '<div class="mem-bar-row"><span class="lb">' + MEM.esc(o) + '</span>'
      + '<div class="track"><div class="fill" style="width:' + Math.max(2, Math.round(100 * a.ops[o] / tot))
      + '%;background:' + MEM.opStyle(o).v + '"></div></div>'
      + '<span class="val">' + a.ops[o] + '</span></div>').join("") || MEM.empty("기록 없음");
  q("mem-feed").innerHTML = s.log.slice(0, 14).map(MEM.logRow).join("") || '<li class="ak-empty">기록 없음</li>';
}

/* ── 판 등록 ────────────────────────────────────────────────────────────────── */

MEM.panels.inject = {
  html:
      '<section class="ak-card" aria-label="전달">'
    + '<h3 class="ak-card__title">전달 <span class="mem-dim" id="mem-inj-meta"></span></h3>'
    + '<div id="mem-inj-state"></div>'
    + '<div class="mem-injgrid"><div>'
    + '<p class="mem-sectitle">모델에게 그대로 전달되는 내용</p>'
    + '<pre class="mem-injblock" id="mem-inj-block" tabindex="0" aria-label="전달 내용 원문">—</pre>'
    + '<p class="ak-card__note">앞뒤 빈 줄만 접었고, 나머지는 실제로 전달되는 글자 그대로예요.'
    + ' 여기 없는 내용은 모델도 볼 수 없어요.</p></div><div>'
    + '<p class="mem-sectitle">종류별 한도 — 모자란 곳과 넘치는 곳</p>'
    + '<ul class="mem-meter" id="mem-inj-meter"></ul>'
    + '<div id="mem-inj-excluded"></div></div></div></section>',
  // 전달만 스냅샷 밖이다 — 블록 원문이 커서 이 탭을 열 때만 받는다.
  render: async function(){
    q("mem-inj-block").innerHTML = "불러오는 중이에요…";
    if(!MEM.APP.inj) MEM.APP.inj = await MEM.fetchInjection();
    renderInjection(MEM.APP.inj);
  },
};
MEM.panels.tend = {
  html:
      '<section class="ak-card" aria-label="노른 정리">'
    + '<h3 class="ak-card__title">노른 정리 <span class="mem-dim" id="mem-norn-meta"></span></h3>'
    + '<div class="mem-modes" id="mem-norn-modes"></div>'
    + '<div class="mem-nrngrid">'
    + '<section aria-label="통찰 계보"><h4>통찰 계보</h4>'
    + '<p class="ak-card__note">출처 페이지에서 뽑아낸 통찰과 코드가 계산한 확신도예요.</p>'
    + '<ul class="mem-lineage" id="mem-norn-insights"></ul></section>'
    + '<section aria-label="모순"><h4>모순 — 사람이 판단할 항목</h4>'
    + '<p class="ak-card__note">노른은 어긋난 기록을 고치지 않고 알리기만 해요.</p>'
    + '<ul class="mem-contra" id="mem-norn-contra"></ul></section>'
    + '<section aria-label="정리 리포트"><h4>정리 리포트</h4>'
    + '<p class="ak-card__note">정리할 때마다 남는 기록 — reports/ 는 한도 밖이에요.</p>'
    + '<ul class="mem-log" id="mem-norn-reports"></ul></section>'
    + '</div></section>'
    + '<div class="mem-two">'
    + '<section class="ak-card" aria-label="보관함">'
    + '<h3 class="ak-card__title">보관함 <span class="mem-dim" id="mem-arc-meta"></span></h3>'
    + '<p class="ak-card__note">보관함으로 옮긴 페이지예요. 지운 것이 아니라서 언제든 되살릴 수 있어요.</p>'
    + '<ul class="mem-arcs" id="mem-norn-archive"></ul></section>'
    + '<section class="ak-card" aria-label="피어 카드">'
    + '<h3 class="ak-card__title">피어 카드 <span class="mem-dim" id="mem-peer-meta"></span></h3>'
    + '<p class="ak-card__note">사용자를 관찰한 내용을 모아 만든 요약이에요. 근거 페이지에서 다시 만들어져요.</p>'
    + '<ul class="mem-arcs" id="mem-peer"></ul></section></div>'
    + '<section class="ak-card" aria-label="백업">'
    + '<h3 class="ak-card__title">정리 직전 백업 <span class="mem-dim" id="mem-bk-meta"></span></h3>'
    + '<ul class="mem-arcs" id="mem-norn-backups"></ul></section>',
  render: renderNorn,
};
MEM.panels.chronicle = {
  html:
      '<section class="ak-card" aria-label="운영 연대기">'
    + '<h3 class="ak-card__title">운영 연대기 <span class="mem-dim" id="mem-chron-count"></span></h3>'
    + '<div id="mem-op-chips" class="mem-chips" role="group" aria-label="작업 갈래 필터"></div>'
    + '<div id="mem-day-filter"></div>'
    + '<div class="mem-chrono" id="mem-chron" aria-live="polite"></div>'
    + '<div id="mem-chron-pgn"></div></section>',
  render: renderChronicle,
};
MEM.panels.activity = {
  html:
      '<section class="ak-card" aria-label="활동 열지도">'
    + '<h3 class="ak-card__title">활동 <span class="mem-dim" id="mem-act-meta"></span></h3>'
    + '<div id="mem-heat"></div></section>'
    + '<div class="mem-two">'
    + '<section class="ak-card" aria-label="작업 분포"><h3 class="ak-card__title">작업 분포</h3>'
    + '<div id="mem-opbars" class="mem-bars"></div></section>'
    + '<section class="ak-card" aria-label="최근 피드"><h3 class="ak-card__title">최근 피드</h3>'
    + '<ul class="mem-log" id="mem-feed"></ul></section></div>',
  render: renderActivity,
};

// 셸이 모르는 행동은 여기로 넘어온다 — 판마다 리스너를 따로 달지 않는다.
const prevAction = MEM.onAction;
MEM.onAction = function(act, target){
  const APP = MEM.APP;
  if(act === "op"){
    APP.op = target.dataset.op || "";
    APP.chronOffset = 0;
    document.querySelectorAll("#mem-op-chips .ak-chip").forEach((c) => {
      c.setAttribute("aria-pressed", (c.dataset.op || "") === APP.op ? "true" : "false");
    });
    loadChron();
  }
  else if(act === "day-clear"){
    APP.day = "";
    APP.chronOffset = 0;
    renderDayFilter();
    loadChron();
  }
  else if(act === "chron-page"){
    APP.chronOffset = Math.max(0, parseInt(target.dataset.page, 10) || 0) * CHRON_LIMIT;
    loadChron();
  }
  else if(act === "heat"){ // 열지도 칸 → 연대기의 그 하루
    APP.day = target.dataset.day || "";
    APP.chronOffset = 0;
    APP.loaded.chronicle = false;
    MEM.switchTab("chronicle");
  }
  else if(prevAction) prevAction(act, target);
};
})();
