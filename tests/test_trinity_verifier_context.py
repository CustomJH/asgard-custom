#!/usr/bin/env python3
"""판정자에게 가는 입력 — 실행 기록 주입, 트랜스크립트 훑기, 실패 누적 에스컬레이션."""

import glob
import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest

from hookscaffold import deploy_library
from trinity_base import (
    SRC,
    TRACKER,
    VCONTEXT,
    TrinityBase,
    jout,
    run,
)


class TestVerifierContext(TrinityBase):
    """판정자에게 하네스 관측 기록을 넘기는 자리 — 없으면 판정 범위를 판정받는 쪽이 정한다.

    26-08-12 실측: 코디네이터가 "이번 델타만" 이라고 적자 트리에 이미 있던 변경이 한 라운드
    통째로 안 판정됐다. 그 입력은 네이티브 루프에만 있었고 이쪽으로 오는 길이 없었다."""

    def payload(self, agent="asgard-verifier", **extra):
        return json.dumps(
            {
                "agent_type": agent,
                "session_id": "s1",
                "cwd": self.root,
                "hook_event_name": "SubagentStart",
                **extra,
            }
        )

    def transcript(self, *calls, stamp=None):
        """(도구, 인자, 결과, 오류인가) 목록을 기록 파일로 — 실물 모양 그대로.

        시각은 기본으로 **안 적는다**. 고정 시각을 박으면 그 시각이 지난 뒤 구간 필터가 전부
        걸러내 시험이 조용히 죽는다 — 실제로 그렇게 죽었다(판정 `time-dependent-test-fixture`).
        구간 자체를 재는 시험만 `stamp` 로 시각을 준다."""
        rows = []
        for i, (tool, request, output, failed) in enumerate(calls):
            use_id = "toolu_%d" % i
            when = {"timestamp": stamp} if stamp else {}
            rows.append(
                {
                    **when,
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": use_id, "name": tool, "input": request}],
                    },
                }
            )
            rows.append(
                {
                    **when,
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": use_id, "content": output, "is_error": failed}
                        ],
                    },
                }
            )
        path = os.path.join(self.root, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return path

    def rollout(self, *calls, stamp=None):
        """Codex 의 rollout 기록 — 실물 모양 그대로 `(이름, 인자, 결과)` 를 받는다.

        `exec_command` 는 인자가 JSON 이고 결과 머리말에 종료 코드가 오지만, 압도적으로 많은
        `exec` 는 인자가 JS 한 토막이고 결과에 종료 코드가 없다. 두 갈래를 다 세워야 판정자가
        읽는 표식(`ok`·`exit N`·`ran`)이 실제 기록에서 나온 것인지 확인된다."""
        rows = []
        for i, (name, request, output) in enumerate(calls):
            call_id = "call_%d" % i
            when = {"timestamp": stamp} if stamp else {}
            kind = "function_call" if name == "exec_command" else "custom_tool_call"
            field = "arguments" if kind == "function_call" else "input"
            rows.append(
                {
                    **when,
                    "type": "response_item",
                    "payload": {"type": kind, "name": name, field: request, "call_id": call_id},
                }
            )
            rows.append(
                {
                    **when,
                    "type": "response_item",
                    "payload": {"type": kind + "_output", "call_id": call_id, "output": output},
                }
            )
        return self.record("rollout.jsonl", rows)

    def cursor_chat(self, *calls):
        """Cursor 의 대화 기록 — 도구 이름과 인자만 남고 결과·id·시각은 하나도 없다.

        실측 21개 파일 318행에서 나온 `tool_use` 블록 654개가 전부 이 모양이었다. 인자는 도구
        605건이 JSON 객체이고 `ApplyPatch` 49건만 패치 본문이 날 문자열로 온다 — 두 모양을 다
        세워야 실물의 다수를 시험이 한 번도 안 밟는 일이 안 생긴다."""
        rows = [
            {"role": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": request}]}}
            for name, request in calls
        ]
        rows.append({"type": "turn_ended", "status": "success"})
        return self.record("cursor-chat.jsonl", rows)

    def record(self, name, rows):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return path

    def injected(self, path, agent="asgard-verifier"):
        p = run(VCONTEXT, stdin=self.payload(agent=agent, transcript_path=path), cwd=self.root)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else ""

    def commands_block(self, text):
        """주입문의 Commands 절만 — 꼬리의 설명 문장에 걸려 통과하는 시험을 막는다."""
        body = text.partition("Commands (")[2]
        return body.partition("A command that never ran")[0]

    def context(self, *calls, agent="asgard-verifier", stamp=None):
        path = self.transcript(*calls, stamp=stamp) if calls else os.path.join(self.root, "none.jsonl")
        return self.injected(path, agent=agent)

    def test_the_verifier_is_told_what_actually_ran(self):
        """워커의 말이 아니라 하네스가 본 것 — 명령과 그 끝, 그리고 쓴 파일."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        text = self.context(
            ("Bash", {"command": "pytest -q"}, "2 passed", False),
            ("Bash", {"command": "ruff check ."}, "Exit code 1\nE501 line too long", True),
            ("Edit", {"file_path": "/repo/app.py"}, "ok", False),
        )
        block = self.commands_block(text)
        self.assertIn("ok        pytest -q", block)
        self.assertIn("exit 1    ruff check .", block)
        self.assertIn("Edit          /repo/app.py", text, "쓰기 도구 호출 목록이 비었다")
        self.assertRegex(text, r"[AM]\tapp\.py", "변경 파일이 git 이 본 대로 안 실렸다")

    def test_a_failure_never_re_run_is_named(self):
        """판정이 물어야 할 것은 실패가 있었나가 아니라 실패가 남아 있나다."""
        self.open_quest()
        text = self.context(
            ("Bash", {"command": "pytest -q"}, "Exit code 1\nfailed", True),
            ("Bash", {"command": "ruff check ."}, "Exit code 2\nboom", True),
            ("Bash", {"command": "pytest -q"}, "2 passed", False),
        )
        self.assertIn("Never re-run after failing (1)", text)
        self.assertIn("ruff check .", text.split("Never re-run")[1])
        self.assertNotIn("pytest -q", text.split("Never re-run")[1], "고치고 다시 돌린 것은 미해결이 아니다")

    def test_a_blocked_call_is_marked_not_counted_as_a_failure(self):
        """가드가 막은 호출은 실행된 적이 없다 — 판정자는 그것이 있었다는 사실만 알면 된다."""
        self.open_quest()
        text = self.context(("Bash", {"command": "git push"}, "Asgard Canon Law 3/6 — irreversible git op", True))
        self.assertIn("blocked   git push", self.commands_block(text), "막힌 호출이 표식 없이 실렸다")
        self.assertNotIn("Never re-run after failing", text, "안 돈 호출이 미해결 실패로 셈됐다")

    def test_a_long_command_is_compared_whole_not_truncated(self):
        """화면용으로 자른 문자열로 맞대면 앞머리가 같은 서로 다른 명령이 한 명령으로 보인다."""
        self.open_quest()
        head = "pytest " + "-x " * 90  # 200자를 넘긴다
        text = self.context(
            ("Bash", {"command": head + "tests/a.py"}, "Exit code 1\nred", True),
            ("Bash", {"command": head + "tests/b.py"}, "2 passed", False),
        )
        self.assertIn("Never re-run after failing (1)", text, "긴 명령의 미해결 실패가 조용히 사라졌다")

    def test_the_interval_starts_at_the_anchor(self):
        """기준보다 앞선 호출은 이미 판정된 것이다 — 다시 들이밀면 새 신호가 묻힌다."""
        self.open_quest()
        text = self.context(("Bash", {"command": "old thing"}, "", False), stamp="2000-01-01T00:00:00Z")
        self.assertNotIn("old thing", text, "기준 앞의 호출이 실렸다")
        fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60))
        text = self.context(("Bash", {"command": "new thing"}, "", False), stamp=fresh)
        self.assertIn("new thing", self.commands_block(text))

    def test_harness_state_stays_out_of_the_file_list(self):
        """판정 해시가 안 덮는 자리를 보여 주면 판정자가 없는 변경을 지적한다."""
        self.open_quest()
        os.makedirs(os.path.join(self.root, ".asgard", "map"), exist_ok=True)
        self.write(".asgard/state/whatever.json", "{}\n")
        self.write(".asgard/map/PROJECT.md", "# map\n")
        self.write("app.py", "print('ok')\n")
        text = self.context(("Bash", {"command": "true"}, "", False))
        self.assertIn("app.py", text)
        self.assertIn(".asgard/map/PROJECT.md", text, "공유 지도는 증거 안이다")
        self.assertNotIn("state/whatever.json", text, "하네스 상태가 판정자 앞에 섰다")

    def test_an_unreadable_transcript_says_so_instead_of_showing_zero(self):
        """기록을 못 읽은 것과 아무것도 안 돌린 것은 다른 사실이다 — 빈 목록은 거짓말이 된다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        p = run(VCONTEXT, stdin=self.payload(transcript_path=os.path.join(self.root, "gone.jsonl")), cwd=self.root)
        text = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Execution record: unreadable", text)
        self.assertNotIn("Commands (0)", text, "안 돌린 것처럼 보이는 빈 목록이 나갔다")
        self.assertRegex(text, r"[AM]\tapp\.py", "기록이 없어도 변경 파일은 나가야 한다")

    def test_an_unrecognized_transcript_is_not_reported_as_an_absent_one(self):
        """형식을 못 알아본 것과 파일이 없는 것은 고칠 자리가 다르다.

        낯선 형식의 `transcript_path` 가 오면 예전에는 행이 파싱된다는 이유로 관측 성공으로 세어
        `Commands (0)` 이 나갔다 — 판정자에게 "워커가 아무것도 안 돌렸다"는 없는 사실이다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        path = os.path.join(self.root, "alien.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"kind": "something-else", "seq": 1}\n{"kind": "something-else", "seq": 2}\n')
        p = run(VCONTEXT, stdin=self.payload(transcript_path=path), cwd=self.root)
        text = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Execution record: unrecognized", text)
        self.assertNotIn("Commands (0)", text, "못 알아본 형식이 안 돌린 것으로 나갔다")

    def test_a_codex_rollout_reaches_the_verifier(self):
        """Codex 는 훅 페이로드로 rollout 경로를 직접 준다 — 막힌 것은 그 형식을 못 읽던 것뿐이다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        text = self.injected(
            self.rollout(
                (
                    "exec_command",
                    json.dumps({"cmd": "pytest -q"}),
                    "Wall time: 0.2 seconds\nProcess exited with code 0",
                ),
                (
                    "exec_command",
                    json.dumps({"cmd": "ruff check ."}),
                    "Wall time: 0.1 seconds\nProcess exited with code 1",
                ),
                ("apply_patch", "*** Begin Patch\n*** Update File: app.py\n@@\n-a\n+b\n*** End Patch", "Success."),
            )
        )
        block = self.commands_block(text)
        self.assertIn("ok        pytest -q", block)
        self.assertIn("exit 1    ruff check .", block)
        self.assertIn("Edit          app.py", text, "패치가 건드린 파일이 쓰기 목록에서 빠졌다")
        self.assertIn("Never re-run after failing (1)", text)

    def test_a_codex_call_with_no_recorded_exit_is_not_called_green(self):
        """`exec` 는 JS 래퍼가 안쪽 종료 코드를 안 실어 보낸다 — 실측 13,090건이 그 모양이다.

        그것을 `ok` 로 접으면 판정자가 아무도 확인하지 않은 초록을 읽는다. 명령문 자체는 래퍼
        안의 JSON 에서 떼어 와야 하고, 못 떼면 판정자에게 JS 한 토막이 명령이라고 나간다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        script = 'const r = await tools.exec_command({"cmd":"pytest -q","workdir":"/w"});\ntext(r.output);\n'
        text = self.injected(
            self.rollout(("exec", script, [{"type": "input_text", "text": "Script completed\nWall time 0.1 seconds"}]))
        )
        block = self.commands_block(text)
        self.assertIn("ran       pytest -q", block, "결과가 안 남은 호출의 명령문이 안 떼어졌다")
        self.assertNotIn("ok ", block, "결과를 못 읽은 호출이 성공으로 나갔다")
        self.assertNotIn("Never re-run after failing", text, "결과를 모르는 호출이 미해결 실패로 셈됐다")

    def test_a_codex_guard_refusal_is_marked_blocked(self):
        """Codex 는 가드 문구 앞에 자기 머리말을 붙인다 — 그 모양을 모르면 안 돈 명령이 실패가 된다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        refusal = "Command blocked by PreToolUse hook: Asgard Canon Law 3/6 — irreversible git op (branch -D)."
        text = self.injected(self.rollout(("exec_command", json.dumps({"cmd": "git branch -D old"}), refusal)))
        self.assertIn("blocked   git branch -D old", self.commands_block(text))
        self.assertNotIn("Never re-run after failing", text, "안 돈 호출이 미해결 실패로 셈됐다")

    def test_a_cursor_record_gives_the_calls_without_claiming_outcomes(self):
        """Cursor 기록에는 결과도 시각도 없다 — 무엇을 불렀는지는 주고 성패는 주장하지 않는다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        text = self.injected(
            self.cursor_chat(
                ("Shell", {"command": "pytest -q", "description": "시험"}),
                ("ApplyPatch", "*** Begin Patch\n*** Add File: app.py\n+print('ok')\n*** End Patch"),
            )
        )
        block = self.commands_block(text)
        self.assertIn("ran       pytest -q", block)
        self.assertIn("Write         app.py", text, "패치가 만든 파일이 쓰기 목록에서 빠졌다")
        self.assertIn("not what came back", text, "결과가 안 남는다는 사실이 판정자에게 안 갔다")
        self.assertIn("record for this session", text, "시각이 없는 기록에 구간을 잘랐다는 딱지가 붙었다")
        self.assertNotIn("Never re-run after failing", text)

    def test_a_cursor_record_is_found_from_the_conversation_id(self):
        """Cursor 페이로드에는 기록 경로가 없다 — 대화 id 와 작업 디렉터리로 짚어야 한다."""
        from asgard_hooklib.transcript import session_file

        home, chat = os.path.join(self.root, "home"), "70c09935-a89c-49db-ae1e-44a1b8fe7b83"
        folder = os.path.join(home, ".cursor", "projects", "tmp-work-space-a-b", "agent-transcripts", chat)
        os.makedirs(folder)
        path = os.path.join(folder, chat + ".jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"type": "turn_ended", "status": "success"}\n')
        payload = {"conversation_id": chat, "cwd": "/tmp/work_space/a-b"}
        self.assertEqual(session_file(payload, home=home), path)
        self.assertEqual(session_file({**payload, "conversation_id": "other"}, home=home), "")

    def test_every_client_gets_its_own_injection_schema(self):
        """세 모드가 같은 사실을 각자의 스키마로 받는다 — 스키마가 틀리면 호스트가 조용히 버린다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        path = self.transcript(("Bash", {"command": "pytest -q"}, "2 passed", False))
        for argv, reader in (
            (["claude-code"], lambda d: d["hookSpecificOutput"]["additionalContext"]),
            (["codex"], lambda d: d["hookSpecificOutput"]["additionalContext"]),
            (["cursor"], lambda d: d["additional_context"]),
        ):
            with self.subTest(client=argv[0]):
                p = run(VCONTEXT, argv, stdin=self.payload(transcript_path=path), cwd=self.root)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("pytest -q", reader(json.loads(p.stdout)))

    def test_only_the_verifier_gets_it(self):
        """워커·씽커에게 주면 판정 독립성이 아니라 그냥 컨텍스트 배포가 된다."""
        self.open_quest()
        for other in ("asgard-worker", "asgard-thinker", "asgard-loki"):
            with self.subTest(agent=other):
                self.assertEqual(self.context(("Bash", {"command": "true"}, "", False), agent=other), "")

    def test_no_quest_and_no_transcript_stay_silent(self):
        """주입이 판정 턴을 죽이면 본말전도다 — 실을 것이 없으면 아무 말도 안 한다."""
        p = run(VCONTEXT, stdin=self.payload(transcript_path="/nope/x.jsonl"), cwd=self.root)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "", "퀘스트가 없는데 주입했다")
        self.open_quest()
        p = run(VCONTEXT, stdin="not json", cwd=self.root)
        self.assertEqual(p.returncode, 0, "깨진 페이로드가 판정 턴을 막았다")

    def test_the_anchor_moves_to_the_last_verdict(self):
        """구간은 마지막 판정 이후다 — 이미 판정된 것을 다시 들이밀면 신호가 묻힌다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.qlog("append", "--role", "verifier", "--event", "verify", "--verdict", "PASS")
        text = self.context(("Bash", {"command": "true"}, "", False))
        self.assertIn("since the last verdict (turn 3)", text)


class TestWhatTheVerdictIsScoredOn(TrinityBase):
    """판정자가 명령을 고르기 전에 알아야 하는 것 — 채점 기준과 하네스가 이미 돌린 것.

    26-08-13 실측: 판정 130건에서 판정자가 직접 부른 명령 965건 중 253건이 pytest 였고, 하네스는
    그와 별개로 PASS 마다 프로젝트 베이스라인을 한 번 더 돌렸다 (판정당 median 121.8초). 두 쪽이
    같은 스위트를 한 트리에 두 번 돌린 것은 판정자가 하네스의 몫을 몰랐기 때문이다."""

    CHECK = "python -m compileall app.py"

    def payload(self, **extra):
        return json.dumps(
            {
                "agent_type": "asgard-verifier",
                "session_id": "s1",
                "cwd": self.root,
                "hook_event_name": "SubagentStart",
                **extra,
            }
        )

    def context(self, *commands):
        """주입 블록. 명령을 주면 그 호출이 실린 기록 파일을 함께 세운다 — 트리가 안 움직인
        라운드에서는 명령 기록이 있어야 블록 자체가 뜬다 (`main` 의 침묵 조건)."""
        # 기록 파일은 저장소 **밖**에 쓴다. 안에 쓰면 그 파일 자체가 추적 밖 변경으로 잡혀
        # (트리 비교가 추적 밖도 담는다) "변경 0" 갈래를 세우려는 시험이 변경 1 을 만든다.
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        path = os.path.join(outside, "none.jsonl")
        if commands:
            rows = []
            for i, command in enumerate(commands):
                use = "toolu_%d" % i
                rows.append(
                    {
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "tool_use", "id": use, "name": "Bash", "input": {"command": command}}],
                        }
                    }
                )
                rows.append(
                    {
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": use, "content": "ok", "is_error": False}
                            ],
                        }
                    }
                )
            path = os.path.join(outside, "transcript.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        p = run(VCONTEXT, stdin=self.payload(transcript_path=path), cwd=self.root)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else ""

    def test_the_declared_contracts_reach_the_verifier(self):
        """계약이 하네스에만 있으면 판정자는 자기 기준을 새로 세운다 — 채점표를 모르는 채로."""
        self.open_quest("--criteria", "app runs | verify: %s | artifacts: app.py" % self.CHECK)
        self.write("app.py", "print('ok')\n")
        text = self.context()
        self.assertIn("run       " + self.CHECK, text)
        self.assertIn("artifacts app.py", text)
        self.assertIn("[1] app runs", text, "계약이 어느 기준의 것인지 안 적혔다")

    def test_each_contract_keeps_its_own_command_and_artifacts(self):
        """계약을 짝 없이 이어 적으면 뒤 기준의 산출물이 앞 기준의 명령에 딸린 것으로 읽힌다."""
        self.open_quest(
            "--criteria",
            "first | verify: %s | artifacts: app.py" % self.CHECK,
            "--criteria",
            "second | artifacts: other.py",
        )
        self.write("app.py", "print('ok')\n")
        body = self.context().partition("Declared verify contracts")[2].partition("\n\n")[0]
        first = body.partition("[2]")[0]
        self.assertIn("artifacts app.py", first)
        self.assertNotIn("other.py", first, "둘째 기준의 산출물이 첫째 계약 밑에 섰다")
        self.assertIn("artifacts other.py", body.partition("[2]")[2])

    def test_the_project_baseline_command_reaches_the_verifier(self):
        """하네스는 PASS 뒤 이 명령을 어차피 돌린다 — 모르면 같은 스위트가 한 트리에 두 번 돈다."""
        self.policy(baseline_checks=[self.CHECK])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        text = self.context()
        self.assertIn("Project baseline — the harness runs this itself when it records a PASS", text)
        self.assertIn(self.CHECK, text)

    def test_every_baseline_command_the_harness_runs_reaches_the_verifier(self):
        """주입이 하네스보다 좁게 자르면, 판정자가 한 번도 못 본 명령이 PASS 채점에 남는다.

        26-08-13 codex 독립 판정이 잡은 자리 — 상한이 주입 5, 하네스 10 이라 여섯째부터 갈렸다."""
        checks = ["python -m compileall app%d.py" % i for i in range(6)]
        self.policy(baseline_checks=checks)
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        text = self.context()
        for cmd in checks:
            self.assertIn(cmd, text, "하네스가 돌리는 명령이 판정자에게 안 갔다: %s" % cmd)

    def test_baseline_commands_beyond_the_harness_cap_are_named_as_dropped(self):
        """상한을 넘겨 안 도는 명령은 조용히 사라지면 안 된다 — 설정한 사람이 돈다고 믿는다."""
        checks = ["python -m compileall app%d.py" % i for i in range(12)]
        self.policy(baseline_checks=checks)
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        text = self.context()
        self.assertIn("2 more declared, which the harness does not run either", text)

    def test_checks_already_run_are_named_with_the_tree_they_ran_on(self):
        """이미 돈 검사는 사실이지만 **그때 트리의** 사실이다 — 귀속을 빼면 판정자가 낡은 초록을 읽는다."""
        self.policy(baseline_checks=[self.CHECK])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verifier_seat()
        p = self.qlog("append", "--role", "verifier", "--event", "verify", "--verdict", "PASS")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(jout(p)["verdict"], "PASS", "베이스라인이 안 붙는 판정으로 시험이 헛돈다")
        self.write("app.py", "print('again')\n")  # 판정 뒤 트리를 움직여야 다음 판정 구간이 생긴다
        text = self.context()
        self.assertIn("Checks the harness already ran", text)
        self.assertIn("exit 0", text)
        self.assertIn("not on the tree you are judging", text)

    def test_an_untracked_file_counts_as_a_change_and_the_caveat_says_so(self):
        """주입면의 단서가 하네스 코드와 어긋나면 판정자가 틀린 전제로 판단한다.

        비교는 `current_tree_ref` 로 트리 둘을 짓고 그 트리는 추적 밖 파일까지 담는다. "추적된
        파일만 본다"고 적던 동안 그 문장은 거짓이었고, 반례가 같은 블록의 변경 목록에 서 있었다
        (26-08-14 판정자 2회차와 codex 4회차가 각각 잡았다)."""
        self.policy(baseline_checks=[self.CHECK])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verifier_seat()
        self.assertEqual(
            jout(self.qlog("append", "--role", "verifier", "--event", "verify", "--verdict", "PASS"))["verdict"], "PASS"
        )
        self.write("never_added.py", "x = 1\n")  # git add 를 안 한다 — 추적 밖 파일이다
        text = self.context()
        self.assertRegex(text, r"[AM]\tnever_added\.py", "추적 밖 파일이 변경 목록에서 빠졌다")
        self.assertNotIn("only watches tracked files", text, "하네스가 하는 일과 어긋나는 단서다")

    def test_the_unchanged_tree_caveat_names_what_the_comparison_really_drops(self):
        """변경이 0 일 때의 단서는 참인 것만 적어야 한다 — 빠지는 것은 무시 경로와 지도 밖 .asgard 다."""
        self.policy(baseline_checks=[self.CHECK])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verifier_seat()
        self.qlog("append", "--role", "verifier", "--event", "verify", "--verdict", "PASS")
        # 트리를 안 움직이고 판정자를 다시 세운다 — 명령 기록만으로 블록이 뜨는 갈래다.
        text = self.context("python -m compileall app.py")
        self.assertIn("Changed files (0)", text)
        self.assertNotIn("not on the tree you are judging", text, "안 움직인 트리를 움직였다고 단언했다")
        # `is_junk` 는 gitignore 여부와 **무관하게** 빼므로 무시 경로만 적으면 그 문장이 다시
        # 과장이 된다 (26-08-14 판정자 3회차가 auto-fix 로 남긴 자리 — 같은 종류의 과장이 그 앞
        # 라운드를 FAIL 로 만들었다).
        self.assertIn("ignored", text)
        self.assertIn("__pycache__", text)
        self.assertIn(".asgard/ outside the", text)
        self.assertNotIn("leaves out only", text, "빠지는 것을 다 안 적고 'only' 라고 단언했다")

    def test_the_verifier_is_never_told_to_skip_a_check(self):
        """판정 독립성은 판정자가 명령을 직접 돌리는 데서 나온다 — 주입면이 그것을 깎으면 안 된다."""
        self.policy(baseline_checks=[self.CHECK])
        self.open_quest("--criteria", "app runs | verify: %s | artifacts: app.py" % self.CHECK)
        self.write("app.py", "print('ok')\n")
        text = self.context().lower()
        # "whether or not you run it" 는 26-08-13 codex 독립 판정 2회차가 잡은 문구다 — 명령형이
        # 아니라서 위 목록을 다 지나갔는데, 읽는 쪽에는 "안 돌려도 된다" 는 허가로 닿는다.
        for phrase in (
            "do not run",
            "don't run",
            "no need to run",
            "skip the",
            "you may skip",
            "whether or not you run",
            "optional",
        ):
            self.assertNotIn(phrase, text, "주입면이 판정자에게 검사를 건너뛰어도 된다고 말했다")

    def test_a_check_that_timed_out_is_not_read_as_a_missing_exit_code(self):
        """상한을 넘긴 검사는 상한을 올리면 답이 나오고, 결과를 못 읽은 검사는 아니다 — 고칠 자리가 다르다."""
        spec = importlib.util.spec_from_file_location("asgard_verifier_context", VCONTEXT)
        self.assertIsNotNone(spec, VCONTEXT)
        assert spec is not None and spec.loader is not None  # ty 는 assertIsNotNone 을 안 좁힌다
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.check_mark({"timed_out": True, "exit_code": None}), "timeout")
        self.assertEqual(module.check_mark({"exit_code": None}), "no exit")
        self.assertEqual(module.check_mark({"exit_code": 1}), "exit 1")


class TestTranscriptSweep(TrinityBase):
    """Claude Code 의 도구 실패 레인 — 페이로드가 아니라 세션 기록에서 들어온다.

    그 호스트는 도구 호출이 실패하면 PostToolUse 를 안 부르므로, 위 클래스가 고정한 계약은
    여기서 한 번도 발화하지 않는다. 턴 경계(Stop)에서 기록 꼬리를 읽는 갈래가 그 몫을 진다."""

    def counts(self, sid="s1"):
        with open(os.path.join(self.root, ".asgard", "failures-" + sid + ".json"), encoding="utf-8") as handle:
            return json.load(handle)

    def fail_events(self):
        with open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"), encoding="utf-8") as handle:
            return [e for e in (json.loads(line) for line in handle) if e["event"] == "fail"]

    def transcript(self, *fails, ok=0):
        """도구 호출 결과가 든 기록 파일 하나 — 실패는 오류문으로, 성공은 개수로 준다."""
        rows = []
        for i, text in enumerate(fails):
            use_id = "toolu_f%d" % i
            rows.append(
                {"message": {"role": "assistant", "content": [{"type": "tool_use", "id": use_id, "name": "Bash"}]}}
            )
            rows.append(
                {
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": use_id, "is_error": True, "content": text}],
                    }
                }
            )
        for i in range(ok):
            use_id = "toolu_ok%d" % i
            rows.append(
                {"message": {"role": "assistant", "content": [{"type": "tool_use", "id": use_id, "name": "Bash"}]}}
            )
            rows.append(
                {
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": use_id, "content": "fine"}],
                    }
                }
            )
        path = os.path.join(self.root, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return path

    def stop(self, path, sid="s1"):
        payload = {"session_id": sid, "cwd": self.root, "transcript_path": path, "hook_event_name": "Stop"}
        return run(TRACKER, stdin=json.dumps(payload), cwd=self.root)

    def test_three_failures_in_the_transcript_reach_the_quest_log(self):
        """페이로드 없이 기록만으로 fail 이벤트가 적히고 전이가 재계획으로 간다."""
        self.open_quest()
        same = "command not found: foo"
        out = self.stop(self.transcript(same, same, same, ok=2))
        self.assertIn("systemMessage", out.stdout)
        self.assertIn("Canon Law 9", json.loads(out.stdout)["systemMessage"])
        self.assertEqual([f["failure_count"] for f in self.fail_events()], [3])
        self.assertEqual(jout(self.qlog("next"))["next_role"], "THINKER_REPLAN")

    def test_the_same_transcript_is_not_counted_twice(self):
        """Stop 은 턴마다 불리고 꼬리는 그대로 남는다 — 두 번 세면 없는 루프를 신고한다."""
        self.open_quest()
        path = self.transcript("boom", "boom")
        self.assertEqual(self.stop(path).stdout.strip(), "")  # 2회 — 임계 미만
        self.assertEqual(self.stop(path).stdout.strip(), "")  # 같은 꼬리를 다시 읽어도 안 는다
        self.assertEqual(list(self.counts().values()), [2])

    def test_a_new_failure_after_a_rescan_still_counts(self):
        """되짚기 장부가 새 실패까지 막으면 레인이 다시 죽는다."""
        self.open_quest()
        self.stop(self.transcript("boom", "boom"))
        out = self.stop(self.transcript("boom", "boom", "boom"))
        self.assertIn("systemMessage", out.stdout)
        self.assertEqual(list(self.counts().values()), [3])

    def test_success_rows_and_broken_lines_are_ignored(self):
        """성공을 실패로 읽으면 매 턴이 루프로 신고된다. 찢어진 줄은 나머지 관측을 안 끊는다."""
        self.open_quest()
        path = self.transcript("boom", ok=5)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("{not json\n[1,2]\n42\n")
        self.assertEqual(self.stop(path).stdout.strip(), "")
        self.assertEqual(list(self.counts().values()), [1], "성공·깨진 줄이 카운트에 섞였다")

    def test_one_sweep_writes_one_fail_event(self):
        """배선을 처음 깐 턴은 지나간 실패까지 소급해 센다 — 그때마다 적으면 로그가 fail 로 덮인다."""
        self.open_quest()
        path = self.transcript(*(["boom"] * 4 + ["thud"] * 3))
        self.stop(path)
        fails = self.fail_events()
        self.assertEqual(len(fails), 1, "한 훑기가 fail 이벤트를 여럿 적었다")
        self.assertEqual(fails[0]["failure_count"], 4, "제일 심한 것이 아니라 다른 것이 적혔다")
        self.assertEqual(sorted(self.counts().values()), [3, 4], "덜 적는 것과 덜 세는 것은 다르다")

    def test_the_seen_ledger_is_not_caught_by_the_counts_glob(self):
        """장부가 `failures-*.json` 에 걸리면 카운트를 긁는 손이 id 목록을 카운트로 읽는다."""
        self.open_quest()
        self.stop(self.transcript("boom"))
        state = os.path.join(self.root, ".asgard")
        globbed = sorted(os.path.basename(p) for p in glob.glob(os.path.join(state, "failures-*.json")))
        self.assertEqual(globbed, ["failures-s1.json"])

    def test_a_blocked_call_is_not_a_tool_failure(self):
        """가드가 막은 호출은 실행된 적이 없다 — 세면 없는 루프를 신고한다.

        turn 7 의 실물 재현이다: 16분에 걸쳐 서로 다른 명령 셋이 막혔고 매번 접근을 바꿨는데,
        거절문 앞 80자가 같은 상용구라 sig() 가 한 키로 뭉쳐 THINKER_REPLAN 이 걸렸다.
        본문은 이 저장소가 실제로 내는 거절문에서 가져왔다 (호스트 머리말 · 가드 자기소개)."""
        self.open_quest()
        denials = [
            'PreToolUse:Bash hook error: [uv run --no-project python "$CLAUDE_PROJECT_DIR/.claude/hooks/'
            'readonly-guard.py"]: Asgard control-surface policy blocked Bash: git check-ignore -v .claude/settings.json',
            "<tool_use_error>Asgard workspace policy blocked Bash on a path outside every work root: /private/tmp/x",
            "Asgard read-only role policy blocked mutating operation",
            "This command requires approval",
            "This Bash command contains multiple operations. The following part requires approval",
            "The user doesn't want to proceed with this tool use",
            "<tool_use_error>Blocked: sleep 60 followed by: echo waited. To wait for a condition, use Monitor",
            "Permission to use Bash with command rm -rf /tmp/x has been denied.",
        ]
        self.assertEqual(self.stop(self.transcript(*denials)).stdout.strip(), "")
        self.assertEqual(self.fail_events(), [], "실행된 적 없는 호출로 fail 이벤트가 적혔다")
        self.assertFalse(
            os.path.exists(os.path.join(self.root, ".asgard", "failures-s1.json")),
            "거절만 있는 턴이 카운터 파일을 만들었다",
        )

    def test_the_workspace_guard_opens_with_the_marker_the_filter_matches(self):
        """readonly-guard 의 뿌리 밖 거절 하나를 실물로 받아 가드와 필터를 맞물려 확인한다.

        이것이 잡는 것은 여섯 가드 중 하나다 — 나머지 다섯이 여는 말을 바꿔도 여기는 통과한다.
        `never_ran` 도스트링이 그 한계를 적는다. turn 11 을 낸 가드가 이쪽이라 여기를 잡는다."""
        from asgard.hooks.failure_tracker import GUARD_OPENER, never_ran
        from asgard.hooks.readonly_guard import _escape_refusal

        denial = _escape_refusal("Bash", "/outside/x", "/outside/x", (self.root,), "claude", True)
        self.assertTrue(denial.startswith(GUARD_OPENER), f"가드 거절문이 {GUARD_OPENER!r} 로 안 연다: {denial[:80]}")
        self.assertTrue(never_ran(denial), "필터가 실물 가드 거절을 못 알아본다")

    def test_a_real_tool_error_is_still_counted(self):
        """거절을 빼는 것과 실패를 놓치는 것은 다르다 — 실행되고 깨진 것은 그대로 센다."""
        self.open_quest()
        ran_and_failed = [
            "Exit code 1\nTraceback (most recent call last):",
            "<tool_use_error>String to replace not found in file.",
            "File does not exist. Note: your current working directory is /repo",
        ]
        self.stop(self.transcript(*ran_and_failed))
        self.assertEqual(sorted(self.counts().values()), [1, 1, 1], "실행된 실패가 거절로 오인돼 빠졌다")

    def test_a_missing_transcript_is_a_no_op(self):
        """기록을 못 읽는 것은 흔하다(다른 호스트·경로 없음). 훅이 죽으면 턴이 멈춘다."""
        self.open_quest()
        self.assertEqual(self.stop(os.path.join(self.root, "nope.jsonl")).returncode, 0)
        self.assertEqual(self.stop("").stdout.strip(), "")

    def test_the_stop_hook_is_wired_for_claude(self):
        """관측원을 심어도 배선이 없으면 한 번도 안 불린다 — 이 레인이 죽어 있던 방식 그대로."""
        from asgard.templates.claude import cc_settings

        stop = json.loads(cc_settings())["hooks"]["Stop"][0]["hooks"]
        self.assertTrue(
            any("failure-tracker.py" in h["command"] for h in stop),
            "Stop 에 failure-tracker 배선이 없다 — 기록을 읽는 손이 안 선다",
        )


class TestFailureEscalation(TrinityBase):
    def test_a_top_level_error_mark_with_a_string_body_is_recognised(self):
        """표식이 어디 있든 실패로 읽고 성공은 안 건드린다. 종전 판정기는 dict 응답만 봤다.

        Claude Code 에서 이 레인이 죽어 있던 원인은 이 판정기가 아니다 — 그 호스트는 도구
        호출이 실패하면 PostToolUse 훅을 아예 안 부른다 (계수기 실측은 `failure_tracker` 머리말
        에 있다). 이 시험이 고정하는 것은 실패에도 훅을 부르는 호스트의 계약이고, 그 호스트의
        몫은 아래 TestTranscriptSweep 이 진다."""
        self.open_quest()
        errored = {
            "tool_name": "Bash",
            "session_id": "s1",
            "cwd": self.root,
            "is_error": True,
            "tool_response": "Exit code 1\nboom: something specific broke",
        }
        outs = [run(TRACKER, stdin=json.dumps(errored), cwd=self.root) for _ in range(3)]
        self.assertEqual([o.stdout.strip() != "" for o in outs], [False, False, True])
        ok = {"tool_name": "Bash", "session_id": "s2", "cwd": self.root, "tool_response": "all good"}
        self.assertEqual(run(TRACKER, stdin=json.dumps(ok), cwd=self.root).stdout.strip(), "")

    def test_three_failures_inject_replan_and_log_fail_event(self):
        self.open_quest()
        payload = {
            "tool_name": "Bash",
            "session_id": "s1",
            "cwd": self.root,
            "tool_response": {"is_error": True, "error": "command not found: foo"},
        }
        outs = [run(TRACKER, stdin=json.dumps(payload), cwd=self.root) for _ in range(3)]
        self.assertEqual([o.stdout.strip() != "" for o in outs], [False, False, True])
        warn = json.loads(outs[2].stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("THINKER_REPLAN", warn)
        events = [json.loads(ln) for ln in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        fails = [e for e in events if e["event"] == "fail"]
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0]["failure_count"], 3)
        # 로그의 fail 이벤트가 전이 함수를 재계획으로 이끈다 (실패 추적 배선의 종점)
        out = jout(self.qlog("next"))
        self.assertEqual(out["next_role"], "THINKER_REPLAN")

    def test_tracker_logs_from_the_deployed_hook_layout(self):
        """배포 디렉터리에서도 기장이 적혀야 한다 — 같은 파일이 두 이름으로 산다.

        패키지는 `quest_log.py`(임포트되는 모듈), 배포본은 `quest-log.py`(훅 파일 규약)다.
        기존 시험은 패키지 배치에서만 돌아 배포 배치의 빗나감을 못 봤고, 호출이
        `check=False` + 바깥 `except` 라 Canon 9 의 3연속 실패가 호스트 3모드에서 한 번도
        안 적혔다 (26-08-05 감사)."""
        import shutil

        self.open_quest()
        hooks = os.path.join(self.root, ".claude", "hooks")
        os.makedirs(hooks, exist_ok=True)
        shutil.copy2(TRACKER, os.path.join(hooks, "failure-tracker.py"))
        shutil.copy2(os.path.join(SRC, "quest_log.py"), os.path.join(hooks, "quest-log.py"))
        deploy_library(hooks)  # 배포본 배치 — 훅 옆에 공용 라이브러리가 함께 선다
        payload = {
            "tool_name": "Bash",
            "session_id": "s1",
            "cwd": self.root,
            "tool_response": {"is_error": True, "error": "command not found: foo"},
        }
        deployed = os.path.join(hooks, "failure-tracker.py")
        for _ in range(3):
            run(deployed, stdin=json.dumps(payload), cwd=self.root)
        events = [json.loads(ln) for ln in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        fails = [e for e in events if e["event"] == "fail"]
        self.assertEqual(len(fails), 1, "배포 배치에서 fail 이벤트가 안 적혔다")
        self.assertEqual(fails[0]["failure_count"], 3)

    def test_tracker_without_quest_still_warns(self):
        payload = {
            "tool_name": "Bash",
            "session_id": "s2",
            "cwd": self.root,
            "tool_response": {"is_error": True, "error": "boom"},
        }
        for _ in range(2):
            run(TRACKER, stdin=json.dumps(payload), cwd=self.root)
        p = run(TRACKER, stdin=json.dumps(payload), cwd=self.root)
        self.assertIn("additionalContext", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
