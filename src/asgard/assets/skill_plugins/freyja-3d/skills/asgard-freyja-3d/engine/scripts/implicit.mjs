#!/usr/bin/env node
// implicit — 부호 거리장(SDF)을 메시로 내리고 렌더 증거를 남긴다.
//
// 사용:
//   node implicit.mjs model.implicit.mjs --out build            # STL + 렌더
//   node implicit.mjs model.implicit.mjs --res 96 --out build
//   node implicit.mjs model.implicit.mjs --json
//
// ## 필드를 GLSL 이 아니라 자바스크립트로 적는 이유
//
// 이전 판의 암시 모델은 GLSL 문자열이었다. 브라우저 레이마처가 유일한 실행체였기 때문이다.
// 그 실행체가 빠진 지금 GLSL 을 고집할 이유가 없다 — 오히려 셋을 잃는다. 필드를 노드에서
// 평가할 수 없어 메시로 내리려면 브라우저가 필요했고, 문법 오류가 런타임까지 안 잡혔고,
// 값을 하나 찍어 보는 일조차 불가능했다.
//
// 여기서는 필드가 그냥 함수다:
//
//   export default {
//     schema: "implicit/1.0",
//     name: "rounded capsule block",
//     bounds: { min: [-40, -25, -25], max: [40, 25, 25] },   // 선택
//     resolution: 64,                                        // 선택
//     sdf(x, y, z) {
//       const sphere = Math.hypot(x, y, z) - 22;
//       const block  = box(x, y, z, 34, 18, 18);
//       return unionRound(sphere, block, 3);
//     },
//   };
//
// 헬퍼는 이 파일이 `--helpers` 로 찍어 준다. 필드가 함수라서 노드에서 바로 평가되고,
// 메싱·렌더·감사가 전부 설치 없이 돈다.
//
// ## 메싱 — 나이브 서피스 넷
//
// 마칭 큐브가 아니라 서피스 넷을 쓴다. 부호가 바뀌는 셀마다 정점을 하나 두고 이웃과 잇는
// 방식이라 표가 거의 없고, 출력이 수밀 매니폴드로 나온다. **정확도는 격자 해상도가 전부다** —
// 얇은 벽과 날카로운 모서리는 뭉갠다. 이 사실은 보고에 그대로 적는다.

import { mkdirSync, writeFileSync } from "node:fs";
import { basename, extname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { flatten, bounds as meshBounds, faces, featureEdges, topology } from "./core/geom.mjs";
import { render, contactSheet } from "./core/raster.mjs";
import { encodePng } from "./core/png.mjs";
import { parseArgs, fail, round } from "./core/cli.mjs";

const HELPERS = `// implicit 필드 헬퍼 — 모델 파일에 복사해 쓰거나 직접 적는다.
const box = (x, y, z, hx, hy, hz) => {
  const dx = Math.abs(x) - hx, dy = Math.abs(y) - hy, dz = Math.abs(z) - hz;
  const outside = Math.hypot(Math.max(dx, 0), Math.max(dy, 0), Math.max(dz, 0));
  return outside + Math.min(Math.max(dx, dy, dz), 0);
};
const sphere = (x, y, z, r) => Math.hypot(x, y, z) - r;
const cylinderZ = (x, y, z, r, h) => {
  const d = Math.hypot(x, y) - r, c = Math.abs(z) - h;
  return Math.min(Math.max(d, c), 0) + Math.hypot(Math.max(d, 0), Math.max(c, 0));
};
const union = (a, b) => Math.min(a, b);
const subtract = (a, b) => Math.max(a, -b);
const intersect = (a, b) => Math.max(a, b);
const unionRound = (a, b, k) => {
  const h = Math.max(k - Math.abs(a - b), 0) / k;
  return Math.min(a, b) - h * h * k * 0.25;
};
// 자이로이드(TPMS) — 주기 p, 두께 t
const gyroid = (x, y, z, p, t) => {
  const s = (2 * Math.PI) / p;
  return Math.abs(Math.sin(x * s) * Math.cos(y * s) + Math.sin(y * s) * Math.cos(z * s) + Math.sin(z * s) * Math.cos(x * s)) - t;
};
`;

const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json", "helpers", "no-render"] });

if (options.helpers) {
  process.stdout.write(HELPERS);
  process.exit(0);
}
if (!positional.length) {
  fail("사용법: node implicit.mjs <model.implicit.mjs> [--out DIR] [--res N] [--json] [--helpers]");
}

const modelPath = resolve(positional[0]);
const outDir = String(options.out || "build");
const model = await loadModel(modelPath);

const resolution = clampInt(options.res ?? model.resolution ?? 64, 16, 256);
const box = normalizeBounds(model.bounds) ?? (await estimateBounds(model.sdf));
const mesh = surfaceNets(model.sdf, box, resolution);

if (!mesh.triangleCount) {
  fail(
    "표면을 찾지 못했다 — 격자 안에서 부호가 한 번도 바뀌지 않았다.\n" +
      "  bounds 가 형상을 벗어났거나, sdf 가 어디서나 같은 부호다. bounds 를 명시하거나 --res 를 올려라.",
    1,
  );
}

mkdirSync(outDir, { recursive: true });
const stem = basename(modelPath).replace(/\.implicit\.(mjs|js)$/i, "").replace(extname(modelPath), "");
const stlPath = join(outDir, `${stem}.stl`);
writeFileSync(stlPath, binaryStl(mesh.positions));

// ── 감사 ─────────────────────────────────────────────────────────────────────
const cache = faces(mesh.positions);
const shape = meshBounds(mesh.positions);
const shell = topology(mesh.positions, Math.max(...shape.size) * 1e-6);
const written = [stlPath];

// ── 렌더 증거 ────────────────────────────────────────────────────────────────
let sheetPath = null;
if (!options["no-render"]) {
  const scene = { positions: mesh.positions, ranges: [{ name: stem, start: 0, count: cache.count }], faceCache: cache };
  const center = [
    (shape.min[0] + shape.max[0]) / 2,
    (shape.min[1] + shape.max[1]) / 2,
    (shape.min[2] + shape.max[2]) / 2,
  ];
  const radius = (Math.max(...shape.size) / 2 || 1) * 1.12;
  const edges = featureEdges(mesh.positions, cache, { angle: 42 }); // SDF 표면은 매끄러워 문턱을 높인다
  const tiles = ["iso", "front", "top", "right"].map((view) => ({
    label: view,
    image: render(scene, { view, size: 420, radius, center, edges }),
  }));
  for (const tile of tiles) {
    const target = join(outDir, `${stem}-${tile.label}.png`);
    writeFileSync(target, encodePng(tile.image.data, tile.image.width, tile.image.height));
    written.push(target);
  }
  const sheet = contactSheet(tiles, {
    title: stem,
    subtitle: `${round(shape.size[0], 2)} x ${round(shape.size[1], 2)} x ${round(shape.size[2], 2)} mm  -  RES ${resolution}  -  TRI ${cache.count}`,
  });
  sheetPath = join(outDir, `${stem}-sheet.png`);
  writeFileSync(sheetPath, encodePng(sheet.data, sheet.width, sheet.height));
  written.push(sheetPath);
}

const cellSize = Math.max(...box.size) / resolution;
const payload = {
  model: modelPath,
  name: model.name || stem,
  bounds: { min: box.min, max: box.max },
  resolution,
  cellSizeMm: round(cellSize, 4),
  size: shape.size.map((value) => round(value, 3)),
  triangles: cache.count,
  watertight: shell.watertight,
  boundaryEdges: shell.boundaryEdges,
  outputs: written,
  sheet: sheetPath,
  caveat:
    `격자 ${resolution}³ 로 근사한 메시다. 셀 한 칸이 ${round(cellSize, 3)}mm 이므로 그보다 얇은 벽과 ` +
    "날카로운 모서리는 뭉갠다. 이 메시를 '치수가 맞는 모델'이라고 부르지 않는다.",
};

if (options.json) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
} else {
  const lines = [
    `모델   ${modelPath}`,
    `격자   ${resolution}³  (셀 ${payload.cellSizeMm}mm)`,
    `치수   ${payload.size.join(" x ")} mm  (삼각형 ${payload.triangles})`,
    `수밀   ${shell.watertight ? "예" : `아니오 — 경계 에지 ${shell.boundaryEdges}개`}`,
  ];
  for (const path of written) lines.push(`산출   ${path}`);
  lines.push("");
  lines.push(`주의   ${payload.caveat}`);
  lines.push("셀렉터 검증(measure·align·frame)이 이 레인에는 없다. 렌더를 직접 열고, 제조 주장은 하지 않는다.");
  process.stdout.write(`${lines.join("\n")}\n`);
}

// ─────────────────────────────────────────────────────────────────────────────

async function loadModel(path) {
  let module_;
  try {
    module_ = await import(pathToFileURL(path).href);
  } catch (error) {
    fail(`모델을 읽지 못했다: ${path}\n  ${error.message}`, 2);
  }
  const value = module_.default ?? module_;
  if (typeof value?.sdf !== "function") {
    fail(
      "모델이 `sdf(x, y, z)` 함수를 내보내지 않았다.\n" +
        "  기본 내보내기에 { schema, name, sdf, bounds?, resolution? } 를 두라. 헬퍼는 --helpers 로 본다.",
      2,
    );
  }
  return value;
}

function clampInt(value, low, high) {
  const parsed = Math.round(Number(value));
  return Number.isFinite(parsed) ? Math.min(high, Math.max(low, parsed)) : low;
}

function normalizeBounds(value) {
  if (!value || !Array.isArray(value.min) || !Array.isArray(value.max)) return null;
  const min = value.min.map(Number);
  const max = value.max.map(Number);
  if (min.length !== 3 || max.length !== 3 || min.some((v) => !Number.isFinite(v)) || max.some((v) => !Number.isFinite(v))) {
    return null;
  }
  return { min, max, size: [max[0] - min[0], max[1] - min[1], max[2] - min[2]] };
}

/**
 * bounds 를 안 주면 원점에서 밖으로 넓혀 가며 표면이 들어오는 상자를 찾는다.
 * SDF 값 자체가 거리이므로 원점 값이 상자 크기의 하한을 준다.
 */
async function estimateBounds(sdf) {
  let extent = Math.max(1, Math.abs(sdf(0, 0, 0)) * 2);
  for (let attempt = 0; attempt < 12; attempt += 1) {
    let inside = false;
    let outside = false;
    const steps = 8;
    for (let i = 0; i <= steps && !(inside && outside); i += 1) {
      for (let j = 0; j <= steps && !(inside && outside); j += 1) {
        for (let k = 0; k <= steps && !(inside && outside); k += 1) {
          const x = -extent + (2 * extent * i) / steps;
          const y = -extent + (2 * extent * j) / steps;
          const z = -extent + (2 * extent * k) / steps;
          if (sdf(x, y, z) <= 0) inside = true;
          else outside = true;
        }
      }
    }
    if (inside && outside) {
      const pad = extent * 0.08;
      return {
        min: [-extent - pad, -extent - pad, -extent - pad],
        max: [extent + pad, extent + pad, extent + pad],
        size: [2 * (extent + pad), 2 * (extent + pad), 2 * (extent + pad)],
      };
    }
    extent *= inside ? 2 : 1.8;
  }
  fail("bounds 를 추정하지 못했다 — 모델에 bounds 를 명시하라.", 1);
}

/**
 * 나이브 서피스 넷. 부호가 바뀌는 셀마다 정점 하나를 에지 교차점의 평균에 두고,
 * 부호가 바뀌는 격자 에지마다 그 에지를 공유하는 네 셀의 정점을 사각형으로 잇는다.
 * 사각형은 삼각형 둘로 낸다(우리 파이프라인 전체가 삼각형 수프를 받는다).
 */
function surfaceNets(sdf, box, resolution) {
  const n = resolution;
  const step = [box.size[0] / n, box.size[1] / n, box.size[2] / n];
  const at = (i, j, k) => [box.min[0] + i * step[0], box.min[1] + j * step[1], box.min[2] + k * step[2]];

  // 격자점 표본. (n+1)³ 을 한 번만 계산한다 — sdf 호출이 이 알고리즘의 비용 전부다.
  const side = n + 1;
  const field = new Float64Array(side * side * side);
  const sample = (i, j, k) => field[(k * side + j) * side + i];
  for (let k = 0; k < side; k += 1) {
    for (let j = 0; j < side; j += 1) {
      for (let i = 0; i < side; i += 1) {
        const [x, y, z] = at(i, j, k);
        field[(k * side + j) * side + i] = Number(sdf(x, y, z));
      }
    }
  }

  const CORNERS = [
    [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],
    [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1],
  ];
  const CELL_EDGES = [
    [0, 1], [2, 3], [4, 5], [6, 7],
    [0, 2], [1, 3], [4, 6], [5, 7],
    [0, 4], [1, 5], [2, 6], [3, 7],
  ];

  const vertexIndex = new Int32Array(n * n * n).fill(-1);
  const vertices = [];
  for (let k = 0; k < n; k += 1) {
    for (let j = 0; j < n; j += 1) {
      for (let i = 0; i < n; i += 1) {
        const values = CORNERS.map(([di, dj, dk]) => sample(i + di, j + dj, k + dk));
        let negative = 0;
        for (const value of values) if (value <= 0) negative += 1;
        if (negative === 0 || negative === 8) continue;

        let sx = 0;
        let sy = 0;
        let sz = 0;
        let hits = 0;
        for (const [a, b] of CELL_EDGES) {
          const va = values[a];
          const vb = values[b];
          if (va <= 0 === vb <= 0) continue;
          const t = va / (va - vb);
          const ca = CORNERS[a];
          const cb = CORNERS[b];
          sx += (ca[0] + (cb[0] - ca[0]) * t) * step[0];
          sy += (ca[1] + (cb[1] - ca[1]) * t) * step[1];
          sz += (ca[2] + (cb[2] - ca[2]) * t) * step[2];
          hits += 1;
        }
        const origin = at(i, j, k);
        vertexIndex[(k * n + j) * n + i] = vertices.length / 3;
        vertices.push(origin[0] + sx / hits, origin[1] + sy / hits, origin[2] + sz / hits);
      }
    }
  }

  // 부호가 바뀌는 격자 에지마다 사각형 하나. 축별로 이웃 셀 넷의 정점을 모은다.
  const out = [];
  const cellVertex = (i, j, k) => {
    if (i < 0 || j < 0 || k < 0 || i >= n || j >= n || k >= n) return -1;
    return vertexIndex[(k * n + j) * n + i];
  };
  const emitQuad = (a, b, c, d, flip) => {
    if (a < 0 || b < 0 || c < 0 || d < 0) return;
    const order = flip ? [a, c, b, a, d, c] : [a, b, c, a, c, d];
    for (const index of order) out.push(vertices[index * 3], vertices[index * 3 + 1], vertices[index * 3 + 2]);
  };

  for (let k = 0; k < side; k += 1) {
    for (let j = 0; j < side; j += 1) {
      for (let i = 0; i < side; i += 1) {
        const here = sample(i, j, k) <= 0;
        if (i + 1 < side && here !== sample(i + 1, j, k) <= 0) {
          emitQuad(cellVertex(i, j - 1, k - 1), cellVertex(i, j, k - 1), cellVertex(i, j, k), cellVertex(i, j - 1, k), here);
        }
        if (j + 1 < side && here !== sample(i, j + 1, k) <= 0) {
          emitQuad(cellVertex(i - 1, j, k - 1), cellVertex(i, j, k - 1), cellVertex(i, j, k), cellVertex(i - 1, j, k), !here);
        }
        if (k + 1 < side && here !== sample(i, j, k + 1) <= 0) {
          emitQuad(cellVertex(i - 1, j - 1, k), cellVertex(i, j - 1, k), cellVertex(i, j, k), cellVertex(i - 1, j, k), here);
        }
      }
    }
  }
  return { positions: new Float32Array(out), triangleCount: out.length / 9 };
}

function binaryStl(positions) {
  const count = positions.length / 9;
  const buffer = Buffer.alloc(84 + count * 50);
  buffer.write("Asgard Freyja 3D — implicit surface nets", 0, 80, "utf8");
  buffer.writeUInt32LE(count, 80);
  let offset = 84;
  for (let f = 0; f < count; f += 1) {
    const i = f * 9;
    const ax = positions[i + 3] - positions[i];
    const ay = positions[i + 4] - positions[i + 1];
    const az = positions[i + 5] - positions[i + 2];
    const bx = positions[i + 6] - positions[i];
    const by = positions[i + 7] - positions[i + 1];
    const bz = positions[i + 8] - positions[i + 2];
    const nx = ay * bz - az * by;
    const ny = az * bx - ax * bz;
    const nz = ax * by - ay * bx;
    const length = Math.hypot(nx, ny, nz) || 1;
    buffer.writeFloatLE(nx / length, offset);
    buffer.writeFloatLE(ny / length, offset + 4);
    buffer.writeFloatLE(nz / length, offset + 8);
    for (let value = 0; value < 9; value += 1) buffer.writeFloatLE(positions[i + value], offset + 12 + value * 4);
    buffer.writeUInt16LE(0, offset + 48);
    offset += 50;
  }
  return buffer;
}
