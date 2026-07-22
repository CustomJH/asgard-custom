"""Heimdall 오케스트레이터 — 네이티브 Trinity 순환 (패키지 파사드).

구조:
  Odin 요청 → [분류] → DIRECT (write 없음, 무세금)
                    → Trinity: 퀘스트 로그 open → 매 턴 전이 함수(quest-log next, 결정론) →
                      역할 세션(child context) → 퀘스트 로그 기록(하니스가 결정론 수행) →
                      Verifier verdict 툴 → 게이트(verifier-gate, 루프 종료 지점) → close

Claude Code 모드 B 와의 차이: 거기선 모델이 quest-log CLI 를 스스로 실행하지만, 네이티브에선
**하니스가 퀘스트 로그을 기록**한다 — 프로토콜 준수가 모델 순응이 아니라 코드 경로다. 훅 자체는
subprocess 배포 형태로 재사용 (36/36 테스트된 계약, 재구현 금지). 상태는 같은 .asgard/ —
Claude Code/Codex/Cursor 세션과 퀘스트 로그을 이어 쓴다 (크로스툴 연속성).

중첩 디스패치: Worker 에 dispatch 툴 — 딜리버리 전문가(child context, depth 1)에
위임하고 배정 근거를 delegate 이벤트로 퀘스트 로그에 남긴다. 딜리버리는 재위임 불가 (툴 미제공).

모듈 구성 (구 단일 모듈 heimdall.py 의 분해 — 공개 표면은 여기서 그대로 재수출):
  roles    — 역할 프롬프트 본문·모델 티어·스킬 리졸버·노트 주입
  classify — 요청 분류·API 오류·게이트 시그니처 (순수 판정)
  planning — 배정 단위 파싱·wave 위상 정렬·재개 스냅샷
  toolspec — 네이티브 세션 툴 스키마 (순수 데이터)
  journal  — .asgard/state 텔레메트리·write sentinel IO
  dispatch — 딜리버리 위임·편대 fan-out (DeliveryDispatch 협력자)
  waves    — 배정 단위 wave 실행·티켓 lease (WaveRunner 협력자)
  trinity  — 퀘스트 순환 상태기계 (TrinityRun)
  core     — Heimdall 오케스트레이터 (세션·모델·라우팅)
"""

from ..session import gate, ql
from .classify import classify_api_error, classify_heuristic, memory_write_intent
from .core import Heimdall, SessionLike
from .dispatch import DeliveryDispatch, _derived_from_pass, _freyja_final_writes, _safe_candidates
from .journal import _log_classify, _record_writes
from .planning import _parse_units, _plan_waves, _resume_snapshot
from .roles import (
    _DELIVERY,
    _DELIVERY_READONLY,
    _DELIVERY_TIERS,
    LAGOM_VERIFIER_NOTE,
    NATIVE_NOTE,
    _identity,
    _mimir_note,
    _role_body,
    _role_prompt,
    _skill_support,
)
from .toolspec import (
    DISPATCH_TOOL,
    FREYJA_SQUAD_TOOL,
    FREYJA_VERDICT_TOOL,
    THOR_SQUAD_TOOL,
    VERDICT_TOOL,
    VISUAL_VERDICT_SUBMIT_TOOL,
)
from .trinity import MAX_TRINITY_TURNS, TrinityRun
from .waves import WaveRunner

__all__ = [
    "DISPATCH_TOOL",
    "DeliveryDispatch",
    "FREYJA_SQUAD_TOOL",
    "FREYJA_VERDICT_TOOL",
    "Heimdall",
    "LAGOM_VERIFIER_NOTE",
    "MAX_TRINITY_TURNS",
    "NATIVE_NOTE",
    "SessionLike",
    "THOR_SQUAD_TOOL",
    "TrinityRun",
    "VERDICT_TOOL",
    "VISUAL_VERDICT_SUBMIT_TOOL",
    "WaveRunner",
    "classify_api_error",
    "classify_heuristic",
    "memory_write_intent",
    "gate",
    "ql",
    "_DELIVERY",
    "_DELIVERY_READONLY",
    "_DELIVERY_TIERS",
    "_derived_from_pass",
    "_freyja_final_writes",
    "_identity",
    "_log_classify",
    "_mimir_note",
    "_parse_units",
    "_plan_waves",
    "_record_writes",
    "_resume_snapshot",
    "_role_body",
    "_role_prompt",
    "_safe_candidates",
    "_skill_support",
]
