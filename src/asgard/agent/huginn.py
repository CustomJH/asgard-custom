"""후긴 — 컨텍스트 압축 엔진 (무닌=회상의 짝, 현재 사고를 다듬는 쪽).

압축은 비용 절감이 목적이 아니다. 길이 자체가 정확도를 깎기 때문에(context rot) 산만함을
걷어내는 게 본령이고, 토큰 절감은 부산물이다. 그래서 이 층의 실패 모드는 "덜 줄인 것"이 아니라
"살려야 할 걸 태운 것"이다 — 요약 실패 시 원본 보존이 기본 동작이다.

3단 사다리 (아래로 갈수록 비싸다 — 위 단이 충분하면 아래는 안 간다):
  T0 위생   중복 툴 출력 접기·이미지 라벨화                      LLM 무호출
  T1 프룬   tail 토큰 예산 밖 tool_result 본문 비우기             LLM 무호출
  T2 요약   head/tail 보호 + 중간 구간 구조화 인수인계            LLM 1회

조정 표면 — asgard-setting-{project,global}.json 의 `compress` 섹션 (프로젝트가 글로벌을 덮는다):
  mode                off | prune | full          기본 full (off = 무개입, prune = T0+T1 만)
  prune_at            0.80   프룬 발동 비율 (컨텍스트 창 대비)
  summary_at          0.90   요약 발동 비율 — prune_at 보다 낮게 적으면 prune_at 으로 올라간다
  protect_first_n     2      머리 보호 메시지 수 (최초 요청·첫 응답 = 과제 정의)
  tail_tokens         20000  꼬리 보호 토큰 예산 — 창의 1/4 로 자동 상한
  min_recovery_tokens 4000   이만큼 못 걷으면 무개입 (캐시 재작성 비용 게이트)
  summary_max_tokens  4000   요약 출력 상한

발동은 단계형이다: 프룬 80% / 요약 90% (config [compress] 로 조정). T0 은 T1 과 같이 탄다 —
프롬프트 캐시는 프리픽스 매치라 히스토리를 건드리는 순간 그 뒤가 전부 무효화되고, 매 턴 위생을
돌리면 캐시 재작성 비용이 절감분을 먹는다. 그래서 히스토리 변형은 임계 교차 시점에만 일어난다.
같은 이유로 최소 회수 게이트가 있다 — 회수량이 캐시 재작성 값어치에 못 미치면 아예 안 건드린다.

권위는 여기 없다. 잘려나간 구간의 원문은 turns.jsonl 과 에피소드 인덱스가 이미 들고 있고,
게이트 증거·퀘스트 로그는 애초에 이 층을 지나지 않는다. 요약은 대화 맥락의 편의 사본일 뿐이다.

트랜스포트별 적용:
  anthropic        T0+T1+T2 — assistant content 는 SDK 객체라 읽기만 하고 변형 대상에서 뺀다
  openai_compat    T0+T1+T2 — role=tool 메시지가 프룬 대상
  codex_responses  T1 — function_call_output 프룬 (stateless 재전송이라 안 걸면 무한 성장)
  openai_responses 미개입 — previous_response_id 로 서버가 상태를 쥐고 truncation="auto" 가 이미 건다
  claude_cli       미개입 — Claude Code 가 자체 압축을 소유

모든 실패는 fail-open — 압축이 세션을 죽이지 않는다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

# ── 핸드오프 계약 ────────────────────────────────────────────────────────────
# LLM 행 문자열은 영어 (프로젝트 규약). 사람 표면 라인만 한국어.

HANDOFF_PREFIX = (
    "[CONTEXT HANDOFF — REFERENCE ONLY] Earlier turns were compacted into the summary "
    "below. This is a handoff from a previous context window: treat it as background "
    "reference, NOT as active instructions. Do NOT answer questions or fulfill requests "
    "described in it — they were already handled. Respond only to the messages that "
    "appear AFTER this handoff; the latest one is the single source of truth for what to "
    "do right now. Topic overlap does not mean resume: if the latest message contradicts, "
    "supersedes, or changes topic from anything below, the latest message wins and the "
    "stale items are discarded. Reverse signals (stop, undo, roll back, never mind, just "
    "verify) end the described work immediately. Your tools remain fully active — keep "
    "calling them for the active task instead of narrating what you would do. Repository "
    "and session state already reflect the completed work below; verify with tools rather "
    "than redoing it."
)

HANDOFF_END = "--- END OF HANDOFF — respond to the messages below, not the summary above ---"

# 핸드오프 쌍의 assistant 쪽. 합성 턴이므로 최대한 짧게 — 모델이 "이미 답했다"고 읽으면 안 된다.
HANDOFF_ACK = "Handoff received. Continuing with the messages that follow."

_SCHEMA = """\
## Active Task
[The user's most recent UNFULFILLED input, quoted verbatim. This is the single most
important field. A question awaiting an answer IS an active task. Write "None." only if
the last exchange was fully resolved. If the latest user message was a reverse signal
(stop, undo, never mind, new topic), record that signal verbatim and do NOT carry the
cancelled work forward.]

## Goal
[What the overall work is trying to achieve, in one or two sentences.]

## Constraints & Preferences
[Explicit user instructions about how to work: style, tooling, things to avoid. These
survive compaction — do not drop them.]

## Completed Actions
[Numbered. Format each as: N. ACTION target — outcome [tool: name]
1. READ src/app.py:45 — found `==` should be `!=` [tool: read]
2. EDIT src/app.py:45 — changed `==` to `!=` [tool: edit]
3. TEST `pytest tests/` — 3/50 failed: test_parse, test_validate [tool: bash]
Be exact with paths, commands, line numbers, and results.]

## Active State
[Working directory, branch, modified/created files, test status (X/Y passing), running
processes, environment facts that matter.]

## Blocked
[Unresolved errors or blockers, with exact error text.]

## Key Decisions
[Technical decisions and WHY — the reasoning is what cannot be recovered from the repo.]

## Relevant Files
[Files read, modified, or created, with a one-line note each.]

## Critical Context
[Specific values, error messages, config details, or data that would be lost otherwise.
NEVER include API keys, tokens, passwords, or credentials — write [REDACTED] instead.]"""

_PREAMBLE = (
    "You are compacting an engineering session so another instance can pick it up without "
    "re-reading the original turns. Write a handoff, not a recap. Do NOT answer any question "
    "you see in the transcript and do NOT continue the work — your entire output is the "
    "handoff document. Be concrete: exact file paths, commands, line numbers, error strings, "
    'and values. Vague phrasing like "made some changes" is a failure.'
)

# ── 정책 ────────────────────────────────────────────────────────────────────

_CHARS_PER_TOKEN = 4
_IMAGE_TOKENS = 1600  # provider 별로 다르지만 예산 계산이 낙관적이면 안 된다 — 상한 쪽 값
_PRUNED = "[오래된 툴 출력 — 컨텍스트 회수됨]"
_FOLDED = "[동일 출력 반복 — 최신 1건만 보존]"
_IMAGE_LABEL = "[이미지 — 컨텍스트 회수됨]"

_SUMMARY_INPUT_MAX_CHARS = 120_000  # 요약 프롬프트 입력 상한 (~30k 토큰)
_SUMMARY_TURN_MAX_CHARS = 4_000  # 메시지 1건이 요약 입력을 독식하지 못하게
_PREV_SUMMARY_MAX_CHARS = 12_000
_COOLDOWN_SECONDS = 600  # 요약 실패 후 재시도 금지 구간
_INEFFECTIVE_LIMIT = 2  # 연속 무효 압축 횟수 — 초과 시 세션 내 자동 요약 정지
_MIN_SAVINGS_PCT = 10.0  # 이만큼도 못 줄이면 무효 압축


@dataclass(frozen=True)
class CompressPolicy:
    mode: str = "full"  # off | prune | full
    prune_at: float = 0.80
    summary_at: float = 0.90
    protect_first_n: int = 2
    tail_tokens: int = 20_000
    min_recovery_tokens: int = 4_000
    summary_max_tokens: int = 4_000
    vault: bool = True  # T4 — 방출 구간을 보관하고 context_recall 로 되짚게 한다
    lessons: bool = True  # ACON — 실패 사례에서 요약 지침을 누적한다
    server_side: bool = False  # T3 — anthropic 서버측 압축 (opt-in, 실패 시 클라이언트측 폴백)
    server_trigger_tokens: int = 0  # 0 = summary_at 비율에서 유도


def policy(root: str) -> CompressPolicy:
    """설정 [compress] 해석 — 프로젝트가 글로벌을 덮는다. 미설정은 전부 기본값."""
    try:
        from ..settings import section

        conf = section("compress", root)
    except Exception:
        conf = {}
    base = CompressPolicy()

    def _f(key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(conf.get(key, default))))
        except TypeError, ValueError:
            return default

    def _i(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(conf.get(key, default))))
        except TypeError, ValueError:
            return default

    def _b(key: str, default: bool) -> bool:
        value = conf.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "on", "yes"}
        return default

    mode = str(conf.get("mode", base.mode)).lower()
    if mode not in {"off", "prune", "full"}:
        mode = base.mode
    prune_at = _f("prune_at", base.prune_at, 0.30, 0.98)
    summary_at = _f("summary_at", base.summary_at, 0.35, 0.99)
    return CompressPolicy(
        mode=mode,
        prune_at=prune_at,
        # 요약이 프룬보다 먼저 터지면 사다리가 뒤집힌다 — 순서를 정책 층에서 강제한다.
        summary_at=max(summary_at, prune_at),
        protect_first_n=_i("protect_first_n", base.protect_first_n, 0, 20),
        tail_tokens=_i("tail_tokens", base.tail_tokens, 2_000, 200_000),
        min_recovery_tokens=_i("min_recovery_tokens", base.min_recovery_tokens, 0, 100_000),
        summary_max_tokens=_i("summary_max_tokens", base.summary_max_tokens, 512, 32_000),
        vault=_b("vault", base.vault),
        lessons=_b("lessons", base.lessons),
        server_side=_b("server_side", base.server_side),
        # API 최소치 50k — 그 아래 값은 요청이 거절되므로 정책 층에서 올린다.
        server_trigger_tokens=_i("server_trigger_tokens", base.server_trigger_tokens, 0, 1_000_000),
    )


# ── 토큰 추정 ───────────────────────────────────────────────────────────────


def _role(msg: object) -> str:
    return str(msg.get("role", "")) if isinstance(msg, dict) else ""


def _blocks(content: object) -> list:
    if isinstance(content, list):
        return content
    return [] if content is None else [content]


def _is_image(block: object) -> bool:
    kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
    return str(kind or "") == "image"


def _block_chars(block: object) -> int:
    if _is_image(block):
        return _IMAGE_TOKENS * _CHARS_PER_TOKEN
    if isinstance(block, str):
        return len(block)
    if isinstance(block, dict):
        try:
            return len(json.dumps(block, ensure_ascii=False, default=str))
        except TypeError, ValueError:
            return len(str(block))
    dump = getattr(block, "model_dump_json", None)
    if callable(dump):
        try:
            return len(dump())
        except Exception:
            pass
    return len(str(block))


def message_tokens(msg: object) -> int:
    """메시지 1건의 대략 토큰 — 전송 전 판단용이라 정확할 필요는 없고 과소계상만 아니면 된다."""
    if not isinstance(msg, dict):
        return _block_chars(msg) // _CHARS_PER_TOKEN
    chars = len(_role(msg)) + sum(_block_chars(b) for b in _blocks(msg.get("content")))
    return chars // _CHARS_PER_TOKEN + 4  # 메시지 프레이밍 오버헤드


def estimate_tokens(messages: list) -> int:
    return sum(message_tokens(m) for m in messages)


# ── 텍스트 추출 (요약 입력 직렬화) ──────────────────────────────────────────


def _block_text(block: object) -> str:
    if isinstance(block, str):
        return block
    if _is_image(block):
        return "[image]"
    if isinstance(block, dict):
        kind = str(block.get("type") or "")
        if kind == "text":
            return str(block.get("text") or "")
        if kind == "tool_result":
            body = block.get("content")
            if isinstance(body, str):
                return f"[tool result] {body}"
            return "[tool result] " + " ".join(_block_text(b) for b in _blocks(body))
        if kind == "tool_use":
            return f"[tool call] {block.get('name')} {_json(block.get('input'))}"
        return _json(block)
    kind = str(getattr(block, "type", "") or "")
    if kind == "text":
        return str(getattr(block, "text", "") or "")
    if kind == "tool_use":
        return f"[tool call] {getattr(block, 'name', '')} {_json(getattr(block, 'input', None))}"
    if kind == "thinking":
        return ""  # 사고 블록은 요약 재료가 아니다 — 결론만 남기면 된다
    return ""


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError, ValueError:
        return str(value)


def _message_text(msg: object) -> str:
    if not isinstance(msg, dict):
        return ""
    parts = [t for t in (_block_text(b) for b in _blocks(msg.get("content"))) if t]
    return " ".join(parts).strip()


def _redact(text: str) -> str:
    try:
        from ..memory.policy import redact_secrets

        return redact_secrets(text)
    except Exception:
        return text  # fail-open — 편집 불능이 압축을 막지 않는다


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    return text[:head].rstrip() + f"\n...[{len(text) - limit}자 생략]...\n" + text[-(limit - head) :].lstrip()


# ── 핸드오프 식별 ───────────────────────────────────────────────────────────


def is_handoff(msg: object) -> bool:
    """이 메시지가 이전 압축이 남긴 핸드오프인가 — 재압축이 요약을 쌓지 않게 하는 판정."""
    if not isinstance(msg, dict) or _role(msg) != "user":
        return False
    return _message_text(msg).lstrip().startswith(HANDOFF_PREFIX[:60])


def _is_ack(msg: object) -> bool:
    return isinstance(msg, dict) and _role(msg) == "assistant" and _message_text(msg).strip() == HANDOFF_ACK


def extract_handoff(messages: list) -> tuple[str | None, list]:
    """기존 핸드오프 쌍을 히스토리에서 떼어내고 (본문, 나머지) 를 준다.

    쌓기 금지가 핵심이다 — 핸드오프가 여럿 살아 있으면 낡은 지시가 계속 살아남고, 요약이
    요약을 요약하며 원문에서 멀어진다. 트랜스크립트에는 항상 최신 1건만 존재한다."""
    body: str | None = None
    out: list = []
    skip_ack = False
    for msg in messages:
        if is_handoff(msg):
            text = _message_text(msg)
            core = text.split(HANDOFF_END)[0]
            if core.lstrip().startswith(HANDOFF_PREFIX[:60]):
                core = core.lstrip()[len(HANDOFF_PREFIX) :] if core.lstrip().startswith(HANDOFF_PREFIX) else core
            body = core.strip() or body
            skip_ack = True
            continue
        if skip_ack and _is_ack(msg):
            skip_ack = False
            continue
        skip_ack = False
        out.append(msg)
    return body, out


def _handoff_pair(summary: str) -> list[dict]:
    return [
        {"role": "user", "content": f"{HANDOFF_PREFIX}\n\n{summary.strip()}\n\n{HANDOFF_END}"},
        {"role": "assistant", "content": HANDOFF_ACK},
    ]


# ── T0 위생 + T1 프룬 ───────────────────────────────────────────────────────


def _prunable_end(messages: list, tail_tokens: int, min_keep: int = 4) -> int:
    """뒤에서부터 토큰 예산을 채워 보호 경계를 찾는다 — 개수가 아니라 질량 기준.

    메시지 개수로 자르면 tool_result 하나가 20k 토큰인 경우와 한 줄짜리 경우가 같은 대접을
    받는다. 예산 기준이면 무거운 최근 출력 하나가 보호 구간을 알아서 좁힌다."""
    budget, idx = tail_tokens, len(messages)
    while idx > 0:
        budget -= message_tokens(messages[idx - 1])
        idx -= 1
        if budget <= 0:
            break
    return max(0, min(idx, len(messages) - min_keep))


def hygiene_and_prune(messages: list, *, tail_tokens: int, min_recovery_tokens: int) -> tuple[list, dict]:
    """T0+T1 — LLM 무호출 결정론 압축. (새 메시지 목록, 사건 dict) 반환.

    회수량이 min_recovery_tokens 에 못 미치면 아무것도 건드리지 않고 돌려준다: 히스토리를
    한 바이트만 바꿔도 프롬프트 캐시의 그 뒤 전부가 무효화되므로, 재작성 비용을 못 갚는
    소액 회수는 순손실이다 (OpenCode 의 PRUNE_MINIMUM 과 같은 판단)."""
    end = _prunable_end(messages, tail_tokens)
    before = estimate_tokens(messages)

    # 원본 불변 — 실제로 바꾼 메시지만 얕은 복사한다 (assistant 의 SDK 객체는 복사도 변형도 안 한다).
    out = list(messages)
    pruned = folded = 0
    seen: dict[str, int] = {}  # tool_result 본문 해시 → 마지막 등장 위치

    for i in range(end):
        msg = out[i]
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")

        if _role(msg) == "tool" and isinstance(content, str) and content != _PRUNED:
            out[i] = {**msg, "content": _PRUNED}
            pruned += 1
            continue

        if not isinstance(content, list):
            continue
        new_blocks: list = []
        changed = False
        for block in content:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue
            if _is_image(block):
                new_blocks.append({"type": "text", "text": _IMAGE_LABEL})
                changed = True
                folded += 1
                continue
            if block.get("type") == "tool_result" and block.get("content") not in (None, _PRUNED, _FOLDED):
                new_blocks.append({**block, "content": _PRUNED})
                changed = True
                pruned += 1
                continue
            new_blocks.append(block)
        if changed:
            out[i] = {**msg, "content": new_blocks}

    # 중복 접기는 보호 구간에도 의미가 있다: 같은 출력이 여러 번 실려 있으면 최신 1건 외에는
    # 정보가 0 이다. 단 보호 구간의 마지막 1건은 반드시 살린다. 프룬 창이 없어도(end==0)
    # 이 단계는 돈다 — 짧지만 무거운 반복 출력이 정확히 그 상태다.
    for i in range(end, len(out)):
        msg = out[i]
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                body = block.get("content")
                if isinstance(body, str) and len(body) > 400:
                    seen[body] = i
    if seen:
        for i in range(end, len(out)):
            msg = out[i]
            if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
                continue
            new_blocks, changed = [], False
            for block in msg["content"]:
                body = block.get("content") if isinstance(block, dict) else None
                if isinstance(body, str) and seen.get(body, -1) > i:
                    new_blocks.append({**block, "content": _FOLDED})
                    changed = True
                    folded += 1
                else:
                    new_blocks.append(block)
            if changed:
                out[i] = {**msg, "content": new_blocks}

    recovered = before - estimate_tokens(out)
    if recovered < min_recovery_tokens:
        # 회수량이 캐시 재작성 값어치에 못 미친다 — 원본 그대로 돌려준다.
        return messages, {"pruned": 0, "folded": 0, "recovered": 0, "skipped": "below_min_recovery"}
    return out, {"pruned": pruned, "folded": folded, "recovered": recovered, "skipped": ""}


def prune_codex_items(items: list, *, tail_tokens: int, min_recovery_tokens: int) -> tuple[list, int]:
    """codex_responses 전용 — function_call_output 본문 프룬. (새 목록, 회수 토큰).

    Codex 는 store=false 라 매 iteration 히스토리 전체를 재전송한다. 여기에 프룬이 없으면
    툴 출력이 무한 누적돼 컨텍스트 한도 초과 400 으로만 터진다."""

    def _item_tokens(item: object) -> int:
        return _block_chars(item) // _CHARS_PER_TOKEN + 4

    budget, cut = tail_tokens, len(items)
    while cut > 0:
        budget -= _item_tokens(items[cut - 1])
        cut -= 1
        if budget <= 0:
            break
    if cut <= 0:
        return items, 0
    before = sum(_item_tokens(i) for i in items)
    out = list(items)
    for i in range(cut):
        item = out[i]
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            if item.get("output") not in (None, _PRUNED):
                out[i] = {**item, "output": _PRUNED}
    recovered = before - sum(_item_tokens(i) for i in out)
    if recovered < min_recovery_tokens:
        return items, 0
    return out, recovered


# ── 툴 쌍 무결성 ────────────────────────────────────────────────────────────


def _tool_use_ids(msg: object) -> set[str]:
    ids: set[str] = set()
    if not isinstance(msg, dict):
        return ids
    for block in _blocks(msg.get("content")):
        if isinstance(block, dict):
            if block.get("type") == "tool_use" and block.get("id"):
                ids.add(str(block["id"]))
        elif str(getattr(block, "type", "") or "") == "tool_use" and getattr(block, "id", None):
            ids.add(str(block.id))
    calls = msg.get("tool_calls")  # openai 와이어
    for call in calls if isinstance(calls, list) else []:
        cid = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
        if cid:
            ids.add(str(cid))
    return ids


def sanitize_tool_pairs(messages: list) -> list:
    """고아 tool_result / tool 메시지를 제거한다.

    압축은 경계를 자르는 일이라 tool_use 는 앞에 남고 tool_result 만 잘려나가거나 그 반대가
    생긴다. 그대로 보내면 anthropic·openai 모두 400 이다 — 압축이 세션을 죽이는 가장 흔한 길."""
    available: set[str] = set()
    for msg in messages:
        available |= _tool_use_ids(msg)

    out: list = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if _role(msg) == "tool":
            if str(msg.get("tool_call_id") or "") in available:
                out.append(msg)
            continue
        content = msg.get("content")
        if _role(msg) == "user" and isinstance(content, list):
            kept = [
                b
                for b in content
                if not (isinstance(b, dict) and b.get("type") == "tool_result")
                or str(b.get("tool_use_id") or "") in available
            ]
            if not kept:
                continue  # tool_result 만 있던 메시지가 통째로 고아가 됐다
            if len(kept) != len(content):
                msg = {**msg, "content": kept}
        out.append(msg)

    # 반대 방향 — 결과가 사라진 tool_use 가 남았는지. assistant content 는 SDK 객체라 블록
    # 단위 수술을 하지 않는다: 짝 없는 호출이 남은 메시지는 통째로 뺀다.
    answered: set[str] = set()
    for msg in out:
        if not isinstance(msg, dict):
            continue
        if _role(msg) == "tool" and msg.get("tool_call_id"):
            answered.add(str(msg["tool_call_id"]))
        for block in _blocks(msg.get("content")):
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                answered.add(str(block["tool_use_id"]))
    final = []
    for msg in out:
        ids = _tool_use_ids(msg)
        if ids and not ids <= answered:
            continue
        final.append(msg)
    return final


# ── 경계 정렬 ───────────────────────────────────────────────────────────────


def _align_head_end(messages: list, n: int) -> int:
    """head 는 assistant 로 끝나야 한다 — 뒤에 붙는 핸드오프(user)와 역할이 겹치지 않게."""
    n = max(0, min(n, len(messages)))
    if n == 0:
        return 0
    while n < len(messages) and _role(messages[n - 1]) != "assistant":
        n += 1
    return n if n <= len(messages) and _role(messages[n - 1]) == "assistant" else 0


def _is_real_user_turn(msg: object) -> bool:
    """사람이 친 턴인가 — tool_result 만 실린 user 메시지는 전송 규약상의 껍데기다."""
    if not isinstance(msg, dict) or _role(msg) != "user":
        return False
    if is_handoff(msg):
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return any(
        isinstance(b, dict) and b.get("type") in {"text", "image"} or isinstance(b, str) for b in _blocks(content)
    )


def _align_tail_start(messages: list, start: int, floor: int) -> int:
    """tail 은 진짜 user 턴에서 시작해야 한다 — 앞에 붙는 ack(assistant)와 교대가 맞고,
    tool_result 로 시작해 고아가 되는 일도 없다. 보존 쪽(뒤로)을 먼저 찾는다."""
    for i in range(min(start, len(messages) - 1), floor - 1, -1):
        if _is_real_user_turn(messages[i]):
            return i
    for i in range(max(start, floor), len(messages)):
        if _is_real_user_turn(messages[i]):
            return i
    return -1


# ── 요약 입력 직렬화 ────────────────────────────────────────────────────────


def serialize_turns(messages: list) -> str:
    lines: list[str] = []
    for msg in messages:
        text = _message_text(msg)
        if not text:
            continue
        lines.append(f"[{_role(msg) or 'unknown'}] {_clip(_redact(text), _SUMMARY_TURN_MAX_CHARS)}")
    body = "\n\n".join(lines)
    return _clip(body, _SUMMARY_INPUT_MAX_CHARS)


def build_prompt(turns: str, previous: str | None, lessons: str = "") -> str:
    if previous:
        return (
            f"{_PREAMBLE}{lessons}\n\n"
            "You are UPDATING an existing handoff. Preserve everything still relevant, add the "
            "new completed actions to the numbered list (continue the numbering), move finished "
            "items out of Blocked, and refresh Active State and Active Task. Drop an item only "
            "when it is clearly obsolete.\n\n"
            f"EXISTING HANDOFF:\n{_clip(previous, _PREV_SUMMARY_MAX_CHARS)}\n\n"
            f"NEW TURNS TO FOLD IN:\n{turns}\n\n"
            f"Use this exact structure:\n\n{_SCHEMA}\n\n"
            "Write only the handoff body. No preamble, no prefix, no closing remarks."
        )
    return (
        f"{_PREAMBLE}{lessons}\n\n"
        f"TURNS TO COMPACT:\n{turns}\n\n"
        f"Use this exact structure:\n\n{_SCHEMA}\n\n"
        "Write only the handoff body. No preamble, no prefix, no closing remarks."
    )


# ── T3 서버측 압축 (anthropic compact-2026-01-12) ───────────────────────────

SERVER_BETA = "compact-2026-01-12"
_SERVER_EDIT_TYPE = "compact_20260112"
_SERVER_MIN_TRIGGER = 50_000  # API 최소치 — 그 아래는 요청이 거절된다


def server_side_kwargs(pol: CompressPolicy, window: int) -> dict:
    """서버측 압축 요청 필드. 미사용이면 빈 dict — 호출자는 그대로 전개하면 된다.

    요약 지시는 우리 핸드오프 계약을 그대로 넘긴다: instructions 는 기본 프롬프트를 '대체'하므로
    (보완이 아니다) 비워두면 provider 기본 요약이 우리 규율을 무시한다."""
    if not pol.server_side:
        return {}
    trigger = pol.server_trigger_tokens or int(window * pol.summary_at)
    return {
        "betas": [SERVER_BETA],
        "context_management": {
            "edits": [
                {
                    "type": _SERVER_EDIT_TYPE,
                    "trigger": {"type": "input_tokens", "value": max(_SERVER_MIN_TRIGGER, int(trigger))},
                    "instructions": f"{_PREAMBLE}\n\nUse this exact structure:\n\n{_SCHEMA}",
                }
            ]
        },
    }


def has_compaction_block(content: object) -> bool:
    """응답에 서버측 압축 블록이 들어 있는가 — 계측·표면 통지용."""
    for block in _blocks(content):
        kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
        if str(kind or "") == "compaction":
            return True
    return False


# ── 실패 분류 ───────────────────────────────────────────────────────────────


def classify_failure(exc: BaseException) -> str:
    """auth / network / other — 앞의 둘은 재시도가 답이지 중간 구간을 태울 이유가 아니다."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in {401, 403}:
        return "auth"
    name = type(exc).__name__.lower()
    text = f"{exc}".lower()
    if any(k in name for k in ("connect", "timeout", "network", "apiconnection")):
        return "network"
    if any(k in text for k in ("connection", "timed out", "timeout", "temporarily unavailable")):
        return "network"
    if any(k in text for k in ("unauthorized", "forbidden", "invalid api key", "authentication")):
        return "auth"
    return "other"


# ── 엔진 ────────────────────────────────────────────────────────────────────


class Huginn:
    """세션 1개의 압축 상태. 가드(안티스래시·쿨다운)는 여기 산다.

    call 은 (prompt, max_tokens) -> str 인 요약 호출자다. 세션이 트랜스포트를 알고 주입한다 —
    이 클래스는 와이어를 모른다 (테스트가 가짜 호출자를 꽂을 수 있는 이유)."""

    def __init__(self, root: str, window: int, pol: CompressPolicy, call=None, now=time.monotonic, session_id=""):
        self.root, self.window, self.policy, self.call, self._now = root, max(1, window), pol, call, now
        self.session_id = session_id
        self.compressions = 0
        self.prunes = 0
        self.archived = 0  # T4 — 보관소로 내려보낸 방출 행 수
        self.server_compactions = 0  # T3 — provider 가 수행한 압축 횟수
        self._ineffective = 0
        self._cooldown_until = 0.0
        self._summary_disabled = False
        self._awaiting_usage = False
        self._announced: set[str] = set()  # 차단 사유는 한 번만 알린다 — 매 턴 같은 경고는 소음이다
        self._redo = None  # ACON — 압축 직후 재작업 감시창
        self.last_event: dict = {}

    # -- 발동 판정 --------------------------------------------------------
    @property
    def prune_tokens(self) -> int:
        return int(self.window * self.policy.prune_at)

    @property
    def summary_tokens(self) -> int:
        return int(self.window * self.policy.summary_at)

    def effective_tail_tokens(self) -> int:
        """보호 tail 이 창의 1/4 을 넘으면 압축할 중간 구간이 남지 않아 매 턴 무효 압축이 돈다."""
        return max(1_000, min(self.policy.tail_tokens, self.window // 4))

    def summary_blocked(self) -> str:
        if self.policy.mode != "full":
            return "mode"
        if self.call is None:
            return "no_caller"
        if self._summary_disabled:
            return "ineffective"
        if self._now() < self._cooldown_until:
            return "cooldown"
        if self._awaiting_usage:
            return "awaiting_usage"
        return ""

    def note_usage(self, context_tokens: int) -> None:
        """실측 사용량 도착 — 압축 직후 추정치로 재발동하는 스래싱을 여기서 끊는다."""
        if context_tokens > 0:
            self._awaiting_usage = False

    # -- 본체 ------------------------------------------------------------
    def compress(self, messages: list, context_tokens: int) -> tuple[list, dict]:
        """(새 메시지 목록, 사건 dict). 사건이 비어 있으면 아무 일도 없었다는 뜻."""
        if self.policy.mode == "off" or not messages or context_tokens < self.prune_tokens:
            return messages, {}
        tail = self.effective_tail_tokens()

        out, event = hygiene_and_prune(messages, tail_tokens=tail, min_recovery_tokens=self.policy.min_recovery_tokens)
        recovered = bool(event.get("recovered"))
        if recovered:
            self.prunes += 1
            event = {**event, "tier": "prune"}
        else:
            out = messages  # 회수 0 이면 원본 객체 그대로 — 호출자가 동일성으로 무개입을 확인할 수 있다

        # 사다리의 요점 — 위 단이 임계를 걷어냈으면 아래 단은 안 간다. 실측 보고값과 프룬 후
        # 추정치 둘 다 봐야 한다: 보고값은 프룬을 반영하지 못한 직전 호출의 값이다.
        if context_tokens < self.summary_tokens or estimate_tokens(out) < self.summary_tokens:
            return self._finish(out, event if recovered else {})

        blocked = self.summary_blocked()
        if blocked:
            if blocked not in self._announced:
                self._announced.add(blocked)
                event = {**event, "blocked": blocked}
            return self._finish(out, event if recovered or event.get("blocked") else {})

        summarized, sevent = self._summarize(out, tail)
        return self._finish(summarized, {**event, **sevent})

    def _finish(self, messages: list, event: dict) -> tuple[list, dict]:
        self.last_event = event
        self._journal(event)
        return messages, event

    def _summarize(self, messages: list, tail_tokens: int) -> tuple[list, dict]:
        call = self.call
        if call is None:  # summary_blocked() 가 이미 걸렀지만 계약은 여기서도 닫는다
            return messages, {"tier": "summary", "failure": "no_caller"}
        before = estimate_tokens(messages)
        previous, working = extract_handoff(messages)

        head_end = _align_head_end(working, self.policy.protect_first_n)
        raw_tail = _prunable_end(working, tail_tokens, min_keep=2)
        tail_start = _align_tail_start(working, raw_tail, head_end)
        if tail_start < 0 or tail_start <= head_end:
            self._record_ineffective("no_summary_window")
            return messages, {"tier": "summary", "failure": "no_summary_window"}

        middle = working[head_end:tail_start]
        if not middle:
            self._record_ineffective("empty_window")
            return messages, {"tier": "summary", "failure": "empty_window"}

        turns = serialize_turns(middle)
        if not turns.strip() and not previous:
            self._record_ineffective("nothing_to_summarize")
            return messages, {"tier": "summary", "failure": "nothing_to_summarize"}

        t0 = self._now()
        try:
            body = (
                call(build_prompt(turns, previous, self._lesson_block()), self.policy.summary_max_tokens) or ""
            ).strip()
        except Exception as exc:  # noqa: BLE001 — 분류해서 전부 fail-open 처리한다
            kind = classify_failure(exc)
            # auth·network 실패로 중간 구간을 태우는 건 압축이 아니라 파손이다. 원본을 지키고 물러난다.
            self._cooldown_until = self._now() + _COOLDOWN_SECONDS
            return messages, {
                "tier": "summary",
                "failure": kind,
                "error": str(exc)[:200],
                "aborted": True,
            }
        duration_ms = int((self._now() - t0) * 1000)
        if not body:
            self._cooldown_until = self._now() + _COOLDOWN_SECONDS
            return messages, {"tier": "summary", "failure": "empty_summary", "aborted": True}

        rebuilt = sanitize_tool_pairs(working[:head_end] + _handoff_pair(_redact(body)) + working[tail_start:])
        after = estimate_tokens(rebuilt)
        savings = 100.0 * (before - after) / before if before else 0.0
        if savings < _MIN_SAVINGS_PCT:
            # 요약이 원문만큼 크다 — 캐시만 날리고 얻은 게 없다. 원본을 지키고 카운트한다.
            self._record_ineffective("low_savings")
            return messages, {
                "tier": "summary",
                "failure": "low_savings",
                "savings_pct": round(savings, 1),
                "aborted": True,
            }

        self.compressions += 1
        self._ineffective = 0
        self._awaiting_usage = True
        event = {
            "tier": "summary",
            "before_tokens": before,
            "after_tokens": after,
            "savings_pct": round(savings, 1),
            "summarized": len(middle),
            "head": head_end,
            "tail": len(working) - tail_start,
            "iterative": bool(previous),
            "duration_ms": duration_ms,
        }
        # T4 — 잘라낸 구간은 태우지 않고 보관소로 내려보낸다 (context_recall 로 되짚기).
        archived = self._archive(middle)
        if archived:
            event["archived"] = archived
        # ACON — 산출물 구조 비평 + 재작업 감시창 개시. 둘 다 결정론, 추가 LLM 호출 없음.
        self._learn(body, middle)
        return rebuilt, event

    # -- T4 보관소 --------------------------------------------------------
    def _archive(self, middle: list) -> int:
        if not self.policy.vault:
            return 0
        try:
            from .evicted import archive

            rows = [(_role(m) or "unknown", _redact(_message_text(m))) for m in middle]
            written = archive(self.root, [r for r in rows if r[1]], session_id=self.session_id)
            self.archived += written
            return written
        except Exception:
            return 0  # fail-open — 보관 실패가 압축을 되돌릴 이유는 아니다

    # -- ACON 교훈 --------------------------------------------------------
    def _lesson_block(self) -> str:
        if not self.policy.lessons:
            return ""
        try:
            from .compact_lessons import guideline_block

            return guideline_block(self.root)
        except Exception:
            return ""

    def _learn(self, body: str, middle: list) -> None:
        if not self.policy.lessons:
            return
        try:
            from .compact_lessons import RedoWatch, call_keys, critique, record

            faults = critique(
                body,
                has_user_turn=any(_is_real_user_turn(m) for m in middle),
                budget_tokens=self.policy.summary_max_tokens,
            )
            if faults:
                record(self.root, faults)
            self._redo = RedoWatch(call_keys(middle))
        except Exception:
            self._redo = None

    def observe_turn(self, messages: list) -> bool:
        """압축 직후 턴 관찰 — 방출된 호출을 그대로 다시 했으면 교훈으로 적립한다.

        '이미 한 일을 또 했다'가 압축 손실의 가장 정직한 관측 신호다. 감시창은 몇 턴 뒤
        스스로 닫힌다 — 압축과 무관한 정상 재읽기까지 세면 지침이 오염된다."""
        watch = self._redo
        if watch is None or not getattr(watch, "active", False):
            return False
        try:
            if not watch.observe(messages):
                return False
            from .compact_lessons import record

            record(self.root, ["redone_work"])
            self._journal({"tier": "lesson", "lesson": "redone_work"})
            return True
        except Exception:
            return False

    # -- T3 서버측 --------------------------------------------------------
    def server_kwargs(self) -> dict:
        """anthropic 요청에 얹을 서버측 압축 필드 — 미사용/미지원이면 빈 dict."""
        if self.policy.mode == "off":
            return {}
        try:
            return server_side_kwargs(self.policy, self.window)
        except Exception:
            return {}

    def note_server_compaction(self, content: object) -> bool:
        """응답에 compaction 블록이 있었으면 계측한다 — provider 가 우리 대신 압축한 것."""
        try:
            if not has_compaction_block(content):
                return False
        except Exception:
            return False
        self.server_compactions += 1
        self._awaiting_usage = True  # 서버측 압축 직후도 추정치 재발동을 막는다
        self._journal({"tier": "server", "server_compactions": self.server_compactions})
        return True

    def _record_ineffective(self, reason: str) -> None:
        self._ineffective += 1
        if self._ineffective >= _INEFFECTIVE_LIMIT:
            # 줄지 않는 압축을 매 턴 재시도하면 세션이 멈춘 것처럼 보인다 — 자동 요약을 끈다.
            self._summary_disabled = True

    def _journal(self, event: dict) -> None:
        if not event:
            return
        try:
            from ..io_journal import note

            note(self.root, "compact", {k: v for k, v in event.items() if v not in ("", None)})
        except Exception:
            pass  # fail-open — 계측이 실행을 인질로 잡지 않는다


# ── 요약 호출자 (트랜스포트 분기) ───────────────────────────────────────────


def make_caller(session) -> object | None:
    """세션의 provider 로 요약 1회 호출하는 호출자. 미지원 트랜스포트는 None."""
    mode = session.rp.profile.api_mode
    if mode in {"claude_cli", "openai_responses"}:
        return None  # 각각 Claude Code / 서버측 truncation 이 압축을 소유한다

    def call(prompt: str, max_tokens: int) -> str:
        from ..io_journal import call_returned, call_started

        jid = call_started(
            session.root,
            provider=session.rp.profile.name,
            model=session.rp.model,
            transport=f"{mode}:huginn",
            role=session.role,
        )
        started = time.monotonic()
        try:
            if mode == "anthropic":
                resp = session.client.messages.create(
                    model=session.rp.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            elif mode == "codex_responses":
                resp = session.client.responses.create(
                    model=session.rp.model,
                    input=prompt,
                    store=False,
                    timeout=300.0,
                )
                text = str(getattr(resp, "output_text", "") or "")
            else:
                resp = session.client.chat.completions.create(
                    model=session.rp.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = str(resp.choices[0].message.content or "")
        except Exception as exc:
            call_returned(session.root, jid, duration_ms=(time.monotonic() - started) * 1000, error=f"{exc}"[:200])
            raise
        call_returned(session.root, jid, duration_ms=(time.monotonic() - started) * 1000)
        return text

    return call
