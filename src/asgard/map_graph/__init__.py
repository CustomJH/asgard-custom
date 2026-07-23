"""관계 그래프 — 코드에서 추출한 증거 기반 프로젝트 지식 계층 (맵 Tier 1).

`asgard map` 의 심화 계층이다. 결정론 추출기(LLM 0토큰)가 라우트·모델·DB 접근·API 호출·
이벤트·잡·외부 서비스 증거를 소스 위치와 함께 수집해 관계 그래프를 만든다. 증명 못 하는
연결은 만들지 않는다 — 모든 증거는 confirmed/candidate 신뢰도를 갖고, candidate 는 절대
confirmed 로 승격 서술하지 않는다.

산출물 소유권:
- `.asgard/state/map-graph.json` — 그래프 상태 (런타임, git 미추적)
- `.asgard/map/GRAPH.md` — 카탈로그 프로젝션 (git 추적, 팀 공유, 맵 컨텍스트에 융합)
"""

from __future__ import annotations

from .bridge import RelatedRecord, related_records
from .evidence import EVIDENCE_KINDS, Evidence
from .graph import (
    EDGE_KINDS,
    GraphError,
    GraphOwnershipError,
    GraphResult,
    graph_state,
    scan_graph,
    trace,
)
from .view import build_view, write_view

__all__ = [
    "EDGE_KINDS",
    "EVIDENCE_KINDS",
    "Evidence",
    "GraphError",
    "GraphOwnershipError",
    "GraphResult",
    "RelatedRecord",
    "build_view",
    "graph_state",
    "related_records",
    "scan_graph",
    "trace",
    "write_view",
]
