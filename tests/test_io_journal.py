"""로컬 I/O 저널 — provider 호출 메타데이터 append-only 기록 (계측 ≠ 기억, fail-open)."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from asgard import io_journal
from asgard.io_journal import call_returned, call_started, journal_path


class JournalBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-io-journal-")
        self.root = os.path.join(self.tmp, "proj")
        os.makedirs(self.root)
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp
        os.environ.pop("ASGARD_IO_JOURNAL", None)

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        os.environ.pop("ASGARD_IO_JOURNAL", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def entries(self):
        with open(journal_path(self.root), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


class TestJournalModule(JournalBase):
    def test_started_returned_pair_shares_call_id(self):
        cid = call_started(self.root, provider="anthropic", model="m1", transport="anthropic", role="worker")
        self.assertTrue(cid)
        call_returned(self.root, cid, duration_ms=123.9, input_tokens=10, output_tokens=5, cache_read_tokens=0)
        started, returned = self.entries()
        self.assertEqual(started["event"], "started")
        self.assertEqual(started["provider"], "anthropic")
        self.assertEqual(started["role"], "worker")
        self.assertEqual(returned["event"], "returned")
        self.assertEqual(returned["call_id"], started["call_id"])
        self.assertEqual(returned["duration_ms"], 123)
        self.assertEqual(returned["input_tokens"], 10)
        self.assertNotIn("cache_read_tokens", returned)  # 0 카운트는 생략 — 원문/노이즈 미기록

    def test_error_is_truncated_and_recorded(self):
        cid = call_started(self.root, provider="p", model="m", transport="openai_compat")
        call_returned(self.root, cid, duration_ms=5, error="RuntimeError: " + "x" * 500)
        self.assertLessEqual(len(self.entries()[-1]["error"]), 200)

    def test_env_kill_switch_suppresses_both(self):
        os.environ["ASGARD_IO_JOURNAL"] = "off"
        cid = call_started(self.root, provider="p", model="m", transport="anthropic")
        self.assertIsNone(cid)
        call_returned(self.root, cid, duration_ms=1)  # call_id None → returned 억제
        self.assertFalse(os.path.exists(journal_path(self.root)))

    def test_fail_open_on_unwritable_root(self):
        blocked = os.path.join(self.tmp, "not-a-dir")
        open(blocked, "w").write("file")  # .asgard 생성이 불가능한 root
        cid = call_started(blocked, provider="p", model="m", transport="anthropic")
        self.assertIsNone(cid)  # started 실패 → returned 억제 (반쪽 레코드 방지)
        call_returned(blocked, cid, duration_ms=1)

    def test_rotation_keeps_one_generation(self):
        with mock.patch.object(io_journal, "MAX_BYTES", 64):
            for _ in range(4):
                cid = call_started(self.root, provider="p", model="m", transport="anthropic")
                call_returned(self.root, cid, duration_ms=1)
        self.assertTrue(os.path.exists(journal_path(self.root) + ".1"))

    def test_gitignore_self_installed(self):
        call_started(self.root, provider="p", model="m", transport="anthropic")
        gi = os.path.join(self.root, ".asgard", ".gitignore")
        self.assertEqual(open(gi).read().strip(), "*")


class _FakeUsage:
    input_tokens = 10
    cache_read_input_tokens = 2
    cache_creation_input_tokens = 3
    output_tokens = 5


class _FakeBlock:
    type = "text"
    text = "ok"


class _FakeResp:
    content = (_FakeBlock(),)
    stop_reason = "end_turn"
    usage = _FakeUsage()


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        return iter(["ok"])

    def get_final_message(self):
        return _FakeResp()


class _FakeMessages:
    def stream(self, **kwargs):
        return _FakeStream()


class _FakeClient:
    messages = _FakeMessages()


class _BoomMessages:
    def stream(self, **kwargs):
        raise RuntimeError("api down")


class _BoomClient:
    messages = _BoomMessages()


class TestSessionWiring(JournalBase):
    def session(self, client):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m1", api_key="k")
        return AgentSession(client, rp, self.root, "sys", role="worker")

    def test_anthropic_call_journals_tokens(self):
        r = self.session(_FakeClient()).run("hi")
        self.assertEqual(r.stop_reason, "end_turn")
        started, returned = self.entries()
        self.assertEqual(started["transport"], "anthropic")
        self.assertEqual(started["model"], "m1")
        self.assertEqual(returned["call_id"], started["call_id"])
        self.assertEqual(returned["input_tokens"], 10)
        self.assertEqual(returned["output_tokens"], 5)
        self.assertEqual(returned["cache_read_tokens"], 2)
        # 원문(프롬프트/응답)은 어떤 필드에도 실리지 않는다 — 계측 ≠ 기억
        self.assertNotIn("hi", json.dumps(self.entries(), ensure_ascii=False))
        self.assertNotIn("ok", "".join(str(v) for e in self.entries() for v in e.values()))

    def test_api_error_journals_error_and_propagates(self):
        with self.assertRaises(RuntimeError):
            self.session(_BoomClient()).run("hi")
        started, returned = self.entries()
        self.assertEqual(returned["call_id"], started["call_id"])
        self.assertIn("RuntimeError", returned["error"])


if __name__ == "__main__":
    unittest.main()
