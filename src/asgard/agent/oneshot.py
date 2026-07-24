"""단발 LLM 완성 — provider 계층을 재사용하는 배경 지능 공용 단일 호출.

evolution.polish(스킬 증류)·memory.norn(노른 손질)처럼 "닫힌 과업 1회 호출"만 필요한
소비자가 공유한다. 스트리밍·툴·세션 상태 없음. 실패는 예외 그대로 올린다 —
fail-open 여부는 호출측 정책이다 (증류는 초안 유지, 노른은 제안 없음)."""

from __future__ import annotations

from typing import Any, cast


def complete_once(root: str, system: str, user: str, max_tokens: int = 3000) -> str:
    """resolve 된 provider 로 단발 완성 1회. provider 미충족은 RuntimeError."""
    from ..providers import resolve
    from .rate_limit import throttle
    from .session import make_client

    rp = resolve(root)
    if rp.missing:
        raise RuntimeError("provider 미충족: " + "; ".join(rp.missing))
    client = make_client(rp)
    throttle(rp)  # RPM 상한 provider — 단발 호출도 전역 윈도에 계수
    if rp.profile.api_mode == "claude_cli":
        from .claude_native import complete_text

        return complete_text(system, user, model=rp.model, root=root)
    if rp.profile.api_mode == "anthropic":
        resp = client.messages.create(
            model=rp.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
        )
        return "".join(b.text for b in resp.content if b.type == "text")
    if rp.profile.api_mode in {"openai_responses", "codex_responses"}:
        kwargs: dict[str, Any] = {"model": rp.model, "instructions": system, "input": user, "timeout": 120.0}
        if rp.profile.api_mode == "codex_responses":
            kwargs["store"] = False
        else:
            kwargs["max_output_tokens"] = max(max_tokens, 4096)
        if rp.model.startswith(("gpt-5", "o")):
            kwargs["reasoning"] = {"effort": "low"}
        resp = cast(Any, client).responses.create(**kwargs)
        return resp.output_text or ""
    resp = client.chat.completions.create(
        model=rp.model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content or ""
