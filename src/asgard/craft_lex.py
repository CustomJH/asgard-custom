"""중괄호 계열 언어의 단위 추출 — 어휘 수준. C·C++·Java·Kotlin·Go·Rust·TS/JS·C#·Swift.

파서를 붙이지 않은 이유: 이 저장소는 언어별 손수 추출기로 지도를 만들어 왔고(map_graph의
extract_tsjs·extract_java·resolve_jvm), 언어마다 문법 의존을 하나씩 더하면 설치 무게가 언어 수만큼
늘어난다. 여기서 필요한 것은 완전한 구문 트리가 아니라 **함수의 경계·길이·중첩** 셋뿐이고, 그건
중괄호와 키워드만으로 충분히 잰다.

대신 정직해야 할 한계가 있다. 어휘 분석은 매크로로 만든 제어 구조, 중괄호 없는 한 줄 분기,
템플릿 안의 부등호, 언어별 특수 문법(Go의 함수 리터럴, Rust의 매크로 본문)을 정확히 못 읽는다.
그래서 이 모듈의 계약은 **못 읽은 것을 읽은 척하지 않는다** 하나다 — 신뢰할 수 없는 파일은 단위
없음(미판정)으로 돌려보내고, 애매한 것은 세지 않는다. 판정을 부풀리면 게이트가 꺼진다.

문자열과 주석은 세기 전에 지운다. 지우지 않으면 `"}"` 한 글자가 함수 경계를 통째로 어긋낸다 —
줄 구조는 보존한 채 내용만 공백으로 바꾼다(줄 번호가 판정의 좌표이므로).
"""

from __future__ import annotations

from .craft_rules import Unit

# 확장자 → 언어 가족. 가족이 다르면 주석·문자열 문법과 제어 키워드가 다르다.
LANG_BY_SUFFIX: dict[str, str] = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".java": "java",
    ".kt": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".swift": "swift",
    ".ts": "ts",
    ".tsx": "ts",
    ".js": "ts",
    ".jsx": "ts",
    ".mjs": "ts",
    ".cjs": "ts",
}
C_FAMILY = frozenset({"c", "cpp"})
# 제어 헤더를 괄호로 감싸는 언어 — 이 언어들에서만 세미콜론이 절을 끝낸다고 볼 수 있다.
PAREN_HEADER_LANGS = frozenset({"c", "cpp", "java", "csharp", "ts"})

# 블록을 여는 제어 키워드 — 중첩 깊이는 이것으로 센다. 중괄호 깊이를 그대로 쓰면 배열 초기화와
# 구조체 리터럴이 중첩으로 잡혀 Python 쪽(_depth는 분기 구문만 센다)과 자가 달라진다.
_CONTROL = frozenset(
    {
        "if", "else", "for", "while", "do", "switch", "try", "catch", "finally",
        "foreach", "loop", "match", "when", "unless", "guard", "defer", "select",
    }
)  # fmt: skip
# 함수처럼 보이지만 아닌 것 — `if (x) {`를 함수로 읽으면 파일 하나가 통째로 어긋난다.
_NOT_A_NAME = _CONTROL | frozenset({"return", "sizeof", "new", "delete", "throw", "await", "yield", "typeof"})
# 여는 중괄호 앞에 오면 함수 본문이 아니라 타입 본문인 것.
_TYPE_KEYWORDS = frozenset(
    {
        "struct",
        "enum",
        "union",
        "class",
        "interface",
        "namespace",
        "impl",
        "trait",
        "extern",
        "typedef",
        "record",
        "object",
        "protocol",
        "extension",
    }  # fmt: skip
)


def language(path: str) -> str | None:
    dot = path.rfind(".")
    return LANG_BY_SUFFIX.get(path[dot:].lower()) if dot >= 0 else None


def scrub(text: str, lang: str) -> str:
    """주석·문자열 내용을 공백으로 바꾼 사본. 줄 수와 각 줄 길이는 보존한다.

    C 계열 전처리기 줄도 지운다 — `#define BLOCK { do {` 같은 매크로가 중괄호 균형을 깨는데,
    매크로 확장은 어휘 분석이 따라갈 수 있는 영역이 아니다(못 읽는 것으로 남긴다).
    """
    out: list[str] = []
    state = _ScrubState(lang)
    for line in text.split("\n"):
        out.append(state.line(line))
    return "\n".join(out)


class _ScrubState:
    """줄을 넘나드는 상태(블록 주석·원시 문자열)를 들고 한 줄씩 지운다."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.in_block = False
        self.in_template = False  # 줄을 넘는 문자열 — TS 백틱 템플릿

    def line(self, raw: str) -> str:
        if self.lang in C_FAMILY and raw.lstrip().startswith("#") and not self.in_block and not self.in_template:
            return " " * len(raw)
        chars = list(raw)
        i = 0
        while i < len(chars):
            if self.in_block:
                i = self._block_end(chars, i)
            elif self.in_template:
                i = self._template_end(chars, i)
            else:
                i = self._scan(chars, i)
        return "".join(chars)

    def _template_end(self, chars: list[str], i: int) -> int:
        """백틱 템플릿은 여러 줄에 걸친다. 이 상태를 안 들고 다니면 둘째 줄부터 원문이 그대로
        세어져 HTML 조각 안의 중괄호가 함수 경계를 무너뜨린다(실측: 실코퍼스 TS 57파일 미판정)."""
        if chars[i] == "\\":
            chars[i] = " "
            if i + 1 < len(chars):
                chars[i + 1] = " "
            return i + 2
        if chars[i] == "`":
            self.in_template = False
            chars[i] = " "
            return i + 1
        chars[i] = " "
        return i + 1

    def _block_end(self, chars: list[str], i: int) -> int:
        if chars[i] == "*" and i + 1 < len(chars) and chars[i + 1] == "/":
            self.in_block = False
            chars[i] = chars[i + 1] = " "
            return i + 2
        chars[i] = " "
        return i + 1

    def _scan(self, chars: list[str], i: int) -> int:
        ch = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if ch == "/" and nxt not in ("/", "*") and self.lang == "ts" and _regex_position(chars, i):
            return _blank_regex(chars, i)
        if ch == "/" and nxt == "/":
            for j in range(i, len(chars)):
                chars[j] = " "
            return len(chars)
        if ch == "/" and nxt == "*":
            self.in_block = True
            chars[i] = chars[i + 1] = " "
            return i + 2
        if ch == "`":
            self.in_template = True
            chars[i] = " "
            return i + 1
        if ch in ("'", '"'):
            return _blank_string(chars, i, ch)
        return i + 1


def _blank_string(chars: list[str], start: int, quote: str) -> int:
    """따옴표 안을 공백으로. 이스케이프를 존중하고, 줄 끝까지 안 닫히면 거기서 멈춘다."""
    i = start + 1
    while i < len(chars):
        if chars[i] == "\\":
            chars[i] = " "
            if i + 1 < len(chars):
                chars[i + 1] = " "
            i += 2
            continue
        if chars[i] == quote:
            chars[i] = " "
            return i + 1
        chars[i] = " "
        i += 1
    return i


# 정규식 리터럴 뒤에 값이 올 수 없는 토큰들 — 이것들 다음의 `/`는 나눗셈이다.
_VALUE_END = frozenset(")]}")


def _regex_position(chars: list[str], i: int) -> bool:
    """이 `/`가 정규식의 시작인가. 앞의 유효 문자가 값의 끝이면 나눗셈이다."""
    j = i - 1
    while j >= 0 and chars[j].isspace():
        j -= 1
    if j < 0:
        return True
    prev = chars[j]
    return not (prev.isalnum() or prev in _VALUE_END or prev == "_")


def _blank_regex(chars: list[str], start: int) -> int:
    """정규식 본문을 공백으로. 문자 클래스 안의 `/`는 종료가 아니다.

    이걸 안 하면 `/[",\\n]/` 안의 따옴표가 문자열 시작으로 읽혀 뒤따르는 중괄호를 통째로
    삼킨다 (실측: 실코퍼스에서 남은 미판정 45건 대부분의 원인).
    """
    i = start + 1
    in_class = False
    while i < len(chars):
        ch = chars[i]
        if ch == "\\":
            chars[i] = " "
            if i + 1 < len(chars):
                chars[i + 1] = " "
            i += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            chars[i] = " "
            return i + 1
        chars[i] = " "
        i += 1
    return i


def _word_before(text: str, index: int) -> tuple[str, int]:
    """`index` 바로 앞의 식별자와 그 시작 위치. 없으면 ("", index)."""
    end = index
    while end > 0 and text[end - 1].isspace():
        end -= 1
    start = end
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_$"):
        start -= 1
    return (text[start:end], start)


def _signature_name(text: str, brace: int) -> tuple[str, int] | None:
    """여는 중괄호가 함수 본문이면 (이름, 서명 시작 위치). 아니면 None.

    판정은 하나뿐이다 — 중괄호 앞에 닫는 괄호가 있고, 그 괄호쌍 앞의 식별자가 제어 키워드가
    아닐 것. Go의 `func f() error {`, Rust의 `fn f() -> T {`, C++ 의 `T f() const {`처럼
    괄호와 중괄호 사이에 붙는 것들은 세지 않고 지나간다.
    """
    i = brace - 1
    while i >= 0 and (text[i].isspace() or text[i].isalnum() or text[i] in "_>&*:,-$."):
        i -= 1  # const·noexcept·-> T·초기화 리스트 없는 수식어를 건너뛴다
    if i < 0 or text[i] != ")":
        return None
    depth = 0
    while i >= 0:
        if text[i] == ")":
            depth += 1
        elif text[i] == "(":
            depth -= 1
            if depth == 0:
                break
        i -= 1
    if i < 0:
        return None
    name, start = _word_before(text, i)
    if not name or name in _NOT_A_NAME or name in _TYPE_KEYWORDS:
        return None
    if start > 0 and text[start - 1] == "@":
        return None  # `@SuppressWarnings("x")`는 호출처럼 생겼지만 애너테이션이다
    if _opens_type(text, brace):
        # 타입 선언 앞에 붙은 애너테이션의 괄호가 이 중괄호의 서명으로 읽힌다. 그대로 두면
        # 클래스 본문 전체가 함수 하나로 잡혀 2,487행짜리 가짜 단위가 생긴다(실측 결함).
        return None
    return (name, start)


def units(text: str, lang: str) -> dict[str, Unit] | None:
    """qualname → 단위 사실. 중괄호가 안 맞으면 None (못 읽은 것은 미판정으로 돌려보낸다)."""
    body = scrub(text, lang)
    if body.count("{") != body.count("}"):
        return None
    starts = _line_starts(body)
    out: dict[str, Unit] = {}
    for name, open_at, close_at in _functions(body):
        line = _line_of(starts, open_at)
        end = _line_of(starts, close_at)
        key = name if name not in out else f"{name}#{line}"  # 오버로드·동명 정적 함수
        out[key] = Unit(
            key, line, end, end - line + 1, _depth(body, open_at, close_at, lang), _stmts(body, open_at, close_at)
        )
    return out


def _functions(body: str):
    """(이름, 서명 시작 오프셋, 닫는 중괄호 오프셋) — 함수 안의 중첩 함수는 따로 세지 않는다.

    타입 본문(class·struct·namespace·impl) 안쪽도 판정 대상이다. 최상단만 보면 Java·C#·
    TS·Kotlin·C++ 의 메서드가 통째로 안 잡힌다 — 그 언어들에서 함수는 대부분 타입 안에 있다.
    """
    frames: list[str] = []  # "type"만 쌓여 있는 동안에만 함수 서명을 찾는다
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "{":
            inside_type_only = all(kind == "type" for kind in frames)
            found = _signature_name(body, i) if inside_type_only else None
            if found:
                close = _match(body, i)
                if close < 0:
                    return
                yield (found[0], found[1], close)
                i = close + 1
                continue
            frames.append("type" if _opens_type(body, i) else "block")
        elif ch == "}":
            if frames:
                frames.pop()
        i += 1


def _opens_type(body: str, brace: int) -> bool:
    """이 중괄호가 타입 본문을 여는가 — 직전 절에 타입 키워드가 있으면 그렇다."""
    start = max(body.rfind(";", 0, brace), body.rfind("{", 0, brace), body.rfind("}", 0, brace)) + 1
    clause = body[start:brace]
    return any(word in _TYPE_KEYWORDS for word in clause.replace(":", " ").split())


def _match(body: str, open_at: int) -> int:
    depth = 0
    for i in range(open_at, len(body)):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _depth(body: str, open_at: int, close_at: int, lang: str) -> int:
    """제어 키워드가 연 블록의 최대 중첩. 중괄호 없는 한 줄 분기는 못 센다(과소 계상, 한계)."""
    stack: list[bool] = []
    best = 0
    pending = False
    parens = 0
    for token, kind in _tokens(body, open_at + 1, close_at):
        if kind == "word":
            pending = pending or token in _CONTROL
        elif token == "(":
            parens += 1
        elif token == ")":
            parens = max(0, parens - 1)
        elif token == "{":
            stack.append(pending)
            best = max(best, sum(1 for flag in stack if flag))
            pending = False
        elif token == "}":
            if stack:
                stack.pop()
        elif token == ";" and parens == 0 and lang in PAREN_HEADER_LANGS:
            # 괄호 **밖의** 세미콜론만 절을 끝낸다. `for (i = 0; i < n; i++)`의 헤더 세미콜론이
            # 여기서 걸리면 for가 연 블록이 중첩으로 안 세어져 깊이가 하나씩 낮아진다. 헤더에
            # 괄호를 안 쓰는 언어(Go의 3절 for)는 이 규칙 자체가 반대로 작동하므로 제외한다.
            pending = False
    return best


def _stmts(body: str, open_at: int, close_at: int) -> int:
    """문장 수의 대리 지표 = 세미콜론 + 블록 수. 길이가 데이터인지 로직인지 가르는 데 쓴다."""
    region = body[open_at:close_at]
    return region.count(";") + region.count("{") - 1


def _tokens(body: str, start: int, stop: int):
    i = start
    while i < stop:
        ch = body[i]
        if ch.isalpha() or ch == "_":
            j = i
            while j < stop and (body[j].isalnum() or body[j] == "_"):
                j += 1
            yield (body[i:j], "word")
            i = j
            continue
        if not ch.isspace():
            yield (ch, "punct")
        i += 1


def _line_starts(body: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(body):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _line_of(starts: list[int], offset: int) -> int:
    low, high = 0, len(starts) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if starts[mid] <= offset:
            low = mid
        else:
            high = mid - 1
    return low + 1
