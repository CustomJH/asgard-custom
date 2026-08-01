"""Worker wave 실행 — 배정 단위의 티켓 lease·격리 workspace·병렬 fan-out/fan-in.

WaveRunner는 planning이 정렬한 wave를 물리 실행하는 협력자다: 티켓 claim/heartbeat/finish
수명주기, UnitWorkspace 격리·scope 검증·패치 병합, 부분 실패의 증거 보존(CUS-247)을 진다.
세션 생성·모델 선택·재시도는 오케스트레이터(hd) 표면을 쓴다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..session import TurnCancelled, ql
from .journal import _record_writes
from .patch_merge import merge_unit_patches
from .planning import _plan_waves
from .roles import _role_prompt, _skill_support, work_shape_note
from .ticket_lease import TicketLease
from .todo import TodoBoard, files_note
from .toolspec import ASK_TOOL, DISPATCH_TOOL

if TYPE_CHECKING:  # core가 이 모듈을 임포트하므로 런타임 임포트는 순환이다
    from .core import Heimdall


def _execute_pending(run_claimed, pending: list[dict], writes_by_id: dict, tickets: TicketLease, cwd_by_id: dict):
    """대기 단위를 실행하고 (완료, 실패)로 가른다. 한 개면 직렬, 여럿이면 최대 3 병렬.

    실패를 던지지 않고 **모아서 돌려주는** 것이 이 함수의 계약이다 — 한 단위가 죽어도 형제 단위의
    쓰기·이벤트는 정산되어야 하고(CUS-247), 그러려면 여기서 예외가 새어 나가면 안 된다.
    유일한 예외가 `TurnCancelled` 다: 취소는 티켓 실패가 아니라 세션 종료라 재배정 예산을
    소모시키지 않고 그대로 전파한다.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    outs: list = []
    failures: list[tuple[dict, Exception]] = []

    def claim(u: dict):
        return run_claimed(u, writes_by_id[u["id"]], tickets.token(u) or "", cwd_by_id[u["id"]])

    if len(pending) == 1:
        try:
            outs = [claim(pending[0])]
        except TurnCancelled:
            raise
        except Exception as e:
            failures.append((pending[0], e))
        return (outs, failures)

    with ThreadPoolExecutor(max_workers=min(3, len(pending))) as ex:
        # ex.map 금지 — lazy 예외 재발생이 성공 단위 후처리까지 끊는다 (CUS-247)
        futs = {ex.submit(claim, u): u for u in pending}
        for fut in as_completed(futs):
            try:
                outs.append(fut.result())
            except TurnCancelled:
                raise  # 공유 이벤트로 나머지도 곧 멈춘다
            except Exception as e:
                failures.append((futs[fut], e))
    return (outs, failures)


@dataclass
class _Ledger:
    """wave 하나가 쌓는 증거 — 쓰기 목록·단위 결과·티켓 장부·진행 보드.

    정산은 두 갈래(성공 단위·실패 단위)로 갈리는데 둘이 만지는 것이 같다. 갈래마다 열두 개를
    인자로 나르면 어느 갈래가 무엇을 빠뜨렸는지 읽어서 알 수 없게 되므로, 한 덩어리로 든다.

    `writes`와 `_seen`이 한 자리에 있는 것이 이 타입의 요점이다. 순서는 증거 재현성 때문에
    목록이어야 하고 중복 판정은 집합이어야 하는데, 둘을 따로 두면 반드시 어긋난다.
    """

    hd: Heimdall
    sid: str
    board: TodoBoard
    tickets: TicketLease
    used_model: str
    writes: list[str] = field(default_factory=list)
    results: dict = field(default_factory=dict)
    _seen: set[str] = field(default_factory=set)

    def merge(self, new: Iterable[str]) -> None:
        """순서는 유지하고 중복만 거른다.

        목록을 매번 처음부터 훑으면 단위 수가 열 배일 때 시간은 백 배다 — 이 저장소의 자기
        게이트(`craft`의 quadratic-scan)가 바로 이 자리를 두 번 짚었다.
        """
        for path in new:
            if path not in self._seen:
                self._seen.add(path)
                self.writes.append(path)

    def persist(self) -> None:
        """센티넬을 디스크에 확정한다. 실패할 수 있는 티켓 호출보다 **먼저** 불러야 한다 —
        유실되면 디스크의 쓰기가 게이트에 orphan으로 남는다 (CUS-247)."""
        _record_writes(self.hd.root, self.sid, self.writes)


class WaveRunner:
    """배정 단위 wave 병렬 실행 협력자 — access list 격리 + 파일 겹침 직렬화."""

    def __init__(self, hd):
        self._hd = hd

    # ── 정산 ────────────────────────────────────────────────────────
    # 성공과 실패를 따로 두는 이유: 두 갈래의 **불변식이 다르다**. 성공 쪽은 한 단위의 티켓
    # 실패가 형제 단위의 기록을 막으면 안 되고(그래서 오류를 모아서 나중에 던진다), 실패 쪽은
    # 재시도 가능한 것과 소진된 것을 갈라야 한다. 한 함수에 섞으면 그 두 규칙이 서로를 가린다.

    def _settle_done(self, led: _Ledger, outs: list, actual_writes: dict) -> list[Exception]:
        """완료 단위의 쓰기·결과·티켓·work 이벤트를 확정한다. 오류는 모아서 돌려준다."""
        errors: list[Exception] = []
        for u, r, writes in outs:
            unit_writes = actual_writes.get(u["id"], writes + [w for w in r.writes if w not in writes])
            led.merge(unit_writes)
            led.persist()  # 실패할 수 있는 티켓 호출보다 먼저 — 유실되면 쓰기가 orphan이 된다
            led.results[u["id"]] = r.text[-2000:]
            led.board.mark(u["id"], "done", files_note(len(unit_writes)))
            self._hd.bifrost.settle_unit(u, "succeeded", summary=r.text[-2000:], files=unit_writes[:50])
            try:
                led.tickets.settle(u, "done")
            except Exception as e:
                # 한 티켓 제어 실패가 형제 단위의 영속 기록을 막아서는 안 된다.
                errors.append(e)
            finally:
                led.tickets.stop_heartbeat(u)
            event = ql(
                led.hd.root,
                "append",
                session=led.sid,
                stdin=json.dumps(
                    {
                        "role": "worker",
                        "event": "work",
                        "unit": u["id"],
                        "changed_files": unit_writes[:50],
                        "commands": r.commands[-20:],
                        "model": led.used_model,
                    }
                ),
            )
            if event.returncode != 0:
                errors.append(RuntimeError(event.stderr.strip() or f"ticket {u['id']} work event append failed"))
        return errors

    def _settle_failed(
        self, led: _Ledger, failures: list, writes_by_id: dict, isolation: bool, errors: list[Exception]
    ) -> tuple[list[dict], list[tuple]]:
        """실패 단위를 재시도와 소진으로 가른다. (재시도할 것, 끝난 것)."""
        from ...i18n import t

        if not failures:
            return ([], [])
        # 공유 root 경로에서는 실패 단위의 부분 쓰기도 증거로 남긴다. 격리 workspace의 실패
        # delta는 폐기됐으므로 canonical write sentinel에 거짓 기록하지 않는다.
        if not isolation:
            for u, _ in failures:
                led.merge(writes_by_id[u["id"]])
        led.persist()
        retry: list[dict] = []
        terminal: list[tuple[dict, Exception]] = []
        for u, e in failures:
            try:
                final = led.tickets.settle(u, "failed", error=f"{e.__class__.__name__}: {str(e)[:400]}")
            except Exception as finish_error:
                errors.append(finish_error)
                continue
            finally:
                led.tickets.stop_heartbeat(u)
            self._hd.bifrost.settle_unit(u, "failed", summary=f"{e.__class__.__name__}: {str(e)[:400]}")
            if final == "failed":
                retry.append(u)
                led.board.mark(u["id"], "failed", t("todo_unit_retry", e=e.__class__.__name__))
            else:
                terminal.append((u, e))
                led.board.mark(u["id"], "blocked", t("todo_unit_exhausted"))
        return (retry, terminal)

    def _open_round(self, pending: list[dict], tickets: TicketLease, isolation: bool):
        """이 라운드의 격리 workspace를 열고 티켓을 claim한다. (스택, workspace, cwd 표).

        여는 도중 실패하면 이미 연 workspace를 닫고 예외를 그대로 올린다 — 안 닫으면 임시
        디렉터리가 남고, 그 다음 라운드가 같은 이름으로 열려다 또 실패한다.
        """
        workspace_stack = ExitStack()
        workspaces: dict = {}
        try:
            if isolation:
                from ..unit_workspace import UnitWorkspace

                for unit in pending:
                    workspaces[unit["id"]] = workspace_stack.enter_context(UnitWorkspace(self._hd.root, unit["id"]))
            cwd_by_id = {unit["id"]: workspaces[unit["id"]].path if isolation else None for unit in pending}
            tickets.begin_wave()
            tickets.claim_all(pending)
        except Exception:
            workspace_stack.close()
            raise
        return workspace_stack, workspaces, cwd_by_id

    def _unit_turn(self, led: _Ledger, u: dict, writes: list[str], cwd: str | None, request: str, budget_note: str):
        """배정 단위 하나의 워커 세션을 세우고 돌린다. (단위, 결과, 쓰기)를 돌려준다.

        writes는 호출측 소유 — 단위가 실패해도 디스패치 경유 부분 쓰기를 회수한다.
        """
        hd = self._hd
        wrp = hd.role_rp.get("worker", hd.rp)
        # 매칭 기준은 퀘스트 전체가 아니라 **이 단위의 과업 문장** — 단위마다 걸리는 규율이
        # 다르다 (한 단위는 회귀 테스트, 다른 단위는 계층 경계).
        unit_task = f"{u.get('subtask') or ''} {' '.join(map(str, u.get('criteria') or []))}".strip()
        skill_note, skill_tools, skill_handlers = _skill_support("worker", hd.root, task=unit_task)
        # 배정 단위의 target files는 계획 시점에 이미 알려진 사실이다 — 지시 문구가 구조를
        # 언급하지 않아도 손댈 형상(경계 교차·이미 큰 파일)으로 구조 규율이 켜진다.
        shape_note = work_shape_note(
            hd.root,
            unit_task,
            {"write_expected": True, "task_class": "standard"},
            changed=u.get("files") or None,
        )
        # 병렬 단위는 서로의 궤적을 못 본다(access 격리). 그래서 범위 경계에서 막히면 스스로
        # 풀 방법이 없고, 여태 그 자리의 선택지는 추측 아니면 실패뿐이었다. ask_coordinator 가
        # 세 번째를 준다 — 코디네이터 고리가 다른 스레드에서 답한다.
        ask_handler = hd.bifrost.ask_handler(u)

        def mk(rp=None):
            return hd._session(
                _role_prompt("asgard-worker.md") + hd.lagom + hd.comments + hd.manual_worker + skill_note + hd.map_note,
                extra_tools=[DISPATCH_TOOL, ASK_TOOL, *skill_tools],
                handlers={
                    "dispatch": hd._dispatch_handler(led.sid, writes, cwd),
                    "ask_coordinator": ask_handler,
                    **skill_handlers,
                },
                role="worker",
                model=hd._model_for("worker"),
                quiet=True,
                rp_override=rp,
                cwd=cwd,
            )

        results = led.results
        access_ctx = "".join(
            f"\n[prior unit {a} result]\n{results[a][:1500]}\n" for a in (u.get("access") or []) if a in results
        )
        prompt = (
            f"Quest: {request}\n\nAssigned unit {u['id']}: {u['subtask']}\n"
            f"Target files: {', '.join(u['files']) or '(unspecified)'}\n"
            f"criteria: {u['criteria']}\n{access_ctx}\n"
            f"Implement only your assigned unit's scope (Canon 7) — "
            f"do not touch other units' files.{shape_note}{budget_note}"
        )
        fallback = (lambda: mk(rp=hd.rp)) if wrp is not hd.rp else None
        return u, hd._run_turn(mk, prompt, fallback), writes

    def run(self, sid: str, request: str, units: list[dict], budget_note: str) -> None:
        """진행 보드를 열고 wave 실행에 넘긴다 — 보드는 어떤 경로로 끝나든 닫는다.

        중단(취소·fatal)도 보드를 닫는 이유: 그 시점의 최종 상태가 곧 "어디까지 갔는가"다.
        보드가 안 닫히면 오딘은 실패 보고만 보고 어느 단위가 남았는지 다시 퀘스트 로그를 뒤져야 한다.
        """
        # 계획을 먼저 연다 — 티켓 장부(퀘스트 로그)와 같은 목록을 오딘 쪽 표면에도 세운다.
        board = TodoBoard(self._hd.on_text)
        board.plan((unit["id"], unit.get("subtask") or "") for unit in units)
        try:
            self._run(sid, request, units, budget_note, board)
        finally:
            board.close()

    def _run(self, sid: str, request: str, units: list[dict], budget_note: str, board: TodoBoard) -> None:
        """배정 단위 wave 병렬 실행 — access list 격리 + 파일 겹침 직렬화.

        격리 원칙 (Fugu §3.2.2 orchestration collapse 방지): 각 단위는 자기 subtask +
        access에 명시된 선행 단위 결과만 본다 — 같은 wave의 다른 단위 궤적은 안 보인다.
        work 이벤트는 단위별 기록 (unit 필드), 병렬 출력은 quiet — wave 요약만 표시.

        부분 실패 (CUS-247): 한 단위가 fatal로 죽어도 성공 단위의 ql append·writes 기록을
        먼저 확정한 뒤 예외를 전파한다 — 유실되면 디스크의 쓰기가 게이트에 orphan으로 남는다."""
        from ... import ui
        from ...i18n import t

        hd = self._hd
        wrp = hd.role_rp.get("worker", hd.rp)
        ticket_policy = hd.policy.get("ticket_runtime") or {}
        isolation = bool(ticket_policy.get("isolation", True))
        tickets = TicketLease(
            hd,
            sid,
            lease_seconds=int(ticket_policy.get("lease_seconds") or 300),
            max_attempts=int(ticket_policy.get("max_attempts") or 3),
        )
        led = _Ledger(hd, sid, board, tickets, f"{wrp.profile.name}:{hd._model_for('worker') or wrp.model}")

        for unit in units:
            tickets.record(unit, "todo")
        # 계획이 선언한 `access` 를 의존으로 세운다 — 여태 문맥 주입에만 쓰이던 값이 여기서
        # 처음 배차 의존이 된다. 티켓 장부와 별개의 표면이라 실패해도 wave 는 그대로 돈다.
        hd.bifrost.register_units(units)

        def run_claimed(u: dict, writes: list[str], token: str, cwd: str | None = None):
            # 빠른 sibling이 먼저 끝나도 느린 sibling의 fan-in·patch merge까지 lease가 살아 있어야
            # 한다. merge finally가 모든 heartbeat를 join 한 직후 ticket-finish를 수행한다.
            hd.bifrost.open_unit(u, model=led.used_model, agent=hd._agent_for("worker") or "")
            heartbeat_errors = tickets.start_heartbeat(u, token)
            result = self._unit_turn(led, u, writes, cwd, request, budget_note)
            if heartbeat_errors:
                raise RuntimeError(f"ticket lease heartbeat failed: {heartbeat_errors[0]}")
            return result

        for wave in _plan_waves(units, hd.root):
            ids = ", ".join(str(u["id"]) for u in wave)
            key = "todo_wave_parallel" if len(wave) > 1 else "todo_wave_single"
            hd.on_text(f"  {ui.dim('│ ⋔ ' + t(key, ids=ids, n=len(wave)))}\n")
            pending = list(wave)
            order = {u["id"]: i for i, u in enumerate(wave)}
            while pending:
                board.start(u["id"] for u in pending)
                writes_by_id: dict = {u["id"]: [] for u in pending}
                workspace_stack, workspaces, cwd_by_id = self._open_round(pending, tickets, isolation)
                failures: list[tuple[dict, Exception]] = []
                outs = []
                actual_writes: dict[object, list[str]] = {}
                cancelled_cleanup = False  # 취소 전파 중 표식 — finally의 close 실패가 failed 정산을 피하게

                try:
                    outs, failures = _execute_pending(run_claimed, pending, writes_by_id, tickets, cwd_by_id)
                    if isolation:
                        outs, merged_writes, merge_failures = merge_unit_patches(outs, workspaces, writes_by_id)
                        actual_writes.update(merged_writes)
                        failures.extend(merge_failures)
                except TurnCancelled:
                    cancelled_cleanup = True
                    # 하트비트를 먼저 멈춘다 — lease를 줄인 뒤 멈추면 그 사이 갱신이 되살린다 (경합)
                    for unit in pending:
                        tickets.stop_heartbeat(unit)
                        # 배차 장부에도 이 시도가 끝났다고 적는다. 안 적으면 Dispatch가 ready로
                        # 남아 그 Task는 다시 배차되지 않는다 — 취소된 wave를 못 이어받게 된다.
                        hd.bifrost.stop_unit(unit)
                    cleanup_errors = tickets.release_unfinished(pending)
                    if cleanup_errors:
                        hd.on_text(f"  ⚠ wave claim cleanup 실패 · {len(cleanup_errors)}건\n")
                    raise
                except Exception as exc:
                    cleanup_errors = tickets.fail_unfinished(pending, exc)
                    if cleanup_errors:
                        hd.on_text(f"  ⚠ wave claim cleanup 실패 · {len(cleanup_errors)}건\n")
                    raise
                finally:
                    try:
                        try:
                            workspace_stack.close()
                        except Exception as close_error:
                            # 취소 전파 중의 close 실패는 티켓 실패 정산이 아니다 — lease 반납만
                            cleanup_errors = (
                                tickets.release_unfinished(pending)
                                if cancelled_cleanup
                                else tickets.fail_unfinished(pending, close_error)
                            )
                            if cleanup_errors:
                                hd.on_text(f"  ⚠ wave claim cleanup 실패 · {len(cleanup_errors)}건\n")
                            raise
                    finally:
                        # Capture/apply/overlap bookkeeping can raise before per-unit finish.
                        # Always reclaim every wave heartbeat before propagating any exception.
                        for unit in pending:
                            tickets.stop_heartbeat(unit)
                try:
                    outs.sort(key=lambda o: order[o[0]["id"]])  # 완료순 → 배정순 — 로그 결정론 유지
                    completion_errors = self._settle_done(led, outs, actual_writes)
                    retry, terminal = self._settle_failed(led, failures, writes_by_id, isolation, completion_errors)
                    if completion_errors:
                        raise RuntimeError("; ".join(str(error) for error in completion_errors))
                    if terminal:
                        raise terminal[0][1]
                    pending = retry
                except Exception as post_error:
                    cleanup_errors = tickets.fail_unfinished(pending, post_error)
                    if cleanup_errors:
                        raise RuntimeError(
                            f"{post_error}; claim cleanup failed: " + "; ".join(str(error) for error in cleanup_errors)
                        ) from post_error
                    raise
        led.persist()
