"""TS/JS(+prisma, Vue/Svelte SFC) 증거 추출기 — 정규식 기반 보조 추출기.

정규식은 구문 증명이 아니다: 관용구가 강한 패턴(Express 라우트, Nest 데코레이터, prisma
model)만 confirmed 로 표시하고 나머지는 전부 candidate 로 남긴다. tree-sitter 승격 여지를
위해 인터페이스는 extract_python 과 동일하게 유지한다.

프론트 레인: 파일 기반 라우팅(page)·전역 상태(store)·관례 디렉터리 컴포저블(composable)·
HTTP 래퍼 호출(api_call). 파일 경로에서 결정론적으로 유도되는 page 만 confirmed 이고,
래퍼 호출은 베이스 URL 을 증명할 수 없어 candidate 로 남는다.

컴포저블·서비스·스토어는 컴포넌트와 같이 선언과 소비 양쪽을 뽑아 이름으로 수렴시킨다 —
그래야 page/component 스팬 안의 호출이 화면→로직→상태→API 플로우 엣지가 된다. 소비는
잠정 증거로 나가고, 리포 안 선언(또는 스토어 접근자 별칭)으로 정체가 증명된 것만
`resolve_fe_usage` 를 통과한다 — 이름만 보고 노드를 세우지 않는다. 소비의 근거는 종류마다
다르다: 컴포저블·스토어는 `useXxx()` 관례, 서비스는 `services/` 임포트가 증명한 심볼의 호출.
"""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlsplit

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
# 컴포저블·스토어 소비 — `useXxx()` 호출 지점. 수신자 메서드(`x.useY()`)는 합성이 아니라 제외한다.
# 정체 확정은 `resolve_fe_usage` 의 수렴이 맡는다 — 부정 목록을 두지 않는 이유는 프레임워크
# 원시 훅(useState/useRouter/useFetch…)이 리포에 선언이 없어 자동으로 탈락하기 때문이다.
_HOOK_USE = re.compile(r"(?<![\w.$])(use[A-Z]\w*)\s*\(")
_USE_DETAIL = "use"
# 서비스 모듈 — 선언은 관례 디렉터리의 네임스페이스 객체(`export const alarmService = {`)와
# 자유 함수. 소비는 이름 접미사 관례가 아니라 **임포트 경로가 증명하는 심볼**의 호출 지점이다:
# `import { alarmService } from '@/services/...'` 가 있어야 그 심볼의 호출을 서비스로 읽는다.
_SERVICE_DIRS = {"services"}
_SERVICE_OBJECT = re.compile(r"^\s*export\s+const\s+(\w+)\s*=\s*\{", re.M)
_SERVICE_FUNCTION = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.M)
_NAMED_IMPORT = re.compile(r"\bimport\s+(type\s+)?\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
# 네임스페이스 객체가 서비스라는 근거 — 호출 가능한 멤버가 하나는 있어야 설정 상수와 갈린다.
# 메서드 축약(`list(p): Promise<X> {`)·화살표·function 값을 다 담으려면 TS 타입 표기까지
# 쫓아야 해서, 시그니처 모양을 정밀하게 그리는 대신 "본문에 호출 형태가 있다"로 넓게 잡는다.
_CALLABLE_MEMBER = re.compile(r"\b\w+\s*\(|=>")
# Pinia 접근자 별칭 — 소비는 `useAuthStore()` 로 나타나지만 노드 이름은 `defineStore` 의 id 다.
_STORE_ALIAS = re.compile(r"\bconst\s+(use[A-Z]\w*)\s*=\s*defineStore\s*\(\s*['\"`]([\w./-]+)['\"`]")
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
# API 베이스 접두 — base 성격의 이름에 묶인 체크인 리터럴만 증거다 (계산식·환경변수 제외).
# `?? '/api'` / `|| '/api'` 폴백 리터럴은 체크인된 기본값이라 Spring 의 annotation default 와
# 같은 지위로 인정한다. 값은 `/경로` 또는 절대 URL(경로부만 취함)이어야 한다.
# 폴백 청크는 식별자·점·공백만 허용한다 — `x = create({ baseURL: … ??` 처럼 호출식 너머의
# 리터럴을 앞쪽 식별자가 가로채지 못하게 막고, 가장 가까운 이름에 귀속시킨다.
_API_BASE_DECL = re.compile(
    r"\b([A-Za-z_$][\w$]*)\s*[:=]\s*(?:[\w$.\s]{0,80}?(?:\?\?|\|\|)\s*)?(['\"`])((?:/|https?://)[^'\"`\n]{0,200})\2"
)
_API_BASE_NAMES = {"baseurl", "apibase", "apibaseurl", "apibasepath", "apiprefix", "apiroot"}
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
    """`start`(여는 문자 위치)의 짝이 닫히는 끝 줄 — 본문 스팬 근사. 실패 시 0."""
    end = _span_end_offset(source, start, open_char, close_char, limit=limit)
    return _line_of(source, end) if end >= 0 else 0


def _span_end_offset(source: str, start: int, open_char: str, close_char: str, *, limit: int = 120_000) -> int:
    """`start` 의 짝이 닫히는 오프셋 — 실패 시 -1.

    문자열('  "  `)·주석(// , /* */)을 건너뛰며 깊이를 센다. 템플릿 중첩 표현식까지는
    쫓지 않으므로(백틱 짝만 인식) 정규식 보조 추출기 수준의 근사다 — 빌더가 candidate 로 캡한다.
    """
    if start < 0:
        return -1
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
                return -1
        elif char == "/" and source[index + 1 : index + 2] == "*":
            closing = source.find("*/", index + 2)
            if closing < 0:
                return -1
            index = closing + 1
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


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


def _mask_comments(source: str) -> str:
    """주석 본문을 공백으로 지운다 — 줄 번호·오프셋 보존이 계약이다.

    주석은 증거가 아니다(extract_java 와 같은 원칙): 산문에 적힌 `useFoo()` 나 주석 처리된
    죽은 호출이 소비 증거로 오인되는 것을 막는다. 문자열·템플릿 리터럴 안의 `//`(URL 등)는
    주석이 아니므로 리터럴을 인식하며 지나간다.
    """
    out = list(source)
    index, total, quote = 0, len(source), ""
    while index < total:
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "\"'`":
            quote = char
            index += 1
            continue
        if char == "/" and index + 1 < total:
            following = source[index + 1]
            if following == "/":
                while index < total and source[index] != "\n":
                    out[index] = " "
                    index += 1
                continue
            if following == "*":
                end = source.find("*/", index + 2)
                end = total if end < 0 else end + 2
                for cursor in range(index, end):
                    if out[cursor] != "\n":
                        out[cursor] = " "
                index = end
                continue
        index += 1
    return "".join(out)


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


def extract_api_bases(source: str) -> list[str]:
    """FE 소스의 API 베이스 접두 수집 — axios/ofetch `baseURL:` 과 `API_BASE_URL` 류 상수.

    브리지가 상대 경로 api_call 의 후보 접두로 시도한다 (노드 이름은 원문 보존).
    """
    bases: list[str] = []
    taken: set[str] = set()  # 순서는 bases 가, 중복 판정은 이쪽이 진다 — 선언이 많은 파일에서 제곱 방지
    for match in _API_BASE_DECL.finditer(source):
        name = re.sub(r"[_$]", "", match.group(1)).casefold()
        if name not in _API_BASE_NAMES:
            continue
        raw = match.group(3)
        if "${" in raw:
            continue  # 계산식 잔여 — 정체가 아니다
        path = urlsplit(raw).path if raw.startswith(("http://", "https://")) else raw
        path = "/" + path.strip("/")
        if path != "/" and path not in taken:
            bases.append(path)
            taken.add(path)
    return bases


def _imported_service_symbols(code: str) -> set[str]:
    """`services/` 모듈에서 들여온 런타임 심볼 — 소비를 이름 관례가 아니라 출처로 증명한다.

    타입 전용 임포트(`import type {...}`, 인라인 `type Foo`)는 런타임 호출이 아니라 제외한다.
    """
    symbols: set[str] = set()
    for match in _NAMED_IMPORT.finditer(code):
        if match.group(1):
            continue  # import type { … }
        module = match.group(3)
        if not any(part in _SERVICE_DIRS for part in module.split("/")):
            continue
        for raw in match.group(2).split(","):
            symbol = raw.split(" as ")[-1].strip()
            if symbol and not symbol.startswith("type "):
                symbols.add(symbol)
    return symbols


def _service_evidence(path: str, code: str) -> list[Evidence]:
    """서비스 모듈의 선언(관례 디렉터리)과 소비(임포트로 증명된 심볼의 호출 지점)."""
    evidence: list[Evidence] = []
    decl_lines: set[int] = set()
    if _SERVICE_DIRS & set(path.split("/")[:-1]):
        for match in _SERVICE_OBJECT.finditer(code):
            brace = code.find("{", match.start(1))
            closing = _span_end_offset(code, brace, "{", "}")
            # 호출 가능한 멤버가 없으면 서비스 모듈이 아니라 설정 상수다 — 주장하지 않는다.
            if closing < 0 or not _CALLABLE_MEMBER.search(code[brace : closing + 1]):
                continue
            line = _line_of(code, match.start(1))
            decl_lines.add(line)
            evidence.append(
                Evidence(
                    "service", match.group(1), path, line, "confirmed", scope_end=max(_line_of(code, closing), line)
                )
            )
        for match in _SERVICE_FUNCTION.finditer(code):
            line = _line_of(code, match.start(1))
            decl_lines.add(line)
            span = _body_end_line(code, match.end())
            evidence.append(
                Evidence("service", match.group(1), path, line, "confirmed", scope_end=max(span, line) if span else 0)
            )
    seen: set[tuple[str, int]] = set()
    for symbol in _imported_service_symbols(code):
        # 네임스페이스 멤버 호출(`alarmService.list(`)과 자유 함수 호출(`fetchAlarms(`) 둘 다.
        for match in re.finditer(rf"(?<![\w.$]){re.escape(symbol)}\s*(?:\.\s*\w+\s*)?\(", code):
            line = _line_of(code, match.start())
            if (symbol, line) in seen or line in decl_lines:
                continue
            seen.add((symbol, line))
            evidence.append(Evidence("service", symbol, path, line, "candidate", _USE_DETAIL))
    return evidence


def extract_store_aliases(source: str) -> list[tuple[str, str]]:
    """Pinia 접근자 별칭 — `const useAuthStore = defineStore('auth')` → `(useAuthStore, auth)`.

    스토어 소비 지점에는 접근자 이름만 나타나므로, 선언이 증명하는 이 짝이 없으면 소비는
    스토어 노드로 수렴하지 못한다. 같은 접근자가 리포 안에서 서로 다른 id 로 갈리면
    호출자가 해석을 포기한다 — 모호성은 지어내지 않는다.
    """
    return [(match.group(1), match.group(2)) for match in _STORE_ALIAS.finditer(_mask_comments(source))]


def resolve_fe_usage(collected: list[Evidence], store_aliases: dict[str, str]) -> list[Evidence]:
    """`useXxx()` 잠정 소비 증거의 정체를 리포 안 선언으로만 확정한다.

    통과 조건은 둘뿐이다: 접근자 별칭표가 증명하는 스토어이거나, 리포 안에 선언된
    컴포저블이거나. 어느 쪽도 아닌 이름(프레임워크 원시 훅, 외부 패키지 훅)은 선언을
    소유한 소스가 없어 정체를 증명할 수 없으므로 버린다 — 이름만 보고 노드를 세우지 않는다.

    서비스 소비도 같은 수렴을 거친다: 임포트가 출처를 증명해도 선언을 못 찾으면(리포 밖
    패키지의 `services/` 경로 등) 노드를 세우지 않는다.
    """
    declared: dict[str, set[str]] = {}
    for item in collected:
        if item.kind in ("composable", "service") and item.detail != _USE_DETAIL:
            declared.setdefault(item.kind, set()).add(item.name)
    resolved: list[Evidence] = []
    for item in collected:
        if item.kind not in ("composable", "service") or item.detail != _USE_DETAIL:
            resolved.append(item)
            continue
        if item.kind == "service":
            if item.name in declared.get("service", ()):
                resolved.append(item)
            continue
        store_id = store_aliases.get(item.name)
        if store_id is not None:
            resolved.append(replace(item, kind="store", name=store_id))
        elif item.name in declared.get("composable", ()):
            resolved.append(item)
    return resolved


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
    # 컴포저블·스토어 레인은 주석을 증거로 삼지 않는다 — 죽은 선언·산문 속 호출을 배제한다.
    code = _mask_comments(source)
    for match in _PINIA_STORE.finditer(code):
        line = _line_of(code, match.start())
        open_paren = code.find("(", match.start(), match.end())
        span = _call_end_line(code, open_paren) if open_paren >= 0 else 0
        evidence.append(
            Evidence(
                "store", match.group(1), path, line, "confirmed", "pinia", scope_end=max(span, line) if span else 0
            )
        )
    for match in _REDUX_SLICE.finditer(code):
        line = _line_of(code, match.start())
        open_paren = code.find("(", match.start(), match.end())
        span = _call_end_line(code, open_paren) if open_paren >= 0 else 0
        evidence.append(
            Evidence(
                "store", match.group(1), path, line, "confirmed", "redux", scope_end=max(span, line) if span else 0
            )
        )
    # 선언 줄 기록은 디렉터리와 무관하다 — 관례 밖 선언도 자기 이름의 소비가 아니다.
    # 선언으로 *주장*하는 것만 관례 디렉터리로 제한한다.
    decl_lines: set[int] = set()
    in_convention = bool(_COMPOSABLE_DIRS & set(path.split("/")[:-1]))
    for match in _COMPOSABLE.finditer(code):
        # `^\s*` 는 앞선 빈 줄의 개행까지 삼킨다 — 정체의 줄은 이름 토큰이 있는 줄이다.
        name_start = match.start(1) if match.group(1) else match.start(2)
        line = _line_of(code, name_start)
        decl_lines.add(line)
        if not in_convention:
            continue
        span = _body_end_line(code, match.end())
        evidence.append(
            Evidence(
                "composable",
                match.group(1) or match.group(2),
                path,
                line,
                "confirmed",
                scope_end=max(span, line) if span else 0,
            )
        )
    # 소비 증거는 잠정이다 — 리포 안 선언으로 수렴하지 못하면 `resolve_fe_usage` 가 버린다.
    # 호출 지점을 줄 단위로 남긴다: 한 파일의 선언자가 여럿이면 각자의 본문 스팬이 자기 몫의
    # 호출을 가져가야 플로우 귀속이 맞는다 (이름으로 접으면 첫 선언자만 엣지를 얻는다).
    seen_hooks: set[tuple[str, int]] = set()
    for match in _HOOK_USE.finditer(code):
        name = match.group(1)
        line = _line_of(code, match.start())
        if (name, line) in seen_hooks or line in decl_lines:
            continue  # 선언 줄의 자기 이름은 소비가 아니다
        seen_hooks.add((name, line))
        evidence.append(Evidence("composable", name, path, line, "candidate", _USE_DETAIL))
    evidence.extend(_service_evidence(path, code))
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
