#!/usr/bin/env node
// scene_audit — 웹 배달용 glTF/GLB 를 성능 예산에 비추어 판정한다.
// 사용: node scene_audit.mjs <scene.glb> [--target mobile|desktop] [--json]
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { parseArgs, fail, round } from "./core/cli.mjs";

const BUDGETS = {
  // 출처: reference/budgets.md — 모바일 30~60fps 유지를 위한 실무 기준선.
  mobile: { bytes: 5 * 1024 * 1024, triangles: 150_000, drawCalls: 100, textureBytes: 50 * 1024 * 1024, maxTexture: 1024 },
  desktop: { bytes: 15 * 1024 * 1024, triangles: 1_000_000, drawCalls: 500, textureBytes: 200 * 1024 * 1024, maxTexture: 2048 },
};

const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json"] });
if (!positional.length) fail("사용법: node scene_audit.mjs <scene.glb|gltf> [--target mobile] [--json]");
const target = String(options.target || "mobile");
const budget = BUDGETS[target];
if (!budget) fail(`알 수 없는 대상: ${target} (mobile, desktop)`);

const path = positional[0];
const buffer = readFileSync(path);
let gltf;
let binChunk = null;
if (buffer.length >= 12 && buffer.readUInt32LE(0) === 0x46546c67) {
  let offset = 12;
  while (offset + 8 <= buffer.length) {
    const length = buffer.readUInt32LE(offset);
    const type = buffer.readUInt32LE(offset + 4);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === 0x4e4f534a) gltf = JSON.parse(data.toString("utf8"));
    else if (type === 0x004e4942) binChunk = data;
    offset += 8 + length;
  }
} else {
  gltf = JSON.parse(buffer.toString("utf8"));
}
if (!gltf) fail("glTF JSON 을 읽지 못했다");

const extensions = new Set(gltf.extensionsUsed || []);
const required = new Set(gltf.extensionsRequired || []);

/** 이미지 바이트에서 픽셀 크기를 읽는다 — PNG·JPEG·WebP·KTX2 헤더만 본다. */
function imageSize(bytes) {
  if (!bytes || bytes.length < 16) return null;
  if (bytes[0] === 0x89 && bytes[1] === 0x50) {
    return { format: "png", width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  }
  if (bytes[0] === 0xff && bytes[1] === 0xd8) {
    let offset = 2;
    while (offset + 9 < bytes.length) {
      if (bytes[offset] !== 0xff) {
        offset += 1;
        continue;
      }
      const marker = bytes[offset + 1];
      const length = bytes.readUInt16BE(offset + 2);
      if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
        return { format: "jpeg", height: bytes.readUInt16BE(offset + 5), width: bytes.readUInt16BE(offset + 7) };
      }
      offset += 2 + length;
    }
    return { format: "jpeg", width: 0, height: 0 };
  }
  if (bytes.subarray(0, 4).toString("latin1") === "RIFF" && bytes.subarray(8, 12).toString("latin1") === "WEBP") {
    const chunk = bytes.subarray(12, 16).toString("latin1");
    if (chunk === "VP8X" && bytes.length >= 30) {
      const le24 = (offset) => bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16);
      return { format: "webp", width: 1 + le24(24), height: 1 + le24(27) };
    }
    if (chunk === "VP8 " && bytes.length >= 30 && bytes[23] === 0x9d && bytes[24] === 0x01 && bytes[25] === 0x2a) {
      return { format: "webp", width: bytes.readUInt16LE(26) & 0x3fff, height: bytes.readUInt16LE(28) & 0x3fff };
    }
    if (chunk === "VP8L" && bytes.length >= 25 && bytes[20] === 0x2f) {
      const width = 1 + (((bytes[22] & 0x3f) << 8) | bytes[21]);
      const height = 1 + (((bytes[24] & 0x0f) << 10) | (bytes[23] << 2) | ((bytes[22] & 0xc0) >> 6));
      return { format: "webp", width, height };
    }
    return { format: "webp", width: 0, height: 0 };
  }
  if (bytes[0] === 0xab && bytes.subarray(1, 4).toString("latin1") === "KTX") {
    return { format: "ktx2", width: bytes.readUInt32LE(20), height: bytes.readUInt32LE(24) };
  }
  return null;
}

const buffers = (gltf.buffers || []).map((entry) => {
  if (!entry.uri) return binChunk || Buffer.alloc(0);
  if (entry.uri.startsWith("data:")) return Buffer.from(entry.uri.slice(entry.uri.indexOf(",") + 1), "base64");
  try {
    return readFileSync(resolve(dirname(path), decodeURIComponent(entry.uri)));
  } catch {
    return Buffer.alloc(0);
  }
});

const images = (gltf.images || []).map((image, index) => {
  let bytes = null;
  let external = null;
  if (image.bufferView !== undefined) {
    const view = gltf.bufferViews[image.bufferView];
    bytes = buffers[view.buffer]?.subarray(view.byteOffset || 0, (view.byteOffset || 0) + view.byteLength);
  } else if (image.uri && !image.uri.startsWith("data:")) {
    external = image.uri;
    try {
      bytes = readFileSync(resolve(dirname(path), decodeURIComponent(image.uri)));
    } catch {
      bytes = null;
    }
  } else if (image.uri) {
    bytes = Buffer.from(image.uri.slice(image.uri.indexOf(",") + 1), "base64");
  }
  const size = imageSize(bytes);
  return {
    index,
    name: image.name || external || `image${index}`,
    mimeType: image.mimeType || size?.format || "unknown",
    width: size?.width || 0,
    height: size?.height || 0,
    bytes: bytes?.length || 0,
    external,
    compressed: size?.format === "ktx2" || image.mimeType === "image/ktx2",
  };
});

let triangles = 0;
let primitives = 0;
let compressedPrimitives = 0;
let morphTargets = 0;
const meshUsage = new Map(); // 노드 배치 수 — 드로우콜과 삼각형 양쪽의 배수.
const gpuExtra = new Map(); // EXT_mesh_gpu_instancing 추가분 — 삼각형에만 곱한다(드로우콜은 1콜).
for (const node of gltf.nodes || []) {
  if (node.mesh === undefined) continue;
  meshUsage.set(node.mesh, (meshUsage.get(node.mesh) || 0) + 1);
  const attribute = Object.values(node.extensions?.EXT_mesh_gpu_instancing?.attributes || {})[0];
  const count = attribute !== undefined ? gltf.accessors?.[attribute]?.count || 1 : 1;
  if (count > 1) gpuExtra.set(node.mesh, (gpuExtra.get(node.mesh) || 0) + count - 1);
}
for (const [meshIndex, mesh] of (gltf.meshes || []).entries()) {
  const instances = meshUsage.get(meshIndex) || 1;
  const triangleInstances = instances + (gpuExtra.get(meshIndex) || 0);
  for (const primitive of mesh.primitives || []) {
    primitives += instances;
    morphTargets += (primitive.targets || []).length;
    const draco = primitive.extensions?.KHR_draco_mesh_compression;
    if (draco) compressedPrimitives += 1;
    let count = 0;
    if (primitive.indices !== undefined) count = gltf.accessors[primitive.indices].count;
    else if (primitive.attributes?.POSITION !== undefined) count = gltf.accessors[primitive.attributes.POSITION].count;
    else if (draco) count = 0;
    triangles += Math.floor(count / 3) * triangleInstances;
  }
}

const textureBytes = images.reduce((sum, image) => {
  if (!image.width || !image.height) return sum;
  const texels = image.width * image.height * 1.33; // 밉맵 체인 포함.
  return sum + Math.round(texels * (image.compressed ? 1 : 4));
}, 0);
const oversized = images.filter((image) => Math.max(image.width, image.height) > budget.maxTexture);
const uncompressed = images.filter((image) => !image.compressed);

const checks = [];
const add = (id, level, message, evidence) => checks.push({ id, level, message, ...(evidence ? { evidence } : {}) });
const verdictFor = (value, limit) => (value > limit ? "fail" : value > limit * 0.75 ? "warn" : "pass");

// .gltf 는 본체가 JSON 뿐이다 — 외부 .bin·이미지를 합쳐야 실제 다운로드 예산이다.
const externalBufferBytes = (gltf.buffers || []).reduce(
  (sum, entry, index) => (entry.uri && !entry.uri.startsWith("data:") ? sum + (buffers[index]?.length || 0) : sum),
  0,
);
const externalImageBytes = images.reduce((sum, image) => (image.external ? sum + image.bytes : sum), 0);
const downloadBytes = buffer.length + externalBufferBytes + externalImageBytes;
add(
  "filesize",
  verdictFor(downloadBytes, budget.bytes),
  `다운로드 ${(downloadBytes / 1024 / 1024).toFixed(2)}MB / 예산 ${(budget.bytes / 1024 / 1024).toFixed(0)}MB (${target})` +
    (downloadBytes > buffer.length ? ` — 외부 파일 ${((externalBufferBytes + externalImageBytes) / 1024 / 1024).toFixed(2)}MB 포함` : ""),
);
add("triangles", verdictFor(triangles, budget.triangles), `삼각형 ${triangles.toLocaleString()} / 예산 ${budget.triangles.toLocaleString()}`);
add(
  "drawcalls",
  verdictFor(primitives, budget.drawCalls),
  `드로우콜(프리미티브×인스턴스) ${primitives} / 예산 ${budget.drawCalls} — 삼각형보다 이 숫자가 프레임을 결정한다.`,
);
add(
  "texturememory",
  verdictFor(textureBytes, budget.textureBytes),
  `추정 텍스처 VRAM ${(textureBytes / 1024 / 1024).toFixed(1)}MB / 예산 ${(budget.textureBytes / 1024 / 1024).toFixed(0)}MB`,
);
if (oversized.length) {
  add("textureresolution", "warn", `${budget.maxTexture}px 를 넘는 텍스처 ${oversized.length}장`, {
    images: oversized.map((image) => `${image.name} ${image.width}×${image.height}`),
  });
}
if (images.length && uncompressed.length === images.length) {
  add(
    "gputexture",
    "warn",
    "KTX2/Basis 로 압축된 텍스처가 하나도 없다 — GPU 에 올라간 뒤에도 비압축이라 VRAM 을 그대로 먹는다.",
  );
} else if (uncompressed.length) {
  add("gputexture", "pass", `KTX2 압축 ${images.length - uncompressed.length}/${images.length}장`);
}
const geometryCompressed = extensions.has("KHR_draco_mesh_compression") || extensions.has("EXT_meshopt_compression");
add(
  "geometrycompression",
  geometryCompressed ? "pass" : triangles > 50_000 ? "warn" : "pass",
  geometryCompressed
    ? `지오메트리 압축 적용: ${[...extensions].filter((name) => name.includes("draco") || name.includes("meshopt")).join(", ")}`
    : "지오메트리 압축이 없다 — meshopt(디코드가 빠르다) 또는 Draco(압축률이 높다) 중 하나를 적용하라.",
);
if (required.size) {
  add("required", "warn", `필수 확장 ${[...required].join(", ")} — 로더에 대응 디코더가 없으면 씬 전체가 로드되지 않는다.`);
}
if (images.some((image) => image.external)) {
  add("packaging", "warn", "외부 이미지 참조가 있다 — 배포 시 요청 수가 늘어난다. GLB 로 묶거나 프리로드하라.");
}
if (morphTargets > 0 || (gltf.skins || []).length) {
  add("animation", "pass", `애니메이션 자산: 스킨 ${(gltf.skins || []).length}, 모프 타깃 ${morphTargets}, 클립 ${(gltf.animations || []).length}`);
}

const payload = {
  scene: path,
  target,
  bytes: buffer.length,
  triangles,
  drawCalls: primitives,
  meshes: (gltf.meshes || []).length,
  nodes: (gltf.nodes || []).length,
  materials: (gltf.materials || []).length,
  images: images.map(({ index, name, mimeType, width, height, bytes, compressed }) => ({ index, name, mimeType, width, height, bytes, compressed })),
  textureVramEstimate: textureBytes,
  extensions: [...extensions],
  extensionsRequired: [...required],
  animations: (gltf.animations || []).length,
  compressedPrimitives,
  budget,
  checks,
  verdict: checks.some((check) => check.level === "fail") ? "fail" : checks.some((check) => check.level === "warn") ? "warn" : "pass",
};

if (options.json) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
} else {
  const mark = { pass: "PASS", warn: "WARN", fail: "FAIL" };
  process.stdout.write(
    [
      `씬       ${path}  (대상 ${target})`,
      `규모     삼각형 ${triangles.toLocaleString()}   드로우콜 ${primitives}   재질 ${payload.materials}   이미지 ${images.length}`,
      "",
      ...checks.map((check) => `[${mark[check.level]}] ${check.id.padEnd(18)} ${check.message}`),
      "",
      `판정     ${payload.verdict.toUpperCase()}`,
    ].join("\n") + "\n",
  );
}
process.exitCode = payload.verdict === "fail" ? 1 : 0;
