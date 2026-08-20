"""증거 모델 — 관계 그래프의 최소 단위.

모든 증거는 소스 위치(file, line)를 갖는다. 위치 없는 주장은 증거가 아니다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

EVIDENCE_KINDS: tuple[str, ...] = (
    "route",  # HTTP/웹 엔드포인트
    "page",  # 프론트 클라이언트 라우트 (파일 기반 라우팅)
    "component",  # UI 컴포넌트 — 선언(components/ 트리)과 템플릿 태그 소비가 이름으로 수렴
    "store",  # 프론트 전역 상태 (Pinia/Redux slice)
    "composable",  # 프론트 재사용 로직 (composables/hooks 관례 디렉터리)
    "service",  # 프론트 서비스 모듈 (services 관례 디렉터리) — 외부 SaaS는 external_service 다
    "command",  # CLI 커맨드 표면
    "model",  # 데이터 모델 (ORM/스키마/검증 모델)
    "db_access",  # 데이터베이스 접근 지점
    "api_call",  # 외부 HTTP 호출
    "event",  # 이벤트 발행/구독
    "job",  # 백그라운드 잡/스케줄
    "external_service",  # 외부 SaaS/SDK 의존
)
CONFIDENCE = ("confirmed", "candidate")
# 파일은 증거가 아니라 증거가 나온 위치다 — EVIDENCE_KINDS 에 없지만 그래프에는 노드로 들어간다.
FILE_KIND = "file"
# 그리는 순서 — 아키텍처 흐름(화면 → 로직 → 경계 → 저장소). 이 표는 순서만 정하고 집합은
# 정하지 않는다: 여기 이름이 없는 종류는 사라지지 않고 뒤에 이름 순으로 붙는다. 화면이 그릴
# 종류를 손으로 적어 두면 EVIDENCE_KINDS 에 하나 늘 때마다 그 하나가 조용히 안 보인다.
_DISPLAY_ORDER = (
    "route",
    "page",
    "component",
    "store",
    "composable",
    "service",
    "command",
    "model",
    "db_access",
    "api_call",
    "event",
    "job",
    "external_service",
    FILE_KIND,
)


def node_kinds() -> tuple[str, ...]:
    """그래프 노드 종류 전부(증거 종류 + 파일), 화면 표시 순서대로."""
    rank = {name: index for index, name in enumerate(_DISPLAY_ORDER)}
    known = [*EVIDENCE_KINDS, FILE_KIND]
    return tuple(sorted(known, key=lambda kind: (rank.get(kind, len(rank)), kind)))


_ID_SAFE = re.compile(r"[^\w./:@-]+")
_MAX_SUMMARY = 120


def safe_summary(value: str) -> str:
    """한 줄 역할 표기 — 제어문자 제거, 한 줄로 접기, 길이 상한.

    이 값은 소스에서 와서 주입면까지 간다. 여러 줄이면 카탈로그의 `- x — y` 문법이 깨지고,
    제어문자는 경계 표식을 흉내낼 수 있다. 백틱은 홑따옴표로 낮춘다.
    """
    folded = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value)
    return " ".join(folded.replace("`", "'").split())[:_MAX_SUMMARY].strip()


def safe_url(value: str) -> str:
    """그래프 프로젝션에 credential/query/fragment를 복제하지 않는 URL 표기."""
    try:
        parsed = urlsplit(value)
        hostname = f"[{parsed.hostname}]" if parsed.hostname and ":" in parsed.hostname else parsed.hostname
        host = hostname + (f":{parsed.port}" if parsed.port else "") if hostname else ""
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"} or not host:
        return value
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


@dataclass(frozen=True)
class Evidence:
    kind: str
    name: str  # 사람이 읽는 식별자 — "GET /users", "User", "stripe"
    file: str  # repo 상대 posix 경로
    line: int
    confidence: str = "confirmed"
    detail: str = ""  # 부가 맥락 — base class, URL, broker 등
    # 선언자 본문 끝 줄 — 라우트/커맨드/잡/리스너처럼 본문을 소유하는 증거만 0 초과.
    # 그래프 빌더가 [line, scope_end] 포함 관계로 개념→개념 플로우 엣지를 만든다.
    scope_end: int = 0
    # 선언이 스스로 밝힌 한 줄 역할 — `help=`/`summary=`/독스트링 첫 줄만이다.
    # 이름을 풀어써 지어내지 않는다. 없으면 빈 값으로 남기고, 카탈로그는 빈 값을 건너뛴다.
    summary: str = ""
    # 역할 문장을 상수 표에 위임한 선언의 열쇠 — `help=t("hc_tk_board")` 의 `hc_tk_board`.
    # 파일 하나만 읽어서는 그 열쇠가 무슨 문장인지 알 수 없으므로 여기 담아 두고, 저장소 전체를
    # 훑은 뒤 `resolve_summaries`가 표에서 찾아 `summary`를 채운다. 표에 없으면 빈 채로 남는다.
    summary_key: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence kind: {self.kind}")
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"unknown confidence: {self.confidence}")
        if self.scope_end and self.scope_end < self.line:
            raise ValueError(f"scope_end precedes line: {self.scope_end} < {self.line}")
        if self.summary != safe_summary(self.summary):
            raise ValueError(f"summary is not a safe one-liner: {self.summary!r}")

    @property
    def node_id(self) -> str:
        """결정론 노드 id — 같은 개념은 파일이 달라도 같은 노드로 수렴한다."""
        slug = _ID_SAFE.sub("_", self.name.strip())[:120]
        return f"{self.kind}:{slug}"
