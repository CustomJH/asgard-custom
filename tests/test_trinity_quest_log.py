#!/usr/bin/env python3
"""퀘스트 로그 자체 — 열기·기록·닫기, 세션 포인터, 보존 기간 정리."""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from trinity_base import (
    QLOG,
    TrinityBase,
    jout,
    run,
)


class TestQuestLog(TrinityBase):
    def test_session_quest_pointers_isolate_concurrent_sessions(self):
        self.assertEqual(
            self.qlog("open", "q1", "--criteria", "one", "--session", "s1").returncode,
            0,
        )
        self.assertEqual(
            self.qlog("open", "q2", "--criteria", "two", "--session", "s2").returncode,
            0,
        )
        self.qlog("append", "--role", "worker", "--event", "work", "--session", "s1")
        self.qlog("append", "--role", "worker", "--event", "work", "--session", "s2")
        q1 = [json.loads(line) for line in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        q2 = [json.loads(line) for line in open(os.path.join(self.root, ".asgard", "quest", "q2.jsonl"))]
        self.assertEqual([event["session_id"] for event in q1], ["s1", "s1"])
        self.assertEqual([event["session_id"] for event in q2], ["s2", "s2"])
        from asgard.hooks.quest_log import active_quest

        self.assertEqual(active_quest(self.root, "s1"), "q1")
        self.assertEqual(active_quest(self.root, "s2"), "q2")

    def test_attach_rebinds_a_pointer_after_the_host_changes_the_session_id(self):
        """호스트가 세션 신원을 갈면 (26-08-04 실측: 39f84a83→2a24f078) 진행 중인 기장이 사라진다.
        `open` 은 같은 id 재개통을 거부하므로 돌아갈 동사가 아예 없었다."""
        from asgard.hooks.quest_log import active_quest

        self.assertEqual(self.qlog("open", "q1", "--criteria", "one", "--session", "old-sid").returncode, 0)
        self.assertEqual(self.qlog("open", "q2", "--criteria", "two", "--session", "other").returncode, 0)
        # 활성 퀘스트가 둘이라 승계 갈래가 fail-closed 다 — 새 신원은 아무것도 못 본다.
        self.assertIsNone(active_quest(self.root, "new-sid"))
        self.assertIn("no active quest", self.qlog("state", "--session", "new-sid").stdout)

        active_file = os.path.join(self.root, ".asgard", "quest", "ACTIVE")
        with open(active_file) as handle:
            global_before = handle.read()

        attached = jout(self.qlog("attach", "q1", "--session", "new-sid"))
        self.assertEqual(attached["attached"], "q1")
        # 기계 전역 ACTIVE 는 세션 이름 없이 묻는 소비처들이 읽는 자리다 (subagent_gate·
        # failure_tracker·verifier_gate·heimdall). 복구 명령이 그것을 옮기면 옆 세션의 일이
        # 이쪽 퀘스트로 귀속된다.
        with open(active_file) as handle:
            self.assertEqual(handle.read(), global_before)
        self.assertEqual(attached["base_ref"], jout(self.qlog("state", "--session", "old-sid"))["base_ref"])
        self.assertEqual(active_quest(self.root, "new-sid"), "q1")

        # 새 실행이 아니다 — 이벤트도 실행 신원도 그대로고, 이어서 적힌다.
        self.qlog("append", "--role", "worker", "--event", "work", "--session", "new-sid")
        with open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")) as handle:
            events = [json.loads(line) for line in handle]
        self.assertEqual([e["turn"] for e in events], [1, 2])
        self.assertEqual({e["execution_id"] for e in events}, {attached["execution_id"]})
        self.assertEqual([e["session_id"] for e in events], ["old-sid", "new-sid"])

    def test_attach_refuses_a_missing_quest_a_closed_one_and_a_session_that_holds_another(self):
        self.assertEqual(self.qlog("open", "q1", "--criteria", "one", "--session", "s1", "--no-write").returncode, 0)
        self.assertEqual(self.qlog("attach", "nope", "--session", "s2").returncode, 1)
        self.assertEqual(self.qlog("open", "q2", "--criteria", "two", "--session", "s2", "--no-write").returncode, 0)
        refused = self.qlog("attach", "q1", "--session", "s2")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("already holds", refused.stdout + refused.stderr)

        self.assertEqual(self.qlog("close", "q1", "--session", "s1", "--force").returncode, 0)
        closed = self.qlog("attach", "q1", "--session", "s3")
        self.assertEqual(closed.returncode, 1)
        self.assertIn("closed", closed.stdout + closed.stderr)

    def test_attach_is_admitted_by_the_read_only_bash_allowlist(self):
        """역할 계약이 안내하는 명령이 가드에 막히면 그 동사는 없는 것과 같다."""
        from asgard.hooks.readonly_guard import is_readonly_bash_safe

        for hooks in (".claude/hooks", ".cursor/hooks", ".codex/hooks"):
            command = f"uv run --no-project python {hooks}/quest-log.py attach q1"
            self.assertTrue(is_readonly_bash_safe(command, root=self.root), command)
            # 파이프 한 번에 판정이 뒤집히면 계약이 안내하는 형태가 통제 표면 갈래에 걸린다.
            self.assertTrue(is_readonly_bash_safe(command + " | tail -5", root=self.root), command)
        # 기장 단계가 붙었다고 다른 단계가 열리지는 않는다.
        for unsafe in (
            ".claude/hooks/quest-log.py state | tee out.txt",
            ".claude/hooks/quest-log.py state && rm -rf src",
            ".claude/hooks/quest-log.py close --force",
        ):
            self.assertFalse(is_readonly_bash_safe(unsafe, root=self.root), unsafe)

    def test_close_is_session_scoped_and_records_durable_close_event(self):
        self.qlog("open", "q1", "--criteria", "one", "--session", "s1", "--no-write")
        self.qlog("open", "q2", "--criteria", "two", "--session", "s2", "--no-write")
        closed = self.qlog("close", "q1", "--session", "s1", "--force")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        from asgard.hooks.quest_log import active_quest

        self.assertIsNone(active_quest(self.root, "s1"))
        self.assertEqual(active_quest(self.root, "s2"), "q2")
        q1 = [json.loads(line) for line in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        self.assertEqual(q1[-1]["event"], "quest_closed")

    def test_schema_16_fields_and_turns(self):
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        lines = open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).read().splitlines()
        self.assertEqual(len(lines), 2)
        ev = json.loads(lines[1])
        want = {
            "schema",
            "quest_id",
            "session_id",
            "turn",
            "ts",
            "role",
            "event",
            "base_ref",
            "risk",
            "criteria",
            "changed_files",
            "diff_hash",
            "commands",
            "verdict",
            "failure_sig",
            "failure_count",
        }
        self.assertEqual(want - set(ev), set())
        self.assertEqual([json.loads(ln)["turn"] for ln in lines], [1, 2])
        self.assertTrue(open(os.path.join(self.root, ".asgard", "quest", "ACTIVE")).read().strip() == "q1")

    def test_v2_chain_binds_execution_acceptance_and_replay(self):
        opened = self.open_quest()
        self.qlog(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"changed_files": ["app.py"]}),
        )
        replayed = jout(self.qlog("replay"))
        events = [
            json.loads(line) for line in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"), encoding="utf-8")
        ]
        self.assertEqual(replayed["ledger"], "protected")
        self.assertEqual(replayed["execution_id"], opened["execution_id"])
        self.assertEqual(replayed["acceptance_hash"], opened["acceptance_hash"])
        self.assertEqual(events[1]["prev_event_hash"], events[0]["event_hash"])
        self.assertEqual({event["execution_id"] for event in events}, {opened["execution_id"]})
        self.assertEqual({event["acceptance_hash"] for event in events}, {opened["acceptance_hash"]})

    def test_existing_quest_id_cannot_be_reopened_with_new_acceptance(self):
        first = self.open_quest()
        reopened = self.qlog("open", "q1", "--criteria", "different")
        self.assertNotEqual(reopened.returncode, 0)
        self.assertIn("already exists", reopened.stderr)
        replayed = jout(self.qlog("replay"))
        self.assertEqual(replayed["execution_id"], first["execution_id"])
        self.assertEqual(replayed["criteria"], ["app.py prints ok"])

    def test_legacy_quest_upgrades_on_first_v2_append_without_rewrite(self):
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True
        ).stdout.strip()
        qdir = os.path.join(self.root, ".asgard", "quest")
        os.makedirs(qdir, exist_ok=True)
        legacy = {
            "schema": 1,
            "quest_id": "legacy",
            "session_id": "s1",
            "turn": 1,
            "ts": "2026-01-01T00:00:00Z",
            "role": "thinker",
            "event": "plan",
            "base_ref": base,
            "risk": {"has_write": True},
            "criteria": ["legacy criterion"],
            "changed_files": [],
            "diff_hash": None,
            "commands": [],
            "verdict": "NA",
            "failure_sig": None,
            "failure_count": 0,
        }
        with open(os.path.join(qdir, "legacy.jsonl"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(legacy) + "\n")
        appended = self.qlog("append", "legacy", "--event", "work", "--session", "s1")
        self.assertEqual(appended.returncode, 0, appended.stderr)
        replayed = jout(self.qlog("replay", "legacy"))
        self.assertEqual(replayed["ledger"], "protected")
        self.assertTrue(replayed["execution_id"].startswith("legacy-"))

    def test_pass_and_close_share_one_verification_identity(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"changed_files": ["app.py"]}),
        )
        verified = jout(self.verify())
        self.assertTrue(verified["verification_id"])
        self.assertEqual(self.qlog("close").returncode, 0)
        events = [
            json.loads(line) for line in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"), encoding="utf-8")
        ]
        self.assertEqual(events[-2]["verification_id"], verified["verification_id"])
        self.assertEqual(events[-1]["verification_id"], verified["verification_id"])
        replayed = jout(self.qlog("replay", "q1"))
        self.assertTrue(replayed["closed"])
        self.assertEqual(replayed["close_decision"], "APPROVED")

    def test_rehashed_pass_with_wrong_verification_identity_is_blocked(self):
        from asgard.hooks.quest_log import event_identity

        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"changed_files": ["app.py"]}),
        )
        self.verify()
        path = os.path.join(self.root, ".asgard", "quest", "q1.jsonl")
        events = [json.loads(line) for line in open(path, encoding="utf-8")]
        events[-1]["verification_id"] = "forged"
        events[-1]["event_hash"] = event_identity(events[-1])
        with open(path, "w", encoding="utf-8") as handle:
            handle.writelines(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
        out = jout(self.gate())
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("[gate:verification-identity]", out.get("reason", ""))

    def test_open_accepts_original_request_via_bounded_stdin(self):
        request = "원본 요청 " + ("x" * 4096)
        opened = run(
            QLOG,
            ["open", "stdin-request", "--criteria", "c", "--request-stdin", "--session", "s1"],
            stdin=json.dumps({"request": request}),
            cwd=self.root,
        )
        self.assertEqual(opened.returncode, 0, opened.stderr)
        event = json.loads(open(os.path.join(self.root, ".asgard", "quest", "stdin-request.jsonl")).readline())
        self.assertEqual(event["request"], request)

        oversized = run(
            QLOG,
            ["open", "oversized-request", "--criteria", "c", "--request-stdin", "--session", "s1"],
            stdin=json.dumps({"request": "x" * 10001}),
            cwd=self.root,
        )
        self.assertNotEqual(oversized.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "oversized-request.jsonl")))

    def test_gate_block_counter_is_scoped_to_active_quest(self):
        from asgard.hooks.verifier_gate import block_counter_path

        self.assertEqual(self.qlog("open", "q1", "--criteria", "c").returncode, 0)
        first = block_counter_path(self.root, "s1")
        self.assertEqual(self.qlog("open", "q2").returncode, 0)
        second = block_counter_path(self.root, "s1")
        self.assertNotEqual(first, second)
        self.assertTrue(first.endswith("-q1.json"))
        self.assertTrue(second.endswith("-q2.json"))

    def test_verify_computes_diff_hash(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        out = jout(self.verify())
        self.assertEqual(out["verdict"], "PASS")
        self.assertTrue(out["diff_hash"])
        st = jout(self.qlog("state"))
        self.assertTrue(st["pass_hash_match"])
        self.assertIn("app.py", st["changed_files"])

    def test_declared_ignored_artifacts_are_bound_to_pass_hash_and_stale_detection(self):
        """선언한 무시 파일은 결속된다. 선언 밖의 무시 경로는 tests/test_gate_ignored_scope.py 담당."""
        self.write(".gitignore", "secret.env\n")
        self.write("secret.env", "before\n")
        self.open_quest("--criteria", "런타임 설정 | artifacts: secret.env")
        self.write("secret.env", "after\n")
        self.verify(commands=[{"cmd": "cat secret.env", "exit_code": 0}])
        state = jout(self.qlog("state"))
        self.assertIn("secret.env", state["changed_files"])
        self.assertTrue(state["pass_hash_match"])
        self.write("secret.env", "tampered\n")
        self.assertFalse(jout(self.qlog("state"))["pass_hash_match"])
        self.assertEqual(self.qlog("close").returncode, 1)

    def test_ignored_enumeration_failure_blocks_open_and_close(self):
        # 스냅샷은 선언된 산출물에만 걸린다 (artifact_scope) — 열거 실패도 그 자리에서만 판정된다.
        from asgard_hooklib import scope as scope_module

        from asgard.hooks import quest_log, verifier_gate

        marker = {"<snapshot-unavailable>": "ignored-enumeration-failed"}
        # 패치는 열거를 실제로 도는 자리에 건다 — 두 훅은 그 함수를 재수출할 뿐이다.
        with mock.patch.object(scope_module, "git", return_value=(1, b"")):
            self.assertEqual(quest_log.ignored_state(self.root, ("workspace",)), marker)
            self.assertEqual(verifier_gate.ignored_state(self.root, ("workspace",)), marker)

        with (
            mock.patch.object(quest_log, "repo_root", return_value=self.root),
            mock.patch.object(quest_log, "ignored_state", return_value=marker),
            mock.patch.object(sys, "argv", ["quest-log", "open", "snapshot-fail", "--criteria", "x"]),
            mock.patch.object(sys, "stdout", io.StringIO()),
            mock.patch.object(sys, "stderr", io.StringIO()),
        ):
            self.assertEqual(quest_log.main(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "snapshot-fail.jsonl")))

        # 스냅샷을 실제로 뜨는 퀘스트여야 열거 실패가 판정에 닿는다 — 선언이 없으면 열거도 없다.
        self.open_quest("--criteria", "산출물 | artifacts: workspace/out.txt")
        self.write("app.py", "print('ok')\n")
        self.verify()
        with (
            mock.patch.object(quest_log, "repo_root", return_value=self.root),
            mock.patch.object(quest_log, "ignored_state", return_value=marker),
            mock.patch.object(sys, "argv", ["quest-log", "close", "--session", "s1"]),
            mock.patch.object(sys, "stdout", io.StringIO()),
            mock.patch.object(sys, "stderr", io.StringIO()),
        ):
            self.assertEqual(quest_log.main(), 1)

    def test_start_snapshot_survives_a_gitignored_asgard_directory(self):
        """`asgard setup`이 `.asgard/`를 무시 목록에 넣은 리포에서도 시작 트리를 뜰 수 있어야 한다.

        exclude 페이스펙이 붙으면 git add가 무시된 경로를 오류로 보고해 rc=1로 죽었고, 그 결과
        모든 write 퀘스트가 "requires a Git repository with HEAD"로 거부됐다 — Studio/Studio의
        모든 실행이 여기서 막혔다."""
        from asgard.hooks import quest_log

        self.write(".gitignore", ".asgard/\n")
        self.write(".asgard/map/INDEX.md", "map\n")
        self.write(".asgard/studio/tasks.jsonl", "{}\n")
        self.write("app.py", "print('ok')\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "ignore asgard"], check=True)
        self.write("untracked.py", "print('new')\n")

        ref = quest_log.snapshot_ref(self.root)
        self.assertTrue(ref, "gitignored .asgard must not block the quest start snapshot")
        listed = subprocess.run(
            ["git", "-C", self.root, "ls-tree", "-r", "--name-only", str(ref)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertIn("untracked.py", listed)  # 시작 트리는 워킹트리 그대로다
        self.assertIn(".asgard/map/INDEX.md", listed)  # map은 강제로 담는다
        self.assertNotIn(".asgard/studio/tasks.jsonl", listed)  # 나머지 .asgard는 여전히 뺀다

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO is unavailable on this platform")
    def test_ignored_fifo_snapshot_never_blocks_reading_device_content(self):
        self.write(".gitignore", "*.fifo\n")
        fifo = os.path.join(self.root, "blocked.fifo")
        os.mkfifo(fifo)
        code = (
            "from asgard.hooks.quest_log import ignored_state; "
            f"print(ignored_state({self.root!r}, ('blocked.fifo',)).get('blocked.fifo'))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "None")  # Git does not enumerate ignored FIFOs as files

    def test_preexisting_untracked_file_is_part_of_base_not_reported_as_quest_change(self):
        self.write("preexisting.txt", "user state\n")
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        state = jout(self.qlog("state"))
        self.assertIn("app.py", state["changed_files"])
        self.assertNotIn("preexisting.txt", state["changed_files"])

    def test_append_rejects_bad_event_and_verify_without_verdict(self):
        self.open_quest()
        self.assertEqual(self.qlog("append", "--event", "nope").returncode, 2)
        self.assertEqual(self.qlog("append", "--event", "verify").returncode, 2)

    def test_close_requires_pass_or_force(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.assertEqual(self.qlog("close").returncode, 1)  # PASS 없음 → 거부
        self.verify()
        self.assertEqual(self.qlog("close").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_last_pointer_failure_keeps_active_quest_and_rejects_close(self):
        from asgard.hooks import quest_log

        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        real_write_pointer = quest_log.write_pointer

        def fail_last(path, qid):
            if path.endswith(".last") or os.path.basename(path) == "LAST":
                raise OSError("injected LAST failure")
            return real_write_pointer(path, qid)

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            with mock.patch.object(sys, "argv", ["quest_log.py", "close", "q1", "--session", "s1"]):
                with mock.patch.object(quest_log, "write_pointer", side_effect=fail_last):
                    with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
                        rc = quest_log.main()
        self.assertEqual(rc, 1)
        self.assertIn("LAST pointer publication failed", stderr.getvalue())
        self.assertEqual(open(os.path.join(self.root, ".asgard", "quest", "ACTIVE")).read().strip(), "q1")

    def test_verify_refreshes_map_before_hash_and_close_reports_current(self):
        # 지도 도입 + 신규 파일 → Verifier hash 계산 전에 managed map 자동 갱신.
        # 따라서 지도 변경도 같은 PASS hash에 포함되고 close 뒤 stale write가 생기지 않는다.
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        self.write(".gitignore", "!.asgard/\n.asgard/*\n!.asgard/map/\n!.asgard/map/**\n")
        self.open_quest()
        self.write("src/new_module.py", "x = 1\n")
        self.write(".claude/hooks/dummy.py", "y = 1\n")  # 닷디렉토리 — 제외돼야 함
        self.verify(level="full")  # hooks는 민감 경로 — full-verify 없이는 close가 거부된다
        project_map = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertIn("src/", project_map)
        self.assertNotIn(".claude", project_map)
        state = jout(self.qlog("state"))
        self.assertIn(".asgard/map/PROJECT.md", state["changed_files"])
        self.assertIn(".asgard/map/GRAPH.md", state["changed_files"])
        from asgard.code_map import check_map

        self.assertTrue(check_map(self.root).ok, check_map(self.root))
        out = jout(self.qlog("close"))
        self.assertEqual(out["closed"], "q1")
        self.assertTrue(out["map_current"])
        self.assertNotIn("map_update", out)

    def test_managed_map_refresh_falls_back_to_installed_cli_when_hook_python_cannot_import_package(self):
        import builtins

        from asgard.hooks import quest_log

        real_import = builtins.__import__

        def isolated_hook_import(name, *args, **kwargs):
            if name == "asgard.code_map":
                raise ModuleNotFoundError("No module named 'asgard'")
            return real_import(name, *args, **kwargs)

        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("builtins.__import__", side_effect=isolated_hook_import):
            with mock.patch.object(quest_log.subprocess, "run", return_value=completed) as invoked:
                self.assertEqual(quest_log.refresh_managed_map(self.root), (True, None))
        self.assertEqual(
            [call.args[0] for call in invoked.call_args_list],
            [["asgard", "map", "update", "--quiet"], ["asgard", "map", "scan", "--quiet"]],
        )

    def test_verify_fails_closed_when_managed_map_refresh_is_rejected(self):
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        self.write(".asgard/map/PROJECT.md", "# human-owned collision\n")
        self.open_quest()
        self.write("app.py", "print('ok')\n")

        result = jout(self.verify(level="full"))

        self.assertEqual(result["verdict"], "FAIL")
        events = [json.loads(line) for line in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        self.assertEqual(events[-1]["failure_sig"], "map-refresh-failed")
        self.assertEqual(self.qlog("close").returncode, 1)

    def test_map_tamper_after_pass_makes_verdict_stale(self):
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        self.open_quest()
        self.write("src/new_module.py", "x = 1\n")
        self.verify(level="full")
        with open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), "a") as f:
            f.write("tampered\n")
        state = jout(self.qlog("state"))
        self.assertFalse(state["pass_hash_match"])
        self.assertEqual(self.qlog("close").returncode, 1)

    def test_symlink_area_map_target_is_never_consumed_as_repository_evidence(self):
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        outside_dir = tempfile.TemporaryDirectory()
        self.addCleanup(outside_dir.cleanup)
        outside = os.path.join(outside_dir.name, "outside-map.md")
        with open(outside, "w") as f:
            f.write("# area\n")
        os.symlink(outside, os.path.join(self.root, ".asgard", "map", "area.md"))
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.assertEqual(jout(self.verify(level="full"))["verdict"], "FAIL")
        before = jout(self.qlog("state"))["diff_hash"]
        with open(outside, "w") as f:
            f.write("# tampered area\n")
        state = jout(self.qlog("state"))
        self.assertEqual(state["diff_hash"], before)
        self.assertFalse(state["pass_hash_match"])

        from asgard_hooklib import scope as scope_module

        from asgard.hooks import quest_log, verifier_gate

        link = os.path.join(self.root, ".asgard", "map", "area.md")
        with mock.patch.object(scope_module.os, "open", side_effect=AssertionError("external target opened")):
            self.assertIn(os.fsencode(outside), scope_module.symlink_map_state(link))
        self.assertIs(verifier_gate.diff_state, quest_log.diff_state)  # 같은 판정을 두 훅이 나눠 갖지 않는다

    def test_gate_blocks_map_symlink_added_after_clean_pass(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.assertEqual(jout(self.verify(level="full"))["verdict"], "PASS")
        os.makedirs(os.path.join(self.root, ".asgard", "map"), exist_ok=True)
        outside = tempfile.NamedTemporaryFile(suffix=".md")
        self.addCleanup(outside.close)
        os.symlink(outside.name, os.path.join(self.root, ".asgard", "map", "area.md"))

        blocked = self.gate()
        self.assertEqual(blocked.returncode, 0)
        self.assertEqual(jout(blocked)["decision"], "block")
        self.assertIn("unsafe code map", blocked.stdout)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO is unavailable on this platform")
    def test_nonregular_area_map_symlink_fails_without_blocking(self):
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        fifo = os.path.join(self.root, "area.fifo")
        os.mkfifo(fifo)
        os.symlink(fifo, os.path.join(self.root, ".asgard", "map", "area.md"))
        self.open_quest()
        self.write("app.py", "print('ok')\n")

        started = time.monotonic()
        result = jout(self.verify(level="full"))
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result["verdict"], "FAIL")

    def test_close_map_nudge_silent_without_map_or_change(self):
        # 지도 미도입 → 구조 변경이 있어도 침묵 (기존 프로젝트에 강요하지 않는다 — fail-open)
        self.open_quest()
        self.write("src/new_module.py", "x = 1\n")
        self.verify()
        out = jout(self.qlog("close"))
        self.assertNotIn("map_update", out)
        # 지도 도입 + 내용 수정(M)만 → 구조 변경 아님, 침묵
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)  # 신규 파일 흡수 — base를 깨끗하게
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "absorb"], check=True)
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        self.qlog("open", "q2", "--criteria", "edit only")
        self.write("README.md", "hello edited\n")
        self.verify()
        out = jout(self.qlog("close", "q2"))
        self.assertNotIn("map_update", out)


class TestQuestPrune(TrinityBase):
    """닫힌 퀘스트 keep-last-N 정리 — 보호 3종(포인터·미종결·미채굴 신호)과 세션 포인터 GC."""

    def _closed_quest(self, qid, session, age):
        self.qlog("open", qid, "--criteria", "one", "--session", session, "--no-write")
        p = self.qlog("close", qid, "--session", session, "--force")
        self.assertEqual(p.returncode, 0, p.stderr)
        path = os.path.join(self.root, ".asgard", "quest", qid + ".jsonl")
        past = time.time() - age
        os.utime(path, (past, past))
        return path

    def test_prune_keeps_last_n_closed_quests_and_lock_files(self):
        from asgard.hooks.quest_log import prune_quests

        for i, age in ((1, 400), (2, 300), (3, 200), (4, 100)):
            self._closed_quest(f"q{i}", f"s{i}", age)
        pruned = prune_quests(self.root, {"quest_retention": 2})
        self.assertEqual(sorted(pruned), ["q1", "q2"])
        qdir = os.path.join(self.root, ".asgard", "quest")
        names = os.listdir(qdir)
        self.assertEqual(sorted(n for n in names if n.endswith(".jsonl")), ["q3.jsonl", "q4.jsonl"])
        self.assertNotIn("q1.lock", names)  # 로그와 lock은 함께 치운다
        self.assertNotIn("q2.lock", names)

    def test_prune_protects_pointer_targets_and_unclosed_logs(self):
        from asgard.hooks.quest_log import prune_quests

        qdir = os.path.join(self.root, ".asgard", "quest")
        self._closed_quest("q1", "s1", 500)
        # 전역 LAST 대상은 상한 밖이어도 보존 — Stop 훅 완료 판정(memory-activate)이 재독한다
        with open(os.path.join(qdir, "LAST"), "w") as f:
            f.write("q1\n")
        # 미종결 로그(quest_closed 없음·포인터 유실) = 크래시 흔적 — 증거가 살아있으니 삭제 금지
        crashed = os.path.join(qdir, "crashed.jsonl")
        with open(crashed, "w") as f:
            f.write(json.dumps({"quest_id": "crashed", "event": "work"}) + "\n")
        past = time.time() - 400
        os.utime(crashed, (past, past))
        self._closed_quest("q2", "s2", 300)
        self._closed_quest("q3", "s3", 200)
        self._closed_quest("q4", "s4", 100)
        self.qlog("open", "q0", "--criteria", "x", "--session", "s0", "--no-write")  # 활성 → 보존
        pruned = prune_quests(self.root, {"quest_retention": 1})
        self.assertEqual(sorted(pruned), ["q2", "q3", "q4"])  # keep 슬롯은 최신 로그(q0)가 차지
        left = sorted(n for n in os.listdir(qdir) if n.endswith(".jsonl"))
        self.assertEqual(left, ["crashed.jsonl", "q0.jsonl", "q1.jsonl"])

    def test_prune_spares_unmined_learning_signal_until_mined(self):
        from asgard.hooks.quest_log import prune_quests

        qdir = os.path.join(self.root, ".asgard", "quest")
        os.makedirs(qdir, exist_ok=True)
        hard = os.path.join(qdir, "hardwon.jsonl")
        events = [
            {"quest_id": "hardwon", "event": "verify", "verdict": "FAIL", "failure_sig": "tests-fail"},
            {
                "quest_id": "hardwon",
                "event": "verify",
                "verdict": "PASS",
                "commands": [{"cmd": "pytest -q", "exit_code": 0}],
            },
            {"quest_id": "hardwon", "event": "quest_closed"},
        ]
        with open(hard, "w") as f:
            f.writelines(json.dumps(e) + "\n" for e in events)
        past = time.time() - 500
        os.utime(hard, (past, past))
        for i, age in ((1, 300), (2, 200)):
            self._closed_quest(f"q{i}", f"s{i}", age)
        self.assertEqual(prune_quests(self.root, {"quest_retention": 1}), ["q1"])
        self.assertTrue(os.path.exists(hard))  # 미채굴 hard-won 신호 → 소급 채굴 전까지 보존
        from asgard.evolution import mine

        mine(self.root)
        self.assertEqual(prune_quests(self.root, {"quest_retention": 1}), ["hardwon"])

    def test_prune_gc_closed_session_pointers_keeps_live_and_recent(self):
        from asgard.hooks.quest_log import prune_quests

        sessions = os.path.join(self.root, ".asgard", "quest", "sessions")
        for i, age in ((1, 400), (2, 300), (3, 200), (4, 100)):
            self._closed_quest(f"q{i}", f"s{i}", age)
            pointer = os.path.join(sessions, f"s{i}.known")
            past = time.time() - age
            os.utime(pointer, (past, past))
        self.qlog("open", "q9", "--criteria", "x", "--session", "live", "--no-write")
        prune_quests(self.root, {"quest_retention": 2})
        left = sorted(os.listdir(sessions))
        self.assertIn("live.active", left)  # 살아있는 세션은 GC 면제
        self.assertIn("s3.known", left)
        self.assertIn("s4.known", left)
        self.assertNotIn("s1.known", left)
        self.assertNotIn("s2.known", left)

    def test_close_triggers_prune_via_policy(self):
        self.policy(quest_retention=1)
        self._closed_quest("q1", "s1", 300)
        self.qlog("open", "q2", "--criteria", "two", "--session", "s2", "--no-write")
        p = self.qlog("close", "q2", "--session", "s2", "--force")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(jout(p).get("pruned"), 1)
        qdir = os.path.join(self.root, ".asgard", "quest")
        self.assertEqual([n for n in os.listdir(qdir) if n.endswith(".jsonl")], ["q2.jsonl"])

    def test_retention_zero_disables_prune(self):
        from asgard.hooks.quest_log import prune_quests

        for i, age in ((1, 300), (2, 200)):
            self._closed_quest(f"q{i}", f"s{i}", age)
        self.assertEqual(prune_quests(self.root, {"quest_retention": 0}), [])
        qdir = os.path.join(self.root, ".asgard", "quest")
        self.assertEqual(len([n for n in os.listdir(qdir) if n.endswith(".jsonl")]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
