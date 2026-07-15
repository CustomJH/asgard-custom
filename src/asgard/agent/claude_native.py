"""claude_cli 트랜스포트 — 로컬 claude CLI(Claude Code)를 Agent SDK 로 구동.

anthropic/openai_compat 과 달리 내부 루프를 Claude Code 하네스가 소유한다. Asgard 계약은
유지: 시스템 프롬프트 주입, 커스텀 툴(dispatch/verdict) 핸들러는 in-process MCP 로 이쪽
프로세스에서 실행, 커맨드·쓰기·토큰은 이벤트 스트림 관찰로 집계. 인증은 CLI 해석 그대로
(구독 keychain → CLAUDE_CODE_OAUTH_TOKEN → ANTHROPIC_API_KEY) — Asgard 는 키를 만지지 않는다.

주의: 구독 인증은 개인 사용 한정 (Anthropic ToS — 제3자 서비스에 구독 로그인 제공 금지).

밴/차단 방어 독트린 (CUS-191, 2026-07 리서치 — 차단은 '클라이언트 진위' 기준):
  1. 토큰 불추출 — keychain/credentials 값을 절대 안 읽는다 (감지는 존재 확인만). #1 차단 트리거.
  2. 클라이언트 무변조 — 스톡 바이너리, 헤더/UA 불변, 텔레메트리 유지 (끄면 '무텔레메트리 이상 트래픽' 지문).
  3. 프록시 금지 — 구독 인증 시 base_url(config)·ANTHROPIC_BASE_URL(env) 차단/무력화 (OpenCode 차단 벡터).
  4. 동시성 상한 — CLI 세션 세마포어 (기본 3, ASGARD_CLAUDE_MAX_CONCURRENT). 서브에이전트 툴(Task) 미노출.
  5. 하드캡 존중 — "You've hit your … limit" 감지 시 UsageCapError(fatal) — 재시도로 캡을 두드리지 않는다.
     일시 스로틀("not your usage limit")은 CLI 내장 백오프에 위임 (자체 재시도 루프 금지).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass

# Claude Code 내장 툴 중 노출 셋 — 네이티브 트랜스포트(bash+editor) 대응 + 읽기 계열.
# 미포함 툴(WebSearch/Task 등)은 컨텍스트에서 제거된다 (tools=availability 계층).
BUILTIN_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")

# ── 밴/차단 방어 (CUS-191) ──────────────────────────────────────────────
# 동시 CLI 세션 상한 — 구독 트래픽 폭주(다중 병렬 에이전트) 방지. Heimdall 딜리버리
# 웨이브(≤3 병렬)까지 수용하되 그 이상은 직렬화. env ASGARD_CLAUDE_MAX_CONCURRENT 로 조정.
_MAX_CONCURRENT = max(1, int(os.environ.get("ASGARD_CLAUDE_MAX_CONCURRENT", "3") or 3))
_spawn_gate = threading.BoundedSemaphore(_MAX_CONCURRENT)

# ── 단일 데몬 이벤트 루프 (CUS-192) ─────────────────────────────────────
# 매 턴 asyncio.run() 새 루프 생성/종료는 SDK subprocess child watcher·async
# generator 잔여와 충돌한다 ("aclose(): already running", "Loop … is closed").
# 프로세스 수명 동안 데몬 스레드에서 루프 하나를 돌리고 모든 코루틴을 거기 제출 —
# 루프가 안 닫히니 child watcher 도 고정, 스레드풀 병렬 딜리버리도 같은 루프 공유.
_loop = None
_loop_lock = threading.Lock()


def _bg_loop():
    global _loop
    if _loop is None:
        with _loop_lock:
            if _loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, daemon=True, name="asgard-claude-cli").start()
                _loop = loop
    return _loop


def _submit(coro):
    """코루틴을 데몬 루프에 제출하고 완료까지 블록 (asyncio.run 대체)."""
    return asyncio.run_coroutine_threadsafe(coro, _bg_loop()).result()


class UsageCapError(RuntimeError):
    """구독 사용량 한도(5시간 윈도/주간 캡) 도달 — 재시도로 뚫지 않는다 (fatal 분류)."""


def detect_auth() -> tuple[str, str]:
    """(kind, detail) — 인증 '감지'만, 토큰 값은 절대 읽지 않는다 (superset 패턴, ToS).

    kind: "api_key" | "oauth_token" | "keychain" | "unknown"
    우선순위는 CLI 해석 순서와 동일: env API 키 > env OAuth 토큰 > keychain/credentials 로그인.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api_key", "$ANTHROPIC_API_KEY — 구독이 아닌 API 과금으로 나간다"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "oauth_token", "$CLAUDE_CODE_OAUTH_TOKEN (claude setup-token)"
    cred = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    if os.path.exists(cred):
        return "keychain", "~/.claude/.credentials.json (claude /login)"
    if (
        sys.platform == "darwin"
    ):  # macOS 는 keychain 저장 — 존재 여부만 (값 조회 금지). os.uname 은 유닉스 전용이라 금지 (CUS-221)
        import subprocess

        p = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials"],
            capture_output=True,
            timeout=5,
        )
        if p.returncode == 0:
            return "keychain", "macOS Keychain (claude /login)"
    return "unknown", "감지 실패 — claude /login 또는 키 export 필요할 수 있음"


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

    if sess.rp.base_url:
        # 구독 인증 + 커스텀 엔드포인트 프록시 조합은 OpenCode류 차단 트리거 — 원천 거부.
        raise RuntimeError("claude-native 는 base_url 미지원 — 프록시+구독 조합은 차단 리스크 (config 에서 제거)")
    result = SessionResult(text="", stop_reason="")
    sess.messages.append({"role": "user", "content": user_content})  # 관찰용 — 전송 히스토리는 CLI 세션 소유
    from claude_agent_sdk import ProcessError

    try:
        with _spawn_gate:  # 동시 CLI 세션 상한 — 초과분은 직렬 대기
            _submit(_run_async(sess, user_content, result))  # 데몬 루프 재사용 (CUS-192)
    except ProcessError as e:
        if _is_usage_cap(str(e), e.stderr or ""):
            raise UsageCapError(
                f"구독 사용량 한도 도달 — 리셋까지 대기하거나 --provider anthropic (API) 로 전환. 원문: {str(e)[:200]}"
            ) from e
        raise
    if result.text:
        sess.messages.append({"role": "assistant", "content": result.text})
    return result


async def _run_async(sess, user_content: str, result) -> None:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        StreamEvent,
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
    # readonly 역할(thinker/verifier/loki)은 write 툴 자체를 뺀다 — anthropic 트랜스포트의
    # editor write 거부와 동일한 구조 강제 (프롬프트 순응 아님)
    builtin = [t for t in BUILTIN_TOOLS if not (getattr(sess, "readonly", False) and t in _WRITE_TOOLS)]
    allowed = list(builtin)
    if custom:
        mcp_servers["asgard"] = create_sdk_mcp_server(
            name="asgard", version="1.0.0", tools=[_bridge_tool(sess, tl, result) for tl in custom]
        )
        allowed.append("mcp__asgard__*")

    options = ClaudeAgentOptions(
        system_prompt=sess.system,
        cwd=sess.root,
        model=sess.rp.model or None,
        tools=builtin,
        allowed_tools=allowed,
        permission_mode="bypassPermissions",  # 네이티브 트랜스포트(무제한 bash)와 동등 자율성
        max_turns=sess.max_iterations,
        mcp_servers=mcp_servers,
        # 유저/프로젝트 MCP 설정(~/.claude.json, .mcp.json) 차단 — Asgard 가 툴 표면을 소유한다.
        # 없으면 pencil/hermes 등 무관 MCP 가 역할 세션에 노출 (bypassPermissions 라 실사용 가능)
        # + classify 가 툴 호출을 시도해 max_turns(1) 초과로 전량 fallback (CUS-194 t1 4/4 실측).
        strict_mcp_config=True,
        resume=getattr(sess, "_claude_session_id", None),  # 두 번째 run() 부터 같은 CLI 세션 이어가기
        include_partial_messages=True,  # 텍스트 델타 스트리밍 — anthropic 트랜스포트와 체감 패리티
        # BASH_MAX_TIMEOUT_MS: 네이티브 트랜스포트 120s 하드캡(tools._TIMEOUT)과 패리티 —
        # 모델이 timeout 연장(기본 최대 10분)으로 폭주 명령을 키우지 못하게 상한.
        env={"BASH_MAX_TIMEOUT_MS": "120000", **_guard_env(sess)},
    )

    pending: dict[str, tuple[str, str, float, int]] = {}  # tool_use_id → (sym, detail, t0, cmd_idx)
    sess.on_status(_t("thinking"))
    t0 = time.monotonic()
    first = True
    streamed = False  # 델타 수신 여부 — 수신 중이면 TextBlock 전체 재방출 억제 (이중 출력 방지)
    gen = query(prompt=user_content, options=options)
    async for msg in _drained(gen):
        if isinstance(msg, StreamEvent):
            d = msg.event.get("delta") or {}
            if msg.event.get("type") == "content_block_delta" and d.get("type") == "text_delta" and d.get("text"):
                streamed = True
                if first:
                    first = False
                    sess.on_status(None)
                    gap = time.monotonic() - t0
                    if gap >= 2:
                        sess._thought_line(gap)
                sess.on_text(d["text"])
        elif isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    if first:
                        first = False
                        sess.on_status(None)
                        gap = time.monotonic() - t0
                        if gap >= 2:
                            sess._thought_line(gap)
                    result.text = b.text  # anthropic 트랜스포트와 동일 — 마지막 어시스턴트 텍스트가 남는다
                    if not streamed:  # 구 CLI(델타 미지원) 폴백 — 기존 전체 블록 방출
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
            if msg.is_error and _is_usage_cap(msg.result or "", *(msg.errors or [])):
                raise UsageCapError(
                    "구독 사용량 한도 도달 — 리셋까지 대기하거나 --provider anthropic (API) 로 전환. "
                    f"원문: {(msg.result or (msg.errors or ['?'])[0])[:200]}"
                )
            if msg.result and not result.text:
                result.text = msg.result
    sess.on_status(None)


async def _drained(gen):
    """query async generator 를 소비하고 finally 에서 명시적으로 닫는다 (CUS-192).

    async for 정상 종료 후에도 SDK 는 subprocess/백그라운드 태스크를 남길 수 있어,
    루프 회수 전에 gen.aclose() 로 확정 정리 — asyncgen shutdown 잔여 경고를 없앤다.
    """
    try:
        async for msg in gen:
            yield msg
    finally:
        await gen.aclose()


# 공식 하드캡 문구 (code.claude.com/docs/en/errors): "You've hit your session|weekly|Opus limit · resets <t>"
_CAP_MARKERS = ("usage limit", "session limit", "weekly limit", "opus limit", "limit reached", "out of extra usage")


def _is_usage_cap(*texts: str) -> bool:
    joined = " ".join(t.lower() for t in texts if t)
    if "not your usage limit" in joined:  # 일시 스로틀 문구 — 캡 아님, CLI 자체 백오프가 처리
        return False
    return any(m in joined for m in _CAP_MARKERS)


def _guard_env(sess=None) -> dict:
    """구독 보호 env 오버레이 — 상속된 ANTHROPIC_BASE_URL(프록시)을 무력화.

    구독 인증 + 게이트웨이 조합은 차단 리스크(OpenCode 사례) — API 키 인증일 때만 존중.
    SDK env 는 os.environ 상속 + 오버레이라 제거 불가 → 빈 문자열로 무력화한다.
    """
    if os.environ.get("ANTHROPIC_BASE_URL") and detect_auth()[0] != "api_key":
        if sess is not None:
            from .. import ui

            sess.on_text(f"  {ui.dim('⬢ ANTHROPIC_BASE_URL 무시 — 구독 인증은 프록시 없이 직결 (차단 방지)')}\n")
        return {"ANTHROPIC_BASE_URL": ""}
    return {}


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
            strict_mcp_config=True,  # tools=[] 는 유저 MCP 를 못 막는다 — classify 순수성 보장 (t1 4/4 원인)
            max_turns=1,
            cwd=root,
            env=_guard_env(),
        )
        out = ""
        async for msg in _drained(query(prompt=user, options=options)):
            if isinstance(msg, ResultMessage):
                out = msg.result or ""
        return out

    with _spawn_gate:  # classify 도 CLI 스폰 — 동시성 상한 공유
        return _submit(_go())  # 데몬 루프 재사용 (CUS-192)
