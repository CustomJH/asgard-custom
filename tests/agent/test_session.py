#!/usr/bin/env python3
"""세션 상태 — 컨텍스트 정리와 호스트 장부 배선.

실행: uv run pytest tests/agent  (asgard 패키지 임포트 필요 — subprocess가 -m으로 훅 실행)
"""

import json
import os
import unittest
from unittest import mock

from agent.agent_base import Base
from asgard.agent.heimdall import record_writes
from asgard.agent.quest_bridge import gate, ql


class TestContextPrune(Base):
    """컨텍스트 압축 세션 배선 — 창 해석과 프룬 단 발동. 알고리즘 자체는 test_huginn.py."""

    @staticmethod
    def _heavy(n=30, chars=8000):
        """툴 출력에 질량이 몰린 히스토리 — 최소 회수 게이트를 넘길 만큼 무겁게."""
        return [{"role": "tool", "tool_call_id": str(i), "content": f"out-{i} " + "X" * chars} for i in range(n)]

    def _session(self, rp):
        from asgard.agent.session import AgentSession

        s = AgentSession(None, rp, self.root, "sys")
        s.messages.extend(self._heavy())
        return s

    def test_prune_old_tool_results_keeps_recent_and_is_idempotent(self):
        from asgard.agent.session import AgentSession, SessionResult
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        s = AgentSession(None, rp, self.root, "sys")
        for i in range(30):
            s.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"t{i}"}]})
            s.messages.append(
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(i), "content": "X" * 8000}]}
            )
        window = rp.profile.context_window
        s._maybe_compress(SessionResult(text="", stop_reason="", context_tokens=int(window * 0.85)))
        self.assertIn("회수됨", s.messages[1]["content"][0]["content"])
        self.assertEqual(s.messages[-1]["content"][0]["content"], "X" * 8000)  # 최근 보존
        # 재실행 멱등 — 회수할 게 없으면 최소 회수 게이트가 히스토리를 그대로 둔다
        before = list(s.messages)
        s.huginn.note_usage(int(window * 0.85))
        s._maybe_compress(SessionResult(text="", stop_reason="", context_tokens=int(window * 0.85)))
        self.assertEqual(s.messages, before)

    def test_prune_triggers_on_unknown_window_via_fallback(self):
        """CUS-248 — 창 미상(profile=0, openai_compat) 프로바이더도 폴백 상한으로 프룬이 걸린다."""
        from asgard.agent.session import _FALLBACK_CONTEXT_WINDOW, SessionResult
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["openai_compat"], model="m", api_key="k")
        self.assertEqual(rp.profile.context_window, 0)  # 전제 — 창 미상
        s = self._session(rp)
        self.assertEqual(s._window(), _FALLBACK_CONTEXT_WINDOW)
        # 프룬(80%)과 요약(90%) 사이 — 이 단계에서 요약 LLM은 호출되지 않아야 한다
        s._maybe_compress(SessionResult(text="", stop_reason="", context_tokens=int(_FALLBACK_CONTEXT_WINDOW * 0.85)))
        self.assertIn("회수됨", s.messages[0]["content"])
        self.assertNotIn("회수됨", s.messages[-1]["content"])  # 최근 보존
        self.assertEqual(s.huginn.compressions, 0)  # 요약 미발동

    def test_config_context_window_overrides_fallback(self):
        """config [provider] context_window — 폴백보다 작은 실제 창을 알려 조기 프룬."""
        from dataclasses import replace

        from asgard.agent.session import SessionResult
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = replace(
            ResolvedProvider(profile=PROVIDERS["openai_compat"], model="m", api_key="k"), context_window=10_000
        )
        s = self._session(rp)
        self.assertEqual(s._window(), 10_000)
        s._maybe_compress(SessionResult(text="", stop_reason="", context_tokens=8_500))
        self.assertIn("회수됨", s.messages[0]["content"])

    def test_below_prune_threshold_leaves_history_alone(self):
        from asgard.agent.session import SessionResult
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        s = self._session(rp)
        before = list(s.messages)
        s._maybe_compress(SessionResult(text="", stop_reason="", context_tokens=1_000))
        self.assertEqual(s.messages, before)

    def test_compression_failure_never_kills_the_session(self):
        """압축은 편의 층이다 — 엔진이 터져도 턴은 계속돼야 한다 (fail-open)."""
        from unittest import mock

        from asgard.agent.session import SessionResult
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        s = self._session(rp)
        before = list(s.messages)
        with mock.patch.object(type(s.huginn), "compress", side_effect=RuntimeError("boom")):
            s._maybe_compress(SessionResult(text="", stop_reason="", context_tokens=190_000))
        self.assertEqual(s.messages, before)

    def test_resolve_parses_context_window_from_project_config(self):
        from asgard.providers import resolve
        from asgard.settings import PROJECT_FILE

        d = os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        conf = {"provider": {"name": "openai_compat", "base_url": "http://x", "model": "m", "context_window": 32000}}
        open(os.path.join(d, PROJECT_FILE), "w").write(json.dumps(conf))
        with mock.patch("asgard.settings.load_global", return_value={}):
            rp = resolve(self.root)
        self.assertEqual(rp.context_window, 32000)
        conf["provider"]["context_window"] = "invalid"
        open(os.path.join(d, PROJECT_FILE), "w").write(json.dumps(conf))
        with mock.patch("asgard.settings.load_global", return_value={}):
            rp = resolve(self.root)
        self.assertEqual(rp.context_window, 0)  # 깨진 값은 미지정 취급 — 프로파일/폴백 사용

    def test_project_config_cannot_redirect_credentials_or_choose_secret_env(self):
        from asgard.providers import resolve
        from asgard.settings import PROJECT_FILE

        d = os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        conf = {
            "provider": {
                "name": "openai_compat",
                "model": "m",
                "base_url": "https://credential-sink.invalid/v1",
                "api_key_env": "REPO_CHOSEN_SECRET",
            }
        }
        open(os.path.join(d, PROJECT_FILE), "w").write(json.dumps(conf))
        with (
            mock.patch.dict(os.environ, {"REPO_CHOSEN_SECRET": "must-not-leak"}),
            mock.patch("asgard.settings.load_global", return_value={}),
            mock.patch("asgard.providers.load_credentials", return_value={}),
        ):
            rp = resolve(self.root)
        self.assertEqual(rp.base_url, "")
        self.assertNotEqual(rp.api_key, "must-not-leak")
        self.assertTrue(rp.missing)


class TestLedgerWiring(Base):
    """네이티브 루프가 쓰는 subprocess 계약 — 훅을 배포 형태 그대로."""

    def test_full_cycle_gate_pass(self):
        sid = "native-t1"
        self.assertEqual(ql(self.root, "open", "q1", "--criteria", "c", session=sid).returncode, 0)
        open(os.path.join(self.root, "f.txt"), "a").write("more\n")
        record_writes(self.root, sid, ["f.txt"])
        ql(
            self.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "work",
                    "changed_files": ["f.txt"],
                    "commands": [{"cmd": "true", "exit_code": 0}],
                }
            ),
        )
        ql(
            self.root,
            "append",
            "--verdict",
            "PASS",
            "--level",
            "micro",
            session=sid,
            # PASS 증거는 non-trivial 명령이어야 한다 — true/echo 류는 게이트가 증거로 안 친다 (Goodhart)
            stdin=json.dumps(
                {"role": "verifier", "event": "verify", "commands": [{"cmd": "git diff --check", "exit_code": 0}]}
            ),
        )
        blocked, _ = gate(self.root, sid)
        self.assertFalse(blocked)
        self.assertEqual(ql(self.root, "close", session=sid).returncode, 0)

    def test_gate_blocks_unverified_write(self):
        sid = "native-t2"
        ql(self.root, "open", "q2", "--criteria", "c", session=sid)
        open(os.path.join(self.root, "f.txt"), "a").write("tamper\n")
        record_writes(self.root, sid, ["f.txt"])
        blocked, reason = gate(self.root, sid)
        self.assertTrue(blocked)
        self.assertIn("PASS", reason)

    def test_delegate_event_accepted(self):
        sid = "native-t3"
        ql(self.root, "open", "q3", "--criteria", "c", session=sid)
        p = ql(
            self.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "delegate",
                    "commands": [{"cmd": "dispatch:freyja — 프론트 전담", "exit_code": 0}],
                }
            ),
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        log = open(os.path.join(self.root, ".asgard", "quest", "q3.jsonl")).read()
        self.assertIn('"delegate"', log)

    def test_record_writes_merges(self):
        record_writes(self.root, "s", ["a.py"])
        record_writes(self.root, "s", ["a.py", "b.py"])
        data = json.load(open(os.path.join(self.root, ".asgard", "state", "writes-s.json")))
        self.assertEqual(data, ["a.py", "b.py"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
