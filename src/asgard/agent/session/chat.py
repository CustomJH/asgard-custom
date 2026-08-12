"""openai_compat(chat.completions) 트랜스포트 — 델타 스트리밍 루프 하나.

reasoning 필드명이 벤더마다 다르고 429 를 여기서 흡수한다는 점이 anthropic 경로와 다르다.
툴콜은 index 슬롯에 조각으로 도착하므로 다 모은 뒤에 실행한다."""

from __future__ import annotations

import json
import time

from ...io_journal import call_returned
from ...memory.fence import scrub as _fence_scrub
from ._shared import _SessionState
from .types import ProviderRetriesExhausted, SessionResult, _Call
from .wire import _to_openai_tool


class _ChatMixin(_SessionState):
    def _run_openai(self, user_content: str) -> SessionResult:
        oai_tools = [_to_openai_tool(t) for t in self.tools]
        self.messages.append({"role": "user", "content": user_content})
        result = SessionResult(text="", stop_reason="")
        extra = self.rp.profile.request_extra_body(self.rp.model)  # 선택 모델에 유효한 provider 고유 필드만
        sys_msg = [{"role": "system", "content": self.system}]
        # 마커 주입은 실측 검증 조합만 (화이트리스트 — 미검증 provider에 비표준 필드는 400 위험).
        # OpenAI 자체는 자동 프리픽스 캐시라 마커 불필요 — 계측(cached_tokens)은 아래 usage에서 공통.
        from ..prompt_cache import openai_cache_markers_supported

        inject = self.cache_enabled and openai_cache_markers_supported(self.rp.base_url, self.rp.model)

        from ...i18n import thinking as _thinking

        for _ in range(self.max_iterations):
            if self._cancelled():
                result.stop_reason = "cancelled"
                return result
            text_buf, calls, think_t0, finish = [], {}, None, None
            self._maybe_compress(result)
            if inject:
                from ..prompt_cache import cached_openai_request

                send_msgs = cached_openai_request(sys_msg, self.messages, self.cache_ttl)
            else:
                send_msgs = sys_msg + self.messages
            self._throttle()
            if self._cancelled():
                result.stop_reason = "cancelled"
                return result
            self.on_status(_thinking(self.role))
            jid, j0 = self._journal_started("openai_compat")
            jcounts: dict[str, int] = {}
            try:
                # 429만 여기서 흡수 (Retry-After 존중) — NIM 무료 티어는 스로틀에도 전역 트래픽으로
                # 초과가 날 수 있다. 그 외 오류는 기존 경로 (재시도는 Heimdall _run_turn 몫).
                from ..rate_limit import retry_after_seconds

                for attempt in range(4):
                    try:
                        stream = self.client.chat.completions.create(
                            model=self.rp.model,
                            messages=send_msgs,
                            tools=oai_tools or None,
                            max_tokens=16384,
                            stream=True,
                            stream_options={"include_usage": True},
                            extra_body=extra or None,
                        )
                        break
                    except Exception as e:
                        wait = retry_after_seconds(e, attempt)
                        if wait is None:
                            raise
                        if attempt == 3:
                            # 이 transport가 이미 4회 시도했다. Heimdall은 provider 폴백만 하고
                            # 같은 요청을 다시 3세트 반복하지 않는다.
                            raise ProviderRetriesExhausted(str(e)) from e
                        self._tool_line("⏳", f"429 rate limit — {wait:.0f}s 후 재시도")
                        if self.cancel_event.wait(wait):
                            self._journal_error(jid, j0, e)
                            result.stop_reason = "cancelled"
                            return result
                for chunk in stream:
                    if self._cancelled():
                        try:
                            stream.close()
                        except Exception:
                            pass
                        break
                    u = getattr(chunk, "usage", None)  # usage는 보통 choices 빈 마지막 chunk에 온다
                    if u:
                        result.context_tokens = getattr(u, "total_tokens", 0) or 0
                        result.tokens += result.context_tokens
                        # OpenAI-와이어 캐시 계측 — 마커 주입 여부와 무관하게 리포트되면 집계
                        # (OpenAI 자동 프리픽스 캐시·OpenRouter 전부 prompt_tokens_details.cached_tokens)
                        det = getattr(u, "prompt_tokens_details", None)
                        cr = (getattr(det, "cached_tokens", 0) or 0) if det else 0
                        result.cache_read_tokens += cr
                        result.uncached_input_tokens += max(0, (getattr(u, "prompt_tokens", 0) or 0) - cr)
                        jcounts = {"total_tokens": result.context_tokens, "cache_read_tokens": cr}
                    if not chunk.choices:
                        continue
                    if chunk.choices[0].finish_reason:
                        finish = chunk.choices[0].finish_reason
                    d = chunk.choices[0].delta
                    # reasoning 필드명은 벤더별 상이 — nvidia=reasoning_content, ollama=reasoning
                    reasoning = getattr(d, "reasoning_content", None) or getattr(d, "reasoning", None)
                    if reasoning:  # 원문 덤프 대신 축약 — 시작 시각만 기록
                        if think_t0 is None:
                            think_t0 = time.monotonic()
                    if d.content:
                        self.on_status(None)
                        if think_t0 is not None:
                            self._thought_line(time.monotonic() - think_t0)
                            think_t0 = None
                        text_buf.append(d.content)
                        self.emit_text(d.content)
                    for tc in d.tool_calls or []:
                        slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["args"] += tc.function.arguments
            except Exception as e:
                self._journal_error(jid, j0, e)
                raise
            call_returned(self.root, jid, duration_ms=(time.monotonic() - j0) * 1000, counts=jcounts)

            self.on_status(None)
            if think_t0 is not None:  # thinking 후 바로 툴콜 — 텍스트 없이 끝난 경우
                self._thought_line(time.monotonic() - think_t0)
            self._fence_tail()
            result.text = _fence_scrub("".join(text_buf))
            if self._cancelled():  # 스트림 중단 — 부분 텍스트를 assistant로 닫아 히스토리 유효 유지
                self.messages.append({"role": "assistant", "content": result.text or "[사용자 취소]"})
                result.stop_reason = "cancelled"
                return result
            if finish == "length":  # max_tokens 절단 — 잘린 툴콜 인자 실행은 위험, 정직하게 종료
                from ... import ui

                self.on_text(f"\n  {ui.dim('⚠ max_tokens 도달 — 응답이 절단됨 (이어서 계속하려면 재요청)')}\n")
                result.stop_reason = "max_tokens"
                return result
            if not calls:
                result.stop_reason = "end_turn"
                return result

            # assistant 툴콜 메시지 재구성 (openai 히스토리 계약)
            self.messages.append(
                {
                    "role": "assistant",
                    "content": result.text or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c["args"] or "{}"},
                        }
                        for c in calls.values()
                    ],
                }
            )
            for c in calls.values():
                if self._cancelled():  # 잔여 콜은 실행 없이 닫는다 — tool 쌍 보존
                    self.messages.append(
                        {"role": "tool", "tool_call_id": c["id"], "content": "[사용자 취소 — 실행 안 함]"}
                    )
                    continue
                try:
                    inp = json.loads(c["args"] or "{}")
                except Exception:
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": "malformed tool arguments: valid JSON object required",
                        }
                    )
                    continue
                out, _err = self._execute(_Call(c["id"], c["name"], inp), result)
                self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        result.stop_reason = "max_iterations"
        return result
