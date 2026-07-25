#!/usr/bin/env node
// shoot — 메시를 여러 방향에서 오프라인 렌더해 PNG 증거를 남긴다.
// 사용: node shoot.mjs <model.stl|obj|glb|gltf> [--out DIR] [--views front,top,iso] [--size 420]
//                     [--up z|y|auto] [--highlight overhang|thick|none] [--angle 45] [--json]
//                     [--thin MM]  (thick 하이라이트 임계 살두께, 기본 p05 자동)
import { mkdirSync, writeFileSync } from "node:fs";
import { basename, extname, join } from "node:path";
import { loadMesh } from "./core/mesh.mjs";
import { flatten, bounds, faces, buildGrid, wallThickness, overhangs, raycast } from "./core/geom.mjs";
import { render, contactSheet, toZUp, viewNames } from "./core/raster.mjs";
import { encodePng } from "./core/png.mjs";
import { parseArgs, fail, round } from "./core/cli.mjs";

const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json", "no-sheet"] });
if (!positional.length) fail("사용법: node shoot.mjs <model> [--out DIR] [--views front,top,iso] [--highlight overhang]");

const modelPath = positional[0];
const outDir = String(options.out || "shots");
const size = Math.max(120, Math.min(1600, Number(options.size || 420)));
const requested = String(options.views || "front,right,top,iso")
  .split(",")
  .map((name) => name.trim())
  .filter(Boolean);
const unknown = requested.filter((name) => !viewNames().includes(name));
if (unknown.length) fail(`알 수 없는 뷰: ${unknown.join(", ")} (가능: ${viewNames().join(", ")})`);

let mesh;
try {
  mesh = loadMesh(modelPath);
} catch (error) {
  fail(`모델을 읽지 못했다: ${modelPath} — ${error.message}`);
}
const flat = flatten(mesh.parts);
const upMode = String(options.up || "auto");
const isGltf = [".glb", ".gltf"].includes(extname(modelPath).toLowerCase());
const positions = upMode === "z" || (upMode === "auto" && !isGltf) ? flat.positions : toZUp(flat.positions);
const cache = faces(positions);
const box = bounds(positions);
const center = box.min.map((value, axis) => value + box.size[axis] / 2);
const radius = Math.max(1e-6, Math.hypot(...box.size) / 2);

let highlight = null;
let legend = "";
const mode = String(options.highlight || "none");
if (mode === "overhang") {
  const angle = Number(options.angle || 45);
  const limit = Math.cos((angle * Math.PI) / 180);
  const floor = box.min[2];
  highlight = (face) => {
    const n = cache.normals[face * 3 + 2];
    if (n >= 0 || -n <= limit) return null;
    const i = face * 9;
    const onPlate = [i, i + 3, i + 6].every((offset) => positions[offset + 2] - floor <= 1e-3);
    return onPlate ? null : [214, 96, 84];
  };
  legend = `overhang < ${angle}° marked red`;
} else if (mode === "thick") {
  const grid = buildGrid(positions, cache, box);
  const measured = wallThickness(positions, cache, grid, { samples: 1500 });
  const limit = Number(options.thin ?? round(measured.p05 ?? 0, 4));
  const epsilon = grid.cell * 1e-3;
  highlight = (face) => {
    const n = [cache.normals[face * 3], cache.normals[face * 3 + 1], cache.normals[face * 3 + 2]];
    const origin = [0, 1, 2].map((axis) => cache.centers[face * 3 + axis] - n[axis] * epsilon);
    const distance = raycast(positions, grid, origin, [-n[0], -n[1], -n[2]]);
    return Number.isFinite(distance) && distance <= limit ? [214, 96, 84] : null;
  };
  legend = `wall <= ${limit} marked red`;
}

mkdirSync(outDir, { recursive: true });
const stem = basename(modelPath, extname(modelPath));
const tiles = requested.map((view) => ({
  label: view,
  image: render({ positions, faceCache: cache, ranges: flat.ranges }, { view, size, radius, center, highlight }),
}));

const written = [];
for (const tile of tiles) {
  const path = join(outDir, `${stem}-${tile.label}.png`);
  writeFileSync(path, encodePng(tile.image.data, tile.image.width, tile.image.height));
  written.push(path);
}

let sheetPath = null;
if (!options["no-sheet"] && tiles.length > 1) {
  // glTF 는 규격상 미터 단위다 — 치수를 그대로 mm 로 읽지 않도록 단위를 함께 적는다.
  const unit = isGltf ? "m" : "mm";
  const dims = `${box.size.map((value) => round(value, 3)).join(" × ")} ${unit}`;
  const overhang = mode === "overhang" ? overhangs(positions, cache) : null;
  const subtitle = [
    `size ${dims}`,
    `tris ${flat.triangleCount}`,
    `parts ${flat.ranges.length}`,
    legend,
    overhang ? `overhang ${(overhang.overhangRatio * 100).toFixed(1)}%` : "",
  ]
    .filter(Boolean)
    .join("   ");
  const sheet = contactSheet(tiles, { title: stem, subtitle });
  sheetPath = join(outDir, `${stem}-sheet.png`);
  writeFileSync(sheetPath, encodePng(sheet.data, sheet.width, sheet.height));
}

const payload = {
  model: modelPath,
  triangles: flat.triangleCount,
  parts: flat.ranges.map((range) => range.name),
  bbox: { min: box.min.map((value) => round(value)), max: box.max.map((value) => round(value)), size: box.size.map((value) => round(value)) },
  upAxis: upMode === "auto" ? (isGltf ? "y→z" : "z") : upMode,
  highlight: mode,
  views: written,
  sheet: sheetPath,
  warnings: mesh.warnings,
};

if (options.json) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
} else {
  process.stdout.write(
    [
      `모델   ${modelPath}`,
      `치수   ${payload.bbox.size.join(" × ")}  (삼각형 ${flat.triangleCount}, 파트 ${flat.ranges.length})`,
      `뷰     ${written.join("\n       ")}`,
      sheetPath ? `시트   ${sheetPath}` : "",
      mesh.warnings.length ? `경고   ${mesh.warnings.join("; ")}` : "",
      "",
      "PNG 를 직접 열어서 형상을 확인하라. 열지 않았으면 확인한 것이 아니다.",
    ]
      .filter(Boolean)
      .join("\n") + "\n",
  );
}
