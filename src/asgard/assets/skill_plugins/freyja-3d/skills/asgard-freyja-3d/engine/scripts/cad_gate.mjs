#!/usr/bin/env node
// cad_gate — CAD 배달물이 "검증됐다"고 말할 자격이 있는지 산출물에서 판정한다.
//
// 이 게이트는 소스를 읽지 않는다. 소스는 의도를 말하고 산출물은 사실을 말하는데,
// 배달 사고는 전부 그 둘이 어긋난 자리에서 난다. 그래서 입력은 납품 디렉터리다.
//
// 막는 것은 **바이트로 증명되는 것만**이다. "형상이 요청과 닮았는가"는 이 게이트가
// 판정하지 못하고, 못 하는 것을 통과로 세지 않으려고 마지막에 미판정 목록을 같이 낸다.
//
// 사용: node cad_gate.mjs <경로...> [--json] [--interference-tolerance 1e-6]
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, realpathSync, statSync } from "node:fs";
import { basename, dirname, extname, join } from "node:path";
import { gunzipSync, inflateSync } from "node:zlib";
import { parseArgs, fail, emit, round } from "./core/cli.mjs";

const STEP_EXT = new Set([".step", ".stp"]);
const MESH_EXT = new Set([".stl", ".3mf", ".glb", ".gltf", ".obj"]);
const SHOT_EXT = new Set([".png", ".gif", ".jpg", ".jpeg", ".webp"]);
const SKIP_DIR = new Set(["node_modules", ".git", "__pycache__", "dist", "build_cache"]);

// ISO 10303-21 은 STEP 물리 파일의 첫 줄을 이 토큰으로 고정한다. 확장자만 바꾼
// 메시를 STEP 이라고 부르는 사고가 실제로 흔해서, 이 게이트의 1번 규칙이 됐다.
const STEP_MAGIC = "ISO-10303-21;";

// DXF $INSUNITS 에서 우리가 치수를 신뢰하는 값. 1=inch, 4=mm.
const DXF_KNOWN_UNITS = new Set([1, 4]);

function walk(target, out, seen = new Set()) {
  let real;
  try {
    real = realpathSync(target);
  } catch {
    return out;
  }
  if (seen.has(real)) return out; // 심링크 순환 방어.
  seen.add(real);
  const info = statSync(real);
  if (info.isFile()) {
    out.push(real);
    return out;
  }
  if (!info.isDirectory()) return out;
  for (const entry of readdirSync(real)) {
    if (SKIP_DIR.has(entry)) continue;
    walk(join(real, entry), out, seen);
  }
  return out;
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

/** GLB 의 JSON 청크만 떼어 읽는다. glTF 2.0 컨테이너 규격 — 12바이트 헤더 + 청크들. */
function readGlbJson(path) {
  const buf = readFileSync(path);
  if (buf.length < 20 || buf.readUInt32LE(0) !== 0x46546c67) return null; // "glTF"
  const jsonLength = buf.readUInt32LE(12);
  if (20 + jsonLength > buf.length) return null;
  let json;
  try {
    json = JSON.parse(buf.subarray(20, 20 + jsonLength).toString("utf8"));
  } catch {
    return null;
  }
  const binOffset = 20 + jsonLength;
  let bin = null;
  if (binOffset + 8 <= buf.length) {
    const binLength = buf.readUInt32LE(binOffset);
    bin = buf.subarray(binOffset + 8, binOffset + 8 + binLength);
  }
  return { json, bin };
}

/**
 * 위상 산출물이 기록해둔 stepHash 를 꺼낸다.
 *
 * 이 값이 왜 중요한가: refs·measure·align·snapshot 은 전부 이 산출물을 읽는다.
 * STEP 을 다시 뽑고 산출물을 갱신하지 않으면, 측정은 성공하는데 **다른 형상을**
 * 측정한다. 사람이 볼 수 없는 종류의 거짓말이라 기계가 져야 한다.
 */
function readTopologyStepHash(glbPath) {
  const parsed = readGlbJson(glbPath);
  if (!parsed) return null;
  const ext = parsed.json?.extensions?.STEP_topology;
  if (!ext || parsed.bin === null) return null;
  const view = parsed.json.bufferViews?.[ext.indexView];
  if (!view) return null;
  const offset = view.byteOffset || 0;
  const raw = parsed.bin.subarray(offset, offset + view.byteLength);
  let text = null;
  for (const decode of [(b) => b.toString("utf8"), (b) => gunzipSync(b).toString("utf8"), (b) => inflateSync(b).toString("utf8")]) {
    try {
      const candidate = decode(raw);
      if (candidate.includes("stepHash")) {
        text = candidate;
        break;
      }
    } catch {
      /* 다음 디코더로 넘어간다 */
    }
  }
  if (text === null) return null;
  const match = text.match(/"stepHash"\s*:\s*"([0-9a-f]{64})"/);
  return match ? match[1] : null;
}

/** DXF $INSUNITS — ASCII DXF 는 그룹코드 9 로 변수명, 다음 코드 70 으로 값을 적는다. */
function readDxfUnits(path) {
  const head = readFileSync(path);
  // 바이너리 DXF 는 이 방식으로 못 읽는다. 못 읽는 것을 fail 로 만들지 않는다.
  if (head.subarray(0, 18).toString("binary").startsWith("AutoCAD Binary DXF")) return { binary: true, units: null };
  const lines = head.toString("utf8").split(/\r?\n/);
  for (let i = 0; i < lines.length - 2; i += 1) {
    if (lines[i].trim() !== "9" || lines[i + 1].trim() !== "$INSUNITS") continue;
    const value = Number.parseInt(lines[i + 3] ?? "", 10);
    return { binary: false, units: Number.isFinite(value) ? value : null };
  }
  return { binary: false, units: null };
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

/** 중첩 구조 어디에 있든 지정한 키를 전부 긁는다 — 진단 JSON 모양이 도구마다 달라서다. */
function harvest(node, key, out = []) {
  if (Array.isArray(node)) {
    for (const item of node) harvest(item, key, out);
    return out;
  }
  if (node && typeof node === "object") {
    for (const [name, value] of Object.entries(node)) {
      if (name === key) out.push(value);
      harvest(value, key, out);
    }
  }
  return out;
}

function classify(files) {
  const steps = [];
  const meshes = [];
  const shots = [];
  const dxfs = [];
  const gcodes = [];
  const jsons = [];
  for (const file of files) {
    const ext = extname(file).toLowerCase();
    const name = basename(file);
    if (STEP_EXT.has(ext)) steps.push(file);
    else if (ext === ".dxf") dxfs.push(file);
    else if (ext === ".gcode") gcodes.push(file);
    else if (SHOT_EXT.has(ext)) shots.push(file);
    else if (ext === ".json") jsons.push(file);
    // 위상 산출물(.name.step.glb)은 납품 메시가 아니라 증거다 — 메시 목록에서 뺀다.
    else if (MESH_EXT.has(ext) && !name.endsWith(".step.glb")) meshes.push(file);
  }
  return { steps, meshes, shots, dxfs, gcodes, jsons };
}

function judge(files, options) {
  const findings = [];
  const { steps, meshes, shots, dxfs, gcodes, jsons } = classify(files);
  const tolerance = Number(options["interference-tolerance"] ?? 1e-6);

  const add = (severity, rule, path, message) => findings.push({ severity, rule, path, message });

  // 메시 경로로 검증했다는 증거 — mesh_audit 이 실제로 돌아 판정을 남겼는가.
  // 파일 이름이 아니라 내용으로 본다(이름은 자유롭게 지어진다).
  const meshVerified = jsons.some((path) => {
    const data = readJson(path);
    if (!data) return false;
    const text = JSON.stringify(data);
    return text.includes("watertight") || text.includes("mesh_audit") || text.includes("minWallThickness");
  });

  for (const step of steps) {
    const size = statSync(step).size;
    if (size === 0) {
      add("fail", "empty-artifact", step, "STEP 이 0 바이트다. 생성이 실패했는데 파일만 남았다.");
      continue;
    }
    const head = readFileSync(step).subarray(0, 64).toString("latin1").trimStart();
    if (!head.startsWith(STEP_MAGIC)) {
      add(
        "fail",
        "fake-step",
        step,
        `확장자는 STEP 인데 내용이 ISO 10303-21 이 아니다. 메시를 STEP 이라고 부른 것이다(첫 바이트: ${JSON.stringify(head.slice(0, 24))}).`,
      );
      continue;
    }

    const stem = basename(step).replace(/\.(step|stp)$/i, "");
    const artifact = join(dirname(step), `.${stem}.step.glb`);
    let artifactExists = true;
    try {
      statSync(artifact);
    } catch {
      artifactExists = false;
    }
    if (!artifactExists) {
      // 위상 산출물이 없으면 셀렉터 검증(refs·measure·align·snapshot)이 불가능하다.
      // 그렇다고 곧장 막지는 않는다 — 메시 경로(mesh_audit + 렌더 증거)로 검증한 배달도
      // 정당하고, 이 엔진의 기준 표본 둘이 실제로 그 경로로 만들어졌다. 막아야 하는 것은
      // "다르게 검증된" 배달이 아니라 "검증되지 않은" 배달이다.
      add(
        meshVerified ? "warn" : "fail",
        "topology-missing",
        step,
        meshVerified
          ? "위상 산출물(.step.glb)이 없다. 메시 경로로 검증된 배달이므로 막지 않지만, 이 STEP 에 대해 셀렉터 측정(refs·measure·align)을 했다고 말할 수는 없다."
          : "위상 산출물(.step.glb)도 메시 감사도 없다. 이 STEP 에 대한 검증 주장은 근거가 없다 — cad.py step 으로 생성하거나 mesh_audit 을 돌려라.",
      );
      continue;
    }
    const recorded = readTopologyStepHash(artifact);
    if (recorded === null) {
      add("warn", "topology-unreadable", artifact, "위상 산출물에서 stepHash 를 읽지 못했다. 신선도를 판정하지 못한다.");
      continue;
    }
    const actual = sha256(step);
    if (recorded !== actual) {
      add(
        "fail",
        "topology-stale",
        step,
        `위상 산출물이 다른 STEP 을 가리킨다(기록 ${recorded.slice(0, 12)}… ≠ 실제 ${actual.slice(0, 12)}…). ` +
          "측정은 성공하지만 옛 형상을 측정한다. cad.py step 으로 다시 생성해야 한다.",
      );
    }
  }

  // 형상이 배달되는데 본 흔적이 없으면 막는다. 조사 전용 과업은 STEP 을 만들지 않으므로
  // 이 규칙에 걸리지 않는다 — 걸린다면 정말로 안 본 것이다.
  if ((steps.length > 0 || meshes.length > 0) && shots.length === 0) {
    add(
      "fail",
      "snapshot-missing",
      steps[0] ?? meshes[0],
      "형상 산출물은 있는데 렌더 증거(PNG/GIF)가 하나도 없다. 결정론 검사 통과는 스냅샷을 건너뛸 이유가 아니다.",
    );
  }

  for (const dxf of dxfs) {
    if (statSync(dxf).size === 0) {
      add("fail", "empty-artifact", dxf, "DXF 가 0 바이트다.");
      continue;
    }
    const { binary, units } = readDxfUnits(dxf);
    if (binary) {
      add("warn", "dxf-binary", dxf, "바이너리 DXF 라 헤더 단위를 이 게이트가 못 읽는다. 단위는 사람이 확인해야 한다.");
      continue;
    }
    if (units === null || !DXF_KNOWN_UNITS.has(units)) {
      add(
        "fail",
        "dxf-units",
        dxf,
        `$INSUNITS 가 ${units === null ? "없다" : `${units} 다`}. 절단 서비스는 단위 없는 DXF 의 치수를 신뢰하지 않는다(1=inch, 4=mm).`,
      );
    }
  }

  for (const path of jsons) {
    const data = readJson(path);
    if (!data) continue;

    for (const volume of harvest(data, "interferenceVolume")) {
      const value = Number(volume);
      if (Number.isFinite(value) && value > tolerance) {
        add("fail", "interference", path, `부품이 ${round(value, 6)}mm³ 만큼 서로를 파고든다. "조금 겹친다"는 상태는 없다.`);
      }
    }

    // mesh_audit 이 스스로 fail 을 적어둔 것을 배달에 끼워 보내는 경우.
    if (typeof data.tool === "string" && data.tool.includes("mesh_audit") && data.status === "fail") {
      add("fail", "mesh-audit-fail", path, "mesh_audit 판정이 fail 인 채로 납품에 들어 있다.");
    }
  }

  for (const gcode of gcodes) {
    const hasValidation = jsons.some((path) => {
      const data = readJson(path);
      return data !== null && JSON.stringify(data).includes("gcode");
    });
    if (!hasValidation) {
      add("warn", "gcode-unvalidated", gcode, "G-code 옆에 검증 결과 JSON 이 없다. 프린터로 넘기기 전에 validate 를 돌려야 한다.");
    }
  }

  return findings;
}

// 이 게이트가 판정하지 못하는 것들. 침묵은 통과가 아니라 미확인이라서 이름으로 남긴다.
const UNJUDGED = [
  "형상이 요청한 물건과 닮았는가 — 렌더를 사람이 열어서 대조해야 한다.",
  "사용자가 말한 치수를 전부 쟀는가 — 선언된 명세가 없으면 무엇을 재야 하는지 알 수 없다.",
  "제조 가능성(공차·재료·공정 인증) — 기하학적 타당성 너머는 해석과 데이터가 필요하다.",
  "조립 순서와 접근성 — 부품이 안 겹친다는 것과 손이 들어간다는 것은 다르다.",
];

function renderText(payload) {
  const lines = [];
  const mark = { fail: "FAIL", warn: "WARN" };
  for (const finding of payload.findings) {
    lines.push(`[${mark[finding.severity] ?? "INFO"}] ${finding.rule}  ${finding.path}`);
    lines.push(`    ${finding.message}`);
  }
  if (payload.findings.length === 0) lines.push("판정 대상에서 막을 것을 찾지 못했다.");
  lines.push("");
  lines.push(`판정 ${payload.summary.judged} · 막힘 ${payload.summary.fail} · 경고 ${payload.summary.warn}`);
  lines.push("");
  lines.push("이 게이트가 판정하지 않는 것:");
  for (const item of payload.unjudged) lines.push(`  - ${item}`);
  return lines.join("\n");
}

function main() {
  const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json"] });
  if (positional.length === 0) fail("판정할 경로를 하나 이상 달라. 사용: node cad_gate.mjs <납품 경로...> [--json]");

  const files = [];
  for (const target of positional) walk(target, files);
  if (files.length === 0) fail(`대상에서 파일을 찾지 못했다: ${positional.join(", ")}`);

  const findings = judge(files, options);
  const failures = findings.filter((item) => item.severity === "fail");
  const payload = {
    tool: "cad_gate",
    status: failures.length > 0 ? "fail" : "pass",
    scanned: files.length,
    findings,
    unjudged: UNJUDGED,
    summary: {
      judged: files.length,
      fail: failures.length,
      warn: findings.length - failures.length,
    },
  };
  emit(payload, Boolean(options.json), renderText);
  return failures.length > 0 ? 1 : 0;
}

process.exit(main());
