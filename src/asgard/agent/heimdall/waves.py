"""Worker wave 실행 — 배정 단위의 티켓 lease·격리 workspace·병렬 fan-out/fan-in.

WaveRunner 는 planning 이 정렬한 wave 를 물리 실행하는 협력자다: 티켓 claim/heartbeat/finish
수명주기, UnitWorkspace 격리·scope 검증·패치 병합, 부분 실패의 증거 보존(CUS-247)을 진다.
세션 생성·모델 선택·재시도는 오케스트레이터(hd) 표면을 쓴다.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import ExitStack

from ..session import TurnCancelled, ql
from .journal import _record_writes
from .planning import _plan_waves
from .roles import _role_prompt, _skill_support
from .toolspec import DISPATCH_TOOL


class WaveRunner:
    """배정 단위 wave 병렬 실행 협력자 — access list 격리 + 파일 겹침 직렬화."""

    def __init__(self, hd):
        self._hd = hd

    def run(self, sid: str, request: str, units: list[dict], budget_note: str) -> None:
        """배정 단위 wave 병렬 실행 — access list 격리 + 파일 겹침 직렬화.

        격리 원칙 (Fugu §3.2.2 orchestration collapse 방지): 각 단위는 자기 subtask +
        access 에 명시된 선행 단위 결과만 본다 — 같은 wave 의 다른 단위 궤적은 안 보인다.
        work 이벤트는 단위별 기록 (unit 필드), 병렬 출력은 quiet — wave 요약만 표시.

        부분 실패 (CUS-247): 한 단위가 fatal 로 죽어도 성공 단위의 ql append·writes 기록을
        먼저 확정한 뒤 예외를 전파한다 — 유실되면 디스크의 쓰기가 게이트에 orphan 으로 남는다."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from ... import ui

        hd = self._hd
        results: dict = {}  # unit id → 결과 텍스트 (access 컨텍스트 소스)
        all_writes: list[str] = []
        wrp = hd.role_rp.get("worker", hd.rp)
        used_model = f"{wrp.profile.name}:{hd._model_for('worker') or wrp.model}"

        def record_ticket(u: dict, status: str, *, error: str = "", changed_files: list[str] | None = None) -> None:
            ql(
                hd.root,
                "append",
                session=sid,
                stdin=json.dumps(
                    {
                        "role": "worker" if status != "todo" else "thinker",
                        "event": "ticket",
                        "unit": u["id"],
                        "ticket_status": status,
                        "subtask": u["subtask"],
                        "changed_files": changed_files if changed_files is not None else u.get("files", []),
                        "criteria": u.get("criteria", []),
                        "access": u.get("access", []),
                        "ticket_error": error,
                    }
                ),
            )

        ticket_policy = hd.policy.get("ticket_runtime") or {}
        lease_seconds = int(ticket_policy.get("lease_seconds") or 300)
        max_attempts = int(ticket_policy.get("max_attempts") or 3)
        isolation = bool(ticket_policy.get("isolation", True))

        def claim_ticket(u: dict) -> str:
            claimed = ql(
                hd.root,
                "ticket-claim",
                "--unit",
                str(u["id"]),
                "--worker",
                f"native:{sid}:{u['id']}",
                "--lease-seconds",
                str(lease_seconds),
                "--max-attempts",
                str(max_attempts),
                session=sid,
            )
            if claimed.returncode != 0:
                raise RuntimeError(claimed.stderr.strip() or f"ticket {u['id']} claim failed")
            return str(json.loads(claimed.stdout)["claim_token"])

        def finish_ticket(u: dict, token: str, status: str, *, error: str = "") -> str:
            args = [
                "ticket-finish",
                "--unit",
                str(u["id"]),
                "--claim-token",
                token,
                "--status",
                status,
            ]
            if error:
                args += ["--error", error[:500]]
            finished = ql(hd.root, *args, session=sid)
            if finished.returncode != 0:
                raise RuntimeError(finished.stderr.strip() or f"ticket {u['id']} finish failed")
            return str(json.loads(finished.stdout)["status"])

        def shorten_claim_lease(u: dict, token: str) -> None:
            shortened = ql(
                hd.root,
                "ticket-heartbeat",
                "--unit",
                str(u["id"]),
                "--claim-token",
                token,
                "--lease-seconds",
                "1",
                session=sid,
            )
            if shortened.returncode != 0:
                raise RuntimeError(
                    shortened.stderr.strip() or shortened.stdout.strip() or f"ticket {u['id']} lease shortening failed"
                )

        for unit in units:
            record_ticket(unit, "todo")

        def run_unit(u: dict, writes: list[str], cwd: str | None = None):
            # writes 는 호출측 소유 — 단위가 실패해도 디스패치 경유 부분 쓰기를 회수한다
            skill_note, skill_tools, skill_handlers = _skill_support("worker", hd.root)

            def mk(rp=None):
                return hd._session(
                    _role_prompt("asgard-worker.md") + hd.lagom + skill_note + hd.map_note,
                    extra_tools=[DISPATCH_TOOL, *skill_tools],
                    handlers={"dispatch": hd._dispatch_handler(sid, writes, cwd), **skill_handlers},
                    role="worker",
                    model=hd._model_for("worker"),
                    quiet=True,
                    rp_override=rp,
                    cwd=cwd,
                )

            access_ctx = "".join(
                f"\n[prior unit {a} result]\n{results[a][:1500]}\n" for a in (u.get("access") or []) if a in results
            )
            prompt = (
                f"Quest: {request}\n\nAssigned unit {u['id']}: {u['subtask']}\n"
                f"Target files: {', '.join(u['files']) or '(unspecified)'}\n"
                f"criteria: {u['criteria']}\n{access_ctx}\n"
                f"Implement only your assigned unit's scope (Canon 7) — "
                f"do not touch other units' files.{budget_note}"
            )
            fallback = (lambda: mk(rp=hd.rp)) if wrp is not hd.rp else None
            return u, hd._run_turn(mk, prompt, fallback), writes

        heartbeat_controls: dict[object, tuple[threading.Event, threading.Thread]] = {}

        def stop_heartbeat(u: dict) -> None:
            control = heartbeat_controls.pop(u["id"], None)
            if control:
                stop, beat = control
                stop.set()
                beat.join()

        def run_claimed(u: dict, writes: list[str], token: str, cwd: str | None = None):
            stop = threading.Event()
            heartbeat_error: list[str] = []

            def heartbeat() -> None:
                interval = max(1.0, min(30.0, lease_seconds / 3))
                while not stop.wait(interval):
                    try:
                        beat_result = ql(
                            hd.root,
                            "ticket-heartbeat",
                            "--unit",
                            str(u["id"]),
                            "--claim-token",
                            token,
                            "--lease-seconds",
                            str(lease_seconds),
                            session=sid,
                        )
                    except Exception as exc:
                        heartbeat_error.append(f"{type(exc).__name__}: {str(exc)[:250]}")
                        stop.set()
                        return
                    if beat_result.returncode != 0:
                        heartbeat_error.append(
                            (beat_result.stderr or beat_result.stdout or "ticket heartbeat rejected").strip()[:300]
                        )
                        stop.set()
                        return

            beat = threading.Thread(target=heartbeat, name=f"asgard-ticket-{u['id']}", daemon=True)
            beat.start()
            heartbeat_controls[u["id"]] = (stop, beat)
            # 빠른 sibling이 먼저 끝나도 느린 sibling의 fan-in·patch merge까지 lease가 살아 있어야 한다.
            # merge finally가 모든 heartbeat를 join한 직후 ticket-finish를 수행한다.
            result = run_unit(u, writes, cwd)
            if heartbeat_error:
                raise RuntimeError(f"ticket lease heartbeat failed: {heartbeat_error[0]}")
            return result

        for wave in _plan_waves(units, hd.root):
            ids = ", ".join(str(u["id"]) for u in wave)
            wave_note = "병렬 %d단위" % len(wave) if len(wave) > 1 else "단독"
            hd.on_text(f"  {ui.dim(f'│ ⋔ wave [{ids}] — {wave_note}')}\n")
            pending = list(wave)
            order = {u["id"]: i for i, u in enumerate(wave)}
            while pending:
                writes_by_id: dict = {u["id"]: [] for u in pending}
                workspace_stack = ExitStack()
                workspaces = {}
                try:
                    if isolation:
                        from ..unit_workspace import UnitWorkspace

                        for unit in pending:
                            workspaces[unit["id"]] = workspace_stack.enter_context(UnitWorkspace(hd.root, unit["id"]))
                    cwd_by_id = {unit["id"]: workspaces[unit["id"]].path if isolation else None for unit in pending}
                    claims_by_id: dict[str, str] = {}
                    for unit in pending:
                        try:
                            claims_by_id[unit["id"]] = claim_ticket(unit)
                        except Exception as claim_error:
                            # A later claim failure must not strand earlier units until lease expiry.
                            cleanup_errors: list[Exception] = []
                            for claimed in pending:
                                token = claims_by_id.get(claimed["id"])
                                if token:
                                    try:
                                        finish_ticket(
                                            claimed, token, "failed", error="wave claim aborted before dispatch"
                                        )
                                    except Exception as cleanup_error:
                                        cleanup_errors.append(cleanup_error)
                                        try:
                                            shorten_claim_lease(claimed, token)
                                        except Exception as expiry_error:
                                            cleanup_errors.append(expiry_error)
                            if cleanup_errors:
                                raise RuntimeError(
                                    f"{claim_error}; claim cleanup failed: "
                                    + "; ".join(str(error) for error in cleanup_errors)
                                ) from claim_error
                            raise
                except Exception:
                    workspace_stack.close()
                    raise
                failures: list[tuple[dict, Exception]] = []
                outs = []
                actual_writes: dict[object, list[str]] = {}
                finished_claims: set[str] = set()
                cancelled_cleanup = False  # 취소 전파 중 표식 — finally 의 close 실패가 failed 정산을 피하게

                def settle_ticket(u: dict, status: str, *, error: str = "") -> str:
                    token = claims_by_id[u["id"]]
                    final = finish_ticket(u, token, status, error=error)
                    finished_claims.add(token)
                    return final

                def release_unfinished(candidates: list[dict]) -> list[Exception]:
                    """취소 전용 — 티켓을 failed 로 정산하지 않고 lease 만 반납한다.
                    취소는 실패가 아니다: 재개(resume)가 같은 티켓을 그대로 재클레임할 수 있어야 한다."""
                    cleanup_errors: list[Exception] = []
                    for candidate in candidates:
                        token = claims_by_id.get(candidate["id"])
                        if not token or token in finished_claims:
                            continue
                        try:
                            shorten_claim_lease(candidate, token)
                        except Exception as expiry_error:
                            cleanup_errors.append(expiry_error)
                    return cleanup_errors

                def fail_unfinished(candidates: list[dict], error: BaseException) -> list[Exception]:
                    cleanup_errors: list[Exception] = []
                    for candidate in candidates:
                        token = claims_by_id.get(candidate["id"])
                        if not token or token in finished_claims:
                            continue
                        try:
                            settle_ticket(
                                candidate,
                                "failed",
                                error=f"{error.__class__.__name__}: {str(error)[:400]}",
                            )
                        except Exception as cleanup_error:
                            cleanup_errors.append(cleanup_error)
                            # If ticket-finish itself is unavailable, stop renewing and shorten
                            # the still-valid claim so resume is blocked for at most one second.
                            try:
                                shorten_claim_lease(candidate, token)
                            except Exception as expiry_error:
                                cleanup_errors.append(expiry_error)
                    return cleanup_errors

                try:
                    if len(pending) == 1:
                        u0 = pending[0]
                        try:
                            outs = [
                                run_claimed(
                                    u0,
                                    writes_by_id[u0["id"]],
                                    claims_by_id[u0["id"]],
                                    cwd_by_id[u0["id"]],
                                )
                            ]
                        except TurnCancelled:
                            raise  # 취소는 티켓 실패가 아니다 — 재배정 예산을 소모하지 않고 전파
                        except Exception as e:
                            failures.append((u0, e))
                    else:
                        with ThreadPoolExecutor(max_workers=min(3, len(pending))) as ex:
                            # ex.map 금지 — lazy 예외 재발생이 성공 단위 후처리까지 끊는다 (CUS-247)
                            futs = {
                                ex.submit(
                                    run_claimed,
                                    u,
                                    writes_by_id[u["id"]],
                                    claims_by_id[u["id"]],
                                    cwd_by_id[u["id"]],
                                ): u
                                for u in pending
                            }
                            for fut in as_completed(futs):
                                try:
                                    outs.append(fut.result())
                                except TurnCancelled:
                                    raise  # 취소는 티켓 실패가 아니다 — 공유 이벤트로 나머지도 곧 멈춘다
                                except Exception as e:
                                    failures.append((futs[fut], e))
                    if isolation:
                        from ..unit_workspace import WorkspaceError

                        patches = {
                            u["id"]: workspaces[u["id"]].capture(
                                extra_paths=tuple(writes_by_id[u["id"]])
                                + tuple(path for path in r.writes if path not in writes_by_id[u["id"]])
                            )
                            for u, r, _ in outs
                        }
                        scope_failed = set()
                        for u, _, _ in outs:
                            declared = [os.path.normpath(str(path)).replace(os.sep, "/") for path in u["files"]]
                            outside = [
                                path
                                for path in patches[u["id"]].paths
                                if not any(
                                    path == allowed or path.startswith(allowed.rstrip("/") + "/")
                                    for allowed in declared
                                )
                            ]
                            if outside:
                                scope_failed.add(u["id"])
                                failures.append((u, WorkspaceError("scope violation: " + ", ".join(sorted(outside)))))
                        outs = [out for out in outs if out[0]["id"] not in scope_failed]
                        path_owners: dict[str, list[dict]] = {}
                        for u, _, _ in outs:
                            for path in patches[u["id"]].paths:
                                path_owners.setdefault(path, []).append(u)
                        conflicted = {u["id"] for owners in path_owners.values() if len(owners) > 1 for u in owners}
                        kept = []
                        for out in outs:
                            u = out[0]
                            if u["id"] in conflicted:
                                paths = sorted(
                                    path for path, owners in path_owners.items() if u in owners and len(owners) > 1
                                )
                                failures.append((u, WorkspaceError("actual path overlap: " + ", ".join(paths))))
                                continue
                            try:
                                workspaces[u["id"]].apply(patches[u["id"]])
                                actual_writes[u["id"]] = list(patches[u["id"]].paths)
                                kept.append(out)
                            except Exception as e:
                                failures.append((u, e))
                        outs = kept
                except TurnCancelled:
                    cancelled_cleanup = True
                    # 하트비트를 먼저 멈춘다 — lease 를 줄인 뒤 멈추면 그 사이 갱신이 되살린다 (경합)
                    for unit in pending:
                        stop_heartbeat(unit)
                    cleanup_errors = release_unfinished(pending)
                    if cleanup_errors:
                        hd.on_text(f"  ⚠ wave claim cleanup 실패 · {len(cleanup_errors)}건\n")
                    raise
                except Exception as exc:
                    cleanup_errors = fail_unfinished(pending, exc)
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
                                release_unfinished(pending)
                                if cancelled_cleanup
                                else fail_unfinished(pending, close_error)
                            )
                            if cleanup_errors:
                                hd.on_text(f"  ⚠ wave claim cleanup 실패 · {len(cleanup_errors)}건\n")
                            raise
                    finally:
                        # Capture/apply/overlap bookkeeping can raise before per-unit finish.
                        # Always reclaim every wave heartbeat before propagating any exception.
                        for unit in pending:
                            stop_heartbeat(unit)
                try:
                    outs.sort(key=lambda o: order[o[0]["id"]])  # 완료순 → 배정순 — 로그 결정론 유지
                    completion_errors: list[Exception] = []
                    for u, r, writes in outs:
                        unit_writes = actual_writes.get(u["id"], writes + [w for w in r.writes if w not in writes])
                        all_writes.extend(w for w in unit_writes if w not in all_writes)
                        # Persist the write sentinel before a potentially failing ticket-finish call.
                        _record_writes(hd.root, sid, all_writes)
                        results[u["id"]] = r.text[-2000:]
                        unit_note = f"│ 단위 {u['id']} 완료 · 파일 {len(unit_writes)}개"
                        hd.on_text(f"  {ui.dim(unit_note)}\n")
                        try:
                            settle_ticket(u, "done")
                        except Exception as e:
                            # One ticket-control failure must not prevent sibling units' durable
                            # work events and ticket completions from being recorded.
                            completion_errors.append(e)
                        finally:
                            stop_heartbeat(u)
                        work_event = ql(
                            hd.root,
                            "append",
                            session=sid,
                            stdin=json.dumps(
                                {
                                    "role": "worker",
                                    "event": "work",
                                    "unit": u["id"],
                                    "changed_files": unit_writes[:50],
                                    "commands": r.commands[-20:],
                                    "model": used_model,
                                }
                            ),
                        )
                        if work_event.returncode != 0:
                            completion_errors.append(
                                RuntimeError(work_event.stderr.strip() or f"ticket {u['id']} work event append failed")
                            )
                    retry: list[dict] = []
                    terminal: list[tuple[dict, Exception]] = []
                    if failures:
                        # 공유 root 경로에서는 실패 단위의 부분 쓰기도 증거로 남긴다. 격리 workspace의
                        # 실패 delta는 폐기됐으므로 canonical write sentinel에 거짓 기록하지 않는다.
                        if not isolation:
                            for u, _ in failures:
                                all_writes.extend(w for w in writes_by_id[u["id"]] if w not in all_writes)
                        _record_writes(hd.root, sid, all_writes)
                        for u, e in failures:
                            try:
                                final = settle_ticket(
                                    u,
                                    "failed",
                                    error=f"{e.__class__.__name__}: {str(e)[:400]}",
                                )
                            except Exception as finish_error:
                                completion_errors.append(finish_error)
                                continue
                            finally:
                                stop_heartbeat(u)
                            if final == "failed":
                                retry.append(u)
                                hd.on_text(f"  ⚠ 단위 {u['id']} 실패 — 재배정 예정 ({e.__class__.__name__})\n")
                            else:
                                terminal.append((u, e))
                                hd.on_text(f"  ⚠ 단위 {u['id']} 실패 — retry budget 소진\n")
                    if completion_errors:
                        raise RuntimeError("; ".join(str(error) for error in completion_errors))
                    if terminal:
                        raise terminal[0][1]
                    pending = retry
                except Exception as post_error:
                    cleanup_errors = fail_unfinished(pending, post_error)
                    if cleanup_errors:
                        raise RuntimeError(
                            f"{post_error}; claim cleanup failed: " + "; ".join(str(error) for error in cleanup_errors)
                        ) from post_error
                    raise
        _record_writes(hd.root, sid, all_writes)
