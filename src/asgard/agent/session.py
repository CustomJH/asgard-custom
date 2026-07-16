"""AgentSession — 단일 컨텍스트 tool use 루프.

세션 = (system, tools, messages) 하나. 서브에이전트(역할·딜리버리)는 새 AgentSession —
child context 라 프로세스 스폰 없이 중첩된다 (중첩 디스패치의 구조적 기반).

트랜스포트 3종 (루프·툴 실행은 공유, API 호출·파싱만 분기):
  anthropic     — Messages API (스키마리스 bash/editor, content 블록)
  openai_compat — chat.completions (function 툴, reasoning_content 스트리밍 — nvidia NIM 등)
  claude_cli    — 로컬 claude CLI(Claude Code) 를 Agent SDK 로 구동 (claude_native.py).
                  예외적으로 내부 루프는 Claude Code 소유 — 커스텀 툴은 in-process MCP 로
                  이쪽 핸들러 실행, 커맨드/쓰기/토큰은 이벤트 관찰로 집계 (계약 유지).
루프를 Asgard 가 소유하는 게 핵심 — strands/langchain 은 루프를 가져가서 Trinity 강제화를 없앤다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from ..io_journal import call_returned, call_started
from ..providers import ResolvedProvider
from .tool_kernel import ToolContext, build_session_registry, execute_tool, to_openai_tool


@dataclass
class SessionResult:
    text: str
    stop_reason: str
    commands: list[dict] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    tokens: int = 0  # 이 세션 누적 토큰 (매 iteration input+output 합산 = 지출량) — status line 사용량
    context_tokens: int = 0  # 마지막 API 호출의 전체 프롬프트+출력 = 현재 컨텍스트 크기 — 창 % 는 이걸로
    # (tokens 는 iteration 마다 전체 프롬프트를 재합산하므로 컨텍스트 창 대비 % 가 100 을 넘는다)
    # 프롬프트 캐시 계측 (anthropic 트랜스포트) — read 는 ~0.1×, write 는 ~1.25× 과금
    cache_read_tokens: int = 0  # 캐시에서 읽은 누적 입력 토큰
    cache_write_tokens: int = 0  # 캐시에 쓴 누적 입력 토큰
    uncached_input_tokens: int = 0  # 정가로 처리된 누적 입력 토큰 — 적중률 분모용


def make_client(rp: ResolvedProvider):
    """provider → SDK 클라이언트. 키는 resolve() 가 env 또는 credentials.json 에서 찾아둔 값(rp.api_key)."""
    if rp.profile.api_mode == "anthropic":
        import anthropic

        # rp.api_key 있으면 그것(env 또는 credentials.json), 없으면 SDK 기본 해석(프로파일 등)에 위임
        return anthropic.Anthropic(api_key=rp.api_key) if rp.api_key else anthropic.Anthropic()
    if rp.profile.api_mode == "openai_compat":
        from openai import OpenAI

        if not rp.api_key:
            raise RuntimeError(f"API 키 없음 ({rp.profile.name}) — asgard start 온보딩에서 입력하세요")
        return OpenAI(base_url=rp.base_url or None, api_key=rp.api_key)
    if rp.profile.api_mode == "claude_cli":
        from .claude_native import make_native_client

        return make_native_client()  # 마커 — 실제 스폰·인증은 Agent SDK/CLI 가 해석
    raise NotImplementedError(f"api_mode '{rp.profile.api_mode}' 미지원")


def _to_openai_tool(t: dict) -> dict:
    return to_openai_tool(t)


# 창 미상 프로바이더의 프룬 폴백 상한 — 주류 창(≥128k) 기준 보수값. 더 작은 모델은
# config [provider] context_window 로 실제 창을 알려야 정확히 보호된다.
_FALLBACK_CONTEXT_WINDOW = 128_000


class _Call:
    """트랜스포트 무관 툴콜 — (id, name, input)."""

    def __init__(self, cid, name, inp):
        self.id, self.name, self.input = cid, name, inp


class AgentSession:
    def __init__(
        self,
        client,
        rp: ResolvedProvider,
        root: str,
        system: str,
        extra_tools: list[dict] | None = None,
        tool_handlers: dict[str, Callable[[dict], str]] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tokens: Callable[[int], None] | None = None,
        on_status: Callable[[str | None], None] | None = None,
        max_iterations: int = 40,
        readonly: bool = False,
        role: str | None = None,
    ):
        self.client, self.rp, self.root, self.system = client, rp, root, system
        # readonly = 역할→도구 구조 강제 (thinker/verifier/loki) — editor write 거부.
        # lagom: bash 리다이렉션 write 는 못 막는다 — 남는 흔적은 게이트(diff/orphan-write)가 잡는다.
        self.readonly = readonly
        self.role = role or ("readonly" if readonly else "legacy")
        self.handlers = tool_handlers or {}
        self.registry = build_session_registry(extra_tools, self.handlers)
        # 세션 중 schema 를 동결해 prompt cache key 와 실제 호출 가능 표면을 일치시킨다.
        self.tools = self.registry.schemas(ToolContext(root=self.root, role=self.role, readonly=self.readonly))
        self.on_text = on_text or (lambda s: None)
        # 라이브 상태 신호 — 침묵 구간(thinking·툴 실행)에 스피너 등을 띄울 훅. None = 해제.
        self.on_status = on_status or (lambda s: None)
        self.on_tokens = on_tokens
        self.max_iterations = max_iterations
        self.messages: list[dict] = []
        # 딜리버리 디스패치 자식 마커 — claude_cli 에서 부모가 spawn permit 을 쥔 채 기다리므로
        # 자식은 permit 을 재요구하지 않는다 (재진입 데드락, CUS-246). _dispatch_handler 가 켠다.
        self._nested_dispatch = False
        # 프롬프트 캐싱 (anthropic 전용, 상시 기본) — config [cache] enabled/ttl, 세션 생성 시 1회 해석
        from .prompt_cache import cache_settings

        self.cache_enabled, self.cache_ttl = cache_settings(root)

    def _tool_line(self, sym: str, detail: str, secs: float | None = None) -> None:
        """cursor-agent 식 활동 라인 — ⬢ + 요약 + 소요시간 (완료 후 출력, 전부 흐리게)."""
        from .. import ui

        dur = f" · {secs:.0f}s" if secs is not None and secs >= 1 else ""
        self.on_text(f"  {ui.dim('⬢ ' + sym + ' ' + detail.strip()[:100] + dur)}\n")

    def _thought_line(self, secs: float) -> None:
        """thinking 원문 대신 축약 한 줄 — '⬢ Thought 3s' (cursor-agent 참조)."""
        from .. import ui
        from ..i18n import t

        label = t("thought")
        self.on_text(f"  {ui.dim(f'⬢ {label} {secs:.0f}s')}\n")

    # ── 툴 실행 (트랜스포트 공유) — (output, is_error) ──────────────────
    def _execute(self, call: _Call, result: SessionResult) -> tuple[str, bool]:
        ctx = ToolContext(
            root=self.root,
            role=self.role,
            readonly=self.readonly,
            writes=result.writes,
            commands=result.commands,
            tool_calls=result.tool_calls,
        )
        if call.name == "bash":
            detail, sym = str(call.input.get("command") or "restart"), "$"
        elif call.name == "str_replace_based_edit_tool":
            detail = f"{call.input.get('command', '?')} {call.input.get('path', '')}"
            sym = "✎"
        else:
            detail, sym = call.name, "⚙"
        self.on_status(f"{sym} {detail[:60]}")
        t0 = time.monotonic()
        out = execute_tool(self.registry, call.name, call.input, ctx)
        self.on_status(None)
        self._tool_line(sym, detail, time.monotonic() - t0)
        return out.content, out.is_error

    # ── 진입점 ──────────────────────────────────────────────────────────
    def _journal_started(self, transport: str) -> tuple[str | None, float]:
        jid = call_started(
            self.root, provider=self.rp.profile.name, model=self.rp.model, transport=transport, role=self.role
        )
        return jid, time.monotonic()

    def _journal_error(self, jid: str | None, t0: float, e: Exception) -> None:
        call_returned(self.root, jid, duration_ms=(time.monotonic() - t0) * 1000, error=f"{type(e).__name__}: {e}")

    def run(self, user_content: str) -> SessionResult:
        try:
            if self.rp.profile.api_mode == "claude_cli":
                from . import claude_native

                # claude_cli 는 내부 루프를 Claude Code 가 소유 — 저널은 run 전체를 한 호출로 기록
                jid, j0 = self._journal_started("claude_cli")
                try:
                    r = claude_native.run(self, user_content)
                except Exception as e:
                    self._journal_error(jid, j0, e)
                    raise
                call_returned(
                    self.root,
                    jid,
                    duration_ms=(time.monotonic() - j0) * 1000,
                    tokens=r.tokens,
                    context_tokens=r.context_tokens,
                    cache_read_tokens=r.cache_read_tokens,
                    cache_write_tokens=r.cache_write_tokens,
                )
            elif self.rp.profile.api_mode == "anthropic":
                r = self._run_anthropic(user_content)
            else:
                r = self._run_openai(user_content)
        finally:
            self.on_status(None)
        if self.on_tokens and r.tokens:
            self.on_tokens(r.tokens)
        return r

    def _prune_history(self, keep: int = 6) -> int:
        """컨텍스트 창 80% 도달 시 오래된 툴 출력 본문을 비운다 — LLM 무호출 결정론 압축.
        lagom: 요약 압축 아님 — 툴 출력이 컨텍스트 질량 대부분이라 이걸로 충분, 부족해지면 요약 승격."""
        pruned = 0
        for m in self.messages[:-keep]:
            c = m.get("content")
            if isinstance(c, list):  # anthropic — user 메시지 안의 tool_result 블록
                for b in c:
                    if (
                        isinstance(b, dict)
                        and b.get("type") == "tool_result"
                        and b.get("content") not in (None, "[pruned]")
                    ):
                        b["content"] = "[pruned]"
                        pruned += 1
            elif m.get("role") == "tool" and c not in (None, "[pruned]"):  # openai — role=tool 메시지
                m["content"] = "[pruned]"
                pruned += 1
        return pruned

    def _maybe_prune(self, result: SessionResult) -> None:
        # 창 미상(profile=0, openai_compat/nvidia)이어도 프룬은 걸려야 한다 — 폴백 없이는
        # 컨텍스트가 무한 성장해 API 한도 초과(400 fatal)로만 터진다 (CUS-248).
        # 정밀값은 config [provider] context_window 로 지정.
        win = self.rp.context_window or self.rp.profile.context_window or _FALLBACK_CONTEXT_WINDOW
        if result.context_tokens > win * 0.8:
            n = self._prune_history()
            if n:
                self._tool_line("⌫", f"컨텍스트 압축 — 오래된 툴 출력 {n}건 프룬")

    def _run_anthropic(self, user_content: str) -> SessionResult:
        self.messages.append({"role": "user", "content": user_content})
        result = SessionResult(text="", stop_reason="")
        for _ in range(self.max_iterations):
            from ..i18n import t as _t

            self._maybe_prune(result)
            system, messages = self.system, self.messages
            if self.cache_enabled:  # 브레이크포인트 주입 — 원본 히스토리는 불변 (prompt_cache 참조)
                from .prompt_cache import cached_request

                system, messages = cached_request(self.system, self.messages, self.cache_ttl)
            self.on_status(_t("thinking"))
            jid, j0 = self._journal_started("anthropic")
            t0, first = time.monotonic(), True
            try:
                with self.client.messages.stream(
                    model=self.rp.model,
                    max_tokens=32000,
                    system=system,
                    thinking={"type": "adaptive"},
                    tools=self.tools,
                    messages=messages,
                ) as stream:
                    for text in stream.text_stream:
                        if first:  # 첫 토큰 전 침묵 = thinking — 2s 이상이면 축약 라인
                            first = False
                            self.on_status(None)
                            gap = time.monotonic() - t0
                            if gap >= 2:
                                self._thought_line(gap)
                        self.on_text(text)
                    resp = stream.get_final_message()
            except Exception as e:
                self._journal_error(jid, j0, e)
                raise
            self.messages.append({"role": "assistant", "content": resp.content})
            result.text = "".join(b.text for b in resp.content if b.type == "text")
            result.stop_reason = resp.stop_reason or ""
            u = getattr(resp, "usage", None)
            counts: dict[str, int] = {}
            if u:
                # 캐시 적중분은 input_tokens 에서 빠진다 — 셋을 합쳐야 실제 컨텍스트 크기.
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
                from .. import ui

                self.on_text(f"\n  {ui.dim('⚠ max_tokens 도달 — 응답이 절단됨 (이어서 계속하려면 재요청)')}\n")
            if resp.stop_reason == "tool_use":
                trs = []
                for b in resp.content:
                    if b.type == "tool_use":
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

    def _run_openai(self, user_content: str) -> SessionResult:
        oai_tools = [_to_openai_tool(t) for t in self.tools]
        self.messages.append({"role": "user", "content": user_content})
        result = SessionResult(text="", stop_reason="")
        extra = self.rp.profile.request_extra_body(self.rp.model)  # 선택 모델에 유효한 provider 고유 필드만
        sys_msg = [{"role": "system", "content": self.system}]
        # 마커 주입은 실측 검증 조합만 (화이트리스트 — 미검증 provider 에 비표준 필드는 400 위험).
        # OpenAI 자체는 자동 프리픽스 캐시라 마커 불요 — 계측(cached_tokens)은 아래 usage 에서 공통.
        from .prompt_cache import openai_cache_markers_supported

        inject = self.cache_enabled and openai_cache_markers_supported(self.rp.base_url, self.rp.model)

        from ..i18n import t as _t

        for _ in range(self.max_iterations):
            text_buf, calls, think_t0, finish = [], {}, None, None
            self._maybe_prune(result)
            if inject:
                from .prompt_cache import cached_openai_request

                send_msgs = cached_openai_request(sys_msg, self.messages, self.cache_ttl)
            else:
                send_msgs = sys_msg + self.messages
            self.on_status(_t("thinking"))
            jid, j0 = self._journal_started("openai_compat")
            jcounts: dict[str, int] = {}
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
                for chunk in stream:
                    u = getattr(chunk, "usage", None)  # usage 는 보통 choices 빈 마지막 chunk 에 온다
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
                        self.on_text(d.content)
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
            result.text = "".join(text_buf)
            if finish == "length":  # max_tokens 절단 — 잘린 툴콜 인자 실행은 위험, 정직하게 종료
                from .. import ui

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
                try:
                    inp = json.loads(c["args"] or "{}")
                except Exception:
                    inp = {}
                out, _err = self._execute(_Call(c["id"], c["name"], inp), result)
                self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        result.stop_reason = "max_iterations"
        return result


# ── 퀘스트 로그·게이트 subprocess 래퍼 — 훅을 배포 형태 그대로 (36/36 테스트된 계약) ──


def ql(root: str, *args: str, stdin: str = "", session: str = "native") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "asgard.hooks.quest_log", *args, "--session", session],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=root,
        timeout=300,  # append(PASS) 가 하네스 베이스라인 체크를 직접 돌린다 (체크당 기본 120s)
    )


def gate(root: str, session: str = "native") -> tuple[bool, str]:
    import json as _json

    p = subprocess.run(
        [sys.executable, "-m", "asgard.hooks.verifier_gate"],
        input=_json.dumps({"session_id": session, "cwd": root}),
        capture_output=True,
        text=True,
        cwd=root,
        timeout=60,
    )
    if '"block"' in (p.stdout or ""):
        try:
            return True, _json.loads(p.stdout)["reason"]
        except Exception:
            return True, p.stdout[:300]
    return False, ""
