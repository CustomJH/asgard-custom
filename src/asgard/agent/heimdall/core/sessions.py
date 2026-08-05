"""세션과 모델 — 역할마다 어느 엔진으로 어떤 프롬프트를 들고 들어가는가, 그리고 그 소비량."""

from __future__ import annotations

import random
import time
from typing import Callable

from ....model_tiers import TIER_UP as _TIER_UP
from ....model_tiers import TIERS
from ....model_tiers import family_tier as _model_tier
from ....model_tiers import tiers_for as _tiers_for
from ....providers import ResolvedProvider
from ...session import AgentSession, TurnCancelled, make_client
from ..classify import (
    classify_api_error,
)
from ..roles import (
    _DELIVERY_TIERS,
)
from ._shared import SessionLike, _concurrent_label


class _SessionsMixin:
    """세션과 모델 — 역할마다 어느 엔진으로 어떤 프롬프트를 들고 들어가는가, 그리고 그 소비량.

    `Heimdall` 가 상속한다 — 혼자서는 아무것도 아니다."""

    def _client_for(self, rp: ResolvedProvider):
        key = (rp.profile.name, rp.base_url, rp.key_source)
        with self._state_lock:
            if key not in self._clients:
                self._clients[key] = make_client(rp)
            return self._clients[key]

    def _add_tokens(self, n: int) -> None:
        with self._state_lock:
            self.total_tokens += n

    def _recap_event(self, text: str) -> None:
        """턴 recap 메타 이벤트 기록 — 기억 저장·프로젝트 메모리 보존/제안 등 백그라운드
        부수 작업을 사용자에게 보이는 한 문장으로 남긴다 (hermes recap 상응). fail-open."""
        try:
            with self._state_lock:
                events = self.turn_recap.setdefault("events", [])
                if text and text not in events:
                    events.append(text)
        except Exception:
            pass

    def _record_tool(self, name: str, args: dict) -> None:
        """세션 툴 호출의 턴 recap 집계 (AgentSession on_tool 훅) — 관측 전용, fail-open."""
        try:
            with self._state_lock:
                recap = self.turn_recap
                recap["tools"][name] += 1
                if name == "str_replace_based_edit_tool" and args.get("command") != "view":
                    path = str(args.get("path") or "")
                    if path:
                        import os as _os

                        rel = _os.path.relpath(path, self.root) if _os.path.isabs(path) else path
                        entry = recap["files"].setdefault(rel, {"op": "edit", "n": 0})
                        entry["n"] += 1
                        if args.get("command") == "create":
                            entry["op"] = "create"
                elif name == "bash":
                    head = str(args.get("command") or "").strip().split()
                    if head:
                        recap["cmds"][head[0]] += 1
        except Exception:
            pass

    def _session_observer(
        self, role: str, label: str = ""
    ) -> tuple[Callable[[str | None], None], Callable[[str, str], None]]:
        """이 세션의 관측 창구. `label`은 **화면에 적히는 이름**이고 `role`은 배치 키다.

        둘을 가르는 이유는 편대다: thor 넷이 동시에 도는데 `role`은 넷 다 'thor'여야 한다
        (provider 배치·도구 가시성·프롬프트 계층이 그 키를 읽는다). 화면에는 넷을 구분해
        적어야 하므로 이름만 따로 받는다."""
        shown = label or role
        with self._state_lock:
            self._session_seq += 1
            sid = f"{shown}-{self._session_seq}"
            self._sessions[sid] = {
                "id": sid,
                "role": shown,
                "state": "ready",
                "status": "",
                "started": 0.0,
                "ended": 0.0,
            }

        def emit() -> None:
            rows = self.session_snapshot(active_only=True)
            if not rows:
                self.on_status(None)
                return
            self.on_status(_concurrent_label(rows))

        def status(label: str | None) -> None:
            with self._state_lock:
                row = self._sessions[sid]
                if row["state"] == "running":
                    row["status"] = label or ""
            emit()

        def lifecycle(event: str, detail: str) -> None:
            from .... import activity

            now = time.monotonic()
            activity.emit(
                "session.start" if event == "running" else "session.end",
                sid=sid,
                role=shown,  # 창도 편대의 넷을 구분해 봐야 한다 — 배치 키가 아니라 적히는 이름이다
                state=None if event == "running" else (detail or "done"),
            )
            with self._state_lock:
                row = self._sessions[sid]
                if event == "running":
                    row.update(state="running", status="", started=now)
                    try:
                        self.turn_recap["agents"][role] += 1  # 턴 recap — 기동 에이전트 역할 집계
                    except AttributeError, KeyError, TypeError:
                        pass  # 관측 부가 기능 — 구버전/최소 대역 세션을 깨지 않는다
                else:
                    state = detail if detail in {"cancelled", "failed"} else "done"
                    row.update(state=state, status="", result=detail, ended=now)
                if len(self._sessions) > 32:
                    for old_id, old in list(self._sessions.items()):
                        if old["state"] != "running" and old_id != sid:
                            del self._sessions[old_id]
                            break
            emit()

        return status, lifecycle

    def session_snapshot(self, active_only: bool = False) -> list[dict]:
        """Thread-safe child-session view for the terminal; no model state or prompts leak."""
        now = time.monotonic()
        with self._state_lock:
            rows = [dict(row) for row in self._sessions.values() if not active_only or row["state"] == "running"]
        for row in rows:
            if row["started"]:
                row["elapsed_s"] = round((row["ended"] or now) - row["started"], 1)
            else:
                row["elapsed_s"] = 0.0
        return rows

    def _agent_for(self, role: str | None) -> str | None:
        """이 역할을 도는 에이전트 id — 배치가 없으면 None (활성 에이전트 그대로).

        세션 전체가 다른 에이전트로 고정돼 있으면(모드 배치) 역할 배치가 없어도 그 이름을 쓴다.
        "해당 세션에서는 그 에이전트로만 동작한다"가 이 한 줄이다."""
        placed = self._role_agent.get(role or "")
        return placed or (self._session_agent or None)

    def _agent_note_for(self, role: str | None) -> str:
        """이 역할을 도는 에이전트의 정체성 블록 — 없으면 빈 문자열.

        역할당 1회 렌더 후 캐시 (프롬프트 프리픽스 안정 = KV 캐시 보존)."""
        agent = self._agent_for(role)
        if not agent:
            return ""
        key = role or ""
        if key not in self._agent_note_cache:
            from ....profiles import note as _agent_note

            try:
                self._agent_note_cache[key] = _agent_note(agent)
            except Exception:
                self._agent_note_cache[key] = ""
        return self._agent_note_cache[key]

    def _session(
        self,
        system: str,
        extra_tools=None,
        handlers=None,
        quiet=False,
        role: str | None = None,
        model: str | None = None,
        readonly: bool = False,
        rp_override: ResolvedProvider | None = None,
        cwd: str | None = None,
        label: str = "",
    ) -> AgentSession:
        session_status, lifecycle = self._session_observer(role or ("readonly" if readonly else "legacy"), label)
        # 에이전트 정체성 — 이 한 자리에서 모든 역할 세션에 얹는다. 호출부마다 붙이면 새 역할이
        # 생길 때마다 빠뜨릴 자리가 늘어난다. 정체성이 비었거나(주석뿐) 배치가 없으면 빈 문자열이라
        # 프로파일을 안 쓰는 설치의 프롬프트는 바이트 단위로 종전과 같다.
        system = system + self._agent_note_for(role)
        rp = rp_override or self.role_rp.get(role or "", self.rp)
        if model and model != rp.model:  # 상황별 모델 스왑 — provider는 유지, 모델만
            from dataclasses import replace

            rp = replace(rp, model=model)
        return AgentSession(
            self._client_for(rp),
            rp,
            self.root,
            system,
            extra_tools=extra_tools,
            tool_handlers=handlers,
            on_text=(lambda s: None) if quiet else self.on_text,
            on_tokens=self._add_tokens,
            on_status=session_status,
            readonly=readonly,
            role=role,
            cwd=cwd,
            cancel_event=self.cancel_event,
            on_lifecycle=lifecycle,
            on_tool=self._record_tool,
            agent=self._agent_for(role),
        )

    def _model_for(self, role_key: str, bump: bool = False) -> str | None:
        """정책 tier → 상황별 모델. None = 스왑 없음 (해당 세션 rp.model 그대로).

        존중 규칙: ① 역할에 명시 placement가 있으면 그 모델 ② 기본 provider가 anthropic이
        아니면 티어 매핑 불가 ③ 알려지지 않은 커스텀 모델은 그 선택 유지.
        티어 하한 = 코디네이터: 정책 티어가 세션 모델 티어보다 낮으면 세션 티어로 올린다 —
        더 싼 손이 필요하면 ① placement로 명시한다.
        bump = 상황 승급 (full-verify·재계획 2회+) — 티어 사다리 한 칸 위 (high→max=fable)."""
        rp = self.role_rp.get(role_key, self.rp)
        if rp is not self.rp:
            return None  # 명시 placement 존중
        # claude_cli도 티어 매핑 가능 — CLI가 full 모델 ID를 그대로 해석한다
        if rp.profile.api_mode not in ("anthropic", "claude_cli"):
            return None
        tier = str((self.policy.get("roles", {}).get(role_key) or {}).get("tier", "standard"))
        # 코디네이터 티어 하한 — 위임된 실행·판정 손이 세션 모델보다 약하면 그 손이 품질 하한이
        # 된다 (숨은 caller 추적처럼 코디네이터는 하는 일을 못 한다). 정책이 명시한 티어라도
        # 코디네이터 아래로는 내리지 않는다; 역매핑 불가 모델(커스텀 ID)은 하한 미적용.
        table = _tiers_for(rp.profile.name, rp.profile.api_mode)
        order = list(TIERS)
        coord = _model_tier(rp.model)
        if coord is None:
            return None
        if coord and tier in order and order.index(coord) > order.index(tier):
            tier = coord
        if bump:
            tier = _TIER_UP.get(tier, tier)
        return table.get(tier)

    def dual_thinker_labels(self) -> tuple[str, str]:
        """Dual mode의 실제 provider:model 쌍 — 동일 모델 오설정을 진입 전에 차단한다."""

        def label(role: str) -> str:
            rp = self.role_rp.get(role, self.rp)
            return f"{rp.profile.name}:{self._model_for(role) or rp.model}"

        return label("thinker"), label("thinker_alt")

    def _delivery_model(self, agent: str) -> str | None:
        """딜리버리 전문가 모델 — 정책 "delivery" 티어 (기본: freyja/thor/eitri=sonnet, loki=haiku)."""
        rp = self.role_rp.get(agent, self.rp)
        if rp is not self.rp:  # 명시 placement 존중
            return None
        if rp.profile.api_mode not in ("anthropic", "claude_cli"):
            return None
        tier = str((self.policy.get("delivery") or {}).get(agent, _DELIVERY_TIERS.get(agent, "standard")))
        coord = _model_tier(rp.model)
        if coord is None:
            return None
        # Loki는 의도된 저비용 반례 정찰. 실제 산출을 만드는 나머지 손만 코디네이터 하한 적용.
        table = _tiers_for(rp.profile.name, rp.profile.api_mode)
        order = list(TIERS)
        if agent != "loki" and tier in order and order.index(coord) > order.index(tier):
            tier = coord
        return table.get(tier)

    def _count_usage(self, resp: object) -> None:
        """단발 completion의 토큰을 세션 누계에 더한다.

        이 경로가 계측 밖에 있으면 상태줄과 budget-guard가 실제 지출보다 적게 본다 — 분류
        한 번은 작지만 코디네이터 답변은 퀘스트마다 여러 번이다. usage 형식이 provider마다
        달라(total_tokens가 있는 곳도, input/output만 있는 곳도 있다) 해석 실패는 0으로 센다:
        계측이 세션을 죽이면 안 된다."""
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        total = getattr(usage, "total_tokens", None)
        if not isinstance(total, int):
            parts = [getattr(usage, name, None) for name in ("input_tokens", "output_tokens")]
            total = sum(n for n in parts if isinstance(n, int))
        if total:
            self._add_tokens(total)

    def _complete_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """비스트리밍 단발 completion — 트랜스포트 무관 (classify 등 내부 판단용).
        [trinity.classify] placement가 있으면 그 provider/모델 사용 (저비용 분류)."""
        rp = self.role_rp.get("classify", self.rp)
        client = self._client_for(rp)
        from ...rate_limit import throttle

        throttle(rp)  # RPM 상한 provider(NIM 40rpm 등) — classify 단발도 전역 윈도에 계수
        if rp.profile.api_mode == "claude_cli":
            from ...claude_native import complete_text

            return complete_text(system, user, model=rp.model, root=self.root)
        if rp.profile.api_mode == "anthropic":
            resp = client.messages.create(
                model=rp.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
            )
            self._count_usage(resp)
            return "".join(b.text for b in resp.content if b.type == "text")
        if rp.profile.api_mode in {"openai_responses", "codex_responses"}:
            kwargs: dict[str, object] = dict(
                model=rp.model,
                instructions=system,
                input=user,
                timeout=120.0,
            )
            if rp.profile.api_mode == "codex_responses":
                kwargs["store"] = False
            else:
                kwargs["max_output_tokens"] = max(4096, max_tokens)
            if rp.model.startswith(("gpt-5", "o1", "o3", "o4")):
                kwargs["reasoning"] = {"effort": "low"}
            if rp.profile.api_mode == "codex_responses":
                from ....openai_codex import create_response  # Codex 엔드포인트는 스트리밍만 받는다

                resp = create_response(client, **kwargs)
            else:
                resp = client.responses.create(**kwargs)
            self._count_usage(resp)
            return resp.output_text or ""
        resp = client.chat.completions.create(
            model=rp.model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        self._count_usage(resp)
        return resp.choices[0].message.content or ""

    def _run_turn(
        self,
        make: Callable[[], SessionLike],
        prompt: str,
        fallback: Callable[[], SessionLike] | None = None,
        fallback_prompt: str | None = None,
    ):
        """역할 턴 실행 + 오류 회복 — retryable은 jittered backoff ≤2회 재시도,
        소진 시 placement 폴백 1회 (기본 provider), fatal은 즉시 표면화."""
        delay = 2.0
        for attempt in range(3):
            try:
                r = make().run(prompt)
                if getattr(r, "stop_reason", "") == "cancelled":
                    raise TurnCancelled()
                self.last_context_tokens = getattr(r, "context_tokens", 0) or self.last_context_tokens
                self._track_cache(r)
                return r
            except TurnCancelled:
                raise  # 취소는 재시도·폴백 대상이 아니다
            except Exception as e:
                if classify_api_error(e) != "retryable" or attempt == 2:
                    if fallback is not None:
                        self.on_text(
                            f"⚠ provider에 문제가 생겨서({e.__class__.__name__}) 기본 provider로 한 번 돌려볼게요\n"
                        )
                        r = fallback().run(prompt if fallback_prompt is None else fallback_prompt)
                        if getattr(r, "stop_reason", "") == "cancelled":
                            raise TurnCancelled()
                        self._track_cache(r)
                        return r
                    raise
                self.on_text(
                    f"⚠ provider가 잠깐 말썽이에요({e.__class__.__name__}) — {delay:.0f}초 뒤에 다시 해볼게요\n"
                )
                self._sleep(delay + random.uniform(0, delay / 2))
                delay = min(delay * 2, 30.0)
        raise RuntimeError("unreachable")

    def _track_cache(self, r) -> None:
        """프롬프트 캐시 계측 집계 — 세션 결과의 read/write/uncached를 누적 (스레드 안전, wave 병렬)."""
        cr = getattr(r, "cache_read_tokens", 0) or 0
        total = cr + (getattr(r, "cache_write_tokens", 0) or 0) + (getattr(r, "uncached_input_tokens", 0) or 0)
        if total:
            with self._state_lock:
                self.cache_read_tokens += cr
                self.cache_prompt_tokens += total
