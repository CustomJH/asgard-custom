#!/usr/bin/env python3
"""siege-inbox 훅 — 호스트 세션이 자기 앞으로 온 메일을 턴 머리에서 읽는가.

호스트 세 모드에는 우편함을 훑는 자리가 없었다. 네이티브 루프는 코디네이터 데몬 스레드가
훑지만, Claude Code·Cursor·Codex 는 에이전트가 제 손으로 `siege check` 를 칠 때만 메일을
읽는다 — 아무도 안 치면 답장이 우편함에 그대로 남는다.

여기서 지키는 계약 넷:
  · 이 세션 이름(`heimdall`) 앞으로 온 메일만 주입한다.
  · 주입한 메일은 확인 처리한다 — 다음 턴에 같은 메일이 또 오면 컨텍스트만 먹는다.
  · 주인 없는 메일은 안 건드린다 — 그 수신자는 나중에 `siege check` 를 부를 코디네이터다.
  · 우편함이 비었으면 아무것도 안 낸다. 그 경로에서는 CLI 도 안 띄운다 (훅 값은 프로세스다).

훅을 배포본 배치로 돌린다 — 파일 하나만 두면 그 배치는 실사가 아니다 (hookscaffold).

실행: uv run pytest tests/test_siege_inbox_hook.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hookscaffold import deploy_cli, deploy_library, isolated_home_env  # noqa: E402

from asgard import orchestration as orc  # noqa: E402

HOOK_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "hooks", "siege_inbox.py"))
INBOX = "heimdall"


class InboxBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        subprocess.run(["git", "init", "-q", self.root], check=True, capture_output=True)
        self.hooks = os.path.join(self.root, "hooks")
        os.makedirs(self.hooks, exist_ok=True)
        deploy_library(self.hooks)
        shutil.copyfile(HOOK_SRC, os.path.join(self.hooks, "siege-inbox.py"))
        self.bin = os.path.join(self.root, "bin")
        deploy_cli(self.bin)
        self.run_id = orc.run_create(self.root, "bridge run", quest_id="q-inbox")["id"]

    def fire(self, client="claude-code", event="UserPromptSubmit", with_cli=True) -> subprocess.CompletedProcess:
        env = isolated_home_env(self.root, PATH=(self.bin + os.pathsep if with_cli else "") + os.environ["PATH"])
        return subprocess.run(
            [sys.executable, os.path.join(self.hooks, "siege-inbox.py"), client],
            input=json.dumps({"cwd": self.root, "session_id": "s1", "hook_event_name": event}),
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
            timeout=120,
        )

    def injected(self, proc: subprocess.CompletedProcess) -> str:
        """호스트가 실제로 읽는 칸에서 꺼낸다 — 스키마가 틀리면 주입은 없던 일이 된다."""
        if not proc.stdout.strip():
            return ""
        payload = json.loads(proc.stdout)
        if "additional_context" in payload:  # Cursor
            return str(payload["additional_context"])
        return str(payload["hookSpecificOutput"]["additionalContext"])

    def mail(self, subject="답이다", body="모델이 답한 내용", sender="codex-1", recipient=INBOX) -> dict:
        return orc.send(
            self.root, self.run_id, "status", subject=subject, body=body, sender=sender, recipient=recipient
        )


class TestDelivery(InboxBase):
    def test_mail_for_this_session_reaches_the_turn(self):
        self.mail()
        body = self.injected(self.fire())
        self.assertIn("<asgard-inbox", body)
        self.assertIn("from codex-1", body)
        self.assertIn("모델이 답한 내용", body)

    def test_it_is_shown_once(self):
        """확인 처리를 안 하면 같은 메일이 매 턴 컨텍스트를 먹는다."""
        self.mail()
        self.assertIn("<asgard-inbox", self.injected(self.fire()))
        self.assertEqual(self.injected(self.fire()), "")

    def test_cursor_gets_its_own_schema(self):
        self.mail()
        payload = json.loads(self.fire(client="cursor", event="sessionStart").stdout)
        self.assertIn("<asgard-inbox", payload["additional_context"])

    def test_more_mail_than_fits_says_where_the_rest_is(self):
        for i in range(7):
            self.mail(subject="답 %d" % i)
        body = self.injected(self.fire())
        self.assertIn("2건이 더 있다", body)
        self.assertIn("--as %s" % INBOX, body)


class TestWhatItLeavesAlone(InboxBase):
    def test_unaddressed_mail_is_not_taken(self):
        orc.send(self.root, self.run_id, "status", subject="주인 없음", sender="w1")
        self.assertEqual(self.injected(self.fire()), "")
        self.assertEqual(orc.check(self.root, self.run_id)["count"], 1)

    def test_mail_for_someone_else_is_not_taken(self):
        self.mail(recipient="codex-1")
        self.assertEqual(self.injected(self.fire()), "")

    def test_a_closed_run_is_not_read(self):
        self.mail()
        orc.run_close(self.root, self.run_id)
        self.assertEqual(self.injected(self.fire()), "")

    def test_an_empty_mailbox_never_spawns_the_cli(self):
        """빈 우편함이 보통이다. 그 경로에서 CLI 를 띄우면 매 프롬프트가 그만큼 늦어진다."""
        proc = self.fire(with_cli=False)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertEqual(proc.returncode, 0)

    def test_no_ledger_at_all_is_silent(self):
        os.remove(os.path.join(self.root, ".asgard", "orchestration.db"))
        self.assertEqual(self.fire().stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
