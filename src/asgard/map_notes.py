"""근거 주석 레인 — "왜 이렇게 돼 있나"의 숏컷.

이 질문은 grep으로 못 찾는다. 답이 어느 낱말로 적혀 있는지 모르기 때문이다. 그런데 이 저장소에서
그 답은 대개 **코드 바로 옆에 이미 적혀 있다** — `src/asgard`에만 실측·날짜·금지 계약을 단 주석이
266건이다 (26-08-01). 그걸 찾아 주는 것이 이 레인이다.

**무엇을 근거로 볼지는 닫힌 표식으로 정한다.** "이 주석은 설계 근거처럼 보인다"를 문장에서
판단하려 들면 그것 자체가 지어내기다. 대신 이 코드베이스가 실제로 쓰는 증거 표식 — 실측 문구,
날짜 도장, 명시적 금지 계약, 그리고 범용 마커(`NOTE:`/`WHY:`/`HACK:`) — 만 근거로 삼는다.
표식이 없는 주석은 설명이지 근거가 아니므로 여기 안 나온다.

귀속은 파이썬만 정확하다: `ast`가 함수·클래스 스팬을 직접 증명한다. 다른 언어는 앞줄을 훑어
추측해야 하므로 단위를 붙이지 않고 파일과 줄만 말한다 — 못 세운 것을 세운 척하지 않는다.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .code_map import _MAX_SOURCE_BYTES, _files
from .map_lex import hits, idf, query_groups

# 근거 표식 — 닫힌 집합. 하나라도 걸리면 그 주석 덩이는 근거다.
_MARKERS = (
    re.compile(r"\(2[0-9]-[0-1][0-9]-[0-3][0-9]\)"),  # 날짜 도장 — 언제 재봤는지가 적힌 것
    re.compile(r"실측|계측|재보|재봤"),
    re.compile(r"안 된다|하지 않는다|안 한다|하면 안|금지|쓰지 않는다|믿지 (?:말|않)"),
    # `그래서`는 뺐다 — 흔한 접속사라 196건을 끌고 들어왔고 그중 대부분이 근거가 아니었다.
    re.compile(r"왜냐|이유는|이유다|때문이다"),
    # 영어로 적힌 근거도 같은 무게로 본다. 이 저장소의 `code_map._files` 주석("This prevents
    # benchmark copies … from becoming false landmarks")이 한국어 표식이 없다는 이유만으로
    # 안 보이던 것을 재보고 넣었다. `because`·`so that`은 `그래서`와 같은 병이라 안 넣는다.
    re.compile(
        r"\b(?:this prevents|this ensures|the reason|must not|never |otherwise\b|would (?:break|fail|be wrong))",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:NOTE|WHY|HACK|XXX|FIXME|GOTCHA|CAUTION)\b\s*:"),
)
_PY_COMMENT = re.compile(r"^\s*#\s?(.*)$")
_MAX_NOTE_BYTES = 400
_MAX_BLOCK_LINES = 12


@dataclass(frozen=True)
class Note:
    path: str
    line: int
    unit: str  # 감싼 함수/클래스 — 파이썬만 채운다. 나머지는 빈 값이다.
    text: str


def _blocks(source: str) -> list[tuple[int, str]]:
    """이어진 `#` 주석 줄을 덩이로 묶는다 — (시작 줄, 본문).

    한 줄씩 보면 근거가 여러 줄에 걸쳐 적힌 경우 표식이 있는 줄만 남아 뜻이 반토막 난다.
    """
    found: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    for number, line in enumerate(source.splitlines(), 1):
        match = _PY_COMMENT.fullmatch(line.rstrip())
        if match:
            if not current:
                start = number
            current.append(match.group(1).strip())
            continue
        if current:
            found.append((start, " ".join(part for part in current if part)))
            current = []
    if current:
        found.append((start, " ".join(part for part in current if part)))
    return [(number, text) for number, text in found if text and len(text.splitlines()) <= _MAX_BLOCK_LINES]


def _python_units(source: str) -> list[tuple[int, int, str]]:
    """(시작, 끝, 이름) — ast가 직접 증명하는 스팬만."""
    try:
        tree = ast.parse(source)
    except SyntaxError, ValueError:
        return []
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            spans.append((node.lineno, node.end_lineno or node.lineno, node.name))
    # 가장 안쪽 단위가 답이다 — `Runner.go` 안의 주석은 `go`의 근거지 `Runner`의 근거가 아니다.
    # 찾는 쪽이 첫 일치를 쓰므로 좁은 스팬이 앞에 와야 한다.
    return sorted(spans, key=lambda span: span[1] - span[0])


def _docstrings(source: str) -> list[tuple[int, str, str]]:
    """(줄, 단위 이름, 본문) — 독스트링도 근거를 담는 자리다."""
    try:
        tree = ast.parse(source)
    except SyntaxError, ValueError:
        return []
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            continue
        text = ast.get_docstring(node)
        if text:
            name = getattr(node, "name", "")
            found.append((getattr(node, "lineno", 1), name, " ".join(text.split())))
    return found


def _clip(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= _MAX_NOTE_BYTES:
        return text
    return encoded[:_MAX_NOTE_BYTES].decode("utf-8", "ignore").rstrip() + "…"


def collect_notes(root: str | os.PathLike[str]) -> list[Note]:
    """저장소의 근거 주석 — 표식이 있는 것만."""
    base = Path(root).resolve()
    found: list[Note] = []
    for rel in _files(base):
        if rel.suffix.lower() != ".py":
            continue
        try:
            full = base / rel
            if full.stat().st_size > _MAX_SOURCE_BYTES:
                continue
            source = full.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            continue
        units = _python_units(source)

        def unit_at(line: int, spans: list[tuple[int, int, str]] = units) -> str:
            return next((name for start, end, name in spans if start <= line <= end), "")

        for line, text in _blocks(source):
            if any(marker.search(text) for marker in _MARKERS):
                found.append(Note(rel.as_posix(), line, unit_at(line), _clip(text)))
        for line, name, text in _docstrings(source):
            if any(marker.search(text) for marker in _MARKERS):
                found.append(Note(rel.as_posix(), line, name, _clip(text)))
    return sorted(found, key=lambda note: (note.path, note.line))


def rank_notes(notes: list[Note], query: str, *, limit: int = 5) -> list[Note]:
    """질의에 가까운 근거 — 개념 수를 먼저 보고, 없으면 비운다."""
    groups = query_groups(query)
    if not groups or not notes:
        return []
    haystacks = [f"{note.path} {note.unit} {note.text}".casefold() for note in notes]
    weights = idf(haystacks, groups)
    scored: list[tuple[int, float, str, int]] = []
    index = {(note.path, note.line): note for note in notes}
    for note, haystack in zip(notes, haystacks):
        covered, score = hits(haystack, f"{note.path} {note.unit}".casefold(), groups, weights)
        if covered:
            scored.append((-covered, -score, note.path, note.line))
    scored.sort()
    return [index[path, line] for _covered, _score, path, line in scored[:limit]]
