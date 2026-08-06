"""로컬 코딩 에이전트의 bounded 왕복과 검증을 조정한다."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import threading
import uuid
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field

from .. import errors
from .. import orchestration as orc
from ..agent.runtime import CliPeerRuntime, PeerRuntime, PeerSpec, PeerTurnResult

try:  # pragma: no cover - 플랫폼별 import 갈래
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # ty: ignore[invalid-assignment] — 플랫폼에 없는 모듈의 자리표시자

try:  # pragma: no cover - 플랫폼별 import 갈래
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # ty: ignore[invalid-assignment] — 플랫폼에 없는 모듈의 자리표시자

_CHECKPOINT_KIND = "asgard.swarm.checkpoint"
_CHECKPOINT_SUBJECT = "swarm session checkpoint"
_CHECKPOINT_VERSION = 1
_LEASES_DIR = "swarm-leases"
_THREAD_LEASES: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
_THREAD_LEASES_GUARD = threading.Lock()


@dataclass(frozen=True, slots=True)
class SwarmRequest:
    """CLI가 넘긴 멀티 모델 실행 선택값이다."""

    prompt: str | None
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    json_out: bool = False
    resume: bool = False
    quest_id: str | None = None
    dual: bool = False
    cc: bool = False
    codex: bool = False
    cc_model: str | None = None
    cc_effort: str | None = None
    codex_model: str | None = None
    codex_effort: str | None = None
    rounds: int = 2
    synth: str | None = None
    verify_commands: list[str] | None = None
    keep_open: bool = False
    swarm_run: str | None = None

    @property
    def text(self) -> str:
        """peer 에게 보낼 작업 문장. `_validate_common` 이 이미 빈 값을 걸렀다.

        `prompt` 를 직접 쓰지 않는 이유는 그 필드가 `str | None` 이고, 그 검사가 다른 함수에
        있어 호출 지점마다 다시 좁혀야 하기 때문이다."""
        return (self.prompt or "").strip()

    def requested(self) -> bool:
        """네이티브 단일 실행이 아니라 swarm 옵션을 골랐는지 반환한다."""
        return any(
            (
                self.cc,
                self.codex,
                self.cc_model,
                self.cc_effort,
                self.codex_model,
                self.codex_effort,
                self.effort,
                self.rounds != 2,
                self.synth,
                self.verify_commands,
                self.keep_open,
                self.swarm_run is not None,
            )
        )


@dataclass(frozen=True, slots=True)
class _Peer:
    spec: PeerSpec
    task_id: str
    dispatch_id: str

    @property
    def runtime(self) -> str:
        return self.spec.runtime


@dataclass(slots=True)
class _State:
    root: str
    request: SwarmRequest
    runtime: PeerRuntime
    command_runner: Callable[..., object]
    run_id: str
    invocation_id: str
    peers: list[_Peer] = field(default_factory=list)
    sessions: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    message_ids: list[str] = field(default_factory=list)
    settled: set[str] = field(default_factory=set)


def run_swarm(
    request: SwarmRequest,
    *,
    peer_runtime: PeerRuntime | None = None,
    verification_runner: Callable[..., object] | None = None,
) -> int:
    """선택한 peer를 왕복 실행하고 한 결론과 순차 검증 결과를 출력한다."""
    root = os.getcwd()
    canonical_run_id = request.swarm_run.strip() if request.swarm_run is not None else None
    with _resume_lease(root, canonical_run_id):
        specs, synthesizer, commands, sessions = _prepare(request, root, canonical_run_id)
        os.environ.setdefault("ASGARD_UNATTENDED", "1")
        run_id = canonical_run_id or ""
        if not run_id:
            run = orc.run_create(root, request.text, coordinator="asgard-run")
            run_id = run["id"]
        state = _State(
            root=root,
            request=request,
            runtime=peer_runtime or CliPeerRuntime(root),
            command_runner=verification_runner or subprocess.run,
            run_id=run_id,
            invocation_id=uuid.uuid4().hex[:12],
            sessions=sessions,
        )
        checkpoint_saved = False
        try:
            _open_peers(state, specs)
            _exchange(state)
            conclusion = _conclude(state, synthesizer)
            _settle_successes(state, synthesizer, conclusion)
            _save_checkpoint(state, synthesizer)
            checkpoint_saved = True
            verification, ok = _verify_all(state, commands)
            return _render(state, synthesizer, conclusion, verification, ok)
        finally:
            if canonical_run_id is None and (not request.keep_open or not checkpoint_saved):
                orc.run_close(root, state.run_id)


@contextmanager
def _resume_lease(root: str, run_id: str | None):
    """같은 열린 Run의 checkpoint 소비와 갱신을 프로세스 사이에서도 직렬화한다."""
    if run_id is None:
        yield
        return
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    lease_dir = os.path.join(os.path.abspath(root), ".asgard", _LEASES_DIR)
    os.makedirs(lease_dir, mode=0o700, exist_ok=True)
    path = os.path.join(lease_dir, f"{digest}.lock")
    with _THREAD_LEASES_GUARD:
        thread_lease = _THREAD_LEASES.setdefault(path, threading.Lock())
    with thread_lease:
        with _file_lease(path):
            yield


@contextmanager
def _file_lease(path: str):
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - 지원 플랫폼에는 둘 중 하나가 있다.
            raise errors.Unavailable(
                "swarm Run을 안전하게 잠글 수 없는 플랫폼이에요.",
                remedy="fcntl 또는 msvcrt 파일 잠금을 제공하는 Python에서 다시 실행하세요.",
            )
        acquired = True
        yield
    finally:
        if acquired and fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif acquired and msvcrt is not None:  # pragma: no cover - Windows
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        os.close(fd)


def _prepare(
    request: SwarmRequest,
    root: str,
    canonical_run_id: str | None,
) -> tuple[list[PeerSpec], str, list[list[str]], dict[str, str]]:
    _validate_common(request)
    if request.swarm_run is not None:
        _validate_resume_options(request, canonical_run_id)
        specs, saved_synthesizer, sessions = _load_checkpoint(root, canonical_run_id or "")
        synthesizer = (request.synth or saved_synthesizer).strip().lower()
    else:
        _validate_new_options(request)
        specs = _peer_specs(request)
        sessions = {}
        synthesizer = (request.synth or ("codex" if request.codex else "cc")).strip().lower()
    runtimes = {spec.runtime for spec in specs}
    if synthesizer not in runtimes:
        raise errors.InvalidInput(
            f"결론 담당 runtime이 선택 목록에 없어요: {synthesizer}",
            remedy=f"--synth를 {' 또는 '.join(sorted(runtimes))} 중 하나로 지정하세요.",
        )
    return specs, synthesizer, _parse_commands(request.verify_commands or []), sessions


def _validate_common(request: SwarmRequest) -> None:
    if not request.prompt or not request.prompt.strip():
        raise errors.InvalidInput(
            "swarm에 보낼 작업이 비어 있어요.",
            remedy='`asgard run "<작업>" --cc`처럼 작업을 함께 적으세요.',
        )
    if request.rounds < 1 or request.rounds > 3:
        raise errors.InvalidInput(
            f"--rounds는 1부터 3까지여야 해요: {request.rounds}",
            remedy="--rounds 1, 2, 3 중 하나를 사용하세요.",
        )


def _validate_new_options(request: SwarmRequest) -> None:
    incompatible = [
        flag
        for value, flag in (
            (request.provider, "--provider"),
            (request.resume, "--resume"),
            (request.quest_id, "--quest"),
            (request.dual, "--dual"),
        )
        if value
    ]
    if incompatible:
        raise errors.InvalidInput(
            f"swarm 선택과 함께 쓸 수 없는 옵션이에요: {', '.join(incompatible)}",
            remedy="각 peer에는 --cc-model/--cc-effort 또는 --codex-model/--codex-effort를 사용하세요.",
        )
    _validate_targets(request)


def _validate_resume_options(request: SwarmRequest, canonical_run_id: str | None) -> None:
    if not canonical_run_id:
        raise errors.InvalidInput(
            "재개할 swarm Run ID가 비어 있어요.",
            remedy="--swarm-run에 최초 실행이 반환한 run_id를 적으세요.",
        )
    incompatible = [
        flag
        for value, flag in (
            (request.provider, "--provider"),
            (request.model, "--model"),
            (request.effort, "--effort"),
            (request.resume, "--resume"),
            (request.quest_id, "--quest"),
            (request.dual, "--dual"),
            (request.cc, "--cc"),
            (request.codex, "--codex"),
            (request.cc_model, "--cc-model"),
            (request.cc_effort, "--cc-effort"),
            (request.codex_model, "--codex-model"),
            (request.codex_effort, "--codex-effort"),
            (request.keep_open, "--keep-open"),
        )
        if value
    ]
    if incompatible:
        raise errors.InvalidInput(
            f"저장된 swarm을 재개할 때 다시 지정할 수 없는 옵션이에요: {', '.join(incompatible)}",
            remedy="peer와 모델은 checkpoint에서 복원됩니다. --rounds, --synth, --verify만 다시 지정하세요.",
        )


def _validate_targets(request: SwarmRequest) -> None:
    if (request.cc_model or request.cc_effort) and not request.cc:
        raise errors.InvalidInput(
            "Claude Code 세부 옵션을 썼지만 --cc를 선택하지 않았어요.",
            remedy="--cc를 추가하거나 --cc-model/--cc-effort를 제거하세요.",
        )
    if (request.codex_model or request.codex_effort) and not request.codex:
        raise errors.InvalidInput(
            "Codex 세부 옵션을 썼지만 --codex를 선택하지 않았어요.",
            remedy="--codex를 추가하거나 --codex-model/--codex-effort를 제거하세요.",
        )
    if not request.cc and not request.codex:
        raise errors.InvalidInput(
            "swarm runtime을 선택하지 않았어요.",
            remedy="--cc 또는 --codex를 하나 이상 추가하세요.",
        )
    if request.cc and request.codex and (request.model or request.effort):
        raise errors.InvalidInput(
            "두 runtime을 선택한 상태에서는 --model/--effort의 대상을 알 수 없어요.",
            remedy="--cc-model/--cc-effort와 --codex-model/--codex-effort로 각각 지정하세요.",
        )


def _peer_specs(request: SwarmRequest) -> list[PeerSpec]:
    specs = []
    if request.cc:
        specs.append(
            PeerSpec(
                "cc",
                (request.cc_model or request.model or "").strip(),
                (request.cc_effort or request.effort or "").strip(),
            )
        )
    if request.codex:
        specs.append(
            PeerSpec(
                "codex",
                (request.codex_model or request.model or "").strip(),
                (request.codex_effort or request.effort or "").strip(),
            )
        )
    return specs


def _parse_commands(commands: list[str]) -> list[list[str]]:
    parsed = []
    for command in commands:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise errors.InvalidInput(
                f"검증 명령의 따옴표가 닫히지 않았어요: {command}",
                remedy="각 --verify 값을 셸 명령 하나가 되도록 다시 적으세요.",
                cause=exc,
            ) from exc
        if not argv:
            raise errors.InvalidInput(
                "빈 검증 명령은 실행할 수 없어요.",
                remedy="빈 --verify를 제거하거나 실행할 명령을 적으세요.",
            )
        parsed.append(argv)
    return parsed


def _open_peers(state: _State, specs: list[PeerSpec]) -> None:
    for spec in specs:
        task = orc.task_create(
            state.root,
            state.run_id,
            f"{spec.runtime} peer로 작업 검토",
            unit_id=f"swarm-{state.invocation_id}-peer-{spec.runtime}",
        )
        dispatch = orc.open_dispatch(
            state.root,
            task["id"],
            worker=spec.runtime,
            role="peer",
            agent=spec.runtime,
            model=spec.model,
        )
        state.peers.append(_Peer(spec, task["id"], dispatch["id"]))
        state.sessions.setdefault(spec.runtime, "")


def _load_checkpoint(root: str, run_id: str) -> tuple[list[PeerSpec], str, dict[str, str]]:
    run = orc.run_show(root, run_id)
    if run is None:
        raise errors.NotFound(
            f"swarm Run을 찾을 수 없어요: {run_id}",
            remedy="최초 `asgard run ... --keep-open --json`이 반환한 run_id를 확인하세요.",
            detail={"run_id": run_id},
        )
    if run["status"] != "open":
        raise errors.Conflict(
            f"이미 닫힌 swarm Run은 재개할 수 없어요: {run_id}",
            remedy="`--keep-open`으로 새 swarm Run을 연 뒤 그 run_id를 사용하세요.",
            detail={"run_id": run_id, "status": run["status"]},
        )
    checkpoint = next(
        (
            message["payload"]
            for message in orc.inbox(root, run_id, limit=10_000)
            if message["type"] == "status"
            and message["subject"] == _CHECKPOINT_SUBJECT
            and message["payload"].get("kind") == _CHECKPOINT_KIND
        ),
        None,
    )
    if checkpoint is None:
        raise errors.Conflict(
            f"swarm session checkpoint가 없는 Run이에요: {run_id}",
            remedy="최초 실행을 `asgard run ... --cc 또는 --codex --keep-open --json`으로 다시 여세요.",
            detail={"run_id": run_id},
        )
    return _decode_checkpoint(run_id, checkpoint)


def _decode_checkpoint(run_id: str, checkpoint: dict) -> tuple[list[PeerSpec], str, dict[str, str]]:
    peers = checkpoint.get("peers")
    synthesizer = checkpoint.get("synth")
    if checkpoint.get("version") != _CHECKPOINT_VERSION or not isinstance(peers, list):
        raise _invalid_checkpoint(run_id)
    specs: list[PeerSpec] = []
    sessions: dict[str, str] = {}
    for item in peers:
        if not isinstance(item, dict):
            raise _invalid_checkpoint(run_id)
        runtime = item.get("runtime")
        model = item.get("model", "")
        effort = item.get("effort", "")
        session_id = item.get("session_id")
        if (
            runtime not in ("cc", "codex")
            or runtime in sessions
            or not isinstance(model, str)
            or not isinstance(effort, str)
            or not isinstance(session_id, str)
            or not session_id.strip()
        ):
            raise _invalid_checkpoint(run_id)
        specs.append(PeerSpec(runtime, model.strip(), effort.strip()))
        sessions[runtime] = session_id.strip()
    if not specs or not isinstance(synthesizer, str) or synthesizer not in sessions:
        raise _invalid_checkpoint(run_id)
    return specs, synthesizer, sessions


def _invalid_checkpoint(run_id: str) -> errors.Conflict:
    return errors.Conflict(
        f"swarm session checkpoint를 복원할 수 없어요: {run_id}",
        remedy="이 Run을 닫고 `--keep-open`으로 새 swarm Run을 시작하세요.",
        detail={"run_id": run_id},
    )


def _save_checkpoint(state: _State, synthesizer: str) -> None:
    orc.send(
        state.root,
        state.run_id,
        "status",
        subject=_CHECKPOINT_SUBJECT,
        body="peer runtime session checkpoint",
        sender="asgard-run",
        thread_id=f"swarm:{state.run_id}",
        payload={
            "kind": _CHECKPOINT_KIND,
            "version": _CHECKPOINT_VERSION,
            "synth": synthesizer,
            "peers": [
                {
                    "runtime": peer.runtime,
                    "model": peer.spec.model,
                    "effort": peer.spec.effort,
                    "session_id": state.sessions[peer.runtime],
                }
                for peer in state.peers
            ],
        },
    )


def _exchange(state: _State) -> None:
    prior_messages = []
    for round_number in range(1, state.request.rounds + 1):
        prompts = _round_prompts(state, round_number, prior_messages)
        results, failures = _execute_wave(state, state.peers, prompts)
        _resolve_wave(state, results, failures)
        prior_messages = _publish_handoffs(state, round_number)


def _round_prompts(state: _State, round_number: int, messages: list[dict]) -> dict[str, str]:
    prompts = {}
    for peer in state.peers:
        addressed = [message for message in messages if message["recipient"] == peer.dispatch_id]
        prompts[peer.runtime] = _peer_prompt(
            state.request.text,
            peer,
            round_number,
            state.request.rounds,
            addressed,
            state.outputs.get(peer.runtime, ""),
        )
    return prompts


def _execute_wave(
    state: _State,
    peers: list[_Peer],
    prompts: dict[str, str],
) -> tuple[dict[str, PeerTurnResult], dict[str, Exception]]:
    results: dict[str, PeerTurnResult] = {}
    failures: dict[str, Exception] = {}
    with ThreadPoolExecutor(max_workers=len(peers), thread_name_prefix="asgard-peer") as pool:
        futures = {
            peer.runtime: pool.submit(
                state.runtime.turn,
                peer.spec,
                prompts[peer.runtime],
                state.sessions.get(peer.runtime, ""),
            )
            for peer in peers
        }
        for peer in peers:
            try:
                results[peer.runtime] = futures[peer.runtime].result()
            except Exception as exc:  # 외부 프로세스 실패를 모은 뒤 열린 Dispatch를 함께 정산한다.
                failures[peer.runtime] = exc
    return results, failures


def _resolve_wave(
    state: _State,
    results: dict[str, PeerTurnResult],
    failures: dict[str, Exception],
) -> None:
    if failures:
        _fail_wave(state, results, failures)
    for runtime, result in results.items():
        state.outputs[runtime] = result.text
        state.sessions[runtime] = result.session_id


def _fail_wave(
    state: _State,
    results: dict[str, PeerTurnResult],
    failures: dict[str, Exception],
) -> None:
    for peer in state.peers:
        if peer.runtime in results:
            result = results[peer.runtime]
            state.outputs[peer.runtime] = result.text
            state.sessions[peer.runtime] = result.session_id
            _settle_peer(state, peer, "succeeded", result.text)
        elif peer.runtime in failures:
            _settle_peer(state, peer, "failed", f"{peer.runtime} peer 실행 실패")
        elif peer.runtime in state.outputs:
            _settle_peer(state, peer, "succeeded", state.outputs[peer.runtime])
    runtime, failure = next(iter(failures.items()))
    if isinstance(failure, errors.AsgardError):
        raise failure
    raise errors.UpstreamError(
        f"{runtime} peer 실행 중 알 수 없는 오류가 났어요.",
        remedy="해당 CLI를 단독으로 실행해 로그인과 모델 선택을 확인하세요.",
        detail={"runtime": runtime, "exception": type(failure).__name__},
        cause=failure,
    ) from failure


def _publish_handoffs(state: _State, round_number: int) -> list[dict]:
    messages = []
    for sender in state.peers:
        for recipient in state.peers:
            if sender == recipient:
                continue
            message = _send_handoff(state, sender, recipient, round_number)
            messages.append(message)
            state.message_ids.append(message["id"])
    return messages


def _send_handoff(
    state: _State,
    sender: _Peer,
    recipient: _Peer,
    round_number: int,
    *,
    phase: str = "",
) -> dict:
    subject = f"round {round_number} · {sender.runtime} → {recipient.runtime}"
    if phase:
        subject = f"{phase} · {sender.runtime}"
    payload = {
        "round": round_number,
        "runtime": sender.runtime,
        "session_id": state.sessions[sender.runtime],
    }
    if phase:
        payload["phase"] = phase
    return orc.send(
        state.root,
        state.run_id,
        "handoff",
        subject=subject,
        body=state.outputs[sender.runtime][:16_000],
        sender=sender.dispatch_id,
        recipient=recipient.dispatch_id,
        task_id=sender.task_id,
        dispatch_id=sender.dispatch_id,
        thread_id=f"swarm:{state.run_id}",
        payload=payload,
    )


def _conclude(state: _State, synthesizer: str) -> str:
    if len(state.peers) == 1:
        return state.outputs[synthesizer]
    peer = next(peer for peer in state.peers if peer.runtime == synthesizer)
    prompt = _synthesis_prompt(state.request.text, peer, state.peers, state.outputs)
    results, failures = _execute_wave(state, [peer], {synthesizer: prompt})
    _resolve_wave(state, results, failures)
    conclusion = state.outputs[synthesizer]
    for recipient in state.peers:
        if recipient == peer:
            continue
        message = _send_handoff(state, peer, recipient, state.request.rounds + 1, phase="conclusion")
        state.message_ids.append(message["id"])
    return conclusion


def _settle_peer(state: _State, peer: _Peer, outcome: str, body: str) -> None:
    if peer.runtime in state.settled:
        return
    orc.worker_done(
        state.root,
        state.run_id,
        peer.task_id,
        peer.dispatch_id,
        outcome,
        subject=f"{peer.runtime} peer {outcome}",
        body=body[:2_000],
        sender=peer.dispatch_id,
    )
    state.settled.add(peer.runtime)


def _settle_successes(state: _State, synthesizer: str, conclusion: str) -> None:
    for peer in state.peers:
        body = conclusion if peer.runtime == synthesizer else state.outputs[peer.runtime]
        _settle_peer(state, peer, "succeeded", body)


def _verify_all(state: _State, commands: list[list[str]]) -> tuple[list[dict], bool]:
    records = []
    dependencies = [peer.task_id for peer in state.peers]
    for index, argv in enumerate(commands, start=1):
        record = _verify_one(state, index, argv, dependencies)
        records.append(record)
        if record["exit_code"] != 0:
            return records, False
        dependencies = [record["task_id"]]
    return records, True


def _verify_one(state: _State, index: int, argv: list[str], dependencies: list[str]) -> dict:
    task = orc.task_create(
        state.root,
        state.run_id,
        f"순차 검증 {index}: {' '.join(argv)}",
        deps=dependencies,
        unit_id=f"swarm-{state.invocation_id}-verify-{index}",
    )
    dispatch = orc.open_dispatch(
        state.root,
        task["id"],
        worker="local",
        role="verification",
        agent="asgard",
    )
    try:
        completed = state.command_runner(
            argv,
            cwd=state.root,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        returncode = int(getattr(completed, "returncode"))
    except (OSError, TypeError, ValueError) as exc:
        _verification_error(state, task["id"], dispatch["id"], index, exc)
    orc.worker_done(
        state.root,
        state.run_id,
        task["id"],
        dispatch["id"],
        "succeeded" if returncode == 0 else "failed",
        body=f"exit {returncode}",
        sender=dispatch["id"],
    )
    return {
        "command": argv,
        "exit_code": returncode,
        "task_id": task["id"],
        "dispatch_id": dispatch["id"],
    }


def _verification_error(state: _State, task_id: str, dispatch_id: str, index: int, exc: Exception) -> None:
    orc.worker_done(
        state.root,
        state.run_id,
        task_id,
        dispatch_id,
        "failed",
        body="검증 프로세스를 시작하지 못함",
        sender=dispatch_id,
    )
    raise errors.UpstreamError(
        f"검증 명령 {index}을 실행하지 못했어요.",
        remedy="명령의 실행 파일과 인자를 확인한 뒤 다시 실행하세요.",
        detail={"index": index, "exception": type(exc).__name__},
        cause=exc,
    ) from exc


def _render(
    state: _State,
    synthesizer: str,
    conclusion: str,
    verification: list[dict],
    ok: bool,
) -> int:
    payload = {
        "result": conclusion,
        "ok": ok,
        "run_id": state.run_id,
        "rounds": state.request.rounds,
        "synth": synthesizer,
        "peers": [_public_peer(state, peer) for peer in state.peers],
        "message_ids": state.message_ids,
        "verification": verification,
        "run_open": bool(state.request.keep_open or state.request.swarm_run),
    }
    if state.request.json_out:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("\n" + conclusion + "\n")
        for item in verification:
            sys.stdout.write(f"검증 exit {item['exit_code']} · {' '.join(item['command'])}\n")
    return 0 if ok else 1


def _public_peer(state: _State, peer: _Peer) -> dict:
    return {
        "runtime": peer.runtime,
        "model": peer.spec.model,
        "effort": peer.spec.effort,
        "task_id": peer.task_id,
        "dispatch_id": peer.dispatch_id,
        "session_id": state.sessions[peer.runtime],
    }


def _peer_prompt(
    task: str,
    peer: _Peer,
    round_number: int,
    rounds: int,
    messages: list[dict],
    prior_answer: str,
) -> str:
    sections = [
        "[ASGARD_SWARM]",
        f"[DISPATCH:{peer.dispatch_id}]",
        f"[ROUND:{round_number}/{rounds}]",
        "원래 작업:",
        task,
    ]
    if messages:
        sections.append("이 Dispatch로 온 동료 handoff:")
        for message in messages:
            sections.extend((f"[MESSAGE:{message['id']}][FROM:{message['sender']}]", str(message["body"])[-16_000:]))
    elif prior_answer:
        sections.extend(("이전 답:", prior_answer[-16_000:]))
    sections.append("작업에 직접 쓸 수 있는 답을 제시하세요. 숨은 사고 과정은 쓰지 말고 근거와 남은 위험만 적으세요.")
    return "\n\n".join(sections)


def _synthesis_prompt(task: str, peer: _Peer, peers: list[_Peer], outputs: dict[str, str]) -> str:
    sections = [
        "[ASGARD_SWARM]",
        "[FINAL_SYNTHESIS]",
        f"[DISPATCH:{peer.dispatch_id}]",
        "원래 작업:",
        task,
        "후보 답:",
    ]
    for candidate in peers:
        sections.extend((f"[{candidate.runtime}][{candidate.dispatch_id}]", outputs[candidate.runtime][-16_000:]))
    sections.append("충돌을 해결해 하나의 최종 답만 내세요. 가정과 검증 결과를 구분하고, 새 에이전트를 부르지 마세요.")
    return "\n\n".join(sections)
