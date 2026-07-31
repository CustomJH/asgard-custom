"""위상 산출물 — `.<이름>.step.glb`의 읽기와 쓰기.

## 이 파일이 무엇인가

STEP 옆에 숨겨 두는 동반 파일이다. 두 몫을 한 파일이 진다:

1. **셀렉터 표.** `#f13`이 어느 면인지, 그 면의 법선·중심·면적이 얼마인지가 여기 적힌다.
   STEP 자체에는 "13번 면"이라는 개념이 없다 — 서수는 커널이 위상을 훑은 순서이고, 그 순서를
   기록해두지 않으면 다음 실행에서 같은 번호가 다른 면을 가리킨다.
2. **렌더 증거.** 삼각분할된 메시가 같이 들어가서 스냅샷·뷰어가 커널 없이 그림을 낸다.

컨테이너는 glTF 2.0 GLB 다. 이유는 실용적이다 — 메시를 나를 표준 그릇이 이미 있고, 확장
슬롯(`extensions`)이 규격에 있어서 셀렉터 표를 규격 위반 없이 실을 수 있다. 그리고
`cad_gate.mjs`가 이미 이 형식을 읽는다.

## 신선도가 왜 이 파일의 핵심인가

`refs`·`measure`·`align`·`snapshot`은 전부 STEP이 아니라 이 파일을 읽는다. STEP을 다시 뽑고
이 파일을 갱신하지 않으면 **측정은 성공하는데 옛날 형상을 잰다.** 사람 눈으로는 잡을 수 없는
종류의 오답이라, STEP의 sha256을 표 안에 박아 두고 매번 대조한다. 그 대조가 `cad_gate`의
`topology-stale` 규칙이다.
"""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass
from pathlib import Path

GLB_MAGIC = 0x46546C67  # "glTF"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
EXTENSION = "STEP_topology"

# glTF 접근자 컴포넌트 타입.
_FLOAT = 5126
_UINT32 = 5125


def sidecar_path(step_path: str | Path) -> Path:
    """`build/bracket.step` → `build/.bracket.step.glb`. 점 접두사로 납품 목록에서 숨는다."""
    step = Path(step_path)
    return step.parent / f".{step.stem}.step.glb"


@dataclass
class Sidecar:
    """위상 산출물의 내용. `index`가 셀렉터 표이고 `mesh`는 있을 수도 없을 수도 있다."""

    path: str
    index: dict
    gltf: dict

    @property
    def step_hash(self) -> str:
        return str(self.index.get("stepHash") or "")

    def entries(self, kind: str) -> list[dict]:
        value = self.index.get(kind)
        return value if isinstance(value, list) else []

    def is_fresh_for(self, step_sha256: str) -> bool:
        return bool(self.step_hash) and self.step_hash == step_sha256


# ─────────────────────────────────────────────────────────────────────────────
# 쓰기
# ─────────────────────────────────────────────────────────────────────────────


def _pad(data: bytes, alignment: int = 4, fill: bytes = b"\x00") -> bytes:
    remainder = len(data) % alignment
    return data if remainder == 0 else data + fill * (alignment - remainder)


def write(
    step_path: str | Path,
    index: dict,
    *,
    positions: list[float] | None = None,
    indices: list[int] | None = None,
) -> Path:
    """셀렉터 표(+선택적 메시)를 GLB로 쓴다. 반환값은 쓴 경로다.

    메시가 없어도 유효한 파일을 낸다 — 커널이 삼각분할에 실패해도 셀렉터 표까지 같이 잃는 것은
    과한 손실이다. 그 경우 뷰어는 그림을 못 그리지만 측정은 계속 된다.
    """
    target = sidecar_path(step_path)
    payload = gzip.compress(json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    buffer_views: list[dict] = []
    accessors: list[dict] = []
    blob = bytearray()

    def push(data: bytes, target_hint: int | None = None) -> int:
        offset = len(blob)
        blob.extend(data)
        blob.extend(b"\x00" * ((4 - len(data) % 4) % 4))
        view: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target_hint is not None:
            view["target"] = target_hint
        buffer_views.append(view)
        return len(buffer_views) - 1

    index_view = push(payload)

    gltf: dict = {
        "asset": {"version": "2.0", "generator": f"Asgard Freyja 3D / cadlib {index.get('version', '')}"},
        "extensionsUsed": [EXTENSION],
        "extensions": {
            EXTENSION: {
                "indexView": index_view,
                "encoding": "gzip+json",
                "stepHash": index.get("stepHash", ""),
            }
        },
    }

    if positions and indices:
        # 34962 = ARRAY_BUFFER, 34963 = ELEMENT_ARRAY_BUFFER — 규격 상수다.
        position_view = push(struct.pack(f"<{len(positions)}f", *positions), 34962)
        index_view_id = push(struct.pack(f"<{len(indices)}I", *indices), 34963)
        count = len(positions) // 3
        lo = [min(positions[axis::3]) for axis in range(3)]
        hi = [max(positions[axis::3]) for axis in range(3)]
        accessors.append(
            {
                "bufferView": position_view,
                "componentType": _FLOAT,
                "count": count,
                "type": "VEC3",
                "min": lo,
                "max": hi,
            }
        )
        accessors.append(
            {
                "bufferView": index_view_id,
                "componentType": _UINT32,
                "count": len(indices),
                "type": "SCALAR",
            }
        )
        gltf["meshes"] = [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}]
        gltf["nodes"] = [{"mesh": 0, "name": str(index.get("name") or "part")}]
        gltf["scenes"] = [{"nodes": [0]}]
        gltf["scene"] = 0
        gltf["accessors"] = accessors

    gltf["bufferViews"] = buffer_views
    gltf["buffers"] = [{"byteLength": len(blob)}]

    json_chunk = _pad(json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), fill=b" ")
    bin_chunk = _pad(bytes(blob))

    total = 12 + 8 + len(json_chunk) + (8 + len(bin_chunk) if bin_chunk else 0)
    out = bytearray()
    out += struct.pack("<III", GLB_MAGIC, 2, total)
    out += struct.pack("<II", len(json_chunk), CHUNK_JSON) + json_chunk
    if bin_chunk:
        out += struct.pack("<II", len(bin_chunk), CHUNK_BIN) + bin_chunk

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(out))
    return target


# ─────────────────────────────────────────────────────────────────────────────
# 읽기
# ─────────────────────────────────────────────────────────────────────────────


def read(path: str | Path) -> Sidecar | None:
    """GLB를 열어 셀렉터 표를 꺼낸다. 형식이 아니거나 확장이 없으면 None — 예외를 던지지 않는다.

    호출부가 "없음"과 "깨짐"을 구분해야 하는 자리가 없다. 둘 다 "이 STEP에 대해 셀렉터 측정을
    했다고 말할 수 없다"로 같게 취급되고, 그 문장을 게이트가 낸다.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) < 20 or struct.unpack_from("<I", raw, 0)[0] != GLB_MAGIC:
        return None

    offset = 12
    gltf: dict | None = None
    binary = b""
    while offset + 8 <= len(raw):
        length, kind = struct.unpack_from("<II", raw, offset)
        body = raw[offset + 8 : offset + 8 + length]
        if kind == CHUNK_JSON and gltf is None:
            try:
                gltf = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
        elif kind == CHUNK_BIN and not binary:
            binary = body
        offset += 8 + length

    if not isinstance(gltf, dict):
        return None
    extension = (gltf.get("extensions") or {}).get(EXTENSION)
    if not isinstance(extension, dict):
        return None
    views = gltf.get("bufferViews") or []
    try:
        view = views[int(extension["indexView"])]
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    start = int(view.get("byteOffset") or 0)
    chunk = binary[start : start + int(view.get("byteLength") or 0)]
    index = _decode_index(chunk)
    if index is None:
        return None
    return Sidecar(path=str(path), index=index, gltf=gltf)


def _decode_index(chunk: bytes) -> dict | None:
    """gzip 또는 평문 JSON. 상류 형식이 바뀌어도 평문 경로가 남게 둘 다 시도한다."""
    for decode in (gzip.decompress, lambda data: data):
        try:
            text = decode(chunk).decode("utf-8")
        except Exception:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def load_for(step_path: str | Path) -> Sidecar | None:
    """STEP 경로로 그 동반 파일을 연다."""
    return read(sidecar_path(step_path))
