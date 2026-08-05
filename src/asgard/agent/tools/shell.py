"""도구 — 셸 실행. 앞단 판정을 통과한 명령을 돌리고, 꼬리만 남겨 되돌린다. 배경 프로세스 포함."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections import deque

from ._core import _MAX_OUT, _TIMEOUT, ToolError, _cap, _dedup_log
from .guards import validate_bash_command


class _TailBuffer:
    """실행 중 상한이 걸리는 꼬리 버퍼 — 출력 폭주가 RAM을 인질로 잡지 않게 읽는 즉시 버린다.
    bash는 오류·실패 사유가 끝에 몰리므로 꼬리 보존 (view는 머리 유지 _cap)."""

    def __init__(self, limit: int = _MAX_OUT) -> None:
        self.limit = limit
        self.parts: deque[str] = deque()
        self.size = 0
        self.dropped = 0
        self._lock = threading.Lock()

    def add(self, chunk: str) -> None:
        with self._lock:
            self.parts.append(chunk)
            self.size += len(chunk)
            while self.size > self.limit and len(self.parts) > 1:
                old = self.parts.popleft()
                self.size -= len(old)
                self.dropped += len(old)
            if self.size > self.limit:  # 단일 청크가 상한 초과 — 청크 안에서 꼬리만 남긴다
                only = self.parts[0]
                cut = self.size - self.limit
                self.parts[0] = only[cut:]
                self.size -= cut
                self.dropped += cut

    def text(self) -> str:
        with self._lock:
            body = "".join(self.parts)
            if self.dropped:
                return f"[... 앞 {self.dropped} chars 절단]\n" + body
            return body


def _kill_group(p: subprocess.Popen) -> None:
    """프로세스 그룹 전체 종료(손자 포함) — SIGTERM 유예 2s 후 그룹에 무조건 SIGKILL.
    셸 부모가 먼저 죽고 손자만 SIGTERM을 무시하는 경우를 놓치지 않는다. Windows는 트리 킬."""
    if os.name != "posix":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        except OSError:
            pass
        return
    try:
        pgid = os.getpgid(p.pid)
    except ProcessLookupError, PermissionError, OSError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    except ProcessLookupError, PermissionError, OSError:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError, PermissionError, OSError:
        pass


def run_bash(root: str, tool_input: dict, cancel: threading.Event | None = None) -> tuple[str, int | None]:
    """(output, exit_code). exit_code는 퀘스트 로그 commands 증거용.
    cancel 이벤트가 켜지면 프로세스 그룹째 종료 — 취소는 즉시성이 생명이라 0.2s 폴링."""
    if tool_input.get("restart"):
        return "shell restarted (stateless — cwd는 프로젝트 루트 고정)", 0
    cmd = str(tool_input.get("command") or "")
    if not cmd.strip():
        raise ToolError("빈 명령")
    blocked = validate_bash_command(root, cmd)
    if blocked:
        raise ToolError(blocked)
    group: dict = {"start_new_session": True} if os.name == "posix" else {}
    # 이 명령은 **에이전트를 대신해** 도는 것이라, 그 안에서 `asgard …`를 부르면 같은 에이전트로
    # 돌아야 한다. 안 넘기면 끈끈한 활성으로 떨어져 남의 홈에 쓴다. 얹는 것은 아스가르드
    # 이름공간의 두 키뿐이라 사용자 명령의 나머지 환경은 그대로다.
    from ...profiles import subprocess_env

    p = subprocess.Popen(
        cmd,
        shell=True,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=subprocess_env(),
        **group,
    )
    out_buf, err_buf = _TailBuffer(), _TailBuffer(4000)
    readers = [
        threading.Thread(target=_pump, args=(p.stdout, out_buf), daemon=True),
        threading.Thread(target=_pump, args=(p.stderr, err_buf), daemon=True),
    ]
    for r in readers:
        r.start()
    deadline = time.monotonic() + _TIMEOUT
    try:
        while True:
            try:
                p.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    _kill_group(p)
                    raise ToolError(f"사용자 취소 — 명령 중단 (프로세스 그룹 종료){_tail_note(out_buf, err_buf)}")
                if time.monotonic() > deadline:
                    _kill_group(p)
                    raise ToolError(
                        f"타임아웃 ({_TIMEOUT}s) — 장기 실행은 분할하거나 백그라운드로{_tail_note(out_buf, err_buf)}"
                    )
    except BaseException:  # KeyboardInterrupt 포함 — 분리된 프로세스 그룹을 절대 고아로 남기지 않는다
        if p.poll() is None:
            _kill_group(p)
        raise
    finally:
        for r in readers:
            r.join(timeout=5)
    stdout = out_buf.text()
    if p.returncode == 0:
        stdout = _dedup_log(stdout)
    out = stdout + (("\n" + err_buf.text()) if err_buf.size or err_buf.dropped else "")
    return out.strip() or f"(no output, exit {p.returncode})", p.returncode


class BackgroundProcessManager:
    """Small session-owned process table; never leaves child processes behind."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def run(self, root: str, tool_input: dict, cancel: threading.Event | None = None) -> str:
        action = str(tool_input.get("action") or "")
        if action == "list":
            with self._lock:
                jobs = list(self._jobs.items())
            if not jobs:
                return "background processes: none"
            return "\n".join(self._summary(process_id, job) for process_id, job in jobs)

        process_id = str(tool_input.get("process_id") or "")
        if action in {"poll", "stop"}:
            with self._lock:
                job = self._jobs.get(process_id)
            if job is None:
                raise ToolError(f"알 수 없는 process_id: {process_id}")
            if action == "stop":
                if job["process"].poll() is None:
                    _kill_group(job["process"])
                return self._render(process_id, job)
            wait_seconds = float(tool_input.get("wait_seconds") or 0)
            if not 0 <= wait_seconds <= 10:
                raise ToolError("wait_seconds는 0..10이어야 합니다")
            deadline = time.monotonic() + wait_seconds
            while job["process"].poll() is None and time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    raise ToolError("사용자 취소 — poll 중단")
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            return self._render(process_id, job)

        if action != "start":
            raise ToolError("action은 start|poll|list|stop 중 하나여야 합니다")
        command = str(tool_input.get("command") or "")
        if not command.strip():
            raise ToolError("start에는 command가 필요합니다")
        blocked = validate_bash_command(root, command)
        if blocked:
            raise ToolError(blocked)
        with self._lock:
            if sum(job["process"].poll() is None for job in self._jobs.values()) >= 8:
                raise ToolError("동시 백그라운드 프로세스 상한(8)에 도달했습니다")
            process_id = f"p{self._next_id}"
            self._next_id += 1
        group: dict = {"start_new_session": True} if os.name == "posix" else {}
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **group,
        )
        job = {"process": process, "command": command, "out": _TailBuffer(), "err": _TailBuffer(4000)}
        job["readers"] = [
            threading.Thread(target=_pump, args=(process.stdout, job["out"]), daemon=True),
            threading.Thread(target=_pump, args=(process.stderr, job["err"]), daemon=True),
        ]
        for reader in job["readers"]:
            reader.start()
        with self._lock:
            self._jobs[process_id] = job
        time.sleep(0.05)
        return self._render(process_id, job)

    def close(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job["process"].poll() is None:
                _kill_group(job["process"])
            for reader in job.get("readers", ()):
                reader.join(timeout=1)

    @staticmethod
    def _summary(process_id: str, job: dict) -> str:
        code = job["process"].poll()
        state = "running" if code is None else f"exited({code})"
        return f"{process_id} · {state} · {job['command'][:160]}"

    def _render(self, process_id: str, job: dict) -> str:
        output = job["out"].text()
        if job["process"].poll() in {None, 0}:
            output = _dedup_log(output)
        errors = job["err"].text()
        body = output + (("\n" + errors) if errors else "")
        return _cap(self._summary(process_id, job) + (f"\n{body.strip()}" if body.strip() else "\n(no output)"))


def _pump(pipe, buf: _TailBuffer) -> None:
    """파이프 → 꼬리 버퍼 상시 배수 — 자식이 파이프 블로킹으로 멈추는 것도 함께 방지."""
    try:
        for chunk in iter(lambda: pipe.read(8192), ""):
            buf.add(chunk)
    except OSError, ValueError:
        pass


def _tail_note(out_buf: _TailBuffer, err_buf: _TailBuffer) -> str:
    partial = (out_buf.text() + "\n" + err_buf.text()).strip()
    return f"\n[중단 시점 출력 꼬리]\n{partial[-2000:]}" if partial else ""
