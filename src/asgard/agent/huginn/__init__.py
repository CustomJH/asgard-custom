"""후긴 — 컨텍스트 압축 엔진 (무닌=회상의 짝, 현재 사고를 다듬는 쪽).

압축은 비용 절감이 목적이 아니다. 길이 자체가 정확도를 깎기 때문에(context rot) 산만함을
제거하는 게 본령이고, 토큰 절감은 부산물이다. 그래서 이 층의 실패 모드는 "덜 줄인 것"이 아니라
"살려야 할 걸 태운 것"이다 — 요약 실패 시 원본 보존이 기본 동작이다.

3단 사다리 (아래로 갈수록 비싸다 — 위 단이 충분하면 아래는 안 간다):
  T0 위생   중복 툴 출력 접기·이미지 라벨화                      LLM 무호출
  T1 프룬   tail 토큰 예산 밖 tool_result 본문 비우기             LLM 무호출
  T2 요약   head/tail 보호 + 중간 구간 구조화 인수인계            LLM 1회

조정 표면 — asgard-setting-{project,global}.json의 `compress` 섹션 (프로젝트가 글로벌을 덮는다):
  mode                off | prune | full          기본 full (off = 무개입, prune = T0+T1만)
  prune_at            0.80   프룬 발동 비율 (컨텍스트 창 대비)
  summary_at          0.90   요약 발동 비율 — prune_at보다 낮게 적으면 prune_at으로 올라간다
  protect_first_n     2      머리 보호 메시지 수 (최초 요청·첫 응답 = 과제 정의)
  tail_tokens         20000  꼬리 보호 토큰 예산 — 창의 1/4로 자동 상한
  min_recovery_tokens 4000   이만큼 못 걷으면 무개입 (캐시 재작성 비용 게이트)
  summary_max_tokens  4000   요약 출력 상한

발동은 단계형이다: 프룬 80% / 요약 90% (config [compress]로 조정). T0은 T1과 같이 탄다 —
프롬프트 캐시는 프리픽스 매치라 히스토리를 건드리는 순간 그 뒤가 전부 무효화되고, 매 턴 위생을
돌리면 캐시 재작성 비용이 절감분을 먹는다. 그래서 히스토리 변형은 임계 교차 시점에만 일어난다.
같은 이유로 최소 회수 게이트가 있다 — 회수량이 캐시 재작성 값어치에 못 미치면 아예 안 건드린다.

권위는 여기 없다. 잘려나간 구간의 원문은 turns.jsonl과 에피소드 인덱스가 이미 들고 있고,
게이트 증거·퀘스트 로그는 애초에 이 층을 지나지 않는다. 요약은 대화 맥락의 편의 사본일 뿐이다.

트랜스포트별 적용:
  anthropic        T0+T1+T2 — assistant content는 SDK 객체라 읽기만 하고 변형 대상에서 뺀다
  openai_compat    T0+T1+T2 — role=tool 메시지가 프룬 대상
  codex_responses  T1 — function_call_output 프룬 (stateless 재전송이라 안 걸면 무한 성장)
  openai_responses 미개입 — previous_response_id로 서버가 상태를 쥐고 truncation="auto"가 이미 건다
  claude_cli       미개입 — Claude Code가 자체 압축을 소유

모든 실패는 fail-open — 압축이 세션을 죽이지 않는다.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.agent.huginn` 하나만
보면 되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).

**이름을 갈아 끼우려면 정의한 모듈에 꽂아라.** 파사드의 이름을 바꿔도 정의한 모듈 안의
호출자는 자기 모듈에서 찾으므로 바뀐 것을 못 본다.
"""

from __future__ import annotations

# 분해 전 `huginn` 이 들고 있던 이름 — 이 파사드 안에서는 안 쓰지만 부르는 쪽이 이 이름으로
# 닿을 수 있어 그대로 남긴다 (표준 라이브러리 모듈까지).
import json  # noqa: F401
import time  # noqa: F401
from dataclasses import dataclass  # noqa: F401

from .align import _align_head_end, _align_tail_start, _is_real_user_turn  # noqa: F401
from .caller import make_caller
from .contract import _PREAMBLE, _SCHEMA, HANDOFF_ACK, HANDOFF_END, HANDOFF_PREFIX  # noqa: F401
from .engine import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _COOLDOWN_SECONDS,
    _INEFFECTIVE_LIMIT,
    _MIN_SAVINGS_PCT,
    Huginn,
    classify_failure,
)
from .handoff import _handoff_pair, _is_ack, extract_handoff, is_handoff  # noqa: F401
from .pairs import _tool_use_ids, sanitize_tool_pairs  # noqa: F401
from .policy import CompressPolicy, policy
from .prune import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _FOLDED,
    _IMAGE_LABEL,
    _PRUNED,
    _prunable_end,
    hygiene_and_prune,
    prune_codex_items,
)
from .server import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _SERVER_EDIT_TYPE,
    _SERVER_MIN_TRIGGER,
    SERVER_BETA,
    has_compaction_block,
    server_side_kwargs,
)
from .text import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _PREV_SUMMARY_MAX_CHARS,
    _SUMMARY_INPUT_MAX_CHARS,
    _SUMMARY_TURN_MAX_CHARS,
    _block_text,
    _clip,
    _json,
    _message_text,
    _redact,
    build_prompt,
    serialize_turns,
)
from .tokens import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _CHARS_PER_TOKEN,
    _IMAGE_TOKENS,
    _block_chars,
    _blocks,
    _is_image,
    _role,
    estimate_tokens,
    message_tokens,
)

__all__ = [
    "CompressPolicy",
    "HANDOFF_ACK",
    "HANDOFF_END",
    "HANDOFF_PREFIX",
    "Huginn",
    "SERVER_BETA",
    "build_prompt",
    "classify_failure",
    "estimate_tokens",
    "extract_handoff",
    "has_compaction_block",
    "hygiene_and_prune",
    "is_handoff",
    "make_caller",
    "message_tokens",
    "policy",
    "prune_codex_items",
    "sanitize_tool_pairs",
    "serialize_turns",
    "server_side_kwargs",
]
