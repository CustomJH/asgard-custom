#!/usr/bin/env node
// Freyja 4 (Mardöll) — deterministic slop gate.
//
// Judges the subset of the 58-gate slop test that can be decided from source
// with certainty. Everything that needs a rendered page is reported as
// `manual` and never counted as a pass. Dependency-free: node built-ins only.
//
//   node slop_gate.mjs <file|dir> [...] [--genre <g>] [--json] [--report]
//
// Exit code 1 when any judged gate fails.

import fs from "node:fs";
import path from "node:path";

/* ─────────────────────────────  colour math  ───────────────────────────── */

const NAMED = {
  black: [0, 0, 0], white: [255, 255, 255], red: [255, 0, 0], blue: [0, 0, 255],
  green: [0, 128, 0], gray: [128, 128, 128], grey: [128, 128, 128],
  silver: [192, 192, 192], navy: [0, 0, 128], teal: [0, 128, 128],
};

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

function oklchToRgb(L, C, Hdeg) {
  const h = (Hdeg * Math.PI) / 180;
  const a = C * Math.cos(h);
  const b = C * Math.sin(h);
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
  const lin = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map(clamp01);
  const enc = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
  return lin.map((c) => Math.round(clamp01(enc(c)) * 255));
}

function rgbToOklch([r, g, b]) {
  const dec = (v) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const [R, G, B] = [dec(r), dec(g), dec(b)];
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const Bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const C = Math.hypot(A, Bb);
  let H = (Math.atan2(Bb, A) * 180) / Math.PI;
  if (H < 0) H += 360;
  return { L, C, H };
}

function luminance([r, g, b]) {
  const dec = (v) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * dec(r) + 0.7152 * dec(g) + 0.0722 * dec(b);
}

const contrastRatio = (a, b) => {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

// Functional colour notations carry spaces — oklch(82% 0.18 200). Splitting a
// declaration on whitespace and taking [0] yields "oklch(82%", which parses as
// nothing and makes a colour gate silently skip. Always extract with this.
const COLOR_TOKEN = /#[0-9a-f]{3,8}\b|(?:oklch|oklab|rgba?|hsla?|lab|lch)\([^()]*\)|\b(?:black|white|red|blue|green|gray|grey|silver|navy|teal)\b/i;

/**
 * Alpha the value actually paints with. 1 is opaque; anything less composites
 * over a backdrop this judge cannot see. `color-mix(in oklab, var(--accent) 8%,
 * transparent)` is an 8 % tint, not the accent — reading its first colour literal
 * at full strength turns a legible dark-surface chip into a contrast failure.
 */
function paintAlpha(value) {
  const s = String(value).trim().toLowerCase();
  const mix = s.match(/color-mix\([^,]*,(.+)\)$/s);
  if (mix) {
    const parts = mix[1].split(",").map((p) => p.trim());
    if (parts.length === 2) {
      const idx = parts.findIndex((p) => /^transparent\b/.test(p));
      if (idx >= 0) {
        // The mix percentage sits outside the colour's own parens. Drop those
        // first or `oklch(72% 0.09 80) 8%` reads its lightness as the weight.
        const weight = (p) => {
          const m2 = p.replace(/\([^()]*\)/g, " ").match(/([\d.]+)\s*%/);
          return m2 ? Number(m2[1]) / 100 : null;
        };
        const pct = weight(parts[1 - idx]);
        if (pct !== null) return pct;
        const own = weight(parts[idx]);
        if (own !== null) return 1 - own;
        return 0.5;
      }
    }
    return 1;
  }
  if (/^transparent$/.test(s)) return 0;
  let m = s.match(/^#([0-9a-f]{8})$/);
  if (m) return parseInt(m[1].slice(6), 16) / 255;
  m = s.match(/^#([0-9a-f]{4})$/);
  if (m) return parseInt(m[1][3] + m[1][3], 16) / 255;
  m = s.match(/^(?:rgba?|hsla?)\(([^)]*)\)$/);
  if (m) {
    // Four components means the last one is alpha; three means opaque. Counting
    // beats a trailing-number match, which reads rgb(12,10,7) as alpha 7.
    const parts = m[1].split(/[\s,/]+/).filter(Boolean);
    if (parts.length !== 4) return 1;
    return parts[3].endsWith("%") ? Number(parts[3].slice(0, -1)) / 100 : Number(parts[3]);
  }
  m = s.match(/^(?:oklch|oklab|lab|lch)\([^)]*\/\s*([\d.]+%?)\s*\)$/);
  if (m) return m[1].endsWith("%") ? Number(m[1].slice(0, -1)) / 100 : Number(m[1]);
  return 1;
}

/** First colour literal in a declaration value, parsed. Null when there is none. */
function firstColor(value) {
  const m = String(value).match(COLOR_TOKEN);
  return m ? parseColor(m[0]) : null;
}

/** Parse one colour literal into { rgb, oklch, raw }. Returns null if not a colour. */
function parseColor(raw) {
  const s = String(raw).trim().toLowerCase();
  let m = s.match(/^#([0-9a-f]{3,8})$/);
  if (m) {
    let hex = m[1];
    if (hex.length === 3 || hex.length === 4) hex = hex.slice(0, 3).split("").map((c) => c + c).join("");
    if (hex.length >= 6) {
      const rgb = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
      return { rgb, oklch: rgbToOklch(rgb), raw: s };
    }
    return null;
  }
  m = s.match(/^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)/);
  if (m) {
    const L = m[2] === "%" ? Number(m[1]) / 100 : Number(m[1]);
    const C = Number(m[3]);
    const H = Number(m[4]);
    return { rgb: oklchToRgb(L, C, H), oklch: { L, C, H }, raw: s };
  }
  m = s.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/);
  if (m) {
    const rgb = [1, 2, 3].map((i) => Math.round(Number(m[i])));
    return { rgb, oklch: rgbToOklch(rgb), raw: s };
  }
  m = s.match(/^hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%/);
  if (m) {
    const [h, sat, lig] = [Number(m[1]) / 360, Number(m[2]) / 100, Number(m[3]) / 100];
    const f = (n) => {
      const k = (n + h * 12) % 12;
      const a = sat * Math.min(lig, 1 - lig);
      return Math.round(255 * (lig - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
    };
    const rgb = [f(0), f(8), f(4)];
    return { rgb, oklch: rgbToOklch(rgb), raw: s };
  }
  if (NAMED[s]) return { rgb: NAMED[s], oklch: rgbToOklch(NAMED[s]), raw: s };
  return null;
}

/* ───────────────────────────────  CSS model  ──────────────────────────── */

const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));

/**
 * Flatten a stylesheet into rules: { selector, decls:[{prop,value,line}], at:[...] }.
 * At-rule context is kept as a list of prelude strings so media queries are visible.
 */
function parseCss(cssRaw, file) {
  const css = stripComments(cssRaw);
  const rules = [];
  const stack = [];
  let buf = "";
  let line = 1;
  let startLine = 1;
  for (let i = 0; i < css.length; i++) {
    const ch = css[i];
    if (ch === "\n") line++;
    if (ch === "{") {
      const prelude = buf.trim();
      buf = "";
      if (prelude.startsWith("@")) {
        stack.push({ kind: "at", prelude, line });
      } else {
        stack.push({ kind: "rule", prelude, line, decls: [], startLine: line });
      }
      startLine = line;
      continue;
    }
    if (ch === "}") {
      const frame = stack.pop();
      if (frame && frame.kind === "rule") {
        pushDecls(frame, buf, line);
        rules.push({
          file,
          selector: frame.prelude,
          line: frame.startLine,
          decls: frame.decls,
          at: stack.filter((f) => f.kind === "at").map((f) => f.prelude),
        });
      } else if (frame && frame.kind === "at" && buf.trim()) {
        // at-rule with plain declarations (e.g. @font-face)
        const pseudo = { prelude: frame.prelude, decls: [], startLine: frame.line };
        pushDecls(pseudo, buf, line);
        rules.push({
          file,
          selector: frame.prelude,
          line: frame.line,
          decls: pseudo.decls,
          at: stack.filter((f) => f.kind === "at").map((f) => f.prelude),
        });
      }
      buf = "";
      continue;
    }
    if (ch === ";" && stack.length && stack[stack.length - 1].kind === "rule") {
      pushDecls(stack[stack.length - 1], buf, line);
      buf = "";
      continue;
    }
    if (ch === ";" && stack.length && stack[stack.length - 1].kind === "at") {
      pushDecls(stack[stack.length - 1], buf, line);
      buf = "";
      continue;
    }
    buf += ch;
  }
  return rules;

  function pushDecls(frame, chunk, atLine) {
    for (const part of chunk.split(";")) {
      const idx = part.indexOf(":");
      if (idx < 0) continue;
      const prop = part.slice(0, idx).trim().toLowerCase();
      const value = part.slice(idx + 1).trim();
      if (!prop || !value) continue;
      frame.decls.push({ prop, value, line: atLine - (chunk.slice(chunk.indexOf(part)).match(/\n/g) || []).length });
    }
  }
}

/** Token map from :root / [data-theme] blocks, with var() chains resolved. */
function tokenMap(rules) {
  const raw = new Map();
  for (const r of rules) {
    if (!/(^|,)\s*(:root|\[data-theme)/.test(r.selector)) continue;
    for (const d of r.decls) if (d.prop.startsWith("--")) raw.set(d.prop, d.value);
  }
  const resolve = (value, depth = 0) => {
    if (depth > 12) return value;
    return value.replace(/var\(\s*(--[\w-]+)\s*(?:,([^()]*))?\)/g, (_m, name, fb) => {
      if (raw.has(name)) return resolve(raw.get(name), depth + 1);
      return fb ? fb.trim() : "";
    });
  };
  const out = new Map();
  for (const [k, v] of raw) out.set(k, resolve(v).trim());
  return { raw, resolved: out, resolve };
}

/* ───────────────────────────────  HTML model  ─────────────────────────── */

const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);

function parseHtml(html) {
  const root = { tag: "#root", attrs: {}, children: [], text: "", line: 1 };
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
  let last = 0;
  let m;
  const lineAt = (idx) => html.slice(0, idx).split("\n").length;
  while ((m = re.exec(html))) {
    const between = html.slice(last, m.index);
    if (between.trim()) stack[stack.length - 1].text += " " + between.trim();
    last = re.lastIndex;
    if (m[0].startsWith("<!--")) continue;
    const [, closing, tagRaw, attrRaw, selfClose] = m;
    const tag = tagRaw.toLowerCase();
    if (closing) {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tag === tag) { stack.length = i; break; }
      }
      continue;
    }
    const attrs = {};
    const ar = /([\w:.-]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
    let am;
    while ((am = ar.exec(attrRaw))) {
      attrs[am[1].toLowerCase()] = am[3] ?? am[4] ?? am[5] ?? "";
    }
    const node = { tag, attrs, children: [], text: "", line: lineAt(m.index), raw: m[0] };
    stack[stack.length - 1].children.push(node);
    if (!VOID.has(tag) && !selfClose) stack.push(node);
    if (tag === "script" || tag === "style") {
      const close = new RegExp(`</${tag}\\s*>`, "i");
      const rest = html.slice(re.lastIndex);
      const cm = rest.match(close);
      const body = cm ? rest.slice(0, cm.index) : rest;
      node.body = body;
      re.lastIndex += cm ? cm.index + cm[0].length : rest.length;
      last = re.lastIndex;
      if (stack[stack.length - 1] === node) stack.pop();
    }
  }
  if (html.slice(last).trim()) stack[stack.length - 1].text += " " + html.slice(last).trim();
  return root;
}

function* walk(node) {
  for (const c of node.children) {
    yield c;
    yield* walk(c);
  }
}

const cls = (n) => (n.attrs?.class || "").toLowerCase();
const HEADINGS = new Set(["h1", "h2", "h3", "h4", "h5", "h6"]);

/* ───────────────────────────────  the gates  ──────────────────────────── */

const BANNED_DISPLAY = ["inter", "roboto", "open sans", "poppins", "lato", "system-ui", "-apple-system", "segoe ui"];
const CLICHE = ["jane doe", "john smith", "acme", "nexus", "seamless", "unleash"];
const ICON_LIBS = [
  [/\blucide[-\s]/i, "lucide"],
  [/\bheroicon/i, "heroicons"],
  [/\bmaterial-icons\b/i, "material"],
  [/\bfa[srlbd]?-[a-z]/i, "font-awesome"],
  [/\bph-[a-z]/i, "phosphor"],
  [/\bbi-[a-z]/i, "bootstrap-icons"],
  [/\bfeather\b/i, "feather"],
];
// Emoji, judged by the Unicode property — not by codepoint block. Arrows and
// other typographic marks (→ ↳ ✓ ·) live inside the symbol blocks but are not
// pictographic, and banning them would be a false positive on ordinary type.
const EMOJI = /\p{Extended_Pictographic}/u;
const CHROME_WORDS = /(browser-?bar|browser-?chrome|window-?chrome|title-?bar|traffic-?light|phone-?frame|device-?frame|\bnotch\b|ide-?chrome|fake-?terminal|terminal-?chrome|mock-?window|code-?window)/i;
const UI_SELECTOR = /(button|\.btn|\[role=["']?button|modal|dialog|tooltip|dropdown|menu|tab|input|select|textarea|nav\b|\.cta|link)/i;
const DISPLAYISH = /(^|[\s,>+~])(h1|h2)\b|hero__?(display|title)|display|section__?title|__title|wordmark|stat__?figure/i;
const EYEBROW_CLASS = /(eyebrow|kicker|label|tag|section__?num|num\b|overline|caption)/i;
const EYEBROW_TEXT = /^\s*(\d{1,2}\s*[·/.\-—]\s*\S|chapter\s|step\s\d)/i;

function judge(bundle, genre) {
  const { rules, html, files, firstCssComment, hasHtml } = bundle;
  const tokens = tokenMap(rules);
  const gates = [];
  const add = (id, title, findings, opts = {}) => {
    gates.push({
      id, title,
      status: opts.na ? "n/a" : findings.length ? "fail" : "pass",
      findings: findings.slice(0, 12),
      truncated: Math.max(0, findings.length - 12),
      notes: opts.notes || [],
    });
  };
  const at = (r, d) => `${path.basename(r.file)}:${d?.line ?? r.line}`;
  const decls = [];
  for (const r of rules) for (const d of r.decls) decls.push({ r, d });

  const isTokenBlock = (sel) => /(^|,)\s*(:root|\[data-theme)/.test(sel);

  /** Largest px a font-size value can resolve to; null when it can't be decided. */
  const maxPx = (value) => {
    const v = tokens.resolve(value);
    let best = null;
    for (const mm of v.matchAll(/(-?[\d.]+)(px|rem|em)\b/g)) {
      const px = mm[2] === "px" ? Number(mm[1]) : Number(mm[1]) * 16;
      if (best === null || px > best) best = px;
    }
    return best;
  };

  /* Index the markup so a rule can be asked "does this surface actually carry text?".
     Without it, every decorative accent chip and ::before bar reads as an unreadable
     text surface. */
  const byClass = new Map();
  const byTag = new Map();
  const push = (map, key, n) => { if (!map.has(key)) map.set(key, []); map.get(key).push(n); };
  for (const root of html) {
    for (const n of walk(root)) {
      push(byTag, n.tag, n);
      for (const c of cls(n).split(/\s+/).filter(Boolean)) push(byClass, c, n);
    }
  }
  const hasOwnOrChildText = (n) => {
    if ((n.text || "").trim()) return true;
    for (const d of walk(n)) if ((d.text || "").trim()) return true;
    return false;
  };
  /** True when the rule paints a surface that some real element renders text on. */
  const carriesText = (r) => {
    const fontish = r.decls.some((d) => /^(font|line-height|letter-spacing|text-)/.test(d.prop));
    for (const s of r.selector.split(",")) {
      const sel = s.trim();
      const pseudo = sel.match(/::(before|after)/);
      if (pseudo) {
        const content = r.decls.find((d) => d.prop === "content");
        // A pseudo-element with no content never renders; with "" it renders no text.
        if (!content) return false;
        return /["'][^"']+["']/.test(content.value) || /counter|attr\(/.test(content.value);
      }
      const last = (sel.split(/[\s>+~]+/).filter(Boolean).pop() || "").replace(/:{1,2}[\w-]+(\([^)]*\))?/g, "");
      let nodes = null;
      if (last.startsWith(".")) nodes = byClass.get(last.slice(1).split(/[.#[]/)[0]);
      else if (/^[a-z]/i.test(last)) nodes = byTag.get(last.split(/[.#[:]/)[0].toLowerCase());
      if (nodes && nodes.some(hasOwnOrChildText)) return true;
      if (!hasHtml && fontish) return true;
    }
    return false;
  };

  /* Two different questions, two different sets.
     - displayRules: does this element render display-SIZE text? Gates 51 and 55
       are about wrapping and cap-collision at large sizes, so a 20px wordmark
       is not one of them however it is named.
     - typeSlotRules: does this rule own a display TYPE SLOT? Gate 38a bans an
       italic wordmark or stat figure outright, at any size. */
  const bigEnough = (r) => {
    const fs = r.decls.filter((d) => d.prop === "font-size").pop();
    if (!fs) return false;
    const px = maxPx(fs.value);
    return px !== null && px >= 32;
  };
  const displayRules = rules.filter(
    (r) => !isTokenBlock(r.selector) && (bigEnough(r) || /(^|[\s,>+~])(h1|h2)\b/.test(r.selector)),
  );
  const isDisplayRule = (r) => displayRules.includes(r);
  const isTypeSlotRule = (r) => !isTokenBlock(r.selector) && (displayRules.includes(r) || DISPLAYISH.test(r.selector));

  /* A transition names a property; the rule that changes it may use a shorthand.
     `background: X` on :hover does change background-color — reading only the
     exact longhand reports live motion as dead. */
  const SHORTHAND = {
    "background-color": ["background"],
    "border-color": [
      "border", "border-top", "border-right", "border-bottom", "border-left",
      "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
      "border-block", "border-inline", "border-block-color", "border-inline-color",
    ],
    "border-top-color": ["border", "border-top"],
    "border-bottom-color": ["border", "border-bottom"],
    "border-left-color": ["border", "border-left"],
    "border-right-color": ["border", "border-right"],
    "outline-color": ["outline"],
    "background-position": ["background"],
    "background-size": ["background"],
    "flex-basis": ["flex"],
    "grid-template-columns": ["grid-template", "grid"],
  };
  const setsProperty = (declProp, wanted) => declProp === wanted || (SHORTHAND[wanted] || []).includes(declProp);

  /* A state variant is the same element in another state. `.btn:hover`,
     `.btn:active`, `details[open] .sign` and `.btn` are one element to every
     gate here: a rule that only flips a background inherits the base rule's
     colour, and a `:hover` override inherits the base rule's overflow-wrap.
     Reading them as separate elements is the single largest false-positive
     source in a source-only judge, so normalise before comparing. */
  // Longest alternative first. JS alternation is first-match-wins, so listing
  // `focus` before `focus-visible` made `:focus-within` normalize to `-within`
  // instead of dropping — and a selector that never equals its base means
  // `sameElement` said no. Every `:focus-visible` / `:focus-within` state rule
  // was invisible to the judge, so A1 called any transition they drive "dead
  // motion". The ruler was wrong, not the surface.
  const STATE_BITS = /:{1,2}(hover|active|focus-visible|focus-within|focus|visited|disabled|checked|target|user-invalid|user-valid|invalid|valid|placeholder|first-child|last-child|nth-child\([^)]*\)|not\([^)]*\)|is\([^)]*\)|where\([^)]*\)|has\([^)]*\)|before|after|details-content|marker|selection|backdrop|-webkit-[\w-]+)/g;
  const normSelector = (s) =>
    s
      .replace(STATE_BITS, "")
      .replace(/\[[^\]]*\]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  const subjectOf = (s) => {
    const parts = normSelector(s).split(/[\s>+~]+/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : "";
  };
  const classesOf = (s) => new Set((normSelector(s).match(/\.[\w-]+/g) || []));
  const contextOf = (s) => {
    const parts = normSelector(s).split(/[\s>+~]+/).filter(Boolean);
    return parts.slice(0, -1).join(" ");
  };
  const compoundTag = (c) => (c.match(/^[a-z][\w-]*/i) || [""])[0];
  const compoundId = (c) => (c.match(/#[\w-]+/) || [""])[0];
  const compoundClasses = (c) => new Set(c.match(/\.[\w-]+/g) || []);
  /* Not every state is a pseudo-class. `.chip` / `.chip.on`, `.row` / `.row.is-open`,
     `#tip` / `#tip.pinned` are one element too — the state rides on a class the
     subject compound gains, so the strings differ where the element does not.
     Compare the compounds structurally: the tag and the id have to agree, and a
     class only has to overlap. The ancestor context below is what still keeps
     `.zoombar button` and `.modebar button` apart; `.rk` and `.rn` never merge
     here because their subject classes do not overlap. */
  const sameSubject = (a, b) => {
    if (a === b) return true;
    if (compoundTag(a) !== compoundTag(b)) return false;
    const ia = compoundId(a);
    const ib = compoundId(b);
    if (!ia !== !ib) return false;
    if (ia && ib && ia !== ib) return false;
    const ca = compoundClasses(a);
    const cb = compoundClasses(b);
    if (ca.size && cb.size) return [...ca].some((c) => cb.has(c));
    return ca.size !== cb.size; // one side simply adds the state class
  };
  /** Do two selectors address the same element in different states? */
  const sameElement = (a, b) => {
    for (const sa of a.split(",")) {
      for (const sb of b.split(",")) {
        const na = normSelector(sa);
        const nb = normSelector(sb);
        if (!na || !nb) continue;
        if (na === nb) return true;
        if (subjectOf(sa) && sameSubject(subjectOf(sa), subjectOf(sb))) {
          // The subjects match; the ancestor context decides. A bare `.chip` rule
          // also paints `.legend .chip`, so an empty context matches anything —
          // but two different non-empty contexts are two different elements
          // unless they share a class somewhere in the chain.
          const ctxA = contextOf(sa);
          const ctxB = contextOf(sb);
          if (!ctxA || !ctxB || ctxA === ctxB) return true;
          if ([...classesOf(sa)].some((c) => classesOf(sb).has(c))) return true;
        }
      }
    }
    return false;
  };

  /* 1 — display font on the banned list */
  {
    const f = [];
    for (const { r, d } of decls) {
      if (d.prop !== "font-family" && d.prop !== "--font-display" && d.prop !== "--font-body" && d.prop !== "--font-outlier") continue;
      const first = tokens.resolve(d.value).split(",")[0].replace(/["']/g, "").trim().toLowerCase();
      if (!first) continue;
      const isDisplaySlot = d.prop === "--font-display" || DISPLAYISH.test(r.selector);
      if (isDisplaySlot && BANNED_DISPLAY.some((b) => first === b || first.startsWith(b))) {
        f.push(`${at(r, d)}  display face "${first}" is an on-distribution default`);
      }
    }
    add(1, "display font is not a trained-in default", f);
  }

  /* 2 — purple→blue / cyan→magenta gradient, and any gradient on text */
  {
    const f = [];
    for (const { r, d } of decls) {
      const v = tokens.resolve(d.value);
      if (!/gradient\(/i.test(v)) continue;
      const stops = [...v.matchAll(/#[0-9a-f]{3,8}|oklch\([^)]*\)|rgba?\([^)]*\)|hsla?\([^)]*\)/gi)]
        .map((mm) => parseColor(mm[0])).filter(Boolean);
      const hues = stops.filter((s) => s.oklch.C > 0.02).map((s) => s.oklch.H);
      const inViolet = hues.filter((h) => h >= 250 && h <= 340).length;
      const cyan = hues.some((h) => h >= 170 && h <= 235);
      const magenta = hues.some((h) => h >= 300 && h <= 355);
      if (inViolet >= 2 || (cyan && magenta)) {
        f.push(`${at(r, d)}  ${d.prop}: violet/blue or cyan/magenta gradient (${hues.map((h) => Math.round(h)).join("→")})`);
      }
      const rule = r.decls.map((x) => `${x.prop}:${x.value}`).join(";");
      if (/background-clip\s*:\s*text|-webkit-background-clip\s*:\s*text/i.test(rule)) {
        f.push(`${at(r, d)}  gradient text (background-clip: text) — banned in every genre`);
      }
    }
    add(2, "no gradient-text, no violet/blue or cyan/magenta gradient", f);
  }

  /* 7 — pure black / pure white as a base colour */
  {
    const f = [];
    const allowWhite = genre === "modern-minimal";
    for (const { r, d } of decls) {
      if (!/^(--color|color|background|background-color|border-color|fill|stroke)/.test(d.prop)) continue;
      for (const lit of d.value.match(/#[0-9a-f]{3,8}|oklch\([^)]*\)|rgba?\([^)]*\)|\b(?:black|white)\b/gi) || []) {
        const c = parseColor(lit);
        if (!c) continue;
        const isBlack = c.rgb.every((v) => v === 0);
        const isWhite = c.rgb.every((v) => v === 255);
        if (isBlack) f.push(`${at(r, d)}  ${d.prop}: pure black (${lit})`);
        else if (isWhite && !allowWhite) f.push(`${at(r, d)}  ${d.prop}: pure white (${lit})`);
      }
    }
    add(7, `no pure #000${allowWhite ? "" : " / #fff"} base colour`, f);
  }

  /* 10 — transition: all */
  {
    const f = [];
    for (const { r, d } of decls) {
      if (!/^(transition|transition-property|-webkit-transition)/.test(d.prop)) continue;
      if (/\ball\b/.test(tokens.resolve(d.value))) f.push(`${at(r, d)}  ${r.selector.trim().slice(0, 60)} — ${d.prop}: ${d.value}`);
    }
    for (const n of html.flatMap((h) => [...walk(h)])) {
      if (/\btransition-all\b/.test(cls(n))) f.push(`html:${n.line}  class="transition-all"`);
    }
    add(10, "no transition: all", f);
  }

  /* 11 — uniform hover-scale across unrelated elements */
  {
    const byScale = new Map();
    for (const r of rules) {
      if (!/:hover/.test(r.selector)) continue;
      for (const d of r.decls) {
        const mm = tokens.resolve(d.value).match(/scale\(\s*([\d.]+)/);
        if (d.prop === "transform" && mm) {
          const k = mm[1];
          if (!byScale.has(k)) byScale.set(k, []);
          byScale.get(k).push(`${at(r, d)}  ${r.selector.trim().slice(0, 50)}`);
        }
      }
    }
    const f = [];
    for (const [k, list] of byScale) {
      if (list.length >= 3) f.push(`scale(${k}) on ${list.length} hover selectors — ${list.slice(0, 3).join(" · ")}`);
    }
    for (const n of html.flatMap((h) => [...walk(h)])) {
      if (/hover:scale-\d/.test(cls(n))) f.push(`html:${n.line}  hover:scale utility`);
    }
    add(11, "no uniform hover-scale across unrelated elements", f);
  }

  /* 12 — overshoot easing on UI state */
  {
    const f = [];
    const overshoot = (v) => {
      const mm = v.match(/cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/);
      if (!mm) return null;
      const y1 = Number(mm[2]), y2 = Number(mm[4]);
      return y1 > 1.001 || y2 > 1.001 || y1 < -0.001 || y2 < -0.001 ? mm[0] : null;
    };
    const badTokens = new Set();
    for (const { r, d } of decls) {
      if (!d.prop.startsWith("--")) continue;
      if (overshoot(d.value)) badTokens.add(d.prop);
    }
    for (const { r, d } of decls) {
      if (!/^(transition|animation)/.test(d.prop)) continue;
      const usesBad = [...badTokens].some((t) => d.value.includes(`var(${t}`));
      const direct = overshoot(tokens.resolve(d.value));
      if ((usesBad || direct) && UI_SELECTOR.test(r.selector)) {
        f.push(`${at(r, d)}  ${r.selector.trim().slice(0, 50)} — overshoot easing on UI state`);
      }
    }
    add(12, "no overshoot easing on UI state changes", f);
  }

  /* 14 — animating layout properties */
  {
    const LAYOUT = /\b(width|height|top|left|right|bottom|margin(-\w+)?|padding(-\w+)?)\b/;
    const f = [];
    for (const { r, d } of decls) {
      if (/^(transition|transition-property)/.test(d.prop) && LAYOUT.test(tokens.resolve(d.value))) {
        f.push(`${at(r, d)}  ${d.prop}: ${d.value.slice(0, 50)}`);
      }
    }
    for (const r of rules) {
      if (!r.at.some((a) => /^@keyframes/.test(a))) continue;
      for (const d of r.decls) {
        if (LAYOUT.test(d.prop)) f.push(`${at(r, d)}  ${r.at.find((a) => /^@keyframes/.test(a))} animates ${d.prop}`);
      }
    }
    add(14, "animates transform/opacity only", f);
  }

  /* 15 — focus ring fades in */
  {
    const f = [];
    for (const { r, d } of decls) {
      if (!/^(transition|transition-property)/.test(d.prop)) continue;
      const v = tokens.resolve(d.value);
      if (/\boutline\b/.test(v)) f.push(`${at(r, d)}  ${r.selector.trim().slice(0, 50)} transitions outline`);
      else if (/:focus/.test(r.selector) && /\b(box-shadow|opacity)\b/.test(v)) {
        f.push(`${at(r, d)}  focus rule transitions ${v.slice(0, 40)}`);
      }
    }
    add(15, "focus ring appears instantly", f);
  }

  /* 19 — placeholder names / startup clichés */
  {
    const f = [];
    for (const root of html) {
      for (const n of walk(root)) {
        const t = (n.text || "").toLowerCase();
        for (const c of CLICHE) {
          if (new RegExp(`\\b${c}\\b`).test(t)) f.push(`html:${n.line}  <${n.tag}> contains "${c}"`);
        }
      }
    }
    add(19, "no placeholder names or startup clichés", f, { na: !hasHtml });
  }

  /* 20 — the stamp */
  {
    const f = [];
    if (!firstCssComment) f.push("no leading CSS comment found — the stamp is missing");
    else if (!/Freyja4\s*·/.test(firstCssComment)) f.push(`leading comment is not a Freyja4 stamp: ${firstCssComment.slice(0, 60)}`);
    else if (!/macrostructure:|component:/.test(firstCssComment)) f.push("stamp present but names no macrostructure/component");
    add(20, "output carries the Freyja4 stamp", f);
  }

  /* 22 — zero-chroma neutral */
  {
    const f = [];
    if (genre !== "modern-minimal") {
      for (const [name, value] of tokens.resolved) {
        if (!name.startsWith("--color")) continue;
        const c = firstColor(value);
        if (c && c.oklch.C < 0.005 && !(c.rgb.every((v) => v === 0) || c.rgb.every((v) => v === 255))) {
          f.push(`${name}: ${value} — zero chroma, tint toward the anchor hue (min 0.005)`);
        }
      }
    }
    add(22, "neutrals are tinted, not flat grey", f, { na: genre === "modern-minimal" });
  }

  /* 24 — spacing off the 4pt scale */
  {
    const f = [];
    const SPACING = /^(padding|margin|gap|row-gap|column-gap)(-(top|right|bottom|left|block|inline)(-(start|end))?)?$/;
    for (const { r, d } of decls) {
      if (!SPACING.test(d.prop)) continue;
      const v = tokens.resolve(d.value);
      if (/\b(calc|clamp|min|max|var|env)\(/.test(v)) continue;
      for (const mm of v.matchAll(/(-?[\d.]+)(px|rem)\b/g)) {
        const px = mm[2] === "rem" ? Number(mm[1]) * 16 : Number(mm[1]);
        if (px !== 0 && Math.abs(px % 4) > 1e-6) f.push(`${at(r, d)}  ${d.prop}: ${mm[0]} (${px}px is off the 4pt scale)`);
      }
    }
    add(24, "spacing stays on the 4pt scale", f);
  }

  /* 26 — eight-state coverage */
  {
    const f = [];
    const sels = rules.map((r) => r.selector).join(" | ");
    const interactive = hasHtml
      ? html.some((root) => [...walk(root)].some((n) => ["button", "a", "input", "select", "textarea"].includes(n.tag)))
      : /button|\.btn|input|select|textarea/.test(sels);
    if (interactive) {
      if (!/:focus-visible/.test(sels)) f.push("no :focus-visible rule anywhere");
      if (!/:active/.test(sels)) f.push("no :active rule anywhere");
      if (!/(:disabled|\[disabled\]|\[aria-disabled)/.test(sels)) f.push("no disabled styling anywhere");
      if (!/:hover/.test(sels)) f.push("no :hover rule anywhere");
    }
    add(26, "interactive elements cover hover/focus-visible/active/disabled", f, { na: !interactive });
  }

  /* 27 — reduced-motion fallback */
  {
    const f = [];
    const motion = rules.some((r) =>
      r.decls.some((d) => (/^(transition|animation)/.test(d.prop) && !/\bnone\b/.test(d.value))) ||
      r.at.some((a) => /^@keyframes/.test(a)));
    const guarded = rules.some((r) => r.at.some((a) => /prefers-reduced-motion/.test(a)));
    if (motion && !guarded) f.push("motion is declared but no @media (prefers-reduced-motion: reduce) block exists");
    add(27, "every motion has a reduced-motion path", f, { na: !motion });
  }

  /* 30 — icon tells */
  {
    const f = [];
    const libs = new Set();
    for (const root of html) {
      for (const n of walk(root)) {
        const c = cls(n);
        for (const [re2, name] of ICON_LIBS) if (re2.test(c)) libs.add(name);
        const own = (n.text || "").trim();
        if (own && EMOJI.test(own)) f.push(`html:${n.line}  <${n.tag}${c ? ` class="${c.slice(0, 24)}"` : ""}> uses an emoji glyph — Asgard surfaces carry no emoji`);
      }
    }
    if (libs.size >= 2) f.push(`${libs.size} icon libraries mixed: ${[...libs].join(", ")}`);
    add(30, "one icon language, no emoji glyphs", f, { na: !hasHtml });
  }

  /* 33 — decorative svg/canvas without an accessible name or an explicit hide */
  {
    const f = [];
    for (const root of html) {
      for (const n of walk(root)) {
        if (n.tag !== "svg" && n.tag !== "canvas") continue;
        const a = n.attrs;
        const named = a["aria-label"] || a["aria-labelledby"] || a.title ||
          (a.role === "img" && [...walk(n)].some((c) => c.tag === "title"));
        const hidden = a["aria-hidden"] === "true";
        if (!named && !hidden) f.push(`html:${n.line}  <${n.tag}> has neither aria-label nor aria-hidden="true"`);
      }
    }
    add(33, "decorative graphics are named or explicitly hidden", f, { na: !hasHtml });
  }

  /* 34 — root overflow-x: clip on html AND body */
  {
    const f = [];
    const state = { html: null, body: null };
    for (const r of rules) {
      const sel = r.selector.toLowerCase();
      const targets = [];
      if (/(^|,)\s*html\b/.test(sel)) targets.push("html");
      if (/(^|,)\s*body\b/.test(sel)) targets.push("body");
      if (/(^|,)\s*html\s*,\s*body/.test(sel)) targets.push("html", "body");
      if (!targets.length) continue;
      for (const d of r.decls) {
        if (d.prop !== "overflow-x" && d.prop !== "overflow") continue;
        const v = tokens.resolve(d.value).split(/\s+/)[d.prop === "overflow" ? 0 : 0];
        for (const t of targets) state[t] = v;
      }
    }
    for (const t of ["html", "body"]) {
      if (state[t] === null) f.push(`${t} declares no overflow-x — gate 34 requires overflow-x: clip`);
      else if (state[t] !== "clip") f.push(`${t} uses overflow-x: ${state[t]} — must be clip, not ${state[t]} (clip preserves sticky/fixed descendants)`);
    }
    add(34, "html and body both declare overflow-x: clip", f);
  }

  /* 37 — more than three font families */
  {
    const fams = new Set();
    for (const { d } of decls) {
      if (d.prop !== "font-family" && !/^--font/.test(d.prop)) continue;
      const first = tokens.resolve(d.value).split(",")[0].replace(/["']/g, "").trim().toLowerCase();
      if (first && !/^(inherit|initial|unset|serif|sans-serif|monospace|cursive|system-ui)$/.test(first)) fams.add(first);
    }
    const f = fams.size > 3 ? [`${fams.size} families: ${[...fams].join(", ")} — ceiling is display + body + one outlier`] : [];
    add(37, "at most three font families (2+1)", f);
  }

  /* 38a — italic headings / display type */
  {
    const f = [];
    const notes = [];
    for (const r of rules) {
      const italic = r.decls.find((d) => d.prop === "font-style" && /italic|oblique/.test(tokens.resolve(d.value)));
      if (italic && isTypeSlotRule(r)) f.push(`${at(r, italic)}  ${r.selector.trim().slice(0, 50)} — italic display type`);
    }
    // An <em> inside a heading only fails when it actually renders italic. A rule
    // that resets it to font-style: normal and carries emphasis by weight/colour
    // is the prescribed fix, not the tell — so read the CSS before failing the tag.
    const neutralised = rules.filter((r) =>
      /\b(em|i)\b/.test(r.selector) && r.decls.some((d) => d.prop === "font-style" && /normal/.test(tokens.resolve(d.value))));
    const neutralisesFor = (headingNode) => neutralised.some((r) =>
      r.selector.split(",").some((s) => {
        const sel = s.trim().toLowerCase();
        if (!/\b(em|i)\s*$/.test(sel)) return false;
        const scope = sel.replace(/\b(em|i)\s*$/, "").trim();
        if (!scope) return true;
        if (scope.startsWith(".")) return cls(headingNode).split(/\s+/).includes(scope.slice(1));
        return scope === headingNode.tag;
      }));
    for (const root of html) {
      for (const n of walk(root)) {
        if (!HEADINGS.has(n.tag)) continue;
        for (const c of walk(n)) {
          if (c.tag !== "em" && c.tag !== "i") continue;
          if (neutralisesFor(n)) {
            notes.push(`html:${c.line}  <${c.tag}> in <${n.tag}> is reset to font-style: normal — emphasis carried without italic`);
          } else {
            f.push(`html:${c.line}  <${c.tag}> inside <${n.tag}> renders italic — italicised emphasis word in a heading`);
          }
        }
      }
    }
    add("38a", "headings and display type are roman", f, { notes });
  }

  /* 41 — the contrast failures that ship most often */
  {
    const f = [];
    const notes = [];
    // A translucent fill is not the colour it names. The rendered surface is that
    // colour composited over whatever sits behind it, and a source-only judge has
    // no backdrop — so say the ratio went unjudged instead of inventing one from
    // the literal at full strength. 0.9 keeps near-opaque scrims in scope.
    const OPAQUE_ENOUGH = 0.9;
    const translucent = (r, d, v) => {
      const a = paintAlpha(v);
      if (a >= OPAQUE_ENOUGH) return false;
      const note =
        `${at(r, d)}  ${r.selector.trim().slice(0, 44)} — fill is ${Math.round(a * 100)}% opaque; ` +
        "the rendered ratio depends on the backdrop, so it is not judged here";
      if (!notes.includes(note)) notes.push(note);
      return true;
    };
    for (const r of rules) {
      if (isTokenBlock(r.selector)) continue;
      const cd = r.decls.filter((d) => d.prop === "color").pop();
      const bd = r.decls.filter((d) => d.prop === "background" || d.prop === "background-color").pop();
      if (!cd || !bd) continue;
      const cv = tokens.resolve(cd.value).trim();
      const bvFull = tokens.resolve(bd.value).trim();
      if (/gradient|url\(/i.test(bvFull)) continue;
      if (translucent(r, bd, bvFull)) continue;
      const fg = firstColor(cv);
      const bg = firstColor(bvFull);
      if (!fg || !bg) continue;
      const dL = Math.abs(fg.oklch.L - bg.oklch.L);
      const dC = Math.abs(fg.oklch.C - bg.oklch.C);
      const ratio = contrastRatio(fg.rgb, bg.rgb);
      // Threshold follows the text's own size: large text (>= 24px, or >= 18px
      // bold) needs 3:1; everything else needs 4.5:1. One flat threshold would
      // fail legitimate display type.
      const fsd = r.decls.filter((d) => d.prop === "font-size").pop();
      const fw = r.decls.filter((d) => d.prop === "font-weight").pop();
      const px = fsd ? maxPx(fsd.value) : null;
      const bold = fw ? /^(bold|[7-9]00)$/.test(tokens.resolve(fw.value).trim()) : false;
      const large = px !== null && (px >= 24 || (px >= 18 && bold));
      const need = large ? 3 : 4.5;
      if (dL < 0.05 && dC < 0.05) {
        f.push(`${at(r, cd)}  ${r.selector.trim().slice(0, 44)} — text ≈ fill (ΔL ${dL.toFixed(3)}, ΔC ${dC.toFixed(3)}, ratio ${ratio.toFixed(2)}:1)`);
      } else if (ratio < need) {
        f.push(`${at(r, cd)}  ${r.selector.trim().slice(0, 44)} — ${ratio.toFixed(2)}:1 (needs ${need}:1 for ${large ? "large" : "body"} text)`);
      }
    }
    // Accent surfaces. The gate's substance is "text on an accent fill stays
    // readable"; the named --color-accent-ink token is how the corpus enforces
    // it. Fail on the substance — an accent fill that inherits its ink, or one
    // whose ink misses 4.5:1. When another named token already clears it, say so
    // in a note rather than failing on the name alone; nothing is dropped silently.
    const accentInk = tokens.resolved.get("--color-accent-ink");
    const accentVal = tokens.resolved.get("--color-accent");
    const accentRgb = accentVal ? firstColor(accentVal)?.rgb : null;
    for (const r of rules) {
      if (isTokenBlock(r.selector)) continue;
      const bd = r.decls.filter((d) => /^background(-color)?$/.test(d.prop)).pop();
      if (!bd || !/var\(--color-accent\)/.test(bd.value)) continue;
      if (!carriesText(r)) continue; // decorative accent chip / bar — no ink to judge
      // An accent *tint* is not an accent fill — `color-mix(accent 8%, transparent)`
      // renders as the page beneath it, so --color-accent-ink does not apply.
      if (translucent(r, bd, tokens.resolve(bd.value).trim())) continue;
      let cd = r.decls.filter((d) => d.prop === "color").pop();
      if (!cd) {
        // Inherit the colour this element carries in its BASE state. A sibling
        // `:disabled` rule is another state, not what `:active` inherits, so
        // prefer a stateless selector and only fall back to a stateful one.
        const isStateless = (sel) => !/[:[]/.test(sel.replace(/::?(before|after|details-content)/g, ""));
        let fallback = null;
        for (const o of rules) {
          if (o === r || isTokenBlock(o.selector)) continue;
          if (!sameElement(r.selector, o.selector)) continue;
          const oc = o.decls.filter((d) => d.prop === "color").pop();
          if (!oc) continue;
          if (isStateless(o.selector)) {
            cd = oc;
            break;
          }
          if (!fallback) fallback = oc;
        }
        if (!cd) cd = fallback;
      }
      if (!cd) {
        f.push(`${at(r, bd)}  ${r.selector.trim().slice(0, 44)} — accent fill inherits its text colour (ink-on-accent risk); set --color-accent-ink`);
        continue;
      }
      const ink = firstColor(tokens.resolve(cd.value));
      if (!ink || !accentRgb) continue;
      const ratio = contrastRatio(ink.rgb, accentRgb);
      if (ratio < 4.5) {
        f.push(`${at(r, cd)}  ${r.selector.trim().slice(0, 44)} — ${ratio.toFixed(2)}:1 on the accent fill (needs 4.5:1)`);
      } else if (!accentInk) {
        notes.push(`${at(r, cd)}  accent fill is readable at ${ratio.toFixed(2)}:1 via ${cd.value.trim()}, but --color-accent-ink is not defined — the corpus wants the named token`);
      }
    }
    add(41, "no text≈fill, no ink-on-ink, accent surfaces stay readable", f, { notes });
  }

  /* 47 — re-drawn UI chrome */
  {
    const f = [];
    for (const root of html) {
      for (const n of walk(root)) {
        const c = cls(n);
        if (CHROME_WORDS.test(c)) f.push(`html:${n.line}  <${n.tag} class="${c.slice(0, 40)}"> reads as hand-built chrome`);
        const dots = n.children.filter((k) => /\b(dot|light|circle)\b/.test(cls(k)));
        if (dots.length === 3 && n.children.length <= 5) {
          f.push(`html:${n.line}  <${n.tag} class="${c.slice(0, 30)}"> has exactly three dot children — traffic-light chrome`);
        }
      }
    }
    for (const r of rules) if (CHROME_WORDS.test(r.selector)) f.push(`${at(r)}  selector ${r.selector.trim().slice(0, 50)}`);
    add(47, "no hand-built browser/phone/IDE chrome", f);
  }

  /* 48 — mid-render token improvisation */
  {
    const f = [];
    const LITERAL = /#[0-9a-f]{3,8}\b|(?<!--[\w-]*)\boklch\(|\brgba?\(|\bhsla?\(/i;
    for (const r of rules) {
      if (isTokenBlock(r.selector)) continue;
      if (r.at.some((a) => /^@(font-face|property)/.test(a))) continue;
      if (/^@(font-face|property|import|charset)/.test(r.selector)) continue;
      for (const d of r.decls) {
        if (d.prop.startsWith("--")) continue;
        const isColourProp = /(^|-)(color|background|background-color|border|border-\w+|outline|fill|stroke|box-shadow|text-shadow)$/.test(d.prop) ||
          /^(background|border|outline|box-shadow|text-shadow|fill|stroke|color)$/.test(d.prop);
        if (isColourProp && LITERAL.test(d.value)) {
          f.push(`${at(r, d)}  ${d.prop}: ${d.value.slice(0, 44)} — colour literal outside the token block`);
        }
        if (d.prop === "font-family" && !/var\(/.test(d.value)) {
          f.push(`${at(r, d)}  font-family bypasses the token block: ${d.value.slice(0, 44)}`);
        }
      }
    }
    add(48, "every colour and font references a named token", f);
  }

  /* 50 — image-bearing grid track without minmax(0, 1fr) */
  {
    const f = [];
    const hasImages = html.some((root) => [...walk(root)].some((n) => n.tag === "img" || n.tag === "picture")) ||
      decls.some(({ d }) => d.prop === "background-image" && /url\(/.test(d.value));
    if (hasImages) {
      for (const { r, d } of decls) {
        if (!/^grid-template-(columns|rows)$/.test(d.prop)) continue;
        const v = tokens.resolve(d.value);
        if (/(^|\s)1fr(\s|$)/.test(v.replace(/minmax\([^)]*\)/g, "MM"))) {
          f.push(`${at(r, d)}  ${d.prop}: ${d.value.slice(0, 44)} — bare 1fr on an image-bearing page; use minmax(0, 1fr)`);
        }
      }
    }
    add(50, "image-bearing grid tracks use minmax(0, 1fr)", f, { na: !hasImages });
  }

  /* 51 — display headers without long-word wrap.
     Judged per selector, not per rule: a media-query override that only resets
     font-size inherits overflow-wrap from the base rule, and reporting it as a
     second, unprotected header is a false positive. */
  {
    const f = [];
    const bySelector = new Map();
    for (const r of displayRules) {
      for (const s of r.selector.split(",")) {
        const key = normSelector(s);
        if (!key) continue;
        if (!bySelector.has(key)) bySelector.set(key, { rules: [], text: "" });
        const entry = bySelector.get(key);
        entry.rules.push(r);
        entry.text += r.decls.map((d) => `${d.prop}:${tokens.resolve(d.value)}`).join(";") + ";";
      }
    }
    for (const [selector, entry] of bySelector) {
      const wrap = /overflow-wrap\s*:\s*(anywhere|break-word)/.test(entry.text);
      const minw = /min-width\s*:\s*0/.test(entry.text);
      if (wrap && minw) continue;
      const missing = [!wrap && "overflow-wrap: anywhere", !minw && "min-width: 0"].filter(Boolean).join(" + ");
      f.push(`${at(entry.rules[0])}  ${selector.slice(0, 44)} — missing ${missing}`);
    }
    add(51, "display headers can break inside long words", f, { na: !bySelector.size });
  }

  /* 54 — eyebrow beside the heading (tag-left, header-right) */
  {
    const f = [];
    const multiCol = new Map();
    for (const { r, d } of decls) {
      if (d.prop !== "grid-template-columns") continue;
      const v = tokens.resolve(d.value).replace(/minmax\([^)]*\)/g, "MM").trim();
      const tracks = v.split(/\s+/).filter(Boolean);
      if (tracks.length >= 2 && !/^1fr$/.test(v)) {
        for (const s of r.selector.split(",")) multiCol.set(s.trim(), at(r, d));
      }
    }
    const rowFlex = new Map();
    for (const r of rules) {
      const text = r.decls.map((d) => `${d.prop}:${tokens.resolve(d.value)}`).join(";");
      if (/display\s*:\s*flex/.test(text) && !/flex-direction\s*:\s*column/.test(text)) {
        for (const s of r.selector.split(",")) rowFlex.set(s.trim(), at(r));
      }
    }
    const lookup = (c) => {
      for (const key of [...multiCol.keys(), ...rowFlex.keys()]) {
        const bare = key.replace(/::?[\w-]+(\([^)]*\))?/g, "").trim();
        if (bare.startsWith(".") && c.split(/\s+/).includes(bare.slice(1))) {
          return { where: multiCol.get(key) || rowFlex.get(key), kind: multiCol.has(key) ? "multi-column grid" : "row flex" };
        }
      }
      return null;
    };
    for (const root of html) {
      for (const n of walk(root)) {
        const heading = n.children.find((k) => HEADINGS.has(k.tag));
        if (!heading) continue;
        const eyebrow = n.children.find((k) => k !== heading &&
          (EYEBROW_CLASS.test(cls(k)) || EYEBROW_TEXT.test((k.text || "").trim())));
        if (!eyebrow) continue;
        const hit = lookup(cls(n));
        if (hit) f.push(`html:${n.line}  <${n.tag} class="${cls(n).slice(0, 30)}"> puts eyebrow beside heading via ${hit.kind} (${hit.where})`);
      }
    }
    add(54, "eyebrow stacks above the heading, never beside it", f, { na: !hasHtml });
  }

  /* 55 — all-caps display head with line-height < 1.0 */
  {
    const f = [];
    for (const r of rules) {
      const text = r.decls.map((d) => `${d.prop}:${tokens.resolve(d.value)}`).join(";");
      if (!/text-transform\s*:\s*uppercase/.test(text)) continue;
      const lh = text.match(/line-height\s*:\s*([\d.]+)\b/);
      if (lh && Number(lh[1]) < 1.0 && isDisplayRule(r)) {
        f.push(`${at(r)}  ${r.selector.trim().slice(0, 44)} — uppercase at line-height ${lh[1]} (floor is 1.0)`);
      }
    }
    add(55, "all-caps display heads keep line-height ≥ 1.0", f);
  }

  /* 56 — two sticky-at-top-0 elements */
  {
    const stickies = [];
    for (const r of rules) {
      const text = r.decls.map((d) => `${d.prop}:${tokens.resolve(d.value)}`).join(";");
      if (!/position\s*:\s*sticky/.test(text)) continue;
      const top = text.match(/(?:^|;)top\s*:\s*([^;]+)/);
      if (top && /^0(px|rem|%)?$/.test(top[1].trim())) stickies.push({ sel: r.selector.trim(), where: at(r) });
    }
    const f = [];
    if (stickies.length >= 2) {
      f.push(`${stickies.length} elements stick at top: 0 — ${stickies.map((s) => `${s.sel.slice(0, 28)} (${s.where})`).join(" · ")}`);
    }
    add(56, "only the top-level nav sticks at top: 0", f, { na: stickies.length === 0 });
  }

  /* Asgard A1 — dead motion: a transition on a property nothing changes */
  {
    const f = [];
    const changed = new Set();
    for (const r of rules) for (const d of r.decls) changed.add(d.prop);
    for (const { r, d } of decls) {
      if (d.prop !== "transition" && d.prop !== "transition-property") continue;
      // `transition: none!important` is the reduced-motion kill switch, not a
      // transition. Strip the flag before splitting or the property list reads
      // "none!important", which is not the literal "none" the filter below drops.
      const v = tokens.resolve(d.value).replace(/!\s*important/gi, " ").trim();
      const props = (d.prop === "transition"
        ? v.split(",").map((p) => p.trim().split(/\s+/)[0])
        : v.split(",").map((p) => p.trim())).filter((p) => p && p !== "none" && !/^[\d.]/.test(p));
      // The user agent drives these, not a stylesheet rule; `allow-discrete`
      // exists precisely because no author declaration flips them.
      const UA_DRIVEN = new Set(["content-visibility", "display", "overlay", "visibility"]);
      for (const p of props) {
        if (p === "all" || UA_DRIVEN.has(p)) continue;
        const stateful = rules.some((o) => {
          if (o === r) return false;
          if (!sameElement(r.selector, o.selector)) return false;
          return o.decls.some((od) => setsProperty(od.prop, p));
        });
        if (!stateful) f.push(`${at(r, d)}  ${r.selector.trim().slice(0, 40)} transitions "${p}" but nothing else sets it — dead motion`);
      }
    }
    add("A1", "no dead motion (Asgard)", f);
  }

  /* Asgard A2 — placeholder link: href="#" with no handler */
  {
    const f = [];
    for (const root of html) {
      for (const n of walk(root)) {
        if (n.tag !== "a") continue;
        const href = (n.attrs.href || "").trim();
        const handled = Object.keys(n.attrs).some((k) => k.startsWith("on")) || n.attrs["data-action"] || n.attrs["aria-controls"];
        if ((href === "#" || href === "" || href === "javascript:void(0)") && !handled) {
          f.push(`html:${n.line}  <a href="${href}"> goes nowhere — a link that does not navigate is not delivered`);
        }
      }
    }
    add("A2", "no placeholder links (Asgard)", f, { na: !hasHtml });
  }

  /* 5 — 두꺼운 색 세로 획을 두른 카드 (side-stripe card)
   *
   * 실측으로 들어온 결함이다. 사용자가 화면을 보고 "이 왼쪽 표시가 AI 슬롭"이라고 짚었는데,
   * 이 판정기는 그 게이트를 **판정하지도, 못 잰다고 선언하지도 않고** 있었다. 그건 통과보다
   * 나쁘다 — 안 본 것을 안 봤다고도 안 하면 보고서가 거짓말을 한다.
   *
   * 세로 획은 `border-left`/`border-inline-start` 로도, `box-shadow: inset Npx 0 0` 로도 그린다.
   * 후자가 더 흔한 요즘 표기라 둘 다 본다. 2px 를 넘고 색이 강조색 계열이면 문다. */
  {
    const f = [];
    const ACCENTISH = /(accent|gold|brand|primary|rune)/i;
    for (const { r, d } of decls) {
      const v = tokens.resolve(d.value);
      if (/^border-(left|right|inline-start|inline-end)$/.test(d.prop)) {
        const px = Number((v.match(/(-?[\d.]+)px/) || [])[1] || 0);
        if (px >= 2 && ACCENTISH.test(d.value)) {
          f.push(`${at(r, d)}  ${r.selector.trim().slice(0, 36)} — ${d.prop}: ${px}px 강조색 세로 획`);
        }
      } else if (d.prop === "box-shadow" && /\binset\b/.test(v)) {
        // inset <x> 0 0 <color> — 세로 획을 그림자로 그리는 표기
        for (const part of v.split(/,(?![^(]*\))/)) {
          const m = part.match(/inset\s+(-?[\d.]+)px\s+0(?:px)?\s+0(?:px)?\s+([^,]*)/i);
          if (m && Math.abs(Number(m[1])) >= 2 && ACCENTISH.test(m[2] + d.value)) {
            f.push(`${at(r, d)}  ${r.selector.trim().slice(0, 36)} — inset ${m[1]}px 강조색 세로 획`);
          }
        }
      }
    }
    add(5, "no side-stripe card — a coloured bar on the edge is a template tell", f);
  }

  /* 3 — 아이콘이 제목 위에 얹힌 3열 균등 카드 격자 (A4 가 잡는 균일 격자의 아이콘 판) */
  {
    const f = [];
    if (hasHtml) {
      for (const root of html) {
        for (const n of walk(root)) {
          const kids = n.children.filter((k) => k.tag);
          if (kids.length !== 3) continue;
          const iconTop = kids.every((k) => {
            const first = k.children.find((c) => c.tag);
            return first && (first.tag === "svg" || first.tag === "img" || /icon/i.test(cls(first)));
          });
          if (iconTop) f.push(`html:${n.line}  <${n.tag} class="${cls(n).slice(0, 28)}"> — 아이콘 위 제목의 3열 카드`);
        }
      }
    }
    add(3, "no icon-above-heading three-card grid", f, { na: !hasHtml });
  }

  /* 4 — 카드 안의 카드 */
  {
    const f = [];
    if (hasHtml) {
      const CARDY = /(^|\s)(card|tile|panel|box)(\s|$|__|-)/i;
      for (const root of html) {
        for (const n of walk(root)) {
          if (!CARDY.test(cls(n))) continue;
          for (const inner of walk(n)) {
            if (CARDY.test(cls(inner))) {
              f.push(`html:${inner.line}  <${inner.tag} class="${cls(inner).slice(0, 24)}"> 가 카드 안에 또 카드`);
              break;
            }
          }
        }
      }
    }
    add(4, "no card nested inside a card", f, { na: !hasHtml });
  }

  /* Asgard A3 — 흐름의 증거: 사전 자기비평이 스탬프에 기록되었는가.
   *
   * 이 도구는 산출물을 판정한다. 그런데 실측된 실패는 **산출물이 아니라 흐름**에서 났다:
   * 에이전트가 엔진 이름을 부르고, 판정기만 돌려 PASS 를 받고, 설계 흐름(장르·매크로 구조·
   * 사전 자기비평)은 건너뛰었다. 판정기가 통과시킨 그 화면은 사람이 보자마자 슬롭이라고 했다.
   *
   * 생각했는지는 기계가 못 본다. 그러나 **규칙이 적으라고 한 것을 적었는지**는 본다.
   * SKILL 의 계약: 여섯 축을 매기고, 3 미만이면 emit 전에 수정 패스를 돈다. 그러므로
   * 축이 없거나 3 미만인 채로 출하된 산출물은, 내용과 무관하게 규칙 위반이다. */
  {
    const f = [];
    const AXES = [["P", "Philosophy"], ["H", "Hierarchy"], ["E", "Execution"],
                  ["S", "Specificity"], ["R", "Restraint"], ["V", "Variety"]];
    const stamp = firstCssComment || "";
    // 이 게이트는 "네가 **주장한** 흐름이 실제로 돌았는가"를 묻는다 — 주장이 없으면 물을 것도
    // 없다. 남의 엔진 산출물(숀헤르빙 표본 등)까지 마르될의 흐름으로 재면 그건 판정이 아니라
    // 월권이다. 도장이 아예 없는 경우는 게이트 20 이 이미 말하므로 여기서 겹쳐 말하지 않는다.
    const claimsFreyja4 = /Freyja4\s*·/.test(stamp);
    if (!claimsFreyja4) {
      // 주장이 없다 — 판정 대상이 아니다. 게이트 20 이 도장 부재를 이미 말한다.
      add("A3", "pre-emit critique is recorded and clears 3 (Asgard)", [], { na: true });
    } else if (!/pre-?emit\s+critique/i.test(stamp)) {
      f.push("스탬프에 pre-emit critique 가 없다 — 여섯 축을 매겼다는 기록이 없으면 흐름은 안 돈 것으로 본다");
    } else {
      for (const [key, name] of AXES) {
        const m = stamp.match(new RegExp(`\\b${key}\\s*([1-5])\\b`));
        if (!m) { f.push(`pre-emit critique 에 ${key}(${name}) 축이 없다`); continue; }
        if (Number(m[1]) < 3) {
          f.push(`${key}(${name}) = ${m[1]} — 3 미만은 emit 전에 수정 패스를 돌아야 한다. 점수가 아니라 코드를 고쳐라`);
        }
      }
    }
    if (claimsFreyja4) add("A3", "pre-emit critique is recorded and clears 3 (Asgard)", f);
  }

  /* Asgard A4 — 균일 타일 격자: 같은 클래스의 카드 N장이 등폭 트랙에 늘어선 모양.
   *
   * 게이트 3 은 "아이콘 위 제목의 3열 격자"만 잡는다. 실측에서 슬롭으로 읽힌 것은 아이콘이
   * 없는 **2×2 등폭 카드 넷**이었다 — AI 채팅앱 환영 화면의 지문. 무게가 전부 같으면 그것은
   * 위계가 아니라 격자이고, 읽는 사람은 "생성된 화면"으로 읽는다. 스팬을 달리하거나,
   * 카드를 줄이거나, 글 한 줄로 바꿔라. */
  {
    const f = [];
    // `repeat(N, 1fr)` 와 `1fr 1fr` / `minmax(0,1fr) minmax(0,1fr)` 두 표기를 같은 것으로 본다
    const REPEAT_EQUAL = /repeat\(\s*([2-9])\s*,\s*(?:minmax\(\s*0\s*,\s*)?1fr/;
    const gridSelectors = [];
    for (const { r, d } of decls) {
      if (d.prop !== "grid-template-columns") continue;
      const v = tokens.resolve(d.value).trim();
      const repeated = v.match(REPEAT_EQUAL);
      if (repeated) { gridSelectors.push({ r, d, tracks: Number(repeated[1]) }); continue; }
      const tracks = v.split(/\s+(?![^(]*\))/).filter(Boolean);
      if (tracks.length >= 2 && tracks.every((t) => t === tracks[0] && /1fr/.test(t))) {
        gridSelectors.push({ r, d, tracks: tracks.length });
      }
    }
    if (gridSelectors.length && hasHtml) {
      const classOf = (n) => (n.attrs?.class || "").trim();
      for (const root of html) {
        for (const n of walk(root)) {
          const kids = n.children.filter((k) => k.tag && !/^(script|style|template)$/.test(k.tag));
          if (kids.length < 3) continue;
          const first = classOf(kids[0]);
          if (!first) continue;
          if (!kids.every((k) => classOf(k) === first)) continue;
          // 카드 모양인지: 자식마다 글을 나르는 요소가 둘 이상(제목 + 설명). 칩·내비 링크는
          // 한 덩어리라 여기서 걸리지 않는다 — 균일함 자체가 죄는 아니다.
          const cardish = kids.every((k) => k.children.filter((c) => c.tag).length >= 2);
          if (!cardish) continue;
          const holder = cls(n);
          const matched = gridSelectors.find(({ r }) =>
            r.selector.split(",").some((sel) => {
              const m = sel.trim().match(/\.([A-Za-z0-9_-]+)\s*$/);
              return m && holder.split(/\s+/).includes(m[1].toLowerCase());
            }));
          if (!matched) continue;
          f.push(`html:${n.line}  <${n.tag} class="${holder.slice(0, 28)}"> — 같은 클래스 카드 ${kids.length}장이 등폭 ${matched.tracks}열에 늘어섰다 (환영/기능 카드 지문)`);
        }
      }
    }
    add("A4", "no uniform tile grid — weight must differ (Asgard)", f, { na: !hasHtml });
  }

  return gates;
}

const MANUAL = [
  [6, "hero shape — centred-everything (needs the rendered hero)"],
  [8, "structural fingerprint vs. previous builds (needs project memory + judgment)"],
  [21, "Specimen fall-through (needs the brief)"],
  [23, "accent covers > ~5 % of the viewport (needs rendered area)"],
  [25, "prose measure in ch (needs computed text metrics)"],
  [28, "demo-video LCP behaviour (needs the media)"],
  [29, "abstract background footprint (needs rendered area)"],
  [32, "within-archetype knob deltas (needs project memory)"],
  [35, "decorative text effects land in the right vertical zone (visual)"],
  [36, "interactive bars vertically centred (visual)"],
  [39, "input-state discipline — five sub-checks (needs the form rendered)"],
  [40, "full contrast sweep against computed backgrounds (inherited surfaces)"],
  [42, "nav fingerprint vs. the archetype catalogue (judgment)"],
  [43, "footer fingerprint vs. the archetype catalogue (judgment)"],
  [44, "hero fits the fold at 1280×800 (rendered)"],
  [45, "decorative-without-purpose (needs the content's meaning)"],
  [46, "invented metric (needs to know what the user supplied)"],
  [49, "two-line clickable text (rendered at each width)"],
  [52, "per-theme section-head mobile collapse (rendered at 768px)"],
  [53, "radio-tab scroll-jump (needs interaction)"],
  [57, "studied DNA discarded for a catalog theme (needs conversation scope)"],
];

/* ────────────────────────────────  driver  ────────────────────────────── */

function collect(target, out) {
  const st = fs.statSync(target);
  if (st.isDirectory()) {
    for (const e of fs.readdirSync(target)) {
      if (e.startsWith(".") || e === "node_modules") continue;
      collect(path.join(target, e), out);
    }
    return out;
  }
  if (/\.(html?|css)$/i.test(target)) out.push(target);
  return out;
}

function loadBundle(targets) {
  const files = [];
  for (const t of targets) collect(path.resolve(t), files);
  const rules = [];
  const htmlRoots = [];
  let firstCssComment = null;
  let hasHtml = false;
  const seen = new Set();
  const readCss = (file, text) => {
    if (firstCssComment === null) {
      const c = text.match(/\/\*([\s\S]*?)\*\//);
      if (c && text.slice(0, c.index).trim() === "") firstCssComment = c[1].trim();
    }
    rules.push(...parseCss(text, file));
  };
  for (const file of files) {
    if (seen.has(file)) continue;
    seen.add(file);
    const text = fs.readFileSync(file, "utf8");
    if (/\.css$/i.test(file)) { readCss(file, text); continue; }
    hasHtml = true;
    const root = parseHtml(text);
    htmlRoots.push(root);
    for (const n of walk(root)) {
      if (n.tag === "style" && n.body) readCss(file, n.body);
      if (n.tag === "link" && /stylesheet/i.test(n.attrs.rel || "")) {
        const href = n.attrs.href || "";
        if (/^https?:|^\/\//.test(href) || !href) continue;
        const p = path.resolve(path.dirname(file), href.split("?")[0]);
        if (fs.existsSync(p) && !seen.has(p)) {
          seen.add(p);
          const t2 = fs.readFileSync(p, "utf8");
          files.push(p);
          readCss(p, t2);
        }
      }
    }
  }
  return { files: [...seen], rules, html: htmlRoots, firstCssComment, hasHtml };
}

function main(argv) {
  const targets = [];
  let genre = "editorial";
  let asJson = false;
  let report = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--genre") genre = (argv[++i] || "editorial").toLowerCase();
    else if (a === "--json") asJson = true;
    else if (a === "--report") report = true;
    else if (a === "-h" || a === "--help") {
      process.stdout.write("usage: slop_gate.mjs <file|dir> [...] [--genre editorial|modern-minimal|atmospheric|playful] [--json] [--report]\n");
      return 0;
    } else targets.push(a);
  }
  if (!targets.length) {
    process.stderr.write("slop_gate: no target given\n");
    return 2;
  }
  const bundle = loadBundle(targets);
  if (!bundle.files.length) {
    process.stderr.write("slop_gate: no .html or .css files under the given target\n");
    return 2;
  }
  const gates = judge(bundle, genre);
  const pass = gates.filter((g) => g.status === "pass");
  const fail = gates.filter((g) => g.status === "fail");
  const na = gates.filter((g) => g.status === "n/a");
  const payload = {
    target: targets,
    genre,
    files: bundle.files,
    gates,
    manual: MANUAL.map(([id, why]) => ({ id, why })),
    summary: { pass: pass.length, fail: fail.length, notApplicable: na.length, manual: MANUAL.length },
    verdict: fail.length ? "fail" : "pass",
  };

  if (report) {
    const dir = path.join(process.cwd(), ".asgard", ".vanadis", "engine4");
    fs.mkdirSync(dir, { recursive: true });
    const slug = path.basename(path.resolve(targets[0])).replace(/[^\w.-]/g, "-");
    const out = path.join(dir, `gate-${slug}.json`);
    fs.writeFileSync(out, JSON.stringify(payload, null, 2));
    if (!asJson) process.stdout.write(`report written: ${path.relative(process.cwd(), out)}\n`);
  }

  if (asJson) {
    process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
    return fail.length ? 1 : 0;
  }

  const lines = [];
  lines.push(`⠶ Freyja4 slop gate — genre ${genre} — ${bundle.files.length} file(s)`);
  for (const f of bundle.files) lines.push(`   ${path.relative(process.cwd(), f)}`);
  lines.push("");
  for (const g of gates) {
    const tag = g.status === "fail" ? "FAIL" : g.status === "n/a" ? "n/a " : "pass";
    lines.push(`  ${tag}  gate ${String(g.id).padEnd(3)} ${g.title}`);
    for (const d of g.findings) lines.push(`            ${d}`);
    if (g.truncated) lines.push(`            … ${g.truncated} more`);
    for (const n of g.notes || []) lines.push(`            note · ${n}`);
  }
  lines.push("");
  lines.push(`  unjudged (${MANUAL.length}) — these are yours, not passes:`);
  lines.push(`    ${MANUAL.map(([id]) => id).join(", ")}`);
  lines.push("");
  lines.push(`  ${pass.length} pass · ${fail.length} fail · ${na.length} not applicable · ${MANUAL.length} unjudged`);
  lines.push(`  verdict: ${payload.verdict.toUpperCase()}`);
  process.stdout.write(lines.join("\n") + "\n");
  return fail.length ? 1 : 0;
}

process.exit(main(process.argv.slice(2)));
