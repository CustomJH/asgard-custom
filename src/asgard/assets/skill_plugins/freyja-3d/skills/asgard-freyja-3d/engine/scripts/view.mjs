#!/usr/bin/env node
// view — 로컬 리뷰 서버. 산출물을 브라우저에서 돌려보게 한다.
//
// 사용:
//   node view.mjs --port 4178                     그리고 http://127.0.0.1:4178/?dir=<절대경로>
//   node view.mjs --dir build --port 4178         기본 디렉터리를 미리 지정
//
// ## 왜 3D 라이브러리를 싣지 않는가
//
// 이전 판의 뷰어는 3.1MB 짜리 three.js 번들을 브라우저로 내려보냈다. 그것이 사는 대가는 셋이었다:
// 저장소에 들어가는 빌드 산출물(우리가 고칠 수 없는 바이트), WebGL 이 없는 환경에서의 전면 실패,
// 그리고 상류 개발 트리에만 있던 런처 때문에 문서대로 하면 안 뜨는 기동 절차.
//
// 여기서는 **서버가 그린다.** 렌더는 이미 우리 것이다(core/raster.mjs) — 오프라인 래스터라이저가
// 스냅샷에 쓰는 바로 그 코드다. 브라우저는 `<img>` 를 바꿔 다는 일만 하므로 자바스크립트 의존이
// 없고, WebGL 도 필요 없고, 내려보내는 페이지가 한 파일이다.
//
// 대가도 정직하게 적는다: 각도를 바꿀 때마다 왕복이 한 번 생긴다. 로컬호스트에서 수십 밀리초라
// 리뷰용으로는 문제되지 않지만, 60fps 로 굴리는 뷰어가 아니다. **뷰어는 편의이지 검증이 아니다** —
// 검증의 본체는 `inspect` 의 측정값과 `snapshot` 의 렌더 증거다.

import { createServer } from "node:http";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, dirname, extname, join, resolve, sep } from "node:path";
import { loadMesh } from "./core/mesh.mjs";
import { flatten, bounds, faces, featureEdges } from "./core/geom.mjs";
import { render, toZUp } from "./core/raster.mjs";
import { encodePng } from "./core/png.mjs";
import { parseArgs } from "./core/cli.mjs";

const VIEWABLE = new Set([".glb", ".gltf", ".stl", ".obj", ".3mf", ".step", ".stp"]);
const TEXT = new Set([".dxf", ".gcode", ".urdf", ".srdf", ".sdf", ".json", ".py", ".md"]);
const CACHE = new Map(); // 경로 → { mtimeMs, scene, box, center, radius, edges }

const { options } = parseArgs(process.argv.slice(2), {});
const port = Number(options.port || 4178);
const host = String(options.host || "127.0.0.1");
const rootDefault = options.dir ? resolve(String(options.dir)) : process.cwd();

const server = createServer((request, response) => {
  let url;
  try {
    url = new URL(request.url, `http://${host}:${port}`);
  } catch {
    return send(response, 400, "text/plain", "잘못된 URL");
  }

  if (url.pathname === "/__cad/server") {
    return json(response, 200, { schemaVersion: 1, app: "asgard-freyja-3d-view", root: rootDefault, ready: true });
  }
  if (url.pathname === "/__cad/render") return renderEndpoint(url, response);
  if (url.pathname === "/__cad/raw") return rawEndpoint(url, response);
  return send(response, 200, "text/html; charset=utf-8", page(url));
});

server.on("error", (error) => {
  process.stderr.write(
    `뷰어를 띄우지 못했다: ${error.message}\n` +
      "포트가 점유됐으면 --port 로 다른 번호를 주라. 샌드박스에서 로컬 바인딩이 막히는 것도 흔한 일이고,\n" +
      "그때는 띄우지 못했다고 보고하고 inspect 측정과 snapshot 렌더로 검증을 마친다.\n",
  );
  process.exit(3);
});

server.listen(port, host, () => {
  process.stdout.write(
    `뷰어  http://${host}:${port}/?dir=${encodeURIComponent(rootDefault)}\n` +
      `준비 확인  curl -s http://${host}:${port}/__cad/server\n` +
      "사용자가 요청하지 않으면 이 서버를 끄지 않는다 — 다른 세션이 쓰고 있을 수 있다.\n",
  );
});

// ─────────────────────────────────────────────────────────────────────────────

/** 디렉터리 탈출 방어. 요청된 경로가 dir 안에 실제로 있는지 확인한 뒤에만 연다. */
function safeJoin(root, relative) {
  const target = resolve(root, relative || ".");
  const base = resolve(root);
  if (target !== base && !target.startsWith(base + sep)) return null;
  return target;
}

function loadScene(path) {
  const stat = statSync(path);
  const cached = CACHE.get(path);
  if (cached && cached.mtimeMs === stat.mtimeMs) return cached;

  const extension = extname(path).toLowerCase();
  let meshPath = path;
  if (extension === ".step" || extension === ".stp") {
    meshPath = join(dirname(path), `.${basename(path, extension)}.step.glb`);
    statSync(meshPath); // 없으면 던진다 — 호출부가 사유를 표시한다
  }
  const loaded = loadMesh(meshPath);
  const flat = flatten(loaded.parts);
  const meshExtension = extname(meshPath).toLowerCase();
  const positions = meshExtension === ".glb" || meshExtension === ".gltf" ? toZUp(flat.positions) : flat.positions;
  const faceCache = faces(positions);
  const box = bounds(positions);
  const entry = {
    mtimeMs: stat.mtimeMs,
    scene: { positions, ranges: flat.ranges, faceCache },
    box,
    center: [(box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2],
    radius: Math.max(...box.size) / 2 || 1,
    edges: featureEdges(positions, faceCache, { angle: 24 }),
    meshPath,
  };
  CACHE.set(path, entry);
  return entry;
}

function renderEndpoint(url, response) {
  const root = url.searchParams.get("dir") || rootDefault;
  const file = url.searchParams.get("file") || "";
  const target = safeJoin(root, file);
  if (!target) return send(response, 403, "text/plain", "디렉터리 밖 경로");

  let entry;
  try {
    entry = loadScene(target);
  } catch (error) {
    return send(response, 404, "text/plain", `열지 못했다: ${error.message}`);
  }

  const yaw = (Number(url.searchParams.get("yaw") || 35) * Math.PI) / 180;
  const pitch = (Number(url.searchParams.get("pitch") || 25) * Math.PI) / 180;
  const size = Math.max(200, Math.min(1400, Number(url.searchParams.get("size") || 640)));
  const section = url.searchParams.get("section");

  const image = render(entry.scene, {
    view: {
      direction: [-Math.cos(yaw) * Math.cos(pitch), Math.sin(yaw) * Math.cos(pitch), -Math.sin(pitch)],
      up: [0, 0, 1],
    },
    size,
    radius: entry.radius * 1.15,
    center: entry.center,
    edges: entry.edges,
    clip: section ? { axis: section, at: entry.center[{ x: 0, y: 1, z: 2 }[section] ?? 2], keep: "min" } : null,
  });
  send(response, 200, "image/png", Buffer.from(encodePng(image.data, image.width, image.height)), true);
}

function rawEndpoint(url, response) {
  const root = url.searchParams.get("dir") || rootDefault;
  const target = safeJoin(root, url.searchParams.get("file") || "");
  if (!target) return send(response, 403, "text/plain", "디렉터리 밖 경로");
  try {
    send(response, 200, "text/plain; charset=utf-8", readCapped(target));
  } catch (error) {
    send(response, 404, "text/plain", `열지 못했다: ${error.message}`);
  }
}

/** 큰 파일이 브라우저를 멈추게 하지 않도록 앞부분만 보낸다 — 잘렸다는 사실은 표시한다. */
function readCapped(target) {
  const LIMIT = 512 * 1024;
  const stat = statSync(target);
  const raw = readFileSync(target);
  return raw.subarray(0, LIMIT).toString("utf8") + (stat.size > LIMIT ? "\n… (잘렸다)" : "");
}

function catalog(root) {
  let entries;
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch {
    return { viewable: [], text: [], error: `디렉터리를 읽지 못했다: ${root}` };
  }
  const viewable = [];
  const text = [];
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const extension = extname(entry.name).toLowerCase();
    // 위상 산출물은 증거이지 납품물이 아니다 — 목록에서 감춘다(STEP 을 열면 자동으로 쓰인다).
    if (entry.name.startsWith(".") || entry.name.endsWith(".step.glb")) continue;
    if (VIEWABLE.has(extension)) viewable.push(entry.name);
    else if (TEXT.has(extension)) text.push(entry.name);
  }
  return { viewable: viewable.sort(), text: text.sort(), error: null };
}

function page(url) {
  const root = url.searchParams.get("dir") || rootDefault;
  const file = url.searchParams.get("file") || "";
  const { viewable, text, error } = catalog(root);
  const link = (name) => `/?dir=${encodeURIComponent(root)}&file=${encodeURIComponent(name)}`;
  const isMesh = file && VIEWABLE.has(extname(file).toLowerCase());

  const list = (title, names) =>
    names.length
      ? `<h2>${title}</h2><ul>${names
          .map((name) => `<li><a href="${link(name)}"${name === file ? ' class="on"' : ""}>${escape(name)}</a></li>`)
          .join("")}</ul>`
      : "";

  const stage = !file
    ? `<p class="hint">왼쪽에서 파일을 고르라. 디렉터리를 바꾸려면 <code>?dir=</code> 에 절대경로를 준다.</p>`
    : isMesh
      ? `<div class="stage">
           <img id="shot" src="/__cad/render?dir=${encodeURIComponent(root)}&file=${encodeURIComponent(file)}" alt="${escape(file)}">
           <div class="ctl">
             <label>회전 <input id="yaw" type="range" min="0" max="359" value="35"></label>
             <label>고도 <input id="pitch" type="range" min="-85" max="85" value="25"></label>
             <label>단면
               <select id="section"><option value="">없음</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select>
             </label>
           </div>
         </div>
         <script>
           const shot = document.getElementById("shot");
           const base = "/__cad/render?dir=${encodeURIComponent(root)}&file=${encodeURIComponent(file)}";
           const update = () => {
             const s = document.getElementById("section").value;
             shot.src = base + "&yaw=" + yaw.value + "&pitch=" + pitch.value + (s ? "&section=" + s : "");
           };
           for (const id of ["yaw", "pitch", "section"]) document.getElementById(id).addEventListener("input", update);
         </script>`
      : `<pre id="text">불러오는 중…</pre>
         <script>
           fetch("/__cad/raw?dir=${encodeURIComponent(root)}&file=${encodeURIComponent(file)}")
             .then((r) => r.text()).then((t) => { document.getElementById("text").textContent = t; });
         </script>`;

  return `<!doctype html><meta charset="utf-8"><title>${escape(file || basename(root))} · Freyja 3D</title>
<style>
 :root{color-scheme:dark}
 body{margin:0;display:grid;grid-template-columns:260px 1fr;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#14161a;color:#dfe3e8}
 nav{padding:16px;border-right:1px solid #262a31;overflow:auto;height:100vh;box-sizing:border-box}
 nav h1{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#7d8794;margin:0 0 4px}
 nav h2{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#7d8794;margin:18px 0 6px}
 nav p.dir{font-size:11px;color:#5e6672;word-break:break-all;margin:0 0 8px}
 ul{list-style:none;padding:0;margin:0}
 li a{display:block;padding:3px 6px;border-radius:4px;color:#c3c9d2;text-decoration:none;word-break:break-all}
 li a:hover{background:#1e222a}
 li a.on{background:#2b323d;color:#fff}
 main{padding:20px;overflow:auto;height:100vh;box-sizing:border-box}
 .stage img{max-width:100%;border:1px solid #262a31;border-radius:6px;background:#181a1f}
 .ctl{display:flex;gap:20px;flex-wrap:wrap;margin-top:14px;align-items:center;color:#98a0ac}
 .ctl input[type=range]{width:200px;vertical-align:middle}
 pre{white-space:pre-wrap;word-break:break-word;background:#181a1f;border:1px solid #262a31;border-radius:6px;padding:14px}
 .hint,.err{color:#7d8794}
 code{color:#b7c0cc}
</style>
<nav>
  <h1>Freyja 3D</h1>
  <p class="dir">${escape(root)}</p>
  ${error ? `<p class="err">${escape(error)}</p>` : ""}
  ${list("형상", viewable)}
  ${list("문서", text)}
</nav>
<main>${stage}</main>`;
}

function escape(value) {
  return String(value).replace(/[&<>"']/g, (character) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
  );
}

function send(response, status, type, body, binary = false) {
  response.writeHead(status, { "content-type": type, "cache-control": "no-store" });
  response.end(binary ? body : String(body));
}

function json(response, status, payload) {
  send(response, status, "application/json", JSON.stringify(payload));
}
