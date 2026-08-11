"""주석과 독스트링의 문체 판정. 규칙 본문은 templates/comments.py에 있다.

주석은 코드가 못 적는 것(제약·이유·결과)을 적는 자리다. 그런데 그 자리에 비유를 적으면
읽는 사람이 비유부터 풀어야 한다. 이 저장소에 있던 `# 임베더가 선다`는 임베더가 준비됐다는
뜻이었지만 그 뜻은 문장에 없고 글쓴이의 머릿속에 있었다. 이 모듈은 그런 문장을 찾아
표준 표현을 제안한다.

판정 범위는 일부러 좁다. 아래 표에 올린 표현만 잡고 애매한 것은 넘긴다. `죽는다`(비정상 종료)나
`샌다`(누수)처럼 개발자가 실제로 쓰는 관용 표현은 표에 넣지 않았다. 오탐이 나기 시작하면
그다음에 일어나는 일은 게이트를 끄는 것이라서다(craft_rules와 같은 판단).

규칙은 둘이다.
  note-metaphor  코드를 사람이나 사물에 빗댄 서술어. 표준 서술로 바꿔도 뜻이 그대로 남는다.
  note-jargon    표준어가 있는데 지어낸 말. 읽는 사람이 사전을 찾아도 안 나온다.

계약에는 규칙이 더 있지만(잠언 금지, 코드 지목) 그 둘은 판정기에 안 넣었다. "식별자가 하나도
없는 주석"으로 재 보니 306건이 걸렸는데 대부분은 설계 근거를 제대로 적은 문단이었다 — 한국어로
이유를 쓰면 라틴 문자 식별자가 안 나오는 것이 정상이다. 사람이 읽고 판단할 규칙은 계약에만 둔다.

한국어 주석만 판정한다. 영어 주석의 문법은 Bragi 계약이 맡는다.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

from .bragi import KO_METAPHOR as _METAPHOR
from .craft_rules import Finding, Unit, _owner

# 지어낸 말 → 표준어. Bragi의 준말 규칙(`불요`·`무매칭`)과 겹치지 않는 것만 여기 둔다.
# 항목은 정규식이다. `접지`는 접다의 활용형(`접지 않는다`)과 글자가 같아 뒤를 보고 갈라야 한다.
_JARGON: tuple[tuple[str, str], ...] = (
    (r"접지(?!\s*(않|못|말))", "근거 대조 · 근거 확인"),
    ("비의존", "의존하지 않는다"),
    ("무매칭", "일치 없음"),
    # `불요` 뒤의 앞보기는 표준어 `불요불급`을 가른다. 이것이 없으면 맞는 낱말이 판정으로 잡히고,
    # 수리 표(craft_fix._JARGON_FIX)는 같은 앞보기로 손대지 않으므로 고칠 방법이 없는 판정이 남는다.
    (r"불요(?!불급)", "불필요"),
    ("무임포트", "임포트하지 않는다"),
)

_HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class Note:
    """주석 하나. `line`은 첫 줄이고 `text`는 기호를 뗀 본문이다."""

    line: int
    text: str
    kind: str  # "line"(# · //) 또는 "doc"(독스트링 · 블록 주석)


# ── 추출 ───────────────────────────────────────────────────────────


def notes(text: str, lang: str) -> list[Note]:
    """파일에서 주석과 독스트링을 뽑는다. 읽지 못하면 빈 목록 — 못 읽은 것을 지어내지 않는다."""
    if lang == "python":
        return _python_notes(text)
    return _brace_notes(text)


def _python_notes(text: str) -> list[Note]:
    out = [*_python_comments(text), *_python_docstrings(text)]
    return sorted(out, key=lambda n: n.line)


def _python_comments(text: str) -> list[Note]:
    """이어진 `#` 줄은 한 덩이로 묶는다. 문장이 줄을 넘어가면 반쪽만 보고는 판정할 수 없다."""
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type == tokenize.COMMENT]
    except tokenize.TokenError, IndentationError, SyntaxError, ValueError:
        return []
    out: list[Note] = []
    start = 0
    buf: list[str] = []
    prev = -2
    for tok in toks:
        row = tok.start[0]
        body = tok.string.lstrip("#").strip()
        if row != prev + 1:
            if buf:
                out.append(Note(start, " ".join(buf), "line"))
            start, buf = row, []
        buf.append(body)
        prev = row
    if buf:
        out.append(Note(start, " ".join(buf), "line"))
    return out


def _python_docstrings(text: str) -> list[Note]:
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return []
    out: list[Note] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out.append(Note(value.lineno, value.value, "doc"))
    return out


def _brace_notes(text: str) -> list[Note]:
    """중괄호 계열의 `//`와 `/* */`. 문자열 안의 `//`를 주석으로 읽지 않게 따옴표 상태를 따라간다."""
    out: list[Note] = []
    row = 1
    i = 0
    quote = ""
    size = len(text)
    while i < size:
        ch = text[i]
        if ch == "\n":
            row += 1
            i += 1
            continue
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < size and text[i + 1] == "/":
            end = text.find("\n", i)
            end = size if end < 0 else end
            out.append(Note(row, text[i + 2 : end].strip(), "line"))
            i = end
            continue
        if ch == "/" and i + 1 < size and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = size if end < 0 else end + 2
            chunk = text[i:end]
            out.append(Note(row, chunk.strip("/*").strip(), "doc"))
            row += chunk.count("\n")
            i = end
            continue
        i += 1
    return _merge_lines(out)


def _merge_lines(found: list[Note]) -> list[Note]:
    out: list[Note] = []
    for note in found:
        if out and note.kind == "line" and out[-1].kind == "line" and note.line == out[-1].line + 1:
            out[-1] = Note(out[-1].line, out[-1].text + " " + note.text, "line")
            continue
        out.append(note)
    return out


# ── 판정 ───────────────────────────────────────────────────────────


def note_findings(text: str, rel: str, spans: list[Unit], lang: str) -> list[Finding]:
    """한국어 주석의 문체 판정. 영어 주석과 판정 대상이 아닌 언어는 조용히 넘긴다."""
    out: list[Finding] = []
    for note in notes(text, lang):
        if not _HANGUL.search(note.text):
            continue
        out.extend(_judge(note, rel, spans))
    return out


def _judge(note: Note, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []
    unit = _owner(spans, note.line)
    body = _lintable(note.text)
    for name, pattern, plain in _METAPHOR:
        if hit := re.search(pattern, body):
            out.append(
                Finding(
                    "note-metaphor",
                    rel,
                    note.line,
                    unit,
                    f'코드를 빗댄 서술 "{hit.group(0)}" ({name})',
                    f"무슨 일이 일어나는지 그대로 적으면 돼요 — {plain}",
                )
            )
            break
    for pattern, plain in _JARGON:
        if hit := re.search(pattern, body):
            out.append(
                Finding(
                    "note-jargon",
                    rel,
                    note.line,
                    unit,
                    f'사전에 없는 말 "{hit.group(0)}"',
                    f"표준어로 적으면 돼요 — {plain}",
                )
            )
            break
    return out


def _lintable(text: str) -> str:
    """판정 사본. 코드 조각과 URL은 지운다 — 그 안의 글자는 글쓴이가 고를 수 있는 말이 아니다."""
    body = re.sub(r"`[^`]*`", " ", text)
    return re.sub(r"https?://\S+", " ", body)
