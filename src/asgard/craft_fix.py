"""craft 의 수리 레인 — 판정기가 잡은 주석 문체 중 **표준 표현이 하나로 정해지는 것**만 고친다.

`craft_note` 는 판정만 하고 `.claude/hooks/craft-gate.py` 는 그것으로 막는다. 고치는 쪽이 없어서
판정 하나마다 모델이 파일을 다시 읽고 다시 쓰는 턴이 한 번씩 붙고, 닫힌 사전에서 나온 같은 치환이
매번 손으로 반복된다. 이 모듈이 그 반복을 가져간다.

경계는 하나다. **결정적으로 정해지는 것만 고치고 나머지는 판정으로 남긴다.** 못 고치는 것을 고친
척하면 게이트를 통째로 못 믿게 되므로, 거부에는 항상 이유가 붙는다.

다시 쓰기 표는 짐작이 아니다. 커밋 274c6c2(`저장소 전체 주석에서 비유를 걷어낸다`, 161줄)에서
사람이 실제로 고른 말만 올렸다. 같은 말이 자리마다 다르게 고쳐진 항목은 뺐다 — 예를 들어
`선다` 는 그 커밋에서 `동작한다` 로, 계약 표(templates/comments.py)에서는 `준비된다` 로 갔고,
`사슬` 은 체인·연쇄·연결 셋으로 갈렸다. 고르는 것은 판단이고, 판단을 자동화하면 오수리가
오탐보다 비싸다: 오탐은 무시하면 되지만 오수리는 파일에 남는다.

보호 장치 넷을 전부 증거로 확인한다.
  G1  코드 바이트 불변 — Python 은 구문 트리(독스트링 비운 뒤)와 주석 뺀 토큰 열, 중괄호 계열은
      주석 뺀 본문을 대조한다.
  G2  사실 보존 — 숫자·날짜·백틱 조각·URL·경로·라틴 식별자의 다중집합이 그대로여야 한다.
  G3  판정 감소 — 고친 뒤 note-* 판정이 반드시 줄어야 하고 없던 판정이 생기면 안 된다.
  G4  애매하면 거부 — 표준 표현이 둘 이상이면 손대지 않는다.

래칫은 걸지 않는다. `craft` 의 래칫은 **막지 않기** 위한 것이지 **고치지 않기** 위한 것이 아니다 —
이미 연 파일의 주석을 같은 계약으로 맞추는 것은 커밋 274c6c2 가 손으로 한 일과 같다.
"""

from __future__ import annotations

import ast
import bisect
import io
import os
import re
import tokenize
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from . import craft, craft_note
from .craft_rules import Finding

# 은유 서술 → 표준 서술. 앞에서부터 맞는 것을 쓰므로 긴 형태가 먼저 온다.
# `든다`·`산다` 앞의 되보기는 조사를 확인한다 — 이것이 없으면 `만든다` 의 뒷글자가 걸린다.
# 판정기가 안 잡는 활용형은 올리지 않는다. 예를 들어 `걷어냈으면` 은 craft_note 의 표에 없어서
# 여기서 고치면 판정을 하나도 못 줄이는 수리가 되고, 그러면 G3 가 같은 덩이를 통째로 되돌린다.
_METAPHOR_FIX: tuple[tuple[str, str], ...] = (
    ("이긴다", "우선한다"),
    (r"이긴 (?=(?:쪽|것|편))", "우선하는 "),
    ("나른다", "전달한다"),
    ("싣는다", "넣는다"),
    ("실린다", "들어간다"),
    ("싣지", "넣지"),
    ("실으면", "넣으면"),
    ("걷어낸다", "제거한다"),
    ("걷어낸", "제거한"),
    (r"걷어내(?=[는지고면])", "제거하"),
    (r"(?<=[을를] )든다", "쓴다"),
    (r"(?<=[에가] )산다", "있다"),
)

# 지어낸 말 → 표준어. 자리에 그대로 넣어도 문장이 성립하는 것만 올린다. `비의존`·`무임포트` 는
# 표준어가 서술문이라 명사 자리에 못 넣는다 — 서술로 끝나는 꼴만 고치고 나머지는 거부한다.
# `불요` 뒤의 앞보기는 `불요불급`(표준어)을 가른다. `접지` 는 표준 표현이 둘이라 표에 없다.
# `무매칭이면` 이 `무매칭` 보다 먼저다. 뒤엣것만 있으면 `일치 없음이면` 이 되는데, 그것은
# templates/comments.py 의 대조표가 적어 둔 `일치가 없으면` 과 다르고 한국어로도 어색하다.
_JARGON_FIX: tuple[tuple[str, str], ...] = (
    (r"불요(?!불급)", "불필요"),
    ("무매칭이면", "일치가 없으면"),
    ("무매칭", "일치 없음"),
    ("비의존이다", "의존하지 않는다"),
    ("무임포트이다", "임포트하지 않는다"),
    ("무임포트다", "임포트하지 않는다"),
)

_FIX: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    ("note-metaphor", re.compile(pattern), after) for pattern, after in _METAPHOR_FIX
) + tuple(("note-jargon", re.compile(pattern), after) for pattern, after in _JARGON_FIX)

NOTE_RULES = frozenset({"note-metaphor", "note-jargon"})

# 백틱 조각과 URL 은 글쓴이가 고를 수 있는 말이 아니다 (craft_note._lintable 과 같은 기준).
# 길이를 유지한 채 덮어야 찾은 자리가 원문 오프셋 그대로 남는다.
_MASK = re.compile(r"`[^`]*`|https?://\S+")
# G2 가 세는 사실. 백틱 조각·URL·숫자·라틴 식별자와 경로.
_FACT = re.compile(r"`[^`]*`|https?://\S+|\d+|[A-Za-z_][A-Za-z0-9_./+-]*")

_WHY_CHOICE = "표준 서술이 여럿이라 어느 쪽인지는 사람이 골라야 해요"
_WHY_SHAPE = "표준어가 서술문이라 명사 자리에 그대로 못 넣어요 — 문장을 다시 세워야 해요"
_SHAPE_WORDS = ("비의존", "무임포트")
_WHY_CODE = "고치면 주석 밖 바이트까지 함께 바뀌어요"
_WHY_FACT = "사실이 그대로 남지 않아요 — 다시 쓰기는 문체만 바꿔요"
_WHY_STALE = "고쳐도 판정이 줄지 않아요 — 같은 주석에 손댈 수 없는 판정이 함께 있어요"
_WHY_WRITE = "파일을 다시 쓰지 못했어요 — 권한이나 잠금을 확인해 주세요"


@dataclass(frozen=True)
class Repair:
    """고친 줄 하나. `before`·`after` 는 그 물리 행 전체다 — 사람이 화면에서 대조할 단위."""

    path: str
    line: int
    rule: str
    before: str
    after: str


@dataclass(frozen=True)
class Refusal:
    """안 고친 판정 하나. `why` 는 왜 사람이 봐야 하는지 — 이유 없는 거부는 침묵과 같다."""

    path: str
    line: int
    rule: str
    detail: str
    why: str


@dataclass(frozen=True)
class FixReport:
    applied: tuple[Repair, ...]
    refused: tuple[Refusal, ...]
    # 내용이 달라진 파일. `write=False` 면 "썼다면 다시 썼을" 목록이다 — 예행이 실행과 다른 값을
    # 내면 예행으로 확인할 수 있는 것이 없어진다.
    files: tuple[str, ...]


@dataclass(frozen=True)
class _Span:
    """고쳐도 되는 구간 — 한 물리 행 안의 주석 본문 또는 독스트링 안쪽."""

    start: int
    end: int
    line: int
    group: int  # 판정 단위(주석 덩이·독스트링 하나). G3 는 이 단위로 건다.


@dataclass(frozen=True)
class _Cand:
    start: int
    end: int
    rule: str
    after: str
    line: int


# ── 고쳐도 되는 구간 ────────────────────────────────────────────────


def _line_starts(text: str) -> list[int]:
    """각 행의 시작 오프셋. `\\n` 만 보고 가른다 — tokenize 의 readline 과 같은 기준이어야 한다."""
    out = [0]
    for index, ch in enumerate(text):
        if ch == "\n":
            out.append(index + 1)
    return out


def _line_end(text: str, starts: list[int], row: int) -> int:
    """행 본문의 끝 — 줄바꿈 문자는 뺀다. CRLF 파일에서 `\\r` 이 구간에 들어오지 않게."""
    end = starts[row] if row < len(starts) else len(text)
    while end > starts[row - 1] and text[end - 1] in "\r\n":
        end -= 1
    return end


def _row_of(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def _writable(text: str, lang: str) -> list[_Span]:
    starts = _line_starts(text)
    if lang == "python":
        return _python_spans(text, starts)
    return _brace_spans(text, starts)


def _docstring_node(node: ast.AST) -> ast.Constant | None:
    """이 노드의 독스트링 상수 — 아니면 None. craft_note._python_docstrings 와 같은 기준."""
    if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    body = node.body
    if not body or not isinstance(body[0], ast.Expr):
        return None
    value = body[0].value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value
    return None


def _docstring_rows(text: str) -> set[int]:
    """독스트링이 시작하는 행 번호. 구문을 못 읽으면 빈 집합 — 못 읽은 것은 안 고친다."""
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return set()
    out: set[int] = set()
    for node in ast.walk(tree):
        found = _docstring_node(node)
        if found is not None:
            out.add(found.lineno)
    return out


def _quote_bounds(raw: str) -> tuple[int, int] | None:
    """(여는 따옴표까지의 길이, 닫는 따옴표 길이). 접두사(r·b·f)는 여는 쪽에 포함한다."""
    head = 0
    while head < len(raw) and raw[head] not in "\"'":
        head += 1
    if head >= len(raw):
        return None
    mark = raw[head]
    triple = raw[head : head + 3] == mark * 3
    opened = head + (3 if triple else 1)
    closed = 3 if triple else 1
    return (opened, closed) if len(raw) >= opened + closed else None


def _slices(text: str, starts: list[int], begin: int, finish: int, group: int) -> list[_Span]:
    """[begin, finish) 를 물리 행 단위로 자른다 — 한 구간은 한 행을 넘지 않는다."""
    out: list[_Span] = []
    for row in range(_row_of(starts, begin), _row_of(starts, max(begin, finish - 1)) + 1):
        low = max(begin, starts[row - 1])
        high = min(finish, _line_end(text, starts, row))
        if low < high:
            out.append(_Span(low, high, row, group))
    return out


def _python_spans(text: str, starts: list[int]) -> list[_Span]:
    """`#` 주석 본문과 독스트링 안쪽. 문자열 안의 `#` 은 COMMENT 토큰이 아니라 여기 안 걸린다."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError, IndentationError, SyntaxError, ValueError:
        return []
    rows = _docstring_rows(text)
    out: list[_Span] = []
    group = 0
    prev = -2
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            row = tok.start[0]
            group += 1 if row != prev + 1 else 0
            prev = row
            head = len(tok.string) - len(tok.string.lstrip("#"))
            out.append(_Span(starts[row - 1] + tok.start[1] + head, starts[row - 1] + tok.end[1], row, group))
        elif tok.type == tokenize.STRING and tok.start[0] in rows:
            group += 1
            out.extend(_doc_spans(text, tok, starts, group))
    return out


def _doc_spans(text: str, tok: tokenize.TokenInfo, starts: list[int], group: int) -> list[_Span]:
    bounds = _quote_bounds(tok.string)
    if bounds is None:
        return []
    begin = starts[tok.start[0] - 1] + tok.start[1] + bounds[0]
    finish = starts[tok.end[0] - 1] + tok.end[1] - bounds[1]
    return _slices(text, starts, begin, finish, group) if begin < finish else []


def _brace_comments(text: str) -> list[tuple[int, int, int, int]]:
    """(주석 시작, 주석 끝, 본문 시작, 본문 끝). 따옴표 상태를 따라가 문자열 안의 `//` 를 거른다.

    craft_note._brace_notes 와 같은 상태 기계다 — 판정과 수리가 다른 자리를 보면 안 된다."""
    out: list[tuple[int, int, int, int]] = []
    size = len(text)
    quote = ""
    i = 0
    while i < size:
        ch = text[i]
        if quote:
            i += 2 if ch == "\\" else 1
            quote = "" if ch == quote else quote
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        pair = text[i : i + 2]
        if pair == "//":
            end = text.find("\n", i)
            end = size if end < 0 else end
            out.append((i, end, i + 2, end))
            i = end
            continue
        if pair == "/*":
            end = text.find("*/", i + 2)
            end = size if end < 0 else end + 2
            out.append((i, end, i + 2, max(i + 2, end - 2)))
            i = end
            continue
        i += 1
    return out


def _brace_spans(text: str, starts: list[int]) -> list[_Span]:
    """이어진 `//` 줄은 한 덩이 — craft_note._merge_lines 와 같이 묶어야 G3 가 같은 단위를 본다."""
    out: list[_Span] = []
    group = 0
    prev = -2
    for begin, _end, body, tail in _brace_comments(text):
        first = _row_of(starts, begin)
        last = _row_of(starts, max(body, tail - 1))
        if first != prev + 1 or last != first:
            group += 1
        prev = last
        out.extend(_slices(text, starts, body, tail, group))
    return out


# ── 고칠 자리 ──────────────────────────────────────────────────────


def _searchable(chunk: str) -> str:
    return _MASK.sub(lambda hit: " " * len(hit.group(0)), chunk)


def _scan(chunk: str, span: _Span) -> list[_Cand]:
    """한 구간에서 고칠 자리. 이미 잡은 자리는 덮어 둔다 — 두 규칙이 같은 글자를 겹쳐 가지면 안 된다."""
    out: list[_Cand] = []
    work = _searchable(chunk)
    for rule, pattern, after in _FIX:
        for hit in pattern.finditer(work):
            out.append(_Cand(span.start + hit.start(), span.start + hit.end(), rule, after, span.line))
            work = work[: hit.start()] + "\x00" * (hit.end() - hit.start()) + work[hit.end() :]
    return out


def _candidates(text: str, spans: list[_Span]) -> dict[int, list[_Cand]]:
    out: dict[int, list[_Cand]] = {}
    for span in spans:
        for cand in _scan(text[span.start : span.end], span):
            out.setdefault(span.group, []).append(cand)
    return out


def _splice(text: str, cands: list[_Cand]) -> str:
    """뒤에서부터 갈아 끼운다 — 앞자리 오프셋이 안 밀린다."""
    out = text
    for cand in sorted(cands, key=lambda c: c.start, reverse=True):
        out = out[: cand.start] + cand.after + out[cand.end :]
    return out


# ── 보호 장치 ──────────────────────────────────────────────────────


def _blank_docstrings(text: str) -> str | None:
    """독스트링을 비운 구문 트리 덤프. 이것이 같으면 코드와 독스트링 아닌 문자열은 그대로다."""
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return None
    for node in ast.walk(tree):
        found = _docstring_node(node)
        if found is not None:
            found.value = ""
    return ast.dump(tree)


def _token_stream(text: str) -> list[tuple[int, str]] | None:
    """주석과 독스트링을 뺀 토큰 열. 주석 기호가 사라지거나 생기면 구문 트리 쪽에서 먼저 걸린다."""
    rows = _docstring_rows(text)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError, IndentationError, SyntaxError, ValueError:
        return None
    out: list[tuple[int, str]] = []
    for tok in toks:
        skip = tok.type == tokenize.COMMENT or (tok.type == tokenize.STRING and tok.start[0] in rows)
        if not skip:
            out.append((tok.type, tok.string))
    return out


def _strip_comments(text: str) -> str:
    """주석을 표식 하나로 바꾼 사본. 중괄호 계열의 G1 은 이것의 일치로 증명한다."""
    out: list[str] = []
    last = 0
    for begin, end, _body, _tail in _brace_comments(text):
        out.append(text[last:begin])
        out.append("\x00")
        last = end
    out.append(text[last:])
    return "".join(out)


def _code_same(before: str, after: str, lang: str) -> bool:
    """G1 — 주석 밖 바이트가 그대로인가."""
    if lang != "python":
        return _strip_comments(before) == _strip_comments(after)
    left, right = _blank_docstrings(before), _blank_docstrings(after)
    if left is None or right is None or left != right:
        return False
    old, new = _token_stream(before), _token_stream(after)
    return old is not None and new is not None and old == new


def _facts_kept(before: str, after: str) -> bool:
    """G2 — 숫자·날짜·백틱 조각·URL·경로·라틴 식별자가 하나도 빠지거나 늘지 않았는가."""
    return Counter(_FACT.findall(before)) == Counter(_FACT.findall(after))


def _note_keys(text: str, rel: str, lang: str) -> set[tuple[str, int, str]]:
    return {(f.rule, f.line, f.detail) for f in craft_note.note_findings(text, rel, [], lang)}


def _better(before: str, after: str, rel: str, lang: str) -> bool:
    """G3 — 판정이 반드시 줄고, 없던 판정이 생기지 않는가."""
    old = _note_keys(before, rel, lang)
    new = _note_keys(after, rel, lang)
    return len(new) < len(old) and not (new - old)


def _guard(before: str, after: str, rel: str, lang: str) -> str:
    """통과하면 빈 문자열, 걸리면 거부 사유."""
    if not _code_same(before, after, lang):
        return _WHY_CODE
    if not _facts_kept(before, after):
        return _WHY_FACT
    if not _better(before, after, rel, lang):
        return _WHY_STALE
    return ""


# ── 수리 ───────────────────────────────────────────────────────────


def _line_text(text: str, starts: list[int], row: int) -> str:
    return text[starts[row - 1] : _line_end(text, starts, row)]


def _records(rel: str, before: str, after: str, cands: list[_Cand]) -> list[Repair]:
    """고친 물리 행마다 한 건. 한 행에 두 자리를 고쳐도 사람이 볼 것은 그 행 하나다."""
    old, new = _line_starts(before), _line_starts(after)
    seen: dict[int, str] = {}
    for cand in cands:
        seen.setdefault(cand.line, cand.rule)
    return [
        Repair(rel, row, rule, _line_text(before, old, row), _line_text(after, new, row))
        for row, rule in sorted(seen.items())
    ]


def _why(detail: str) -> str:
    return _WHY_SHAPE if any(word in detail for word in _SHAPE_WORDS) else _WHY_CHOICE


def _refusals(text: str, rel: str, lang: str, blocked: dict[int, str]) -> list[Refusal]:
    """고친 뒤에도 남은 note-* 판정은 전부 거부다 — 안 본 것과 못 고친 것을 같은 칸에 적지 않는다."""
    return [
        Refusal(rel, f.line, f.rule, f.detail, blocked.get(f.line, "") or _why(f.detail))
        for f in craft_note.note_findings(text, rel, [], lang)
    ]


def repair(text: str, rel: str, lang: str) -> tuple[str, list[Repair], list[Refusal]]:
    """순수 함수 — 본문을 받아 고친 본문을 돌려준다. 디스크를 만지지 않는다.

    판정 단위(주석 덩이·독스트링 하나)마다 고칠 자리를 한꺼번에 갈아 끼우고 보호 장치 셋을 건다.
    한 단위 안에서 실패하면 그 단위만 되돌린다 — 한 자리 때문에 파일 전체를 포기하지 않는다."""
    groups = _candidates(text, _writable(text, lang))
    current = text
    applied: list[Repair] = []
    blocked: dict[int, str] = {}
    for group in sorted(groups, reverse=True):
        cands = groups[group]
        nominee = _splice(current, cands)
        why = _guard(current, nominee, rel, lang)
        if why:
            blocked.update({cand.line: why for cand in cands})
            continue
        applied.extend(_records(rel, current, nominee, cands))
        current = nominee
    return current, sorted(applied, key=lambda r: r.line), _refusals(current, rel, lang, blocked)


def _read(root: str, rel: str) -> str | None:
    """줄바꿈을 그대로 읽는다 — CRLF 파일을 LF 로 되쓰면 주석 밖 바이트가 통째로 바뀐다."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError, UnicodeDecodeError:
        return None


def _write(root: str, rel: str, text: str) -> bool:
    """다시 쓰지 못하면 False. 못 쓴 것을 고친 것으로 세면 다음 판정과 보고가 어긋난다."""
    try:
        with open(os.path.join(root, rel), "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except OSError:
        return False
    return True


def _prescription(finding: Finding) -> Refusal:
    """코드 형상 규칙의 거부. 스스로 함수를 다시 짜는 판정기는 보고만 하는 판정기보다 나쁘다 —
    무엇을 하면 풀리는지는 이미 판정에 붙어 있으므로 그 처방을 그대로 옮긴다."""
    return Refusal(finding.path, finding.line, finding.rule, finding.detail, finding.fix)


def apply(root: str, paths: Sequence[str], base: str = "HEAD", *, write: bool) -> FixReport:
    """판정한 경로를 고친다. `write=False` 는 예행 — 전부 계산하고 아무것도 쓰지 않는다.

    언어와 판정 대상은 `craft` 가 정한 것을 그대로 쓴다. 판정기가 둘이면 반드시 어긋난다."""
    report = craft.judge(root, list(paths), base)
    refused = [_prescription(f) for f in report.findings if f.rule not in NOTE_RULES]
    applied: list[Repair] = []
    files: list[str] = []
    for rel in report.judged:
        lang = craft._language(rel)
        raw = _read(root, rel) if lang else None
        if raw is None or lang is None:
            continue
        fixed, repairs, refusals = repair(raw, rel, lang)
        refused.extend(refusals)
        if fixed == raw:
            continue
        if write and not _write(root, rel, fixed):
            refused.extend(Refusal(rel, r.line, r.rule, r.before.strip(), _WHY_WRITE) for r in repairs)
            continue
        applied.extend(repairs)
        files.append(rel)
    return FixReport(tuple(applied), tuple(refused), tuple(files))
