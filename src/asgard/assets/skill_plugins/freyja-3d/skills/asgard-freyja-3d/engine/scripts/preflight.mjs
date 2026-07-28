#!/usr/bin/env node
// preflight — 3D 작업을 시작하기 전에 이 기계에서 무엇이 되고 무엇이 안 되는지 확인한다.
// 사용: node preflight.mjs [프로젝트경로] [--json]
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "./core/cli.mjs";

const SCRIPTS_DIR = dirname(fileURLToPath(import.meta.url));
const CADLIB = join(SCRIPTS_DIR, "cadlib");

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

// 런타임이 실제로 있어야 READY 라고 말한다. 없는데 READY 면 나중에 "안 됐다"가 되고,
// preflight 의 존재 이유가 바로 그것을 막는 것이다.
//
// 두 갈래로 나뉜다. 검증 동사(inspect·gcode·urdf)는 순수 파이썬이라 **uv 도 커널도 없이** 돌고,
// 형상을 만드는 일(step)만 커널을 요구한다. 이 구분을 preflight 가 흐리면 사용자는 검증조차
// 못 하는 줄 알고 물러선다.
const cadRuntime = existsSync(join(CADLIB, "steplane.py"));
const viewerRuntime = existsSync(join(SCRIPTS_DIR, "view.mjs"));
const verifyReady = cadRuntime && Boolean(python);
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
    lane: "measure",
    label: "산출물 판독·검증 (STEP·DXF·G-code·로봇 파일 — 커널 불필요)",
    ready: verifyReady,
    detail: [python ? python : "python3 없음", cadRuntime ? "cadlib 있음" : "cadlib 없음"].join(", "),
    needs: verifyReady
      ? "없음 — python engine/scripts/cad.py inspect|gcode|urdf|srdf|sdf 가 설치 없이 바로 돈다."
      : !python
        ? "python3 가 필요하다."
        : "engine/scripts/cadlib/ 이 없다 — 스킬 설치가 깨졌다.",
  },
  {
    lane: "cad",
    label: "정밀 조형 (STEP 우선 파라메트릭 CAD — 커널 필요)",
    ready: cadReady,
    detail: [uv ? `uv ${uv}` : "uv 없음", cadRuntime ? "cadlib 있음" : "cadlib 없음"].join(", "),
    needs: !uv
      ? "uv 를 설치하라: curl -LsSf https://astral.sh/uv/install.sh | sh (형상 생성만 필요하고, 검증은 uv 없이 돈다)"
      : !cadRuntime
        ? "engine/scripts/cadlib/ 이 없다 — 스킬 설치가 깨졌다."
        : "python engine/scripts/cad.py step <model.py> — 최초 1회 CAD 커널 휠을 내려받아 오래 걸린다.",
  },
  {
    lane: "fabricate",
    label: "도면·슬라이싱·발주 (DXF·G-code·절단)",
    ready: verifyReady,
    detail: [
      verifyReady ? "gcode·dxf check 준비" : "판독 레인이 막혀 있다",
      uv ? "dxf 생성 준비" : "dxf 생성은 uv 필요",
    ].join(", "),
    needs: verifyReady
      ? "슬라이싱은 실제 슬라이서가 필요하다: python engine/scripts/cad.py gcode discover (없으면 brew install --cask orcaslicer)"
      : "판독 레인을 먼저 뚫어라.",
  },
  {
    lane: "robot",
    label: "로봇 기술 파일 (URDF·SRDF·SDF — 커널 불필요)",
    ready: verifyReady,
    detail: verifyReady ? "생성·검증 모두 표준 라이브러리로 돈다" : "python3 없음",
    needs: "python engine/scripts/cad.py urdf|srdf|sdf <source.py>. SRDF 는 --urdf 로 교차 검증을 같이 돌려라.",
  },
  {
    lane: "viewer",
    label: "로컬 리뷰 뷰어",
    ready: nodeMajor >= 18 && viewerRuntime,
    detail: viewerRuntime ? "네이티브 서버(서버측 렌더 — 브라우저 3D 의존 없음)" : "view.mjs 없음",
    needs: "node engine/scripts/view.mjs --dir <산출물 디렉터리> --port 4178",
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
