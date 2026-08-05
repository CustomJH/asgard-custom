"""티켓 lease 수명주기 — claim·heartbeat·finish와 그 정리 경로.

`WaveRunner.run`에서 들어낸 이유: 한 함수 안에 서로 다른 두 가지가 있었다. 하나는 "이 wave를
어떻게 병렬로 돌리고 패치를 어떻게 합치는가"이고, 다른 하나는 "누가 이 단위를 쥐고 있는가, 언제
놓는가"다. 둘이 섞여 있으면 정리 경로가 특히 위험해진다 — 취소·실패·close 실패마다 lease를
어떻게 되돌릴지가 조금씩 다른데, 그 미묘한 차이가 475행 본문 안쪽 깊은 곳에 흩어져 있었다.

이 모듈이 지는 계약은 하나다: **claim 한 것은 반드시 어떤 경로로든 놓는다.** 놓는 방법은 셋이고
의미가 다르다 — done/failed 정산(`settle`), 실패 일괄 정산(`fail_unfinished`), 그리고 lease만
반납(`release_unfinished`). 마지막 것이 취소 전용인 이유는 취소가 실패가 아니기 때문이다: 재개가
같은 티켓을 그대로 재클레임할 수 있어야 하므로 재시도 예산을 소모시키면 안 된다.

하트비트는 lease를 살려두는 배경 스레드다. 멈추는 순서가 중요하다 — lease를 줄인 뒤에 멈추면
그 사이의 갱신이 줄인 것을 되살린다. 그래서 취소 경로는 항상 **먼저 멈추고 그다음 반납**한다.
"""

from __future__ import annotations

import json
import threading

from ..quest_bridge import ql


class TicketLease:
    """한 세션의 티켓 수명주기. wave 반복마다 `begin_wave()`로 claim 장부를 새로 연다."""

    def __init__(self, hd, sid: str, *, lease_seconds: int, max_attempts: int) -> None:
        self._hd = hd
        self._sid = sid
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._claims: dict[str, str] = {}
        self._finished: set[str] = set()
        self._beats: dict[str, tuple[threading.Event, threading.Thread]] = {}

    # ── 기록 ────────────────────────────────────────────────────────

    def record(self, unit: dict, status: str, *, error: str = "", changed_files: list[str] | None = None) -> None:
        ql(
            self._hd.root,
            "append",
            session=self._sid,
            stdin=json.dumps(
                {
                    "role": "worker" if status != "todo" else "thinker",
                    "event": "ticket",
                    "unit": unit["id"],
                    "ticket_status": status,
                    "subtask": unit["subtask"],
                    "changed_files": changed_files if changed_files is not None else unit.get("files", []),
                    "criteria": unit.get("criteria", []),
                    "access": unit.get("access", []),
                    "ticket_error": error,
                }
            ),
        )

    # ── claim ───────────────────────────────────────────────────────

    def begin_wave(self) -> None:
        self._claims.clear()
        self._finished.clear()

    def token(self, unit: dict) -> str | None:
        return self._claims.get(unit["id"])

    def claim_all(self, pending: list[dict]) -> None:
        """전부 claim 하거나, 실패하면 이미 쥔 것을 전부 놓고 올린다.

        뒤늦은 claim 실패가 앞선 단위를 lease 만료까지 붙잡아 두면 안 된다 — 그 사이 재개도
        재배정도 막힌다.
        """
        for unit in pending:
            try:
                self._claims[unit["id"]] = self._claim(unit)
            except Exception as claim_error:
                errors = self._abort_claimed(pending)
                if errors:
                    raise RuntimeError(
                        f"{claim_error}; claim cleanup failed: " + "; ".join(str(error) for error in errors)
                    ) from claim_error
                raise

    def _abort_claimed(self, pending: list[dict]) -> list[Exception]:
        errors: list[Exception] = []
        for claimed in pending:
            token = self._claims.get(claimed["id"])
            if not token:
                continue
            try:
                self._finish(claimed, token, "failed", error="wave claim aborted before dispatch")
            except Exception as cleanup_error:
                errors.append(cleanup_error)
                errors.extend(self._shorten_quietly(claimed, token))
        return errors

    # ── 정산 ────────────────────────────────────────────────────────

    def settle(self, unit: dict, status: str, *, error: str = "") -> str:
        token = self._claims[unit["id"]]
        final = self._finish(unit, token, status, error=error)
        self._finished.add(token)
        return final

    def fail_unfinished(self, candidates: list[dict], error: BaseException) -> list[Exception]:
        """아직 안 놓은 것을 failed로 정산 — 재시도 예산을 소모한다."""
        errors: list[Exception] = []
        for candidate in self._unfinished(candidates):
            token = self._claims[candidate["id"]]
            try:
                self.settle(candidate, "failed", error=f"{error.__class__.__name__}: {str(error)[:400]}")
            except Exception as cleanup_error:
                errors.append(cleanup_error)
                # ticket-finish 자체가 불가하면 갱신을 멈추고 lease를 줄여, 재개 차단을 1초로 막는다
                errors.extend(self._shorten_quietly(candidate, token))
        return errors

    def release_unfinished(self, candidates: list[dict]) -> list[Exception]:
        """취소 전용 — failed로 정산하지 않고 lease만 반납한다.

        취소는 실패가 아니다: 재개가 같은 티켓을 그대로 재클레임할 수 있어야 한다.
        """
        errors: list[Exception] = []
        for candidate in self._unfinished(candidates):
            errors.extend(self._shorten_quietly(candidate, self._claims[candidate["id"]]))
        return errors

    def _unfinished(self, candidates: list[dict]) -> list[dict]:
        return [c for c in candidates if self._claims.get(c["id"]) and self._claims[c["id"]] not in self._finished]

    # ── 하트비트 ────────────────────────────────────────────────────

    def start_heartbeat(self, unit: dict, token: str) -> list[str]:
        """갱신 스레드를 띄우고 **에러 수집함**을 돌려준다 — 호출부가 단위 종료 시 확인한다."""
        stop = threading.Event()
        errors: list[str] = []
        beat = threading.Thread(
            target=self._beat_until, args=(unit, token, stop, errors), name=f"asgard-ticket-{unit['id']}", daemon=True
        )
        beat.start()
        self._beats[unit["id"]] = (stop, beat)
        return errors

    def stop_heartbeat(self, unit: dict) -> None:
        control = self._beats.pop(unit["id"], None)
        if not control:
            return
        stop, beat = control
        stop.set()
        beat.join()

    def _beat_until(self, unit: dict, token: str, stop: threading.Event, errors: list[str]) -> None:
        interval = max(1.0, min(30.0, self._lease_seconds / 3))
        while not stop.wait(interval):
            failure = self._beat_once(unit, token)
            if failure:
                errors.append(failure)
                stop.set()
                return

    def _beat_once(self, unit: dict, token: str) -> str | None:
        try:
            result = self._ticket("ticket-heartbeat", unit, token, "--lease-seconds", str(self._lease_seconds))
        except Exception as exc:
            return f"{type(exc).__name__}: {str(exc)[:250]}"
        if result.returncode != 0:
            return (result.stderr or result.stdout or "ticket heartbeat rejected").strip()[:300]
        return None

    # ── quest-log 호출 ──────────────────────────────────────────────

    def _claim(self, unit: dict) -> str:
        claimed = ql(
            self._hd.root,
            "ticket-claim",
            "--unit",
            str(unit["id"]),
            "--worker",
            f"native:{self._sid}:{unit['id']}",
            "--lease-seconds",
            str(self._lease_seconds),
            "--max-attempts",
            str(self._max_attempts),
            session=self._sid,
        )
        if claimed.returncode != 0:
            raise RuntimeError(claimed.stderr.strip() or f"ticket {unit['id']} claim failed")
        return str(json.loads(claimed.stdout)["claim_token"])

    def _finish(self, unit: dict, token: str, status: str, *, error: str = "") -> str:
        args = ["--status", status]
        if error:
            args += ["--error", error[:500]]
        finished = self._ticket("ticket-finish", unit, token, *args)
        if finished.returncode != 0:
            raise RuntimeError(finished.stderr.strip() or f"ticket {unit['id']} finish failed")
        return str(json.loads(finished.stdout)["status"])

    def _shorten_quietly(self, unit: dict, token: str) -> list[Exception]:
        try:
            self._shorten(unit, token)
        except Exception as expiry_error:
            return [expiry_error]
        return []

    def _shorten(self, unit: dict, token: str) -> None:
        shortened = self._ticket("ticket-heartbeat", unit, token, "--lease-seconds", "1")
        if shortened.returncode != 0:
            raise RuntimeError(
                shortened.stderr.strip() or shortened.stdout.strip() or f"ticket {unit['id']} lease shortening failed"
            )

    def _ticket(self, verb: str, unit: dict, token: str, *extra: str):
        return ql(self._hd.root, verb, "--unit", str(unit["id"]), "--claim-token", token, *extra, session=self._sid)
