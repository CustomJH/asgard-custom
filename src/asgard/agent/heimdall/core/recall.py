"""기억 — 턴에 들이는 회수층과, 턴이 끝난 뒤 무엇을 남길지의 판단. 지도 준비도 여기."""

from __future__ import annotations

from ....providers import ResolvedProvider
from ....sessions import resolve_agent as _resolve_agent
from ..journal import _log_classify
from ..roles import (
    _EXPLORE_NUDGE_MIN,
)


class _RecallMixin:
    """기억 — 턴에 들이는 회수층과, 턴이 끝난 뒤 무엇을 남길지의 판단. 지도 준비도 여기.

    `Heimdall` 가 상속한다 — 혼자서는 아무것도 아니다."""

    def _load_memory_layers(self, rp: ResolvedProvider, root: str) -> None:
        """개인 메모리 동결 스냅샷(memory v3 P1)과 역할별 에이전트 배치를 해석한다.

        주입 매트릭스: DIRECT(identity)·호출된 Thinker = 스냅샷+회수. standard Worker는 요청
        관련 개인 회수만 받고, deep Worker는 개인 메모리를 받지 않는다. Verifier/딜리버리(loki
        포함)는 영구 무주입. provider 게이트는 inject_allowed — 킬스위치 + allowlist.
        """
        from ....memory import inject_allowed as _mem_allowed
        from ....memory import snapshot_note as _memory_note

        self._memory_snap = _memory_note()  # 동결 원본 — 역할별 게이트는 아래에서
        self._mem_allowed = _mem_allowed
        # 스웜 — 이 프로젝트가 역할마다 다른 에이전트를 세워 뒀는가 (.asgard의 [agents].roles).
        # 세워 뒀으면 그 역할의 세션은 **그 에이전트의 홈**에서 돌고, 1차 기억 스냅샷도 거기서
        # 뜬다. 배치가 없으면 이 딕셔너리가 비어 있고 아래 경로는 전부 종전과 바이트 동일하다.
        from ....swarm import swarm as _swarm_roles

        try:
            self._role_agent: dict[str, str] = _swarm_roles(root)
            # 세션 전체의 에이전트는 sessions 사다리가 정한다 — 이 세션이 명시로 고른 것이
            # 프로젝트 배치보다, 배치가 끈끈한 활성보다 우선한다.
            self._session_agent: str = _resolve_agent(root, self._explicit_agent, mode="native")
        except Exception:  # 배치 해석 실패가 세션 시동을 막으면 안 된다 (fail-open)
            self._role_agent, self._session_agent = {}, ""
        self._role_memory_snap: dict[str, str] = {}
        self._agent_note_cache: dict[str, str] = {}
        self._memory_note_fn = _memory_note
        self._memory_provider_allowed = _mem_allowed(rp.profile.name, rp.source)
        self.memory_note = self._memory_snap if self._memory_provider_allowed else ""

    def _record_recall(self, text: str) -> None:
        """턴 recap 회상 주입량 집계 — 결정론 회상(숏컷)이 이 턴의 프롬프트에 실제로 실은
        문자수. REPL done 줄의 답변 소스 배지('⠶ 무닌 ~n%' — 오딘의 기억 까마귀) 원천 — 관측 전용, fail-open.
        게이트 증거가 아니다 (배지는 UX 신호, Verifier 판정과 무관)."""
        try:
            if text and text.strip():
                with self._state_lock:
                    recap = self.turn_recap
                    recap["recall_chars"] = recap.get("recall_chars", 0) + len(text)
        except Exception:
            pass

    def _memory_snap_for(self, role: str | None) -> str:
        """역할별 1차 기억 스냅샷 — 배치된 에이전트가 있으면 **그 에이전트의** 기억.

        역할당 1회만 뜨고 캐시한다 (세션 생성 시 1회 렌더 규율 유지 — KV 캐시·재현성).
        배치가 없으면 종전의 동결 원본을 그대로 돌려준다 (프롬프트 무변화)."""
        agent = self._role_agent.get(role or "")
        if not agent:
            return self._memory_snap
        if role not in self._role_memory_snap:
            from ....profiles import scoped

            try:
                with scoped(agent):
                    self._role_memory_snap[role or ""] = self._memory_note_fn()
            except Exception:
                self._role_memory_snap[role or ""] = ""  # 그 에이전트의 기억을 못 읽으면 무주입
        return self._role_memory_snap.get(role or "", self._memory_snap)

    def _learned_note(self, task: str, agent: str, quiet: bool = False) -> str:
        """learned 스킬 주입 노트 (skill_bank, CUS-252) — 승인된 경험 지식의 advisory 층.

        Verifier/loki 호출측은 이 함수를 부르지 않는다 (게이트 무결성 — 학습물은 판정 표면 금지).
        실패는 조용히 빈 문자열 (fail-open — 스킬 뱅크 문제로 본 작업이 죽으면 안 된다)."""
        try:
            from .... import ui  # 로컬 임포트 — WIP 커밋 순서와 무관하게 자립 (모듈 임포트와 공존 무해)
            from ....skill_bank import record_use, resolve_learned

            hits = resolve_learned(self.root, task, agent)
            if not hits:
                return ""
            record_use(self.root, [n for n, _ in hits])
            if not quiet:
                self.on_text(f"  {ui.dim('│ ✦ 학습 스킬 — ' + ', '.join(n for n, _ in hits))}\n")
            return "\n\n# Learned skills (approved past experience — advisory, not gate evidence)\n\n" + "\n\n".join(
                b for _, b in hits
            )
        except Exception:
            return ""

    def _record_outcome(self, task_class: str, result: str, saw_red: bool) -> None:
        """퀘스트 종결 → route-priors 카운트 + classify.jsonl 감사 (Bayesian-lite 데이터 축)."""
        from ....hooks.quest_log import update_priors

        _log_classify(
            self.root, {"event": "outcome", "task_class": task_class, "result": result, "baseline_red": saw_red}
        )
        update_priors(self.root, task_class, saw_red)

    def _prepare_map(self, request: str) -> str:
        """Refresh before work starts and build task-relevant advisory context."""
        import os

        # Map is an opt-in project asset created by `asgard init/map generate`. Do not turn a
        # native session in an arbitrary repository into an unexpected tracked documentation diff.
        if not os.path.isdir(os.path.join(self.root, ".asgard", "map")):
            self.map_note = ""
            return ""
        try:
            from ....map_context import build_map_context

            context = build_map_context(self.root, request, refresh=True)
            for issue in context.issues:
                warning = f"{issue.source}: {issue.reason}"
                if warning not in self._map_warnings:
                    self._map_warnings.add(warning)
                    self.on_text(f"⚠ 프로젝트 맵에서 뺀 항목이 있어요 — {warning}\n")
            self.map_note = ("\n\n" + context.text) if context.text else ""
        except Exception as exc:
            self.map_note = ""
            warning = f"{exc.__class__.__name__}: {str(exc)[:180]}"
            if warning not in self._map_warnings:
                self._map_warnings.add(warning)
                self.on_text(f"⚠ 프로젝트 맵을 새로 못 그렸어요 — 맵 없이 갈게요 ({warning})\n")
        return self.map_note

    def _memory_write_outcome(self, request: str, saved: list[tuple[str, str]]) -> str:
        """기억 지시 턴의 실행 증거 봉합 — 저장 여부를 결정론으로 확정해 사용자에게 보인다.

        도구 미호출이면 요청 원문을 폴백 ingest 한다 (사용자 지시 = 승인; 위협·시크릿 스캔은
        ingest가 그대로 수행). 폴백까지 실패하면 실패를 숨기지 않는다 — 모델의 "기억했다"
        서술과 무관하게 이 노티스가 디스크 진실이다."""
        from ....i18n import t

        if saved:
            _log_classify(self.root, {"event": "memory_write", "source": "tool", "count": len(saved)})
            self._recap_event(t("recap_ev_memory_saved", s=", ".join(slug for _, slug in saved)))
            return "⠶ 위그드라실에 새겼어요: " + ", ".join(f"{slug} ({action})" for action, slug in saved)
        try:
            from ....memory import ingest

            action, slug = ingest(request.strip(), kind="user")
            _log_classify(self.root, {"event": "memory_write", "source": "fallback", "action": action})
            self._recap_event(t("recap_ev_memory_saved", s=slug))
            return f"⠶ 위그드라실에 새겼어요 (원문 폴백): {slug} ({action})"
        except Exception as e:
            _log_classify(self.root, {"event": "memory_write", "source": "failed"})
            return (
                f"⚠ 위그드라실에 새기지 못했어요 ({e.__class__.__name__}: {str(e)[:120]}) — "
                '`asgard memory ingest "<사실>" --kind user`로 직접 저장하세요.'
            )

    # ── 진입점 ───────────────────────────────────────────────────────────
    def _finalize_memory(self, request: str, visible_response: str) -> str:
        """완성 turn 자동 retain + 검증된 write 과업의 승인 proposal + 탐색 발견 증류 넛지.
        모든 장애는 agent 실행에 fail-open."""
        from ....i18n import t

        out = visible_response
        response = visible_response or self.last_response_text
        try:
            from ....memory_bridge import auto_retain_turns_enabled, find_config, is_backend_trusted
            from ....project_memory import propose_completion, retain_turn

            found = find_config(self.root)
            if found:
                root, cfg = found
                self._memory_turn_seq += 1
                # 리포 설정은 제안이다 — 사람이 쓴 턴 원문을 공유 backend로 보내는 손잡이라
                # 이 기계의 허가까지 있어야 켜진다 (memory_bridge.auto_retain_turns_state).
                if auto_retain_turns_enabled(cfg) and is_backend_trusted(cfg):
                    retain_turn(
                        root,
                        cfg,
                        session_id=self._memory_session_id,
                        turn_id=f"turn-{self._memory_turn_seq}",
                        user_text=request,
                        assistant_text=response,
                        mode="native",
                    )
                    self._recap_event(t("recap_ev_retained"))
                completion = self._last_completion
                if completion and cfg.get("auto_propose_completion", True):
                    proposal = propose_completion(root, cfg, request=request, response=response, **completion)
                    if proposal.status == "proposed":
                        out += "\n\n⠶ 프로젝트 메모리 승인 제안\n" + proposal.preview
                        self._recap_event(t("recap_ev_proposed"))
        except Exception:
            pass
        # 탐색 발견 증류 (개인 Tier0) — 프로젝트 backend 유무와 무관. 탐색이 컸던 순수 DIRECT
        # 턴의 위치 지식을 기존 ingest 승인 게이트로 안내한다 (숏컷 벤치 26-07-16 근거).
        try:
            if self._explore_cmds >= _EXPLORE_NUDGE_MIN and self._memory_provider_allowed:
                from ....memory import distill_nudge

                nudge = distill_nudge(request, response, self.root)
                if nudge:
                    out += "\n\n" + nudge
                    self._recap_event(t("recap_ev_distill"))
        except Exception:
            pass
        # 되짚기 — 이 턴이 쓴 코드를 사용자 앞에 물음으로 되돌린다. 외부 클라이언트는 Stop 훅이
        # 하는 일인데, 네이티브 루프에는 끼어들 훅이 없어서(단일 프로세스) 도달 경로를 여기 둔다.
        # 물음이 없거나 직전 턴과 같으면 침묵한다 — 카드가 매 턴 나오면 셋째 턴부터 안 읽힌다.
        try:
            from ....tutor import turn_note

            card = turn_note(self.root, self._last_quest_id)
            if card:
                out += "\n\n" + card
        except Exception:
            pass  # 되짚기 불능이 턴을 막지 않는다 — 튜터는 규율이지 관문이 아니다
        return out
