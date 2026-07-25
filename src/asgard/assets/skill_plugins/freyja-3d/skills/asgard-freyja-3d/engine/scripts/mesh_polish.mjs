#!/usr/bin/env node
// mesh_polish — CAD 패싯을 게임 자산으로. 커널이 내뱉는 지오메트리는 평면 셰이딩 그대로라
// 게임·제품 뷰에서 조잡해 보인다. 여기서 용접·크리스 스무딩·PBR 머티리얼을 입혀
// 게임 준비(glTF PBR) GLB 로 다시 쓴다. 의존성 없음.
// 사용: node mesh_polish.mjs <model.stl|obj|glb|gltf|3mf> --out polished.glb
//       [--crease 40] [--material steel] [--materials '{"blade":"steel","grip":"leather"}']
//       [--up z|y|auto] [--json]
// 머티리얼 값은 프리셋 이름 또는 "#RRGGBB,metallic,roughness" 커스텀.
import { readFileSync, writeFileSync } from "node:fs";
import { extname } from "node:path";
import { pathToFileURL } from "node:url";
import { loadMesh } from "./core/mesh.mjs";
import { bounds, buildGrid, faces, raycast } from "./core/geom.mjs";
import { parseArgs, fail, round } from "./core/cli.mjs";

// 재질 라이브러리의 정본은 engine/data/materials.json 하나다 — 문서·검출기·폴리시가 같은 값을 읽는다.
export const MATERIAL_PRESETS = Object.fromEntries(
  Object.entries(JSON.parse(readFileSync(new URL("../data/materials.json", import.meta.url), "utf8")).presets).map(
    ([name, preset]) => [name, { baseColor: preset.baseColor, metallic: preset.metallic, roughness: preset.roughness }],
  ),
);

function resolveMaterial(value) {
  if (MATERIAL_PRESETS[value]) return { name: value, ...MATERIAL_PRESETS[value] };
  const custom = /^#([0-9a-f]{6})(?:,([\d.]+))?(?:,([\d.]+))?$/i.exec(String(value));
  if (!custom) return null;
  const hex = Number.parseInt(custom[1], 16);
  return {
    name: value,
    baseColor: [((hex >> 16) & 255) / 255, ((hex >> 8) & 255) / 255, (hex & 255) / 255, 1],
    metallic: custom[2] !== undefined ? Number(custom[2]) : 0,
    roughness: custom[3] !== undefined ? Number(custom[3]) : 0.5,
  };
}

/** 크리스 각 기준 스무스 노멀 — 코너마다, 같은 정점을 쓰는 이웃 면 중 법선 차가 크리스 미만인 것만 평균한다. */
export function smoothNormals(positions, creaseDeg = 40) {
  const faceCount = positions.length / 9;
  const faceNormals = new Float64Array(faceCount * 3);
  const faceAreas = new Float64Array(faceCount);
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = positions[i + axis];
      if (value < min[axis]) min[axis] = value;
      if (value > max[axis]) max[axis] = value;
    }
  }
  const diag = Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) || 1;
  const tolerance = diag * 1e-6;
  const key = (index) =>
    `${Math.round(positions[index] / tolerance)},${Math.round(positions[index + 1] / tolerance)},${Math.round(positions[index + 2] / tolerance)}`;

  const adjacency = new Map(); // 정점 키 → 면 목록
  for (let face = 0; face < faceCount; face += 1) {
    const base = face * 9;
    const ux = positions[base + 3] - positions[base];
    const uy = positions[base + 4] - positions[base + 1];
    const uz = positions[base + 5] - positions[base + 2];
    const vx = positions[base + 6] - positions[base];
    const vy = positions[base + 7] - positions[base + 1];
    const vz = positions[base + 8] - positions[base + 2];
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const length = Math.hypot(nx, ny, nz);
    faceAreas[face] = length / 2;
    if (length > 0) {
      nx /= length;
      ny /= length;
      nz /= length;
    }
    faceNormals[face * 3] = nx;
    faceNormals[face * 3 + 1] = ny;
    faceNormals[face * 3 + 2] = nz;
    for (let corner = 0; corner < 3; corner += 1) {
      const vertexKey = key(base + corner * 3);
      if (!adjacency.has(vertexKey)) adjacency.set(vertexKey, []);
      adjacency.get(vertexKey).push(face);
    }
  }

  const cosCrease = Math.cos((creaseDeg * Math.PI) / 180);
  const normals = new Float32Array(positions.length);
  for (let face = 0; face < faceCount; face += 1) {
    const base = face * 9;
    const fx = faceNormals[face * 3];
    const fy = faceNormals[face * 3 + 1];
    const fz = faceNormals[face * 3 + 2];
    for (let corner = 0; corner < 3; corner += 1) {
      let nx = 0;
      let ny = 0;
      let nz = 0;
      for (const neighbor of adjacency.get(key(base + corner * 3))) {
        const gx = faceNormals[neighbor * 3];
        const gy = faceNormals[neighbor * 3 + 1];
        const gz = faceNormals[neighbor * 3 + 2];
        if (fx * gx + fy * gy + fz * gz < cosCrease) continue;
        const weight = faceAreas[neighbor];
        nx += gx * weight;
        ny += gy * weight;
        nz += gz * weight;
      }
      const length = Math.hypot(nx, ny, nz);
      if (length > 0) {
        nx /= length;
        ny /= length;
        nz /= length;
      } else {
        nx = fx;
        ny = fy;
        nz = fz;
      }
      normals[base + corner * 3] = nx;
      normals[base + corner * 3 + 1] = ny;
      normals[base + corner * 3 + 2] = nz;
    }
  }
  return normals;
}

/**
 * 마스크 베이크 — 게임 텍스처링의 두 원료를 메시에서 실측한다.
 * R = AO(반구 코사인 가중 레이캐스트, 몬테카를로), G = 볼록 엣지(마모가 앉는 곳),
 * B = 오목 캐비티(그라임이 고이는 곳). occluder 는 조립 전체를 쓴다 — 가드가 날 뿌리를 가린다.
 */
export function bakeMasks(positions, occluderPositions, { samples = 24, rangeRatio = 0.05 } = {}) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < occluderPositions.length; i += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = occluderPositions[i + axis];
      if (value < min[axis]) min[axis] = value;
      if (value > max[axis]) max[axis] = value;
    }
  }
  const diag = Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) || 1;
  const range = diag * rangeRatio;
  const epsilon = diag * 2e-4;
  const tolerance = diag * 1e-6;
  // 코어 buildGrid 는 최장축 기준 큐브 셀이라 길쭉한 조립체에서 셀이 비대해진다.
  // AO 사거리에 맞춘 세밀 격자를 같은 구조체로 만들어 코어 raycast 에 그대로 꽂는다.
  const grid = (() => {
    const cell = Math.max(range / 6, diag / 512);
    const dims = [0, 1, 2].map((axis) => Math.max(1, Math.min(512, Math.ceil((max[axis] - min[axis]) / cell) || 1)));
    const buckets = new Map();
    const clampIndex = (value, axis) =>
      Math.max(0, Math.min(dims[axis] - 1, Math.floor((value - min[axis]) / cell)));
    const occluderFaces = occluderPositions.length / 9;
    for (let face = 0; face < occluderFaces; face += 1) {
      const base = face * 9;
      const lo = [0, 1, 2].map((axis) =>
        clampIndex(
          Math.min(occluderPositions[base + axis], occluderPositions[base + 3 + axis], occluderPositions[base + 6 + axis]),
          axis,
        ),
      );
      const hi = [0, 1, 2].map((axis) =>
        clampIndex(
          Math.max(occluderPositions[base + axis], occluderPositions[base + 3 + axis], occluderPositions[base + 6 + axis]),
          axis,
        ),
      );
      for (let x = lo[0]; x <= hi[0]; x += 1) {
        for (let y = lo[1]; y <= hi[1]; y += 1) {
          for (let z = lo[2]; z <= hi[2]; z += 1) {
            const bucketKey = (z * dims[1] + y) * dims[0] + x;
            const bucket = buckets.get(bucketKey);
            if (bucket) bucket.push(face);
            else buckets.set(bucketKey, [face]);
          }
        }
      }
    }
    return { dims, cell, min: [...min], buckets };
  })();

  const faceCount = positions.length / 9;
  const key = (index) =>
    `${Math.round(positions[index] / tolerance)},${Math.round(positions[index + 1] / tolerance)},${Math.round(positions[index + 2] / tolerance)}`;

  // 정점 단위 집계: 평균 법선(베이크 방향), 부호 있는 이면각(커버처)
  const vertexData = new Map(); // key → { n:[3], p:[3], signedAngle, edgeCount }
  const faceNormals = new Float64Array(faceCount * 3);
  const faceCenters = new Float64Array(faceCount * 3);
  const edgeFaces = new Map(); // 에지 키 → [faceIndex]
  for (let face = 0; face < faceCount; face += 1) {
    const base = face * 9;
    const ux = positions[base + 3] - positions[base];
    const uy = positions[base + 4] - positions[base + 1];
    const uz = positions[base + 5] - positions[base + 2];
    const vx = positions[base + 6] - positions[base];
    const vy = positions[base + 7] - positions[base + 1];
    const vz = positions[base + 8] - positions[base + 2];
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const area = Math.hypot(nx, ny, nz);
    if (area > 0) {
      nx /= area;
      ny /= area;
      nz /= area;
    }
    faceNormals.set([nx, ny, nz], face * 3);
    for (let axis = 0; axis < 3; axis += 1) {
      faceCenters[face * 3 + axis] =
        (positions[base + axis] + positions[base + 3 + axis] + positions[base + 6 + axis]) / 3;
    }
    const cornerKeys = [key(base), key(base + 3), key(base + 6)];
    for (let corner = 0; corner < 3; corner += 1) {
      const vertexKey = cornerKeys[corner];
      if (!vertexData.has(vertexKey)) {
        vertexData.set(vertexKey, {
          p: [positions[base + corner * 3], positions[base + corner * 3 + 1], positions[base + corner * 3 + 2]],
          n: [0, 0, 0],
          signedAngle: 0,
          edgeCount: 0,
        });
      }
      const entry = vertexData.get(vertexKey);
      entry.n[0] += nx * area;
      entry.n[1] += ny * area;
      entry.n[2] += nz * area;
      const edgeKey = [cornerKeys[corner], cornerKeys[(corner + 1) % 3]].sort().join("|");
      if (!edgeFaces.has(edgeKey)) edgeFaces.set(edgeKey, []);
      edgeFaces.get(edgeKey).push(face);
    }
  }

  // 이면각: 볼록(+) = 마모, 오목(−) = 그라임. 볼록 판정은 이웃 면심이 내 법선 반대쪽에 있는가로.
  for (const [edgeKey, facesOnEdge] of edgeFaces) {
    if (facesOnEdge.length !== 2) continue;
    const [f1, f2] = facesOnEdge;
    const dot =
      faceNormals[f1 * 3] * faceNormals[f2 * 3] +
      faceNormals[f1 * 3 + 1] * faceNormals[f2 * 3 + 1] +
      faceNormals[f1 * 3 + 2] * faceNormals[f2 * 3 + 2];
    const angle = Math.acos(Math.max(-1, Math.min(1, dot)));
    if (angle < 0.03) continue; // 사실상 평탄
    const toward =
      faceNormals[f1 * 3] * (faceCenters[f2 * 3] - faceCenters[f1 * 3]) +
      faceNormals[f1 * 3 + 1] * (faceCenters[f2 * 3 + 1] - faceCenters[f1 * 3 + 1]) +
      faceNormals[f1 * 3 + 2] * (faceCenters[f2 * 3 + 2] - faceCenters[f1 * 3 + 2]);
    const signed = toward < 0 ? angle : -angle;
    for (const vertexKey of edgeKey.split("|")) {
      const entry = vertexData.get(vertexKey);
      if (!entry) continue;
      entry.signedAngle += signed;
      entry.edgeCount += 1;
    }
  }

  // AO: 정점 법선 반구를 골든 나선(코사인 가중)으로 샘플링, 거리 감쇠 차폐.
  const GOLDEN = Math.PI * (3 - Math.sqrt(5));
  const baked = new Map(); // key → [ao, edge, cavity]
  for (const [vertexKey, entry] of vertexData) {
    let [nx, ny, nz] = entry.n;
    const length = Math.hypot(nx, ny, nz) || 1;
    nx /= length;
    ny /= length;
    nz /= length;
    // 법선 기준 정규직교 기저
    const ax = Math.abs(nx) < 0.9 ? 1 : 0;
    const ay = Math.abs(nx) < 0.9 ? 0 : 1;
    let tx = ay * nz - 0 * ny;
    let ty = 0 * nx - ax * nz;
    let tz = ax * ny - ay * nx;
    const tlen = Math.hypot(tx, ty, tz) || 1;
    tx /= tlen;
    ty /= tlen;
    tz /= tlen;
    const bx = ny * tz - nz * ty;
    const by = nz * tx - nx * tz;
    const bz = nx * ty - ny * tx;
    const origin = [entry.p[0] + nx * epsilon, entry.p[1] + ny * epsilon, entry.p[2] + nz * epsilon];
    let occlusion = 0;
    for (let s = 0; s < samples; s += 1) {
      const u = (s + 0.5) / samples;
      const radial = Math.sqrt(u);
      const height = Math.sqrt(1 - u);
      const phi = s * GOLDEN;
      const lx = Math.cos(phi) * radial;
      const ly = Math.sin(phi) * radial;
      const dir = [
        tx * lx + bx * ly + nx * height,
        ty * lx + by * ly + ny * height,
        tz * lx + bz * ly + nz * height,
      ];
      const distance = raycast(occluderPositions, grid, origin, dir, range);
      if (Number.isFinite(distance) && distance < range) occlusion += 1 - distance / range;
    }
    const ao = Math.max(0, Math.min(1, 1 - occlusion / samples));
    const mean = entry.edgeCount ? entry.signedAngle / entry.edgeCount : 0;
    const edge = Math.max(0, Math.min(1, mean / (Math.PI / 4)));
    const cavity = Math.max(0, Math.min(1, -mean / (Math.PI / 4)));
    baked.set(vertexKey, [ao, edge, cavity]);
  }

  const colors = new Float32Array(positions.length);
  for (let i = 0; i < positions.length; i += 3) {
    const value = baked.get(key(i));
    colors[i] = value[0];
    colors[i + 1] = value[1];
    colors[i + 2] = value[2];
  }
  return colors;
}

/** (위치, 법선) 쌍 기준 용접 인덱싱 — 크리스 경계는 정점이 갈라진 채 남는다. 컬러(베이크 마스크)는 위치 종속이라 함께 탄다. */
export function indexMesh(positions, normals, colors = null) {
  const seen = new Map();
  const vertices = [];
  const colorOut = [];
  const indices = [];
  for (let i = 0; i < positions.length; i += 3) {
    const vertexKey = `${positions[i].toFixed(5)},${positions[i + 1].toFixed(5)},${positions[i + 2].toFixed(5)}|${normals[i].toFixed(3)},${normals[i + 1].toFixed(3)},${normals[i + 2].toFixed(3)}`;
    let index = seen.get(vertexKey);
    if (index === undefined) {
      index = vertices.length / 6;
      seen.set(vertexKey, index);
      vertices.push(positions[i], positions[i + 1], positions[i + 2], normals[i], normals[i + 1], normals[i + 2]);
      if (colors) colorOut.push(colors[i], colors[i + 1], colors[i + 2]);
    }
    indices.push(index);
  }
  return {
    vertices: Float32Array.from(vertices),
    indices: Uint32Array.from(indices),
    colors: colors ? Float32Array.from(colorOut) : null,
  };
}

function align4(chunks) {
  let total = 0;
  for (const chunk of chunks) total += chunk.length;
  const padding = (4 - (total % 4)) % 4;
  return padding ? [...chunks, Buffer.alloc(padding)] : chunks;
}

export function writeGlb(outPath, parts) {
  const bufferViews = [];
  const accessors = [];
  const meshes = [];
  const nodes = [];
  const materials = [];
  const materialIndex = new Map();
  let binChunks = [];
  let byteOffset = 0;

  const pushView = (data, target) => {
    const buffer = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
    bufferViews.push({ buffer: 0, byteOffset, byteLength: buffer.length, ...(target ? { target } : {}) });
    binChunks.push(buffer);
    byteOffset += buffer.length;
    const padding = (4 - (byteOffset % 4)) % 4;
    if (padding) {
      binChunks.push(Buffer.alloc(padding));
      byteOffset += padding;
    }
    return bufferViews.length - 1;
  };

  for (const part of parts) {
    const { vertices, indices } = part;
    const vertexCount = vertices.length / 6;
    const positions = new Float32Array(vertexCount * 3);
    const normals = new Float32Array(vertexCount * 3);
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < vertexCount; i += 1) {
      for (let axis = 0; axis < 3; axis += 1) {
        const value = vertices[i * 6 + axis];
        positions[i * 3 + axis] = value;
        normals[i * 3 + axis] = vertices[i * 6 + 3 + axis];
        if (value < min[axis]) min[axis] = value;
        if (value > max[axis]) max[axis] = value;
      }
    }
    if (!materialIndex.has(part.material.name)) {
      materialIndex.set(part.material.name, materials.length);
      materials.push({
        name: part.material.name,
        pbrMetallicRoughness: {
          baseColorFactor: part.material.baseColor,
          metallicFactor: part.material.metallic,
          roughnessFactor: part.material.roughness,
        },
      });
    }
    const positionView = pushView(positions, 34962);
    const normalView = pushView(normals, 34962);
    const indexView = pushView(indices, 34963);
    const positionAccessor = accessors.length;
    accessors.push({ bufferView: positionView, componentType: 5126, count: vertexCount, type: "VEC3", min, max });
    accessors.push({ bufferView: normalView, componentType: 5126, count: vertexCount, type: "VEC3" });
    accessors.push({ bufferView: indexView, componentType: 5125, count: indices.length, type: "SCALAR" });
    const attributes = { POSITION: positionAccessor, NORMAL: positionAccessor + 1 };
    if (part.colors) {
      const colorView = pushView(part.colors, 34962);
      attributes.COLOR_0 = accessors.length;
      accessors.push({ bufferView: colorView, componentType: 5126, count: vertexCount, type: "VEC3" });
    }
    meshes.push({
      name: part.name,
      primitives: [
        {
          attributes,
          indices: positionAccessor + 2,
          material: materialIndex.get(part.material.name),
        },
      ],
    });
    nodes.push({ name: part.name, mesh: meshes.length - 1 });
  }

  binChunks = align4(binChunks);
  const binLength = binChunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const gltf = {
    asset: { version: "2.0", generator: "brisingamen mesh_polish" },
    scene: 0,
    scenes: [{ nodes: nodes.map((_, index) => index) }],
    nodes,
    meshes,
    materials,
    accessors,
    bufferViews,
    buffers: [{ byteLength: binLength }],
  };
  let jsonChunk = Buffer.from(JSON.stringify(gltf), "utf8");
  const jsonPadding = (4 - (jsonChunk.length % 4)) % 4;
  if (jsonPadding) jsonChunk = Buffer.concat([jsonChunk, Buffer.alloc(jsonPadding, 0x20)]);
  const header = Buffer.alloc(12);
  header.writeUInt32LE(0x46546c67, 0);
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(12 + 8 + jsonChunk.length + 8 + binLength, 8);
  const jsonHeader = Buffer.alloc(8);
  jsonHeader.writeUInt32LE(jsonChunk.length, 0);
  jsonHeader.writeUInt32LE(0x4e4f534a, 4);
  const binHeader = Buffer.alloc(8);
  binHeader.writeUInt32LE(binLength, 0);
  binHeader.writeUInt32LE(0x004e4942, 4);
  writeFileSync(outPath, Buffer.concat([header, jsonHeader, jsonChunk, binHeader, ...binChunks]));
}

function toYUp(positions) {
  const out = new Float32Array(positions.length);
  for (let i = 0; i < positions.length; i += 3) {
    out[i] = positions[i];
    out[i + 1] = positions[i + 2];
    out[i + 2] = -positions[i + 1];
  }
  return out;
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const { positional, options } = parseArgs(process.argv.slice(2), { flags: ["json", "bake"] });
  if (!positional.length) {
    fail("사용법: node mesh_polish.mjs <model> --out polished.glb [--crease 40] [--materials JSON] [--bake] [--ao-samples 32]");
  }
  const outPath = String(options.out || "polished.glb");
  const creaseDeg = Number(options.crease || 40);
  const fallback = resolveMaterial(String(options.material || "plastic"));
  if (!fallback) fail(`알 수 없는 머티리얼: ${options.material} (프리셋: ${Object.keys(MATERIAL_PRESETS).join(", ")})`);
  let materialMap = {};
  if (options.materials) {
    try {
      materialMap = JSON.parse(String(options.materials));
    } catch (error) {
      fail(`--materials JSON 을 읽지 못했다: ${error.message}`);
    }
  }

  let mesh;
  try {
    mesh = loadMesh(positional[0]);
  } catch (error) {
    fail(`모델을 읽지 못했다: ${positional[0]} — ${error.message}`);
  }
  const isGltf = [".glb", ".gltf"].includes(extname(positional[0]).toLowerCase());
  const upMode = String(options.up || "auto");
  const convert = upMode === "y" || (upMode === "auto" && !isGltf); // glTF 출력은 Y-up 이 규격이다.

  // CAD 내보내기는 면마다 프리미티브를 쪼갠다 — 같은 이름은 병합해야 스무딩이 조각 경계를 넘고
  // 드로우콜도 부품당 1이 된다.
  const merged = new Map();
  for (const part of mesh.parts) {
    if (!merged.has(part.name)) merged.set(part.name, []);
    merged.get(part.name).push(part.positions);
  }
  const combinedParts = [...merged].map(([name, buffers]) => {
    const total = buffers.reduce((sum, positions) => sum + positions.length, 0);
    let combined = new Float32Array(total);
    let cursor = 0;
    for (const positions of buffers) {
      combined.set(positions, cursor);
      cursor += positions.length;
    }
    if (convert) combined = toYUp(combined);
    return { name, positions: combined };
  });

  // 베이크의 차폐물은 조립 전체다 — 가드가 날 뿌리를, 아치가 베이스를 가린다.
  let occluder = null;
  if (options.bake) {
    const total = combinedParts.reduce((sum, part) => sum + part.positions.length, 0);
    occluder = new Float32Array(total);
    let cursor = 0;
    for (const part of combinedParts) {
      occluder.set(part.positions, cursor);
      cursor += part.positions.length;
    }
  }

  const parts = combinedParts.map(({ name, positions }) => {
    const normals = smoothNormals(positions, creaseDeg);
    const masks = options.bake
      ? bakeMasks(positions, occluder, { samples: Number(options["ao-samples"] || 32) })
      : null;
    const { vertices, indices, colors } = indexMesh(positions, normals, masks);
    const assigned = materialMap[name] !== undefined ? resolveMaterial(materialMap[name]) : fallback;
    if (!assigned) fail(`알 수 없는 머티리얼: ${materialMap[name]} (부품 ${name})`);
    return { name, vertices, indices, colors, material: assigned };
  });
  writeGlb(outPath, parts);

  const payload = {
    source: positional[0],
    out: outPath,
    creaseDeg,
    parts: parts.map((part) => {
      const entry = {
        name: part.name,
        material: part.material.name,
        vertices: part.vertices.length / 6,
        triangles: part.indices.length / 3,
      };
      if (part.colors) {
        let aoSum = 0;
        let edgeSum = 0;
        for (let i = 0; i < part.colors.length; i += 3) {
          aoSum += part.colors[i];
          edgeSum += part.colors[i + 1];
        }
        const count = part.colors.length / 3;
        entry.bake = { aoMean: round(aoSum / count, 3), edgeMean: round(edgeSum / count, 3) };
      }
      return entry;
    }),
    triangles: parts.reduce((sum, part) => sum + part.indices.length / 3, 0),
    vertices: parts.reduce((sum, part) => sum + part.vertices.length / 6, 0),
  };
  if (options.json) process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
  else {
    const lines = [`폴리시  ${positional[0]} → ${outPath}  (크리스 ${creaseDeg}°)`];
    for (const part of payload.parts) {
      lines.push(`  ${part.name.padEnd(16)} 삼각형 ${part.triangles}  정점 ${part.vertices}  머티리얼 ${part.material}`);
    }
    lines.push(`  검증: scene_audit.mjs 로 예산을, shoot.mjs 로 형상을 다시 확인하라.`);
    process.stdout.write(`${lines.join("\n")}\n`);
  }
}
