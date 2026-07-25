#!/usr/bin/env node
// detect3d — 실시간 3D 코드의 배달 결함을 정적으로 잡는다.
// 코드 리뷰로는 통과하지만 배달된 화면에서 죽는 것들: 돌지 않는 컨트롤, 못 도는 폴백,
// 해제되지 않는 GPU 자원, 저감 모션을 무시하는 카메라 연출.
// 사용: node detect3d.mjs [경로...] [--json] [--severity warn|fail]
import { readFileSync, readdirSync, realpathSync, statSync } from "node:fs";
import { extname, join } from "node:path";
import { parseArgs, fail } from "./core/cli.mjs";

const SOURCE = new Set([".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue", ".svelte", ".astro"]);
const SKIP = new Set(["node_modules", ".git", "dist", "build", ".next", ".nuxt", ".output", "coverage", ".asgard"]);

function collect(target, out, seen = new Set()) {
  const real = realpathSync(target); // 심링크 순환·중복 방문 방어.
  if (seen.has(real)) return out;
  seen.add(real);
  const info = statSync(target);
  if (info.isFile()) {
    if (SOURCE.has(extname(target))) out.push(target);
    return out;
  }
  for (const entry of readdirSync(target)) {
    if (SKIP.has(entry) || entry.startsWith(".")) continue;
    collect(join(target, entry), out, seen);
  }
  return out;
}

/** 주석과 문자열만 남는 줄은 규칙 판정에서 제외한다. */
function isComment(line) {
  const trimmed = line.trim();
  return trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*");
}

/** 문자열 밖의 주석을 걷어낸다 — 주석 속 단어("controls.update() 를 안 불렀다")가 판정을 뒤집지 못하게. */
function stripComments(source) {
  let out = "";
  let quote = null; // ', ", ` 안에서는 주석 문법을 무시한다.
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    const next = source[i + 1];
    if (quote) {
      out += ch;
      if (ch === "\\") {
        out += next ?? "";
        i += 1;
      } else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === "`") {
      quote = ch;
      out += ch;
      continue;
    }
    if (ch === "/" && next === "/") {
      while (i < source.length && source[i] !== "\n") i += 1;
      out += "\n";
      continue;
    }
    if (ch === "/" && next === "*") {
      i += 2;
      while (i < source.length && !(source[i] === "*" && source[i + 1] === "/")) {
        if (source[i] === "\n") out += "\n";
        i += 1;
      }
      i += 1;
      continue;
    }
    out += ch;
  }
  return out;
}

const RULES = [
  {
    id: "inert-controls",
    severity: "fail",
    test: (source) => /enableDamping\b(?!\s*[:=]\s*\{?\s*false)/.test(source) && !/controls?\s*\.\s*update\s*\(/i.test(source),
    anchor: /enableDamping/,
    message: "enableDamping 을 켰지만 루프에서 controls.update() 를 호출하지 않는다 — 관성은 코드에만 있고 화면에서는 죽어 있다.",
    fix: "애니메이션 루프 안에서 매 프레임 controls.update() 를 호출하라.",
  },
  {
    id: "webgpu-legacy-material",
    severity: "fail",
    test: (source) => /from\s+["']three\/webgpu["']|WebGPURenderer/.test(source) && /new\s+(THREE\.)?(Raw)?ShaderMaterial|onBeforeCompile/.test(source),
    anchor: /(Raw)?ShaderMaterial|onBeforeCompile/,
    message: "WebGPURenderer 경로에서 ShaderMaterial/onBeforeCompile 은 지원되지 않는다 — 런타임에 셰이더가 컴파일되지 않는다.",
    fix: "TSL 노드 머티리얼(NodeMaterial, Fn, uniform, texture)로 포팅하라. TSL 은 WGSL·GLSL 양쪽으로 컴파일된다.",
  },
  {
    id: "webgpu-init-missing",
    severity: "fail",
    test: (source) =>
      /new\s+(THREE\.)?WebGPURenderer\s*\(/.test(source) &&
      /\.render\s*\(/.test(source) &&
      !/await\s+\w+\.init\s*\(|\.init\s*\(\s*\)\s*\.then|setAnimationLoop|renderAsync/.test(source),
    anchor: /new\s+(THREE\.)?WebGPURenderer/,
    message: "WebGPURenderer 를 만들고 render() 를 부르지만 await renderer.init() 이 없다 — 백엔드 초기화 전 렌더는 조용히 빈 화면이다.",
    fix: "await renderer.init() 뒤에 렌더하거나, 초기화를 내부에서 기다리는 setAnimationLoop() 을 써라.",
  },
  {
    id: "pixelratio-unclamped",
    severity: "fail",
    anchor: /setPixelRatio\s*\(\s*window\.devicePixelRatio\s*\)/,
    message: "devicePixelRatio 를 그대로 넘기면 고DPI 모바일에서 픽셀 수가 4~9배로 늘어 프레임이 무너진다.",
    fix: "renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)) 로 상한을 두어라.",
  },
  {
    id: "reduced-motion-missing",
    severity: "fail",
    test: (source) =>
      /(gsap|ScrollTrigger|useFrame|setAnimationLoop|requestAnimationFrame)/.test(source) &&
      /(camera\.(position|rotation|lookAt)|\.rotation\.[xyz]\s*[+\-*/]?=|lerp|damp)/.test(source) &&
      !/prefers-reduced-motion/.test(source),
    anchor: /(camera\.(position|rotation|lookAt)|useFrame|ScrollTrigger)/,
    message: "카메라·오브젝트 연출이 있는데 prefers-reduced-motion 분기가 없다 — 전정 장애 사용자에게 회피 수단이 없다.",
    fix: "matchMedia('(prefers-reduced-motion: reduce)') 로 감속·정지 경로를 만들고, 첫 프레임의 최종 상태는 모션 없이도 보이게 하라.",
  },
  {
    id: "draco-decoder-path",
    severity: "fail",
    test: (source) => /new\s+DRACOLoader\s*\(/.test(source) && !/setDecoderPath|setDecoderConfig/.test(source),
    anchor: /new\s+DRACOLoader/,
    message: "DRACOLoader 에 디코더 경로를 지정하지 않았다 — 압축 모델 로드가 런타임에 실패한다.",
    fix: "dracoLoader.setDecoderPath('/draco/') 처럼 정적 경로를 지정하고 디코더 파일을 함께 배포하라.",
  },
  {
    id: "deprecated-api",
    severity: "fail",
    anchor: /(outputEncoding|sRGBEncoding|LinearEncoding|physicallyCorrectLights|useLegacyLights|new\s+THREE\.Geometry\b)/,
    message: "three 에서 제거된 API 다(색공간 API 는 r152, physicallyCorrectLights 는 r155, Geometry 는 r125 에 교체됨).",
    fix: "outputColorSpace/SRGBColorSpace, renderer.toneMapping, BufferGeometry 로 바꿔라.",
  },
  {
    id: "resource-leak",
    severity: "warn",
    test: (source) =>
      /(remove\s*\(|clear\s*\(\s*\)|unmount|onDestroy|beforeUnmount|useEffect\s*\()/.test(source) &&
      /new\s+(THREE\.)?(BufferGeometry|BoxGeometry|SphereGeometry|PlaneGeometry|CylinderGeometry|MeshStandardMaterial|MeshPhysicalMaterial|ShaderMaterial|NodeMaterial)/.test(source) &&
      !/\.dispose\s*\(/.test(source),
    anchor: /new\s+(THREE\.)?(BufferGeometry|BoxGeometry|SphereGeometry|PlaneGeometry|CylinderGeometry|MeshStandardMaterial|MeshPhysicalMaterial|ShaderMaterial|NodeMaterial)/,
    message: "지오메트리·머티리얼을 만들지만 dispose() 가 없다 — 라우트를 오갈 때마다 GPU 메모리가 샌다.",
    fix: "언마운트 시 geometry.dispose(), material.dispose(), texture.dispose(), renderer.dispose() 를 호출하라.",
  },
  {
    id: "loop-allocation",
    severity: "warn",
    anchor: /(useFrame|setAnimationLoop|function\s+animate|const\s+animate\s*=)/,
    test: (source) => /(useFrame\s*\(|setAnimationLoop\s*\(|function\s+animate)/.test(source) && /new\s+(THREE\.)?(Vector[234]|Quaternion|Matrix4|Color|Euler|Raycaster)\s*\(/.test(source),
    detail: (lines) => {
      const findings = [];
      let depth = null;
      lines.forEach((line, index) => {
        if (/(useFrame\s*\(|setAnimationLoop\s*\(|function\s+animate|const\s+animate\s*=\s*\()/.test(line)) depth = index;
        if (depth !== null && index - depth < 40 && /new\s+(THREE\.)?(Vector[234]|Quaternion|Matrix4|Color|Euler|Raycaster)\s*\(/.test(line)) {
          findings.push(index);
        }
      });
      return findings;
    },
    message: "프레임 루프 안에서 Vector/Matrix 객체를 새로 만든다 — 매 프레임 쓰레기가 쌓여 주기적인 프레임 드랍을 만든다.",
    fix: "루프 밖에서 임시 객체를 한 번 만들어 재사용하라(모듈 스코프 상수 또는 useRef).",
  },
  {
    id: "background-loop",
    severity: "warn",
    test: (source) =>
      /requestAnimationFrame\s*\(/.test(source) &&
      !/setAnimationLoop|visibilitychange|document\.hidden|IntersectionObserver|frameloop/.test(source),
    anchor: /requestAnimationFrame\s*\(/,
    message: "탭이 가려져도 도는 렌더 루프다 — 배터리와 열을 계속 소모한다.",
    fix: "renderer.setAnimationLoop 을 쓰거나 visibilitychange/IntersectionObserver 로 보이지 않을 때 멈춰라.",
  },
  {
    id: "resize-missing",
    severity: "warn",
    test: (source) =>
      /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(/.test(source) &&
      !/(resize|ResizeObserver|updateProjectionMatrix)/.test(source),
    anchor: /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(/,
    message: "렌더러를 만들지만 리사이즈 처리가 없다 — 창 크기나 방향이 바뀌면 화면이 늘어난다.",
    fix: "ResizeObserver 로 setSize 와 camera.aspect/updateProjectionMatrix 를 갱신하라.",
  },
  {
    id: "tonemapping-default",
    severity: "warn",
    test: (source) =>
      /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(/.test(source) && !/toneMapping/.test(source),
    anchor: /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(/,
    message: "톤 매핑을 지정하지 않았다 — 하이라이트가 그대로 클리핑되어 재질이 플라스틱처럼 보인다.",
    fix: "renderer.toneMapping = THREE.AgXToneMapping(또는 ACESFilmic) 과 toneMappingExposure 를 설정하라.",
  },
  {
    id: "texture-colorspace",
    severity: "warn",
    test: (source) => /(TextureLoader|useTexture|useLoader\s*\(\s*TextureLoader)/.test(source) && !/colorSpace|SRGBColorSpace/.test(source),
    anchor: /(TextureLoader|useTexture)/,
    message: "색상 텍스처의 colorSpace 를 지정하지 않았다 — 알베도가 밝고 흐리게 나온다.",
    fix: "색상 맵에는 texture.colorSpace = THREE.SRGBColorSpace, 데이터 맵(노멀·러프니스)에는 지정하지 않는다.",
  },
  {
    id: "context-loss",
    severity: "warn",
    test: (source) => /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(/.test(source) && !/(webglcontextlost|lost|onDeviceLost)/.test(source),
    anchor: /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(/,
    message: "GPU 컨텍스트 손실 처리가 없다 — 모바일 백그라운드 복귀나 드라이버 리셋에서 캔버스가 검게 남는다.",
    fix: "canvas 의 webglcontextlost/webglcontextrestored (WebGPU 는 device.lost) 를 받아 재초기화 경로를 만들어라.",
  },
  {
    id: "heavy-tessellation",
    severity: "warn",
    anchor: /(Sphere|Torus|Cylinder|Plane|TorusKnot)Geometry\s*\([^)]*?(\b(?:1[2-9]\d|[2-9]\d\d|\d{4,})\b)\s*,\s*(\b(?:1[2-9]\d|[2-9]\d\d|\d{4,})\b)/,
    message: "세그먼트 수가 과하다 — 화면에서 구분되지 않는 삼각형에 정점 처리 비용만 낸다.",
    fix: "화면 점유 크기에 맞춰 세그먼트를 줄이고, 필요하면 노멀 맵으로 디테일을 대체하라.",
  },
  {
    id: "placeholder-asset",
    severity: "warn",
    anchor: /(load\s*\(\s*["'](?:#|TODO|placeholder|path\/to)|src\s*=\s*["']path\/to)/i,
    message: "자산 경로가 자리표시자다 — 배달본에서 모델이 로드되지 않는다.",
    fix: "실제 자산 경로로 바꾸고 onError 폴백을 두어라.",
  },
  // ---- 룩 슬롭 — 정적으로 잡히는 초보 티. 판정이 아니라 경보다(취향 규칙은 fail 로 두지 않는다).
  //      씬 루트(렌더러·Canvas 를 만드는 파일)에만 발화시켜, 환경을 다른 파일에서 세팅하는
  //      컴포넌트 분할 코드베이스에서 오탐하지 않게 한다. 렌더에서만 보이는 나머지 초보 티는
  //      look-floor.md 의 사람 검증 몫이다.
  {
    id: "env-missing",
    severity: "warn",
    test: (source) =>
      /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(|<Canvas[\s>]/.test(source) &&
      /new\s+(THREE\.)?Mesh(Standard|Physical)Material|GLTFLoader|useGLTF/.test(source) &&
      !/environment|envmap|pmrem/i.test(source),
    anchor: /new\s+(THREE\.)?(WebGLRenderer|WebGPURenderer)\s*\(|<Canvas[\s>]/,
    message: "PBR 머티리얼을 쓰는 씬에 환경 조명이 없다 — 금속은 검게, 전체는 플라스틱으로 보인다. 환경광이 재질을 만든다.",
    fix: "scene.environment 에 HDRI(PMREMGenerator) 또는 RoomEnvironment 를 넣어라. R3F 는 drei 의 <Environment> 한 줄이다.",
  },
  {
    id: "ambient-only-lighting",
    severity: "warn",
    test: (source) =>
      /new\s+(THREE\.)?AmbientLight\s*\(|<ambientLight[\s/>]/.test(source) &&
      !/(Directional|Spot|Point|Hemisphere|RectArea)Light|directionalLight|spotLight|pointLight|hemisphereLight|rectAreaLight|environment|envmap|pmrem/i.test(
        source,
      ),
    anchor: /new\s+(THREE\.)?AmbientLight\s*\(|<ambientLight[\s/>]/,
    message: "조명이 AmbientLight 뿐이다 — 방향 없는 빛은 음영을 지워 모든 면이 같은 밝기가 된다. 평평한 초보 렌더의 첫째 신호다.",
    fix: "키 라이트(DirectionalLight) 하나와 환경(HDRI/RoomEnvironment)을 세우고, ambient 는 보조로 낮게 깔아라.",
  },
  {
    id: "debug-look-shipped",
    severity: "warn",
    anchor: /new\s+(THREE\.)?MeshNormalMaterial\s*\(|<meshNormalMaterial[\s/>]|wireframe\s*[:=]\s*\{?\s*true/,
    message: "디버그 룩(MeshNormalMaterial·wireframe)이 배달 코드에 남아 있다 — 검증용 표면은 완성 재질이 아니다.",
    fix: "의도된 스타일이면 그렇다고 적고, 아니면 조명·환경을 갖춘 PBR 머티리얼로 바꿔라.",
  },
  {
    id: "primary-color-material",
    severity: "warn",
    test: (source) => /new\s+(THREE\.)?Mesh\w*Material/.test(source),
    anchor: /color\s*[:=(]\s*['"]?(0xff0000|0x00ff00|0x0000ff|#ff0000|#00ff00|#0000ff|red|lime)\b/i,
    message: "머티리얼 색이 순수 원색이다 — 실물에는 없는 알베도라 어떤 조명에서도 장난감처럼 보인다.",
    fix: "알베도 보정 범위(30–240 sRGB) 안의 실측 색을 써라. engine/data/materials.json 의 프리셋이 기준값이다.",
  },
];

const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json"] });
const minSeverity = String(options.severity || "warn");
if (!["warn", "fail"].includes(minSeverity)) fail(`알 수 없는 심각도: ${minSeverity} (가능: warn, fail)`);
const targets = positional.length ? positional : ["."];
const files = [];
for (const target of targets) {
  try {
    collect(target, files);
  } catch (error) {
    fail(`경로를 읽지 못했다: ${target} (${error.message})`);
  }
}

const findings = [];
let scanned = 0;
for (const file of files) {
  const source = readFileSync(file, "utf8");
  if (!/(three|@react-three|WebGPURenderer|useFrame|ScrollTrigger)/.test(source)) continue;
  scanned += 1;
  const judged = stripComments(source);
  const lines = source.split(/\r?\n/);
  for (const rule of RULES) {
    if (rule.test && !rule.test(judged)) continue;
    if (rule.detail) {
      for (const index of rule.detail(lines)) {
        if (isComment(lines[index])) continue;
        findings.push({ rule: rule.id, severity: rule.severity, file, line: index + 1, snippet: lines[index].trim().slice(0, 120), message: rule.message, fix: rule.fix });
      }
      continue;
    }
    const index = lines.findIndex((line) => !isComment(line) && rule.anchor.test(line));
    if (index === -1) continue;
    findings.push({ rule: rule.id, severity: rule.severity, file, line: index + 1, snippet: lines[index].trim().slice(0, 120), message: rule.message, fix: rule.fix });
  }
}

const order = { fail: 0, warn: 1 };
if (minSeverity === "fail") {
  findings.splice(0, findings.length, ...findings.filter((finding) => finding.severity === "fail"));
}
findings.sort((a, b) => order[a.severity] - order[b.severity] || a.file.localeCompare(b.file) || a.line - b.line);
const payload = {
  scannedFiles: scanned,
  totalFiles: files.length,
  findings,
  counts: {
    fail: findings.filter((finding) => finding.severity === "fail").length,
    warn: findings.filter((finding) => finding.severity === "warn").length,
  },
};

if (options.json) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
} else if (!findings.length) {
  process.stdout.write(`3D 소스 ${scanned}개 검사 — 검출 없음.\n`);
} else {
  const lines = [`3D 소스 ${scanned}개 검사 — FAIL ${payload.counts.fail} / WARN ${payload.counts.warn}`, ""];
  for (const finding of findings) {
    lines.push(`[${finding.severity.toUpperCase()}] ${finding.rule}  ${finding.file}:${finding.line}`);
    lines.push(`        ${finding.message}`);
    lines.push(`        고치기: ${finding.fix}`);
    lines.push("");
  }
  process.stdout.write(`${lines.join("\n")}\n`);
}
process.exitCode = payload.counts.fail ? 1 : 0;
