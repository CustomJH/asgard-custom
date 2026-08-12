"""OpenAI/Codex Responses 트랜스포트 — 논스트리밍 루프 하나.

두 백엔드가 상태를 다르게 쥔다. api.openai.com 은 `previous_response_id` 로 서버가 히스토리를
들고, ChatGPT Codex 엔드포인트는 store=false 라 매 iteration 전체를 재전송한다 — 그래서 이
경로만 프룬(`_maybe_compress_codex`)과 reasoning 재생 폴백이 붙는다."""

from __future__ import annotations

import hashlib
import json
import time

from ...io_journal import call_returned
from ...memory.fence import scrub as _fence_scrub
from ._shared import _SessionState
from .types import SessionResult, _Call
from .wire import _codex_replay_item, _invalid_encrypted_content, _responses_create, _to_responses_tool


class _ResponsesMixin(_SessionState):
    def _run_responses(self, user_content: str) -> SessionResult:
        """OpenAI/Codex Responses loop with canonical Asgard function tools."""
        tools = [_to_responses_tool(tool) for tool in self.tools]
        result = SessionResult(text="", stop_reason="")
        codex_backend = self.rp.profile.api_mode == "codex_responses"
        if codex_backend:
            # ChatGPT's Codex endpoint is stateless (store=false): replay visible history and
            # this turn's function items instead of relying on previous_response_id.
            history = getattr(self, "_codex_history_items", None)
            if history is None:
                history = [
                    {
                        "role": message["role"],
                        "content": [
                            {
                                "type": "input_text" if message["role"] == "user" else "output_text",
                                "text": str(message.get("content", "")),
                            }
                        ],
                    }
                    for message in self.messages
                    if message.get("role") in {"user", "assistant"}
                ]
            pending_input: object = list(history)
            pending_input.append({"role": "user", "content": [{"type": "input_text", "text": user_content}]})
            previous_response_id = None
        else:
            pending_input = user_content
            previous_response_id = getattr(self, "_openai_response_id", None)
        from ...i18n import thinking as _thinking

        for _ in range(self.max_iterations):
            if self._cancelled():
                # Responses는 논스트리밍 — 취소 경계는 iteration/툴 배치. 미제출 툴 출력은 버려지고
                # codex 히스토리는 마지막 완결 상태(_codex_history_items)로 남는다.
                result.stop_reason = "cancelled"
                return result
            self._throttle()
            if self._cancelled():
                result.stop_reason = "cancelled"
                return result
            if codex_backend and isinstance(pending_input, list):
                # store=false라 매 iteration 히스토리 전체를 재전송한다 — 프룬이 없으면
                # 툴 출력이 무한 누적돼 한도 초과 400 으로만 터진다.
                pending_input = self._maybe_compress_codex(pending_input, result)
                self._codex_history_items = list(pending_input)
            self.on_status(_thinking(self.role))
            jid, j0 = self._journal_started("codex_responses" if codex_backend else "openai_responses")
            kwargs: dict = {
                "model": self.rp.model,
                "instructions": self.system,
                "input": pending_input,
                "timeout": 3600.0,
                "store": not codex_backend,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
                kwargs["parallel_tool_calls"] = True
            if codex_backend:
                cache_material = json.dumps(tools, sort_keys=True, separators=(",", ":")) + self.system
                if self._codex_reasoning_replay_enabled:
                    kwargs["include"] = ["reasoning.encrypted_content"]
                kwargs["prompt_cache_key"] = hashlib.sha256(cache_material.encode()).hexdigest()
                kwargs["extra_headers"] = {
                    "session_id": self._codex_session_id,
                    "x-client-request-id": self._codex_session_id,
                }
                if self.rp.model.startswith(("gpt-5", "o")):
                    kwargs["reasoning"] = {"effort": "medium", "summary": "auto"}
            if not codex_backend:
                kwargs["max_output_tokens"] = 32_768
                kwargs["truncation"] = "auto"
            if previous_response_id:
                kwargs["previous_response_id"] = previous_response_id
            try:
                response = _responses_create(self.client, kwargs, codex_backend=codex_backend)
            except Exception as e:
                if codex_backend and self._codex_reasoning_replay_enabled and _invalid_encrypted_content(e):
                    self._codex_reasoning_replay_enabled = False
                    if isinstance(pending_input, list):
                        pending_input = [item for item in pending_input if item.get("type") != "reasoning"]
                        self._codex_history_items = list(pending_input)
                        kwargs["input"] = pending_input
                    kwargs.pop("include", None)
                    try:
                        response = _responses_create(self.client, kwargs, codex_backend=codex_backend)
                    except Exception as retry_error:
                        self._journal_error(jid, j0, retry_error)
                        raise
                elif codex_backend and getattr(e, "status_code", None) == 401:
                    try:
                        from ...openai_codex import make_client as make_codex_client

                        self.client = make_codex_client(force_refresh=True)
                        response = _responses_create(self.client, kwargs, codex_backend=codex_backend)
                    except Exception as retry_error:
                        self._journal_error(jid, j0, retry_error)
                        raise
                else:
                    self._journal_error(jid, j0, e)
                    raise
            usage = getattr(response, "usage", None)
            inp = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
            total = int(getattr(usage, "total_tokens", 0) or (inp + output)) if usage else 0
            details = getattr(usage, "input_tokens_details", None) if usage else None
            cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
            result.context_tokens = total
            result.tokens += total
            result.cache_read_tokens += cached
            result.uncached_input_tokens += max(0, inp - cached)
            call_returned(
                self.root,
                jid,
                duration_ms=(time.monotonic() - j0) * 1000,
                counts={"total_tokens": total, "cache_read_tokens": cached},
            )
            self.on_status(None)
            if self._cancelled():
                # 블로킹 호출 중 취소 도착 — 응답을 히스토리·codex replay에 편입하지 않고 버린다.
                # (iteration 경계 취소와 동일 의미 — end_turn으로 흘러 영속·보존되는 구멍 봉쇄)
                result.stop_reason = "cancelled"
                return result
            response_status = str(getattr(response, "status", "completed") or "")
            if response_status not in {"completed", "incomplete"}:
                self._openai_response_id = None
                raise RuntimeError(f"Responses protocol rejected terminal status: {response_status or 'missing'}")
            text = str(getattr(response, "output_text", "") or "")
            replay_items = [
                replay
                for item in (getattr(response, "output", None) or [])
                if (replay := _codex_replay_item(item)) is not None
                and (self._codex_reasoning_replay_enabled or replay.get("type") != "reasoning")
            ]
            if text:
                result.text = _fence_scrub(text)
                self.emit_text(text)
            if response_status == "incomplete":
                details = getattr(response, "incomplete_details", None)
                reason = str(getattr(details, "reason", "") or "incomplete")
                result.stop_reason = "max_tokens" if reason == "max_output_tokens" else reason
                self._openai_response_id = None
                if codex_backend and isinstance(pending_input, list):
                    pending_input.extend(replay_items)
                    self._codex_history_items = list(pending_input)
                self.messages.append({"role": "user", "content": user_content})
                if result.text:
                    self.messages.append({"role": "assistant", "content": result.text})
                return result
            calls = [
                item
                for item in (getattr(response, "output", None) or [])
                if getattr(item, "type", "") == "function_call"
            ]
            previous_response_id = str(getattr(response, "id", "") or "") if not codex_backend else None
            self._openai_response_id = previous_response_id or None
            if not calls:
                result.stop_reason = "end_turn"
                if codex_backend and isinstance(pending_input, list):
                    pending_input.extend(replay_items)
                    self._codex_history_items = list(pending_input)
                self.messages.append({"role": "user", "content": user_content})
                if result.text:
                    self.messages.append({"role": "assistant", "content": result.text})
                return result
            outputs: list[dict] = []
            if codex_backend:
                if not isinstance(pending_input, list):
                    raise RuntimeError("Codex Responses input state is invalid")
                pending_input.extend(replay_items)
            for call in calls:
                if self._cancelled():  # 잔여 콜은 실행 없이 닫는다 — call_id 쌍 보존
                    out = "[사용자 취소 — 실행 안 함]"
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": str(getattr(call, "call_id", "")),
                            "output": out,
                        }
                    )
                    continue
                try:
                    value = json.loads(getattr(call, "arguments", "") or "{}")
                    if not isinstance(value, dict):
                        raise ValueError("object required")
                    out, _error = self._execute(
                        _Call(str(getattr(call, "call_id", "")), str(getattr(call, "name", "")), value), result
                    )
                except json.JSONDecodeError, ValueError:
                    out = "malformed tool arguments: valid JSON object required"
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(getattr(call, "call_id", "")),
                        "output": out,
                    }
                )
            if codex_backend:
                if not isinstance(pending_input, list):
                    raise RuntimeError("Codex Responses input state is invalid")
                pending_input.extend(outputs)
            else:
                pending_input = outputs
        self._openai_response_id = None
        if codex_backend and isinstance(pending_input, list):
            self._codex_history_items = list(pending_input)
            self.messages.append({"role": "user", "content": user_content})
        result.stop_reason = "max_iterations"
        return result
