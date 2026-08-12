"""T0 위생 + T1 프룬 — LLM 무호출 결정론 압축.

회수량이 캐시 재작성 값어치에 못 미치면 히스토리를 아예 안 건드린다. 프롬프트 캐시는
프리픽스 매치라, 한 바이트만 바꿔도 그 뒤 전부가 무효화되기 때문이다."""

from __future__ import annotations

from .tokens import _CHARS_PER_TOKEN, _block_chars, _is_image, _role, estimate_tokens, message_tokens

_PRUNED = "[오래된 툴 출력 — 컨텍스트 회수됨]"
_FOLDED = "[동일 출력 반복 — 최신 1건만 보존]"
_IMAGE_LABEL = "[이미지 — 컨텍스트 회수됨]"


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

    회수량이 min_recovery_tokens에 못 미치면 아무것도 건드리지 않고 돌려준다: 히스토리를
    한 바이트만 바꿔도 프롬프트 캐시의 그 뒤 전부가 무효화되므로, 재작성 비용을 못 갚는
    소액 회수는 순손실이다 (OpenCode의 PRUNE_MINIMUM과 같은 판단)."""
    end = _prunable_end(messages, tail_tokens)
    before = estimate_tokens(messages)

    # 원본 불변 — 실제로 바꾼 메시지만 얕은 복사한다 (assistant의 SDK 객체는 복사도 변형도 안 한다).
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

    Codex는 store=false라 매 iteration 히스토리 전체를 재전송한다. 여기에 프룬이 없으면
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
