"""C·C++ 의 자원 수명·경계·비용 규칙. MISRA C:2025와 CERT C를 우리 말로 재서술한 것.

왜 이 언어에 따로 규칙이 필요한가: Python에서 누수는 "언젠가 회수되지만 늦게"지만 C 에서는
회수가 아예 없다. 해제는 언어가 아니라 사람이 하고, 그래서 코드 규약이 안전의 마지막 층이다.
자동차·항공·의료·산업제어가 언어의 부분집합(MISRA)이나 위험 사용 지침(CERT)을 강제하는 이유다.

담는 방식은 두 표준의 성격 차이를 그대로 따른다. MISRA는 쓸 수 있는 문법을 좁히고, CERT는
위험한 기능을 안전하게 쓰는 법을 준다. 여기 있는 규칙은 후자 쪽이다 — malloc을 금지하지 않고,
소유자가 없는 malloc을 지목한다. 금지형 규칙은 프로젝트가 그 표준을 채택했을 때만 의미가 있고,
그 판단은 게이트가 아니라 프로젝트 관행이 한다(역할 계약: 프로젝트가 일반 캐논을 이긴다).

어휘 분석이라 못 보는 것이 많다. 함수 경계를 넘는 소유 이전, 매크로가 만든 제어 흐름, 포인터
별칭, 조건부 해제 경로는 전부 미검출이다. 잡는 것은 **한 함수 안에서 눈으로 확인되는 형상**뿐이고,
그래서 오탐이 적다. 못 보는 영역은 스킬(마그니·언어 캐논)이 사람 판단으로 덮는다.
"""

from __future__ import annotations

import re

from .craft_lex import scrub
from .craft_rules import Finding, Unit

# 할당은 소유를 만든다 — 이 호출들의 결과에는 반드시 주인이 있어야 한다.
_ALLOC = r"(?:malloc|calloc|realloc|strdup|strndup|aligned_alloc|reallocarray)"
_ASSIGN_ALLOC = re.compile(r"=\s*(?:\([^)]*\)\s*)?" + _ALLOC + r"\s*\(")
_ASSIGN_HANDLE = re.compile(r"=\s*(?:\([^)]*\)\s*)?(fopen|freopen|tmpfile|popen|opendir)\s*\(")
_REALLOC_SELF = re.compile(r"(?:^|[^\w.>])(\w+)\s*=\s*(?:\([^)]*\)\s*)?realloc\s*\(\s*\1\s*[,)]")
# 두 표준이 공통으로 지목하는, 대상 크기를 모르는 복사·형식화.
_UNBOUNDED = re.compile(r"(?:^|[^\w.>])(gets|strcpy|strcat|sprintf|vsprintf)\s*\(")
_STRLEN_IN_FOR = re.compile(r"\bfor\s*\([^;]*;[^;]*\b(strlen|wcslen)\s*\(")


def pattern_findings(text: str, rel: str, spans: list[Unit], lang: str) -> list[Finding]:
    """C 계열 판정. 함수 단위로 잘라서 본다 — 소유는 함수 안에서만 눈으로 확인된다."""
    body = scrub(text, lang)
    lines = body.split("\n")
    out: list[Finding] = []
    for unit in sorted(spans, key=lambda u: u.line):
        region = "\n".join(lines[unit.line - 1 : unit.end])
        out.extend(_unit_findings(region, rel, unit))
    return out


def _unit_findings(region: str, rel: str, unit: Unit) -> list[Finding]:
    out: list[Finding] = []
    out.extend(_alloc_findings(region, rel, unit))
    out.extend(_realloc_findings(region, rel, unit))
    out.extend(_handle_findings(region, rel, unit))
    out.extend(_bounds_findings(region, rel, unit))
    out.extend(_cost_findings(region, rel, unit))
    return out


def _line_at(region: str, offset: int, unit: Unit) -> int:
    return unit.line + region.count("\n", 0, offset)


_CALL_ARG_SLOT = re.compile(r"\w\s*\(\s*(?:[^()]*,\s*)?$")  # `fgetc(` · `memcpy(dst, ` — 인자 자리


def _returned(region: str, name: str) -> bool:
    """반환식이 그 이름을 **넘기는가**, 아니면 그냥 **쓰는가**.

    `return f;`와 `return cond ? f : NULL;`은 소유를 호출자에게 넘긴다. 그러나
    `return fgetc(f);`와 `return buf[0];`은 자원을 **읽은 결과**를 돌려줄 뿐이고 자원 자체는
    이 함수에 남는다. 둘을 "반환문 안에 이름이 보인다"로 똑같이 읽으면, C에서 가장 흔한 형상에서
    누수 규칙이 조용히 꺼진다 — 실측에서 `fopen`·`malloc` 두 규칙이 이 한 줄 때문에 함께 죽었다.
    """
    bare = re.escape(name)
    for statement in re.finditer(r"\breturn\b([^;]*);", region):
        expression = statement.group(1)
        for hit in re.finditer(r"\b" + bare + r"\b", expression):
            after = expression[hit.end() :].lstrip()
            if after[:1] in ("[", "(", ".", "-"):
                continue  # buf[0] · f(…) · f->fd — 이름을 통해 무언가를 읽는 것이다
            if _CALL_ARG_SLOT.search(expression[: hit.start()]):
                continue  # fgetc(f) — 인자 자리이지 반환값이 아니다
            return True
    return False


def _owner_escapes(region: str, name: str, *, via_call: bool) -> bool:
    """소유가 이 함수 밖으로 나갔는가 — 반환·필드 대입·별칭·(선택적으로) 다른 호출의 인자.

    `via_call`을 자원 종류마다 다르게 두는 이유: 할당한 메모리를 함수에 넘기는 것은 인계인
    경우가 많지만(`list_add(l, buf)`), 열어 둔 파일 핸들을 넘기는 것은 대개 그냥 쓰는 것이다
    (`fgetc(f)`). 같은 규칙으로 읽으면 전자는 오탐이 되고 후자는 미검출이 된다.
    """
    bare = re.escape(name)
    if _returned(region, name):
        return True
    if re.search(r"(?:->|\.)\s*\w+\s*=\s*" + bare + r"\s*;", region):
        return True
    if re.search(r"\b\w+\s*=\s*" + bare + r"\s*;", region):
        return True  # `q = tmp;` — realloc의 정석 형태에서 소유는 다른 이름으로 옮겨간다
    if not via_call:
        return False
    # 넘긴 뒤의 수명은 이 분석이 못 따라간다 — 못 따라가는 것을 누수라 부르지 않는다.
    return bool(re.search(r"\b\w+\s*\([^)]*\b" + bare + r"\b[^)]*\)\s*;", region))


def _freed(region: str, name: str) -> bool:
    bare = re.escape(name)
    return bool(re.search(r"\bfree\s*\(\s*\*?\s*" + bare + r"\s*\)", region))


def _target(region: str, eq: int) -> str | None:
    """대입문의 왼쪽이 가리키는 지역 변수 이름. 소유가 밖으로 가는 형태면 None.

    `char *buf = malloc(n)`의 `*`는 타입의 일부이고 `*out = malloc(n)`의 `*`는 역참조다 —
    같은 글자를 같게 읽으면 전자를 전부 놓친다(실측 결함). 가르는 것은 앞에 타입 낱말이 있는가다.
    """
    start = max(region.rfind(";", 0, eq), region.rfind("{", 0, eq), region.rfind("}", 0, eq), region.rfind("\n", 0, eq))
    left = region[start + 1 : eq]
    if "->" in left or "." in left or "[" in left:
        return None  # 구조체 필드·배열 원소로 들어간 순간 소유자는 그 객체다
    words = re.findall(r"[A-Za-z_]\w*", left)
    if not words:
        return None
    if len(words) == 1 and "*" in left:
        return None  # `*out = malloc(...)` — 호출자에게 넘기는 출력 인자
    return words[-1]


def _alloc_findings(region: str, rel: str, unit: Unit) -> list[Finding]:
    out: list[Finding] = []
    for match in _ASSIGN_ALLOC.finditer(region):
        name = _target(region, match.start())
        if name is None:
            continue
        line = _line_at(region, match.start(), unit)
        if not _freed(region, name) and not _owner_escapes(region, name, via_call=True):
            out.append(
                Finding(
                    "c-alloc-unfreed",
                    rel,
                    line,
                    unit.qualname,
                    f"{name}이 할당만 되고 이 함수 안에서 주인을 못 찾는다 (free도 반환도 인계도 없음)",
                    "할당한 자리에서 해제 경로를 함께 써라 — 실패 분기까지 포함해서, goto cleanup 이든 단일 출구든",
                )
            )
        if not _checked(region, name):
            out.append(
                Finding(
                    "c-alloc-unchecked",
                    rel,
                    line,
                    unit.qualname,
                    f"{name}의 할당 실패를 이 함수 어디에서도 검사하지 않는다",
                    "할당 직후에 NULL을 검사하라 — 실패한 포인터를 역참조하면 그 자리가 아니라 나중에 터진다",
                )
            )
    return out


def _checked(region: str, name: str) -> bool:
    bare = re.escape(name)
    return bool(
        re.search(r"\bif\s*\(\s*!?\s*" + bare + r"\s*(?:==|!=)?\s*(?:NULL|nullptr|0)?\s*\)", region)
        or re.search(r"\b" + bare + r"\s*(?:==|!=)\s*(?:NULL|nullptr|0)\b", region)
        or re.search(r"\bassert\s*\(\s*" + bare + r"\b", region)
    )


def _realloc_findings(region: str, rel: str, unit: Unit) -> list[Finding]:
    out: list[Finding] = []
    for match in _REALLOC_SELF.finditer(region):
        name = match.group(1)
        out.append(
            Finding(
                "c-realloc-self-assign",
                rel,
                _line_at(region, match.start(), unit),
                unit.qualname,
                f"{name} = realloc({name}, …) — 실패하면 NULL이 덮어써서 원래 블록으로 가는 길이 사라진다",
                "임시 포인터로 받아 성공을 확인한 뒤에 옮겨 담아라 — 실패해도 원본은 살아 있어야 한다",
            )
        )
    return out


def _handle_findings(region: str, rel: str, unit: Unit) -> list[Finding]:
    closers = {"fopen": "fclose", "freopen": "fclose", "tmpfile": "fclose", "popen": "pclose", "opendir": "closedir"}
    out: list[Finding] = []
    for match in _ASSIGN_HANDLE.finditer(region):
        name = _target(region, match.start())
        if name is None:
            continue
        call = match.group(1)
        closer = closers[call]
        if re.search(r"\b" + closer + r"\s*\(\s*" + re.escape(name) + r"\s*\)", region) or _owner_escapes(
            region, name, via_call=False
        ):
            continue
        out.append(
            Finding(
                "c-handle-unclosed",
                rel,
                _line_at(region, match.start(), unit),
                unit.qualname,
                f"{call}()로 연 {name}을 이 함수 안에서 닫지 않는다",
                f"{closer}()를 모든 출구에 두어라 — 이른 return 하나가 핸들을 영원히 잡는다",
            )
        )
    return out


def _bounds_findings(region: str, rel: str, unit: Unit) -> list[Finding]:
    out: list[Finding] = []
    for match in _UNBOUNDED.finditer(region):
        call = match.group(1)
        out.append(
            Finding(
                "c-unbounded-copy",
                rel,
                _line_at(region, match.start(), unit),
                unit.qualname,
                f"{call}()는 대상 크기를 모른다 — 입력 길이가 곧 쓰기 길이가 된다",
                "크기를 받는 형태로 바꿔라 (snprintf·strncat·경계를 명시한 memcpy), 그리고 잘림도 처리하라",
            )
        )
    return out


def _cost_findings(region: str, rel: str, unit: Unit) -> list[Finding]:
    out: list[Finding] = []
    for match in _STRLEN_IN_FOR.finditer(region):
        call = match.group(1)
        out.append(
            Finding(
                "c-quadratic-scan",
                rel,
                _line_at(region, match.start(), unit),
                unit.qualname,
                f"루프 조건에서 매 회전마다 {call}()을 다시 센다 — 문자열 길이의 제곱이 된다",
                "길이를 루프 밖에서 한 번 재서 변수에 담아라",
            )
        )
    return out
