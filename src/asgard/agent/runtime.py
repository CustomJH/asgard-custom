"""Transport-neutral Heimdall session and turn contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias

from .. import errors

if TYPE_CHECKING:
    from ..providers import ResolvedProvider


TurnOutcome: TypeAlias = Literal["completed", "attention"]


@dataclass(frozen=True, slots=True)
class TurnStarted:
    """한 턴이 실행 경계에 들어왔음을 알린다."""

    session_id: str
    prompt: str
    provider: str
    model: str
    resume: bool


@dataclass(frozen=True, slots=True)
class TurnText:
    """Heimdall이 표면으로 보낸 텍스트 조각을 전달한다."""

    session_id: str
    text: str


@dataclass(frozen=True, slots=True)
class TurnStatusChanged:
    """진행 상태 라벨의 변경을 전달한다."""

    session_id: str
    label: str | None


@dataclass(frozen=True, slots=True)
class TurnFinished:
    """한 턴의 실행 계측과 결과 상태를 알린다."""

    session_id: str
    ok: bool
    wall_s: float
    tokens: int


TurnEvent: TypeAlias = TurnStarted | TurnText | TurnStatusChanged | TurnFinished


@dataclass(frozen=True, slots=True)
class TurnResult:
    """표면 종류와 무관하게 한 Heimdall 턴이 반환하는 결과다."""

    session_id: str
    text: str
    outcome: TurnOutcome
    response_streamed: bool
    quest_id: str | None
    tokens: int
    cache_read_tokens: int
    cache_prompt_tokens: int
    wall_s: float
    provider: str
    model: str

    @property
    def ok(self) -> bool:
        return self.outcome == "completed"


PeerKind: TypeAlias = Literal["cc", "codex", "cursor"]
PEER_KINDS: tuple[str, ...] = ("cc", "codex", "cursor")
# peer 이름 → PATH 에서 찾을 실행 파일. 새 에이전트 CLI 를 붙이는 자리가 여기 한 줄이다.
PEER_BINARIES: dict[str, str] = {"cc": "claude", "codex": "codex", "cursor": "cursor-agent"}


def peers_present() -> tuple[str, ...]:
    """이 기계의 PATH 에 실제로 있는 peer CLI — 선언이 아니라 조회다.

    로그인 여부는 안 본다. 여기서 인증까지 확인하려면 CLI 를 한 번씩 띄워야 하는데, 그 값이
    이 조회를 부르는 자리(좌석 배정·준비 상태 표시)마다 든다. 못 부르는 CLI 는 부른 쪽이
    `UpstreamError` 로 받는다.
    """
    return tuple(kind for kind in PEER_KINDS if shutil.which(PEER_BINARIES[kind]))


@dataclass(frozen=True, slots=True)
class PeerSpec:
    """로컬 코딩 에이전트 한 명을 실행하는 데 필요한 선택값이다."""

    runtime: PeerKind
    model: str = ""
    effort: str = ""


@dataclass(frozen=True, slots=True)
class PeerTurnResult:
    """외부 에이전트 한 턴의 답과 다음 턴에 쓸 세션 식별자다."""

    text: str
    session_id: str
    command: tuple[str, ...]
    returncode: int


class PeerRuntime(Protocol):
    """로컬 프로세스와 이후 원격 transport가 함께 구현할 턴 경계다."""

    def turn(self, spec: PeerSpec, prompt: str, session_id: str = "") -> PeerTurnResult: ...


class _CompletedProcess(Protocol):
    returncode: int
    stdout: str
    stderr: str


class CliPeerRuntime:
    """Claude Code와 Codex CLI를 읽기 전용 세션으로 한 턴씩 실행한다."""

    def __init__(
        self,
        root: str,
        *,
        runner: Callable[..., _CompletedProcess] | None = None,
        timeout_s: float = 1800.0,
    ) -> None:
        self.root = root
        self._runner = runner or subprocess.run
        self.timeout_s = max(1.0, float(timeout_s))

    def turn(self, spec: PeerSpec, prompt: str, session_id: str = "") -> PeerTurnResult:
        """한 peer 턴을 실행하고 같은 세션을 재개할 수 있는 결과를 반환한다."""
        if spec.runtime not in PEER_KINDS:
            raise errors.InvalidInput(
                f"지원하지 않는 peer runtime이에요: {spec.runtime}",
                remedy="cc·codex·cursor 중 하나를 선택하세요.",
            )
        if not prompt.strip():
            raise errors.InvalidInput(
                "peer에게 보낼 prompt가 비어 있어요.",
                remedy="실행할 작업이나 동료의 피드백을 prompt로 전달하세요.",
            )

        command = self._command(spec, prompt, session_id.strip())
        shown = (*command[:-1], "<prompt>")
        try:
            completed = self._runner(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_s,
            )
        except FileNotFoundError as exc:
            raise errors.UpstreamError(
                f"{command[0]} CLI를 찾을 수 없어요.",
                remedy=self._remedy(spec.runtime),
                detail={"runtime": spec.runtime},
                cause=exc,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise errors.UpstreamError(
                f"{spec.runtime} peer가 {self.timeout_s:g}초 안에 응답하지 않았어요.",
                remedy="작업을 더 작게 나누거나 peer 턴 제한을 늘린 뒤 다시 실행하세요.",
                detail={"runtime": spec.runtime, "timeout_s": self.timeout_s},
                cause=exc,
            ) from exc
        except OSError as exc:
            raise errors.UpstreamError(
                f"{spec.runtime} peer 프로세스를 시작하지 못했어요.",
                remedy=self._remedy(spec.runtime),
                detail={"runtime": spec.runtime, "exception": type(exc).__name__},
                cause=exc,
            ) from exc

        if completed.returncode != 0:
            raise errors.UpstreamError(
                f"{spec.runtime} peer가 종료 코드 {completed.returncode}로 끝났어요.",
                remedy=self._remedy(spec.runtime),
                detail={"runtime": spec.runtime, "returncode": completed.returncode},
            )
        text, returned_session = self._parse(spec.runtime, completed.stdout, session_id.strip())
        return PeerTurnResult(text, returned_session, shown, completed.returncode)

    @staticmethod
    def _command(spec: PeerSpec, prompt: str, session_id: str) -> list[str]:
        if spec.runtime == "cc":
            command = ["claude", "-p", "--output-format", "json", "--permission-mode", "plan"]
            if session_id:
                command.extend(("--resume", session_id))
            if spec.model:
                command.extend(("--model", spec.model))
            if spec.effort:
                command.extend(("--effort", spec.effort))
            command.append(prompt)
            return command

        if spec.runtime == "cursor":
            # `--mode ask` 는 읽기 전용 질의응답이다. `--trust` 는 쓰기를 여는 것이 아니라 이
            # 디렉터리를 믿느냐는 물음을 건너뛴다 — 그 물음은 대화형으로만 답할 수 있어서,
            # 없으면 비대화형 호출이 매번 그 안내문만 내고 끝난다.
            command = ["cursor-agent", "-p", "--output-format", "json", "--mode", "ask", "--trust"]
            if session_id:
                command.extend(("--resume", session_id))
            if spec.model:
                command.extend(("--model", spec.model))
            command.append(prompt)
            return command

        command = ["codex", "exec"]
        if session_id:
            command.append("resume")
        command.append("--json")
        if session_id:
            command.extend(("-c", 'sandbox_mode="read-only"'))
        else:
            command.extend(("--sandbox", "read-only"))
        if spec.model:
            command.extend(("--model", spec.model))
        if spec.effort:
            command.extend(("-c", f"model_reasoning_effort={json.dumps(spec.effort)}"))
        if session_id:
            command.append(session_id)
        command.append(prompt)
        return command

    def _parse(self, runtime: PeerKind, output: str, prior_session: str) -> tuple[str, str]:
        try:
            # cursor-agent 의 `--output-format json` 은 claude 와 같은 한 덩어리다
            # ({"result": ..., "session_id": ...}). codex 만 줄 단위 이벤트 스트림이다.
            if runtime in ("cc", "cursor"):
                payload = json.loads(output)
                if not isinstance(payload, dict):
                    raise ValueError("Claude result is not an object")
                text = payload.get("result")
                session_id = payload.get("session_id") or prior_session
            else:
                events = [json.loads(line) for line in output.splitlines() if line.strip()]
                if not events or not all(isinstance(event, dict) for event in events):
                    raise ValueError("Codex event stream is empty")
                session_id = prior_session
                text = ""
                for event in events:
                    if event.get("type") == "thread.started" and event.get("thread_id"):
                        session_id = event["thread_id"]
                    item: Any = event.get("item")
                    if (
                        event.get("type") == "item.completed"
                        and isinstance(item, dict)
                        and item.get("type") == "agent_message"
                        and isinstance(item.get("text"), str)
                    ):
                        text = item["text"]
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise errors.UpstreamError(
                f"{runtime} peer의 구조화 출력을 읽을 수 없어요.",
                remedy=f"{runtime} CLI가 JSON 출력 옵션을 지원하는 최신 버전인지 확인하세요.",
                detail={"runtime": runtime, "exception": type(exc).__name__},
                cause=exc,
            ) from exc

        if not isinstance(text, str) or not text.strip() or not isinstance(session_id, str) or not session_id.strip():
            raise errors.UpstreamError(
                f"{runtime} peer가 최종 답이나 세션 ID를 돌려주지 않았어요.",
                remedy="peer CLI 로그인 상태와 JSON 출력 형식을 확인한 뒤 다시 실행하세요.",
                detail={"runtime": runtime, "has_text": bool(text), "has_session": bool(session_id)},
            )
        return text, session_id

    @staticmethod
    def _remedy(runtime: PeerKind) -> str:
        if runtime == "cc":
            return "Claude Code를 설치하고 `claude /login`으로 인증하세요."
        if runtime == "cursor":
            return "Cursor CLI를 설치하고 `cursor-agent login`으로 인증하세요."
        return "Codex CLI를 설치하고 `codex login`으로 인증하세요."


class _HeimdallLike(Protocol):
    total_tokens: int
    cache_read_tokens: int
    cache_prompt_tokens: int
    last_response_text: str
    dual_mode: bool

    def handle(self, request: str) -> str: ...

    def resume(self, qid: str | None = None) -> str: ...

    def cancel(self) -> None: ...


_PROMPT_REQUIRED = "⚠ 새 실행에는 prompt가 필요해요. 이미 있는 Quest를 이어가려면 --resume을 쓰세요."


class ExecutionSession:
    """Heimdall 인스턴스 하나와 그 턴·취소 수명을 소유한다."""

    def __init__(
        self,
        provider: "ResolvedProvider",
        root: str,
        *,
        session_id: str | None = None,
        agent: str | None = None,
        dual: bool = False,
        on_event: Callable[[TurnEvent], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.provider = provider
        self.root = root
        self.session_id = session_id or uuid.uuid4().hex
        self.agent = agent
        self.dual = dual
        self._on_event = on_event or (lambda _event: None)
        self._clock = clock or time.monotonic
        self._heimdall: _HeimdallLike | None = None
        self._turn_lock = threading.Lock()
        self._state_lock = threading.Lock()
        # TurnStarted 콜백은 지연 생성 중인 Heimdall보다 먼저 취소할 수 있으므로 준비 전 신호를 보관한다.
        self._turn_active = False
        self._cancel_ready = False
        self._cancel_pending = False

    def submit(self, prompt: str) -> TurnResult:
        """새 요청 한 건을 같은 Heimdall 세션에서 실행한다."""
        return self._run(prompt, resume=False)

    def resume(self, quest_id: str | None = None) -> TurnResult:
        """기존 Quest를 같은 Heimdall 세션에서 이어서 실행한다."""
        return self._run("", resume=True, quest_id=quest_id)

    def cancel(self) -> None:
        """이미 만들어진 Heimdall 세션의 현재 턴에 협조적 취소를 요청한다."""
        with self._state_lock:
            if not self._turn_active:
                return
            if not self._cancel_ready:
                self._cancel_pending = True
                return
            if self._heimdall is not None:
                self._heimdall.cancel()

    def _run(self, prompt: str, *, resume: bool, quest_id: str | None = None) -> TurnResult:
        with self._turn_lock:
            return self._run_turn(prompt, resume=resume, quest_id=quest_id)

    def _run_turn(self, prompt: str, *, resume: bool, quest_id: str | None) -> TurnResult:
        profile = self.provider.profile.name
        model = self.provider.model
        with self._state_lock:
            self._turn_active = True
            self._cancel_ready = False
            self._cancel_pending = False
        try:
            self._emit(TurnStarted(self.session_id, prompt, profile, model, resume))
            heimdall = self._get_heimdall()
            cancel_event = getattr(heimdall, "cancel_event", None)
            with self._state_lock:
                if cancel_event is not None:
                    cancel_event.clear()
                # Heimdall.resume()의 조기 경고 경로는 이 값을 초기화하지 않으므로 턴 경계에서 비운다.
                setattr(heimdall, "_last_quest_id", None)
                self._cancel_ready = True
                if self._cancel_pending:
                    heimdall.cancel()
                    self._cancel_pending = False

            started = self._clock()
            if resume:
                raw = heimdall.resume(quest_id)
            elif prompt:
                raw = heimdall.handle(prompt)
            else:
                raw = _PROMPT_REQUIRED
            wall_s = round(self._clock() - started, 1)
            text = raw or heimdall.last_response_text
            outcome: TurnOutcome = "attention" if raw.startswith("⚠") else "completed"
            result = TurnResult(
                session_id=self.session_id,
                text=text,
                outcome=outcome,
                response_streamed=not raw and bool(text),
                quest_id=getattr(heimdall, "_last_quest_id", None),
                tokens=heimdall.total_tokens,
                cache_read_tokens=heimdall.cache_read_tokens,
                cache_prompt_tokens=heimdall.cache_prompt_tokens,
                wall_s=wall_s,
                provider=profile,
                model=model,
            )
            self._emit(TurnFinished(self.session_id, result.ok, wall_s, result.tokens))
            return result
        finally:
            with self._state_lock:
                self._turn_active = False
                self._cancel_ready = False
                self._cancel_pending = False

    def _get_heimdall(self) -> _HeimdallLike:
        heimdall = self._heimdall
        if heimdall is None:
            from .heimdall import Heimdall

            if self.agent is None:
                heimdall = Heimdall(self.provider, self.root, on_text=self._emit_text, on_status=self._emit_status)
            else:
                heimdall = Heimdall(
                    self.provider,
                    self.root,
                    on_text=self._emit_text,
                    on_status=self._emit_status,
                    agent=self.agent,
                )
            heimdall.dual_mode = self.dual
            self._heimdall = heimdall
        return heimdall

    def _emit_text(self, text: str) -> None:
        self._emit(TurnText(self.session_id, text))

    def _emit_status(self, label: str | None) -> None:
        self._emit(TurnStatusChanged(self.session_id, label))

    def _emit(self, event: TurnEvent) -> None:
        self._on_event(event)
