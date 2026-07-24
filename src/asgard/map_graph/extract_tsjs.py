"""TS/JS(+prisma, Vue/Svelte SFC) 증거 추출기 — 정규식 기반 보조 추출기.

정규식은 구문 증명이 아니다: 관용구가 강한 패턴(Express 라우트, Nest 데코레이터, prisma
model)만 confirmed 로 표시하고 나머지는 전부 candidate 로 남긴다. tree-sitter 승격 여지를
위해 인터페이스는 extract_python 과 동일하게 유지한다.

프론트 레인: 파일 기반 라우팅(page)·전역 상태(store)·관례 디렉터리 컴포저블(composable)·
HTTP 래퍼 호출(api_call). 파일 경로에서 결정론적으로 유도되는 page 만 confirmed 이고,
래퍼 호출은 베이스 URL 을 증명할 수 없어 candidate 로 남는다.
"""

from __future__ import annotations

import re

from .evidence import Evidence, safe_url

_ROUTE = re.compile(
    r"\b(app|router|server|fastify)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*['\"`](/[^'\"`]*)", re.I
)
_ROUTE_BINDING = re.compile(
    r"\b(?:const|let|var)\s+(app|router|server|fastify)\s*=\s*(?:express\s*\(\s*\)|(?:express\s*\.\s*)?Router\s*\(\s*\)|fastify\s*\(\s*\))",
    re.I,
)
_NEST_ROUTE = re.compile(r"@(Get|Post|Put|Delete|Patch)\s*\(\s*(?:['\"`]([^'\"`)]*)['\"`])?\s*\)")
# `$fetch` 는 프론트 래퍼 패스가 소유한다 — lookbehind 로 이중 계상을 막는다.
_API_CALL = re.compile(
    r"(?<![\w$])(?:fetch|axios(?:\s*\.\s*(?:get|post|put|delete|patch|request))?)\s*\(\s*['\"`]([^'\"`]+)"
)
_PRISMA_MODEL = re.compile(r"^\s*model\s+(\w+)\s*\{", re.M)
_DRIZZLE_TABLE = re.compile(r"\b(?:pgTable|mysqlTable|sqliteTable)\s*\(\s*['\"`](\w+)")
_JOB = re.compile(r"\bcron\s*\.\s*schedule\s*\(|\bnew\s+CronJob\s*\(|@Cron\s*\(")
_IMPORT = re.compile(r"(?:from\s+['\"]([^'\"]+)['\"]|require\s*\(\s*['\"]([^'\"]+)['\"])")
# ---- 프론트 레인 ----------------------------------------------------------------
# HTTP 래퍼 관용구 — apiGet/apiPost 류 프로젝트 래퍼, Nuxt $fetch/useFetch, ofetch.
# 리터럴 경로(선행 `/` 또는 절대 URL)만 증거다; 변수 인자는 주장을 만들지 않는다.
_WRAPPER_CALL = re.compile(
    r"(?<![\w$.])(api[A-Z]\w*|apiClient\s*\.\s*(?:get|post|put|delete|patch)|\$fetch(?:\s*\.\s*raw)?|useFetch|ofetch)"
    r"\s*(?:<[^<>()]{0,200}>)?\s*\(\s*(['\"`])((?:/|https?://)[^'\"`\n]*)\2"
)
# 템플릿 보간 → `{}` 정규화 — 노드 id 를 값이 아니라 경로 모양으로 수렴시킨다.
_TEMPLATE_EXPR = re.compile(r"\$\{[^{}]*\}")
_PINIA_STORE = re.compile(r"\bdefineStore\s*\(\s*['\"`]([\w./-]+)['\"`]")
_REDUX_SLICE = re.compile(r"\bcreateSlice\s*\(\s*\{[^{}]{0,200}?\bname\s*:\s*['\"`]([\w./-]+)['\"`]", re.S)
_COMPOSABLE = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function\s+(use[A-Z]\w*)|const\s+(use[A-Z]\w*)\s*=)", re.M
)
_COMPOSABLE_DIRS = {"composables", "hooks"}
# 파일 기반 라우팅 관례 — 라우트 그룹 `(group)` 은 URL 에서 사라지고, `[param]`/`_param` 은
# 경로 변수다. 확장자별 프레임워크 표기는 detail 로만 남긴다 (관례 추정이지 증명이 아니다).
_SFC_SUFFIXES = (".vue", ".svelte")
_PAGE_SUFFIXES = {".vue": "nuxt", ".svelte": "sveltekit", ".tsx": "next", ".jsx": "next", ".ts": "next", ".js": "next"}
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
# 컴포넌트 합성 — 선언은 components/ 트리의 SFC/JSX 파일(스템=컴포넌트명), 소비는 템플릿/JSX
# 의 PascalCase(또는 케밥 커스텀) 태그. 이름 수렴으로 선언↔소비가 같은 노드에 모여
# atoms → molecules → organisms → page 체인이 플로우 엣지로 선다.
_COMPONENT_SUFFIXES = (".vue", ".svelte", ".tsx", ".jsx")
_TAG_USE = re.compile(r"(?<![\w)\]])<([A-Z][A-Za-z0-9]*|[a-z][a-z0-9]*(?:-[a-z0-9]+)+)[\s/>]")
# 프레임워크 원시 태그 — 합성 관계가 아니라 런타임 구조라 증거에서 제외한다.
_BUILTIN_TAGS = {
    "Transition", "TransitionGroup", "KeepAlive", "Teleport", "Suspense", "Component", "Fragment",
    "NuxtLink", "NuxtPage", "NuxtLayout", "NuxtImg", "NuxtPicture", "ClientOnly", "DevOnly",
    "RouterLink", "RouterView", "Head", "Html", "Body", "Title", "Meta", "Link", "Script", "Style", "NoScript",
}  # fmt: skip
# 패키지 접두 → 서비스 라벨
_SERVICE_PACKAGES = (
    ("@anthropic-ai/", "anthropic"),
    ("@aws-sdk/", "aws"),
    ("@sendgrid/", "sendgrid"),
    ("@slack/", "slack"),
    ("@supabase/", "supabase"),
    ("aws-sdk", "aws"),
    ("firebase", "firebase"),
    ("ioredis", "redis"),
    ("kafkajs", "kafka"),
    ("amqplib", "rabbitmq"),
    ("openai", "openai"),
    ("redis", "redis"),
    ("stripe", "stripe"),
    ("twilio", "twilio"),
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _span_end_line(source: str, start: int, open_char: str, close_char: str, *, limit: int = 120_000) -> int:
    """`start`(여는 문자 위치)의 짝이 닫히는 끝 줄 — 본문 스팬 근사. 실패 시 0.

    문자열('  "  `)·주석(// , /* */)을 건너뛰며 깊이를 센다. 템플릿 중첩 표현식까지는
    쫓지 않으므로(백틱 짝만 인식) 정규식 보조 추출기 수준의 근사다 — 빌더가 candidate 로 캡한다.
    """
    index, depth, quote = start, 0, ""
    end = min(len(source), start + limit)
    while index < end:
        char = source[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char == "/" and source[index + 1 : index + 2] == "/":
            index = source.find("\n", index)
            if index < 0:
                return 0
        elif char == "/" and source[index + 1 : index + 2] == "*":
            closing = source.find("*/", index + 2)
            if closing < 0:
                return 0
            index = closing + 1
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return _line_of(source, index)
        index += 1
    return 0


def _call_end_line(source: str, open_paren: int, *, limit: int = 120_000) -> int:
    return _span_end_line(source, open_paren, "(", ")", limit=limit)


def _body_end_line(source: str, search_from: int, *, window: int = 400) -> int:
    """`search_from` 뒤 첫 `{` 부터 중괄호 짝이 닫히는 끝 줄 — 함수 본문 스팬 근사. 실패 시 0."""
    brace = source.find("{", search_from, search_from + window)
    return _span_end_line(source, brace, "{", "}") if brace >= 0 else 0


def _mask_sfc(source: str) -> str:
    """SFC 의 `<script>` 블록 밖을 빈 줄로 치환한다 — 줄 번호 보존이 계약이다.

    template/style 마크업이 TS 정규식에 걸리는 오염을 막고, 스크립트 증거의 소스 위치는
    원본 파일 줄과 정확히 일치시킨다.
    """
    keep = [False] * (source.count("\n") + 1)
    for match in _SCRIPT_BLOCK.finditer(source):
        first = source.count("\n", 0, match.start(1))
        last = source.count("\n", 0, match.end(1))
        for index in range(first, last + 1):
            keep[index] = True
    lines = source.split("\n")
    return "\n".join(line if keep[index] else "" for index, line in enumerate(lines))


def _pascal(name: str) -> str:
    """케밥/스네이크 → PascalCase — 태그 표기와 파일 스템을 같은 개념 이름으로 수렴시킨다."""
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[-_]+", name) if part)


def _component_decl(path: str) -> tuple[str, str] | None:
    """components/ 트리의 컴포넌트 선언 — (이름, 아토믹 위치 detail). 비대상이면 None."""
    posix = path.replace("\\", "/")
    dot = posix.rfind(".")
    suffix = posix[dot:].lower() if dot >= 0 else ""
    if suffix not in _COMPONENT_SUFFIXES:
        return None
    parts = posix.split("/")
    dirs, stem = parts[:-1], parts[-1][: len(parts[-1]) - len(suffix)]
    if "components" not in dirs:
        return None
    anchor = dirs.index("components")
    name = _pascal(dirs[-1] if stem == "index" and anchor < len(dirs) - 1 else stem)
    if not name or not name[0].isupper():
        return None
    return name, "/".join(dirs[anchor + 1 : anchor + 3])


def _template_region(source: str) -> str:
    """SFC 의 script/style 블록을 빈 줄로 치환한다 — 템플릿 마크업만 남긴 줄 보존 뷰."""
    drop = [False] * (source.count("\n") + 1)
    for pattern in (_SCRIPT_BLOCK, _STYLE_BLOCK):
        for match in pattern.finditer(source):
            first = source.count("\n", 0, match.start(1))
            last = source.count("\n", 0, match.end(1))
            for index in range(first, last + 1):
                drop[index] = True
    lines = source.split("\n")
    return "\n".join("" if drop[index] else line for index, line in enumerate(lines))


def _clean_segment(segment: str, framework: str) -> str | None:
    """라우트 세그먼트 정규화 — 그룹/슬롯 제거, 경로 변수 `{name}` 표기. 제거 시 None."""
    if segment.startswith("(") and segment.endswith(")"):
        return None  # 라우트 그룹 — URL 에 나타나지 않는다
    if framework == "next" and segment.startswith("@"):
        return None  # 병렬 슬롯
    # 경로 변수는 Vue Router 식 `:name` 으로 통일한다 — 노드 id 슬러그에서도 살아남는 표기다.
    catch_all = re.fullmatch(r"\[\.\.\.(\w+)\]", segment)
    if catch_all:
        return ":" + catch_all.group(1)
    param = re.fullmatch(r"\[(\w+)\]", segment)
    if param:
        return ":" + param.group(1)
    if framework == "nuxt" and re.fullmatch(r"_\w+", segment):
        return ":" + segment[1:]  # Nuxt 2 표기
    return segment


def _page_route(path: str) -> tuple[str, str] | None:
    """파일 기반 라우팅 관례에서 클라이언트 라우트를 결정론적으로 유도한다. 비대상이면 None."""
    posix = path.replace("\\", "/")
    dot = posix.rfind(".")
    suffix = posix[dot:].lower() if dot >= 0 else ""
    framework = _PAGE_SUFFIXES.get(suffix)
    if framework is None:
        return None
    parts = posix.split("/")
    dirs, stem = parts[:-1], parts[-1][: len(parts[-1]) - len(suffix)]
    if suffix == ".svelte":
        if stem != "+page" or "routes" not in dirs:
            return None
        segments = dirs[dirs.index("routes") + 1 :]
    elif suffix == ".vue":
        if "pages" not in dirs:
            return None
        anchor = dirs.index("pages")
        # 아토믹 트리의 `components/**/pages` 레벨은 라우팅 디렉터리가 아니다.
        if "components" in dirs[:anchor]:
            return None
        segments = dirs[anchor + 1 :] + ([] if stem == "index" else [stem])
    elif stem == "page" and "app" in dirs:  # Next app router — page.{ts,tsx,js,jsx}
        segments = dirs[dirs.index("app") + 1 :]
    elif suffix in {".tsx", ".jsx"} and "pages" in dirs:  # Next pages router
        anchor = dirs.index("pages")
        rest = dirs[anchor + 1 :]
        if "components" in dirs[:anchor] or stem.startswith("_") or rest[:1] == ["api"] or stem == "api":
            return None
        segments = rest + ([] if stem == "index" else [stem])
    else:
        return None
    cleaned = [result for segment in segments if (result := _clean_segment(segment, framework)) is not None]
    return "/" + "/".join(cleaned), framework


def extract_tsjs(path: str, source: str) -> list[Evidence]:
    evidence: list[Evidence] = []
    if path.endswith(".prisma"):
        for match in _PRISMA_MODEL.finditer(source):
            evidence.append(Evidence("model", match.group(1), path, _line_of(source, match.start()), "confirmed"))
        return evidence

    total_lines = source.count("\n") + 1
    page = _page_route(path)
    if page is not None:
        # 페이지는 파일 본문 전체를 소유한다 — 같은 파일의 api_call 이 페이지 플로우로 귀속된다.
        evidence.append(Evidence("page", page[0], path, 1, "confirmed", page[1], scope_end=total_lines))
    decl = _component_decl(path)
    if decl is not None:
        # 컴포넌트도 파일 본문을 소유한다 — 자기 템플릿의 하위 컴포넌트 소비가 합성 플로우가 된다.
        evidence.append(Evidence("component", decl[0], path, 1, "confirmed", decl[1], scope_end=total_lines))
    markup = None
    if path.endswith(_SFC_SUFFIXES):
        markup = _template_region(source)
        source = _mask_sfc(source)
    elif path.endswith((".tsx", ".jsx")):
        markup = source
    if markup is not None:
        seen_tags: set[str] = set()
        for match in _TAG_USE.finditer(markup):
            tag = _pascal(match.group(1))
            if tag in _BUILTIN_TAGS or tag in seen_tags or (decl is not None and tag == decl[0]):
                continue
            seen_tags.add(tag)
            evidence.append(Evidence("component", tag, path, _line_of(markup, match.start()), "candidate", "use"))

    route_receivers = {match.group(1).casefold() for match in _ROUTE_BINDING.finditer(source)}
    for match in _ROUTE.finditer(source):
        receiver, method, route_path = match.group(1).casefold(), match.group(2).upper(), match.group(3)
        confidence = "confirmed" if receiver in route_receivers else "candidate"
        line = _line_of(source, match.start())
        # 인라인 핸들러 스팬 — 라우트 등록 호출의 여는 괄호부터 닫는 괄호까지
        open_paren = source.find("(", match.end(2), match.end())
        span = _call_end_line(source, open_paren) if open_paren >= 0 else 0
        evidence.append(
            Evidence(
                "route", f"{method} {route_path}", path, line, confidence, scope_end=max(span, line) if span else 0
            )
        )
    for match in _NEST_ROUTE.finditer(source):
        method, route_path = match.group(1).upper(), match.group(2) or ""
        name = f"{method} /{route_path.lstrip('/')}" if route_path else f"{method} ."
        evidence.append(Evidence("route", name, path, _line_of(source, match.start()), "confirmed", "nest"))
    api_call_lines: set[int] = set()
    for match in _API_CALL.finditer(source):
        target = _TEMPLATE_EXPR.sub("{}", match.group(1))
        confidence = "confirmed" if target.startswith(("http://", "https://")) else "candidate"
        line = _line_of(source, match.start())
        api_call_lines.add(line)
        evidence.append(Evidence("api_call", safe_url(target), path, line, confidence))
    for match in _WRAPPER_CALL.finditer(source):
        line = _line_of(source, match.start())
        if line in api_call_lines:
            continue  # 같은 줄의 fetch/axios 캡처와 이중 계상 금지
        target = _TEMPLATE_EXPR.sub("{}", match.group(3))
        confidence = "confirmed" if target.startswith(("http://", "https://")) else "candidate"
        wrapper = re.sub(r"\s+", "", match.group(1))
        evidence.append(Evidence("api_call", safe_url(target), path, line, confidence, wrapper))
    for match in _PINIA_STORE.finditer(source):
        line = _line_of(source, match.start())
        open_paren = source.find("(", match.start(), match.end())
        span = _call_end_line(source, open_paren) if open_paren >= 0 else 0
        evidence.append(
            Evidence(
                "store", match.group(1), path, line, "confirmed", "pinia", scope_end=max(span, line) if span else 0
            )
        )
    for match in _REDUX_SLICE.finditer(source):
        line = _line_of(source, match.start())
        open_paren = source.find("(", match.start(), match.end())
        span = _call_end_line(source, open_paren) if open_paren >= 0 else 0
        evidence.append(
            Evidence(
                "store", match.group(1), path, line, "confirmed", "redux", scope_end=max(span, line) if span else 0
            )
        )
    if _COMPOSABLE_DIRS & set(path.split("/")[:-1]):
        for match in _COMPOSABLE.finditer(source):
            name = match.group(1) or match.group(2)
            line = _line_of(source, match.start())
            span = _body_end_line(source, match.end())
            evidence.append(
                Evidence("composable", name, path, line, "confirmed", scope_end=max(span, line) if span else 0)
            )
    for match in _DRIZZLE_TABLE.finditer(source):
        evidence.append(
            Evidence("model", match.group(1), path, _line_of(source, match.start()), "candidate", "drizzle")
        )
    for match in _JOB.finditer(source):
        line = _line_of(source, match.start())
        open_paren = source.rfind("(", match.start(), match.end())
        # @Cron 데코레이터는 본문이 뒤따르는 메서드라 괄호 스팬이 안 잡힌다 — 콜백형만 스팬을 얻는다.
        span = _call_end_line(source, open_paren) if open_paren >= 0 and "@" not in match.group(0) else 0
        evidence.append(Evidence("job", "cron", path, line, "candidate", scope_end=max(span, line) if span else 0))
    seen_services: set[str] = set()
    for match in _IMPORT.finditer(source):
        package = match.group(1) or match.group(2) or ""
        for prefix, label in _SERVICE_PACKAGES:
            exact = package == prefix.rstrip("/")
            scoped = prefix.endswith("/") and package.startswith(prefix)
            if (exact or scoped) and label not in seen_services:
                seen_services.add(label)
                evidence.append(
                    Evidence("external_service", label, path, _line_of(source, match.start()), "confirmed", package)
                )
    return evidence
