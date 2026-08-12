"""AgentSession — 한 턴의 생애. 트랜스포트별 루프는 믹스인 셋이 나눠 진다.

여기 남은 것은 트랜스포트가 공유하는 것뿐이다: 도구 등록부와 스키마 동결, 활동 라인·상태
신호, 협조적 취소, 툴 실행, 저널 기록, 그리고 `run` 이 고르는 분기. 믹스인인 이유는 그
루프들이 전부 같은 세션 상태(`self.messages`·`self.tools`·`self.cancel_event`)를 읽고 쓰기
때문이다 — 협력 객체로 뽑으려면 그 상태를 먼저 갈라야 하고, 그것은 이 분해가 답할 질문이
아니다."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from typing import Callable

from ...io_journal import call_returned, call_started
from ...memory.fence import FenceScrubber
from ...providers import ResolvedProvider
from ..tool_kernel import ToolContext, build_session_registry, execute_tool
from .chat import _ChatMixin
from .compress import _CompressionMixin
from .messages import _MessagesMixin
from .responses import _ResponsesMixin
from .types import SessionResult, _Call


class AgentSession(_CompressionMixin, _MessagesMixin, _ChatMixin, _ResponsesMixin):
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
        cwd: str | None = None,
        readonly_paths: list[str] | tuple[str, ...] = (),
        cancel_event: threading.Event | None = None,
        on_lifecycle: Callable[[str, str], None] | None = None,
        on_tool: Callable[[str, dict], None] | None = None,
        agent: str | None = None,
    ):
        self.client, self.rp, self.root, self.system = client, rp, root, system
        # 이 세션을 도는 에이전트 (에인헤랴르 id). None = 활성 에이전트 그대로.
        # 스웜에서 역할마다 다른 에이전트를 세우면 여기 이름이 박히고, run()이 그 홈으로
        # 스코프를 열어 **턴 안의 메모리 도구까지** 그 에이전트의 1차 기억을 쓴다.
        # 생성자에서 스코프를 열어봐야 소용없다 — 툴 호출은 run() 안에서 일어난다.
        self.agent = agent or None
        # root는 Quest/journal/config의 canonical 소유자, cwd는 도구와 provider subprocess의 실행 공간.
        # 기본값은 기존 동작과 동일하다.
        self.cwd = os.path.abspath(cwd or root)
        self._explicit_cwd = cwd is not None
        self._readonly_workspace = None
        self._readonly_unisolated = False
        self.readonly_paths = tuple(str(path) for path in readonly_paths)
        # readonly = 역할→도구 구조 강제 (thinker/verifier/loki) — editor write 거부.
        # lagom: bash 리다이렉션 write는 못 막는다 — 남는 흔적은 게이트(diff/orphan-write)가 잡는다.
        self.readonly = readonly
        self.role = role or ("readonly" if readonly else "legacy")
        self.handlers = tool_handlers or {}
        self.registry = build_session_registry(extra_tools, self.handlers)
        # 세션 중 schema를 동결해 prompt cache key와 실제 호출 가능 표면을 일치시킨다.
        self.tools = self.registry.schemas(ToolContext(root=self.cwd, role=self.role, readonly=self.readonly))
        self.on_text = on_text or (lambda s: None)
        # 모델이 되뱉은 메모리 펜스를 표면에 닿기 전에 제거한다. 델타를 가로질러 쪼개진
        # 태그는 정규식으로 못 잡으므로 상태기계를 턴 내내 들고 간다 (memory.fence).
        self._fence = FenceScrubber()
        # 라이브 상태 신호 — 침묵 구간(thinking·툴 실행)에 스피너 등을 띄울 훅. None = 해제.
        self.on_status = on_status or (lambda s: None)
        self.on_tokens = on_tokens
        # 턴 recap 수집 훅 — 부모(Heimdall)가 턴 단위 툴 사용을 집계 (None = 무집계)
        self.on_tool = on_tool
        self.max_iterations = max_iterations
        # 협조적 취소 — 부모(Heimdall)가 이벤트를 공유하면 디스패치 자식까지 한 신호로 중단된다.
        # 검사 지점: iteration 경계·스트림 청크·툴 배치 사이. 히스토리는 항상 API-유효 상태로 닫는다.
        self.cancel_event = cancel_event or threading.Event()
        self.on_lifecycle = on_lifecycle or (lambda _event, _detail: None)
        self.messages: list[dict] = []
        self._codex_session_id = uuid.uuid4().hex
        self._codex_reasoning_replay_enabled = True
        # 딜리버리 디스패치 자식 마커 — claude_cli에서 부모가 spawn permit을 쥔 채 기다리므로
        # 자식은 permit을 재요구하지 않는다 (재진입 데드락, CUS-246). _dispatch_handler가 켠다.
        self._nested_dispatch = False
        # 프롬프트 캐싱 (anthropic 전용, 상시 기본) — config [cache] enabled/ttl, 세션 생성 시 1회 해석
        from ..prompt_cache import cache_settings

        self.cache_enabled, self.cache_ttl = cache_settings(root)

    def _tool_line(self, sym: str, detail: str, secs: float | None = None) -> None:
        """활동 라인 — HAIRLINE │ 거터 아래 sym+요약+소요시간 (완료 후 출력, 전부 흐리게).
        역할 배너 아래 툴들을 시각적으로 묶는 세로 스레드 (프레이야 정보위계)."""
        from ... import theme, ui

        dur = f" · {secs:.0f}s" if secs is not None and secs >= 1 else ""
        budget = max(12, ui.stream_width() - 6 - len(dur))  # col6 시작 + dur 여유
        # 히어독·python -c 멀티라인 명령이 행마다 스트림 줄로 흩어지지 않게 단일 행으로 접는다
        text = ui.oneline(detail, budget)
        gutter = ui.paint(theme.ansi(theme.HAIRLINE), "│")
        self.on_text(f"  {gutter} {ui.dim(sym + ' ' + text + dur)}\n")

    def _tool_preview(self, name: str, args: dict) -> tuple[str, str]:
        """Provider-neutral one-line tool label for the live status and scrollback."""
        tool = name.removeprefix("mcp__asgard__")
        key = tool.lower()
        path = str(args.get("file_path") or args.get("path") or args.get("notebook_path") or "")
        if key == "bash":
            return "$", str(args.get("command") or "shell")
        if key == "str_replace_based_edit_tool":
            op = str(args.get("command") or "edit")
            return ("→" if op == "view" else "✎"), f"{op} {path}".strip()
        if key == "read":
            return "→", f"read {path}".strip()
        if key in {"write", "edit", "notebookedit"}:
            return "✎", f"{key} {path}".strip()
        if key in {"glob", "grep"}:
            pattern = str(args.get("pattern") or "")
            where = f" in {path}" if path else ""
            return "✱", f'{key} "{pattern}"{where}'
        if key == "read_document":
            return "→", f"read document {path}".strip()
        if key in {"web_fetch", "webfetch"}:
            return "%", str(args.get("url") or "web fetch")
        if key == "process":
            action = str(args.get("action") or "process")
            target = args.get("command") if action == "start" else args.get("process_id")
            return "▶", f"{action} {target or ''}".strip()
        if key == "apply_patch":
            return "✎", "apply patch"
        if key in {"load_skill", "skill"}:
            return "◇", f"load skill {args.get('name') or ''}".strip()
        if key == "memory_save":
            return "◆", "save memory"
        if key.startswith("dispatch"):
            agent = str(args.get("agent") or key.removeprefix("dispatch_").removesuffix("_squad"))
            task = str(args.get("task") or "")
            return "↗", " · ".join(part for part in (agent, task) if part)
        if key in {"verdict", "submit_visual_verdict"}:
            return "✓", key.replace("_", " ")
        return "⚙︎", tool

    def _observe_tool(self, name: str, args: dict) -> None:
        """Best-effort turn activity hook shared by every provider transport."""
        if self.on_tool is not None:
            try:
                self.on_tool(name, dict(args))
            except Exception:
                pass

    def _thought_line(self, secs: float) -> None:
        """thinking 원문 대신 축약 한 줄 — '│ ⋯ 룬 해독 3s' (스레드 아래 사고층)."""
        from ... import activity, theme, ui
        from ...i18n import t

        gutter = ui.paint(theme.ansi(theme.HAIRLINE), "│")
        label = t("thought")
        # 사고도 활동이다. 이 줄이 없으면 창에서는 모델이 오래 생각하는 구간이 통째로 정적이라,
        # 멈춘 것과 구분이 안 된다 (레퍼런스들이 8~10초 뒤 '아직 일하는 중' 줄을 넣는 이유).
        activity.emit("thought", role=self.role, secs=round(secs, 1), label=label)
        self.on_text(f"  {gutter} {ui.dim(f'⋯ {label} {secs:.0f}s')}\n")

    def _throttle(self) -> None:
        """RPM 상한 provider(NVIDIA NIM 무료 40rpm 등) — API 호출 직전 슬롯 대기.
        무상한 provider는 no-op. 대기가 길어지면 흐린 한 줄로 정직하게 알린다."""
        from ..rate_limit import limiter_for

        lim = limiter_for(self.rp)
        if lim is None:
            return
        waited = lim.acquire(self.cancel_event)
        if waited >= 1:
            self._tool_line("⏳", f"rpm {lim.rpm} 상한 대기 ({self.rp.profile.name})", waited)

    def cancel(self) -> None:
        """협조적 취소 요청 — 다음 안전 지점(청크/툴/iteration 경계)에서 턴이 멈춘다."""
        self.cancel_event.set()

    def _cancelled(self) -> bool:
        return self.cancel_event.is_set()

    # ── 툴 실행 (트랜스포트 공유) — (output, is_error) ──────────────────
    def _execute(self, call: _Call, result: SessionResult) -> tuple[str, bool]:
        if self._readonly_unisolated and call.name == "bash":
            return "read-only Bash requires an isolated Git workspace", True
        ctx = ToolContext(
            root=self.cwd,
            role=self.role,
            readonly=self.readonly,
            writes=result.writes,
            commands=result.commands,
            tool_calls=result.tool_calls,
            cancel=self.cancel_event,
        )
        sym, detail = self._tool_preview(call.name, call.input)
        self._observe_tool(call.name, call.input)
        from ... import activity, ui

        # 표시 폭 절단은 렌더 계층(독 _status_str·ui.spin)이 터미널 폭 기준으로 담당 —
        # 여기서 좁게 자르면 실행 중인 명령 전문 가독이 죽는다. 폭주 방어 상한만 건다.
        self.on_status(ui.oneline(f"{sym} {detail}", 240))
        # 창은 터미널과 **같은 어휘**로 본다. 여기서 만든 (기호, 한 줄)은 독의 상태 행이 쓰는
        # 바로 그 값이라, 두 표면이 같은 순간에 같은 문장을 말한다 — 창 전용 문구를 따로
        # 지으면 둘이 갈리고, 갈린 뒤엔 어느 쪽이 정본인지 아무도 모른다.
        activity.emit(
            "tool.start",
            id=call.id,
            role=self.role,
            agent=self.agent,
            name=call.name,
            sym=sym,
            detail=ui.oneline(detail, 240),
        )
        t0 = time.monotonic()
        out = execute_tool(self.registry, call.name, call.input, ctx)
        secs = time.monotonic() - t0
        self.on_status(None)
        activity.emit("tool.end", id=call.id, role=self.role, ok=not out.is_error, secs=round(secs, 1))
        self._tool_line(
            "✕" if out.is_error else sym,
            detail + (" — 실패" if out.is_error else ""),
            secs,
        )
        return out.content, out.is_error

    # ── 진입점 ──────────────────────────────────────────────────────────
    def _journal_started(self, transport: str) -> tuple[str | None, float]:
        jid = call_started(
            self.root, provider=self.rp.profile.name, model=self.rp.model, transport=transport, role=self.role
        )
        return jid, time.monotonic()

    def _journal_error(self, jid: str | None, t0: float, e: Exception) -> None:
        call_returned(self.root, jid, duration_ms=(time.monotonic() - t0) * 1000, error=f"{type(e).__name__}: {e}")

    def emit_text(self, text: str) -> None:
        """모델 본문 델타 전용 출구 — 펜스를 제거한 부분만 표면으로 보낸다.

        상태선(_tool_line 등)은 여기를 안 탄다: 우리가 만든 문자열이라 걸러낼 것이 없고,
        같은 상태기계를 공유하면 모델 델타의 미완 태그 판정이 엉킨다."""
        if visible := self._fence.feed(text):
            self.on_text(visible)

    def _fence_tail(self) -> None:
        """스트림 종료 — 붙잡아 둔 꼬리를 흘려보낸다 (미종료 블록이면 버려진다)."""
        if tail := self._fence.flush():
            self.on_text(tail)

    def run(self, user_content: str) -> SessionResult:
        """턴 실행 — 이 세션에 에이전트가 박혀 있으면 그 에이전트의 홈으로 스코프를 열고 돈다.

        스코프를 **여기서** 여는 이유: 메모리 회수·저장은 턴 안의 툴 호출이라 생성자 시점의
        스코프는 이미 닫혀 있다. contextvar라 스레드/태스크마다 독립적이므로, 역할 셋을
        병렬로 돌려도 서로의 홈을 덮어쓰지 않는다 (환경변수였다면 덮어쓴다)."""
        if not self.agent:
            return self._run(user_content)
        from ...profiles import scoped

        with scoped(self.agent):
            return self._run(user_content)

    def _run(self, user_content: str) -> SessionResult:
        outcome = "failed"
        self._fence.reset()  # 턴 경계 — 이전 턴의 미완 상태가 이번 턴을 삼키지 않는다
        if self.readonly and not self._explicit_cwd:
            from ..unit_workspace import UnitWorkspace, WorkspaceError

            try:
                workspace = UnitWorkspace(
                    self.root,
                    f"readonly-{os.getpid()}-{id(self)}",
                    include_ignored=self.readonly_paths,
                )
                workspace.__enter__()
                # Do not leave the canonical project's absolute path discoverable as a clone remote.
                subprocess.run(
                    ["git", "-C", workspace.path, "remote", "remove", "origin"],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self._readonly_workspace = workspace
                self.cwd = workspace.path
                self.tools = self.registry.schemas(ToolContext(root=self.cwd, role=self.role, readonly=True))
            except WorkspaceError:
                # Without a disposable Git clone, even a nominal test command may mutate the
                # canonical tree. Keep file-inspection tools, but remove execution entirely.
                self._readonly_workspace = None
                self._readonly_unisolated = True
                self.tools = [tool for tool in self.tools if tool.get("name") not in {"bash", "process"}]
        self.on_lifecycle("running", "")
        try:
            if self.rp.profile.api_mode == "claude_cli":
                from .. import claude_native

                # claude_cli는 내부 루프를 Claude Code가 소유 — 저널은 run 전체를 한 호출로 기록
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
            elif self.rp.profile.api_mode in {"openai_responses", "codex_responses"}:
                r = self._run_responses(user_content)
            else:
                r = self._run_openai(user_content)
            outcome = r.stop_reason or "done"
        finally:
            self.on_lifecycle("finished", outcome)
            self.on_status(None)
            self.registry.close()
            if self._readonly_workspace is not None:
                self._readonly_workspace.__exit__(None, None, None)
                self._readonly_workspace = None
        if self.on_tokens and r.tokens:
            self.on_tokens(r.tokens)
        return r
