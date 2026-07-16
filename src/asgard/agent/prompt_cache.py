"""프롬프트 캐시 브레이크포인트 주입 — anthropic 트랜스포트 전용 (system_and_3 레이아웃).

캐싱은 프리픽스 매치다: 렌더 순서 tools → system → messages, 프리픽스 어디서든 1바이트가
바뀌면 그 뒤 전부 무효. Asgard 세션은 (tools, system) 이 세션 수명 동안 동결이고 messages 만
자라는 구조라 브레이크포인트 4개(API 최대치)를 이렇게 배치한다:
  1. system 말미 1개 — tools+system 층 통째 캐시 (역할 프롬프트·identity 는 같은 역할의
     다음 세션에서도 바이트 동일 → TTL 내 세션 간 재사용).
  2. 최근 user 메시지 3개 — 증분 캐시. 직전 요청의 마커가 다음 요청의 read point 로 남고,
     20-블록 lookback 한계·동시 요청 대비 이중화가 된다 (실측 ~75% 절감).

assistant 메시지는 마킹하지 않는다 — SDK 객체(ThinkingBlock 포함)라 dict 마커를 못 얹고,
thinking 블록은 cache_control 거부 대상이다. user 메시지(초기 요청 문자열 + tool_result 목록)는
전부 우리가 만든 dict 라 안전하다.

관리 표면: lagom 도 게이트도 아니다 — 판정·프롬프트 내용을 바꾸지 않는 결정론 전송 최적화라
상시 적용이 기본값이고, 전 경로 fail-open 이다 (최소 캐시 프리픽스 1024~4096 토큰 미달은 API 가
조용히 무시, 마커 자체는 무해). 조정은 config.toml `[cache]`: enabled=false / ttl="1h".

모드 매트릭스 (전 모드 커버 — 표면만 다르다):
  anthropic     주입(cached_request) + 계측 — 이 모듈이 전담.
  claude_cli    Claude Code 가 자체 캐싱 — 주입 불필요, ResultMessage usage 의 캐시 필드 계측만
                패리티 (claude_native.py).
  openai_compat 주입은 실측 검증 조합만(openai_cache_markers_supported — OpenRouter+claude/qwen,
                DashScope+qwen: anthropic 식 마커를 존중, 실측 확인). 그 외는 미주입 —
                OpenAI 는 자동 프리픽스 캐시(마커 불요), ollama 는 로컬 KV, NIM 은 계약 부재이고
                미지 필드는 400 위험. 계측은 usage.prompt_tokens_details.cached_tokens 공통.
  모드 A/B      호스트 툴(Claude Code/Codex/Cursor)이 캐싱 소유 — 우리 몫은 스캐폴드 정적 프리픽스
                규율: 템플릿은 setup 시 1회 렌더되는 상수(타임스탬프·난수 금지)라 캐시 친화.
                tests/test_prompt_cache.py 가 결정론을 검사한다.

주의: session._prune_history 가 오래된 tool_result 를 비우면 그 지점부터 messages 층 캐시가
1회 무효화된다(재작성 비용 1회) — tools+system 층은 살아남는다. 프룬은 창 80% 도달 시에만
발동하므로 감수한다.
"""

from __future__ import annotations

import copy


def cache_settings(root: str) -> tuple[bool, str]:
    """설정 cache 섹션 해석 — (enabled, ttl). 기본 (True, "5m"), 프로젝트가 글로벌을 덮는다.
    설정 파일 = asgard-setting-{project,global}.json (settings.py — 구 config.toml 폴백 내장)."""
    from ..settings import section

    conf = section("cache", root)
    ttl = str(conf.get("ttl", "5m"))
    return bool(conf.get("enabled", True)), ("1h" if ttl == "1h" else "5m")


def _marker(ttl: str) -> dict:
    m: dict = {"type": "ephemeral"}
    if ttl == "1h":
        m["ttl"] = "1h"
    return m


def cached_request(system: str, messages: list, ttl: str = "5m") -> tuple[list, list]:
    """(system 문자열, 메시지 히스토리) → 마커 주입된 (system 블록 목록, 메시지 사본).

    원본은 불변 — 마킹 대상 user 메시지만 깊은 복사하고 나머지는 참조 공유한다
    (assistant 의 SDK 객체 deepcopy 비용·부작용 회피). API 호출 직전에만 쓰고 버린다."""
    m = _marker(ttl)
    sys_blocks = [{"type": "text", "text": system, "cache_control": dict(m)}]
    out = list(messages)
    user_idx = [i for i, msg in enumerate(out) if isinstance(msg, dict) and msg.get("role") == "user"]
    for i in user_idx[-3:]:
        msg = copy.deepcopy(out[i])
        c = msg.get("content")
        if isinstance(c, str):
            msg["content"] = [{"type": "text", "text": c, "cache_control": dict(m)}]
        elif isinstance(c, list) and c and isinstance(c[-1], dict):
            c[-1]["cache_control"] = dict(m)
        out[i] = msg
    return sys_blocks, out


def openai_cache_markers_supported(base_url: str, model: str) -> bool:
    """OpenAI-와이어 provider 중 anthropic 식 cache_control 마커를 실제로 존중하는 조합만 (실측 화이트리스트).

    화이트리스트 방식 — 마커는 표준 밖 필드라 미검증 provider 에 보내면 400 위험이 있고,
    OpenAI 자체는 자동 프리픽스 캐시라 마커가 필요 없다 (계측은 별도로 공통 동작)."""
    b, m = (base_url or "").lower(), (model or "").lower()
    if "openrouter.ai" in b:
        return "claude" in m or "qwen" in m
    if "dashscope" in b:  # Alibaba DashScope — qwen 계열이 마커를 존중
        return "qwen" in m
    return False


def cached_openai_request(sys_msgs: list, messages: list, ttl: str = "5m") -> list:
    """OpenAI-와이어 envelope 레이아웃 (system_and_3 의 비-네이티브 변형) — 전송용 사본 반환.

    system 메시지 + 최근 비-system 메시지 3개에 마커. tool 역할은 스킵(envelope 레이아웃 계약 —
    OpenAI-와이어 tool 메시지엔 마커 자리가 없다), None/빈 content 는 메시지 봉투에 마커."""
    m = _marker(ttl)
    out = list(sys_msgs) + list(messages)
    non_sys = [i for i, msg in enumerate(out) if isinstance(msg, dict) and msg.get("role") != "system"]
    for i in list(range(len(sys_msgs))) + non_sys[-3:]:
        if not isinstance(out[i], dict) or out[i].get("role") == "tool":
            continue
        msg = copy.deepcopy(out[i])
        c = msg.get("content")
        if c is None or c == "":
            msg["cache_control"] = dict(m)
        elif isinstance(c, str):
            msg["content"] = [{"type": "text", "text": c, "cache_control": dict(m)}]
        elif isinstance(c, list) and c and isinstance(c[-1], dict):
            c[-1]["cache_control"] = dict(m)
        out[i] = msg
    return out
