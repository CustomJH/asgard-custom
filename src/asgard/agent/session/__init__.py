"""AgentSession — 단일 컨텍스트 tool use 루프.

세션 = (system, tools, messages) 하나. 서브에이전트(역할·딜리버리)는 새 AgentSession —
child context라 프로세스 스폰 없이 중첩된다 (중첩 디스패치의 구조적 기반).

트랜스포트 5종 (루프·툴 실행은 공유, API 호출·파싱만 분기):
  anthropic     — Messages API (스키마리스 bash/editor, content 블록)
  openai_compat — chat.completions (function 툴, reasoning_content 스트리밍 — nvidia NIM 등)
  openai_responses — 공식 OpenAI Responses API (function tool loop).
  claude_cli    — 로컬 claude CLI(Claude Code)를 Agent SDK로 구동 (claude_native.py).
                  예외적으로 내부 루프는 Claude Code 소유 — 커스텀 툴은 in-process MCP로
                  이쪽 핸들러 실행, 커맨드/쓰기/토큰은 이벤트 관찰로 집계 (계약 유지).
  codex_responses — Asgard-owned ChatGPT OAuth로 Codex Responses API를 직접 호출.
루프를 Asgard가 소유하는 게 핵심 — strands/langchain은 루프를 가져가서 Trinity 강제화를 없앤다.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.agent.session` 하나만
보면 되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).

**이름을 갈아 끼우려면 정의한 모듈에 꽂아라.** 파사드의 이름을 바꿔도 정의한 모듈 안의
호출자는 자기 모듈에서 찾으므로 바뀐 것을 못 본다. `make_client` 만은 부르는 쪽이 전부 이
파사드에서 호출 시점에 임포트하므로 여기 꽂는 것이 맞다.
"""

from __future__ import annotations

# 분해 전 `session` 이 들고 있던 이름 — 이 파사드 안에서는 안 쓰지만 부르는 쪽이 이 이름으로
# 닿을 수 있어 그대로 남긴다 (표준 라이브러리 모듈까지).
import hashlib  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import subprocess  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import uuid  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import Callable  # noqa: F401

from ...io_journal import call_returned, call_started  # noqa: F401
from ...memory.fence import FenceScrubber  # noqa: F401
from ...memory.fence import scrub as _fence_scrub  # noqa: F401
from ...providers import ResolvedProvider  # noqa: F401
from ..tool_kernel import ToolContext, build_session_registry, execute_tool, to_openai_tool  # noqa: F401
from .client import make_client
from .core import AgentSession
from .types import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _FALLBACK_CONTEXT_WINDOW,
    ProviderRetriesExhausted,
    SessionResult,
    TurnCancelled,
    _Call,
)
from .wire import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _codex_replay_item,
    _invalid_encrypted_content,
    _responses_create,
    _to_openai_tool,
    _to_responses_tool,
)

__all__ = [
    "AgentSession",
    "ProviderRetriesExhausted",
    "SessionResult",
    "TurnCancelled",
    "make_client",
]
