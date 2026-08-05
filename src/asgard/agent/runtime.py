"""Transport-neutral Heimdall session and turn contracts."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias

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
