#!/usr/bin/env node
// snapshot — CAD 워크벤치 뷰. 작업 명세(JSON)를 받아 형상 대조용 렌더 증거를 낸다.
//
// 사용:
//   node snapshot.mjs --job shots.json
//   node snapshot.mjs model.step --out shots            (기본 4장 패킷)
//   node snapshot.mjs model.step --out shots --orbit 24 (궤도 GIF 추가)
//
// ## 이것이 shoot.mjs 와 다른 점
//
// `shoot.mjs` 는 면 법선만 셰이딩한다. 이 도구는 거기에 **특징 에지 라인워크**를 얹는다 —
// 실루엣과 접힘 모서리를 실제 선으로 그린다. 평면 위의 구멍 테두리, 모따기 경계, 리브의 능선처럼
// 셰이딩만으로는 사라지는 것들이 그 선에서만 보이고, 사람이 "요청한 물건이 맞는가"를 판정할 때
// 실제로 보는 것이 그것이다. 단면(clip)과 궤도 GIF 도 여기 있다.
//
// 브라우저도 GPU 도 헤드리스 크롬도 쓰지 않는다. node 내장만으로 돈다.
//
// ## 입력
//
// `.step` 을 주면 옆의 위상 산출물(`.<이름>.step.glb`)에서 메시를 읽는다. STEP 자체에는 삼각망이
// 없으므로 이것이 유일한 경로이고, 산출물이 없으면 그 사실을 말하고 종료한다 — 그릴 것이 없는데
// 빈 이미지를 내지 않는다.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join, resolve } from "node:path";
import { loadMesh } from "./core/mesh.mjs";
import { flatten, bounds, faces, featureEdges } from "./core/geom.mjs";
import { render, contactSheet, toZUp, viewNames } from "./core/raster.mjs";
import { encodePng } from "./core/png.mjs";
import { encodeGif } from "./core/gif.mjs";
import { parseArgs, fail, round } from "./core/cli.mjs";

const SIZE_PROFILES = { thumb: 260, review: 420, diagnostic: 640, large: 900 };
const DEFAULT_PACKET = ["iso", "front", "top", "right"];

const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json", "no-sheet", "no-edges"] });

const job = options.job ? readJob(String(options.job)) : null;
const inputPath = job ? job.input : positional[0];
if (!inputPath) {
  fail("사용법: node snapshot.mjs --job shots.json  |  node snapshot.mjs <model> [--out DIR] [--orbit N]");
}

const modelPath = resolve(String(inputPath));
const outDir = String(options.out || (job?.outDir ?? "shots"));
const renderOptions = job?.render ?? {};
const size = SIZE_PROFILES[String(renderOptions.sizeProfile || "review")] || Number(options.size) || 420;
const drawEdges = !options["no-edges"] && renderOptions.edges !== false;
const creaseAngle = Number(renderOptions.creaseAngle ?? options.crease ?? 24);

// ── 메시 확보 ────────────────────────────────────────────────────────────────
const meshPath = resolveMeshPath(modelPath);
let scene;
try {
  const loaded = loadMesh(meshPath);
  const flat = flatten(loaded.parts);
  const positions = extname(meshPath).toLowerCase() === ".glb" || extname(meshPath).toLowerCase() === ".gltf"
    ? toZUp(flat.positions)
    : flat.positions;
  scene = { positions, ranges: flat.ranges, faceCache: faces(positions) };
} catch (error) {
  fail(`메시를 읽지 못했다: ${meshPath}\n  ${error.message}`, 3);
}

const box = bounds(scene.positions);
const center = [
  (box.min[0] + box.max[0]) / 2,
  (box.min[1] + box.max[1]) / 2,
  (box.min[2] + box.max[2]) / 2,
];
const radius = Math.max(...box.size) / 2 || 1;
const padding = Number(renderOptions.padding ?? 0.12);
const edges = drawEdges ? featureEdges(scene.positions, scene.faceCache, { angle: creaseAngle }) : null;

mkdirSync(outDir, { recursive: true });

// ── 출력 목록 ────────────────────────────────────────────────────────────────
const outputs = job?.outputs?.length
  ? job.outputs
  : DEFAULT_PACKET.map((camera) => ({ path: join(outDir, `${stem(modelPath)}-${camera}.png`), camera }));

const written = [];
const tiles = [];
for (const entry of outputs) {
  const view = normalizeCamera(entry.camera);
  const image = render(scene, {
    view,
    size,
    radius: radius * (1 + padding),
    center,
    edges,
    clip: entry.section ?? entry.clip ?? null,
  });
  const target = resolve(String(entry.path));
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, encodePng(image.data, image.width, image.height));
  written.push(target);
  tiles.push({ image, label: labelFor(entry) });
}

// ── 궤도 GIF ─────────────────────────────────────────────────────────────────
let orbitPath = null;
const orbitSteps = Number(options.orbit ?? job?.orbit ?? 0);
if (orbitSteps >= 4) {
  const frames = [];
  for (let step = 0; step < orbitSteps; step += 1) {
    const angle = (step / orbitSteps) * Math.PI * 2;
    frames.push(
      render(scene, {
        view: { direction: [-Math.cos(angle), Math.sin(angle), -0.55], up: [0, 0, 1] },
        size,
        radius: radius * (1 + padding),
        center,
        edges,
      }),
    );
  }
  orbitPath = join(outDir, `${stem(modelPath)}-orbit.gif`);
  writeFileSync(orbitPath, encodeGif(frames, { delay: 8 }));
  written.push(resolve(orbitPath));
}

// ── 컨택트 시트 ──────────────────────────────────────────────────────────────
let sheetPath = null;
if (!options["no-sheet"] && tiles.length > 1) {
  const sheet = contactSheet(tiles, {
    title: stem(modelPath),
    // 시트의 비트맵 글꼴은 ASCII 만 갖는다 — 한글 라벨을 넣으면 글자가 통째로 빈칸이 된다.
    subtitle: `${round(box.size[0], 2)} x ${round(box.size[1], 2)} x ${round(box.size[2], 2)} mm  -  TRI ${scene.faceCache.count}  -  EDGE ${edges ? edges.length / 6 : 0}`,
  });
  sheetPath = join(outDir, `${stem(modelPath)}-sheet.png`);
  writeFileSync(sheetPath, encodePng(sheet.data, sheet.width, sheet.height));
  written.push(resolve(sheetPath));
}

const payload = {
  model: modelPath,
  mesh: meshPath,
  size: box.size.map((value) => round(value, 3)),
  triangles: scene.faceCache.count,
  featureEdges: edges ? edges.length / 6 : 0,
  outputs: written,
  sheet: sheetPath,
  orbit: orbitPath,
};

if (options.json) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
} else {
  const lines = [
    `모델   ${modelPath}`,
    `메시   ${meshPath}`,
    `치수   ${payload.size.join(" x ")} mm  (삼각형 ${payload.triangles}, 특징에지 ${payload.featureEdges})`,
  ];
  for (const path of written) lines.push(`뷰     ${path}`);
  lines.push("PNG 를 직접 열어서 형상을 확인하라. 열지 않았으면 확인한 것이 아니다.");
  process.stdout.write(`${lines.join("\n")}\n`);
}

// ─────────────────────────────────────────────────────────────────────────────

function readJob(path) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    fail(`작업 명세를 읽지 못했다: ${path}\n  ${error.message}`);
  }
  if (!parsed.input) fail("작업 명세에 `input` 이 없다.");
  return parsed;
}

/**
 * STEP 은 삼각망을 갖고 있지 않다. 옆의 위상 산출물이 유일한 렌더 경로이고,
 * 없으면 그 사실을 말하고 죽는다 — 그릴 것이 없는데 빈 이미지를 내지 않는다.
 */
function resolveMeshPath(path) {
  const extension = extname(path).toLowerCase();
  if (extension !== ".step" && extension !== ".stp") return path;
  const sidecar = join(dirname(path), `.${basename(path, extension)}.step.glb`);
  try {
    readFileSync(sidecar);
  } catch {
    fail(
      `위상 산출물이 없다: ${sidecar}\n` +
        "STEP 에는 삼각망이 없어 이것 없이는 그릴 수 없다. `python cad.py step <소스>` 로 생성하라.",
      3,
    );
  }
  return sidecar;
}

function normalizeCamera(camera) {
  if (!camera) return "iso";
  if (typeof camera === "string") {
    if (!viewNames().includes(camera)) fail(`모르는 뷰 이름이다: ${camera} (${viewNames().join(", ")})`);
    return camera;
  }
  if (Array.isArray(camera.direction) && camera.direction.length === 3) return { direction: camera.direction, up: camera.up };
  fail(`카메라 명세를 읽지 못했다: ${JSON.stringify(camera)}`);
}

function labelFor(entry) {
  if (typeof entry.camera === "string") return entry.camera;
  if (entry.label) return String(entry.label);
  return basename(String(entry.path), extname(String(entry.path)));
}

function stem(path) {
  return basename(path, extname(path));
}
