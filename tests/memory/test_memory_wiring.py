"""memory 호스트 배선 — 1차 주입 게이트 doctor, Claude Code settings 훅 배선과 memory-activate 동작."""

import hashlib
import json
import os
import re
import time
from unittest import mock

from memory_base import MemoryBase
from typer.testing import CliRunner

from asgard import memory
from asgard.cli import app


class TestPersonalMemoryDoctor(MemoryBase):
    """1차 메모리 주입 게이트 doctor 표면 — 무음 차단 가시화.

    26-07-21 실측: 프로젝트 설정의 provider 선택이 inject_allowed를 기본 거부로 만들어
    "저장은 되는데 어떤 세션도 회상하지 못하는" 상태가 경고 없이 지속됐다."""

    def test_project_selected_provider_block_is_visible_and_allowlist_cures(self):
        from asgard.commands.doctor import _personal_memory_check

        proj = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(proj, ".asgard"), exist_ok=True)
        open(os.path.join(proj, ".asgard", "asgard-setting-project.json"), "w").write(
            json.dumps({"provider": {"name": "claude-native", "model": "haiku"}})
        )
        check = _personal_memory_check(proj)
        assert check is not None
        self.assertFalse(check["ok"])
        self.assertIn("claude-native", check["detail"])
        self.assertIn("providers", check["fix"])  # 처방 = 글로벌 allowlist 명시 허용
        os.makedirs(os.path.join(self.tmp, ".asgard"), exist_ok=True)
        open(os.path.join(self.tmp, ".asgard", "asgard-setting-global.json"), "w").write(
            json.dumps({"memory": {"providers": ["claude-native"]}})
        )
        cured = _personal_memory_check(proj)
        assert cured is not None
        self.assertTrue(cured["ok"])

    def test_kill_switch_reports_ok_as_intentional(self):
        from asgard.commands.doctor import _personal_memory_check

        os.environ["ASGARD_MEMORY_INJECT"] = "off"
        try:
            check = _personal_memory_check(self.tmp)
            assert check is not None
            self.assertTrue(check["ok"])
            self.assertIn("kill switch", check["detail"])
        finally:
            os.environ.pop("ASGARD_MEMORY_INJECT", None)


class TestCCWiring(MemoryBase):
    """Claude Code 배선 — settings 훅 배선, memory-activate 훅 동작, doctor 단선 탐지."""

    HOOK = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src",
        "asgard",
        "hooks",
        "memory_activate.py",
    )

    def test_completion_context_requires_current_approved_close(self):
        from asgard.hooks import memory_activate, quest_log

        root = os.path.join(self.tmp, "project")
        quest_dir = os.path.join(root, ".asgard", "quest")
        os.makedirs(os.path.join(quest_dir, "sessions"), exist_ok=True)
        qid = "q-memory"
        log = os.path.join(quest_dir, qid + ".jsonl")
        verify = {
            "event": "verify",
            "verdict": "PASS",
            "session_id": "s1",
            "commands": [{"cmd": "pytest", "exit_code": 0}],
        }

        def write_events(events):
            with open(log, "w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event) + "\n")
            with open(os.path.join(quest_dir, "LAST"), "w", encoding="utf-8") as handle:
                handle.write(qid)

        write_events([verify])
        self.assertFalse(memory_activate._completion_context(root, "s1")["verified"])

        approved_close = {
            "event": "quest_closed",
            "session_id": "s1",
            "risk": {"decision": "APPROVED", "forced": False},
        }
        write_events([verify, approved_close])
        summary = {"changed_files": ["app.py"]}
        with (
            mock.patch.object(quest_log, "summarize", return_value=summary),
            mock.patch.object(quest_log, "completion_decision", return_value=("APPROVED", "pass", "ok")),
        ):
            context = memory_activate._completion_context(root, "s1")
        self.assertTrue(context["verified"])
        self.assertEqual(context["changed_files"], ["app.py"])

        with (
            mock.patch.object(quest_log, "summarize", return_value=summary),
            mock.patch.object(quest_log, "completion_decision", return_value=("REJECTED", "stale", "stale hash")),
        ):
            self.assertFalse(memory_activate._completion_context(root, "s1")["verified"])

        write_events([verify, {**approved_close, "risk": {"decision": "ESCALATED", "forced": False}}])
        self.assertFalse(memory_activate._completion_context(root, "s1")["verified"])

        write_events([verify, {**approved_close, "session_id": "s2"}])
        with (
            mock.patch.object(quest_log, "summarize", return_value=summary),
            mock.patch.object(quest_log, "completion_decision", return_value=("APPROVED", "pass", "ok")),
        ):
            self.assertFalse(memory_activate._completion_context(root, "s1")["verified"])

    def _run_hook(self, payload: dict, path_dirs: list[str], mode: str | None = None) -> str:
        import subprocess
        import sys as _sys

        env = {**os.environ, "PATH": os.pathsep.join(path_dirs)}
        r = subprocess.run(
            [_sys.executable, self.HOOK, *([mode] if mode else [])],
            input=_json_dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(r.returncode, 0)  # 훅은 어떤 경우에도 세션을 막지 않는다
        return r.stdout

    def _fake_asgard(self, output: str) -> str:
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        p = os.path.join(bindir, "asgard")
        open(p, "w").write(f'#!/bin/sh\nprintf %s "{output}"\n')
        os.chmod(p, 0o755)
        return bindir

    def test_cc_settings_contains_memory_wiring(self):
        import json as j

        from asgard.templates.claude import cc_settings

        s = j.loads(cc_settings())
        self.assertIn("memory-activate", j.dumps(s["hooks"]["SessionStart"]))
        mem_entries = [e for e in s["hooks"]["SubagentStart"] if "memory-activate" in j.dumps(e)]
        self.assertEqual(len(mem_entries), 1)
        self.assertEqual(mem_entries[0]["matcher"], "^asgard-thinker$")  # Thinker 한정 (감사 매트릭스)
        self.assertIn("memory-activate", j.dumps(s["hooks"]["Stop"]))

    def test_hook_registry_and_scaffold(self):
        from asgard.commands.setup import MEMORY_SKILL_MD
        from asgard.hooks import script

        self.assertIn("memory snapshot", script("memory-activate"))
        self.assertIn("ingest", MEMORY_SKILL_MD)  # 저장 계약 스킬 — 승인 게이트 경유

    def test_hook_session_start_injects(self):
        bindir = self._fake_asgard("<memory-context>HELLO</memory-context>")
        out = self._run_hook({"hook_event_name": "SessionStart", "source": "startup"}, [bindir])
        self.assertIn("HELLO", out)

    def test_hook_subagent_thinker_only(self):
        bindir = self._fake_asgard("<memory-context>HELLO</memory-context>")
        self.assertIn(
            "HELLO", self._run_hook({"hook_event_name": "SubagentStart", "agent_type": "asgard-thinker"}, [bindir])
        )
        for agent in ("asgard-worker", "asgard-verifier", "asgard-loki", "asgard-freyja", ""):
            out = self._run_hook({"hook_event_name": "SubagentStart", "agent_type": agent}, [bindir])
            self.assertEqual(out, "", f"agent {agent!r} 에 주입되면 안 된다")

    def test_hook_silent_without_asgard(self):
        empty = os.path.join(self.tmp, "empty-bin")
        os.makedirs(empty, exist_ok=True)
        self.assertEqual(self._run_hook({"hook_event_name": "SessionStart"}, [empty]), "")

    def test_doctor_detects_missing_wiring(self):
        import json as j

        from asgard.commands.doctor import _trinity_checks

        root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(root, ".claude", "hooks"), exist_ok=True)
        open(os.path.join(root, "AGENTS.md"), "w").write("asgard:trinity")
        open(os.path.join(root, ".claude", "settings.json"), "w").write(
            j.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "memory-activate.py"}]}]}})
        )

        def check(name="memory wiring (CC)"):
            return next(c for c in _trinity_checks(root) if c["name"] == name)

        self.assertFalse(check()["ok"])  # 훅 파일 없음 → 단선 경고
        open(os.path.join(root, ".claude", "hooks", "memory-activate.py"), "w").write("# hook")
        self.assertFalse(check()["ok"])  # 요청별 recall + skill 아직 없음
        open(os.path.join(root, ".claude", "settings.json"), "w").write(
            j.dumps(
                {
                    "hooks": {
                        "SessionStart": [{"hooks": [{"command": "memory-activate.py"}]}],
                        "UserPromptSubmit": [{"hooks": [{"command": "memory-activate.py"}]}],
                        "Stop": [{"hooks": [{"command": "memory-activate.py"}]}],
                    }
                }
            )
        )
        os.makedirs(os.path.join(root, ".claude", "skills", "asgard-memory"), exist_ok=True)
        open(os.path.join(root, ".claude", "skills", "asgard-memory", "SKILL.md"), "w").write("# memory")
        self.assertTrue(check()["ok"])  # hook + snapshot + recall + skill = 정상

    def test_codex_and_cursor_scaffold_full_memory_lifecycle(self):
        import json as j
        import tomllib

        from asgard.commands.setup import plan_files

        cursor = dict(plan_files(cc=False, cursor=True, codex=False, root="/workspace")[0])
        cursor_hooks = j.loads(cursor["/workspace/.cursor/hooks.json"])["hooks"]
        self.assertIn("/workspace/.cursor/hooks/memory-activate.py", cursor)
        self.assertIn("memory-activate", j.dumps(cursor_hooks["sessionStart"]))
        self.assertIn("memory-activate", j.dumps(cursor_hooks["beforeSubmitPrompt"]))
        self.assertIn("memory-activate", j.dumps(cursor_hooks["stop"]))
        self.assertIn("/workspace/.agents/skills/asgard-memory/SKILL.md", cursor)

        codex = dict(plan_files(cc=False, cursor=False, codex=True, root="/workspace")[0])
        codex_hooks = tomllib.loads(codex["/workspace/.codex/config.toml"])["hooks"]
        self.assertIn("/workspace/.codex/hooks/memory-activate.py", codex)
        self.assertIn("memory-activate", j.dumps(codex_hooks["SessionStart"]))
        self.assertIn("memory-activate", j.dumps(codex_hooks["UserPromptSubmit"]))
        self.assertIn("memory-activate", j.dumps(codex_hooks["Stop"]))
        self.assertIn("/workspace/.agents/skills/asgard-memory/SKILL.md", codex)

    def test_cursor_native_prompt_recall_and_stop_sync(self):
        import json as j

        bindir = os.path.join(self.tmp, "cursor-bin")
        os.makedirs(bindir, exist_ok=True)
        fake = os.path.join(bindir, "asgard")
        open(fake, "w").write(
            "#!/bin/sh\n"
            '[ "$1" = memory ] && [ "$2" = recall ] && [ "$4" = cursor ] '
            "&& printf '%s' '<memory-recall>CURSOR</memory-recall>'\n"
            '[ "$1" = memory ] && [ "$2" = sync-turn ] && [ "$4" = cursor ] '
            '&& printf \'%s\' \'{"proposal":{"preview":"CURSOR-PROPOSAL"}}\'\n'
            "exit 0\n"
        )
        os.chmod(fake, 0o755)

        recall = self._run_hook(
            {"hook_event_name": "beforeSubmitPrompt", "prompt": "project history"}, [bindir], mode="cursor"
        )
        self.assertIn("CURSOR", j.loads(recall)["additional_context"])

        transcript = os.path.join(self.tmp, "cursor.jsonl")
        with open(transcript, "w", encoding="utf-8") as handle:
            handle.write(j.dumps({"role": "user", "message": {"content": [{"type": "text", "text": "요청"}]}}) + "\n")
            handle.write(
                j.dumps({"role": "assistant", "message": {"content": [{"type": "text", "text": "완료"}]}}) + "\n"
            )
        stopped = self._run_hook(
            {
                "hook_event_name": "stop",
                "conversation_id": "cursor-session",
                "transcript_path": transcript,
                "cwd": self.tmp,
            },
            [bindir],
            mode="cursor",
        )
        self.assertIn("CURSOR-PROPOSAL", j.loads(stopped)["followup_message"])

    def test_cc_noninteractive_approval_executes_the_exact_saved_plan(self):

        runner = CliRunner()
        text = "Lagom ultra CUS-218 full 100 percent success reason"
        planned = runner.invoke(app, ["memory", "ingest", text, "--kind", "decision"])
        self.assertEqual(planned.exit_code, 2)  # 되묻지 못해 못 끝냈다 — `--plan-id … --yes`로 풀린다
        approval = re.search(r"approval-id:\s*([0-9a-f]{64})", planned.stdout)
        self.assertIsNotNone(approval)
        assert approval is not None

        memory.add("Lagom ultra CUS-218 full 100 percent success", title="lagom")
        executed = runner.invoke(
            app,
            ["memory", "ingest", text, "--kind", "decision", "--yes", "--plan-id", approval.group(1)],
        )

        self.assertEqual(executed.exit_code, 0)
        self.assertIn("created:", executed.stdout)
        self.assertNotIn("merged: lagom", executed.stdout)
        replay = runner.invoke(
            app,
            ["memory", "ingest", text, "--kind", "decision", "--yes", "--plan-id", approval.group(1)],
        )
        self.assertEqual(replay.exit_code, 2)  # 소진된 계획 id — 다시 ingest 하면 풀린다

    def test_pending_approval_does_not_store_original_text(self):
        from asgard.commands import memory as memory_command

        text = "승인 전에는 이 개인 원문을 평문으로 저장하지 않는다"
        plan_id = memory_command._save_plan(text, "user", memory.plan_ingest(text))
        raw = open(os.path.join(self.d, ".pending-plans", f"{plan_id}.json"), encoding="utf-8").read()

        self.assertNotIn(text, raw)
        self.assertIn(hashlib.sha256(text.encode()).hexdigest(), raw)

    def test_concurrent_personal_approval_has_exactly_one_winner(self):
        import threading

        from asgard.commands import memory as memory_command

        text = "사용자는 동시 승인 테스트에서 pytest를 선호한다."
        plan_id = memory_command._save_plan(text, "user", memory.plan_ingest(text))
        entered = threading.Event()
        release = threading.Event()
        original_ingest = memory.ingest

        def slow_ingest(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(10))
            return original_ingest(*args, **kwargs)

        results: list[int] = []
        with mock.patch.object(memory_command.memory, "ingest", side_effect=slow_ingest):
            first = threading.Thread(
                target=lambda: results.append(memory_command.run_ingest(text, "user", True, plan_id))
            )
            first.start()
            self.assertTrue(entered.wait(10))
            second = threading.Thread(
                target=lambda: results.append(memory_command.run_ingest(text, "user", True, plan_id))
            )
            second.start()
            second.join(1)
            release.set()
            first.join(10)
            second.join(10)

        # 두 번째 호출은 이미 소진된 계획을 집는다 — 다시 시도한다고 풀리지 않으므로 2.
        self.assertEqual(sorted(results), [0, 2])
        self.assertEqual(len(memory._pages(self.d)), 1)

    def test_failed_personal_approval_can_retry_same_id(self):
        from asgard.commands import memory as memory_command

        text = "실패한 개인 승인은 같은 ID로 재시도할 수 있다."
        plan_id = memory_command._save_plan(text, "note", memory.plan_ingest(text))
        with mock.patch.object(memory_command.memory, "ingest", side_effect=OSError("temporary")):
            self.assertEqual(memory_command.run_ingest(text, "note", True, plan_id), 1)

        self.assertEqual(memory_command.run_ingest(text, "note", True, plan_id), 0)
        self.assertEqual(len(memory._pages(self.d)), 1)

    def test_stale_crashed_personal_approval_claim_can_retry(self):
        from asgard.commands import memory as memory_command

        text = "crash 이후 lease가 만료된 승인은 복구한다."
        plan_id = memory_command._save_plan(text, "note", memory.plan_ingest(text))
        _plan, token = memory_command._claim_plan(plan_id, text, "note")
        claimed = memory_command._claimed_path(plan_id, token)
        stale = time.time() - memory_command.PERSONAL_CLAIM_LEASE_SECONDS - 1
        os.utime(claimed, (stale, stale))

        _recovered, recovered_token = memory_command._claim_plan(plan_id, text, "note")
        memory_command._finish_plan(plan_id, recovered_token, success=False)

        self.assertTrue(os.path.exists(os.path.join(memory_command._pending_dir(), f"{plan_id}.json")))

    def test_stale_claim_after_merge_write_retries_as_idempotent_success(self):
        from asgard.commands import memory as memory_command

        memory.ingest("Lagom ultra는 CUS-218에서 제거됐다.", kind="decision")
        text = "Lagom ultra 제거는 CUS-218 검증 결과다."
        plan = memory.plan_ingest(text)
        self.assertEqual(plan["action"], "merge")
        plan_id = memory_command._save_plan(text, "decision", plan)
        claimed_plan, token = memory_command._claim_plan(plan_id, text, "decision")
        self.assertEqual(memory.ingest(text, kind="decision", plan=claimed_plan)[0], "merged")
        claimed = memory_command._claimed_path(plan_id, token)
        stale = time.time() - memory_command.PERSONAL_CLAIM_LEASE_SECONDS - 1
        os.utime(claimed, (stale, stale))

        self.assertEqual(memory_command.run_ingest(text, "decision", True, plan_id), 0)
        page = memory._read(self.d, plan["slug"])
        assert page is not None
        self.assertEqual(page[1].count(text), 1)

    def test_cc_snapshot_client_mode_ignores_native_allowlist_but_honors_killswitch(self):
        """클라이언트 모드는 전 모드 동일 기억(오딘 결정 26-07-23) — allowlist는 네이티브
        provider 통제 표면이라 CC/Codex/Cursor 주입을 막지 않는다. 끄는 길은 킬스위치뿐."""

        memory.add("CC provider gate secret", title="cc-provider-secret")
        os.makedirs(os.path.join(self.tmp, ".asgard"), exist_ok=True)
        cfg = os.path.join(self.tmp, ".asgard", "config.toml")
        open(cfg, "w").write('[memory]\nproviders = ["ollama"]\n')

        result = CliRunner().invoke(app, ["memory", "snapshot", "--provider", "claude-code"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("cc-provider-secret", result.stdout)

        open(cfg, "w").write('[memory]\ninject = "off"\nproviders = ["ollama"]\n')
        result = CliRunner().invoke(app, ["memory", "snapshot", "--provider", "claude-code"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("cc-provider-secret", result.stdout)

    def test_cc_user_prompt_submit_injects_query_recall(self):
        import json as j

        from asgard.templates.claude import cc_settings

        settings = j.loads(cc_settings())
        self.assertIn("memory-activate", j.dumps(settings["hooks"]["UserPromptSubmit"]))
        bindir = os.path.join(self.tmp, "recall-bin")
        os.makedirs(bindir, exist_ok=True)
        fake = os.path.join(bindir, "asgard")
        open(fake, "w").write(
            '#!/bin/sh\n[ "$1" = memory ] && [ "$2" = recall ] && [ "$6" = alpha-773 ] '
            '&& printf %s "<memory-recall>DETAIL</memory-recall>"\n'
        )
        os.chmod(fake, 0o755)

        out = self._run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "alpha-773"}, [bindir])

        payload = j.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("<memory-recall>DETAIL</memory-recall>", payload["hookSpecificOutput"]["additionalContext"])

    def test_cc_stop_syncs_completed_turn_and_surfaces_memory_proposal(self):
        import json as j

        bindir = os.path.join(self.tmp, "stop-bin")
        os.makedirs(bindir, exist_ok=True)
        fake = os.path.join(bindir, "asgard")
        open(fake, "w").write(
            "#!/bin/sh\n"
            '[ "$1" = memory ] && printf \'%s\' \'{"status":"retained","proposal":{"preview":"중요 사건 사용자 승인 제안"},"automation":"mental model 자동 유지보수 시작"}\'\n'
            "exit 0\n"
        )
        os.chmod(fake, 0o755)
        out = self._run_hook(
            {
                "hook_event_name": "Stop",
                "session_id": "cc-session-1",
                "prompt": "메모리 lifecycle을 구현해줘",
                "last_assistant_message": "구현과 검증을 완료했다.",
                "cwd": self.tmp,
            },
            [bindir],
        )
        payload = j.loads(out)
        self.assertIn("중요 사건 사용자 승인 제안", payload["systemMessage"])
        self.assertIn("mental model 자동 유지보수 시작", payload["systemMessage"])
        self.assertNotIn("탐색 발견 저장 후보", payload["systemMessage"])  # 넛지 침묵 = systemMessage에 미등장

    def test_cc_stop_surfaces_every_nudge_from_one_tick(self):
        """턴 끝 넛지 CC 배선 — `memory tick` 한 번이 낸 줄이 전부 Stop systemMessage 로 나온다.

        종전에는 자식 넷(evolve nudge · norn --wake · pattern --due · semantic nudge)을 훅이
        차례로 띄웠다. 판정은 그대로 CLI 소유고 훅은 전달만 하므로, 이 시험은 **여러 줄이
        빠짐없이** 올라오는지를 본다 — 한 줄만 보면 합치면서 뒤가 잘려도 통과한다."""
        import json as j

        bindir = os.path.join(self.tmp, "nudge-bin")
        os.makedirs(bindir, exist_ok=True)
        fake = os.path.join(bindir, "asgard")
        open(fake, "w").write(
            "#!/bin/sh\n"
            '[ "$1" = memory ] && [ "$2" = tick ] && '
            "printf '%s\\n%s\\n' \"진화 후보 신호 1건 — asgard evolve scan 으로 채굴\" "
            '"위그드라실 노른 통합이 밀렸어요"\n'
            '[ "$1" = memory ] && printf \'%s\' \'{"status":"skipped"}\'\n'
            "exit 0\n"
        )
        os.chmod(fake, 0o755)
        out = self._run_hook(
            {
                "hook_event_name": "Stop",
                "session_id": "cc-session-2",
                "prompt": "버그 잡아줘",
                "last_assistant_message": "수정과 검증을 완료했다.",
                "cwd": self.tmp,
            },
            [bindir],
        )
        payload = j.loads(out)
        self.assertIn("⠶", payload["systemMessage"])
        self.assertIn("진화 후보 신호 1건", payload["systemMessage"])
        self.assertIn("위그드라실 노른 통합이 밀렸어요", payload["systemMessage"])


def _json_dumps(payload: dict) -> str:
    import json as j

    return j.dumps(payload)
