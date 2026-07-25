#!/usr/bin/env node
// mesh_audit — 메시를 측정하고 공정 규칙에 비추어 판정한다.
// 사용: node mesh_audit.mjs <model.stl|obj|glb> [--process fdm|sla|sls|cnc|sheet|injection] [--json]
//                          [--samples 3000] [--angle 45] [--baseline prev.json]
//                          [--shell N] [--unit mm|cm|m|in] [--up z|y|auto]
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { loadMesh } from "./core/mesh.mjs";
import { flatten, bounds, faces, volume, topology, overhangs, buildGrid, wallThickness, shells, extractShell } from "./core/geom.mjs";
import { toZUp } from "./core/raster.mjs";
import { parseArgs, fail, round } from "./core/cli.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const catalogue = JSON.parse(readFileSync(join(here, "..", "data", "processes.json"), "utf8"));

const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json"] });
if (!positional.length) fail("사용법: node mesh_audit.mjs <model> [--process fdm] [--json]");

const processKey = String(options.process || "fdm").toLowerCase();
const rules = catalogue.processes[processKey];
if (!rules) fail(`알 수 없는 공정: ${processKey} (가능: ${Object.keys(catalogue.processes).join(", ")})`);

let mesh;
try {
  mesh = loadMesh(positional[0]);
} catch (error) {
  fail(`모델을 읽지 못했다: ${positional[0]} — ${error.message}`);
}
const flat = flatten(mesh.parts);
const isGltf = /\.(glb|gltf)$/i.test(positional[0]);
const upMode = String(options.up || "auto");
// shoot.mjs 와 같은 의미: --up y 면 어떤 형식이든 변환, auto 는 glTF(Y-up 규격)만 변환.
let positions = upMode === "z" || (upMode === "auto" && !isGltf) ? flat.positions : toZUp(flat.positions);

// 단위 정규화 — 제조 규칙은 전부 mm 다. glTF 는 규격상 미터, STL/OBJ 는 관례상 mm.
const UNIT_TO_MM = { mm: 1, cm: 10, m: 1000, in: 25.4 };
const unitName = String(options.unit || "auto") === "auto" ? (isGltf ? "m" : "mm") : String(options.unit);
const unitScale = UNIT_TO_MM[unitName];
if (!unitScale) fail(`알 수 없는 단위: ${unitName} (mm, cm, m, in)`);
if (unitScale !== 1) {
  const scaled = new Float32Array(positions.length);
  for (let i = 0; i < positions.length; i += 1) scaled[i] = positions[i] * unitScale;
  positions = scaled;
}

// 독립 셸(부품)을 먼저 센다 — 조립체 메시에서 살두께를 재면 광선이 이웃 부품에 닿아 거짓 경보가 난다.
const weldTolerance = Math.max(1e-6, Math.hypot(...bounds(positions).size) * 1e-6);
const shellList = shells(positions, weldTolerance);
let shellNote = null;
if (options.shell !== undefined) {
  const index = Number(options.shell);
  if (!Number.isInteger(index) || index < 0 || index >= shellList.length) {
    fail(`셸 번호가 범위를 벗어났다: ${options.shell} (0..${shellList.length - 1})`);
  }
  positions = extractShell(positions, shellList[index]);
  shellNote = `셸 ${index}/${shellList.length - 1} 만 검사했다 (삼각형 ${shellList[index].length})`;
}
let cache = faces(positions);
const box = bounds(positions);
const tolerance = Math.max(1e-6, Math.hypot(...box.size) * 1e-6);
const topo = topology(positions, tolerance);
const grid = buildGrid(positions, cache, box);
const wall = wallThickness(positions, cache, grid, { samples: Number(options.samples || 3000) });
const overhang = overhangs(positions, cache, { threshold: Number(options.angle || rules.overhangDeg || 45) });
const signedVolume = volume(positions);
const surfaceArea = cache.areas.reduce((sum, value) => sum + value, 0);

const checks = [];
const add = (id, level, message, evidence) => checks.push({ id, level, message, ...(evidence ? { evidence } : {}) });

if (!topo.watertight) {
  add(
    "watertight",
    "fail",
    `닫힌 솔리드가 아니다 — 열린 에지 ${topo.openEdges}, 비매니폴드 에지 ${topo.nonManifoldEdges}. 부피·살두께 판정은 신뢰할 수 없다.`,
    { openEdges: topo.openEdges, nonManifoldEdges: topo.nonManifoldEdges },
  );
} else {
  add("watertight", "pass", "닫힌 매니폴드 메시다.");
}
if (topo.inconsistentEdges > 0) {
  add(
    "winding",
    "fail",
    `면 감김이 어긋난 에지 ${topo.inconsistentEdges}개 — 법선이 뒤집혀 오버행·두께 판정이 왜곡된다.`,
    { inconsistentEdges: topo.inconsistentEdges },
  );
}
if (cache.degenerate > 0) {
  add("degenerate", "warn", `면적 0인 삼각형 ${cache.degenerate}개 — 슬라이서·부울 연산에서 실패를 만든다.`);
}
if (signedVolume < 0 && topo.watertight) {
  add("orientation", "warn", "부호 부피가 음수다 — 법선이 전부 안쪽을 향한다. 메시를 뒤집어라.");
}

const multiShell = shellList.length > 1 && options.shell === undefined;
if (shellList.length > 1) {
  add(
    "shells",
    options.shell === undefined ? "warn" : "pass",
    options.shell === undefined
      ? `독립 셸이 ${shellList.length}개다 — 살두께 광선이 이웃 부품에 먼저 닿아 실제보다 얇게 측정된다. --shell 0..${shellList.length - 1} 로 부품마다 따로 검사하라.`
      : shellNote,
    { shellTriangles: shellList.map((shell) => shell.length) },
  );
}

const minWall = rules.minWall;
if (minWall && wall.samples) {
  const measured = wall.p01 ?? wall.min;
  if (measured < minWall) {
    add(
      "wall",
      multiShell ? "warn" : "fail",
      `최소 살두께 ${round(wall.min, 3)}mm (1퍼센타일 ${round(measured, 3)}mm) < ${rules.label} 한계 ${minWall}mm` +
        (multiShell ? " — 다만 셸이 여러 개라 부품 간 간극을 살두께로 잘못 읽었을 수 있다. --shell 로 재확인하라." : ""),
      { min: round(wall.min, 3), at: wall.minAt, thinnest: wall.thinnest },
    );
  } else if (rules.recommendedWall && measured < rules.recommendedWall) {
    add(
      "wall",
      "warn",
      `살두께 ${round(measured, 3)}mm 는 최소치는 넘지만 권장 ${rules.recommendedWall}mm 미만이다.`,
      { min: round(wall.min, 3), at: wall.minAt },
    );
  } else {
    add("wall", "pass", `살두께 ${round(measured, 3)}mm (최소 ${round(wall.min, 3)}mm) ≥ ${rules.label} 한계 ${minWall}mm`);
  }
}

// 사출은 두꺼운 살이 얇은 살만큼 치명적이다 — 싱크 마크·휨·냉각 지연.
if (rules.maxWall && wall.samples) {
  const thick = wall.p95 ?? wall.max;
  if (thick > rules.maxWall) {
    add(
      "wallmax",
      "warn",
      `관통 두께 95퍼센타일 ${round(thick, 3)}mm 가 ${rules.label} 최대 ${rules.maxWall}mm 를 넘는다 — 싱크 마크·휨을 만든다. 코어링·리브로 살을 균일하게 빼라.`,
      { p95: round(thick, 3), max: round(wall.max, 3) },
    );
  } else {
    add("wallmax", "pass", `관통 두께 95퍼센타일 ${round(thick, 3)}mm ≤ ${rules.label} 최대 ${rules.maxWall}mm`);
  }
}

if (rules.overhangDeg) {
  const ratio = overhang.overhangRatio;
  if (ratio > 0.15) {
    add(
      "overhang",
      "fail",
      `${rules.overhangDeg}° 미만 하향면이 전체 면적의 ${(ratio * 100).toFixed(1)}% — 서포트 없이는 무너진다. 최악 ${overhang.worst ? `${overhang.worst.tilt}°` : "n/a"}`,
      { ratio: round(ratio, 4), hotspots: overhang.hotspots },
    );
  } else if (ratio > 0.02) {
    add("overhang", "warn", `지지 필요 면적 ${(ratio * 100).toFixed(1)}% — 방향 회전이나 챔퍼로 줄일 수 있는지 확인하라.`, {
      hotspots: overhang.hotspots,
    });
  } else {
    add("overhang", "pass", `지지 필요 면적 ${(ratio * 100).toFixed(1)}% — 서포트 없이 인쇄 가능한 범위다.`);
  }
} else if (rules.powderSupported) {
  add("overhang", "pass", `${rules.label} 은 분말이 지지해 서포트 제약이 없다. 대신 분말 배출홀을 확인하라.`);
} else {
  add("overhang", "pass", `${rules.label} 은 적층 공정이 아니라 오버행 제약이 없다.`);
}

if (rules.buildVolume) {
  const sorted = [...box.size].sort((a, b) => b - a);
  const capacity = [...rules.buildVolume].sort((a, b) => b - a);
  const fits = sorted.every((value, index) => value <= capacity[index]);
  add(
    "buildvolume",
    fits ? "pass" : "warn",
    fits
      ? `조형 공간 ${rules.buildVolume.join("×")}mm 안에 들어간다.`
      : `치수 ${box.size.map((value) => round(value, 1)).join("×")}mm 가 기준 조형 공간 ${rules.buildVolume.join("×")}mm 를 넘는다 — 분할이나 장비 변경이 필요하다.`,
  );
}

const payload = {
  model: positional[0],
  unit: unitName,
  unitScaleToMm: unitScale,
  process: processKey,
  processLabel: rules.label,
  triangles: cache.count,
  shells: shellList.length,
  shellSelected: options.shell === undefined ? null : Number(options.shell),
  parts: flat.ranges.map((range) => ({ name: range.name, triangles: range.count })),
  bbox: {
    min: box.min.map((value) => round(value)),
    max: box.max.map((value) => round(value)),
    size: box.size.map((value) => round(value)),
  },
  volume: round(Math.abs(signedVolume), 3),
  surfaceArea: round(surfaceArea, 3),
  topology: topo,
  degenerateTriangles: cache.degenerate,
  wall: wall.samples
    ? { samples: wall.samples, min: round(wall.min, 4), p01: round(wall.p01, 4), median: round(wall.median, 4), minAt: wall.minAt, thinnest: wall.thinnest }
    : { samples: 0 },
  overhang: {
    thresholdDeg: overhang.thresholdDeg,
    ratio: round(overhang.overhangRatio, 4),
    area: round(overhang.overhangArea, 3),
    worst: overhang.worst ? { tiltDeg: overhang.worst.tilt, at: overhang.worst.at.map((value) => round(value)) } : null,
    hotspots: overhang.hotspots,
  },
  checks,
  verdict: checks.some((check) => check.level === "fail")
    ? "fail"
    : checks.some((check) => check.level === "warn")
      ? "warn"
      : "pass",
  notes: rules.notes,
  warnings: mesh.warnings,
};

if (options.baseline) {
  try {
    const previous = JSON.parse(readFileSync(String(options.baseline), "utf8"));
    payload.delta = {
      volume: round(payload.volume - previous.volume, 3),
      triangles: payload.triangles - previous.triangles,
      minWall: round((payload.wall.min ?? 0) - (previous.wall?.min ?? 0), 4),
      overhangRatio: round((payload.overhang.ratio ?? 0) - (previous.overhang?.ratio ?? 0), 4),
      verdict: `${previous.verdict} → ${payload.verdict}`,
    };
  } catch (error) {
    payload.delta = { error: `기준 파일을 읽지 못했다: ${error.message}` };
  }
}

if (options.json) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
} else {
  const mark = { pass: "PASS", warn: "WARN", fail: "FAIL" };
  const lines = [
    `모델     ${payload.model}   (${payload.processLabel}, 원본 단위 ${unitName} → mm)`,
    `치수     ${payload.bbox.size.join(" × ")} mm    부피 ${payload.volume} mm³    삼각형 ${payload.triangles}`,
    `살두께   최소 ${payload.wall.min ?? "n/a"} / 1% ${payload.wall.p01 ?? "n/a"} / 중앙 ${payload.wall.median ?? "n/a"} mm`,
    `오버행   ${(payload.overhang.ratio * 100).toFixed(1)}% (${payload.overhang.thresholdDeg}° 기준)`,
    "",
    ...checks.map((check) => `[${mark[check.level]}] ${check.id.padEnd(12)} ${check.message}`),
    "",
    `판정     ${payload.verdict.toUpperCase()}`,
  ];
  if (payload.delta) lines.push(`변화     ${JSON.stringify(payload.delta)}`);
  process.stdout.write(`${lines.join("\n")}\n`);
}
process.exitCode = payload.verdict === "fail" ? 1 : 0;
