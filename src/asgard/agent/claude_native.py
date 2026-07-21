"""claude_cli 트랜스포트 — 로컬 claude CLI(Claude Code)를 Agent SDK 로 구동.

anthropic/openai_compat 과 달리 내부 루프를 Claude Code 하네스가 소유한다. Asgard 계약은
유지: 시스템 프롬프트 주입, 커스텀 툴(dispatch/verdict) 핸들러는 in-process MCP 로 이쪽
프로세스에서 실행, 커맨드·쓰기·토큰은 이벤트 스트림 관찰로 집계. 인증은 CLI 해석 그대로
(구독 keychain → CLAUDE_CODE_OAUTH_TOKEN → ANTHROPIC_API_KEY) — Asgard 는 키를 만지지 않는다.

주의: 구독 인증은 개인 사용 한정 (Anthropic ToS — 제3자 서비스에 구독 로그인 제공 금지).

밴/차단 방어 독트린 (2026-07 리서치 — 차단은 '클라이언트 진위' 기준):
  1. 토큰 불추출 — keychain/credentials 값을 절대 안 읽는다 (감지는 존재 확인만). #1 차단 트리거.
  2. 클라이언트 무변조 — 스톡 바이너리, 헤더/UA 불변, 텔레메트리 유지 (끄면 '무텔레메트리 이상 트래픽' 지문).
  3. 프록시 금지 — 구독 인증 시 base_url(config)·ANTHROPIC_BASE_URL(env) 차단/무력화 (OpenCode 차단 벡터).
  4. 동시성 상한 — CLI 세션 세마포어 (기본 3, ASGARD_CLAUDE_MAX_CONCURRENT). 서브에이전트 툴(Task) 미노출.
  5. 하드캡 존중 — "You've hit your … limit" 감지 시 UsageCapError(fatal) — 재시도로 캡을 두드리지 않는다.
     일시 스로틀("not your usage limit")은 CLI 내장 백오프에 위임 (자체 재시도 루프 금지).
"""

from __future__ import annotations

import asyncio
import hashlib
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

# ── 밴/차단 방어 ──────────────────────────────────────────────
# 동시 CLI 세션 상한 — 구독 트래픽 폭주(다중 병렬 에이전트) 방지. Heimdall 딜리버리
# 웨이브(≤3 병렬)까지 수용하되 그 이상은 직렬화. env ASGARD_CLAUDE_MAX_CONCURRENT 로 조정.
_MAX_CONCURRENT = max(1, int(os.environ.get("ASGARD_CLAUDE_MAX_CONCURRENT", "3") or 3))
_spawn_gate = threading.BoundedSemaphore(_MAX_CONCURRENT)
# 턴 wall-clock 상한 — CLI 행(hang) 시 영구 블록 방지 (CUS-246). 정상 장기 턴(대형 구현)을
# 죽이지 않게 기본 1시간. permit 대기에도 같은 상한 — 행 세션이 permit 을 안 놓는 경우 방어.
_TURN_TIMEOUT_S = max(60.0, float(os.environ.get("ASGARD_CLAUDE_TURN_TIMEOUT_S", "3600") or 3600))

# ── 단일 데몬 이벤트 루프 ─────────────────────────────────────
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


def _submit(coro, timeout: float | None = None):
    """코루틴을 데몬 루프에 제출하고 완료까지 블록 (asyncio.run 대체).

    timeout 초과 시 future 취소(_drained finally 가 CLI subprocess 정리) 후 TimeoutError —
    classify_api_error 가 이름 기반 retryable 로 분류해 새 세션 재시도로 이어진다."""
    fut = asyncio.run_coroutine_threadsafe(coro, _bg_loop())
    try:
        return fut.result(timeout)
    except TimeoutError:
        if fut.done():  # 코루틴 자신이 던진 TimeoutError — 대기 초과 아님, 그대로 표면화
            raise
        fut.cancel()
        raise TimeoutError(
            f"claude CLI 턴 {timeout:.0f}s 초과 — 행 의심, 취소 후 재시도 (ASGARD_CLAUDE_TURN_TIMEOUT_S 로 조정)"
        ) from None


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
    ):  # macOS 는 keychain 저장 — 존재 여부만 (값 조회 금지). os.uname 은 유닉스 전용이라 금지
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

    @tool(name, spec.get("description", ""), spec["input_schema"])
    async def _run(args: dict):
        from .session import _Call

        inp = dict(args)
        out, is_error = await asyncio.to_thread(sess._execute, _Call("mcp", name, inp), result)
        response: dict[str, object] = {"content": [{"type": "text", "text": out}]}
        if is_error:
            response["is_error"] = True
        return response

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
        if getattr(sess, "_nested_dispatch", False):
            # 딜리버리 디스패치 자식 — 부모 worker 가 permit 을 쥔 채 이 결과를 기다린다.
            # 여기서 permit 을 재요구하면 재진입 데드락 (CUS-246): 병렬 worker 3개가 permit
            # 3개를 전부 점유한 채 자식 3개가 영구 대기. 자식 동시성은 부모 웨이브(≤3)에 유계.
            _submit(_run_async(sess, user_content, result), timeout=_TURN_TIMEOUT_S)
        else:
            if not _spawn_gate.acquire(timeout=_TURN_TIMEOUT_S):  # 동시 CLI 세션 상한 — 초과분은 직렬 대기
                raise TimeoutError(
                    f"CLI 세션 슬롯 대기 {_TURN_TIMEOUT_S:.0f}s 초과 — 행 세션 의심 "
                    "(ASGARD_CLAUDE_MAX_CONCURRENT / ASGARD_CLAUDE_TURN_TIMEOUT_S 확인)"
                )
            try:
                _submit(_run_async(sess, user_content, result), timeout=_TURN_TIMEOUT_S)  # 데몬 루프 재사용
            finally:
                _spawn_gate.release()
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
        HookMatcher,
        ResultMessage,
        StreamEvent,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
        create_sdk_mcp_server,
        query,
    )
    from claude_agent_sdk.types import HookContext, HookInput, HookJSONOutput

    from ..hooks.readonly_guard import READONLY_BASH_HINT, is_readonly_bash_safe
    from ..i18n import t as _t
    from . import tools as native_tools
    from .tool_kernel import ROLE_CAPABILITIES

    custom = [tl for tl in sess.tools if "input_schema" in tl]  # bash/editor 는 스키마리스 내장 — 제외
    mcp_servers: dict = {}
    # Explicit readonly and canonical role policy both constrain SDK built-ins.
    # A mismatched caller cannot turn Verifier into a writer by omitting readonly=True.
    can_mutate = "mutate" in ROLE_CAPABILITIES.get(sess.role, frozenset()) and not getattr(sess, "readonly", False)
    builtin = [t for t in BUILTIN_TOOLS if can_mutate or t not in _WRITE_TOOLS]
    allowed = list(builtin)
    if custom:
        mcp_servers["asgard"] = create_sdk_mcp_server(
            name="asgard", version="1.0.0", tools=[_bridge_tool(sess, tl, result) for tl in custom]
        )
        allowed.append("mcp__asgard__*")

    denied_tool_ids: set[str] = set()
    sess._denied_tool_ids = denied_tool_ids  # _observe_result 가 차단 증거를 실행 실패와 구분한다

    async def _canonical_tool_guard(
        hook_input: HookInput, tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        tool_name = str(hook_input.get("tool_name") or "")
        tool_input = hook_input.get("tool_input") or {}
        command = str(tool_input.get("command") or "")
        reason = native_tools.validate_bash_command(sess.cwd, command) if tool_name == "Bash" else None
        if tool_name == "Bash" and getattr(sess, "_readonly_unisolated", False):
            reason = "read-only Bash requires an isolated Git workspace"
        path = str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path") or "")
        if path:
            project = os.path.realpath(sess.cwd)
            candidate = os.path.realpath(
                os.path.expanduser(path) if path.startswith(("~", "/")) else os.path.join(project, path)
            )
            try:
                escaped = os.path.commonpath((project, candidate)) != project
            except ValueError:
                escaped = True
            if escaped:
                reason = f"tool path escapes Asgard project: {path}"
        role_denied = not can_mutate and (
            tool_name in _WRITE_TOOLS or (tool_name == "Bash" and not is_readonly_bash_safe(command, sess.cwd))
        )
        if reason or role_denied:
            if tool_use_id:
                denied_tool_ids.add(tool_use_id)
            if not reason:
                # 사유 없는 차단은 모델이 같은 명령의 변형으로 턴을 태우게 한다 — 허용 레인을 가르친다
                reason = "Asgard read-only 역할 정책 차단 — " + (
                    READONLY_BASH_HINT
                    if tool_name == "Bash"
                    else "파일 수정 도구는 이 역할에서 금지다. 관측·검증 명령과 판정 제출만 하라."
                )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        return {}

    hooks: dict = {
        "PreToolUse": [
            HookMatcher(matcher="Bash|Read|Grep|Glob|Write|Edit|NotebookEdit", hooks=[_canonical_tool_guard])
        ]
    }

    options = ClaudeAgentOptions(
        system_prompt=sess.system,
        cwd=sess.cwd,
        model=sess.rp.model or None,
        tools=builtin,
        allowed_tools=allowed,
        permission_mode="bypassPermissions",  # 네이티브 트랜스포트(무제한 bash)와 동등 자율성
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
        },
        max_turns=sess.max_iterations,
        mcp_servers=mcp_servers,
        # 유저/프로젝트 MCP 설정(~/.claude.json, .mcp.json) 차단 — Asgard 가 툴 표면을 소유한다.
        # 없으면 무관 유저 MCP 가 역할 세션에 노출 (bypassPermissions 라 실사용 가능)
        # + classify 가 툴 호출을 시도해 max_turns(1) 초과로 전량 fallback (t1 4/4 실측).
        strict_mcp_config=True,
        # SDK 기본(None)은 ~/.claude와 project/local settings·hooks·skills를 전부 로드한다.
        # Asgard child는 role prompt/tool surface를 하니스가 소유하므로 ambient 확장을 봉인한다.
        setting_sources=[],
        skills=[],
        hooks=hooks,
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
    streamed_text = ""  # 일부 CLI 경로는 최종 AssistantMessage 없이 델타만 보낸다.
    gen = query(prompt=user_content, options=options)
    async for msg in _drained(gen):
        if sess.cancel_event.is_set():
            # 협조적 취소 — break 가 _drained finally 의 gen.aclose() 를 부르고, SDK 가
            # CLI subprocess 를 정리한다. 취소 결과는 Heimdall 이 TurnCancelled 로 승격.
            result.stop_reason = "cancelled"
            break
        if isinstance(msg, StreamEvent):
            d = msg.event.get("delta") or {}
            if msg.event.get("type") == "message_start":
                streamed_text = ""
                streamed = False
            elif msg.event.get("type") == "content_block_delta" and d.get("type") == "text_delta" and d.get("text"):
                streamed = True
                streamed_text += d["text"]
                # SDK 2.1.x 실측: 최종 AssistantMessage/TextBlock가 생략될 수 있다. 델타도
                # SessionResult의 정본으로 누적해 headless/JSON 결과가 빈 문자열이 되지 않게 한다.
                result.text = streamed_text
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
                    if b.text:
                        # SDK가 델타 뒤 빈 TextBlock을 보낼 수 있다. 이미 누적한 최종 텍스트를
                        # 빈 블록으로 지우지 않는다.
                        result.text = b.text  # anthropic 트랜스포트와 동일 — 마지막 어시스턴트 텍스트
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
            # Claude Code 가 자체적으로 프롬프트 캐싱을 적용한다 — 주입 불필요, 계측만 패리티.
            # 캐시 적중분은 input_tokens 에서 빠지므로 합산 안 하면 지출·적중률이 전부 누락된다.
            u = msg.usage or {}
            inp = u.get("input_tokens") or 0
            cr = u.get("cache_read_input_tokens") or 0
            cw = u.get("cache_creation_input_tokens") or 0
            result.tokens += inp + cr + cw + (u.get("output_tokens") or 0)
            result.cache_read_tokens += cr
            result.cache_write_tokens += cw
            result.uncached_input_tokens += inp
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
    """query async generator 를 소비하고 finally 에서 명시적으로 닫는다.

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
    from .. import ui as _ui
    from ..i18n import t as _t

    if b.name == "Bash":
        cmd = str(b.input.get("command", ""))
        sess.on_status(_ui.oneline("$ " + cmd, 60))
        command = {"cmd": cmd[:200], "exit_code": None}
        if len(cmd) > 200:
            command["command_hash"] = hashlib.sha256(cmd.encode()).hexdigest()
        result.commands.append(command)  # 결과 블록이 와야만 증거로 승격
        pending[b.id] = ("$", cmd, time.monotonic(), len(result.commands) - 1)
    elif b.name in _WRITE_TOOLS:
        path = str(b.input.get("file_path", ""))
        sess.on_status(_ui.oneline("✎ " + path, 60))
        pending[b.id] = ("✎", f"{b.name.lower()} {path}", time.monotonic(), -1)
    elif b.name.startswith("mcp__asgard__"):
        sess.on_status("⚙ " + b.name.removeprefix("mcp__asgard__"))
    else:  # Read/Glob/Grep 등 읽기 계열 — executable verification evidence 는 아님
        sess.on_status(_t("thinking"))


def _observe_result(sess, result, b, pending) -> None:
    """ToolResultBlock 관찰 → 활동 라인 + exit_code 근사(is_error) + 쓰기 확정."""
    sym, detail, t0, cmd_idx = pending.pop(b.tool_use_id, ("", "", 0.0, -1))
    if not sym:
        return
    sess.on_status(None)
    failed = bool(b.is_error)
    blocked = b.tool_use_id in getattr(sess, "_denied_tool_ids", ())
    sess._tool_line(
        "✕" if failed else sym, detail + (" — 차단" if blocked else " — 실패" if failed else ""), time.monotonic() - t0
    )
    if cmd_idx >= 0:
        # CLI 는 exit code 미노출 — is_error 로 근사. 가드가 차단한 호출은 실행된 적이 없으므로
        # 증거에서 제외 표식 (커널 경로의 blocked 미기록과 패리티 — 미해소 실패 오판 방지).
        result.commands[cmd_idx]["exit_code"] = 1 if b.is_error else 0
        if blocked:
            result.commands[cmd_idx]["blocked"] = True
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
            setting_sources=[],
            skills=[],
            max_turns=1,
            cwd=root,
            env=_guard_env(),
        )
        out = ""
        async for msg in _drained(query(prompt=user, options=options)):
            if isinstance(msg, ResultMessage):
                out = msg.result or ""
        return out

    if not _spawn_gate.acquire(timeout=_TURN_TIMEOUT_S):  # classify 도 CLI 스폰 — 동시성 상한 공유
        raise TimeoutError(f"CLI 세션 슬롯 대기 {_TURN_TIMEOUT_S:.0f}s 초과 — 행 세션 의심")
    try:
        return _submit(_go(), timeout=_TURN_TIMEOUT_S)  # 데몬 루프 재사용
    finally:
        _spawn_gate.release()
