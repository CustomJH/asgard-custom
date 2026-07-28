// 기하 분석 — 경계상자·부피·면적·매니폴드·오버행·살두께. 의존성 없음.

/** 모든 파트의 삼각형을 하나의 Float32Array(9n) 로 합치고 파트 경계를 남긴다. */
export function flatten(parts) {
  const total = parts.reduce((sum, part) => sum + part.positions.length, 0);
  const positions = new Float32Array(total);
  const ranges = [];
  let cursor = 0;
  for (const part of parts) {
    positions.set(part.positions, cursor);
    ranges.push({ name: part.name, start: cursor / 9, count: part.positions.length / 9 });
    cursor += part.positions.length;
  }
  return { positions, ranges, triangleCount: total / 9 };
}

export function bounds(positions) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = positions[i + axis];
      if (value < min[axis]) min[axis] = value;
      if (value > max[axis]) max[axis] = value;
    }
  }
  return { min, max, size: [max[0] - min[0], max[1] - min[1], max[2] - min[2]] };
}

function cross(ax, ay, az, bx, by, bz) {
  return [ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx];
}

/** 삼각형별 면적·법선·중심을 한 번에 계산한다(반복 호출을 피하기 위한 캐시). */
export function faces(positions) {
  const count = positions.length / 9;
  const normals = new Float32Array(count * 3);
  const areas = new Float64Array(count);
  const centers = new Float32Array(count * 3);
  let degenerate = 0;
  for (let f = 0; f < count; f += 1) {
    const i = f * 9;
    const ax = positions[i + 3] - positions[i];
    const ay = positions[i + 4] - positions[i + 1];
    const az = positions[i + 5] - positions[i + 2];
    const bx = positions[i + 6] - positions[i];
    const by = positions[i + 7] - positions[i + 1];
    const bz = positions[i + 8] - positions[i + 2];
    const [nx, ny, nz] = cross(ax, ay, az, bx, by, bz);
    const length = Math.hypot(nx, ny, nz);
    areas[f] = length / 2;
    if (length === 0) degenerate += 1;
    const scale = length || 1;
    normals[f * 3] = nx / scale;
    normals[f * 3 + 1] = ny / scale;
    normals[f * 3 + 2] = nz / scale;
    for (let axis = 0; axis < 3; axis += 1) {
      centers[f * 3 + axis] = (positions[i + axis] + positions[i + 3 + axis] + positions[i + 6 + axis]) / 3;
    }
  }
  return { count, normals, areas, centers, degenerate };
}

/**
 * 특징 에지 — 실루엣(경계)과 접힘(crease)만 남긴다.
 *
 * CAD 워크벤치 뷰가 뷰티 렌더와 다른 지점이 여기다. 삼각형을 셰이딩만 하면 평면 위의 구멍
 * 테두리와 모따기 경계가 안 보인다. 사람이 "이 형상이 맞는가"를 판정할 때 실제로 보는 것은
 * 그 선들이다.
 *
 * 판정 기준은 인접 두 삼각형의 법선 사이 각도다. 문턱을 넘으면 접힘이고, 인접면이 하나뿐이면
 * 열린 경계다. 곡면을 잘게 쪼갠 삼각형끼리는 각도가 작아 선이 그려지지 않으므로, 원기둥 옆면이
 * 줄무늬로 덮이지 않는다.
 *
 * @param {Float32Array} positions 9n 삼각형 수프
 * @param {object} cache faces(positions) 결과
 * @param {object} options { angle: 접힘 판정 각도(도), weld: 정점 병합 격자(mm) }
 * @returns {Float32Array} 에지 끝점 6개씩 [x1,y1,z1,x2,y2,z2, …]
 */
export function featureEdges(positions, cache, { angle = 24, weld = 1e-4 } = {}) {
  const threshold = Math.cos((angle * Math.PI) / 180);
  const quantum = 1 / weld;
  const key = (i) =>
    `${Math.round(positions[i] * quantum)},${Math.round(positions[i + 1] * quantum)},${Math.round(positions[i + 2] * quantum)}`;

  // 에지 → 인접 삼각형 목록. 정점을 격자로 병합해야 같은 모서리가 하나로 모인다.
  const shared = new Map();
  for (let f = 0; f < cache.count; f += 1) {
    if (cache.areas[f] <= 0) continue;
    const i = f * 9;
    const corners = [key(i), key(i + 3), key(i + 6)];
    for (let c = 0; c < 3; c += 1) {
      const a = corners[c];
      const b = corners[(c + 1) % 3];
      if (a === b) continue; // 퇴화 에지
      const id = a < b ? `${a}|${b}` : `${b}|${a}`;
      let entry = shared.get(id);
      if (entry === undefined) {
        entry = { faces: [], p: [positions[i + c * 3], positions[i + c * 3 + 1], positions[i + c * 3 + 2]], q: null };
        const n = ((c + 1) % 3) * 3;
        entry.q = [positions[i + n], positions[i + n + 1], positions[i + n + 2]];
        shared.set(id, entry);
      }
      entry.faces.push(f);
    }
  }

  const out = [];
  for (const entry of shared.values()) {
    const { faces: adjacent, p, q } = entry;
    let keep = adjacent.length === 1; // 열린 경계는 무조건 그린다
    if (!keep && adjacent.length >= 2) {
      const [a, b] = adjacent;
      const dot =
        cache.normals[a * 3] * cache.normals[b * 3] +
        cache.normals[a * 3 + 1] * cache.normals[b * 3 + 1] +
        cache.normals[a * 3 + 2] * cache.normals[b * 3 + 2];
      keep = Math.abs(dot) < threshold;
    }
    if (keep) out.push(p[0], p[1], p[2], q[0], q[1], q[2]);
  }
  return new Float32Array(out);
}

/** 부호 있는 부피(㎣ 단위 가정). 감김이 일관되고 닫힌 메시에서만 물리적 의미가 있다. */
export function volume(positions) {
  let total = 0;
  for (let i = 0; i < positions.length; i += 9) {
    const [nx, ny, nz] = cross(
      positions[i + 3],
      positions[i + 4],
      positions[i + 5],
      positions[i + 6],
      positions[i + 7],
      positions[i + 8],
    );
    total += (positions[i] * nx + positions[i + 1] * ny + positions[i + 2] * nz) / 6;
  }
  return total;
}

/**
 * 정점을 격자 스냅으로 용접한 뒤 에지 위상을 센다.
 * 열린 에지(1회)와 비매니폴드 에지(3회 이상)는 수밀성 위반이다.
 */
export function topology(positions, tolerance) {
  const scale = 1 / Math.max(tolerance, 1e-9);
  const keyOf = (i) =>
    `${Math.round(positions[i] * scale)},${Math.round(positions[i + 1] * scale)},${Math.round(positions[i + 2] * scale)}`;
  const vertexIds = new Map();
  const indices = new Int32Array(positions.length / 3);
  for (let i = 0, v = 0; i < positions.length; i += 3, v += 1) {
    const key = keyOf(i);
    let id = vertexIds.get(key);
    if (id === undefined) {
      id = vertexIds.size;
      vertexIds.set(key, id);
    }
    indices[v] = id;
  }
  const edges = new Map();
  let flipped = 0;
  for (let f = 0; f < indices.length; f += 3) {
    for (let e = 0; e < 3; e += 1) {
      const a = indices[f + e];
      const b = indices[f + ((e + 1) % 3)];
      if (a === b) continue;
      const key = a < b ? `${a}|${b}` : `${b}|${a}`;
      const entry = edges.get(key) || { count: 0, forward: 0 };
      entry.count += 1;
      entry.forward += a < b ? 1 : -1;
      edges.set(key, entry);
    }
  }
  let openEdges = 0;
  let nonManifold = 0;
  for (const entry of edges.values()) {
    if (entry.count === 1) openEdges += 1;
    else if (entry.count > 2) nonManifold += 1;
    else if (entry.count === 2 && entry.forward !== 0) flipped += 1;
  }
  return {
    vertices: vertexIds.size,
    edges: edges.size,
    openEdges,
    nonManifoldEdges: nonManifold,
    inconsistentEdges: flipped,
    watertight: openEdges === 0 && nonManifold === 0,
  };
}

/**
 * 에지를 공유하는 삼각형을 묶어 독립 셸(부품)을 찾는다.
 * 조립체 메시에서 살두께를 재면 광선이 이웃 부품에 먼저 닿아 거짓 경보가 나므로,
 * 부품 경계를 먼저 알아야 판정이 정직해진다.
 */
export function shells(positions, tolerance) {
  const scale = 1 / Math.max(tolerance, 1e-9);
  const vertexIds = new Map();
  const faceCount = positions.length / 9;
  const corner = new Int32Array(faceCount * 3);
  for (let f = 0; f < faceCount; f += 1) {
    for (let c = 0; c < 3; c += 1) {
      const i = f * 9 + c * 3;
      const key = `${Math.round(positions[i] * scale)},${Math.round(positions[i + 1] * scale)},${Math.round(positions[i + 2] * scale)}`;
      let id = vertexIds.get(key);
      if (id === undefined) {
        id = vertexIds.size;
        vertexIds.set(key, id);
      }
      corner[f * 3 + c] = id;
    }
  }
  const parent = new Int32Array(faceCount).map((_, index) => index);
  const find = (x) => {
    let root = x;
    while (parent[root] !== root) root = parent[root];
    while (parent[x] !== root) {
      const next = parent[x];
      parent[x] = root;
      x = next;
    }
    return root;
  };
  const union = (a, b) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent[rb] = ra;
  };
  const seen = new Map();
  for (let f = 0; f < faceCount; f += 1) {
    for (let e = 0; e < 3; e += 1) {
      const a = corner[f * 3 + e];
      const b = corner[f * 3 + ((e + 1) % 3)];
      const key = a < b ? `${a}|${b}` : `${b}|${a}`;
      const previous = seen.get(key);
      if (previous === undefined) seen.set(key, f);
      else union(previous, f);
    }
  }
  const groups = new Map();
  for (let f = 0; f < faceCount; f += 1) {
    const root = find(f);
    const group = groups.get(root);
    if (group) group.push(f);
    else groups.set(root, [f]);
  }
  return [...groups.values()].sort((a, b) => b.length - a.length);
}

/** 셸 하나만 뽑아 새 삼각형 배열을 만든다. */
export function extractShell(positions, faceList) {
  const out = new Float32Array(faceList.length * 9);
  faceList.forEach((face, index) => {
    for (let v = 0; v < 9; v += 1) out[index * 9 + v] = positions[face * 9 + v];
  });
  return out;
}

/**
 * 적층 방향(기본 +Z)에 대한 오버행 분석.
 * 빌드 플레이트에 붙은 바닥면은 지지가 필요 없으므로 제외한다 — 평평한 뒷면 오탐의 원인.
 */
export function overhangs(positions, cache, { axis = 2, threshold = 45, plateTolerance = 1e-3 } = {}) {
  const limit = Math.cos((threshold * Math.PI) / 180); // |n·축| 이 이 값보다 크면 수평에 가깝다.
  const box = bounds(positions);
  const floor = box.min[axis];
  let overhangArea = 0;
  let downArea = 0;
  let total = 0;
  let worst = null;
  const regions = [];
  for (let f = 0; f < cache.count; f += 1) {
    const area = cache.areas[f];
    total += area;
    const n = cache.normals[f * 3 + axis];
    if (n >= 0) continue;
    downArea += area;
    const i = f * 9;
    const onPlate =
      positions[i + axis] - floor <= plateTolerance &&
      positions[i + 3 + axis] - floor <= plateTolerance &&
      positions[i + 6 + axis] - floor <= plateTolerance;
    if (onPlate) continue;
    const tilt = (Math.acos(Math.min(1, -n)) * 180) / Math.PI; // 수평면 기준 면 기울기.
    if (-n <= limit) continue;
    overhangArea += area;
    const height = Math.min(positions[i + axis], positions[i + 3 + axis], positions[i + 6 + axis]) - floor;
    const entry = { tilt: Number(tilt.toFixed(2)), area, height };
    regions.push({ ...entry, at: [cache.centers[f * 3], cache.centers[f * 3 + 1], cache.centers[f * 3 + 2]] });
    if (!worst || tilt < worst.tilt) worst = { ...entry, at: regions.at(-1).at };
  }
  regions.sort((a, b) => b.area - a.area);
  return {
    axis: ["x", "y", "z"][axis],
    thresholdDeg: threshold,
    faceArea: total,
    downFacingArea: downArea,
    overhangArea,
    overhangRatio: total ? overhangArea / total : 0,
    worst,
    hotspots: regions.slice(0, 5).map((region) => ({
      tiltDeg: region.tilt,
      area: Number(region.area.toFixed(3)),
      at: region.at.map((value) => Number(value.toFixed(3))),
    })),
  };
}

/** 삼각형을 균일 격자에 담아 광선 질의를 가속한다. */
export function buildGrid(positions, cache, box) {
  const count = cache.count;
  const target = Math.max(1, Math.min(64, Math.round(Math.cbrt(count / 2))));
  const size = box.size.map((value) => Math.max(value, 1e-6));
  const cell = Math.max(...size) / target;
  const dims = size.map((value) => Math.max(1, Math.ceil(value / cell)));
  const buckets = new Map();
  const clampIndex = (value, axis) => Math.max(0, Math.min(dims[axis] - 1, Math.floor((value - box.min[axis]) / cell)));
  for (let f = 0; f < count; f += 1) {
    const i = f * 9;
    const lo = [0, 1, 2].map((axis) =>
      clampIndex(Math.min(positions[i + axis], positions[i + 3 + axis], positions[i + 6 + axis]), axis),
    );
    const hi = [0, 1, 2].map((axis) =>
      clampIndex(Math.max(positions[i + axis], positions[i + 3 + axis], positions[i + 6 + axis]), axis),
    );
    for (let x = lo[0]; x <= hi[0]; x += 1) {
      for (let y = lo[1]; y <= hi[1]; y += 1) {
        for (let z = lo[2]; z <= hi[2]; z += 1) {
          const key = (z * dims[1] + y) * dims[0] + x;
          const bucket = buckets.get(key);
          if (bucket) bucket.push(f);
          else buckets.set(key, [f]);
        }
      }
    }
  }
  return { dims, cell, min: box.min, buckets };
}

function hitTriangle(positions, f, ox, oy, oz, dx, dy, dz) {
  const i = f * 9;
  const e1x = positions[i + 3] - positions[i];
  const e1y = positions[i + 4] - positions[i + 1];
  const e1z = positions[i + 5] - positions[i + 2];
  const e2x = positions[i + 6] - positions[i];
  const e2y = positions[i + 7] - positions[i + 1];
  const e2z = positions[i + 8] - positions[i + 2];
  const [px, py, pz] = cross(dx, dy, dz, e2x, e2y, e2z);
  const det = e1x * px + e1y * py + e1z * pz;
  if (Math.abs(det) < 1e-12) return -1;
  const inv = 1 / det;
  const tx = ox - positions[i];
  const ty = oy - positions[i + 1];
  const tz = oz - positions[i + 2];
  const u = (tx * px + ty * py + tz * pz) * inv;
  if (u < -1e-9 || u > 1 + 1e-9) return -1;
  const [qx, qy, qz] = cross(tx, ty, tz, e1x, e1y, e1z);
  const v = (dx * qx + dy * qy + dz * qz) * inv;
  if (v < -1e-9 || u + v > 1 + 1e-9) return -1;
  return (e2x * qx + e2y * qy + e2z * qz) * inv;
}

/** 격자를 3D-DDA 로 훑어 가장 가까운 교차 거리를 찾는다. 없으면 Infinity. */
export function raycast(positions, grid, origin, direction, maxDistance = Infinity) {
  const cell = grid.cell;
  const index = [0, 1, 2].map((axis) =>
    Math.max(0, Math.min(grid.dims[axis] - 1, Math.floor((origin[axis] - grid.min[axis]) / cell))),
  );
  const step = direction.map((value) => (value > 0 ? 1 : value < 0 ? -1 : 0));
  const tDelta = direction.map((value) => (value === 0 ? Infinity : Math.abs(cell / value)));
  const tMax = [0, 1, 2].map((axis) => {
    if (direction[axis] === 0) return Infinity;
    const boundary = grid.min[axis] + (index[axis] + (direction[axis] > 0 ? 1 : 0)) * cell;
    return (boundary - origin[axis]) / direction[axis];
  });
  let best = Infinity;
  let guard = grid.dims[0] + grid.dims[1] + grid.dims[2] + 3;
  while (guard > 0) {
    guard -= 1;
    const key = (index[2] * grid.dims[1] + index[1]) * grid.dims[0] + index[0];
    for (const f of grid.buckets.get(key) || []) {
      const t = hitTriangle(positions, f, origin[0], origin[1], origin[2], direction[0], direction[1], direction[2]);
      if (t > 1e-6 && t < best) best = t;
    }
    const axis = tMax[0] < tMax[1] ? (tMax[0] < tMax[2] ? 0 : 2) : tMax[1] < tMax[2] ? 1 : 2;
    if (best <= tMax[axis] || tMax[axis] > maxDistance) break;
    index[axis] += step[axis];
    if (step[axis] === 0 || index[axis] < 0 || index[axis] >= grid.dims[axis]) break;
    tMax[axis] += tDelta[axis];
  }
  return best;
}

/**
 * 면 중심에서 안쪽으로 광선을 쏘아 국소 살두께를 표본화한다.
 * 표본 수를 제한해 큰 메시에서도 상수 시간에 가깝게 끝난다.
 */
export function wallThickness(positions, cache, grid, { samples = 3000 } = {}) {
  const stride = Math.max(1, Math.floor(cache.count / samples));
  const measurements = [];
  for (let f = 0; f < cache.count; f += stride) {
    if (cache.areas[f] <= 0) continue;
    const nx = cache.normals[f * 3];
    const ny = cache.normals[f * 3 + 1];
    const nz = cache.normals[f * 3 + 2];
    const epsilon = grid.cell * 1e-3;
    const origin = [
      cache.centers[f * 3] - nx * epsilon,
      cache.centers[f * 3 + 1] - ny * epsilon,
      cache.centers[f * 3 + 2] - nz * epsilon,
    ];
    const distance = raycast(positions, grid, origin, [-nx, -ny, -nz]);
    if (Number.isFinite(distance)) {
      // 출발점을 표면 안쪽으로 밀어낸 만큼 되돌려 준다 — 한계치 경계에서 오탐이 생기지 않게.
      measurements.push({ value: distance + epsilon, at: [...cache.centers.slice(f * 3, f * 3 + 3)] });
    }
  }
  if (!measurements.length) return { samples: 0 };
  measurements.sort((a, b) => a.value - b.value);
  const at = (ratio) => measurements[Math.min(measurements.length - 1, Math.floor(measurements.length * ratio))].value;
  return {
    samples: measurements.length,
    min: measurements[0].value,
    minAt: measurements[0].at.map((value) => Number(value.toFixed(3))),
    p01: at(0.01),
    p05: at(0.05),
    median: at(0.5),
    p95: at(0.95),
    max: measurements[measurements.length - 1].value,
    thinnest: measurements.slice(0, 5).map((entry) => ({
      value: Number(entry.value.toFixed(4)),
      at: entry.at.map((value) => Number(value.toFixed(3))),
    })),
  };
}
