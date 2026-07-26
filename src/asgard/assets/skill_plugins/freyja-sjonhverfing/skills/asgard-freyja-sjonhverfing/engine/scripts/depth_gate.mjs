#!/usr/bin/env node
// Sjónhverfing — 평면 위 깊이(의사 3D)의 결정론 게이트.
//
// 소스만 보고 확실히 판정할 수 있는 것만 판정한다. 렌더된 화면이 있어야 아는 것은
// `unjudged` 로 내보내고 절대 pass 로 세지 않는다. 의존성 없음(node 내장 모듈만, node 18+).
//
//   node depth_gate.mjs <file|dir> [...] [--json] [--report] [--severity warn|fail]
//
// 판정이 fail 이면 종료 코드 1. --severity warn 을 주면 warn 도 1 로 올린다.

import fs from "node:fs";
import path from "node:path";

const SOURCE = new Set([
  ".css", ".html", ".htm", ".js", ".mjs", ".cjs", ".jsx",
  ".ts", ".tsx", ".vue", ".svelte", ".astro",
]);
const MARKUP = new Set([".html", ".htm", ".vue", ".svelte", ".astro"]);
const SKIP = new Set([
  "node_modules", ".git", "dist", "build", ".next", ".nuxt",
  ".output", "coverage", ".asgard", ".svelte-kit", "vendor",
]);
const MAX_HITS = 6;

/* ───────────────────────────────  읽기  ─────────────────────────────── */

function collect(target, out, seen = new Set()) {
  let real;
  try {
    real = fs.realpathSync(target);
  } catch {
    return out;
  }
  if (seen.has(real)) return out;
  seen.add(real);
  const info = fs.statSync(real);
  if (info.isFile()) {
    if (SOURCE.has(path.extname(real).toLowerCase())) out.push(real);
    return out;
  }
  if (!info.isDirectory()) return out;
  for (const entry of fs.readdirSync(real).sort()) {
    if (SKIP.has(entry) || entry.startsWith(".")) continue;
    collect(path.join(real, entry), out, seen);
  }
  return out;
}

// 줄 번호는 인덱스로 매번 세면 O(n²) 이라 시작 오프셋 표를 한 번만 만든다.
function lineIndex(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
  return starts;
}

function lineOf(starts, index) {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid] <= index) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1;
}

// 주석은 지우되 줄 수는 보존한다 — 증거의 줄 번호가 어긋나면 안 된다.
function blank(chunk) {
  return chunk.replace(/[^\n]/g, " ");
}

function stripCssComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, blank);
}

function stripJsComments(text) {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === "/" && next === "*") {
      const end = text.indexOf("*/", i + 2);
      const stop = end === -1 ? text.length : end + 2;
      out += blank(text.slice(i, stop));
      i = stop;
    } else if (ch === "/" && next === "/") {
      let stop = text.indexOf("\n", i);
      if (stop === -1) stop = text.length;
      out += blank(text.slice(i, stop));
      i = stop;
    } else if (ch === '"' || ch === "'" || ch === "`") {
      let j = i + 1;
      while (j < text.length && text[j] !== ch) {
        if (text[j] === "\\") j++;
        j++;
      }
      out += text.slice(i, Math.min(j + 1, text.length));
      i = j + 1;
    } else {
      out += ch;
      i++;
    }
  }
  return out;
}

function blocks(text, tag) {
  const found = [];
  const lower = text.toLowerCase();
  const open = new RegExp(`<${tag}\\b[^>]*>`, "gi");
  let match;
  while ((match = open.exec(text))) {
    const start = match.index + match[0].length;
    const close = lower.indexOf(`</${tag}`, start);
    if (close === -1) break;
    found.push({ start, body: text.slice(start, close) });
    open.lastIndex = close;
  }
  return found;
}

function inlineStyles(text) {
  const found = [];
  const re = /\sstyle\s*=\s*(["'])([\s\S]*?)\1/gi;
  let match;
  while ((match = re.exec(text))) found.push({ start: match.index, body: match[2] });
  return found;
}

/* ───────────────────────────────  CSS  ─────────────────────────────── */

// 선언을 프레임 단위로 모은다. 괄호·따옴표 안의 `;` `{` `}` 는 구분자가 아니다
// (url(data:...;base64,...) 가 규칙을 쪼개면 판정이 통째로 어긋난다).
function parseCss(src, file, starts, offset) {
  const text = stripCssComments(src);
  const rules = [];
  const stack = [];
  let buf = "";
  let bufStart = 0;
  let paren = 0;
  let quote = "";

  const pushDecl = (frame, chunk, at) => {
    const colon = chunk.indexOf(":");
    if (colon < 1) return;
    const prop = chunk.slice(0, colon).trim().toLowerCase();
    const value = chunk.slice(colon + 1).trim();
    if (!prop || prop.startsWith("@") || !value) return;
    frame.decls.push({ prop, value, line: lineOf(starts, at + offset) });
  };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      buf += ch;
      if (ch === "\\") {
        buf += text[++i] ?? "";
      } else if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      buf += ch;
      continue;
    }
    if (ch === "(") paren++;
    if (ch === ")") paren = Math.max(0, paren - 1);
    if (paren > 0) {
      buf += ch;
      continue;
    }
    if (ch === "{") {
      stack.push({ prelude: buf.trim().replace(/\s+/g, " "), line: lineOf(starts, bufStart + offset), decls: [] });
      buf = "";
      bufStart = i + 1;
    } else if (ch === "}") {
      const frame = stack.pop();
      if (frame) {
        pushDecl(frame, buf, bufStart);
        rules.push({
          file,
          selector: frame.prelude,
          line: frame.line,
          decls: frame.decls,
          at: stack.map((f) => f.prelude).filter((p) => p.startsWith("@")),
        });
      }
      buf = "";
      bufStart = i + 1;
    } else if (ch === ";") {
      const frame = stack[stack.length - 1];
      if (frame) pushDecl(frame, buf, bufStart);
      buf = "";
      bufStart = i + 1;
    } else {
      buf += ch;
    }
  }
  return rules;
}

function loadBundle(targets) {
  const files = [];
  for (const target of targets) collect(target, files);
  const bundle = { files: [...new Set(files)], rules: [], docs: [] };
  for (const file of bundle.files) {
    const raw = fs.readFileSync(file, "utf8");
    const ext = path.extname(file).toLowerCase();
    const starts = lineIndex(raw);
    if (ext === ".css") {
      bundle.rules.push(...parseCss(raw, file, starts, 0));
      bundle.docs.push({ file, starts, text: stripCssComments(raw) });
      continue;
    }
    if (MARKUP.has(ext)) {
      for (const block of blocks(raw, "style")) {
        bundle.rules.push(...parseCss(block.body, file, starts, block.start));
      }
      for (const attr of inlineStyles(raw)) {
        const frame = { decls: [] };
        for (const chunk of attr.body.split(";")) {
          const colon = chunk.indexOf(":");
          if (colon < 1) continue;
          frame.decls.push({
            prop: chunk.slice(0, colon).trim().toLowerCase(),
            value: chunk.slice(colon + 1).trim(),
            line: lineOf(starts, attr.start),
          });
        }
        if (frame.decls.length) {
          bundle.rules.push({
            file,
            selector: "[style]",
            line: lineOf(starts, attr.start),
            decls: frame.decls,
            at: [],
          });
        }
      }
      // 마크업은 주석 종류가 섞인다. JS 주석 규칙은 script 본문에만 적용한다 —
      // 전체에 적용하면 스타일 블록의 `url(https://…)` 가 줄 끝까지 지워진다.
      // stripJsComments 는 길이를 보존하므로 잘라 붙여도 오프셋이 어긋나지 않는다.
      let text = raw.replace(/<!--[\s\S]*?-->/g, blank);
      for (const block of blocks(text, "script")) {
        text = text.slice(0, block.start) + stripJsComments(block.body) + text.slice(block.start + block.body.length);
      }
      bundle.docs.push({ file, starts, text: stripCssComments(text) });
      continue;
    }
    bundle.docs.push({ file, starts, text: stripJsComments(raw) });
  }
  return bundle;
}

/* ─────────────────────────────  토큰 스캔  ───────────────────────────── */

function scan(bundle, re, keep) {
  const hits = [];
  for (const doc of bundle.docs) {
    const rx = new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
    let match;
    while ((match = rx.exec(doc.text))) {
      if (keep && !keep(match)) continue;
      const line = lineOf(doc.starts, match.index);
      hits.push({
        file: doc.file,
        line,
        evidence: doc.text.slice(doc.starts[line - 1], doc.starts[line] ?? doc.text.length).trim().slice(0, 120),
      });
    }
  }
  return hits;
}

const has = (bundle, re) => scan(bundle, re).length > 0;

const nonZero = (raw) => {
  if (raw === undefined || raw === null || raw === "") return true; // 값이 식이면 0 임을 증명할 수 없다
  const num = Number.parseFloat(raw);
  return Number.isNaN(num) ? true : num !== 0;
};

// 깊이를 실제로 쓰는 자리. `translateZ(0)` 같은 레이어 승격 관용구는 깊이가 아니고,
// `--card-rotateX` 처럼 이름에 든 것도 선언이 아니다(앞의 `-`·단어문자를 배제한다).
function depthHits(bundle) {
  const hits = [];
  hits.push(...scan(bundle, /(?<![-\w])(?:rotateX|rotateY|translateZ)\s*[(:]\s*(-?[\d.]+)?/, (m) => nonZero(m[1])));
  hits.push(...scan(bundle, /\btranslate3d\s*\(([^)]*)\)/, (m) => nonZero((m[1].split(",")[2] || "").trim())));
  hits.push(...scan(bundle, /\brotate3d\s*\(([^)]*)\)/, (m) => {
    const parts = m[1].split(",").map((p) => p.trim());
    return parts.length >= 4 && (nonZero(parts[0]) || nonZero(parts[1])) && nonZero(parts[3]);
  }));
  hits.push(...scan(bundle, /\bmatrix3d\s*\(/));
  return dedupe(hits);
}

function dedupe(hits) {
  const seen = new Set();
  const out = [];
  for (const hit of hits) {
    const key = `${hit.file}:${hit.line}:${hit.evidence}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(hit);
  }
  return out.sort((a, b) => (a.file === b.file ? a.line - b.line : a.file < b.file ? -1 : 1));
}

// 토큰(사용자 정의 속성)을 한 단계 풀어 준다. 실무 코드는 원근 거리를 거의 항상 변수로 둔다.
function customProperties(bundle) {
  const vars = new Map();
  for (const rule of bundle.rules) {
    for (const decl of rule.decls) {
      if (decl.prop.startsWith("--")) vars.set(decl.prop, decl.value);
    }
  }
  return vars;
}

function resolve(value, vars, depth = 0) {
  const ref = /^var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)$/.exec(String(value).trim());
  if (!ref || depth > 4) return value;
  const target = vars.has(ref[1]) ? vars.get(ref[1]) : ref[2];
  return target === undefined ? value : resolve(target, vars, depth + 1);
}

// 원근이 어디엔가 선언돼 있는가. 값이 0/none 이면 3D 는 평면으로 투영된다 — 없는 것과 같다.
// `--depth-perspective: 900px` 같은 변수 *이름* 은 선언이 아니다 — 앞의 `-` 를 배제한다.
function perspectiveHits(bundle) {
  const vars = customProperties(bundle);
  const found = [];
  for (const rule of bundle.rules) {
    for (const decl of rule.decls) {
      if (decl.prop !== "perspective") continue;
      const value = String(resolve(decl.value, vars)).trim();
      if (/^(?:none|0)(?:\D|$)/.test(value)) continue;
      const px = Number.parseFloat(value);
      if (!Number.isNaN(px) && px <= 0) continue;
      found.push({
        file: rule.file,
        line: decl.line,
        evidence: `${rule.selector} { perspective: ${decl.value} }`,
        px: Number.isNaN(px) ? null : px,
        unit: /^[\d.]+px\b/.test(value) ? "px" : null,
      });
    }
  }
  const inline = scan(bundle, /(?<![-\w])perspective\s*[(:]\s*(-?[\d.]+)(px)?/, (m) => Number.parseFloat(m[1]) > 0);
  for (const hit of inline) {
    const parsed = /(?<![-\w])perspective\s*[(:]\s*(-?[\d.]+)(px)?/.exec(hit.evidence);
    found.push({ ...hit, px: parsed ? Number.parseFloat(parsed[1]) : null, unit: parsed && parsed[2] ? "px" : null });
  }
  // 같은 줄을 규칙 경로와 토큰 경로가 함께 잡는다 — 자리 기준으로 한 번만 센다.
  const seen = new Set();
  return found.filter((hit) => {
    const key = `${hit.file}:${hit.line}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/* ──────────────────────────────  판정  ─────────────────────────────── */

// 같은 규칙 안에서 3D 공간을 평면으로 되돌리는 속성들. 스펙상 "그룹핑" 속성이라
// preserve-3d 를 쓴 값이 flat 으로 강제된다.
const FLATTENERS = [
  ["overflow", (v) => !/\bvisible\b/.test(v)],
  ["overflow-x", (v) => !/\bvisible\b/.test(v)],
  ["overflow-y", (v) => !/\bvisible\b/.test(v)],
  ["filter", (v) => !/^none$/i.test(v.trim())],
  ["backdrop-filter", (v) => !/^none$/i.test(v.trim())],
  ["-webkit-backdrop-filter", (v) => !/^none$/i.test(v.trim())],
  ["opacity", (v) => { const n = Number.parseFloat(v); return !Number.isNaN(n) && n < 1; }],
  ["mask", (v) => !/^none$/i.test(v.trim())],
  ["mask-image", (v) => !/^none$/i.test(v.trim())],
  ["-webkit-mask-image", (v) => !/^none$/i.test(v.trim())],
  ["clip-path", (v) => !/^none$/i.test(v.trim())],
  ["mix-blend-mode", (v) => !/^normal$/i.test(v.trim())],
  ["contain", (v) => /\b(paint|layout|strict|content)\b/.test(v)],
  ["isolation", (v) => /\bisolate\b/.test(v)],
];

const V3_TOKENS = /\banime\.(timeline|stagger|random|path|setDashoffset|remove|get|set|running|speed|suspendWhenDocumentHidden)\b|\banime\s*\(\s*\{[\s\S]{0,400}?\btargets\s*:/;
const V4_IMPORT = /\bfrom\s*["']animejs(?:\/[\w./-]+)?["']|\brequire\s*\(\s*["']animejs["']\s*\)/;

// 실시간 3D 런타임 파일. 여기서는 원근이 CSS 가 아니라 카메라에 있으므로 D1 의 관할이 아니다 —
// 씬·예산·연출은 엔진 3(asgard-freyja-3d)이 소유하고 detect3d 가 판정한다.
const SCENE_RUNTIME = /\bfrom\s*["'](?:three|three\/[\w./-]+|@react-three\/[\w-]+|@tresjs\/[\w-]+|@threlte\/[\w-]+|babylonjs|@babylonjs\/[\w-]+)["']|animejs\/adapters\/three|\bnew\s+(?:THREE\.)?(?:Perspective|Orthographic)Camera\s*\(/;

function sceneFiles(bundle) {
  const set = new Set();
  for (const doc of bundle.docs) if (SCENE_RUNTIME.test(doc.text)) set.add(doc.file);
  return set;
}

function judge(bundle) {
  const gates = [];
  const depth = depthHits(bundle);
  const perspective = perspectiveHits(bundle);
  // 포인터·스크롤이 값을 미는 것도 모션이다. 선언형 전환만 모션으로 세면
  // 손으로 transform 을 쓰는 틸트가 저감 모션 판정을 통째로 빠져나간다.
  const motion = has(
    bundle,
    /\b(?:transition|animation)\s*:|@keyframes\b|\b(?:animate|createTimeline|createAnimatable|onScroll|createDraggable)\s*\(|addEventListener\s*\(\s*["'](?:pointermove|mousemove|scroll|deviceorientation)["']|\bon(?:Pointer|Mouse)Move\s*[=:]|@(?:pointermove|mousemove)\b/,
  );
  const reduced = has(bundle, /prefers-reduced-motion/);

  const gate = (id, title, severity, status, hits = [], notes = []) => {
    gates.push({
      id,
      title,
      severity,
      status,
      hits: hits.slice(0, MAX_HITS),
      truncated: Math.max(0, hits.length - MAX_HITS),
      notes,
    });
  };

  // D1 — 원근 없는 깊이. rotateX/Y·translateZ 는 원근이 없으면 눌린 2D 축소로만 보인다.
  // 실시간 3D 런타임 파일은 카메라가 원근을 쥐고 있으므로 여기서 판정하지 않는다.
  const scenes = sceneFiles(bundle);
  const cssDepth = depth.filter((hit) => !scenes.has(hit.file));
  const sceneNote = scenes.size
    ? [`${scenes.size} file(s) run a 3D runtime — the camera owns the perspective there; engine 3 (asgard-freyja-3d) judges those`]
    : [];
  if (!cssDepth.length) gate("D1", "depth declares a perspective", "fail", "n/a", [], sceneNote);
  else if (perspective.length) gate("D1", "depth declares a perspective", "fail", "pass", [], [`perspective declared at ${perspective.length} site(s)`, ...sceneNote]);
  else gate("D1", "depth declares a perspective", "fail", "fail", cssDepth, ["no perspective anywhere in the scanned set — rotateX/rotateY/translateZ render as a flat squash", ...sceneNote]);

  // D2 — 같은 규칙이 preserve-3d 와 그룹핑 속성을 함께 선다. 조상 체인은 판정 밖(M3).
  const flattened = [];
  for (const rule of bundle.rules) {
    const keeper = rule.decls.find((d) => d.prop === "transform-style" && /preserve-3d/i.test(d.value));
    if (!keeper) continue;
    for (const decl of rule.decls) {
      const rule3d = FLATTENERS.find(([prop]) => prop === decl.prop);
      if (rule3d && rule3d[1](decl.value)) {
        flattened.push({
          file: rule.file,
          line: decl.line,
          evidence: `${rule.selector} { transform-style: preserve-3d; ${decl.prop}: ${decl.value} }`,
        });
      }
    }
  }
  const keepers = bundle.rules.some((r) => r.decls.some((d) => d.prop === "transform-style"));
  if (!keepers) gate("D2", "preserve-3d is not flattened by its own rule", "fail", "n/a");
  else if (flattened.length) gate("D2", "preserve-3d is not flattened by its own rule", "fail", "fail", flattened, ["a grouping property in the same rule forces transform-style back to flat"]);
  else gate("D2", "preserve-3d is not flattened by its own rule", "fail", "pass");

  // D3 — 깊이 모션에는 저감 경로가 있어야 한다. 접근성 바닥은 내려가지 않는다.
  if (!depth.length || !motion) gate("D3", "depth motion has a reduced-motion path", "fail", "n/a");
  else if (reduced) gate("D3", "depth motion has a reduced-motion path", "fail", "pass");
  else gate("D3", "depth motion has a reduced-motion path", "fail", "fail", depth, ["no prefers-reduced-motion anywhere — CSS media query, matchMedia, or anime.js createScope mediaQueries all satisfy this"]);

  // D4 — v4 를 임포트해 놓고 v3 전역 API 를 부르면 런타임에서 바로 죽는다.
  const v3 = scan(bundle, V3_TOKENS);
  const v4 = scan(bundle, V4_IMPORT);
  const clash = v3.filter((hit) => v4.some((imp) => imp.file === hit.file));
  if (!v3.length) gate("D4", "anime.js v3 API is not called under a v4 import", "fail", "n/a");
  else if (clash.length) gate("D4", "anime.js v3 API is not called under a v4 import", "fail", "fail", clash, ["v4 has no default `anime` export: anime({targets}) → animate(target, {…}), anime.timeline() → createTimeline()"]);
  else gate("D4", "anime.js v3 API is not called under a v4 import", "fail", "pass");

  // D5 — 뒤집기에 backface-visibility 가 없으면 두 면이 겹쳐 보인다.
  const flip = scan(bundle, /\brotate[XY]\s*[(:]\s*(-?180)(?:deg)?\b/);
  const backface = has(bundle, /backface-visibility/);
  if (!flip.length || !keepers) gate("D5", "a flipped face hides its backface", "warn", "n/a");
  else if (backface) gate("D5", "a flipped face hides its backface", "warn", "pass");
  else gate("D5", "a flipped face hides its backface", "warn", "warn", flip, ["180° face in a preserve-3d document with no backface-visibility declared"]);

  // D6 — 포인터 이벤트마다 직접 transform 을 쓰면 프레임과 무관하게 레이아웃 스레드를 때린다.
  const pointer = scan(bundle, /addEventListener\s*\(\s*["'](?:pointermove|mousemove)["']|\bon(?:Pointer|Mouse)Move\s*[=:]|@(?:pointermove|mousemove)\b/);
  const direct = has(bundle, /\.style\.(?:transform|setProperty)\b|\.style\.setProperty\s*\(/);
  const batched = has(bundle, /requestAnimationFrame|createAnimatable|\banimate\s*\(/);
  if (!pointer.length || !direct) gate("D6", "pointer-driven depth is frame-batched", "warn", "n/a");
  else if (batched) gate("D6", "pointer-driven depth is frame-batched", "warn", "pass");
  else gate("D6", "pointer-driven depth is frame-batched", "warn", "warn", pointer, ["writes transform per pointer event with no rAF batching and no createAnimatable"]);

  // D7 — 원근 거리가 짧으면 UI 크기 요소는 어안렌즈처럼 일그러진다.
  // 단위 없는 값(vw·em·변수 미해석)은 판정하지 않는다 — px 로 확정된 것만 잰다.
  const shallow = perspective.filter((hit) => hit.unit === "px" && hit.px !== null && hit.px > 0 && hit.px < 400);
  if (!perspective.length) gate("D7", "perspective distance stays out of fisheye range", "warn", "n/a");
  else if (shallow.length) gate("D7", "perspective distance stays out of fisheye range", "warn", "warn", shallow, ["under ~400px a UI-sized element distorts; 2–4× the element's width reads natural"]);
  else gate("D7", "perspective distance stays out of fisheye range", "warn", "pass");

  // D8 — will-change 를 넓은 선택자에 걸면 합성 레이어가 페이지 전체에 남는다.
  const broad = [];
  for (const rule of bundle.rules) {
    if (!rule.decls.some((d) => d.prop === "will-change")) continue;
    const selectors = rule.selector.split(",").map((s) => s.trim()).filter(Boolean);
    const universal = selectors.some((s) => ["*", "html", "body", ":root"].includes(s.replace(/::?[\w-]+$/, "")));
    if (universal || selectors.length >= 4) {
      const decl = rule.decls.find((d) => d.prop === "will-change");
      broad.push({ file: rule.file, line: decl.line, evidence: `${rule.selector} { will-change: ${decl.value} }` });
    }
  }
  if (!bundle.rules.some((r) => r.decls.some((d) => d.prop === "will-change"))) gate("D8", "will-change is scoped to the animating element", "warn", "n/a");
  else if (broad.length) gate("D8", "will-change is scoped to the animating element", "warn", "warn", broad, ["will-change on a page-wide selector keeps every element on its own layer"]);
  else gate("D8", "will-change is scoped to the animating element", "warn", "pass");

  // D9 — 멈출 길 없는 3D 무한 회전. 눈을 끌어당기고 놓지 않으며 배터리를 쓴다.
  const loops = scan(bundle, /\bloop\s*:\s*(?:true|Infinity)\b|animation(?:-iteration-count)?\s*:[^;]*\binfinite\b/);
  const stoppable = has(bundle, /\.pause\s*\(|animation-play-state|IntersectionObserver|visibilitychange|prefers-reduced-motion/);
  if (!loops.length || !depth.length) gate("D9", "an endless 3D loop can be stopped", "warn", "n/a");
  else if (stoppable) gate("D9", "an endless 3D loop can be stopped", "warn", "pass");
  else gate("D9", "an endless 3D loop can be stopped", "warn", "warn", loops, ["no pause, no offscreen stop, no reduced-motion branch"]);

  // D10 — v3 만 쓰는 코드. 죽지는 않지만 v4 가 현행 메이저다.
  if (!v3.length || clash.length) gate("D10", "anime.js version pin is current", "warn", "n/a");
  else gate("D10", "anime.js version pin is current", "warn", "warn", v3, ["v3-only API in use; v4 is the current major — confirm the pin is deliberate"]);

  return gates;
}

// 기계가 판정할 수 없는 것들. 침묵은 통과가 아니라 미확인이다.
const UNJUDGED = [
  ["M1", "text stays sharp — a rotated composited layer rasterizes once and scales; read it at rest, not in a screenshot"],
  ["M2", "hit targets and focus order follow the rotated geometry, and a hidden backface never eats a click"],
  ["M3", "no ancestor flattens the 3D context — only same-rule flattening is judged (D2); the cascade decides the rest"],
  ["M4", "frame budget on the target device, not on the machine that wrote it"],
  ["M5", "the depth earns its place — the delivering engine's restraint or slop gate owns this, not this script"],
];

/* ───────────────────────────────  CLI  ─────────────────────────────── */

function main(argv) {
  const targets = [];
  let asJson = false;
  let report = false;
  let severity = "fail";
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--json") asJson = true;
    else if (arg === "--report") report = true;
    else if (arg === "--severity") severity = (argv[++i] || "fail").toLowerCase();
    else if (arg === "-h" || arg === "--help") {
      process.stdout.write("usage: depth_gate.mjs <file|dir> [...] [--json] [--report] [--severity warn|fail]\n");
      return 0;
    } else targets.push(arg);
  }
  if (!targets.length) {
    process.stderr.write("depth_gate: no target given\n");
    return 2;
  }
  const bundle = loadBundle(targets);
  if (!bundle.files.length) {
    process.stderr.write("depth_gate: no CSS, markup, or script files under the given target\n");
    return 2;
  }

  const gates = judge(bundle);
  const fail = gates.filter((g) => g.status === "fail");
  const warn = gates.filter((g) => g.status === "warn");
  const pass = gates.filter((g) => g.status === "pass");
  const na = gates.filter((g) => g.status === "n/a");
  const blocked = fail.length > 0 || (severity === "warn" && warn.length > 0);
  const payload = {
    tool: "depth_gate",
    version: "1",
    target: targets,
    files: bundle.files,
    gates,
    unjudged: UNJUDGED.map(([id, why]) => ({ id, why })),
    summary: {
      pass: pass.length,
      fail: fail.length,
      warn: warn.length,
      notApplicable: na.length,
      unjudged: UNJUDGED.length,
    },
    verdict: blocked ? "fail" : "pass",
  };

  if (report) {
    const dir = path.join(process.cwd(), ".asgard", ".vanadis", "sjonhverfing");
    fs.mkdirSync(dir, { recursive: true });
    const slug = path.basename(path.resolve(targets[0])).replace(/[^\w.-]/g, "-");
    const out = path.join(dir, `depth-${slug}.json`);
    fs.writeFileSync(out, JSON.stringify(payload, null, 2));
    if (!asJson) process.stdout.write(`report written: ${path.relative(process.cwd(), out)}\n`);
  }

  if (asJson) {
    process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
    return blocked ? 1 : 0;
  }

  const lines = [`⠶ Sjónhverfing depth gate — ${bundle.files.length} file(s)`];
  for (const file of bundle.files) lines.push(`   ${path.relative(process.cwd(), file)}`);
  lines.push("");
  for (const g of gates) {
    const tag = g.status === "fail" ? "FAIL" : g.status === "warn" ? "warn" : g.status === "n/a" ? "n/a " : "pass";
    lines.push(`  ${tag}  gate ${String(g.id).padEnd(4)} ${g.title}`);
    for (const hit of g.hits) lines.push(`            ${path.relative(process.cwd(), hit.file)}:${hit.line}  ${hit.evidence}`);
    if (g.truncated) lines.push(`            … ${g.truncated} more`);
    for (const note of g.notes) lines.push(`            note · ${note}`);
  }
  lines.push("");
  lines.push(`  unjudged (${UNJUDGED.length}) — these are yours, not passes:`);
  for (const [id, why] of UNJUDGED) lines.push(`    ${id}  ${why}`);
  lines.push("");
  lines.push(`  ${pass.length} pass · ${fail.length} fail · ${warn.length} warn · ${na.length} not applicable · ${UNJUDGED.length} unjudged`);
  lines.push(`  verdict: ${payload.verdict.toUpperCase()}`);
  process.stdout.write(lines.join("\n") + "\n");
  return blocked ? 1 : 0;
}

// process.exit() 은 파이프로 나가는 stdout 의 비동기 버퍼를 버린다 — 64KB 를 넘는 --json 이
// 잘려 나간다. 종료 코드만 세우고 node 가 스스로 비우고 끝내게 둔다.
process.exitCode = main(process.argv.slice(2));
