// GIF89a 인코더 — 의존성 없음. 궤도 애니메이션 증거를 브라우저 없이 만든다.
//
// 왜 필요한가: 정지 이미지 넉 장으로는 "안쪽이 어떻게 생겼는가"가 안 보인다. 형상이 요청과
// 닮았는지 판정할 때 사람이 실제로 하는 일은 돌려보는 것이고, 그 동작을 파일 하나에 담는
// 표준 그릇이 GIF 다. PNG 인코더(png.mjs)와 짝을 이룬다.
//
// 팔레트는 고정 6×6×6 색입방체 + 40 회색이다. 적응 팔레트(메디안 컷)를 쓰지 않는 이유는
// 결정론이다 — 같은 입력이 언제나 같은 바이트를 내야 증거로 쓸 수 있고, 우리 렌더는 회색조에
// 파스텔이 얹힌 좁은 색역이라 고정 팔레트로 충분하다.

const CUBE = 6; // 축당 단계
const GRAYS = 40;

/** 256색 전역 팔레트. 앞 216 은 색입방체, 뒤 40 은 회색 계단. */
function palette() {
  const table = new Uint8Array(256 * 3);
  let index = 0;
  for (let r = 0; r < CUBE; r += 1) {
    for (let g = 0; g < CUBE; g += 1) {
      for (let b = 0; b < CUBE; b += 1) {
        table[index * 3] = Math.round((r * 255) / (CUBE - 1));
        table[index * 3 + 1] = Math.round((g * 255) / (CUBE - 1));
        table[index * 3 + 2] = Math.round((b * 255) / (CUBE - 1));
        index += 1;
      }
    }
  }
  for (let i = 0; i < GRAYS; i += 1) {
    const value = Math.round((i * 255) / (GRAYS - 1));
    table[index * 3] = value;
    table[index * 3 + 1] = value;
    table[index * 3 + 2] = value;
    index += 1;
  }
  return table;
}

const PALETTE = palette();

/** RGB 를 팔레트 인덱스로. 회색이면 회색 계단이 색입방체보다 정확하므로 그쪽을 쓴다. */
function quantize(r, g, b) {
  const spread = Math.max(r, g, b) - Math.min(r, g, b);
  if (spread <= 8) {
    const level = Math.round((((r + g + b) / 3) * (GRAYS - 1)) / 255);
    return CUBE ** 3 + Math.min(GRAYS - 1, Math.max(0, level));
  }
  const step = (value) => Math.round((value * (CUBE - 1)) / 255);
  return step(r) * CUBE * CUBE + step(g) * CUBE + step(b);
}

function indexFrame(rgba, width, height) {
  const out = new Uint8Array(width * height);
  for (let i = 0; i < width * height; i += 1) {
    out[i] = quantize(rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]);
  }
  return out;
}

/** GIF 의 가변 비트 LZW. 규격이 요구하는 clear/end 코드와 코드폭 증가를 그대로 따른다. */
function lzw(indices, minimumCodeSize = 8) {
  const clearCode = 1 << minimumCodeSize;
  const endCode = clearCode + 1;
  let codeSize = minimumCodeSize + 1;
  let nextCode = endCode + 1;
  let dictionary = new Map();

  const bytes = [];
  let bitBuffer = 0;
  let bitCount = 0;
  const emit = (code) => {
    bitBuffer |= code << bitCount;
    bitCount += codeSize;
    while (bitCount >= 8) {
      bytes.push(bitBuffer & 0xff);
      bitBuffer >>= 8;
      bitCount -= 8;
    }
  };

  emit(clearCode);
  let previous = indices.length ? indices[0] : -1;
  for (let i = 1; i < indices.length; i += 1) {
    const value = indices[i];
    const key = previous * 4096 + value;
    const found = dictionary.get(key);
    if (found !== undefined) {
      previous = found;
      continue;
    }
    emit(previous);
    dictionary.set(key, nextCode);
    nextCode += 1;
    if (nextCode > (1 << codeSize) && codeSize < 12) {
      codeSize += 1;
    } else if (nextCode >= 4096) {
      emit(clearCode);
      dictionary = new Map();
      codeSize = minimumCodeSize + 1;
      nextCode = endCode + 1;
    }
    previous = value;
  }
  if (previous >= 0) emit(previous);
  emit(endCode);
  if (bitCount > 0) bytes.push(bitBuffer & 0xff);

  // 서브블록: 길이 바이트 + 최대 255 바이트, 0 으로 종료.
  const out = [];
  for (let offset = 0; offset < bytes.length; offset += 255) {
    const chunk = bytes.slice(offset, offset + 255);
    out.push(chunk.length, ...chunk);
  }
  out.push(0);
  return out;
}

/**
 * 프레임들을 반복 재생 GIF 로 묶는다.
 * @param {Array<{width:number,height:number,data:Uint8Array}>} frames png.mjs 와 같은 이미지 형식
 * @param {object} options { delay: 프레임 간 1/100 초, loop: 0 이면 무한 }
 */
export function encodeGif(frames, { delay = 8, loop = 0 } = {}) {
  if (!frames.length) throw new Error("GIF 에 넣을 프레임이 없다");
  const { width, height } = frames[0];
  const out = [];
  const push = (...values) => out.push(...values);
  const short = (value) => push(value & 0xff, (value >> 8) & 0xff);

  push(0x47, 0x49, 0x46, 0x38, 0x39, 0x61); // "GIF89a"
  short(width);
  short(height);
  push(0xf7, 0, 0); // 전역 색표 있음, 256색, 8비트
  push(...PALETTE);

  // NETSCAPE2.0 반복 확장.
  push(0x21, 0xff, 0x0b);
  push(...[..."NETSCAPE2.0"].map((character) => character.charCodeAt(0)));
  push(3, 1);
  short(loop);
  push(0);

  for (const frame of frames) {
    if (frame.width !== width || frame.height !== height) {
      throw new Error("GIF 프레임 크기가 서로 다르다");
    }
    push(0x21, 0xf9, 0x04, 0x04); // 그래픽 제어: 처분 방식 1(그대로 둠)
    short(delay);
    push(0, 0);
    push(0x2c);
    short(0);
    short(0);
    short(width);
    short(height);
    push(0); // 지역 색표 없음, 인터레이스 없음
    push(8);
    push(...lzw(indexFrame(frame.data, width, height), 8));
  }

  push(0x3b); // 트레일러
  return Uint8Array.from(out);
}
