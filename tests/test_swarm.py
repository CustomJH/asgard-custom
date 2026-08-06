"""멀티 모델 swarm의 공개 CLI와 로컬 peer 실행 경계."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest import mock

import pytest
from cli_boundary import run_cli

from asgard import errors
from asgard.agent.runtime import CliPeerRuntime, PeerSpec, PeerTurnResult
from asgard.commands import start
from asgard.commands import swarm as swarm_command
from asgard.orchestration import inbox, run_close, run_create, run_list, run_show, task_list

_CLAUDE_COMMAND = [
    "claude",
    "-p",
    "--output-format",
    "json",
    "--permission-mode",
    "plan",
    "--model",
    "opus",
    "--effort",
    "high",
    "검토해줘",
]
_CODEX_COMMAND = [
    "codex",
    "exec",
    "--json",
    "--sandbox",
    "read-only",
    "--model",
    "gpt-5.6-sol",
    "-c",
    'model_reasoning_effort="medium"',
    "검토해줘",
]
_CODEX_RESUME_COMMAND = [
    "codex",
    "exec",
    "resume",
    "--json",
    "-c",
    'sandbox_mode="read-only"',
    "--model",
    "gpt-5.6-sol",
    "-c",
    'model_reasoning_effort="medium"',
    "codex-session",
    "다시 봐줘",
]


class _FakePeerRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[PeerSpec, str, str]] = []
        self._lock = threading.Lock()

    def turn(self, spec: PeerSpec, prompt: str, session_id: str = "") -> PeerTurnResult:
        with self._lock:
            self.calls.append((spec, prompt, session_id))
        returned_session = session_id or f"session-{spec.runtime}"
        if "[FINAL_SYNTHESIS]" in prompt:
            text = "합의 결론"
        elif session_id:
            text = f"{spec.runtime} 수정안"
        else:
            text = f"{spec.runtime} 초안"
        return PeerTurnResult(text, returned_session, ("fake", spec.runtime, "<prompt>"), 0)


class _SessionChainRuntime:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self._lock = threading.Lock()
        self._overlap = threading.Event()
        self._step = 0

    def turn(self, spec: PeerSpec, prompt: str, session_id: str = "") -> PeerTurnResult:
        with self._lock:
            self.sessions.append(session_id)
            if not session_id:
                return PeerTurnResult("seed", "seed", ("fake", spec.runtime, "<prompt>"), 0)
            self._step += 1
            step = self._step
        if session_id == "seed" and step == 1:
            self._overlap.wait(0.3)
        elif session_id == "seed":
            self._overlap.set()
        return PeerTurnResult(f"next-{step}", f"next-{step}", ("fake", spec.runtime, "<prompt>"), 0)


class _FailingPeerRuntime:
    def turn(self, spec: PeerSpec, prompt: str, session_id: str = "") -> PeerTurnResult:
        raise errors.UpstreamError("peer 실패", remedy="fake runtime 실패를 고치세요.")


def test_cli_peer_runtime_builds_claude_and_codex_session_commands(tmp_path):
    calls = []
    outputs = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"result": "Claude 답", "session_id": "claude-session"}),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=(
                    '{"type":"thread.started","thread_id":"codex-session"}\n'
                    '{"type":"item.completed","item":{"type":"agent_message","text":"Codex 답"}}\n'
                ),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout='{ "type":"item.completed", "item":{"type":"agent_message","text":"수정 답"}}\n',
                stderr="",
            ),
        ]
    )

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return next(outputs)

    runtime = CliPeerRuntime(str(tmp_path), runner=runner)
    claude = runtime.turn(PeerSpec("cc", model="opus", effort="high"), "검토해줘")
    codex = runtime.turn(PeerSpec("codex", model="gpt-5.6-sol", effort="medium"), "검토해줘")
    resumed = runtime.turn(PeerSpec("codex", model="gpt-5.6-sol", effort="medium"), "다시 봐줘", codex.session_id)

    assert claude.text == "Claude 답"
    assert codex.session_id == "codex-session"
    assert resumed.text == "수정 답"
    assert calls[0][0] == _CLAUDE_COMMAND
    assert calls[1][0] == _CODEX_COMMAND
    assert calls[2][0] == _CODEX_RESUME_COMMAND
    assert all(call[1]["cwd"] == str(tmp_path) and call[1]["check"] is False for call in calls)


def test_swarm_exchanges_dispatch_addressed_handoffs_and_verifies_in_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    peer_runtime = _FakePeerRuntime()
    commands = []

    def verification_runner(argv, **kwargs):
        commands.append((tuple(argv), kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = start.run_prompt(
            "설계를 검토해줘",
            json_out=True,
            cc=True,
            codex=True,
            cc_model="opus",
            cc_effort="high",
            codex_model="gpt-5.6-sol",
            codex_effort="medium",
            rounds=2,
            synth="codex",
            verify_commands=["python -m pytest first", "python -m pytest second"],
            peer_runtime=peer_runtime,
            verification_runner=verification_runner,
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert payload["run_open"] is False
    assert run_show(str(tmp_path), payload["run_id"])["status"] == "closed"
    assert payload["result"] == "합의 결론"
    assert [peer["runtime"] for peer in payload["peers"]] == ["cc", "codex"]
    assert [item["exit_code"] for item in payload["verification"]] == [0, 0]
    assert [item[0] for item in commands] == [
        ("python", "-m", "pytest", "first"),
        ("python", "-m", "pytest", "second"),
    ]
    assert all(item[1]["cwd"] == str(tmp_path) and item[1]["shell"] is False for item in commands)

    by_runtime = {peer["runtime"]: peer for peer in payload["peers"]}
    messages = inbox(str(tmp_path), payload["run_id"])
    handoffs = [message for message in messages if message["type"] == "handoff"]
    dispatches = {peer["dispatch_id"] for peer in payload["peers"]}
    assert handoffs
    assert all(message["sender"] in dispatches and message["recipient"] in dispatches for message in handoffs)
    assert {(message["sender"], message["recipient"]) for message in handoffs if message["payload"]["round"] == 1} == {
        (by_runtime["cc"]["dispatch_id"], by_runtime["codex"]["dispatch_id"]),
        (by_runtime["codex"]["dispatch_id"], by_runtime["cc"]["dispatch_id"]),
    }

    calls = peer_runtime.calls
    assert len(calls) == 5
    assert {(call[0].runtime, call[2]) for call in calls[:2]} == {("cc", ""), ("codex", "")}
    resumed = [call for call in calls[2:] if "[FINAL_SYNTHESIS]" not in call[1]]
    assert {(call[0].runtime, call[2]) for call in resumed} == {
        ("cc", "session-cc"),
        ("codex", "session-codex"),
    }


def test_open_swarm_run_resumes_saved_peer_sessions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    peer_runtime = _FakePeerRuntime()

    first_stdout = StringIO()
    with redirect_stdout(first_stdout):
        first_code = start.run_prompt(
            "첫 검토",
            json_out=True,
            cc=True,
            codex=True,
            cc_model="opus",
            cc_effort="high",
            codex_model="gpt-5.6-sol",
            codex_effort="medium",
            rounds=1,
            synth="codex",
            keep_open=True,
            peer_runtime=peer_runtime,
        )

    first = json.loads(first_stdout.getvalue())
    follow_stdout = StringIO()
    with redirect_stdout(follow_stdout):
        follow_code = start.run_prompt(
            "후속 검토",
            json_out=True,
            swarm_run=first["run_id"],
            rounds=1,
            peer_runtime=peer_runtime,
        )

    follow = json.loads(follow_stdout.getvalue())
    assert first_code == follow_code == 0
    assert follow["run_id"] == first["run_id"]
    assert run_show(str(tmp_path), first["run_id"])["status"] == "open"
    assert {peer["runtime"]: peer["session_id"] for peer in follow["peers"]} == {
        "cc": "session-cc",
        "codex": "session-codex",
    }
    assert {peer["task_id"] for peer in first["peers"]}.isdisjoint(peer["task_id"] for peer in follow["peers"])
    assert {peer["dispatch_id"] for peer in first["peers"]}.isdisjoint(peer["dispatch_id"] for peer in follow["peers"])
    unit_ids = [task["unit_id"] for task in task_list(str(tmp_path), first["run_id"])]
    assert len(unit_ids) == len(set(unit_ids))
    follow_round = peer_runtime.calls[3:5]
    assert {(call[0].runtime, call[0].model, call[0].effort, call[2]) for call in follow_round} == {
        ("cc", "opus", "high", "session-cc"),
        ("codex", "gpt-5.6-sol", "medium", "session-codex"),
    }


def test_concurrent_swarm_resumes_follow_one_serial_session_chain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    peer_runtime = _SessionChainRuntime()
    seed_stdout = StringIO()
    with redirect_stdout(seed_stdout):
        assert (
            start.run_prompt(
                "첫 검토",
                json_out=True,
                cc=True,
                rounds=1,
                keep_open=True,
                peer_runtime=peer_runtime,
            )
            == 0
        )
    run_id = json.loads(seed_stdout.getvalue())["run_id"]

    sink = StringIO()
    with redirect_stdout(sink), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                start.run_prompt,
                f"후속 검토 {index}",
                json_out=False,
                swarm_run=run_id,
                rounds=1,
                peer_runtime=peer_runtime,
            )
            for index in range(2)
        ]
        assert [future.result() for future in futures] == [0, 0]

    assert peer_runtime.sessions == ["", "seed", "next-1"]
    checkpoints = [
        message for message in inbox(str(tmp_path), run_id) if message["subject"] == "swarm session checkpoint"
    ]
    assert checkpoints[0]["payload"]["peers"][0]["session_id"] == "next-2"


def test_raw_and_padded_swarm_run_ids_share_one_serial_session_chain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    peer_runtime = _SessionChainRuntime()
    seed_stdout = StringIO()
    with redirect_stdout(seed_stdout):
        assert (
            start.run_prompt(
                "첫 검토",
                json_out=True,
                cc=True,
                rounds=1,
                keep_open=True,
                peer_runtime=peer_runtime,
            )
            == 0
        )
    run_id = json.loads(seed_stdout.getvalue())["run_id"]

    sink = StringIO()
    with redirect_stdout(sink), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                start.run_prompt,
                f"후속 검토 {index}",
                json_out=False,
                swarm_run=value,
                rounds=1,
                peer_runtime=peer_runtime,
            )
            for index, value in enumerate((run_id, f"  {run_id}  "))
        ]
        assert [future.result() for future in futures] == [0, 0]

    assert peer_runtime.sessions == ["", "seed", "next-1"]


def test_resume_lease_blocks_a_separate_process(tmp_path):
    child_script = "\n".join(
        (
            "import sys, time",
            "from asgard.commands.swarm import _resume_lease",
            "print('ready', flush=True)",
            "started = time.monotonic()",
            "with _resume_lease(sys.argv[1], sys.argv[2]):",
            "    print(time.monotonic() - started, flush=True)",
        )
    )
    with swarm_command._resume_lease(str(tmp_path), "../../same-run"):
        child = subprocess.Popen(
            [sys.executable, "-c", child_script, str(tmp_path), "../../same-run"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        time.sleep(0.15)
        assert child.poll() is None
    stdout, stderr = child.communicate(timeout=5)

    assert child.returncode == 0, stderr
    assert float(stdout.strip()) >= 0.1


def test_failed_initial_keep_open_swarm_closes_run_without_checkpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(errors.UpstreamError, match="peer 실패"):
        start.run_prompt(
            "실패하는 첫 검토",
            json_out=True,
            cc=True,
            rounds=1,
            keep_open=True,
            peer_runtime=_FailingPeerRuntime(),
        )

    runs = run_list(str(tmp_path))
    assert len(runs) == 1
    assert runs[0]["status"] == "closed"
    checkpoints = [
        message for message in inbox(str(tmp_path), runs[0]["id"]) if message["subject"] == "swarm session checkpoint"
    ]
    assert checkpoints == []


def test_failed_existing_swarm_resume_preserves_open_checkpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed_stdout = StringIO()
    with redirect_stdout(seed_stdout):
        assert (
            start.run_prompt(
                "첫 검토",
                json_out=True,
                cc=True,
                rounds=1,
                keep_open=True,
                peer_runtime=_FakePeerRuntime(),
            )
            == 0
        )
    run_id = json.loads(seed_stdout.getvalue())["run_id"]

    with pytest.raises(errors.UpstreamError, match="peer 실패"):
        start.run_prompt(
            "실패하는 후속 검토",
            json_out=True,
            swarm_run=run_id,
            rounds=1,
            peer_runtime=_FailingPeerRuntime(),
        )

    assert run_show(str(tmp_path), run_id)["status"] == "open"
    checkpoints = [
        message for message in inbox(str(tmp_path), run_id) if message["subject"] == "swarm session checkpoint"
    ]
    assert len(checkpoints) == 1


def test_swarm_stops_sequential_verification_on_first_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    peer_runtime = _FakePeerRuntime()
    calls = []

    def verification_runner(argv, **kwargs):
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=7, stdout="", stderr="failed")

    stdout = StringIO()
    with redirect_stdout(stdout):
        code = start.run_prompt(
            "검토해줘",
            json_out=True,
            cc=True,
            rounds=1,
            verify_commands=["python first.py", "python second.py"],
            peer_runtime=peer_runtime,
            verification_runner=verification_runner,
        )

    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert calls == [("python", "first.py")]
    assert payload["verification"] == [
        {"command": ["python", "first.py"], "exit_code": 7, "task_id": mock.ANY, "dispatch_id": mock.ANY}
    ]


def test_single_peer_accepts_generic_model_and_effort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stdout = StringIO()
    with redirect_stdout(stdout):
        code = start.run_prompt(
            "검토해줘",
            model="gpt-5.6-sol",
            effort="high",
            json_out=True,
            codex=True,
            rounds=1,
            peer_runtime=_FakePeerRuntime(),
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["peers"][0]["model"] == "gpt-5.6-sol"
    assert payload["peers"][0]["effort"] == "high"


def test_run_cli_forwards_per_runtime_selection_and_repeatable_verification():
    with mock.patch("asgard.commands.start.run_prompt", return_value=0) as run_prompt:
        outcome = run_cli(
            "run",
            "설계를 검토해줘",
            "--cc",
            "--cc-model",
            "opus",
            "--cc-effort",
            "high",
            "--codex",
            "--codex-model",
            "gpt-5.6-sol",
            "--codex-effort",
            "medium",
            "--rounds",
            "3",
            "--synth",
            "cc",
            "--verify",
            "python first.py",
            "--verify",
            "python second.py",
            "--keep-open",
            "--json",
        )

    assert outcome.exit_code == 0
    run_prompt.assert_called_once_with(
        "설계를 검토해줘",
        provider=None,
        model=None,
        effort=None,
        json_out=True,
        resume=False,
        quest_id=None,
        dual=False,
        cc=True,
        codex=True,
        cc_model="opus",
        cc_effort="high",
        codex_model="gpt-5.6-sol",
        codex_effort="medium",
        rounds=3,
        synth="cc",
        verify_commands=["python first.py", "python second.py"],
        keep_open=True,
        swarm_run=None,
    )


def test_run_cli_forwards_existing_swarm_run_without_peer_selection():
    with mock.patch("asgard.commands.start.run_prompt", return_value=0) as run_prompt:
        outcome = run_cli(
            "run",
            "후속 검토",
            "--swarm-run",
            "run_saved",
            "--rounds",
            "1",
            "--synth",
            "cc",
            "--verify",
            "python verify.py",
            "--json",
        )

    assert outcome.exit_code == 0
    args, kwargs = run_prompt.call_args
    assert args == ("후속 검토",)
    assert kwargs["cc"] is kwargs["codex"] is False
    assert kwargs["swarm_run"] == "run_saved"
    assert kwargs["rounds"] == 1
    assert kwargs["synth"] == "cc"
    assert kwargs["verify_commands"] == ["python verify.py"]


def test_swarm_run_rejects_missing_closed_and_checkpointless_runs_with_remedies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    missing = run_cli("run", "후속 검토", "--swarm-run", "run_missing", "--json")
    missing_error = json.loads(missing.stdout)["error"]
    assert missing.exit_code == 2
    assert missing_error["code"] == "not_found"
    assert "--keep-open" in missing_error["remedy"]

    traversal = run_cli("run", "후속 검토", "--swarm-run", "../../outside", "--json")
    assert traversal.exit_code == 2
    assert not (tmp_path / "outside.lock").exists()
    lease_files = list((tmp_path / ".asgard" / "swarm-leases").iterdir())
    assert lease_files
    assert all(len(path.stem) == 64 and set(path.stem) <= set("0123456789abcdef") for path in lease_files)

    run = run_create(str(tmp_path), "checkpoint 없는 Run")
    checkpointless = run_cli("run", "후속 검토", "--swarm-run", run["id"], "--json")
    checkpointless_error = json.loads(checkpointless.stdout)["error"]
    assert checkpointless.exit_code == 2
    assert checkpointless_error["code"] == "conflict"
    assert "--keep-open" in checkpointless_error["remedy"]

    run_close(str(tmp_path), run["id"])
    closed = run_cli("run", "후속 검토", "--swarm-run", run["id"], "--json")
    closed_error = json.loads(closed.stdout)["error"]
    assert closed.exit_code == 2
    assert closed_error["code"] == "conflict"
    assert "--keep-open" in closed_error["remedy"]

    reselected = run_cli("run", "후속 검토", "--swarm-run", run["id"], "--cc", "--json")
    reselected_error = json.loads(reselected.stdout)["error"]
    assert reselected.exit_code == 2
    assert reselected_error["code"] == "invalid_input"
    assert "checkpoint" in reselected_error["remedy"]


def test_swarm_specific_option_requires_its_runtime_and_returns_json_error():
    outcome = run_cli("run", "검토해줘", "--cc-model", "opus", "--json")

    assert outcome.exit_code == 2
    payload = json.loads(outcome.stdout)
    assert payload["error"]["code"] == "invalid_input"
    assert "--cc" in payload["error"]["remedy"]
    assert outcome.stderr == ""
