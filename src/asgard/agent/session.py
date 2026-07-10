"""AgentSession — 단일 컨텍스트 tool use 루프 (CUS-137, CUS-143).

세션 = (system, tools, messages) 하나. 서브에이전트(역할·딜리버리)는 새 AgentSession —
child context 라 프로세스 스폰 없이 중첩된다 (CUS-142 의 구조적 기반).

트랜스포트 3종 (루프·툴 실행은 공유, API 호출·파싱만 분기):
  anthropic     — Messages API (스키마리스 bash/editor, content 블록)
  openai_compat — chat.completions (function 툴, reasoning_content 스트리밍 — nvidia NIM 등)
  claude_cli    — 로컬 claude CLI(Claude Code) 를 Agent SDK 로 구동 (claude_native.py, CUS-190).
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

from ..providers import ResolvedProvider
from . import tools as T


@dataclass
class SessionResult:
    text: str
    stop_reason: str
    commands: list[dict] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    tokens: int = 0  # 이 세션 누적 토큰 (매 iteration input+output 합산 = 지출량) — status line 사용량
    context_tokens: int = 0  # 마지막 API 호출의 input+output = 현재 컨텍스트 크기 — 창 % 는 이걸로
    # (tokens 는 iteration 마다 전체 프롬프트를 재합산하므로 컨텍스트 창 대비 % 가 100 을 넘는다)


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


# ── openai function 스키마 — 스키마리스 anthropic 툴의 명시 대응 ──
_OPENAI_BASH = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a bash command in the project root.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
}
_OPENAI_EDIT = {
    "type": "function",
    "function": {
        "name": "str_replace_based_edit_tool",
        "description": "View/create/edit files. command: view|create|str_replace|insert.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "path": {"type": "string"},
                "file_text": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
                "insert_line": {"type": "integer"},
                "insert_text": {"type": "string"},
                "view_range": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["command", "path"],
        },
    },
}


def _to_openai_tool(t: dict) -> dict:
    if t.get("type", "").startswith("bash"):
        return _OPENAI_BASH
    if t.get("type", "").startswith("text_editor"):
        return _OPENAI_EDIT
    return {
        "type": "function",
        "function": {  # 커스텀 (dispatch/verdict)
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t["input_schema"],
        },
    }


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
    ):
        self.client, self.rp, self.root, self.system = client, rp, root, system
        # readonly = 역할→도구 구조 강제 (thinker/verifier/loki) — editor write 거부.
        # ponytail: bash 리다이렉션 write 는 못 막는다 — 남는 흔적은 게이트(diff/orphan-write)가 잡는다.
        self.readonly = readonly
        self.tools = [T.BASH_TOOL, T.EDITOR_TOOL] + (extra_tools or [])
        self.handlers = tool_handlers or {}
        self.on_text = on_text or (lambda s: None)
        # 라이브 상태 신호 — 침묵 구간(thinking·툴 실행)에 스피너 등을 띄울 훅. None = 해제.
        self.on_status = on_status or (lambda s: None)
        self.on_tokens = on_tokens
        self.max_iterations = max_iterations
        self.messages: list[dict] = []

    def _tool_line(self, sym: str, detail: str, secs: float | None = None) -> None:
        """cursor-agent 식 활동 라인 — ⬢ + 요약 + 소요시간 (완료 후 출력, 전부 흐리게)."""
        from .. import ui

        dur = f" · {secs:.0f}s" if secs is not None and secs >= 1 else ""
        self.on_text(f"  {ui.dim('⬢ ' + sym + ' ' + detail.strip()[:100] + dur)}\n")

    def _thought_line(self, secs: float) -> None:
        """thinking 원문 대신 축약 한 줄 — '⬢ Thought 3s' (cursor-agent 참조)."""
        from .. import ui
        from ..i18n import t

        self.on_text(f"  {ui.dim(f'⬢ {t("thought")} {secs:.0f}s')}\n")

    # ── 툴 실행 (트랜스포트 공유) — (output, is_error) ──────────────────
    def _execute(self, call: _Call, result: SessionResult) -> tuple[str, bool]:
        try:
            if call.name == "bash":
                cmd = str(call.input.get("command") or "restart")
                self.on_status("$ " + cmd[:60])
                t0 = time.monotonic()
                out, code = T.run_bash(self.root, call.input)
                self.on_status(None)
                self._tool_line("$", cmd, time.monotonic() - t0)
                result.commands.append({"cmd": cmd[:200], "exit_code": code})
                return out, False
            if call.name == "str_replace_based_edit_tool":
                if self.readonly and call.input.get("command") != "view":
                    return "이 세션은 읽기 전용 역할입니다 — 파일 수정은 Worker 의 몫 (view 만 허용)", True
                self.on_status("✎ " + str(call.input.get("path", ""))[:60])
                t0 = time.monotonic()
                out = T.run_editor(self.root, call.input, result.writes)
                self.on_status(None)
                self._tool_line(
                    "✎", f"{call.input.get('command', '?')} {call.input.get('path', '')}", time.monotonic() - t0
                )
                return out, False
            if call.name in self.handlers:
                result.tool_calls.append({"name": call.name, "input": dict(call.input)})
                return self.handlers[call.name](dict(call.input)), False
            return f"unknown tool {call.name}", True
        except T.ToolError as e:
            return str(e), True
        except Exception as e:
            return f"tool crashed: {e}", True

    # ── 진입점 ──────────────────────────────────────────────────────────
    def run(self, user_content: str) -> SessionResult:
        try:
            if self.rp.profile.api_mode == "claude_cli":
                from . import claude_native

                r = claude_native.run(self, user_content)
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
        ponytail: 요약 압축 아님 — 툴 출력이 컨텍스트 질량 대부분이라 이걸로 충분, 부족해지면 요약 승격."""
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
        win = self.rp.profile.context_window
        if win and result.context_tokens > win * 0.8:
            n = self._prune_history()
            if n:
                self._tool_line("⌫", f"컨텍스트 압축 — 오래된 툴 출력 {n}건 프룬")

    def _run_anthropic(self, user_content: str) -> SessionResult:
        self.messages.append({"role": "user", "content": user_content})
        result = SessionResult(text="", stop_reason="")
        for _ in range(self.max_iterations):
            from ..i18n import t as _t

            self._maybe_prune(result)
            self.on_status(_t("thinking"))
            t0, first = time.monotonic(), True
            with self.client.messages.stream(
                model=self.rp.model,
                max_tokens=32000,
                system=self.system,
                thinking={"type": "adaptive"},
                tools=self.tools,
                messages=self.messages,
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
            self.messages.append({"role": "assistant", "content": resp.content})
            result.text = "".join(b.text for b in resp.content if b.type == "text")
            result.stop_reason = resp.stop_reason or ""
            u = getattr(resp, "usage", None)
            if u:
                result.context_tokens = (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "output_tokens", 0) or 0)
                result.tokens += result.context_tokens
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
        extra = dict(self.rp.profile.extra_body)  # provider 고유 (nvidia reasoning 등)
        sys_msg = [{"role": "system", "content": self.system}]

        from ..i18n import t as _t

        for _ in range(self.max_iterations):
            text_buf, calls, think_t0, finish = [], {}, None, None
            self._maybe_prune(result)
            self.on_status(_t("thinking"))
            stream = self.client.chat.completions.create(
                model=self.rp.model,
                messages=sys_msg + self.messages,
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
        timeout=300,  # append(PASS) 가 하네스 베이스라인 체크를 직접 돌린다 (CUS-187, 체크당 기본 120s)
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
