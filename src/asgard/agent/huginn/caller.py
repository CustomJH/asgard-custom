"""요약 호출자 — 세션의 트랜스포트로 요약 1회를 부르는 함수를 만든다.

엔진은 와이어를 모른다. 그 경계가 여기라서, 시험은 가짜 호출자를 그대로 꽂을 수 있다."""

from __future__ import annotations

import time


def make_caller(session) -> object | None:
    """세션의 provider로 요약 1회 호출하는 호출자. 미지원 트랜스포트는 None."""
    mode = session.rp.profile.api_mode
    if mode in {"claude_cli", "openai_responses"}:
        return None  # 각각 Claude Code / 서버측 truncation이 압축을 소유한다

    def call(prompt: str, max_tokens: int) -> str:
        from ...io_journal import call_returned, call_started

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
                from ...openai_codex import create_response  # Codex 엔드포인트는 스트리밍만 받는다

                resp = create_response(
                    session.client,
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
