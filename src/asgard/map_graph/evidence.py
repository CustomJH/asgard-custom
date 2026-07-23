"""증거 모델 — 관계 그래프의 최소 단위.

모든 증거는 소스 위치(file, line)를 갖는다. 위치 없는 주장은 증거가 아니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

EVIDENCE_KINDS = (
    "route",  # HTTP/웹 엔드포인트
    "command",  # CLI 커맨드 표면
    "model",  # 데이터 모델 (ORM/스키마/검증 모델)
    "db_access",  # 데이터베이스 접근 지점
    "api_call",  # 외부 HTTP 호출
    "event",  # 이벤트 발행/구독
    "job",  # 백그라운드 잡/스케줄
    "external_service",  # 외부 SaaS/SDK 의존
)
CONFIDENCE = ("confirmed", "candidate")
_ID_SAFE = re.compile(r"[^\w./:@-]+")


def safe_url(value: str) -> str:
    """그래프 프로젝션에 credential/query/fragment 를 복제하지 않는 URL 표기."""
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

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence kind: {self.kind}")
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"unknown confidence: {self.confidence}")
        if self.scope_end and self.scope_end < self.line:
            raise ValueError(f"scope_end precedes line: {self.scope_end} < {self.line}")

    @property
    def node_id(self) -> str:
        """결정론 노드 id — 같은 개념은 파일이 달라도 같은 노드로 수렴한다."""
        slug = _ID_SAFE.sub("_", self.name.strip())[:120]
        return f"{self.kind}:{slug}"
