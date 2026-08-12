"""anthropic Messages 트랜스포트 — 스트리밍 루프 하나.

content 블록 그대로를 히스토리에 넣고, tool_use 블록을 툴 배치로 돌린다. 취소는 iteration
경계·스트림 청크·툴 배치 사이에서 잡히고, 어느 자리에서 끊겨도 히스토리는 API-유효한
assistant 메시지로 닫는다."""

from __future__ import annotations

import time

from ...io_journal import call_returned
from ...memory.fence import scrub as _fence_scrub
from ._shared import _SessionState
from .types import SessionResult, _Call


class _MessagesMixin(_SessionState):
    def _run_anthropic(self, user_content: str) -> SessionResult:
        self.messages.append({"role": "user", "content": user_content})
        result = SessionResult(text="", stop_reason="")
        for _ in range(self.max_iterations):
            from ...i18n import thinking as _thinking

            if self._cancelled():
                result.stop_reason = "cancelled"
                return result
            self._maybe_compress(result)
            system, messages = self.system, self.messages
            if self.cache_enabled:  # 브레이크포인트 주입 — 원본 히스토리는 불변 (prompt_cache 참조)
                from ..prompt_cache import cached_request

                system, messages = cached_request(self.system, self.messages, self.cache_ttl)
            self._throttle()
            if self._cancelled():
                result.stop_reason = "cancelled"
                return result
            self.on_status(_thinking(self.role))
            jid, j0 = self._journal_started("anthropic")
            t0, first = time.monotonic(), True
            parts: list[str] = []
            resp = None
            try:
                with self._anthropic_stream(
                    model=self.rp.model,
                    max_tokens=32000,
                    system=system,
                    thinking={"type": "adaptive"},
                    tools=self.tools,
                    messages=messages,
                ) as stream:
                    for text in stream.text_stream:
                        if self._cancelled():  # with 탈출이 스트림을 닫는다 — 부분 응답은 아래서 봉합
                            break
                        if first:  # 첫 토큰 전 침묵 = thinking — 2s 이상이면 축약 라인
                            first = False
                            self.on_status(None)
                            gap = time.monotonic() - t0
                            if gap >= 2:
                                self._thought_line(gap)
                        parts.append(text)
                        self.emit_text(text)
                    if not self._cancelled():
                        resp = stream.get_final_message()
            except Exception as e:
                self._journal_error(jid, j0, e)
                if self._server_compaction_retry():
                    continue  # opt-in 기능이 세션을 깨지 않는다 — 끄고 같은 iteration 재시도
                raise
            if resp is None:  # 취소 중단 — 부분 텍스트를 assistant로 닫아 히스토리 API-유효 유지
                call_returned(self.root, jid, duration_ms=(time.monotonic() - j0) * 1000, error="cancelled")
                self.messages.append({"role": "assistant", "content": "".join(parts) or "[사용자 취소]"})
                self._fence_tail()
                result.text = _fence_scrub("".join(parts))
                result.stop_reason = "cancelled"
                return result
            self.messages.append({"role": "assistant", "content": resp.content})
            self._note_server_compaction(resp.content)  # T3 — provider가 압축했으면 계측
            result.text = _fence_scrub("".join(b.text for b in resp.content if b.type == "text"))
            result.stop_reason = resp.stop_reason or ""
            u = getattr(resp, "usage", None)
            counts: dict[str, int] = {}
            if u:
                # 캐시 적중분은 input_tokens에서 빠진다 — 셋을 합쳐야 실제 컨텍스트 크기.
                # 이걸 빼먹으면 캐싱 도입 후 창 80% 프룬 트리거가 과소계상으로 안 터진다.
                inp = getattr(u, "input_tokens", 0) or 0
                cr = getattr(u, "cache_read_input_tokens", 0) or 0
                cw = getattr(u, "cache_creation_input_tokens", 0) or 0
                outp = getattr(u, "output_tokens", 0) or 0
                result.context_tokens = inp + cr + cw + outp
                result.tokens += result.context_tokens
                result.cache_read_tokens += cr
                result.cache_write_tokens += cw
                result.uncached_input_tokens += inp
                counts = {
                    "input_tokens": inp,
                    "cache_read_tokens": cr,
                    "cache_write_tokens": cw,
                    "output_tokens": outp,
                }
            call_returned(self.root, jid, duration_ms=(time.monotonic() - j0) * 1000, counts=counts)
            if resp.stop_reason == "max_tokens":
                from ... import ui

                self.on_text(f"\n  {ui.dim('⚠ max_tokens 도달 — 응답이 절단됨 (이어서 계속하려면 재요청)')}\n")
            if resp.stop_reason == "tool_use":
                trs = []
                for b in resp.content:
                    if b.type == "tool_use":
                        if self._cancelled():  # 잔여 콜은 실행 없이 닫는다 — tool 쌍 보존 불변식
                            trs.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": b.id,
                                    "content": "[사용자 취소 — 실행 안 함]",
                                    "is_error": True,
                                }
                            )
                            continue
                        out, err = self._execute(_Call(b.id, b.name, dict(b.input)), result)
                        tr = {"type": "tool_result", "tool_use_id": b.id, "content": out}
                        if err:
                            tr["is_error"] = True
                        trs.append(tr)
                self.messages.append({"role": "user", "content": trs})
                continue
            if resp.stop_reason == "refusal":
                result.text = result.text or "(모델이 안전상 거부 — 요청을 조정해 재시도하세요)"
            return result
        result.stop_reason = "max_iterations"
        return result
