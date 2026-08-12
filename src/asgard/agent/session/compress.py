"""컨텍스트 압축을 세션에 붙이는 믹스인 — 창 계산, 후긴 엔진 소유, 사람 표면 통지.

압축 자체는 `agent.huginn` 이 한다. 여기 있는 것은 그 엔진을 세션 수명에 묶고, 발동 결과를
한 줄로 알리고, anthropic 서버측 압축(T3)의 opt-in 실패를 폴백으로 접는 부분이다."""

from __future__ import annotations

from ._shared import _SessionState
from .types import _FALLBACK_CONTEXT_WINDOW, SessionResult


class _CompressionMixin(_SessionState):
    def _window(self) -> int:
        # 창 미상(profile=0, openai_compat/nvidia)이어도 압축은 걸려야 한다 — 폴백 없이는
        # 컨텍스트가 무한 성장해 API 한도 초과(400 fatal)로만 터진다 (CUS-248).
        # 정밀값은 config [provider] context_window로 지정.
        return self.rp.context_window or self.rp.profile.context_window or _FALLBACK_CONTEXT_WINDOW

    @property
    def huginn(self):
        """압축 엔진 — 세션 수명 동안 1개 (안티스래시·쿨다운 상태가 여기 산다)."""
        engine = getattr(self, "_huginn", None)
        if engine is None:
            from ..huginn import Huginn, make_caller, policy

            engine = Huginn(
                self.root,
                self._window(),
                policy(self.root),
                call=make_caller(self),
                session_id=self._codex_session_id,
            )
            self._huginn = engine
        return engine

    def _report_compaction(self, event: dict) -> None:
        """사람 표면 1줄 — 조용한 손실은 없다. 요약이 실패해 물러난 것도 그대로 말한다."""
        if not event:
            return
        failure = event.get("failure")
        if event.get("tier") == "summary" and not failure:
            self._tool_line(
                "⌫",
                f"컨텍스트 요약 — {event.get('summarized', 0)}건 인수인계, "
                f"{event.get('before_tokens', 0):,}→{event.get('after_tokens', 0):,} 토큰 "
                f"({event.get('savings_pct', 0)}% 회수)",
            )
            return
        if failure in {"auth", "network", "empty_summary"}:
            self._tool_line("⚠", f"컨텍스트 요약 실패({failure}) — 원본 보존, 잠시 뒤 재시도")
        elif event.get("blocked") == "ineffective":
            self._tool_line("⚠", "컨텍스트 요약이 줄지 않아 자동 압축을 멈춤 — 창을 비우려면 새 세션")
        if event.get("recovered"):
            detail = f"오래된 툴 출력 {event.get('pruned', 0)}건 프룬"
            if event.get("folded"):
                detail += f" · 중복 {event['folded']}건 접기"
            self._tool_line("⌫", f"컨텍스트 압축 — {detail} ({event['recovered']:,} 토큰 회수)")

    def _maybe_compress(self, result: SessionResult) -> None:
        """단계형 발동 — 프룬 80% / 요약 90% (config [compress]). 전 실패 fail-open."""
        try:
            engine = self.huginn
            engine.note_usage(result.context_tokens)
            # 압축 직후 턴에서 방출된 작업을 다시 하고 있는지 본다 — ACON 교훈 신호.
            engine.observe_turn(self.messages)
            messages, event = engine.compress(self.messages, result.context_tokens)
            self.messages = messages
            self._report_compaction(event)
            if event.get("archived"):
                self._tool_line("⌫", f"방출 구간 {event['archived']}건 보관 — context_recall로 회수 가능")
        except Exception:
            return  # 압축은 편의 층이다 — 여기서 죽으면 세션이 죽는다

    def _note_server_compaction(self, content: object) -> None:
        """T3 — provider가 서버측에서 압축했으면 계측하고 표면에 알린다."""
        try:
            if self.huginn.note_server_compaction(content):
                self._tool_line("⌫", "컨텍스트 압축 — provider 서버측 요약(compaction 블록)")
        except Exception:
            return

    def _maybe_compress_codex(self, items: list, result: SessionResult) -> list:
        """codex_responses 전용 — stateless 재전송이라 프룬이 없으면 무한 성장한다."""
        try:
            engine = self.huginn
            if engine.policy.mode == "off" or result.context_tokens < engine.prune_tokens:
                return items
            from ..huginn import prune_codex_items

            pruned, recovered = prune_codex_items(
                items,
                tail_tokens=engine.effective_tail_tokens(),
                min_recovery_tokens=engine.policy.min_recovery_tokens,
            )
            if recovered:
                engine.prunes += 1
                self._tool_line("⌫", f"컨텍스트 압축 — 오래된 툴 출력 프룬 ({recovered:,} 토큰 회수)")
            return pruned
        except Exception:
            return items

    def _anthropic_stream(self, **kwargs):
        """Messages 스트림 — T3(서버측 압축)가 켜져 있으면 beta 표면으로 올린다.

        opt-in 인 이유: 서버측 압축은 provider가 히스토리 절단을 소유하므로 우리 사다리·보관소·
        교훈 루프가 그 구간을 못 본다. 켜는 순간 관측 가능성을 절감과 맞바꾸는 거래라 기본값은 off.

        SDK 미지원·베타 미승인은 예외가 아니라 폴백이다. 스트림 생성은 네트워크를 타지 않으므로
        (요청은 __enter__에서 난다) 여기서 잡히는 건 시그니처 불일치뿐이고, 400/403은 호출부의
        _server_compaction_retry()가 받는다. 한 번 실패하면 세션 내내 클라이언트측만 쓴다."""
        self._server_compaction_active = False
        extra = {} if getattr(self, "_server_compaction_failed", False) else self.huginn.server_kwargs()
        if not extra:
            return self.client.messages.stream(**kwargs)
        try:
            stream = self.client.beta.messages.stream(**kwargs, **extra)
        except Exception:
            self._disable_server_compaction()
            return self.client.messages.stream(**kwargs)
        self._server_compaction_active = True
        return stream

    def _disable_server_compaction(self) -> None:
        if not getattr(self, "_server_compaction_failed", False):
            self._server_compaction_failed = True
            self._tool_line("⚠", "서버측 압축 미지원 — 클라이언트측 압축으로 폴백")

    def _server_compaction_retry(self) -> bool:
        """서버측 압축이 붙은 요청이 터졌는가 — True 면 호출부가 같은 iteration을 재시도한다.

        beta 헤더·context_management 미승인은 400/403으로 오는데, 이건 세션을 죽일 이유가 아니라
        기능을 끄고 다시 보낼 이유다. 재시도 1회의 대가로 opt-in이 세션을 못 깨게 만든다."""
        if not getattr(self, "_server_compaction_active", False):
            return False
        self._server_compaction_active = False
        self._disable_server_compaction()
        return True
