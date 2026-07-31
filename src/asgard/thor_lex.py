"""토르 게이트 규칙 (중괄호 계열) — Java·Kotlin·C#·TS/JS·Go·Swift·Rust.

Python만 판정하는 백엔드 게이트는 거의 아무 백엔드도 판정하지 못한다. 그래서 어휘 수준에서
증명되는 것을 여기로 옮긴다. 전 언어 공통 셋: **삼킨 예외 · 하드코딩된 시크릿 · SQL 문자열 보간**.
JVM 에는 둘을 더 옮겼다 — **부동소수 금액**과 **@Transactional 안의 외부 I/O**.

JVM에서 그 둘이 되는 이유는 어휘가 더 똑똑해서가 아니라 언어가 더 많이 말해 주기 때문이다.
`double amount`는 선언에 타입이 붙어 있어 추론이 필요 없고(파이썬보다 오히려 쉽다),
`@Transactional`은 경계를 애너테이션으로 못 박아 준다(`with`를 따라가는 것보다 쉽다).

타임아웃은 여전히 안 옮겼다 — 클라이언트마다 이름이 다르고, 설정이 호출부가 아니라 빈 정의나
설정 파일에 있어서 한 문장 안에서 부재를 증명할 수 없다. 못 옮긴 규칙은 미측정으로 정직하게
보고한다(`thor_gate.unmeasured`).

`craft_lex.scrub`을 쓰는 곳과 원문을 쓰는 곳이 갈린다. 구조(빈 catch 본문)는 문자열·주석이
지워진 사본에서 봐야 문자열 안의 `catch {}`에 속지 않고, 내용(SQL·시크릿)은 원문에서만 보인다.
"""

from __future__ import annotations

import re

from .craft_lex import language, scrub
from .craft_rules import Finding, Unit, _owner
from .thor_rules import _VALUE_SLOT, _secretish, money_name, secret_name, sql_shaped

# 이 파일이 판정하는 언어. Rust는 catch가 없고 Go도 없다 — 시크릿·SQL만 걸린다.
JUDGED = frozenset({"java", "kotlin", "csharp", "ts", "go", "swift", "rust"})
_NO_CATCH = frozenset({"go", "rust"})  # catch 문법 자체가 없다 — 규칙을 발화시키지 않는다

# 잡아도 반례가 없는 넓은 예외 타입. 좁은 타입의 침묵은 알림에 그친다(Python 쪽과 같은 갈래).
_BROAD_TYPE = re.compile(r"\b(Exception|Throwable|RuntimeException|Error|NSError|Any)\b")
_CATCH_EMPTY = re.compile(r"\bcatch\b([^{;]*)\{(\s*)\}")
# 언어별 선언 문법을 하나로 — `val x = "..."`, `String x = "..."`, `x: String = "..."`, `x := "..."`.
_ASSIGN = re.compile(
    r"""(?:^|[;{}\s])(?:(?:const|let|var|val|final|static|readonly|private|public|protected)\s+)*"""
    r"""(?:[A-Za-z_][\w<>\[\].]*\s+)?([A-Za-z_]\w*)\s*(?::\s*[\w<>\[\].?]+\s*)?(?::?=)\s*(["'`])([^"'`\n]*)\2"""
)
# 문자열 안의 구멍 — Kotlin/Swift `$x`·`\(x)`, TS/Kotlin `${...}`, C# `{0}`, Java `%s`.
_HOLE_IN_STRING = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_]\w*|\\\([^)]*\)|\{\d+\}|%[sdf]")
_STRING = re.compile(r"(\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`)", re.S)
# 문자열 뒤에 이어지는 `+ <식별자>` — 자바·C# 의 고전적인 질의 조립.
_CONCAT_HOLE = re.compile(r"\+\s*(?![\"'`])[A-Za-z_(]")


def _line_of(starts: list[int], offset: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def _starts(text: str) -> list[int]:
    out, pos = [0], 0
    for line in text.split("\n")[:-1]:
        pos += len(line) + 1
        out.append(pos)
    return out


# ── ① 삼킨 예외 ────────────────────────────────────────────────────


def _catch_findings(raw: str, clean: str, rel: str, spans: list[Unit], starts: list[int], lang: str) -> list[Finding]:
    out: list[Finding] = []
    for match in _CATCH_EMPTY.finditer(clean):
        line = _line_of(starts, match.start())
        header = match.group(1)
        # 본문에 주석이 있으면 "의도된 침묵"의 근거가 코드에 남아 있는 것 — 알림으로 낮춘다.
        body = raw[match.start(2) : match.end(2)]
        # TS/JS의 catch는 타입을 못 붙인다 — 전부 넓다. 타입 없는 catch를 좁다고 읽으면 이 언어
        # 에서는 규칙이 통째로 발화하지 않는다.
        broad = lang == "ts" or bool(_BROAD_TYPE.search(header)) or not header.strip().strip("()")
        blocking = broad and "//" not in body and "/*" not in body
        out.append(
            Finding(
                "swallowed-exception",
                rel,
                line,
                _owner(spans, line),
                "catch 본문이 비어 있다" + ("" if broad else " (좁은 타입)"),
                "처리할 수 없으면 문맥을 붙여 전파해라 — 삼킬 근거가 있으면 그 근거를 코드에 남겨라",
                blocking=blocking,
            )
        )
    return out


# ── ② 하드코딩된 시크릿 ─────────────────────────────────────────────


def _secret_findings(raw: str, rel: str, spans: list[Unit], starts: list[int]) -> list[Finding]:
    out: list[Finding] = []
    for match in _ASSIGN.finditer(raw):
        name, value = match.group(1), match.group(3)
        if not secret_name(name) or not _secretish(value):
            continue
        line = _line_of(starts, match.start(1))
        out.append(
            Finding(
                "secret-literal",
                rel,
                line,
                _owner(spans, line),
                f"{name}에 비밀처럼 생긴 문자열이 박혀 있다",
                "환경변수·시크릿 저장소로 옮기고, 이미 커밋됐으면 그 값을 폐기해라",
            )
        )
    return out


# ── ③ SQL 문자열 보간 ───────────────────────────────────────────────


def _statements(clean: str) -> list[tuple[int, int]]:
    """문장 경계 — 질의는 여러 줄에 걸쳐 이어붙여지므로 줄 단위로는 못 본다."""
    out: list[tuple[int, int]] = []
    start = 0
    for i, char in enumerate(clean):
        if char in ";{}":
            if i > start:
                out.append((start, i))
            start = i + 1
    if start < len(clean):
        out.append((start, len(clean)))
    return out


def _sql_holes(region: str) -> list[str] | None:
    """SQL 질의면 각 구멍 앞의 문맥을, 아니면 None."""
    literals = [m.group(1)[1:-1] for m in _STRING.finditer(region)]
    if not literals:
        return None
    # 구멍을 **지운 뒤**에 질의인지 묻는다. 백틱 문자열은 `${...}` 안의 식까지 통째로 잡히므로,
    # 원문 그대로 재면 보간식 안의 메서드 이름이 질의어가 된다(실측: `LOCALES.join('|')`의
    # `join`이 절로 읽혀 빌드 스크립트가 막혔다). 질의 본문이 아닌 것은 판정에 넣지 않는다.
    # 줄바꿈으로 잇는다 — 리터럴 하나하나가 질의를 열 수 있다. 공백으로 이으면 앞 리터럴의
    # 마지막 낱말이 동사 앞에 서서, 질의를 여는 리터럴이 산문 한가운데로 읽힌다(sql_shaped 계약).
    if not sql_shaped("\n".join(_HOLE_IN_STRING.sub(" ", literal) for literal in literals)):
        return None
    before: list[str] = []
    for literal in literals:
        cursor = 0
        for hole in _HOLE_IN_STRING.finditer(literal):
            before.append(literal[cursor : hole.start()])
            cursor = hole.end()
    for match in _CONCAT_HOLE.finditer(region):
        prior = _STRING.findall(region[: match.start()])
        before.append(prior[-1][1:-1] if prior else "")
    return before or None


def _sql_findings(raw: str, clean: str, rel: str, spans: list[Unit], starts: list[int]) -> list[Finding]:
    out: list[Finding] = []
    for start, end in _statements(clean):
        before = _sql_holes(raw[start:end])
        if before is None:
            continue
        value_slot = any(_VALUE_SLOT.search(chunk.rstrip()) for chunk in before)
        line = _line_of(starts, start + len(raw[start:end]) - len(raw[start:end].lstrip()))
        out.append(
            Finding(
                "sql-interpolated",
                rel,
                line,
                _owner(spans, line),
                "값 자리에 문자열 보간" if value_slot else "SQL 문자열을 보간으로 조립 (식별자 자리)",
                "파라미터 바인딩으로 옮겨라 — 값 자리는 바인딩으로 전부 대체된다"
                if value_slot
                else "식별자는 바인딩이 안 된다 — 허용 목록으로 좁히고 그 근거를 남겨라",
                blocking=value_slot,
            )
        )
    return out


# ── ④ 부동소수 금액 (JVM 한정) ───────────────────────────────────────
# 정적 타입 언어에서는 이게 Python보다 **더** 잘 보인다 — 선언에 타입이 붙어 있어서 추론이 필요
# 없다. `double amount`는 그 자리에서 끝나는 사실이다.
_JVM_MONEY_DECL = re.compile(
    r"\b(?:double|float|Double|Float|BigDecimal)\s+([A-Za-z_]\w*)\s*[=;,)]"  # Java: double amount
    r"|\b(?:val|var)\s+([A-Za-z_]\w*)\s*:\s*(?:Double|Float)\b"  # Kotlin: val amount: Double
)


def _money_findings(raw: str, clean: str, rel: str, spans: list[Unit], starts: list[int]) -> list[Finding]:
    out: list[Finding] = []
    for match in _JVM_MONEY_DECL.finditer(clean):
        name = match.group(1) or match.group(2) or ""
        # BigDecimal은 금액에 **옳은** 타입이다 — 이름만 보고 걸면 정답을 결함으로 만든다.
        if "BigDecimal" in match.group(0) or not money_name(name):
            continue
        line = _line_of(starts, match.start())
        out.append(
            Finding(
                "money-float",
                rel,
                line,
                _owner(spans, line),
                f"{name}을 부동소수로 다룬다 — 0.1 + 0.2는 0.3이 아니다",
                "정수 최소단위(원·센트)나 BigDecimal로 바꿔라",
            )
        )
    return out


# ── ⑤ 트랜잭션 안의 외부 I/O (JVM 한정) ──────────────────────────────
# `@Transactional`은 경계를 **선언**으로 못 박아 준다 — 파이썬의 `with`보다 찾기 쉽다.
_TX_ANNOTATION = re.compile(r"@Transactional\b")
# 커밋 전에 되돌릴 수 없는 부수효과를 내는 호출들. 이름이 곧 의미인 것만 넣는다.
_JVM_EXTERNAL = re.compile(
    r"\b(?:restTemplate|webClient|httpClient|feignClient|okHttpClient)\s*\.|"
    r"\b(?:kafkaTemplate|rabbitTemplate|jmsTemplate|sqsClient|snsClient)\s*\.\s*(?:send|convertAndSend|publish)|"
    r"\bHttpClient\s*\.\s*newHttpClient\b|\bmailSender\s*\.\s*send"
)


def _match_brace(clean: str, open_at: int) -> int | None:
    """`open_at`의 여는 중괄호와 짝인 닫는 중괄호 위치. 안 닫히면 None.

    `_body_after`에서 들어냈다 — 본문 **시작**을 찾는 일과 그 본문의 **끝**을 맞추는 일은
    서로 다른 문제이고, 한 함수에 두면 괄호 깊이 변수가 둘(`depth`·`level`) 살아 있는 자리가
    생긴다. 이름이 없으면 그 둘을 헷갈리는 순간을 아무도 못 잡는다.
    """
    level = 0
    for j in range(open_at, len(clean)):
        if clean[j] == "{":
            level += 1
        elif clean[j] == "}":
            level -= 1
            if level == 0:
                return j if j > open_at else None
    return None


def _body_after(clean: str, start: int) -> tuple[int, int] | None:
    """애너테이션 뒤에 오는 메서드 본문의 (여는 중괄호, 닫는 중괄호). 못 맞추면 None.

    `craft_lex`의 단위 추출에 기대지 않고 직접 맞춘다. 그쪽은 `record`를 자바 record 타입 키워드로
    읽어서 `void record(...)`를 단위로 잡지 못하는데(실전 검증에서 발견), 단위를 못 잡았다는 이유로
    **정확성 규칙이 조용히 꺼지면** 안 된다. 침묵이 곧 통과가 되는 구조는 게이트가 아니다.
    """
    depth = 0
    for i in range(start, len(clean)):
        char = clean[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth == 0:
            return None  # 본문 없는 선언 (인터페이스·추상 메서드)
        elif char == "{" and depth == 0:
            close = _match_brace(clean, i)
            return None if close is None else (i, close)
    return None


def _tx_findings(raw: str, clean: str, rel: str, spans: list[Unit], starts: list[int]) -> list[Finding]:
    out: list[Finding] = []
    for annotation in _TX_ANNOTATION.finditer(clean):
        span = _body_after(clean, annotation.end())
        if span is None:
            continue
        open_at, close_at = span
        hit = _JVM_EXTERNAL.search(clean, open_at, close_at)
        if hit is None:
            continue
        line = _line_of(starts, hit.start())
        out.append(
            Finding(
                "tx-external-io",
                rel,
                line,
                _owner(spans, line),
                "@Transactional 안에서 외부 호출 — 커밋 전 부수효과는 롤백이 되돌리지 못한다",
                "트랜잭션 밖으로 빼거나 outbox로 옮겨라",
            )
        )
    return out


_JVM = frozenset({"java", "kotlin"})


def findings(text: str, rel: str, spans: list[Unit], lang: str) -> list[Finding] | None:
    if lang not in JUDGED:
        return None
    clean = scrub(text, lang)
    starts = _starts(text)
    out = _secret_findings(text, rel, spans, starts) + _sql_findings(text, clean, rel, spans, starts)
    if lang not in _NO_CATCH:
        out.extend(_catch_findings(text, clean, rel, spans, starts, lang))
    if lang in _JVM:
        out.extend(_money_findings(text, clean, rel, spans, starts))
        out.extend(_tx_findings(text, clean, rel, spans, starts))
    return sorted(out, key=lambda f: (f.line, f.rule))


def lang_of(path: str) -> str | None:
    lang = language(path)
    return lang if lang in JUDGED else None
