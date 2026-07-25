// 메시 로더 — STL(binary/ascii) · OBJ · glTF/GLB · 3MF. 의존성 없음.
// 반환 형태: { parts: [{ name, positions: Float32Array(9*tri), materialIndex }], source, gltf?, warnings: [] }
import { readFileSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";
import { inflateRawSync } from "node:zlib";

const COMPONENT = {
  5120: { array: Int8Array, size: 1 },
  5121: { array: Uint8Array, size: 1 },
  5122: { array: Int16Array, size: 2 },
  5123: { array: Uint16Array, size: 2 },
  5125: { array: Uint32Array, size: 4 },
  5126: { array: Float32Array, size: 4 },
};
const TYPE_COUNT = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };

function loadStl(buffer) {
  const text = buffer.subarray(0, Math.min(buffer.length, 512)).toString("latin1");
  const asciiHeader = text.trimStart().startsWith("solid");
  const expectedBinary = buffer.length >= 84 ? 84 + buffer.readUInt32LE(80) * 50 : -1;
  if (!asciiHeader || expectedBinary === buffer.length) {
    if (buffer.length < 84) throw new Error("바이너리 STL 헤더(84바이트)조차 없다 — STL 이 아니거나 손상된 파일이다");
    const count = buffer.readUInt32LE(80);
    const capacity = Math.floor((buffer.length - 84) / 50);
    if (count > capacity) {
      throw new Error(`손상된 바이너리 STL — 헤더는 삼각형 ${count}개를 선언하지만 파일에는 ${capacity}개 분량만 있다`);
    }
    const positions = new Float32Array(count * 9);
    for (let i = 0; i < count; i += 1) {
      const base = 84 + i * 50 + 12; // 법선 12바이트는 버리고 정점에서 다시 계산한다.
      for (let v = 0; v < 9; v += 1) positions[i * 9 + v] = buffer.readFloatLE(base + v * 4);
    }
    return { parts: [{ name: "stl", positions, materialIndex: -1 }], warnings: [] };
  }
  const values = [];
  const source = buffer.toString("utf8");
  const re = /vertex\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)/g;
  let match = re.exec(source);
  while (match) {
    values.push(Number(match[1]), Number(match[2]), Number(match[3]));
    match = re.exec(source);
  }
  return { parts: [{ name: "stl", positions: Float32Array.from(values), materialIndex: -1 }], warnings: [] };
}

function loadObj(buffer) {
  const vertices = [];
  const parts = [];
  let current = { name: "obj", values: [], materialIndex: -1 };
  for (const line of buffer.toString("utf8").split(/\r?\n/)) {
    const token = line.trim().split(/\s+/);
    if (token[0] === "v") {
      vertices.push([Number(token[1]), Number(token[2]), Number(token[3])]);
    } else if (token[0] === "o" || token[0] === "g") {
      if (current.values.length) parts.push(current);
      current = { name: token.slice(1).join(" ") || `part${parts.length}`, values: [], materialIndex: -1 };
    } else if (token[0] === "f") {
      const corners = token.slice(1).map((entry) => {
        const index = Number(entry.split("/")[0]);
        return vertices[index > 0 ? index - 1 : vertices.length + index];
      });
      for (let i = 1; i + 1 < corners.length; i += 1) {
        for (const point of [corners[0], corners[i], corners[i + 1]]) {
          if (point) current.values.push(point[0], point[1], point[2]);
        }
      }
    }
  }
  if (current.values.length) parts.push(current);
  return {
    parts: parts.map((part) => ({
      name: part.name,
      positions: Float32Array.from(part.values),
      materialIndex: part.materialIndex,
    })),
    warnings: [],
  };
}

// ── 3MF — OPC(ZIP) 패키지 + 3dmodel.model XML. 제조 납품 표준이라 검증 루프에서 빠질 수 없다. ──
const THREEMF_UNIT_TO_MM = { micron: 0.001, millimeter: 1, centimeter: 10, inch: 25.4, foot: 304.8, meter: 1000 };

function zipEntries(buffer) {
  let eocd = -1;
  const scanStart = Math.max(0, buffer.length - 65557); // EOCD 22B + 주석 최대 64KB.
  for (let i = buffer.length - 22; i >= scanStart; i -= 1) {
    if (buffer.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("ZIP 중앙 디렉터리 끝(EOCD)이 없다 — 3MF(ZIP) 파일이 아니거나 손상됐다");
  let count = buffer.readUInt16LE(eocd + 10);
  let offset = buffer.readUInt32LE(eocd + 16);
  if (count === 0xffff || offset === 0xffffffff) {
    // ZIP64 — lib3mf 등 실제 기록기가 쓴다. EOCD 로케이터(PK 06 07)가 EOCD 바로 앞에 온다.
    let z64 = -1;
    if (eocd >= 20 && buffer.readUInt32LE(eocd - 20) === 0x07064b50) {
      z64 = Number(buffer.readBigUInt64LE(eocd - 20 + 8));
    } else {
      for (let i = eocd - 56; i >= Math.max(0, eocd - 65612); i -= 1) {
        if (buffer.readUInt32LE(i) === 0x06064b50) {
          z64 = i;
          break;
        }
      }
    }
    if (z64 < 0 || z64 + 56 > buffer.length || buffer.readUInt32LE(z64) !== 0x06064b50) {
      throw new Error("ZIP64 EOCD 레코드를 찾지 못했다 — 손상된 3MF 다");
    }
    count = Number(buffer.readBigUInt64LE(z64 + 32));
    offset = Number(buffer.readBigUInt64LE(z64 + 48));
  }
  const entries = [];
  for (let i = 0; i < count; i += 1) {
    if (offset + 46 > buffer.length || buffer.readUInt32LE(offset) !== 0x02014b50) {
      throw new Error("ZIP 중앙 디렉터리가 손상됐다");
    }
    const nameLength = buffer.readUInt16LE(offset + 28);
    const extraLength = buffer.readUInt16LE(offset + 30);
    let uncompressedSize = buffer.readUInt32LE(offset + 24);
    let compressedSize = buffer.readUInt32LE(offset + 20);
    let localOffset = buffer.readUInt32LE(offset + 42);
    // 포화된(0xFFFFFFFF) 필드의 실값은 ZIP64 extra(0x0001)에 포화 순서대로 온다.
    let extraOffset = offset + 46 + nameLength;
    const extraEnd = extraOffset + extraLength;
    while (extraOffset + 4 <= extraEnd) {
      const id = buffer.readUInt16LE(extraOffset);
      const size = buffer.readUInt16LE(extraOffset + 2);
      if (id === 0x0001) {
        let cursor = extraOffset + 4;
        if (uncompressedSize === 0xffffffff) {
          uncompressedSize = Number(buffer.readBigUInt64LE(cursor));
          cursor += 8;
        }
        if (compressedSize === 0xffffffff) {
          compressedSize = Number(buffer.readBigUInt64LE(cursor));
          cursor += 8;
        }
        if (localOffset === 0xffffffff) {
          localOffset = Number(buffer.readBigUInt64LE(cursor));
          cursor += 8;
        }
      }
      extraOffset += 4 + size;
    }
    entries.push({
      name: buffer.subarray(offset + 46, offset + 46 + nameLength).toString("utf8"),
      method: buffer.readUInt16LE(offset + 10),
      compressedSize,
      localOffset,
    });
    offset += 46 + nameLength + extraLength + buffer.readUInt16LE(offset + 32);
  }
  return entries;
}

function zipRead(buffer, entry) {
  if (entry.compressedSize === 0xffffffff || entry.localOffset === 0xffffffff) {
    throw new Error("ZIP64 형식은 지원하지 않는다");
  }
  const local = entry.localOffset;
  if (buffer.readUInt32LE(local) !== 0x04034b50) throw new Error("ZIP 로컬 헤더가 손상됐다");
  const start = local + 30 + buffer.readUInt16LE(local + 26) + buffer.readUInt16LE(local + 28);
  const data = buffer.subarray(start, start + entry.compressedSize);
  if (entry.method === 0) return data;
  if (entry.method === 8) return inflateRawSync(data);
  throw new Error(`지원하지 않는 ZIP 압축 방식이다: ${entry.method}`);
}

function attr3mf(text, name) {
  const match = new RegExp(`\\b${name}="([^"]*)"`).exec(text);
  return match ? match[1] : undefined;
}

/** 3MF transform: "m00 m01 m02 m10 … m30 m31 m32" — 행벡터 규약(p' = p·M). */
function apply3mf(t, x, y, z) {
  if (!t) return [x, y, z];
  return [
    x * t[0] + y * t[3] + z * t[6] + t[9],
    x * t[1] + y * t[4] + z * t[7] + t[10],
    x * t[2] + y * t[5] + z * t[8] + t[11],
  ];
}

function compose3mf(inner, outer) {
  if (!inner) return outer;
  if (!outer) return inner;
  const out = new Array(12);
  for (let c = 0; c < 3; c += 1) {
    for (let r = 0; r < 3; r += 1) {
      out[r * 3 + c] = inner[r * 3] * outer[c] + inner[r * 3 + 1] * outer[3 + c] + inner[r * 3 + 2] * outer[6 + c];
    }
    out[9 + c] = inner[9] * outer[c] + inner[10] * outer[3 + c] + inner[11] * outer[6 + c] + outer[9 + c];
  }
  return out;
}

function loadThreeMf(buffer) {
  const entries = zipEntries(buffer);
  const model = entries.find((entry) => entry.name.toLowerCase().endsWith(".model"));
  if (!model) throw new Error("3MF 패키지 안에서 .model 문서를 찾지 못했다");
  const xml = zipRead(buffer, model).toString("utf8");
  const unitName = /<(?:\w+:)?model\b[^>]*\bunit="([^"]+)"/.exec(xml)?.[1] || "millimeter";
  const scale = THREEMF_UNIT_TO_MM[unitName];
  const warnings = [];
  if (scale === undefined) warnings.push(`알 수 없는 3MF 단위 ${unitName} — mm 로 간주한다`);
  else if (scale !== 1) warnings.push(`3MF 단위 ${unitName} → mm 환산(×${scale})`);
  const unitScale = scale ?? 1;

  const objects = new Map();
  const objectRe = /<(?:\w+:)?object\b([^>]*)>([\s\S]*?)<\/(?:\w+:)?object>/g;
  for (let match = objectRe.exec(xml); match; match = objectRe.exec(xml)) {
    const [, head, body] = match;
    const id = attr3mf(head, "id");
    const record = { name: attr3mf(head, "name") || `object${id}`, type: attr3mf(head, "type") || "model" };
    const vertices = [];
    const vertexRe = /<(?:\w+:)?vertex\b([^/>]*)\/?>/g;
    for (let v = vertexRe.exec(body); v; v = vertexRe.exec(body)) {
      vertices.push(Number(attr3mf(v[1], "x")), Number(attr3mf(v[1], "y")), Number(attr3mf(v[1], "z")));
    }
    const triangles = [];
    const triangleRe = /<(?:\w+:)?triangle\b([^/>]*)\/?>/g;
    for (let t = triangleRe.exec(body); t; t = triangleRe.exec(body)) {
      triangles.push(Number(attr3mf(t[1], "v1")), Number(attr3mf(t[1], "v2")), Number(attr3mf(t[1], "v3")));
    }
    const components = [];
    const componentRe = /<(?:\w+:)?component\b([^/>]*)\/?>/g;
    for (let c = componentRe.exec(body); c; c = componentRe.exec(body)) {
      const transform = attr3mf(c[1], "transform");
      components.push({ objectid: attr3mf(c[1], "objectid"), transform: transform?.split(/\s+/).map(Number) });
    }
    record.vertices = vertices;
    record.triangles = triangles;
    record.components = components;
    objects.set(id, record);
  }

  const parts = [];
  const emit = (id, transform, label, depth) => {
    const object = objects.get(id);
    if (!object || depth > 8) return;
    if (object.triangles.length) {
      const vertexCount = object.vertices.length / 3;
      const positions = new Float32Array(object.triangles.length * 3);
      for (let i = 0; i < object.triangles.length; i += 1) {
        const index = object.triangles[i];
        if (index >= vertexCount) throw new Error(`3MF 삼각형이 없는 정점 ${index} 을 가리킨다 (정점 ${vertexCount}개)`);
        const [x, y, z] = apply3mf(
          transform,
          object.vertices[index * 3],
          object.vertices[index * 3 + 1],
          object.vertices[index * 3 + 2],
        );
        positions[i * 3] = x * unitScale;
        positions[i * 3 + 1] = y * unitScale;
        positions[i * 3 + 2] = z * unitScale;
      }
      parts.push({ name: label || object.name, positions, materialIndex: -1 });
    }
    for (const component of object.components) {
      emit(component.objectid, compose3mf(component.transform, transform), label || object.name, depth + 1);
    }
  };

  const buildBody = /<(?:\w+:)?build\b[^>]*>([\s\S]*?)<\/(?:\w+:)?build>/.exec(xml)?.[1] || "";
  const itemRe = /<(?:\w+:)?item\b([^/>]*)\/?>/g;
  let placed = false;
  for (let item = itemRe.exec(buildBody); item; item = itemRe.exec(buildBody)) {
    placed = true;
    const transform = attr3mf(item[1], "transform");
    emit(attr3mf(item[1], "objectid"), transform?.split(/\s+/).map(Number), undefined, 0);
  }
  if (!placed) {
    for (const [id, object] of objects) if (object.type === "model") emit(id, undefined, undefined, 0);
  }
  return { parts, warnings };
}

function multiply(a, b) {
  const out = new Float64Array(16);
  for (let c = 0; c < 4; c += 1) {
    for (let r = 0; r < 4; r += 1) {
      out[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
  }
  return out;
}

function trsMatrix(node) {
  if (node.matrix) return Float64Array.from(node.matrix);
  const [tx, ty, tz] = node.translation || [0, 0, 0];
  const [qx, qy, qz, qw] = node.rotation || [0, 0, 0, 1];
  const [sx, sy, sz] = node.scale || [1, 1, 1];
  const x2 = qx + qx;
  const y2 = qy + qy;
  const z2 = qz + qz;
  const xx = qx * x2;
  const xy = qx * y2;
  const xz = qx * z2;
  const yy = qy * y2;
  const yz = qy * z2;
  const zz = qz * z2;
  const wx = qw * x2;
  const wy = qw * y2;
  const wz = qw * z2;
  return Float64Array.from([
    (1 - (yy + zz)) * sx, (xy + wz) * sx, (xz - wy) * sx, 0,
    (xy - wz) * sy, (1 - (xx + zz)) * sy, (yz + wx) * sy, 0,
    (xz + wy) * sz, (yz - wx) * sz, (1 - (xx + yy)) * sz, 0,
    tx, ty, tz, 1,
  ]);
}

function resolveBuffers(gltf, binChunk, baseDir) {
  return (gltf.buffers || []).map((buffer, index) => {
    if (!buffer.uri) return binChunk || Buffer.alloc(0);
    if (buffer.uri.startsWith("data:")) return Buffer.from(buffer.uri.slice(buffer.uri.indexOf(",") + 1), "base64");
    try {
      return readFileSync(resolve(baseDir, decodeURIComponent(buffer.uri)));
    } catch {
      throw new Error(`glTF 외부 버퍼를 읽지 못했다: buffers[${index}].uri=${buffer.uri}`);
    }
  });
}

function readRaw(gltf, buffers, source, componentType, count, components) {
  const layout = COMPONENT[componentType];
  const view = gltf.bufferViews[source.bufferView];
  const buffer = buffers[view.buffer];
  const base = (view.byteOffset || 0) + (source.byteOffset || 0);
  const stride = view.byteStride || layout.size * components;
  const out = new Float64Array(count * components);
  for (let i = 0; i < count; i += 1) {
    for (let c = 0; c < components; c += 1) {
      const offset = base + i * stride + c * layout.size;
      let value;
      switch (componentType) {
        case 5120: value = buffer.readInt8(offset); break;
        case 5121: value = buffer.readUInt8(offset); break;
        case 5122: value = buffer.readInt16LE(offset); break;
        case 5123: value = buffer.readUInt16LE(offset); break;
        case 5125: value = buffer.readUInt32LE(offset); break;
        default: value = buffer.readFloatLE(offset);
      }
      out[i * components + c] = value;
    }
  }
  return out;
}

// KHR_mesh_quantization: normalized 정수는 [-1,1]/[0,1] 로 역양자화해야 좌표다.
const NORMALIZE_DIVISOR = { 5120: 127, 5121: 255, 5122: 32767, 5123: 65535 };

function readAccessor(gltf, buffers, accessorIndex) {
  const accessor = gltf.accessors[accessorIndex];
  const components = TYPE_COUNT[accessor.type];
  let out;
  if (accessor.bufferView !== undefined) {
    out = readRaw(gltf, buffers, accessor, accessor.componentType, accessor.count, components);
  } else {
    out = new Float64Array(accessor.count * components); // 0 채움 accessor 는 규격상 유효하다.
  }
  if (accessor.sparse) {
    const { count, indices, values } = accessor.sparse;
    const targets = readRaw(gltf, buffers, indices, indices.componentType, count, 1);
    const replacements = readRaw(gltf, buffers, values, accessor.componentType, count, components);
    for (let i = 0; i < count; i += 1) {
      const target = targets[i] * components;
      for (let c = 0; c < components; c += 1) out[target + c] = replacements[i * components + c];
    }
  }
  const divisor = accessor.normalized ? NORMALIZE_DIVISOR[accessor.componentType] : undefined;
  if (divisor) {
    for (let i = 0; i < out.length; i += 1) out[i] = Math.max(out[i] / divisor, -1);
  }
  return out;
}

function loadGltf(buffer, filePath) {
  const baseDir = dirname(filePath);
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
      offset += 8 + length; // GLB 규격상 chunkLength 는 패딩까지 포함한 4바이트 정렬 값이다.
    }
  } else {
    gltf = JSON.parse(buffer.toString("utf8"));
  }
  if (!gltf) throw new Error("glTF JSON 청크를 찾지 못했다");

  const warnings = [];
  const compressed = new Set(
    (gltf.extensionsUsed || []).filter((name) =>
      ["KHR_draco_mesh_compression", "EXT_meshopt_compression"].includes(name),
    ),
  );
  const buffers = resolveBuffers(gltf, binChunk, baseDir);
  // EXT_meshopt_compression 은 규격상 bufferView 레벨 확장이다 — primitive 만 보면 놓친다.
  const meshoptViews = new Set();
  (gltf.bufferViews || []).forEach((view, index) => {
    if (view.extensions?.EXT_meshopt_compression) meshoptViews.add(index);
  });
  const parts = [];
  const walk = (nodeIndex, parent) => {
    const node = gltf.nodes[nodeIndex];
    if (!node) return;
    const world = multiply(parent, trsMatrix(node));
    if (node.mesh !== undefined) {
      const mesh = gltf.meshes[node.mesh];
      for (const [primitiveIndex, primitive] of (mesh.primitives || []).entries()) {
        if (primitive.mode !== undefined && primitive.mode !== 4) continue; // 삼각형만 다룬다.
        if (primitive.extensions && Object.keys(primitive.extensions).some((key) => compressed.has(key))) {
          warnings.push(`압축 지오메트리(${Object.keys(primitive.extensions).join(",")})는 디코드하지 않았다`);
          continue;
        }
        if (primitive.attributes?.POSITION === undefined) continue;
        const accessorIndices = [primitive.attributes.POSITION, primitive.indices].filter((i) => i !== undefined);
        if (accessorIndices.some((i) => meshoptViews.has(gltf.accessors?.[i]?.bufferView))) {
          warnings.push("압축 지오메트리(EXT_meshopt_compression)는 디코드하지 않았다");
          continue;
        }
        const position = readAccessor(gltf, buffers, primitive.attributes.POSITION);
        const index =
          primitive.indices !== undefined
            ? readAccessor(gltf, buffers, primitive.indices)
            : Float64Array.from({ length: position.length / 3 }, (_, i) => i);
        const values = new Float32Array(index.length * 3);
        for (let i = 0; i < index.length; i += 1) {
          const v = index[i] * 3;
          const x = position[v];
          const y = position[v + 1];
          const z = position[v + 2];
          values[i * 3] = world[0] * x + world[4] * y + world[8] * z + world[12];
          values[i * 3 + 1] = world[1] * x + world[5] * y + world[9] * z + world[13];
          values[i * 3 + 2] = world[2] * x + world[6] * y + world[10] * z + world[14];
        }
        parts.push({
          name: node.name || mesh.name || `mesh${node.mesh}.${primitiveIndex}`,
          positions: values,
          materialIndex: primitive.material ?? -1,
        });
      }
    }
    for (const child of node.children || []) walk(child, world);
  };
  const identity = Float64Array.from([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  const scene = gltf.scenes?.[gltf.scene ?? 0];
  // scenes 가 없으면 루트 노드만 순회한다 — 전 노드를 돌면 자식이 두 번 방문돼 삼각형이 중복된다.
  const childIndices = new Set((gltf.nodes || []).flatMap((node) => node.children || []));
  const fallbackRoots = (gltf.nodes || []).map((_, i) => i).filter((i) => !childIndices.has(i));
  for (const root of scene?.nodes || fallbackRoots) walk(root, identity);
  return { parts, gltf, warnings, byteLength: buffer.length };
}

/** 파일 확장자로 로더를 고르고 삼각형 목록을 돌려준다. */
export function loadMesh(filePath) {
  const buffer = readFileSync(filePath);
  const extension = extname(filePath).toLowerCase();
  let result;
  if (extension === ".stl") result = loadStl(buffer);
  else if (extension === ".obj") result = loadObj(buffer);
  else if (extension === ".glb" || extension === ".gltf") result = loadGltf(buffer, filePath);
  else if (extension === ".3mf") result = loadThreeMf(buffer);
  else throw new Error(`지원하지 않는 형식이다: ${extension} (stl, obj, glb, gltf, 3mf 만 읽는다)`);
  const parts = result.parts.filter((part) => part.positions.length >= 9);
  if (!parts.length) {
    const reason = result.warnings.length ? ` — ${result.warnings.join("; ")}` : "";
    throw new Error(`삼각형을 하나도 읽지 못했다: ${filePath}${reason}`);
  }
  return { ...result, parts, source: filePath, byteLength: result.byteLength ?? buffer.length };
}
