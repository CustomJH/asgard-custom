"use strict";
/* 맵 화면의 그리는 절반 — 관계 그래프 캔버스.
 *
 * 옛 단일 파일 창(`assets/map_view.html`)의 렌더러를 옮겨 온 것이다. 옮기면서 바뀐 것은 둘뿐이다.
 *
 *   1. 색이 이 파일에 없다. 종류 색·잉크·금은 전부 `assets/ui/map.css` 의 사용자 정의 속성에서
 *      읽는다. 옛 창은 `PAL` 만 토큰에서 만들고 종류 팔레트 열셋은 16진수로 박아 뒀는데,
 *      라이트 테마가 생긴 지금 그 열셋은 흰 바탕에 다크용 색으로 남아 그래프만 어둡게 뜬다.
 *   2. 투명도를 미리 합성해 둔 색 문자열이 없다. 대신 `globalAlpha` 를 패스마다 세운다 — 토큰
 *      색은 `oklch()` 라 16진수처럼 잘라 붙일 수 없고, 어차피 패스 단위라 프레임당 문자열
 *      조립도 생기지 않는다.
 *
 * 캔버스 좌표는 CSS 픽셀이 아니라 장치 픽셀이다(`devicePixelRatio` 배). 카메라 오프셋 `off` 도
 * 같은 단위이므로, 마우스 좌표를 쓰는 자리는 전부 `dpr()` 을 곱한 뒤에 들어온다.
 */
(function (global) {
  // 종류 어휘의 정본은 파이썬(`map_graph.evidence.node_kinds`)이고 자료의 `kinds` 칸에 실려 온다.
  // 아래는 그 칸이 없던 옛 상태 파일을 여는 경우의 폴백일 뿐이다. 그리는 쪽이 목록을 소유하면
  // 파이썬에 종류가 하나 늘 때 그 하나가 범례에도 레인에도 서지 못한 채 사라진다.
  const KIND_ORDER = [
    "route", "page", "component", "store", "composable", "service", "command", "model",
    "db_access", "api_call", "event", "job", "external_service", "file",
  ];
  const EDGE_KINDS = ["declares", "calls", "touches", "uses", "emits"];
  const EDGE_DASH = { declares: [], calls: [7, 4], touches: [2, 4], uses: [11, 3, 2, 3], emits: [4, 3, 1, 3] };
  const FONT = '"SF Mono",Menlo,Consolas,monospace';

  // 상시 라벨 우선순위 — 차수에 종류 가중을 더한다. 순수 차수로 고르면 UI 킷 원자(Button·Card)가
  // 상위를 독점해서, 아키텍처를 읽으러 온 사람에게 아무것도 말해 주지 않는다.
  const KIND_BOOST = {
    page: 400, route: 400, store: 300, command: 220, job: 220, event: 220, model: 220,
    api_call: 160, db_access: 160, external_service: 160, composable: 120, service: 120, component: 0,
  };

  // 레인(계층 컬럼) — 아키텍처 흐름 순서. 비어 있는 레인은 접힌다.
  const LANES = [
    { label: "page", kinds: ["page"] },
    { label: "component", kinds: ["component"], tiered: true },
    { label: "composable · store", kinds: ["composable", "store"] },
    { label: "service", kinds: ["service"] },
    { label: "api_call", kinds: ["api_call"] },
    { label: "route", kinds: ["route"] },
    { label: "command · job · event", kinds: ["command", "job", "event"] },
    { label: "model", kinds: ["model"] },
    { label: "db · external", kinds: ["db_access", "external_service"] },
    { label: "file", kinds: ["file"] },
  ];
  const TIER_NAMES = ["atoms", "molecules", "organisms", "etc"];

  // 초점거리 1100 은 깊이가 읽히되 가장자리가 어안으로 휘지 않는 지점이다.
  const FOCAL = 1100;
  // 깊이 밴드 — 앞뒤 섬유가 갈라져 보이게 알파를 3단으로 나눈다. 평면(레인)에서는 1단.
  const DEPTH_BANDS = [[0, 0.93, 0.34], [0.93, 1.07, 0.72], [1.07, 9, 1]];
  const DRIFT_TURNS = 1400; // 도착 표류 — 부피를 한 번 읽히고 멈춘다(무한 턴테이블이 아니다)

  // 배경 성진 — 결정론 LCG라 새로 고쳐도 같은 하늘이 뜬다.
  const STARS = (() => {
    let s = 20260726;
    const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
    return Array.from({ length: 260 }, () => ({
      ux: rnd(), uy: rnd(), layer: 1 + Math.floor(rnd() * 3), a: 0.22 + rnd() * 0.5, r: rnd(),
    }));
  })();

  const dpr = () => Math.max(1, global.devicePixelRatio || 1);
  const reduced = () => global.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mix = (color, pct) => "color-mix(in srgb, " + color + " " + pct + "%, transparent)";

  /** 캔버스 하나를 맡는 렌더러. `canvas`·`stage` 와 화면 쪽 콜백(`hooks`)을 받는다. */
  function create(opts) {
    const canvas = opts.canvas;
    const stage = opts.stage;
    const hooks = opts.hooks || {};
    const ctx = canvas.getContext("2d");

    let PAL = {};
    let KIND_COLOR = {};
    let glowCache = {};

    let nodes = [], edges = [], byId = {};
    let degree = {}, kindCount = {}, edgeKindCount = {}, records = {};
    let OUT = {}, IN = {}, topLabel = new Set(), pulseEdges = [];
    let model = { nodes: nodes, edges: edges, byId: byId, degree: degree, kindCount: kindCount,
      edgeKindCount: edgeKindCount, records: records, OUT: OUT, IN: IN };

    let off = { x: 0, y: 0 }, scale = 1;
    let active = new Set(), activeEdge = new Set(EDGE_KINDS), query = "", showCand = true;
    let selected = null, hover = null, neighbors = new Set(), bridges = new Set(), previewKind = null;
    let userCam = false, hot = 0, settled = false, starSaved = false;
    let kindOrder = KIND_ORDER.slice();
    let laneMode = false, laneHeads = [], laneH = 0, morph = null, space = true, orbiting = false;
    let trace = null, traceT = 0, traceRaf = 0;
    let yaw = 0.42, pitch = -0.26, drift = 0;
    let cvx0 = -1e9, cvy0 = -1e9, cvx1 = 1e9, cvy1 = 1e9;
    let pulseT = 0, raf = 0, lastTs = 0, lastDraw = 0, drawQueued = false;

    // ── 팔레트 — 유일한 출처는 CSS 토큰이다 ────────────────────────────────
    function refreshPalette() {
      const cs = getComputedStyle(stage);
      const tok = (name) => (cs.getPropertyValue(name) || "").trim();
      PAL = { canvas: tok("--canvas"), ink: tok("--ink"), muted: tok("--muted"),
        faint: tok("--faint"), goldLit: tok("--gold-lit"), line: tok("--line-strong") };
      KIND_COLOR = { unknown: tok("--map-kind-unknown") };
      for (const kind of kindOrder) KIND_COLOR[kind] = tok("--map-kind-" + kind.replace(/_/g, "-"));
      glowCache = {};
    }

    const colorOf = (kind) => KIND_COLOR[kind] || KIND_COLOR.unknown;

    // ── 자료 적재 ──────────────────────────────────────────────────────────
    function load(payload) {
      records = payload.records || {};
      const raw = payload.nodes || [];
      // 성좌는 3차원이다 — 황금각 나선을 구면으로 올려 초기 부피를 준다. 레인은 z=0 으로 접힌다.
      nodes = raw.map((n, i) => {
        const t = (i + 0.5) / Math.max(1, raw.length);
        const zz = 1 - 2 * t;
        const rr = Math.sqrt(Math.max(0, 1 - zz * zz));
        const th = i * 2.399963;
        const span = 60 + Math.sqrt(i) * 22;
        return Object.assign({}, n, {
          x: Math.cos(th) * span * rr || Math.cos(th) * span,
          y: Math.sin(th) * span * rr || Math.sin(th) * span,
          z: zz * span * 0.55, vx: 0, vy: 0, vz: 0,
        });
      });
      byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
      edges = (payload.edges || []).filter((e) => byId[e.source] && byId[e.target]);
      degree = {}; kindCount = {}; edgeKindCount = {};
      for (const e of edges) {
        degree[e.source] = (degree[e.source] || 0) + 1;
        degree[e.target] = (degree[e.target] || 0) + 1;
      }
      for (const n of nodes) kindCount[n.kind] = (kindCount[n.kind] || 0) + 1;
      kindOrder = (payload.kinds && payload.kinds.length) ? payload.kinds.slice() : KIND_ORDER.slice();
      rebuildLanes();
      refreshPalette();
      for (const e of edges) edgeKindCount[e.kind] = (edgeKindCount[e.kind] || 0) + 1;
      const weight = (n) => (KIND_BOOST[n.kind] || 0) + (degree[n.id] || 0);
      topLabel = new Set(
        nodes.filter((n) => n.kind !== "file").sort((a, b) => weight(b) - weight(a))
          .slice(0, 14).map((n) => n.id),
      );
      // 플로우 인접(개념→개념) — 체인 추적과 레인 정렬의 재료. 파일은 증거 캐리어라 뺀다.
      OUT = {}; IN = {};
      for (const e of edges) {
        if (byId[e.source].kind === "file") continue;
        (OUT[e.source] = OUT[e.source] || []).push(e);
        (IN[e.target] = IN[e.target] || []).push(e);
      }
      // 시냅스 신호 — 상위 42개 엣지에만 점이 흐른다. 전 엣지에 걸면 프레임을 먹는다.
      pulseEdges = edges.filter((e) => byId[e.source].kind !== "file")
        .sort((a, b) => (degree[b.source] || 0) + (degree[b.target] || 0)
          - (degree[a.source] || 0) - (degree[a.target] || 0))
        .slice(0, 42).map((e, i) => ({ e: e, phase: i / 42 }));
      model = { nodes: nodes, edges: edges, byId: byId, degree: degree, kindCount: kindCount,
        edgeKindCount: edgeKindCount, records: records, OUT: OUT, IN: IN };

      active = new Set(kindOrder.filter((k) => kindCount[k]));
      activeEdge = new Set(EDGE_KINDS);
      query = ""; showCand = true; previewKind = null;
      selected = null; hover = null; neighbors = new Set(); bridges = new Set();
      trace = null; laneMode = false; space = true; settled = false; starSaved = false;
      off = { x: 0, y: 0 }; scale = 1; userCam = false; drift = 0;
      yaw = 0.42; pitch = -0.26;
      hot = reduced() ? 0 : 260;
      if (reduced()) { settle(); }
      // 큰 그래프는 레인으로 연다 — 결정론 배치라 물리 정착 없이 첫 페인트가 즉시다.
      if (nodes.length > 1200 && Object.keys(kindCount).filter((k) => k !== "file").length >= 3) {
        setMode(true, { snap: true });
      }
    }

    function settle() { // 시간 예산 정착 — 애니메이션 없이 자리를 잡는다
      const t0 = performance.now();
      let i = 0;
      while (i < 260 && performance.now() - t0 < 450) { tick(); i++; }
      settled = true;
    }

    // ── 표시 상태 ──────────────────────────────────────────────────────────
    const radius = (n) => (n.kind === "file" ? 3.2 : Math.min(11, 5 + (degree[n.id] || 0) * 0.55));
    const matches = (n) => !query || (n.id + " " + n.name).toLowerCase().includes(query);

    /** 0 숨김 · 1 유령(검색 불일치) · 2 표시. 체인 추적 중인 노드는 필터와 무관하게 보인다. */
    function state(n) {
      if (trace && trace.nodes.has(n.id)) return 2;
      if (!active.has(n.kind)) return 0;
      if (!showCand && n.confidence === "candidate") return 0;
      if (query && !matches(n)) return 1;
      return 2;
    }

    // ── 물리 · 카메라 ──────────────────────────────────────────────────────
    function tick() {
      for (const n of nodes) {
        n.vx *= 0.82; n.vy *= 0.82; n.vz *= 0.82;
        n.vx -= n.x * 0.0018; n.vy -= n.y * 0.0018; n.vz -= n.z * 0.0024; // z 는 살짝 더 조인다
      }
      // lagom: 큰 그래프는 근접 80개만 반발한다. 전역 공간 인덱스는 병목이 실측되면 넣는다.
      const repelSpan = nodes.length > 800 ? 80 : nodes.length;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < Math.min(nodes.length, i + repelSpan); j++) {
          const a = nodes[i], b = nodes[j];
          let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
          const d2 = dx * dx + dy * dy + dz * dz + 0.01;
          if (d2 > 16000) continue;
          const f = 140 / d2;
          dx *= f; dy *= f; dz *= f;
          a.vx -= dx; a.vy -= dy; a.vz -= dz; b.vx += dx; b.vy += dy; b.vz += dz;
        }
      }
      for (const e of edges) {
        const a = byId[e.source], b = byId[e.target];
        const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        const d = Math.hypot(dx, dy, dz) || 1, f = (d - 46) * 0.004;
        a.vx += dx / d * f; a.vy += dy / d * f; a.vz += dz / d * f;
        b.vx -= dx / d * f; b.vy -= dy / d * f; b.vz -= dz / d * f;
      }
      for (const n of nodes) { n.x += n.vx; n.y += n.vy; n.z += n.vz; }
    }

    function project() {
      if (!space) { for (const n of nodes) { n.px = n.x; n.py = n.y; n.pz = 0; n.k = 1; } return; }
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      for (const n of nodes) {
        const xr = n.x * cy - n.z * sy, zt = n.x * sy + n.z * cy;
        const yr = n.y * cp - zt * sp, zr = n.y * sp + zt * cp;
        const k = FOCAL / (FOCAL + zr); // 원근 — 가까울수록 크고 밝다
        n.px = xr * k; n.py = yr * k; n.pz = zr; n.k = k;
      }
    }

    // 깊이 안개 — 먼 것은 잠긴다. 3차원을 읽히게 하는 유일한 장치다(블룸 스택 금지).
    const depth = (k) => Math.max(0.16, Math.min(1, (k - 0.72) / 0.62));

    function resize() {
      const w = Math.max(1, Math.round(stage.clientWidth * dpr()));
      const h = Math.max(1, Math.round(stage.clientHeight * dpr()));
      if (canvas.width === w && canvas.height === h) return false;
      canvas.width = w; canvas.height = h;
      return true;
    }

    /** 투영된 자리의 경계 상자. 아무것도 안 보이면 `null`. */
    function bbox(list) {
      let b = null;
      for (const n of list) {
        if (!b) b = { x0: n.px, y0: n.py, x1: n.px, y1: n.py };
        else {
          b.x0 = Math.min(b.x0, n.px); b.x1 = Math.max(b.x1, n.px);
          b.y0 = Math.min(b.y0, n.py); b.y1 = Math.max(b.y1, n.py);
        }
      }
      return b;
    }

    function fit() {
      if (!nodes.length) return;
      project(); // 투영된 자리로 재야 궤도를 돌린 뒤에도 전경이 맞는다
      const b = bbox(nodes.filter(state));
      if (!b) return;
      frame(b, 60, 0.84, 0.8, 2.5);
      userCam = false;
    }

    /** 세계 좌표 상자를 화면에 맞춘다 — `fit` 과 체인 추적이 같은 계산을 쓴다. */
    function frame(b, floor, fw, fh, cap) {
      const bw = Math.max(floor, b.x1 - b.x0), bh = Math.max(floor, b.y1 - b.y0);
      const d = dpr();
      // 레인은 가로 전폭이 커서, 좁은 뷰포트에서도 전경이 들어오게 하한을 낮춘다
      scale = Math.max(laneMode ? 0.06 : 0.25,
        Math.min(cap, Math.min(canvas.width * fw / (bw * d), canvas.height * fh / (bh * d))));
      off.x = -(b.x0 + b.x1) / 2 * scale * d;
      off.y = -(b.y0 + b.y1) / 2 * scale * d;
    }

    function zoomAt(px, py, ns) {
      const d = dpr();
      ns = Math.max(laneMode ? 0.06 : 0.25, Math.min(4, ns));
      const wx = (px - canvas.width / 2 - off.x) / (scale * d);
      const wy = (py - canvas.height / 2 - off.y) / (scale * d);
      scale = ns;
      off.x = px - canvas.width / 2 - wx * scale * d;
      off.y = py - canvas.height / 2 - wy * scale * d;
      userCam = true;
      scheduleDraw();
    }

    function zoomBy(factor) { zoomAt(canvas.width / 2, canvas.height / 2, scale * factor); }

    function panBy(dx, dy) { off.x += dx * dpr(); off.y += dy * dpr(); userCam = true; }

    function orbitBy(dx, dy) { // 첫 조작이 도착 표류를 끈다 — 자동 카메라를 멈출 수단이 조작이다
      orbiting = true;
      yaw += dx * 0.006;
      pitch = Math.max(-1.25, Math.min(1.25, pitch + dy * 0.006));
    }

    function centerOn(n) {
      userCam = true;
      project();
      off.x = -n.px * scale * dpr();
      off.y = -n.py * scale * dpr();
    }

    /** 화면 좌표(CSS 픽셀 기준 이벤트) → 가장 가까운 표시 노드. 앞에 있는 것이 먼저 집힌다. */
    function hitTest(evt) {
      const r = canvas.getBoundingClientRect();
      const d = dpr();
      const px = ((evt.clientX - r.left) * d - canvas.width / 2 - off.x) / (scale * d);
      const py = ((evt.clientY - r.top) * d - canvas.height / 2 - off.y) / (scale * d);
      let best = null, bd = 9 / scale;
      for (const n of nodes) {
        if (state(n) !== 2) continue;
        const dist = Math.hypot(n.px - px, n.py - py) - radius(n) * n.k;
        if (dist < bd || (dist < 0 && best && n.k > best.k)) { bd = Math.min(bd, dist); best = n; }
      }
      return best;
    }

    // ── 레인 배치 — 결정론(물리 없음): 바리센터 2스윕 정렬 후 계층 컬럼 그리드 ──────
    let lanes = LANES.slice(), laneOf = {};
    function rebuildLanes() {
      lanes = LANES.slice();
      laneOf = {};
      lanes.forEach((l, i) => l.kinds.forEach((k) => { laneOf[k] = i; }));
      // 레인 표에 자리가 없는 종류는 사라지는 대신 마지막 칸에 모인다 — 그래야 레인이 성좌와
      // 같은 노드 집합을 그린다. 라벨은 그 종류들의 이름 그대로 쓴다(없는 이름을 짓지 않는다).
      const laneless = kindOrder.filter((k) => laneOf[k] == null && kindCount[k]);
      if (!laneless.length) return;
      lanes = lanes.concat([{ label: laneless.join(" · "), kinds: laneless }]);
      laneless.forEach((k) => { laneOf[k] = lanes.length - 1; });
    }
    rebuildLanes();

    function tierOf(n) {
      const f = (n.files && n.files[0] && n.files[0].file) || "";
      if (f.includes("/atoms/")) return 0;
      if (f.includes("/molecules/")) return 1;
      if (f.includes("/organisms/")) return 2;
      return 3;
    }

    function laneLayout() {
      const vis = nodes.filter((n) => laneOf[n.kind] != null);
      laneHeads = [];
      if (!vis.length) return;
      const H = Math.max(380, Math.min(1700, Math.ceil(Math.sqrt(vis.length)) * 38));
      const rowH = 17, rows = Math.max(6, Math.floor(H / rowH));
      const pos = {};
      let order = vis.slice().sort((a, b) => a.id.localeCompare(b.id));
      order.forEach((n, i) => { pos[n.id] = i; });
      for (let s = 0; s < 2; s++) { // 이웃 평균 순위로 레인 내 순서를 정해 교차를 줄인다
        const avg = {};
        for (const n of order) {
          let sum = 0, c = 0;
          for (const e of (OUT[n.id] || [])) if (pos[e.target] != null) { sum += pos[e.target]; c++; }
          for (const e of (IN[n.id] || [])) if (pos[e.source] != null) { sum += pos[e.source]; c++; }
          avg[n.id] = c ? sum / c : pos[n.id];
        }
        order = order.slice().sort((a, b) => avg[a.id] - avg[b.id] || a.id.localeCompare(b.id));
        order.forEach((n, i) => { pos[n.id] = i; });
      }
      const colW = 34, gapG = 18, laneGap = 96;
      let x = 0;
      for (let li = 0; li < lanes.length; li++) {
        const lane = lanes[li];
        const members = order.filter((n) => laneOf[n.kind] === li);
        if (!members.length) continue;
        const groups = lane.tiered
          ? [0, 1, 2, 3].map((t) => ({ t: t, g: members.filter((n) => tierOf(n) === t) })).filter((o) => o.g.length)
          : [{ t: -1, g: members }];
        const x0 = x, tiers = [];
        for (const o of groups) {
          const gx0 = x;
          o.g.forEach((n, i) => {
            const col = Math.floor(i / rows);
            n.tx = x + col * colW;
            n.ty = -H / 2 + (i % rows) * rowH + ((col % 2) * rowH * 0.5);
            n.tz = 0;
          });
          x += Math.ceil(o.g.length / rows) * colW;
          if (o.t >= 0) tiers.push({ name: TIER_NAMES[o.t], x0: gx0, n: o.g.length });
          x += gapG;
        }
        x -= gapG;
        laneHeads.push({ label: lane.label, x0: x0, x1: x, n: members.length, tiers: tiers });
        x += laneGap;
      }
      const w = x - laneGap;
      for (const n of vis) n.tx -= w / 2;
      for (const h of laneHeads) {
        h.x0 -= w / 2; h.x1 -= w / 2;
        for (const t of h.tiers) t.x0 -= w / 2;
      }
      laneH = H;
    }

    function startMorph() {
      for (const n of nodes) {
        n.mx = n.x; n.my = n.y; n.mz = n.z;
        if (n.tx == null) { n.tx = n.x; n.ty = n.y; n.tz = n.z; }
      }
      morph = { t0: performance.now() };
      requestAnimationFrame(morphStep);
    }

    function morphStep(now) {
      if (!morph) return;
      let k = Math.min(1, (now - morph.t0) / 220);
      k = 1 - Math.pow(1 - k, 3);
      for (const n of nodes) {
        n.x = n.mx + (n.tx - n.mx) * k;
        n.y = n.my + (n.ty - n.my) * k;
        n.z = n.mz + ((n.tz == null ? 0 : n.tz) - n.mz) * k;
      }
      if (!userCam) fit();
      draw();
      if (k < 1) requestAnimationFrame(morphStep); else morph = null;
    }

    /** 성좌(물리 3차원) ⇄ 레인(결정론 평면) 전환. */
    function setMode(lane, opt) {
      if (lane === laneMode) return;
      laneMode = lane;
      space = !lane; // 원근·성진·신호는 성좌의 것이다
      stage.classList.toggle("is-flat", lane);
      if (lane) {
        if (!starSaved) { for (const n of nodes) { n.sx = n.x; n.sy = n.y; n.sz = n.z; } starSaved = true; }
        hot = 0;
        laneLayout();
      } else {
        if (!starSaved) { for (const n of nodes) { n.sx = n.x; n.sy = n.y; n.sz = n.z; } starSaved = true; }
        if (!settled) { // 성좌를 아직 정착시킨 적이 없다 — 레인 좌표를 잠시 치우고 정착시킨다
          for (const n of nodes) { n.lx = n.x; n.ly = n.y; n.lz = n.z; n.x = n.sx; n.y = n.sy; n.z = n.sz; }
          settle();
          for (const n of nodes) { n.sx = n.x; n.sy = n.y; n.sz = n.z; n.x = n.lx; n.y = n.ly; n.z = n.lz; }
        }
        for (const n of nodes) { n.tx = n.sx; n.ty = n.sy; n.tz = n.sz; }
      }
      if (selected && !state(selected)) select(null);
      if (hooks.onMode) hooks.onMode(lane);
      userCam = false;
      if ((opt && opt.snap) || reduced()) {
        for (const n of nodes) if (n.tx != null) { n.x = n.tx; n.y = n.ty; n.z = n.tz == null ? 0 : n.tz; }
        fit(); draw();
      } else startMorph();
      if (space) startLoop();
    }

    // ── 선택 · 체인 추적 ───────────────────────────────────────────────────
    function select(n) {
      clearTrace();
      selected = n || null;
      neighbors = new Set();
      bridges = new Set();
      if (selected) {
        for (const e of edges) {
          if (e.source === selected.id) neighbors.add(e.target);
          if (e.target === selected.id) {
            neighbors.add(e.source);
            if (byId[e.source].kind === "file") bridges.add(e.source);
          }
        }
        // 실제 연계 — 같은 파일 증거를 공유하는 개념(파일 경유 2-hop)까지 이웃으로 편입
        if (bridges.size) {
          for (const e of edges) if (bridges.has(e.source) && e.target !== selected.id) neighbors.add(e.target);
        }
      }
      if (hooks.onSelect) hooks.onSelect(selected);
      draw();
    }

    function runTrace(n) {
      const eset = new Set(), nset = new Set([n.id]), up = [], down = [];
      for (const dir of [{ adj: OUT, rev: false, acc: down }, { adj: IN, rev: true, acc: up }]) {
        let frontier = [n.id];
        for (let d = 1; d <= 4 && frontier.length; d++) {
          const next = [];
          for (const id of frontier) {
            for (const e of (dir.adj[id] || [])) {
              if (eset.has(e)) continue;
              eset.add(e);
              const o = dir.rev ? e.source : e.target;
              if (!nset.has(o)) { nset.add(o); next.push(o); dir.acc.push({ id: o, d: d, up: dir.rev }); }
            }
          }
          frontier = next;
        }
      }
      trace = { eset: eset, nodes: nset, up: up, down: down, cam: { x: off.x, y: off.y, s: scale, u: userCam } };
      if (nset.size >= 2) { // 체인 범위로 카메라 — 추적한 이야기가 화면에 들어온다
        project();
        const b = bbox([...nset].map((id) => byId[id]).filter(Boolean));
        if (b) { frame(b, 120, 0.78, 0.72, 2.2); userCam = true; }
      }
      // 유방향 대시 흐름은 350엣지 이하·모션 허용에서만 — 그 밖에서는 정적 화살촉이 방향을 말한다
      if (!reduced() && eset.size <= 350 && !traceRaf) traceRaf = requestAnimationFrame(traceLoop);
    }

    function traceLoop(ts) {
      if (!trace) { traceRaf = 0; return; }
      traceT = (ts / 34) % 600;
      draw();
      traceRaf = requestAnimationFrame(traceLoop);
    }

    function clearTrace() {
      if (trace && trace.cam) { off.x = trace.cam.x; off.y = trace.cam.y; scale = trace.cam.s; userCam = trace.cam.u; }
      trace = null;
      traceT = 0;
    }

    // ── 그리기 ─────────────────────────────────────────────────────────────
    function strokeEdges(list, style, alpha, width) {
      if (!list.length) return;
      ctx.strokeStyle = style;
      ctx.lineWidth = width;
      const bands = space ? DEPTH_BANDS : [[-9, 9, 1]];
      for (const band of bands) {
        ctx.globalAlpha = alpha * band[2];
        for (const k of EDGE_KINDS) {
          // 저줌 LOD — 대시 패턴은 판독 불가 구간(0.5x 미만)에서 실선으로 접는다
          ctx.setLineDash(scale < 0.5 ? [] : EDGE_DASH[k].map((v) => v / scale));
          ctx.beginPath();
          for (const e of list) {
            if (e.kind !== k) continue;
            const a = byId[e.source], b = byId[e.target];
            if (space) { const mk = (a.k + b.k) / 2; if (mk < band[0] || mk >= band[1]) continue; }
            if ((a.px < cvx0 && b.px < cvx0) || (a.px > cvx1 && b.px > cvx1)
              || (a.py < cvy0 && b.py < cvy0) || (a.py > cvy1 && b.py > cvy1)) continue;
            ctx.moveTo(a.px, a.py); ctx.lineTo(b.px, b.py);
          }
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
    }

    function arrowHeads(list, style) {
      ctx.fillStyle = style;
      for (const e of list) {
        const a = byId[e.source], b = byId[e.target];
        const dx = b.px - a.px, dy = b.py - a.py, d = Math.hypot(dx, dy) || 1;
        const ux = dx / d, uy = dy / d;
        const rr = radius(b) * b.k + 2 / scale, s = 7 / scale;
        const tx = b.px - ux * rr, ty = b.py - uy * rr;
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(tx - ux * s - uy * s * 0.5, ty - uy * s + ux * s * 0.5);
        ctx.lineTo(tx - ux * s + uy * s * 0.5, ty - uy * s - ux * s * 0.5);
        ctx.closePath();
        ctx.fill();
      }
    }

    function drawStars(w, h) {
      const mod = (v, m) => ((v % m) + m) % m;
      const d = dpr();
      for (const st of STARS) { // 앞 층일수록 크고 밝고 더 많이 흐른다 — 시차가 깊이를 말한다
        const px = mod(st.ux + yaw * st.layer * 0.055 + off.x / (w * 14), 1) * w;
        const py = mod(st.uy + pitch * st.layer * 0.045 + off.y / (h * 14), 1) * h;
        ctx.globalAlpha = st.a * (0.42 + st.layer * 0.19);
        ctx.fillStyle = st.r > 0.93 ? PAL.goldLit : PAL.ink; // 드물게 금빛 하나 — 단색 점묘를 깬다
        ctx.beginPath();
        ctx.arc(px, py, (0.45 + st.r * 0.95) * (0.6 + st.layer * 0.3) * d, 0, 7);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    /** 소마 글로우 — 종류색 스프라이트 한 장을 캐시해 재사용한다(프레임당 그라디언트 생성 금지). */
    function glowSprite(col) {
      if (glowCache[col]) return glowCache[col];
      const S = 64;
      const c = document.createElement("canvas");
      c.width = c.height = S;
      const g = c.getContext("2d");
      const grd = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
      grd.addColorStop(0, mix(col, 50));
      grd.addColorStop(0.4, mix(col, 14));
      grd.addColorStop(1, "transparent");
      g.fillStyle = grd;
      g.fillRect(0, 0, S, S);
      glowCache[col] = c;
      return c;
    }

    function draw() {
      const w = canvas.width, h = canvas.height;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, w, h);
      if (!nodes.length) return; // 빈 그래프는 캔버스가 아니라 화면이 말한다
      project();
      if (space) drawStars(w, h);
      let visN = 0;
      for (const n of nodes) if (state(n)) visN++;
      if (hooks.onVisible) hooks.onVisible(visN, nodes.length);
      if (!visN) return;
      const d = dpr();
      ctx.translate(w / 2 + off.x, h / 2 + off.y);
      ctx.scale(scale * d, scale * d);
      ctx.textBaseline = "middle";
      const focus = selected;
      // 월드 좌표 뷰포트 — 노드·라벨 패스는 화면 밖(여유 60)을 건너뛴다
      const vx0 = (-w / 2 - off.x) / (scale * d) - 60, vy0 = (-h / 2 - off.y) / (scale * d) - 60;
      const vx1 = vx0 + w / (scale * d) + 120, vy1 = vy0 + h / (scale * d) + 120;
      const inView = (n) => n.px > vx0 && n.px < vx1 && n.py > vy0 && n.py < vy1;
      cvx0 = vx0; cvy0 = vy0; cvx1 = vx1; cvy1 = vy1; // 엣지 컬링 경계(strokeEdges 공유)
      const lit = [], lit2 = [], base = [], ghost = [], via = [], viaN = {}, path = [];
      for (const e of edges) {
        if (!activeEdge.has(e.kind) && !(trace && trace.eset.has(e))) continue;
        const a = byId[e.source], b = byId[e.target];
        const sa = state(a), sb = state(b);
        if (!sa || !sb) {
          // 파일이 필터로 꺼져도 파일 경유 연계(실제 구성)는 접점 스터브로 남긴다
          if (!sa && a.kind === "file" && sb === 2) { via.push(e); viaN[a.id] = (viaN[a.id] || 0) + 1; }
          continue;
        }
        if (trace) { if (trace.eset.has(e)) path.push(e); else ghost.push(e); }
        else if (focus) {
          if (e.source === focus.id || e.target === focus.id) lit.push(e);
          else if (bridges.has(e.source)) lit2.push(e); // 선택 개념의 파일 경유 2-hop 구간
          else ghost.push(e);
        } else if (query && sa < 2 && sb < 2) ghost.push(e);
        else if (previewKind && a.kind !== previewKind && b.kind !== previewKind) ghost.push(e);
        else base.push(e);
      }
      strokeEdges(ghost, PAL.muted, 0.07, 0.8 / scale);
      // 3차원은 깊이 밴드가 알파를 나눠 먹는다 — 바닥을 올려 둔다
      strokeEdges(base, PAL.muted, space ? 0.44 : 0.3, 0.9 / scale);
      strokeEdges(lit2, PAL.goldLit, 0.4, 1.1 / scale);
      strokeEdges(lit, PAL.goldLit, 0.75, 1.5 / scale);
      if (trace && path.length) { // 체인 경로 — 유방향 대시가 하류로 흐른다(모션 불가 시 정적)
        ctx.globalAlpha = 0.85;
        ctx.strokeStyle = PAL.goldLit;
        ctx.lineWidth = 1.6 / scale;
        ctx.setLineDash([7 / scale, 5 / scale]);
        ctx.lineDashOffset = -traceT / scale;
        ctx.beginPath();
        for (const e of path) {
          const a = byId[e.source], b = byId[e.target];
          ctx.moveTo(a.px, a.py); ctx.lineTo(b.px, b.py);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.lineDashOffset = 0;
        ctx.globalAlpha = 0.9;
        arrowHeads(path, PAL.goldLit);
        ctx.globalAlpha = 1;
      }
      drawViaStubs(via, viaN, focus);
      if (focus && lit.length) { // 방향(파일 → 개념)은 선택 시에만 화살촉으로 노출
        ctx.globalAlpha = 0.8;
        arrowHeads(lit, PAL.goldLit);
        ctx.globalAlpha = 1;
      }
      drawPulses(focus);
      drawNodes(inView, focus);
      drawLabels(inView, focus);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (laneMode && laneHeads.length) drawLaneHeads(w, h);
    }

    function drawViaStubs(via, viaN, focus) {
      // 은닉 파일 접점 — 연계 2개 이상만 의미가 있다(외줄 스터브 제외)
      const viaBase = [], viaLit = [];
      for (const e of via) {
        if (viaN[e.source] < 2) continue;
        if (!focus) viaBase.push(e);
        else if (bridges.has(e.source)) viaLit.push(e);
      }
      if (!viaBase.length && !viaLit.length) return;
      ctx.setLineDash([2 / scale, 3.5 / scale]);
      for (const spec of [[viaBase, PAL.muted, 0.24, 0.8], [viaLit, PAL.goldLit, 0.55, 1.2]]) {
        if (!spec[0].length) continue;
        ctx.strokeStyle = spec[1];
        ctx.globalAlpha = spec[2];
        ctx.lineWidth = spec[3] / scale;
        ctx.beginPath();
        for (const e of spec[0]) {
          const a = byId[e.source], b = byId[e.target];
          ctx.moveTo(a.px, a.py); ctx.lineTo(b.px, b.py);
        }
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.lineWidth = 1 / scale;
      for (const id in viaN) {
        if (viaN[id] < 2) continue;
        if (focus && !bridges.has(id)) continue;
        const f = byId[id];
        ctx.strokeStyle = focus ? PAL.goldLit : PAL.muted;
        ctx.globalAlpha = focus ? 0.6 : 0.5;
        ctx.beginPath();
        ctx.arc(f.px, f.py, 2.2 * f.k, 0, 7);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    function drawPulses(focus) {
      // 시냅스 신호 — 정지 상태에서도 망이 살아 있다는 유일한 신호다
      if (!(space && !reduced() && pulseEdges.length && !trace && !focus)) return;
      ctx.fillStyle = PAL.goldLit;
      for (const p of pulseEdges) {
        const a = byId[p.e.source], b = byId[p.e.target];
        if (!state(a) || !state(b)) continue;
        const u = (pulseT + p.phase) % 1;
        const x = a.px + (b.px - a.px) * u, y = a.py + (b.py - a.py) * u;
        if (x < cvx0 || x > cvx1 || y < cvy0 || y > cvy1) continue;
        const kk = a.k + (b.k - a.k) * u;
        ctx.globalAlpha = depth(kk) * 0.85 * Math.sin(u * Math.PI); // 양 끝에서 사그라든다
        ctx.beginPath();
        ctx.arc(x, y, 1.7 * kk / scale * Math.max(1, scale), 0, 7);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    const dimOf = (n, s, focus) => (s === 1)
      || (trace ? !trace.nodes.has(n.id) : (focus && n !== selected && !neighbors.has(n.id)))
      || (previewKind && n.kind !== previewKind);

    function drawNodes(inView, focus) {
      // 페인터 순서 — 먼 것부터. 3차원에서 앞뒤가 뒤집히면 깊이가 통째로 무너진다.
      const list = [];
      for (const n of nodes) if (state(n) && inView(n)) list.push(n);
      if (space) list.sort((a, b) => b.pz - a.pz);
      if (space) { // 소마 글로우 — 허브만, 가산 합성 1패스(블룸·플레어 스택 없음)
        ctx.globalCompositeOperation = "lighter";
        for (const n of list) {
          const r = radius(n) * n.k;
          if (r < 6.4 || n.kind === "file") continue;
          if (dimOf(n, state(n), focus)) continue;
          const g = glowSprite(colorOf(n.kind)), gr = r * 3.4;
          ctx.globalAlpha = depth(n.k) * 0.9;
          ctx.drawImage(g, n.px - gr, n.py - gr, gr * 2, gr * 2);
        }
        ctx.globalCompositeOperation = "source-over";
        ctx.globalAlpha = 1;
      }
      for (const n of list) {
        const s = state(n), r = radius(n) * n.k;
        ctx.globalAlpha = dimOf(n, s, focus) ? 0.16 : (space ? depth(n.k) : 1);
        const col = colorOf(n.kind);
        ctx.beginPath();
        ctx.arc(n.px, n.py, r, 0, 7);
        if (n.confidence === "candidate") {
          // 빈 원이 저줌에서 채운 원으로 뭉개지지 않게 링 폭을 화면 반지름에 비례 클램프
          ctx.strokeStyle = col;
          ctx.lineWidth = Math.min(1.4, Math.max(0.7, r * scale * 0.42)) / scale;
          ctx.stroke();
        } else {
          ctx.fillStyle = col;
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      }
      if (hover && hover !== selected) {
        ctx.strokeStyle = PAL.ink;
        ctx.globalAlpha = 0.6;
        ctx.lineWidth = 1.2 / scale;
        ctx.beginPath();
        ctx.arc(hover.px, hover.py, radius(hover) * hover.k + 3 / scale, 0, 7);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (selected) {
        ctx.strokeStyle = PAL.goldLit;
        ctx.lineWidth = 1.6 / scale;
        ctx.beginPath();
        ctx.arc(selected.px, selected.py, radius(selected) * selected.k + 3.5 / scale, 0, 7);
        ctx.stroke();
      }
    }

    function drawLabels(inView, focus) {
      // 라벨 정책 — 기본 허브 14개, 검색 일치 30개, 줌인 시 개념 전체(1.4x)·파일까지(2.4x).
      const allConcept = scale >= 1.4, allFiles = scale >= 2.4;
      ctx.font = (11 / scale).toFixed(2) + "px " + FONT;
      ctx.lineWidth = 3 / scale;
      ctx.strokeStyle = PAL.canvas; // 후광 — 선 위에 얹힌 글자를 읽히게 한다
      let qLabels = 0;
      const cands = [];
      for (const n of nodes) {
        if (state(n) !== 2 || !inView(n)) continue;
        if (trace) { if (!trace.nodes.has(n.id) && n !== hover) continue; }
        else if (focus && n !== selected && !neighbors.has(n.id)) continue;
        const concept = n.kind !== "file";
        let show = n === selected || n === hover;
        if (!show && trace && trace.nodes.has(n.id)) show = true;
        if (!show && focus && concept && neighbors.has(n.id)) show = true;
        if (!show && concept && (allConcept || topLabel.has(n.id))) show = true;
        if (!show && !concept && allFiles) show = true;
        if (!show && query && concept && qLabels < 30) { show = true; qLabels++; }
        if (!show) continue;
        const pri = n === selected ? 0 : n === hover ? 1 : (focus && neighbors.has(n.id)) ? 2 : 3;
        cands.push({ n: n, pri: pri, deg: degree[n.id] || 0, concept: concept });
      }
      // 가까운 것이 라벨 자리를 우선한다 — 뒤에 있는 이름이 앞을 가리면 깊이가 거짓말이 된다
      cands.sort((a, b) => a.pri - b.pri || (space ? b.n.k - a.n.k : 0) || b.deg - a.deg);
      const boxes = [], lh = 13 / scale;
      for (const c of cands) {
        const n = c.n;
        const t = n.name.length > 26 ? n.name.slice(0, 25) + "…" : n.name;
        const lx = n.px + radius(n) * n.k + 5 / scale;
        const x0 = lx, x1 = lx + ctx.measureText(t).width, y0 = n.py - lh / 2, y1 = n.py + lh / 2;
        let clash = false;
        for (const b of boxes) { if (x0 < b.x1 && x1 > b.x0 && y0 < b.y1 && y1 > b.y0) { clash = true; break; } }
        if (clash && c.pri > 1) continue;
        boxes.push({ x0: x0, x1: x1, y0: y0, y1: y1 });
        ctx.globalAlpha = space ? Math.max(0.45, depth(n.k)) : 1;
        ctx.strokeText(t, lx, n.py);
        ctx.fillStyle = n === selected ? PAL.goldLit : (c.concept ? PAL.ink : PAL.muted);
        ctx.fillText(t, lx, n.py);
        ctx.globalAlpha = 1;
      }
    }

    function drawLaneHeads(w, h) {
      // 레인 헤더는 화면 공간에 그린다 — 줌과 무관하게 읽혀야 한다
      const d = dpr();
      const SX = (v) => v * scale * d + w / 2 + off.x;
      const SY = (v) => v * scale * d + h / 2 + off.y;
      const hy = Math.max(56 * d, SY(-laneH / 2) - 24 * d);
      ctx.textBaseline = "alphabetic";
      const zbLeft = w - 70 * d, zbBottom = 176 * d; // 줌바 점유 영역 회피
      for (let i = 0; i < laneHeads.length; i++) {
        const hd = laneHeads[i];
        const x0 = SX(hd.x0), x1 = SX(hd.x1);
        if (x1 < -40 || x0 > w + 40) continue;
        let slotEnd = (i + 1 < laneHeads.length ? SX(laneHeads[i + 1].x0) : w) - 10 * d;
        if (hy < zbBottom) slotEnd = Math.min(slotEnd, zbLeft - 6 * d);
        const avail = slotEnd - x0;
        if (avail > 8 * d) {
          // 슬롯 분할 — 좁으면 말줄임, 더 좁으면 카운트만. 무명 레인은 만들지 않는다.
          ctx.font = "600 " + (10.5 * d) + "px " + FONT;
          const cnt = " " + hd.n, cw = ctx.measureText(cnt).width;
          let lbl = hd.label.toUpperCase();
          while (lbl.length > 2 && ctx.measureText(lbl + "…").width + cw > avail) lbl = lbl.slice(0, -1);
          if (lbl !== hd.label.toUpperCase()) lbl = lbl + "…";
          if (ctx.measureText(lbl).width + cw > avail) lbl = "";
          const lw = lbl ? ctx.measureText(lbl).width : 0;
          if (lbl) { ctx.fillStyle = PAL.goldLit; ctx.fillText(lbl, x0, hy); }
          ctx.font = (10.5 * d) + "px " + FONT;
          ctx.fillStyle = PAL.muted;
          ctx.fillText(String(hd.n), x0 + lw + (lbl ? 7 * d : 0), hy);
        }
        ctx.strokeStyle = PAL.line;
        ctx.lineWidth = 1 * d;
        ctx.beginPath();
        ctx.moveTo(x0, hy + 7 * d);
        ctx.lineTo(Math.max(x1, x0 + 30 * d), hy + 7 * d);
        ctx.stroke();
        if (hd.tiers.length > 1 && scale > 0.55) { // 아토믹 서브밴드 — 확대 시에만
          ctx.font = (9.5 * d) + "px " + FONT;
          ctx.fillStyle = PAL.faint;
          for (const t of hd.tiers) ctx.fillText(t.name, SX(t.x0), hy + 20 * d);
        }
        if (i < laneHeads.length - 1) {
          const mx = SX((hd.x1 + laneHeads[i + 1].x0) / 2);
          if (mx > -10 && mx < w + 10) {
            ctx.strokeStyle = PAL.line;
            ctx.globalAlpha = 0.35;
            ctx.beginPath();
            ctx.moveTo(mx, Math.max(0, hy - 12 * d));
            ctx.lineTo(mx, Math.min(h, SY(laneH / 2) + 14 * d));
            ctx.stroke();
            ctx.globalAlpha = 1;
          }
        }
      }
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
    }

    // ── 프레임 루프 — 성좌가 살아 있는 동안만 돈다 ─────────────────────────
    const ambient = () => space && !reduced() && !document.hidden;

    function loop(ts) {
      raf = 0;
      const now = ts || performance.now();
      const dt = lastTs ? Math.min(50, now - lastTs) : 16;
      lastTs = now;
      let live = false, busy = false;
      if (!laneMode && hot-- > 0) {
        tick();
        if (nodes.length > 400) tick(); // 큰 그래프는 프레임당 2틱 — 정착 벽시계를 절반으로
        if (!userCam) fit();
        live = busy = true;
      } else settled = settled || !laneMode;
      if (ambient()) {
        pulseT = (pulseT + dt / 5200) % 1; // 신호 한 바퀴 ≈ 5.2초
        if (!orbiting && drift < DRIFT_TURNS) { yaw += 0.00042 * (dt / 16); drift++; busy = true; }
        live = true;
      }
      // 유휴 신호만 도는 구간은 30fps 로 접는다 — 개발 도구를 열어 둔 채 팬을 돌리지 않는다
      if (busy || now - lastDraw >= 32) { lastDraw = now; draw(); }
      if (live) startLoop();
    }

    function startLoop() { if (!raf && nodes.length) raf = requestAnimationFrame(loop); }
    function stopLoop() { if (raf) cancelAnimationFrame(raf); raf = 0; }

    function scheduleDraw() { // 휠·팬·핀치·호버 폭주를 프레임당 1회로 코얼레싱
      if (drawQueued) return;
      drawQueued = true;
      requestAnimationFrame(() => { drawQueued = false; draw(); });
    }

    refreshPalette();

    // 화면(map.js)이 잡는 손잡이. 안쪽 좌표·물리·팔레트는 전부 이 닫힘 안에 남는다 —
    // 밖에서 필요한 것은 "무엇을 보여 줄까"(필터·선택·모드)와 "그려라" 둘뿐이다.
    return {
      load: load, refreshPalette: refreshPalette, colorOf: colorOf,
      state: state, radius: radius, select: select,
      setQuery(q) { query = q; }, setShowCand(v) { showCand = v; }, setPreviewKind(k) { previewKind = k; },
      ensureKind(k) { active.add(k); },
      soloKind(k) { // 단독 보기 — 이미 단독이면 전체 복귀
        const all = kindOrder.filter((x) => kindCount[x]);
        active = (active.size === 1 && active.has(k)) ? new Set(all) : new Set([k]);
      },
      resetFilters() {
        active = new Set(kindOrder.filter((k) => kindCount[k]));
        activeEdge = new Set(EDGE_KINDS);
        showCand = true; query = "";
      },
      setMode: setMode, resize: resize, fit: fit, draw: draw, scheduleDraw: scheduleDraw,
      zoomAt: zoomAt, zoomBy: zoomBy, panBy: panBy, orbitBy: orbitBy, centerOn: centerOn,
      hitTest: hitTest, startLoop: startLoop, stopLoop: stopLoop,
      runTrace: runTrace, clearTrace: clearTrace,
      get model() { return model; },
      get filters() { return { active: active, activeEdge: activeEdge, showCand: showCand, query: query }; },
      get selected() { return selected; },
      get hover() { return hover; },
      set hover(n) { hover = n; },
      get trace() { return trace; },
      get kindOrder() { return kindOrder; },
      get laneMode() { return laneMode; },
      get space() { return space; },
      get scale() { return scale; },
      set userCam(v) { userCam = v; },
    };
  }

  global.AsgardMapDraw = {
    create: create,
    EDGE_KINDS: EDGE_KINDS,
    EDGE_DASH: EDGE_DASH,
    reduced: reduced,
  };
})(window);
