// 오프라인 래스터라이저 — 정사영 + z버퍼 + 평면 셰이딩. 브라우저도 GPU 도 쓰지 않는다.
// 목적은 예쁜 그림이 아니라 "형상이 의도대로 나왔는지" 를 눈으로 확인할 수 있는 결정적 증거다.

const GLYPHS = {
  // 5x7 비트맵 — 대문자·숫자·기호만. 각 행은 5비트.
  A: [0x0e, 0x11, 0x11, 0x1f, 0x11, 0x11, 0x11], B: [0x1e, 0x11, 0x1e, 0x11, 0x11, 0x11, 0x1e],
  C: [0x0e, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0e], D: [0x1e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1e],
  E: [0x1f, 0x10, 0x1e, 0x10, 0x10, 0x10, 0x1f], F: [0x1f, 0x10, 0x1e, 0x10, 0x10, 0x10, 0x10],
  G: [0x0e, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0f], H: [0x11, 0x11, 0x1f, 0x11, 0x11, 0x11, 0x11],
  I: [0x0e, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0e], J: [0x07, 0x02, 0x02, 0x02, 0x12, 0x12, 0x0c],
  K: [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11], L: [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1f],
  M: [0x11, 0x1b, 0x15, 0x15, 0x11, 0x11, 0x11], N: [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
  O: [0x0e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e], P: [0x1e, 0x11, 0x11, 0x1e, 0x10, 0x10, 0x10],
  Q: [0x0e, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0d], R: [0x1e, 0x11, 0x11, 0x1e, 0x14, 0x12, 0x11],
  S: [0x0f, 0x10, 0x10, 0x0e, 0x01, 0x01, 0x1e], T: [0x1f, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
  U: [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e], V: [0x11, 0x11, 0x11, 0x11, 0x11, 0x0a, 0x04],
  W: [0x11, 0x11, 0x11, 0x15, 0x15, 0x1b, 0x11], X: [0x11, 0x11, 0x0a, 0x04, 0x0a, 0x11, 0x11],
  Y: [0x11, 0x11, 0x0a, 0x04, 0x04, 0x04, 0x04], Z: [0x1f, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1f],
  0: [0x0e, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0e], 1: [0x04, 0x0c, 0x04, 0x04, 0x04, 0x04, 0x0e],
  2: [0x0e, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1f], 3: [0x1f, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0e],
  4: [0x02, 0x06, 0x0a, 0x12, 0x1f, 0x02, 0x02], 5: [0x1f, 0x10, 0x1e, 0x01, 0x01, 0x11, 0x0e],
  6: [0x06, 0x08, 0x10, 0x1e, 0x11, 0x11, 0x0e], 7: [0x1f, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
  8: [0x0e, 0x11, 0x11, 0x0e, 0x11, 0x11, 0x0e], 9: [0x0e, 0x11, 0x11, 0x0f, 0x01, 0x02, 0x0c],
  ".": [0, 0, 0, 0, 0, 0x06, 0x06], "-": [0, 0, 0, 0x1f, 0, 0, 0], "+": [0, 0x04, 0x04, 0x1f, 0x04, 0x04, 0],
  "×": [0, 0x11, 0x0a, 0x04, 0x0a, 0x11, 0], "/": [0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10],
  ":": [0, 0x06, 0x06, 0, 0x06, 0x06, 0], " ": [0, 0, 0, 0, 0, 0, 0], "(": [0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02],
  ")": [0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08], "°": [0x0e, 0x0a, 0x0e, 0, 0, 0, 0], _: [0, 0, 0, 0, 0, 0, 0x1f],
};

const VIEWS = {
  front: { dir: [0, 1, 0], up: [0, 0, 1] },
  back: { dir: [0, -1, 0], up: [0, 0, 1] },
  left: { dir: [1, 0, 0], up: [0, 0, 1] },
  right: { dir: [-1, 0, 0], up: [0, 0, 1] },
  top: { dir: [0, 0, -1], up: [0, 1, 0] },
  bottom: { dir: [0, 0, 1], up: [0, -1, 0] },
  iso: { dir: [-1, 1, -1], up: [0, 0, 1] },
  iso2: { dir: [1, -1, -1], up: [0, 0, 1] },
};

const PALETTE = [
  [186, 196, 208], [168, 190, 214], [206, 186, 168], [176, 200, 184],
  [206, 178, 196], [196, 194, 166], [176, 186, 206], [200, 200, 200],
];

function normalize(v) {
  const length = Math.hypot(...v) || 1;
  return v.map((value) => value / length);
}

function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

/** Y-업(glTF) 좌표를 Z-업(CAD) 으로 맞춘다. 뷰 이름의 의미를 두 규약에서 같게 유지한다. */
export function toZUp(positions) {
  const out = new Float32Array(positions.length);
  for (let i = 0; i < positions.length; i += 3) {
    out[i] = positions[i];
    out[i + 1] = -positions[i + 2];
    out[i + 2] = positions[i + 1];
  }
  return out;
}

export function viewNames() {
  return Object.keys(VIEWS);
}

export function drawText(image, text, x, y, color, scale = 1) {
  let cursor = x;
  for (const raw of String(text)) {
    const glyph = GLYPHS[raw.toUpperCase()] || GLYPHS[raw] || GLYPHS[" "];
    for (let row = 0; row < 7; row += 1) {
      for (let column = 0; column < 5; column += 1) {
        if (!(glyph[row] & (1 << (4 - column)))) continue;
        for (let dy = 0; dy < scale; dy += 1) {
          for (let dx = 0; dx < scale; dx += 1) {
            const px = cursor + column * scale + dx;
            const py = y + row * scale + dy;
            if (px < 0 || py < 0 || px >= image.width || py >= image.height) continue;
            const offset = (py * image.width + px) * 4;
            image.data[offset] = color[0];
            image.data[offset + 1] = color[1];
            image.data[offset + 2] = color[2];
            image.data[offset + 3] = 255;
          }
        }
      }
    }
    cursor += 6 * scale;
  }
  return cursor;
}

export function createImage(width, height, background = [24, 26, 31]) {
  const data = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i += 1) {
    data[i * 4] = background[0];
    data[i * 4 + 1] = background[1];
    data[i * 4 + 2] = background[2];
    data[i * 4 + 3] = 255;
  }
  return { width, height, data };
}

export function blit(target, source, x0, y0) {
  for (let y = 0; y < source.height; y += 1) {
    const ty = y0 + y;
    if (ty < 0 || ty >= target.height) continue;
    for (let x = 0; x < source.width; x += 1) {
      const tx = x0 + x;
      if (tx < 0 || tx >= target.width) continue;
      const from = (y * source.width + x) * 4;
      const to = (ty * target.width + tx) * 4;
      target.data[to] = source.data[from];
      target.data[to + 1] = source.data[from + 1];
      target.data[to + 2] = source.data[from + 2];
      target.data[to + 3] = 255;
    }
  }
}

/**
 * 한 방향에서 메시를 정사영으로 그린다.
 * @param {object} scene { positions, faceCache, ranges }
 * @param {object} options { view, size, radius, center, highlight }
 */
export function render(scene, { view = "iso", size = 420, radius, center, highlight = null, background } = {}) {
  const camera = VIEWS[view] || VIEWS.iso;
  const forward = normalize(camera.dir);
  let up = camera.up;
  if (Math.abs(forward[0] * up[0] + forward[1] * up[1] + forward[2] * up[2]) > 0.99) up = [0, 1, 0];
  const right = normalize(cross(forward, up));
  const trueUp = cross(right, forward);
  const image = createImage(size, size, background);
  const depth = new Float64Array(size * size).fill(Infinity);
  const margin = Math.round(size * 0.09);
  const scale = (size - margin * 2) / (radius * 2);
  const { positions, faceCache, ranges } = scene;
  const faceToPart = new Int32Array(faceCache.count);
  ranges.forEach((range, index) => faceToPart.fill(index, range.start, range.start + range.count));
  const project = (index) => {
    const x = positions[index] - center[0];
    const y = positions[index + 1] - center[1];
    const z = positions[index + 2] - center[2];
    return [
      size / 2 + (x * right[0] + y * right[1] + z * right[2]) * scale,
      size / 2 - (x * trueUp[0] + y * trueUp[1] + z * trueUp[2]) * scale,
      x * forward[0] + y * forward[1] + z * forward[2],
    ];
  };
  const key = normalize([0.4, 0.75, 0.5]);
  const fill = normalize([-0.6, -0.3, 0.35]);

  for (let f = 0; f < faceCache.count; f += 1) {
    if (faceCache.areas[f] <= 0) continue;
    const i = f * 9;
    const a = project(i);
    let b = project(i + 3);
    let c = project(i + 6);
    // 화면 감김이 시계 방향이면 두 정점을 바꿔 무게중심 좌표 부호를 항상 양수로 만든다.
    if ((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]) < 0) [b, c] = [c, b];
    const minX = Math.max(0, Math.floor(Math.min(a[0], b[0], c[0])));
    const maxX = Math.min(size - 1, Math.ceil(Math.max(a[0], b[0], c[0])));
    const minY = Math.max(0, Math.floor(Math.min(a[1], b[1], c[1])));
    const maxY = Math.min(size - 1, Math.ceil(Math.max(a[1], b[1], c[1])));
    if (minX > maxX || minY > maxY) continue;
    const area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
    if (Math.abs(area) < 1e-9) continue;
    const nx = faceCache.normals[f * 3];
    const ny = faceCache.normals[f * 3 + 1];
    const nz = faceCache.normals[f * 3 + 2];
    const facing = nx * forward[0] + ny * forward[1] + nz * forward[2];
    const flip = facing > 0 ? -1 : 1; // 뒷면은 법선을 뒤집어 내부도 읽히게 한다.
    const lambert =
      0.32 +
      0.52 * Math.max(0, (nx * key[0] + ny * key[1] + nz * key[2]) * flip) +
      0.2 * Math.max(0, (nx * fill[0] + ny * fill[1] + nz * fill[2]) * flip);
    const marked = highlight ? highlight(f) : null;
    const base = marked || PALETTE[faceToPart[f] % PALETTE.length];
    const shade = [
      Math.min(255, base[0] * lambert),
      Math.min(255, base[1] * lambert),
      Math.min(255, base[2] * lambert),
    ];
    for (let py = minY; py <= maxY; py += 1) {
      for (let px = minX; px <= maxX; px += 1) {
        const sx = px + 0.5;
        const sy = py + 0.5;
        const w0 = ((b[0] - a[0]) * (sy - a[1]) - (sx - a[0]) * (b[1] - a[1])) / area;
        const w1 = ((sx - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (sy - a[1])) / area;
        const w2 = 1 - w0 - w1;
        if (w0 < 0 || w1 < 0 || w2 < 0) continue;
        const z = w2 * a[2] + w1 * b[2] + w0 * c[2];
        const offset = py * size + px;
        if (z >= depth[offset]) continue;
        depth[offset] = z;
        image.data[offset * 4] = shade[0];
        image.data[offset * 4 + 1] = shade[1];
        image.data[offset * 4 + 2] = shade[2];
        image.data[offset * 4 + 3] = 255;
      }
    }
  }

  // 깊이 불연속을 외곽선으로 그려 형상 경계를 또렷하게 만든다.
  const step = (radius * 2) / size;
  const outline = new Uint8Array(size * size);
  for (let y = 1; y < size - 1; y += 1) {
    for (let x = 1; x < size - 1; x += 1) {
      const here = depth[y * size + x];
      if (!Number.isFinite(here)) continue;
      const neighbours = [depth[y * size + x + 1], depth[y * size + x - 1], depth[(y + 1) * size + x], depth[(y - 1) * size + x]];
      if (neighbours.some((value) => !Number.isFinite(value) || Math.abs(value - here) > step * 6)) {
        outline[y * size + x] = 1;
      }
    }
  }
  for (let i = 0; i < outline.length; i += 1) {
    if (!outline[i]) continue;
    image.data[i * 4] = Math.round(image.data[i * 4] * 0.45);
    image.data[i * 4 + 1] = Math.round(image.data[i * 4 + 1] * 0.45);
    image.data[i * 4 + 2] = Math.round(image.data[i * 4 + 2] * 0.45);
  }
  return image;
}

/** 뷰 이미지들을 격자로 붙이고 머리글·치수를 얹은 컨택트 시트를 만든다. */
export function contactSheet(tiles, { title, subtitle, columns } = {}) {
  const cols = columns || Math.min(tiles.length, Math.ceil(Math.sqrt(tiles.length)));
  const rows = Math.ceil(tiles.length / cols);
  const tile = tiles[0].image.width;
  const pad = 10;
  const header = 44;
  const label = 18;
  const width = cols * tile + pad * (cols + 1);
  const height = header + rows * (tile + label) + pad * (rows + 1);
  const sheet = createImage(width, height, [16, 17, 21]);
  drawText(sheet, String(title || "").slice(0, Math.floor(width / 12)), pad, 12, [232, 234, 238], 2);
  if (subtitle) drawText(sheet, String(subtitle).slice(0, Math.floor(width / 6)), pad, 30, [150, 156, 166], 1);
  tiles.forEach((entry, index) => {
    const column = index % cols;
    const row = Math.floor(index / cols);
    const x = pad + column * (tile + pad);
    const y = header + pad + row * (tile + label + pad);
    blit(sheet, entry.image, x, y);
    drawText(sheet, entry.label.toUpperCase(), x + 2, y + tile + 4, [150, 156, 166], 1);
  });
  return sheet;
}
