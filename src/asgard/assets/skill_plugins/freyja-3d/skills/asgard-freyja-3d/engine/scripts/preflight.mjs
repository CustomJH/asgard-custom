#!/usr/bin/env node
// preflight — 3D 작업을 시작하기 전에 이 기계에서 무엇이 되고 무엇이 안 되는지 확인한다.
// 사용: node preflight.mjs [프로젝트경로] [--json]
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "./core/cli.mjs";

const SCRIPTS_DIR = dirname(fileURLToPath(import.meta.url));
const VENDOR = join(SCRIPTS_DIR, "..", "vendor", "text-to-cad");

const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json"] });
const root = positional[0] || process.cwd();

function probe(command, args) {
  try {
    return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 8000 }).trim().split("\n")[0];
  } catch {
    return null;
  }
}

const nodeVersion = process.versions.node;
const nodeMajor = Number(nodeVersion.split(".")[0]);
const uv = probe("uv", ["--version"]);
const python = probe("python3", ["--version"]);
const npx = probe("npx", ["--version"]);
const blender = probe("blender", ["--version"]);

let packageJson = null;
try {
  packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
} catch {
  packageJson = null;
}
const dependencies = { ...(packageJson?.dependencies || {}), ...(packageJson?.devDependencies || {}) };
const threeVersion = dependencies.three || null;
const r3f = dependencies["@react-three/fiber"] || null;
const trois = dependencies["@tresjs/core"] || dependencies["troisjs"] || null;
const threlte = dependencies["@threlte/core"] || null;
const gsap = dependencies.gsap || null;

// CAD 커널 층은 벤더링된 런타임이 실제로 있어야 돈다. 없는데 READY 라고 말하면
// 나중에 "안 됐다"가 된다 — preflight 의 존재 이유가 그것을 막는 것이다.
const cadRuntime = existsSync(join(VENDOR, "skills", "cad", "scripts", "step"));
const viewerRuntime = existsSync(join(VENDOR, "skills", "cad-viewer", "scripts", "viewer", "backend", "server.mjs"));
const cadReady = Boolean(uv) && cadRuntime;

const lanes = [
  {
    lane: "verify",
    label: "형상 검증 (렌더·측정·검출)",
    ready: nodeMajor >= 18,
    detail: `node ${nodeVersion}${nodeMajor >= 18 ? "" : " — node 18 이상이 필요하다"}`,
    needs: "없음 — 이 엔진의 모든 검증 스크립트는 의존성이 없다.",
  },
  {
    lane: "cad",
    label: "정밀 조형 (STEP 우선 파라메트릭 CAD)",
    ready: cadReady,
    detail: [uv ? `uv ${uv}` : "uv 없음", cadRuntime ? "벤더 런타임 있음" : "벤더 런타임 없음"].join(", "),
    needs: !uv
      ? "uv 를 설치하라: curl -LsSf https://astral.sh/uv/install.sh | sh"
      : !cadRuntime
        ? "engine/vendor/text-to-cad/ 가 없다. UPSTREAM.md 의 재동기화 절차를 보라."
        : "python engine/scripts/cad.py step <model.py> — 최초 1회 CAD 커널 휠을 내려받아 오래 걸린다.",
  },
  {
    lane: "fabricate",
    label: "도면·슬라이싱·발주 (DXF·G-code·절단·프린터)",
    ready: cadReady,
    detail: cadReady ? "cad.py dxf|gcode|parts 준비" : "cad 레인이 막혀 있다",
    needs: cadReady
      ? "슬라이싱은 실제 슬라이서가 필요하다: python engine/scripts/cad.py gcode discover (없으면 brew install --cask orcaslicer)"
      : "cad 레인을 먼저 뚫어라.",
  },
  {
    lane: "robot",
    label: "로봇 기술 파일 (URDF·SRDF·SDF)",
    ready: Boolean(uv) && existsSync(join(VENDOR, "skills", "urdf", "scripts", "urdf")),
    detail: uv ? `uv ${uv}` : "uv 없음",
    needs: "python engine/scripts/cad.py urdf|srdf|sdf <source.py>. MoveIt2 대화 리뷰는 별도 conda·ROS 설치가 필요하다.",
  },
  {
    lane: "viewer",
    label: "로컬 리뷰 뷰어",
    ready: nodeMajor >= 18 && viewerRuntime,
    detail: viewerRuntime ? "번들 서버 있음(추가 설치 불필요)" : "뷰어 번들 없음",
    needs: "node engine/vendor/text-to-cad/skills/cad-viewer/scripts/viewer/backend/server.mjs --host 127.0.0.1 --port 4178 (그 뒤 ?dir= 로 산출물 위치를 준다)",
  },
  {
    lane: "realtime",
    label: "실시간 3D 웹",
    ready: Boolean(threeVersion || r3f || trois || threlte),
    detail:
      [threeVersion && `three ${threeVersion}`, r3f && `r3f ${r3f}`, trois && `tres ${trois}`, threlte && `threlte ${threlte}`]
        .filter(Boolean)
        .join(", ") || "프로젝트에 3D 런타임이 없다",
    needs: threeVersion ? "없음" : "npm i three (WebGPU 경로는 three r171 이상, TSL 은 three/webgpu 에서 온다)",
  },
  {
    lane: "motion",
    label: "3D 모션·연출",
    ready: true,
    detail: gsap ? `gsap ${gsap}` : "gsap 없음 — Web Animations API·자체 보간으로도 진행할 수 있다",
    needs: "스크롤 스크럽·핀이 필요하면 gsap ScrollTrigger, 그 외에는 추가 의존성이 필요 없다.",
  },
  {
    lane: "pipeline",
    label: "자산 파이프라인 (압축·최적화)",
    ready: Boolean(npx),
    detail: npx ? `npx ${npx}` : "npx 없음",
    needs: "npx @gltf-transform/cli optimize in.glb out.glb --texture-compress ktx2 (네트워크 필요)",
  },
  {
    lane: "game",
    label: "게임 자산 (폴리시·DCC 승급)",
    ready: nodeMajor >= 18,
    detail: blender ? `mesh_polish + ${blender}` : "mesh_polish 준비 — blender 없음(스컬프트·UV·베이크 승급 불가)",
    needs: blender
      ? "없음 — 스무딩·머티리얼은 mesh_polish, 그 이상은 blender -b --python 헤드리스."
      : "용접·크리스 스무딩·PBR 머티리얼은 mesh_polish.mjs 로 된다. 유기 조형·UV 전개·텍스처 베이크가 필요하면 Blender 를 설치하라(brew install --cask blender).",
  },
];

const payload = {
  root,
  node: nodeVersion,
  uv,
  python,
  npx,
  blender,
  runtime: { three: threeVersion, r3f, tres: trois, threlte, gsap },
  lanes,
  blockers: lanes.filter((lane) => !lane.ready).map((lane) => lane.lane),
};

if (options.json) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
} else {
  const lines = [`프로젝트  ${root}`, ""];
  for (const lane of lanes) {
    lines.push(`[${lane.ready ? "READY" : "BLOCK"}] ${lane.lane.padEnd(9)} ${lane.label}`);
    lines.push(`          ${lane.detail}`);
    if (!lane.ready || lane.needs !== "없음") lines.push(`          필요: ${lane.needs}`);
    lines.push("");
  }
  process.stdout.write(`${lines.join("\n")}\n`);
}
