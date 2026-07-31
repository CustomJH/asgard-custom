"""파일 읽고 쓰기 — 인코딩·수명·원자성을 한 자리에 가둔다.

왜 만들었나: 저장소 전역에 `json.load(open(p, encoding="utf-8"))`와 `open(tmp,
"w").write(x)`와 tmp+os.replace 세 줄이 144곳에 흩어져 있었다. 흩어져 있으면 세 가지가 동시에 샌다 — 핸들
수명(예외가 나면 안 닫힌다), 인코딩(빠뜨린 자리가 Windows 에서만 깨진다), 원자성(중간에 죽으면
반쪽 파일이 남는다). 셋 다 호출부가 매번 기억해야 하는 것이었고, 그래서 매번은 아니었다.

인터페이스는 일부러 좁다. 경로와 값만 받고 나머지는 여기서 결정한다 — 호출부가 알아야 할 것이
줄어든 만큼만 이 모듈이 깊다. 파일 모드·버퍼링·개행 제어가 필요한 자리는 그냥 `open`을 쓰면
된다. 여기 있는 것은 "설정 하나를 읽고 쓴다"는 압도적 다수 경우다.

읽기는 전부 **없으면 기본값**이다. 없는 파일과 깨진 파일을 예외로 올리면 호출부가 매번 try를
쓰게 되고, 그 try가 결국 다른 실패까지 삼킨다. 쓰기는 반대로 실패를 올린다 — 못 쓴 것을
썼다고 믿으면 그 다음이 전부 거짓이 된다.
"""

from __future__ import annotations

import json
import os
from typing import Any

_ENCODING = "utf-8"


def read_text(path: str, default: str = "") -> str:
    """없거나 못 읽으면 기본값. 존재 여부를 먼저 묻지 않는다 — 물어보고 여는 사이에 사라질 수 있다."""
    try:
        with open(path, encoding=_ENCODING) as handle:
            return handle.read()
    except OSError, UnicodeDecodeError:
        return default


def read_json(path: str, default: Any = None) -> Any:
    """깨진 JSON도 없는 것으로 친다 — 절단된 파일은 크래시의 흔적이지 호출부의 잘못이 아니다."""
    try:
        with open(path, encoding=_ENCODING) as handle:
            return json.load(handle)
    except OSError, UnicodeDecodeError, ValueError:
        return default


def read_jsonl(path: str) -> list[Any]:
    """줄 단위 JSON. 깨진 줄은 건너뛴다 — 마지막 줄 절단은 정상적인 크래시 흔적이다."""
    out: list[Any] = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def write_text(path: str, text: str, *, atomic: bool = True) -> None:
    """기본이 원자적이다 — 반쪽 파일은 없는 파일보다 나쁘다(읽는 쪽이 유효하다고 믿는다)."""
    _ensure_parent(path)
    if not atomic:
        with open(path, "w", encoding=_ENCODING) as handle:
            handle.write(text)
        return
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding=_ENCODING) as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        _discard(tmp)  # 임시 파일을 남기면 다음 실행이 그것을 진짜로 착각한다
        raise


def write_json(path: str, data: Any, *, indent: int | None = 1, sort_keys: bool = False) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=sort_keys) + "\n")


def append_line(path: str, text: str) -> None:
    """추가는 원자적으로 못 만든다 — 대신 한 번의 write로 끝내 부분 기록 창을 최소화한다."""
    _ensure_parent(path)
    with open(path, "a", encoding=_ENCODING) as handle:
        handle.write(text if text.endswith("\n") else text + "\n")


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _discard(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
