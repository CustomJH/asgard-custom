"""claude_cli 트랜스포트 — 로컬 claude CLI(Claude Code)를 Agent SDK 로 구동.

anthropic/openai_compat 과 달리 내부 루프를 Claude Code 하네스가 소유한다. Asgard 계약은
유지: 시스템 프롬프트 주입, 커스텀 툴(dispatch/verdict) 핸들러는 in-process MCP 로 이쪽
프로세스에서 실행, 커맨드·쓰기·토큰은 이벤트 스트림 관찰로 집계. 인증은 CLI 해석 그대로
(구독 keychain → CLAUDE_CODE_OAUTH_TOKEN → ANTHROPIC_API_KEY) — Asgard 는 키를 만지지 않는다.

주의: 구독 인증은 개인 사용 한정 (Anthropic ToS — 제3자 서비스에 구독 로그인 제공 금지).
"""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass

# Claude Code 내장 툴 중 노출 셋 — 네이티브 트랜스포트(bash+editor) 대응 + 읽기 계열.
# 미포함 툴(WebSearch/Task 등)은 컨텍스트에서 제거된다 (tools=availability 계층).
BUILTIN_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")


@dataclass(frozen=True)
class ClaudeNativeClient:
    """make_client 반환용 마커 — 실제 호출은 Agent SDK 가 CLI 를 스폰. 존재 확인만 담당."""

    cli_path: str


def make_native_client() -> ClaudeNativeClient:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError as e:
        raise RuntimeError("claude-agent-sdk 미설치 — asgard update (또는 uv tool install asgard --force)") from e
    path = shutil.which("claude")
    if not path:
        raise RuntimeError(
            "claude CLI 없음 — https://claude.com/claude-code 설치 후 claude /login (구독) 또는 키 export"
        )
    return ClaudeNativeClient(cli_path=path)


def _bridge_tool(sess, spec: dict, result):
    """Asgard 커스텀 툴(dict 스키마 + sync 핸들러) → SDK in-process MCP 툴.

    핸들러는 sync(딜리버리 세션 스폰 등 장시간 블로킹 가능) — to_thread 로 돌려
    SDK 리더 루프(제어 프로토콜)를 막지 않는다.
    """
    from claude_agent_sdk import tool

    name = spec["name"]
    handler = sess.handlers[name]

    @tool(name, spec.get("description", ""), spec["input_schema"])
    async def _run(args: dict):
        inp = dict(args)
        result.tool_calls.append({"name": name, "input": inp})
        try:
            out = await asyncio.to_thread(handler, inp)
            return {"content": [{"type": "text", "text": out}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"tool crashed: {e}"}], "is_error": True}

    return _run


def run(sess, user_content: str):
    """AgentSession.run 의 claude_cli 분기 본체. sess = AgentSession (session.py)."""
    from .session import SessionResult

    result = SessionResult(text="", stop_reason="")
    sess.messages.append({"role": "user", "content": user_content})  # 관찰용 — 전송 히스토리는 CLI 세션 소유
    asyncio.run(_run_async(sess, user_content, result))
    if result.text:
        sess.messages.append({"role": "assistant", "content": result.text})
    return result


async def _run_async(sess, user_content: str, result) -> None:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
        create_sdk_mcp_server,
        query,
    )

    from ..i18n import t as _t

    custom = [tl for tl in sess.tools if "input_schema" in tl]  # bash/editor 는 스키마리스 내장 — 제외
    mcp_servers: dict = {}
    allowed = list(BUILTIN_TOOLS)
    if custom:
        mcp_servers["asgard"] = create_sdk_mcp_server(
            name="asgard", version="1.0.0", tools=[_bridge_tool(sess, tl, result) for tl in custom]
        )
        allowed.append("mcp__asgard__*")

    options = ClaudeAgentOptions(
        system_prompt=sess.system,
        cwd=sess.root,
        model=sess.rp.model or None,
        tools=list(BUILTIN_TOOLS),
        allowed_tools=allowed,
        permission_mode="bypassPermissions",  # 네이티브 트랜스포트(무제한 bash)와 동등 자율성
        max_turns=sess.max_iterations,
        mcp_servers=mcp_servers,
        resume=getattr(sess, "_claude_session_id", None),  # 두 번째 run() 부터 같은 CLI 세션 이어가기
    )

    pending: dict[str, tuple[str, str, float, int]] = {}  # tool_use_id → (sym, detail, t0, cmd_idx)
    sess.on_status(_t("thinking"))
    t0 = time.monotonic()
    first = True
    async for msg in query(prompt=user_content, options=options):
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    if first:
                        first = False
                        sess.on_status(None)
                        gap = time.monotonic() - t0
                        if gap >= 2:
                            sess._thought_line(gap)
                    result.text = b.text  # anthropic 트랜스포트와 동일 — 마지막 어시스턴트 텍스트가 남는다
                    sess.on_text(b.text)
                elif isinstance(b, ToolUseBlock):
                    _observe_use(sess, result, b, pending)
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for b in msg.content:
                if isinstance(b, ToolResultBlock):
                    _observe_result(sess, result, b, pending)
        elif isinstance(msg, ResultMessage):
            sess._claude_session_id = msg.session_id
            u = msg.usage or {}
            result.tokens += (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
            result.stop_reason = {
                "success": "end_turn",
                "error_max_turns": "max_iterations",
            }.get(msg.subtype, msg.subtype)
            if msg.result and not result.text:
                result.text = msg.result
    sess.on_status(None)


def _observe_use(sess, result, b, pending) -> None:
    """ToolUseBlock 관찰 → 커맨드/쓰기 추적 준비. 실행은 CLI 안 — 여기선 기록만."""
    from ..i18n import t as _t

    if b.name == "Bash":
        cmd = str(b.input.get("command", ""))
        sess.on_status("$ " + cmd[:60])
        result.commands.append({"cmd": cmd[:200], "exit_code": 0})  # 결과 블록에서 is_error 로 보정
        pending[b.id] = ("$", cmd, time.monotonic(), len(result.commands) - 1)
    elif b.name in _WRITE_TOOLS:
        path = str(b.input.get("file_path", ""))
        sess.on_status("✎ " + path[:60])
        pending[b.id] = ("✎", f"{b.name.lower()} {path}", time.monotonic(), -1)
    elif b.name.startswith("mcp__asgard__"):
        sess.on_status("⚙ " + b.name.removeprefix("mcp__asgard__"))
    else:  # Read/Glob/Grep 등 읽기 계열 — 상태만
        sess.on_status(_t("thinking"))


def _observe_result(sess, result, b, pending) -> None:
    """ToolResultBlock 관찰 → 활동 라인 + exit_code 근사(is_error) + 쓰기 확정."""
    sym, detail, t0, cmd_idx = pending.pop(b.tool_use_id, ("", "", 0.0, -1))
    if not sym:
        return
    sess.on_status(None)
    sess._tool_line(sym, detail, time.monotonic() - t0)
    if cmd_idx >= 0 and b.is_error:
        result.commands[cmd_idx]["exit_code"] = 1  # CLI 는 exit code 미노출 — is_error 로 근사
    if sym == "✎" and not b.is_error:
        path = detail.split(" ", 1)[1] if " " in detail else detail
        if path and path not in result.writes:
            result.writes.append(path)


def complete_text(system: str, user: str, model: str = "", root: str | None = None) -> str:
    """비스트리밍 단발 completion — heimdall._complete_text 의 claude_cli 대응 (툴 전부 제거, 1턴)."""

    async def _go() -> str:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        options = ClaudeAgentOptions(
            system_prompt=system,
            model=model or None,
            tools=[],  # 내장 툴 전부 제거 — 순수 텍스트 완성
            max_turns=1,
            cwd=root,
        )
        async for msg in query(prompt=user, options=options):
            if isinstance(msg, ResultMessage):
                return msg.result or ""
        return ""

    return asyncio.run(_go())
