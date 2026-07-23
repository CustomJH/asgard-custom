#!/usr/bin/env python3
"""Charter 모드 B 훅 (charter-activate) — standalone subprocess 검증 (배포 형태 그대로).

네이티브 Heimdall 은 charter.py note() 를 직접 주입하지만, 모드 B(Claude Code/Codex/Cursor)는
서브에이전트가 AGENTS.md 를 읽는 구조라 훅으로 보상한다. 이 스위트는 훅을 진짜 subprocess 로
JSON stdin 을 물려 돌리고(모드 B 가 호출하는 형태 그대로) 다음을 검증한다:

  · SessionStart(agent_type 없음) → through_line 만 (설계①)
  · SubagentStart asgard-thinker → coherence + criteria 환원 (협업②)
  · SubagentStart asgard-verifier → 반례 렌즈 + "criteria 대체 아님" (판단③, evidence-first 보존)
  · SubagentStart asgard-worker → through_line 만, coherence 미주입 (게이트 무결성)
  · charter 부재/파손 → 무출력 (fail-open, 토큰 회귀 없음)
  · **단일 출처 정합성**: 훅 render() 본문 == 네이티브 charter.note() 본문 (재구현 동기화 보증)

실행: uv run pytest tests/test_charter_hook.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from asgard.charter import note

HOOK_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "asgard",
    "hooks",
    "charter_activate.py",
)


class CharterHookBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.hooks = os.path.join(self.root, ".claude", "hooks")
        os.makedirs(self.hooks)
        shutil.copy(HOOK_SRC, os.path.join(self.hooks, "charter-activate.py"))

    def tearDown(self):
        self.tmp.cleanup()

    def set_charter(self, charter):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as f:
            json.dump({"charter": charter}, f)

    def hook(self, payload):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run(
            [sys.executable, os.path.join(self.hooks, "charter-activate.py")],
            input=json.dumps({"cwd": self.root, **payload}),
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
            timeout=30,
        )

    def body(self, out):
        """[charter]\\n\\n prefix (또는 SubagentStart JSON additionalContext) 를 벗겨 본문만."""
        out = out.strip()
        if not out:
            return ""
        if out.startswith("{"):
            out = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert out.startswith("[charter]"), out
        return out[len("[charter]") :].strip()


class TestCharterHook(CharterHookBase):
    def test_session_start_through_line_only(self):
        self.set_charter({"through_line": "TL관통원칙", "coherence": ["C1일관성"]})
        out = self.hook({"source": "startup"}).stdout
        self.assertIn("TL관통원칙", out)
        self.assertNotIn("C1일관성", out)  # 메인 스레드엔 coherence 미주입

    def test_thinker_folds_coherence(self):
        self.set_charter({"through_line": "TL", "coherence": ["C1일관성"]})
        p = self.hook({"agent_type": "asgard-thinker"})
        ctx = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "SubagentStart")
        self.assertIn("C1일관성", ctx["additionalContext"])
        self.assertIn("assigned-unit criteria", ctx["additionalContext"])

    def test_verifier_is_lens_not_gate(self):
        self.set_charter({"through_line": "TL", "coherence": ["C1일관성"]})
        ctx = json.loads(self.hook({"agent_type": "asgard-verifier"}).stdout)["hookSpecificOutput"]
        self.assertIn("C1일관성", ctx["additionalContext"])
        self.assertIn("does not replace criteria", ctx["additionalContext"])  # evidence-first 보존

    def test_worker_gets_no_charter(self):
        # 네이티브 패리티 — Worker 세션은 worker.md+lagom 만, charter 무주입 (Fugu 격리)
        self.set_charter({"through_line": "TL관통", "coherence": ["C1일관성"]})
        self.assertEqual(self.hook({"agent_type": "asgard-worker"}).stdout.strip(), "")

    def test_delivery_gets_through_line_only(self):
        # 딜리버리(freyja/thor/loki) — 네이티브 delivery_identity 대응: through_line 만
        self.set_charter({"through_line": "TL딜리버리", "coherence": ["C1일관성"]})
        for agent in ("asgard-freyja", "asgard-thor", "asgard-loki"):
            ctx = json.loads(self.hook({"agent_type": agent}).stdout)["hookSpecificOutput"]
            self.assertIn("TL딜리버리", ctx["additionalContext"])
            self.assertNotIn("C1일관성", ctx["additionalContext"])

    def test_no_charter_is_silent(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)  # charter 키 자체 부재
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), "w") as f:
            f.write("{}")
        self.assertEqual(self.hook({"agent_type": "asgard-thinker"}).stdout.strip(), "")
        self.assertEqual(self.hook({"source": "startup"}).stdout.strip(), "")

    def test_broken_charter_is_silent(self):
        self.set_charter(42)
        self.assertEqual(self.hook({"source": "startup"}).stdout.strip(), "")

    def test_string_shorthand(self):
        self.set_charter("속도보다 정합성")
        out = self.hook({"source": "startup"}).stdout
        self.assertIn("속도보다 정합성", out)

    def test_parity_with_native_note(self):
        # 단일 출처 원칙 — 훅 render() 본문이 네이티브 charter.note() 본문과 정확히 일치해야
        self.set_charter({"through_line": "관통TL", "coherence": ["일관성C1", "일관성C2"]})
        cases = [
            ({"source": "startup"}, "identity"),
            ({"agent_type": "asgard-thinker"}, "thinker"),
            ({"agent_type": "asgard-verifier"}, "verifier"),
            ({"agent_type": "asgard-freyja"}, "identity"),  # 딜리버리 = through_line
        ]
        for payload, section in cases:
            with self.subTest(section=section):
                hook_body = self.body(self.hook(payload).stdout)
                native_body = note(self.root, section).strip()
                self.assertEqual(hook_body, native_body)


if __name__ == "__main__":
    unittest.main()
