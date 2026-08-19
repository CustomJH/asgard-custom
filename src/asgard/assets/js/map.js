"use strict";
/* 맵 화면의 나머지 절반 — 자료·상태·뿌리 선택기·상호작용. 그리는 쪽은 `map-draw.js` 다.
 *
 * 옛 맵은 자립형 창이었다. `asgard map view` 가 그래프를 HTML 에 구워 `file://` 로 열었고,
 * 자료는 페이지 안의 `<script id="data">` 에 박혀 있었다. 그래서 그 창에는 로딩도 오류도
 * 없었다 — 문서가 열렸으면 자료는 이미 거기 있었으니까.
 *
 * 이제는 창구를 탄다. `GET /api/map/graph?root=…` 는 200 말고도 셋을 낸다.
 *
 *   · 409 `map_unscanned` — 그 뿌리를 아직 안 훑었다. 오류가 아니라 **상태**다. 창구는 남의
 *     저장소에 상태 파일을 쓰지 않으려고 대신 스캔하지 않으므로, 화면이 처방을 대신 말한다.
 *   · 403 `map_root_unknown` — 목록 밖 경로. 선택기에서만 고르면 날 일이 없다.
 *   · 그 밖 — 창구가 낸 `error.message`·`error.remedy` 를 그대로 옮긴다.
 *
 * 그래서 이 파일이 옛 창에 없던 것을 넷 갖는다: 로딩 · 빈 그래프 · 미스캔 · 오류.
 */
(function (global) {
  const API_ROOTS = "/api/map/roots";
  const API_GRAPH = "/api/map/graph";

  // 뿌리가 목록에 있는 이유 — 사용자가 "이 줄이 왜 여기 있나"를 물을 필요가 없게 이름을 붙인다.
  const SOURCE_LABEL = {
    session: "지금 이 세션",
    workspace: "스튜디오에서 연 곳",
    declared: "asgard root add 로 선언한 곳",
  };

  const HINT_STAR = "드래그 궤도 · Shift+드래그 팬 · 휠 줌 · 클릭 선택 · 키: 화살표 궤도 / + − / 0 전체 / v 성좌⇄레인 / t 체인 / Esc";
  const HINT_LANE = "드래그 팬 · 휠 줌 · 클릭 선택 · 키: 화살표 / + − / 0 전체 / v 성좌⇄레인 / t 체인 / Esc";

  const SHELL = `
<div class="map-head">
  <div>
    <div class="map-roots">
      <label class="ak-field__label" for="map-root-select">프로젝트</label>
      <select class="ak-select" id="map-root-select" data-map="rootpick"></select>
    </div>
    <p class="map-rootpath" data-map="rootpath"></p>
  </div>
  <p class="map-stats" data-map="stats"></p>
</div>
<div class="map-body">
  <div class="map-stage" data-map="stage">
    <canvas data-map="canvas" tabindex="0" role="application" aria-describedby="map-hint"
      aria-label="관계 그래프 캔버스 — 노드를 클릭하면 증거가 열려요. 화살표 키로 궤도를 돌리고 Shift+화살표로 평면 이동, 더하기·빼기 줌, 0 전체 보기, v 배치 전환, t 체인 추적, Esc 해제. 캔버스 없이도 옆의 노드 선택 목록으로 탐색할 수 있어요."></canvas>
    <div class="map-modebar" role="group" aria-label="배치 모드">
      <button type="button" data-map="mode-star" aria-pressed="true">성좌</button>
      <button type="button" data-map="mode-lane" aria-pressed="false">레인</button>
    </div>
    <div class="map-zoombar" role="group" aria-label="보기 조절">
      <button type="button" data-map="zoom-in" aria-label="확대">＋</button>
      <button type="button" data-map="zoom-out" aria-label="축소">−</button>
      <button type="button" data-map="zoom-fit" aria-label="전체 보기">⤢</button>
    </div>
    <p class="map-hint" id="map-hint" data-map="hint"></p>
    <p class="map-viscount" data-map="viscount" aria-hidden="true"></p>
    <button type="button" class="ak-btn map-visreset" data-map="visreset" hidden>필터로 모두 숨겨졌어요 — 필터 초기화</button>
    <div class="map-tip" data-map="tip" hidden></div>
    <div class="map-state" data-map="state" role="status" aria-live="polite" hidden></div>
  </div>
  <aside class="map-panel" aria-label="그래프 조작과 상세">
    <div class="ak-field">
      <label class="ak-field__label" for="map-q">노드 검색</label>
      <input class="ak-input" id="map-q" data-map="q" type="search" placeholder="이름·id"
        autocomplete="off" spellcheck="false">
    </div>
    <p class="map-qhint" data-map="qhint" hidden></p>
    <ul class="d-rel map-results" data-map="results" hidden
      aria-label="검색 결과 — 위아래 화살표로 이동, Enter 로 선택"></ul>
    <div class="ak-field">
      <label class="ak-field__label" for="map-node">노드 선택 — 증거 보기</label>
      <select class="ak-select" id="map-node" data-map="node"></select>
    </div>
    <section class="map-detail" data-map="detail" aria-live="polite"></section>
    <section>
      <h2 class="map-sectitle">종류 필터</h2>
      <div class="map-chips" data-map="legend" role="group" aria-label="노드 종류 필터"></div>
      <p class="map-subhint">클릭 = 토글 · Alt(⌥)+클릭 = 단독 보기</p>
    </section>
    <section data-map="ekinds" aria-label="엣지 종류"></section>
    <p class="map-foot">깊은 추적 — <code>asgard map trace --from &lt;node-id&gt;</code></p>
  </aside>
</div>`;

  let mounted = null;

  function esc(value) {
    const span = document.createElement("span");
    span.textContent = value == null ? "" : String(value);
    return span.innerHTML.replace(/"/g, "&quot;");
  }

  function build(host) {
    const root = document.createElement("div");
    root.className = "map-view";
    root.innerHTML = SHELL;
    host.appendChild(root);
    const el = {};
    for (const node of root.querySelectorAll("[data-map]")) el[node.dataset.map] = node;
    el.root = root;
    return el;
  }

  function create(host) {
    const el = build(host);
    const view = global.AsgardMapDraw.create({
      canvas: el.canvas,
      stage: el.stage,
      hooks: {
        onSelect: renderDetail,
        onVisible: updateVis,
        onMode: (lane) => {
          el["mode-star"].setAttribute("aria-pressed", String(!lane));
          el["mode-lane"].setAttribute("aria-pressed", String(lane));
          el.hint.textContent = lane ? HINT_LANE : HINT_STAR;
          syncChips();
        },
      },
    });
    let rootPath = "";
    let resIds = [], resIdx = -1;
    const mobile = global.matchMedia("(max-width: 720px)");
    el.hint.textContent = HINT_STAR;

    // ── 상태 넷 ────────────────────────────────────────────────────────────
    function showState(kind, title, body, remedy, retry) {
      el.state.className = "map-state" + (kind ? " map-state--" + kind : "");
      let html = "";
      if (kind === "loading") {
        html = '<h2>관계 그래프를 읽는 중이에요</h2>'
          + '<span class="ak-skeleton"></span><span class="ak-skeleton"></span><span class="ak-skeleton"></span>';
      } else {
        html = "<h2>" + esc(title) + "</h2><p>" + esc(body) + "</p>";
        if (remedy) html += "<p><code>" + esc(remedy) + "</code></p>";
        if (retry) html += '<button type="button" class="ak-btn ak-btn--secondary" data-retry>다시 시도</button>';
      }
      el.state.innerHTML = html;
      el.state.hidden = false;
    }

    function clearState() { el.state.hidden = true; el.state.innerHTML = ""; }

    el.state.addEventListener("click", (e) => {
      if (e.target.closest("[data-retry]")) loadGraph(rootPath);
    });

    // ── 뿌리 선택기 ────────────────────────────────────────────────────────
    async function loadRoots() {
      const listing = await ask(API_ROOTS);
      if (listing.error) {
        showState("error", "프로젝트 목록을 못 읽었어요", listing.error.message, listing.error.remedy, true);
        return;
      }
      const groups = {};
      for (const row of listing.roots) (groups[row.source] = groups[row.source] || []).push(row);
      el.rootpick.innerHTML = "";
      for (const source of ["session", "workspace", "declared"]) {
        const rows = groups[source];
        if (!rows) continue;
        const group = document.createElement("optgroup");
        group.label = SOURCE_LABEL[source] || source;
        for (const row of rows) {
          const option = document.createElement("option");
          option.value = row.root;
          // 미스캔은 고를 수 있어야 한다 — 고른 다음 화면이 처방을 말하는 것이 이 흐름이다.
          option.textContent = row.name + (row.scanned ? "" : " · 아직 안 훑음");
          option.selected = row.current;
          group.appendChild(option);
        }
        el.rootpick.appendChild(group);
      }
      const chosen = el.rootpick.value || listing.current;
      await loadGraph(chosen);
    }

    async function ask(url) {
      try {
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        const body = await response.json().catch(() => ({}));
        if (response.ok) return body;
        return body.error ? body : { error: { code: "http_" + response.status, message: "창구가 " + response.status + " 로 답했어요" } };
      } catch (failure) {
        return { error: { code: "unreachable", message: "창을 띄운 서버에 닿지 않아요 — " + failure.message, remedy: "asgard open studio" } };
      }
    }

    async function loadGraph(root) {
      rootPath = root || "";
      el.rootpath.textContent = rootPath;
      view.stopLoop();
      showState("loading");
      const payload = await ask(API_GRAPH + (root ? "?root=" + encodeURIComponent(root) : ""));
      if (payload.error) {
        const err = payload.error;
        if (err.code === "map_unscanned") {
          showState("unscanned", err.message, "맵은 스캔한 뿌리만 열어요 — 다른 저장소에 파일을 만들지 않으려고 대신 훑지 않아요.", err.remedy, true);
        } else {
          showState("error", "그래프를 못 읽었어요", err.message, err.remedy, true);
        }
        view.load({ nodes: [], edges: [], records: {} });
        renderAll(null);
        return;
      }
      view.load(payload);
      if (!view.model.nodes.length) {
        showState("empty", "그래프가 비어 있어요", "훑을 관계를 못 찾았어요. 스캔을 다시 돌리면 채워져요.", "asgard map scan", true);
      } else clearState();
      renderAll(payload);
      view.resize();
      view.fit();
      view.draw();
      view.startLoop();
    }

    // ── 계기 · 범례 ────────────────────────────────────────────────────────
    function renderAll(payload) {
      renderStats(payload);
      renderLegend();
      renderEdgeKinds();
      buildOptions();
      renderResults();
      renderDetail(null);
    }

    function renderStats(payload) {
      if (!payload) { el.stats.innerHTML = ""; return; }
      const counts = payload.counts || {};
      const model = view.model;
      const gauges = [
        ["files", counts.files_scanned, "스캔한 파일"],
        ["evidence", counts.evidence, "수집한 file:line 증거"],
        ["nodes", counts.nodes == null ? model.nodes.length : counts.nodes, "그래프 노드 — 개념+파일"],
        ["edges", counts.edges == null ? model.edges.length : counts.edges, "그래프 엣지"],
        ["flows", counts.flows, "개념→개념 플로우 엣지"],
      ];
      let html = gauges.filter((g) => g[1] != null)
        .map((g) => '<span class="g" title="' + esc(g[2]) + '"><b>' + esc(g[1]) + "</b><i>" + g[0] + "</i></span>").join("");
      if ((counts.api_links | 0) > 0) {
        html += '<span class="g" title="FE api_call ↔ BE route 조인"><b>' + esc(counts.api_links) + "</b><i>api-links</i></span>";
      }
      if (payload.revision) {
        const rev = String(payload.revision);
        const short = rev.includes(":") ? rev.split(":").pop().slice(0, 8) : rev.slice(0, 10);
        html += '<span class="rev" title="' + esc(rev) + '">rev ' + esc(short) + "</span>";
      }
      el.stats.innerHTML = html;
    }

    function renderLegend() {
      el.legend.innerHTML = "";
      const model = view.model;
      for (const kind of global.AsgardMapDraw.KIND_ORDER) {
        if (!model.kindCount[kind]) continue;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "ak-chip";
        chip.dataset.kind = kind;
        chip.setAttribute("aria-pressed", "true");
        chip.innerHTML = '<i style="background:' + esc(view.colorOf(kind)) + '"></i>' + esc(kind)
          + ' <span class="n">' + model.kindCount[kind] + "</span>";
        chip.addEventListener("click", (e) => {
          if (e.altKey) view.soloKind(kind);
          else {
            const on = view.filters.active;
            if (on.has(kind)) on.delete(kind); else on.add(kind);
          }
          syncChips();
          if (view.selected && !view.state(view.selected)) view.select(null); else view.draw();
        });
        // 호버 미리보기 — 색만으로 헷갈리는 구분을 그 자리에서 푼다(터치는 미리보기가 없다)
        chip.addEventListener("pointerenter", (e) => {
          if (e.pointerType === "touch") return;
          view.setPreviewKind(kind);
          view.scheduleDraw();
        });
        chip.addEventListener("pointerleave", () => { view.setPreviewKind(null); view.scheduleDraw(); });
        el.legend.appendChild(chip);
      }
      const candN = model.nodes.filter((n) => n.confidence === "candidate").length;
      if (!candN) return;
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "ak-chip";
      toggle.dataset.cand = "1";
      // 테마가 바뀌면 범례를 다시 짓는다 — 그때 지금 상태를 잃지 않게 여기서 읽어 세운다
      toggle.setAttribute("aria-pressed", String(view.filters.showCand));
      toggle.title = "구문으로 증명되지 않은 후보 — 단정 전에 소스를 확인하세요";
      toggle.innerHTML = '<i class="cand-dot"></i>후보 <span class="n">' + candN + "</span>";
      toggle.addEventListener("click", () => {
        const next = !view.filters.showCand;
        view.setShowCand(next);
        toggle.setAttribute("aria-pressed", String(next));
        if (view.selected && !view.state(view.selected)) view.select(null); else view.draw();
      });
      el.legend.appendChild(toggle);
    }

    function syncChips() {
      const on = view.filters.active;
      for (const chip of el.legend.children) {
        if (!chip.dataset.kind) continue; // 후보 토글은 자기 상태를 따로 갖는다
        chip.setAttribute("aria-pressed", String(on.has(chip.dataset.kind)));
        chip.disabled = view.laneMode && chip.dataset.kind === "file";
        if (chip.disabled) chip.title = "레인 모드에서는 파일 노드를 접어 둬요 — 증거는 오른쪽 패널에 남아요";
        else chip.removeAttribute("title");
      }
    }

    function renderEdgeKinds() {
      const kinds = global.AsgardMapDraw.EDGE_KINDS;
      const dash = global.AsgardMapDraw.EDGE_DASH;
      const counts = view.model.edgeKindCount;
      el.ekinds.innerHTML = '<h2 class="map-sectitle">엣지 언어 — 클릭 = 필터</h2><ul class="map-ekl">'
        + kinds.map((k) => {
          const pattern = dash[k].join(" "), n = counts[k] || 0;
          return '<li><button type="button" data-ek="' + k + '" aria-pressed="true"' + (n ? "" : " disabled") + ">"
            + '<svg viewBox="0 0 28 6" width="28" height="6" aria-hidden="true">'
            + '<line x1="1" y1="3" x2="27" y2="3" stroke="currentColor" stroke-width="1.6"'
            + (pattern ? ' stroke-dasharray="' + pattern + '"' : "") + "></line></svg>"
            + esc(k) + " <b>" + n + "</b></button></li>";
        }).join("") + "</ul>";
    }

    el.ekinds.addEventListener("click", (e) => {
      const button = e.target.closest("[data-ek]");
      if (!button || button.disabled) return;
      const on = view.filters.activeEdge, kind = button.dataset.ek;
      if (on.has(kind)) on.delete(kind); else on.add(kind);
      button.setAttribute("aria-pressed", String(on.has(kind)));
      view.draw();
    });

    function updateVis(visible, total) {
      el.viscount.textContent = "표시 " + visible + " / " + total;
      const show = !visible && total > 0;
      if (el.visreset.hidden === show) el.visreset.hidden = !show;
    }

    el.visreset.addEventListener("click", () => {
      view.resetFilters();
      el.q.value = "";
      el.qhint.hidden = true;
      renderResults();
      for (const chip of el.legend.children) chip.setAttribute("aria-pressed", "true");
      for (const button of el.ekinds.querySelectorAll("[data-ek]")) {
        if (!button.disabled) button.setAttribute("aria-pressed", "true");
      }
      syncChips();
      buildOptions();
      view.fit();
      view.draw();
    });

    // ── 상세 — 선택 노드의 증거 ────────────────────────────────────────────
    function renderDetail(node) {
      const model = view.model;
      if (!model.nodes.length) {
        el.detail.innerHTML = '<p class="d-empty">볼 그래프가 없어요.</p>';
        el.node.value = "";
        return;
      }
      if (!node) {
        el.detail.innerHTML = '<p class="d-empty">노드를 고르면 file:line 증거가 나와요.</p>';
        el.node.value = "";
        return;
      }
      el.node.value = node.kind === "file" ? "" : node.id;
      const recs = model.records[node.id] || [];
      let html = '<div class="d-kind"><i style="background:' + esc(view.colorOf(node.kind)) + '"></i>' + esc(node.kind)
        + (node.confidence === "candidate" ? ' <span class="cand">candidate — 단정 전 소스 확인</span>' : "")
        + '<span class="d-deg">이웃 ' + (model.degree[node.id] || 0) + "</span></div>"
        + '<div class="d-id">' + esc(node.id) + "</div>"
        + '<h3 class="d-h">증거 ' + node.files.length + "</h3><ul class=\"d-ev\">"
        + node.files.map((f) => "<li><b>" + esc(f.file) + ":" + esc(f.line) + "</b>"
          + (f.confidence === "candidate" ? ' <span class="cand">?</span>' : "")
          + (f.detail ? ' <span class="d-det">— ' + esc(f.detail) + "</span>" : "") + "</li>").join("")
        + "</ul>";
      html += relatedHtml(node);
      html += chainHtml(node);
      if (recs.length) {
        html += '<h3 class="d-h">관련 기록 — 프로젝트 메모리</h3><ul class="d-rec">'
          + recs.map((r) => '<li><span class="rt">' + esc(r.title) + '</span><span class="rm">' + esc(r.match)
            + '</span><span class="rf">' + esc(r.file) + "</span></li>").join("") + "</ul>";
      }
      html += '<h3 class="d-h">추적</h3><code class="d-code">asgard map trace --from ' + esc(node.id) + "</code>";
      el.detail.innerHTML = html;
    }

    /** 연계 노드 — 같은 파일 증거를 공유하는 개념까지 본다(1-hop 파일에 갇히지 않는다). */
    function relatedHtml(node) {
      const model = view.model;
      let related = [];
      if (node.kind === "file") {
        related = model.edges.filter((e) => e.source === node.id).map((e) => ({ o: model.byId[e.target], via: [node.name] }));
      } else {
        const files = new Set(model.edges.filter((e) => e.target === node.id).map((e) => e.source));
        const acc = {};
        for (const e of model.edges) {
          if (!files.has(e.source) || e.target === node.id) continue;
          (acc[e.target] = acc[e.target] || { o: model.byId[e.target], via: [] }).via.push(model.byId[e.source].name);
        }
        related = Object.values(acc);
      }
      const order = global.AsgardMapDraw.KIND_ORDER;
      related.sort((a, b) => order.indexOf(a.o.kind) - order.indexOf(b.o.kind) || a.o.name.localeCompare(b.o.name));
      if (!related.length) return "";
      const cap = 24;
      return '<h3 class="d-h">연계 노드 ' + related.length + ' — 파일 경유</h3><ul class="d-rel">'
        + related.slice(0, cap).map((r) => {
          const first = r.via[0].split("/").pop();
          const label = r.via.length > 1 ? first + " +" + (r.via.length - 1) : first;
          return '<li><button type="button" data-nid="' + esc(r.o.id) + '" title="' + esc(r.via.join(", ")) + '">'
            + '<i style="background:' + esc(view.colorOf(r.o.kind)) + '"></i>'
            + '<span class="rk">' + esc(r.o.kind) + '</span><span class="rn">' + esc(r.o.name) + "</span>"
            + '<span class="rv">' + esc(label) + "</span></button></li>";
        }).join("")
        + (related.length > cap ? '<li class="more">+' + (related.length - cap) + " — trace 로 전체 추적</li>" : "")
        + "</ul>";
    }

    /** 체인 추적 — 플로우가 있는 개념만. 파일은 증거 캐리어라 상·하류가 없다. */
    function chainHtml(node) {
      const model = view.model, trace = view.trace;
      const inN = (model.IN[node.id] || []).length, outN = (model.OUT[node.id] || []).length;
      if (node.kind === "file" || !(inN || outN)) return "";
      let html = '<h3 class="d-h">' + (trace
        ? "체인 — 노드 " + (trace.nodes.size - 1) + " · 엣지 " + trace.eset.size + " · 깊이 4"
        : "체인 — 직결 상류 " + inN + " · 하류 " + outN) + "</h3>"
        + '<div class="d-act"><button type="button" class="ak-btn ak-btn--secondary" data-trace aria-pressed="'
        + (trace ? "true" : "false") + '">' + (trace ? "체인 해제 (t)" : "상·하류 4단 추적 (t)") + "</button></div>";
      if (!trace) return html;
      const cap = 30;
      const row = (c) => {
        const o = model.byId[c.id];
        return '<li><button type="button" data-nid="' + esc(c.id) + '">'
          + '<span class="dep">' + (c.up ? "‹" : "›").repeat(c.d) + "</span>"
          + '<i style="background:' + esc(view.colorOf(o.kind)) + '"></i>'
          + '<span class="rk">' + esc(o.kind) + '</span><span class="rn">' + esc(o.name) + "</span></button></li>";
      };
      for (const side of [trace.up, trace.down]) {
        if (!side.length) continue;
        html += '<ul class="d-rel">' + side.slice(0, cap).map(row).join("")
          + (side.length > cap ? '<li class="more">+' + (side.length - cap) + " — trace 로 전체</li>" : "") + "</ul>";
      }
      return html + '<p class="map-subhint">체인은 필터와 무관하게 전체 플로우를 따라가요 · 깊이 4 · 클릭 = 이동</p>';
    }

    el.detail.addEventListener("click", (e) => {
      if (e.target.closest("[data-trace]")) {
        if (view.trace) view.clearTrace();
        else if (view.selected) view.runTrace(view.selected);
        renderDetail(view.selected);
        view.draw();
        return;
      }
      const button = e.target.closest("[data-nid]");
      if (!button) return;
      pick(button.dataset.nid);
    });

    function pick(id) {
      const node = view.model.byId[id];
      if (!node) return;
      view.ensureKind(node.kind);
      syncChips();
      view.select(node); // 선택이 체인 카메라를 되돌리므로 센터링은 그 뒤다
      view.centerOn(node);
      view.scheduleDraw();
      if (mobile.matches) el.detail.scrollIntoView({ behavior: global.AsgardMapDraw.reduced() ? "auto" : "smooth", block: "nearest" });
    }

    // ── 검색 · 노드 목록(캔버스의 대체 표현) ───────────────────────────────
    function concepts() {
      return view.model.nodes.filter((n) => n.kind !== "file" && matches(n));
    }

    function matches(n) {
      const q = view.filters.query;
      return !q || (n.id + " " + n.name).toLowerCase().includes(q);
    }

    function buildOptions() {
      const keep = el.node.value;
      el.node.innerHTML = "";
      const head = document.createElement("option");
      head.value = "";
      head.textContent = "노드 선택 — 증거 보기";
      el.node.appendChild(head);
      for (const n of concepts().sort((a, b) => a.id.localeCompare(b.id))) {
        const option = document.createElement("option");
        option.value = n.id;
        option.textContent = n.id;
        el.node.appendChild(option);
      }
      el.node.value = keep;
    }

    el.node.addEventListener("change", () => { if (el.node.value) pick(el.node.value); else view.select(null); });

    function renderResults() {
      resIdx = -1;
      const q = view.filters.query;
      if (!q) { el.results.hidden = true; el.results.innerHTML = ""; resIds = []; return; }
      const model = view.model;
      const weight = (n) => model.degree[n.id] || 0;
      resIds = concepts().sort((a, b) => {
        // 접두 일치가 먼저다 — 검색어로 시작하는 이름이 부분 일치보다 찾던 것일 확률이 높다
        const ap = a.name.toLowerCase().startsWith(q) ? 0 : 1;
        const bp = b.name.toLowerCase().startsWith(q) ? 0 : 1;
        return ap - bp || weight(b) - weight(a) || a.id.localeCompare(b.id);
      }).slice(0, 50).map((n) => n.id);
      el.results.innerHTML = resIds.map((id) => {
        const n = model.byId[id];
        return '<li><button type="button" data-nid="' + esc(n.id) + '">'
          + '<i style="background:' + esc(view.colorOf(n.kind)) + '"></i>'
          + '<span class="rk">' + esc(n.kind) + '</span><span class="rn">' + esc(n.name) + "</span>"
          + '<span class="deg">이웃 ' + (model.degree[n.id] || 0) + "</span></button></li>";
      }).join("");
      el.results.hidden = !resIds.length;
    }

    el.results.addEventListener("click", (e) => {
      const button = e.target.closest("[data-nid]");
      if (button) pick(button.dataset.nid);
    });

    function setResIdx(i) {
      resIdx = i;
      [...el.results.children].forEach((li, j) => li.classList.toggle("is-active", j === resIdx));
      const li = el.results.children[resIdx];
      if (li) li.scrollIntoView({ block: "nearest" });
    }

    el.q.addEventListener("input", () => {
      view.setQuery(el.q.value.trim().toLowerCase());
      buildOptions();
      renderResults();
      // 세는 것은 **아래 목록에 실제로 올라간 줄**이다. 캔버스에서 밝아지는 것까지 세면
      // "2개 일치" 밑에 한 줄만 있는 화면이 나온다 — 파일 노드는 목록에 안 오르기 때문이다.
      el.qhint.hidden = !view.filters.query;
      el.qhint.textContent = resIds.length
        ? resIds.length + "개 — ↑↓ 이동 · Enter 선택"
        : "일치하는 개념 노드가 없어요";
      view.draw();
    });

    el.q.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" && resIds.length) { e.preventDefault(); setResIdx(Math.min(resIdx + 1, resIds.length - 1)); return; }
      if (e.key === "ArrowUp" && resIds.length) { e.preventDefault(); setResIdx(Math.max(resIdx - 1, 0)); return; }
      if (e.key === "Escape" && view.filters.query) { el.q.value = ""; el.q.dispatchEvent(new Event("input")); return; }
      if (e.key !== "Enter" || !resIds.length) return;
      pick(resIds[resIdx >= 0 ? resIdx : 0]);
    });

    // ── 카메라 · 포인터 · 키보드 ───────────────────────────────────────────
    el["zoom-in"].addEventListener("click", () => view.zoomBy(1.25));
    el["zoom-out"].addEventListener("click", () => view.zoomBy(0.8));
    el["zoom-fit"].addEventListener("click", () => { view.fit(); view.draw(); });
    el["mode-star"].addEventListener("click", () => view.setMode(false));
    el["mode-lane"].addEventListener("click", () => view.setMode(true));

    el.canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = el.canvas.getBoundingClientRect();
      const d = Math.max(1, global.devicePixelRatio || 1);
      view.zoomAt((e.clientX - r.left) * d, (e.clientY - r.top) * d, view.scale * (e.deltaY < 0 ? 1.12 : 0.9));
    }, { passive: false });

    const pointers = new Map();
    let pinch = null, downAt = null, moved = 0;

    el.canvas.addEventListener("pointerdown", (e) => {
      el.canvas.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 2) {
        const p = [...pointers.values()];
        pinch = { d: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) || 1, s: view.scale };
        downAt = null;
      } else { downAt = { x: e.clientX, y: e.clientY }; moved = 0; }
    });

    el.canvas.addEventListener("pointermove", (e) => {
      if (pointers.size) { drag(e); return; }
      const node = view.hitTest(e);
      if (node !== view.hover) { view.hover = node; view.scheduleDraw(); }
      el.canvas.style.cursor = node ? "pointer" : "grab";
      if (node) showTip(e, node); else el.tip.hidden = true;
    });

    function drag(e) {
      const prev = pointers.get(e.pointerId);
      if (!prev) return;
      if (pointers.size === 1 && downAt) {
        const dx = e.clientX - prev.x, dy = e.clientY - prev.y;
        moved += Math.abs(dx) + Math.abs(dy);
        if (moved > 4) {
          // 성좌에서 끌기는 궤도다 — 평면 이동은 Shift(또는 두 손가락)로 남겨 둔다
          if (view.space && !e.shiftKey) view.orbitBy(dx, dy); else view.panBy(dx, dy);
          el.canvas.style.cursor = "grabbing";
          view.scheduleDraw();
        }
      }
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pointers.size === 2) {
        const p = [...pointers.values()];
        const dist = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) || 1;
        const r = el.canvas.getBoundingClientRect();
        const mx = (p[0].x + p[1].x) / 2, my = (p[0].y + p[1].y) / 2;
        // 두 손가락은 줌과 팬을 함께 — 터치에도 평면 이동 수단이 남는다
        if (pinch.mx != null) view.panBy(mx - pinch.mx, my - pinch.my);
        pinch.mx = mx; pinch.my = my;
        const d = Math.max(1, global.devicePixelRatio || 1);
        view.zoomAt((mx - r.left) * d, (my - r.top) * d, pinch.s * dist / pinch.d);
      }
    }

    function endPointer(e) {
      if (!pointers.has(e.pointerId)) return;
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      el.canvas.style.cursor = "grab";
      if (downAt && moved <= 4 && e.type === "pointerup") {
        const node = view.hitTest(e);
        if (node) pick(node.id); else view.select(null);
      }
      downAt = null;
    }

    el.canvas.addEventListener("pointerup", endPointer);
    el.canvas.addEventListener("pointercancel", endPointer);
    el.canvas.addEventListener("pointerleave", () => {
      if (!view.hover) return;
      view.hover = null;
      el.tip.hidden = true;
      view.draw();
    });

    function showTip(e, node) {
      el.tip.innerHTML = "<div>" + esc(node.name) + '</div><div class="k">' + esc(node.kind)
        + (node.confidence === "candidate" ? " · 후보 — 단정 전 소스 확인" : "") + "</div>";
      el.tip.hidden = false;
      const r = el.stage.getBoundingClientRect();
      const x = Math.min(e.clientX - r.left + 14, r.width - el.tip.offsetWidth - 8);
      const y = Math.min(e.clientY - r.top + 14, r.height - el.tip.offsetHeight - 8);
      el.tip.style.left = x + "px";
      el.tip.style.top = y + "px";
    }

    el.canvas.addEventListener("keydown", (e) => {
      const step = 48;
      const orbit = view.space && !e.shiftKey; // 성좌에서 화살표는 궤도, 평면 이동은 Shift+화살표
      let handled = true;
      if (e.key === "ArrowLeft") { if (orbit) view.orbitBy(-34, 0); else view.panBy(step, 0); }
      else if (e.key === "ArrowRight") { if (orbit) view.orbitBy(34, 0); else view.panBy(-step, 0); }
      else if (e.key === "ArrowUp") { if (orbit) view.orbitBy(0, -34); else view.panBy(0, step); }
      else if (e.key === "ArrowDown") { if (orbit) view.orbitBy(0, 34); else view.panBy(0, -step); }
      else if (e.key === "+" || e.key === "=") view.zoomBy(1.25);
      else if (e.key === "-" || e.key === "_") view.zoomBy(0.8);
      else if (e.key === "0") view.fit();
      else if (e.key === "v" || e.key === "V") view.setMode(!view.laneMode);
      else if (e.key === "t" || e.key === "T") {
        const node = view.selected;
        if (node && node.kind !== "file") {
          if (view.trace) view.clearTrace(); else view.runTrace(node);
          renderDetail(node);
        }
      } else if (e.key === "Escape") {
        if (view.trace) { view.clearTrace(); renderDetail(view.selected); } else view.select(null);
      } else handled = false;
      if (handled) { e.preventDefault(); view.draw(); }
    });

    el.rootpick.addEventListener("change", () => loadGraph(el.rootpick.value));

    // ── 테마 · 크기 · 가시성 ───────────────────────────────────────────────
    // 토큰만 바꾸고 재그리기를 안 붙이면 DOM 만 라이트가 되고 그림은 그대로 남는다.
    // 캔버스는 CSS 를 다시 읽지 않으므로 팔레트를 다시 만들어 줘야 한다.
    function repaintForTheme() {
      view.refreshPalette();
      renderLegend();
      syncChips();
      renderDetail(view.selected);
      renderResults();
      view.draw();
    }

    const themeWatch = new MutationObserver(repaintForTheme);
    themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    global.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", repaintForTheme);

    new ResizeObserver(() => {
      if (!view.resize()) return;
      view.fit();
      view.draw();
    }).observe(el.stage);

    // 화면이 안 보이면 프레임을 쓰지 않는다. 스튜디오는 판을 감춰 둘 뿐 떼지 않으므로,
    // 이걸 안 걸면 다른 화면을 보는 동안에도 힘 시뮬레이션이 계속 돈다.
    new IntersectionObserver((entries) => {
      const visible = entries.some((entry) => entry.isIntersecting);
      if (!visible) { view.stopLoop(); return; }
      view.resize();
      view.draw();
      view.startLoop();
    }).observe(el.stage);

    document.addEventListener("visibilitychange", () => { if (!document.hidden) view.startLoop(); });

    return { el: el, view: view, reload: loadRoots };
  }

  /** 스튜디오가 맵 화면에 들어올 때마다 부른다. 첫 호출만 짓고, 이후는 다시 그리기만 한다. */
  function initMapView() {
    const host = document.getElementById("map-view");
    if (!host) return null;
    if (!mounted) mounted = create(host);
    mounted.view.resize();
    mounted.view.draw();
    mounted.view.startLoop();
    if (!mounted.loaded) { mounted.loaded = true; mounted.reload(); }
    return mounted;
  }

  global.initMapView = initMapView;
})(window);
