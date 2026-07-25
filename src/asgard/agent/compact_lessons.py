"""압축 교훈 — 실패 사례에서 요약 지침을 스스로 다듬는 루프 (후긴 ACON 층).

ACON(ICML 2026)의 관찰: 압축기를 미세조정하는 대신, '전체 맥락이면 성공하는데 압축 맥락이면
실패하는' 사례를 분석해 **자연어 지침을 반복 개선**하는 것만으로 압축 품질이 오른다. 이 모듈은
그 루프의 로컬 구현이다 — 추가 LLM 호출 없이, 관측 가능한 신호만으로 돈다.

신호 2종 (둘 다 결정론):
  1. 구조 비평   요약 산출물 자체를 스키마 대조한다. 섹션 누락·빈 Active Task·없던 사용자
                 발화 날조·credential 잔류. 요약 직후에 즉시 판정된다.
  2. 재작업 탐지 압축 뒤 몇 턴 안에, 방출된 구간에 이미 있던 툴 호출을 그대로 다시 하면
                 압축이 무언가를 떨어뜨렸다는 뜻이다. "이미 한 일을 또 했다"는 압축 손실의
                 가장 정직한 관측 신호다.

각 신호는 한 줄짜리 지침으로 환원돼 다음 요약 프롬프트에 붙는다. 저장소는 프로젝트별 파일이라
교훈이 세션을 넘어 누적된다. 상한이 있고(_MAX), 오래되고 덜 맞은 지침부터 밀려난다 —
지침 목록 자체가 컨텍스트 압력이 되면 본말전도다.

권위는 여기 없다. 지침은 프롬프트 힌트일 뿐 게이트가 아니고, 파일을 지우면 기본값으로 돌아간다.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time

_MAX = 8  # 프롬프트에 붙일 지침 상한 — 이 목록이 요약 예산을 먹으면 안 된다
# 지침 1줄 상한 — 안전망일 뿐 상시 절단선이 아니다. 문장 중간에서 잘린 지침은 없는 것보다
# 나쁘므로(_LESSONS 는 이 모듈이 직접 쓴다) 가장 긴 항목보다 넉넉해야 한다. 테스트가 지킨다.
_MAX_CHARS = 400
_STORE = "compress-lessons.json"

# 요약 산출물이 반드시 갖춰야 할 머리글 — build_prompt 의 _SCHEMA 와 짝을 이룬다.
REQUIRED_SECTIONS = (
    "## Active Task",
    "## Goal",
    "## Completed Actions",
    "## Active State",
    "## Relevant Files",
)

# 없던 사용자 발화를 지어내는 실패 — 사용자 턴이 없는 세션(서브에이전트·자동 실행)에서
# "User asked:" 가 나오면 요약기가 도구 출력을 사람 발화로 승격시킨 것이다.
_USER_ATTRIBUTION = re.compile(r"\bUser\s+(?:asked|requested|said)\s*:", re.IGNORECASE)

_LESSONS: dict[str, str] = {
    "missing_sections": (
        "Emit every section heading from the template verbatim, even when a section is empty "
        "(write 'None.' under it). A previous handoff dropped headings and the next instance "
        "could not tell absence from omission."
    ),
    "empty_active_task": (
        "'## Active Task' must never be blank. Quote the user's latest unfulfilled input verbatim, "
        "or write exactly 'None.' — a previous handoff left it empty and work stalled."
    ),
    "invented_user": (
        "This session has no user-authored turns. Never write 'User asked:' or attribute anything "
        "to a user — describe agent and tool work as completed actions only."
    ),
    "credential_leak": (
        "Never copy credential-like strings into the handoff. Write [REDACTED] — a previous handoff "
        "carried a secret through compaction."
    ),
    "redone_work": (
        "Preserve concrete outputs, not just the fact that a step happened: exact file paths with the "
        "finding, full command lines with their result, and error strings verbatim. After a previous "
        "handoff the next instance re-ran work it had already completed because only the action was "
        "recorded, not its outcome."
    ),
    "truncated_summary": (
        "Keep the handoff inside the token budget. A previous handoff was cut off mid-section and the "
        "trailing sections were lost — prefer terse complete sections over verbose partial ones."
    ),
}


def _path(root: str) -> str:
    from ..settings import state_path

    return state_path(root, _STORE)


def load(root: str) -> dict:
    """{key: {"hits": n, "ts": float}} — 파일 부재·손상은 빈 dict."""
    try:
        with open(_path(root), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(root: str, data: dict) -> None:
    try:
        from ..settings import ensure_state_dir

        ensure_state_dir(root)
        path = _path(root)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(Exception):
            os.remove(_path(root) + ".tmp")


def record(root: str, keys: list[str]) -> None:
    """관측된 실패 키를 적립한다. 미지 키는 무시 — 지침 본문은 이 모듈이 소유한다."""
    keys = [k for k in keys if k in _LESSONS]
    if not keys:
        return
    data = load(root)
    now = time.time()
    for key in keys:
        entry = data.get(key)
        hits = int(entry.get("hits", 0)) if isinstance(entry, dict) else 0
        data[key] = {"hits": hits + 1, "ts": now}
    if len(data) > _MAX:
        # 덜 맞고 오래된 것부터 밀어낸다 — 반복되는 실패가 살아남는다.
        ordered = sorted(data.items(), key=lambda kv: (kv[1].get("hits", 0), kv[1].get("ts", 0.0)), reverse=True)
        data = dict(ordered[:_MAX])
    _save(root, data)


def guidelines(root: str) -> list[str]:
    """적립된 실패에서 유도된 지침 — 많이 맞은 순. 없으면 빈 목록(기본 프롬프트 그대로)."""
    data = load(root)
    ordered = sorted(data.items(), key=lambda kv: (-int(kv[1].get("hits", 0) or 0), kv[0]))
    return [_LESSONS[key][:_MAX_CHARS] for key, _ in ordered if key in _LESSONS][:_MAX]


def guideline_block(root: str) -> str:
    """요약 프롬프트에 붙일 블록. 교훈이 없으면 빈 문자열 (프롬프트 바이트 불변)."""
    lines = guidelines(root)
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return (
        "\n\nLEARNED GUIDELINES — these come from handoffs that measurably failed in this project. "
        f"They override the generic instructions above where they conflict:\n{body}"
    )


# ── 신호 1: 구조 비평 ───────────────────────────────────────────────────────


def critique(summary: str, *, has_user_turn: bool, budget_tokens: int) -> list[str]:
    """요약 산출물의 결함 키 목록 (0-LLM). 빈 목록 = 흠 없음."""
    found: list[str] = []
    text = summary or ""
    if any(section not in text for section in REQUIRED_SECTIONS):
        found.append("missing_sections")
    match = re.search(r"(?ms)^##\s*Active Task\s*\n(.*?)(?=^##\s|\Z)", text)
    if not match or not match.group(1).strip():
        found.append("empty_active_task")
    if not has_user_turn and _USER_ATTRIBUTION.search(text):
        found.append("invented_user")
    try:
        from ..memory.policy import redact_secrets

        if redact_secrets(text) != text:
            found.append("credential_leak")
    except Exception:
        pass
    # 예산 한계에 바짝 붙은 채 마지막 섹션이 없으면 출력이 잘린 것이다.
    if budget_tokens and len(text) // 4 >= budget_tokens * 0.95 and REQUIRED_SECTIONS[-1] not in text:
        found.append("truncated_summary")
    return found


# ── 신호 2: 재작업 탐지 ────────────────────────────────────────────────────


def _call_key(name: str, args: dict) -> str:
    """툴 호출의 동일성 좌표 — 이름 + 가장 식별력 있는 인자 1개."""
    for field in ("file_path", "path", "command", "notebook_path", "url", "query"):
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            normalized = re.sub(r"\s+", " ", value.strip())[:160]
            return f"{name}:{normalized}"
    return name


def call_keys(messages: list) -> set[str]:
    """메시지 목록에 담긴 툴 호출 좌표 집합 — 방출 구간과 이후 구간 대조용."""
    keys: set[str] = set()
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                keys.add(_call_key(str(block.get("name") or ""), block.get("input") or {}))
            elif getattr(block, "type", "") == "tool_use":
                raw = getattr(block, "input", None)
                keys.add(_call_key(str(getattr(block, "name", "")), raw if isinstance(raw, dict) else {}))
        calls = msg.get("tool_calls")
        for call in calls if isinstance(calls, list) else []:
            fn = call.get("function") if isinstance(call, dict) else None
            if isinstance(fn, dict):
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except TypeError, ValueError:
                    args = {}
                keys.add(_call_key(str(fn.get("name") or ""), args if isinstance(args, dict) else {}))
    return keys


class RedoWatch:
    """압축 직후 몇 턴 동안 '이미 했던 호출'의 재발을 지켜본다.

    방출 구간의 호출 좌표를 들고 있다가 이후 턴에서 같은 좌표가 나오면 재작업으로 본다.
    창을 넘기면 스스로 꺼진다 — 압축과 무관한 정상적 재읽기까지 실패로 세면 지침이 오염된다."""

    def __init__(self, evicted_keys: set[str], window: int = 3):
        self.keys = set(evicted_keys)
        self.remaining = window if evicted_keys else 0

    @property
    def active(self) -> bool:
        return self.remaining > 0 and bool(self.keys)

    def observe(self, messages: list) -> bool:
        """이번 턴에서 재작업이 관측됐는가. 창 소진 시 항상 False."""
        if not self.active:
            return False
        self.remaining -= 1
        hit = bool(self.keys & call_keys(messages))
        if hit:
            self.remaining = 0  # 한 번 잡으면 충분하다 — 같은 압축을 반복 청구하지 않는다
        return hit
