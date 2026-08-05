"""명시 승인형 ``asgard review`` 에이전트와 Studio용 제안 기록."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli_boundary import run_cli

from asgard import errors, review_agent


class ReviewRepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="asgard-review-")
        self.root = self.tmp.name
        self._git("init", "-q")
        self._git("config", "user.email", "review@example.com")
        self._git("config", "user.name", "Review Test")
        self.write("app.py", "def add(left, right):\n    return left + right\n")
        self._git("add", "app.py")
        self._git("commit", "-qm", "base")
        self.write(
            "app.py",
            "def add(left, right):\n    if right is None:\n        return 0\n    return left + right\n",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, rel: str, text: str) -> None:
        path = Path(self.root, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def result(path: str = "app.py", line: int = 2) -> dict:
        return {
            "summary": "None 입력에서 기존 덧셈 계약이 달라지는 제안 한 건이 있어요",
            "findings": [
                {
                    "type": "issue",
                    "severity": "major",
                    "category": "correctness",
                    "path": path,
                    "line": line,
                    "title": "None 입력이 0으로 바뀌어요",
                    "body": "기존에는 TypeError가 나던 입력이 성공으로 바뀌어 호출자의 오류 처리가 건너뛰어져요.",
                    "evidence": "app.py의 새 분기가 right is None일 때 덧셈 전에 0을 반환해요.",
                    "suggestion": "None을 허용하는 계약인지 먼저 정하고, 허용한다면 호출부와 테스트에 명시해요.",
                    "confidence": "high",
                }
            ],
            "gaps": [],
            "_meta": {"provider": "fake", "model": "review-test", "tokens": 12, "stop_reason": "tool_use"},
        }


class TestReviewScopeAndApproval(ReviewRepoCase):
    def test_scope_reuses_tutor_inventory_and_fixes_the_snapshot(self) -> None:
        scope = review_agent.inspect_scope(self.root)

        self.assertEqual(scope.paths, ("app.py",))
        self.assertEqual(scope.inventory[0]["path"], "app.py")
        self.assertGreater(scope.added, 0)
        self.assertEqual(len(scope.fingerprint), 64)
        self.assertTrue(scope.base_commit)

    def test_staging_does_not_run_a_model_and_deduplicates_a_waiting_request(self) -> None:
        scope = review_agent.inspect_scope(self.root)

        first = review_agent.stage(self.root, scope, "None 계약", now=1_000)
        second = review_agent.stage(self.root, scope, "None 계약", now=1_001)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "awaiting_confirmation")
        self.assertEqual(review_agent.panel_state(self.root)["counts"]["waiting"], 1)

    def test_only_an_approved_request_runs_and_persists_structured_suggestions(self) -> None:
        scope = review_agent.inspect_scope(self.root)
        request = review_agent.stage(self.root, scope, now=1_000)
        runner = mock.Mock(return_value=self.result())

        row = review_agent.execute(self.root, request["id"], runner=runner, now=1_001)

        runner.assert_called_once()
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["reviewer"], "asgard-review")
        self.assertEqual(row["findings"][0]["id"], "f1")
        self.assertEqual(row["findings"][0]["path"], "app.py")
        self.assertEqual(row["model"]["model"], "review-test")
        self.assertEqual(review_agent.get(self.root, row["id"])["summary"], row["summary"])

    def test_changed_scope_invalidates_the_approval_before_model_cost(self) -> None:
        scope = review_agent.inspect_scope(self.root)
        request = review_agent.stage(self.root, scope, now=1_000)
        self.write("app.py", Path(self.root, "app.py").read_text(encoding="utf-8") + "\nVALUE = 1\n")
        runner = mock.Mock(return_value=self.result())

        with self.assertRaises(errors.Conflict):
            review_agent.execute(self.root, request["id"], runner=runner, now=1_001)

        runner.assert_not_called()
        self.assertEqual(review_agent.get(self.root, request["id"])["status"], "stale")

    def test_a_change_during_review_keeps_the_result_but_marks_it_stale(self) -> None:
        scope = review_agent.inspect_scope(self.root)
        request = review_agent.stage(self.root, scope, now=1_000)

        def runner(_root, _scope, _focus):
            self.write("app.py", Path(self.root, "app.py").read_text(encoding="utf-8") + "\nVALUE = 2\n")
            return self.result()

        row = review_agent.execute(self.root, request["id"], runner=runner, now=1_001)

        self.assertEqual(row["status"], "stale")
        self.assertEqual(len(row["findings"]), 1)
        self.assertIn("도는 동안", row["stale_reason"])

    def test_out_of_scope_or_impossible_anchors_are_not_saved_as_findings(self) -> None:
        scope = review_agent.inspect_scope(self.root)
        request = review_agent.stage(self.root, scope, now=1_000)

        row = review_agent.execute(
            self.root,
            request["id"],
            runner=lambda *_: self.result("other.py", 999),
            now=1_001,
        )

        self.assertEqual(row["status"], "no_findings")
        self.assertEqual(row["findings"], [])
        self.assertTrue(any("제외했어요" in str(gap) for gap in row["gaps"]))

    def test_a_mode_change_also_invalidates_the_approved_snapshot(self) -> None:
        scope = review_agent.inspect_scope(self.root)
        request = review_agent.stage(self.root, scope, now=1_000)
        Path(self.root, "app.py").chmod(0o755)
        runner = mock.Mock(return_value=self.result())

        with self.assertRaises(errors.Conflict):
            review_agent.execute(self.root, request["id"], runner=runner, now=1_001)

        runner.assert_not_called()
        self.assertEqual(review_agent.get(self.root, request["id"])["status"], "stale")

    def test_a_symlink_cannot_turn_an_external_line_into_a_finding(self) -> None:
        outside = Path(self.root).parent / f"{Path(self.root).name}-outside.py"
        outside.write_text("SECRET = 'outside'\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        Path(self.root, "escape.py").symlink_to(outside)
        scope = review_agent.inspect_scope(self.root)
        request = review_agent.stage(self.root, scope, now=1_000)

        row = review_agent.execute(
            self.root,
            request["id"],
            runner=lambda *_: self.result("escape.py", 1),
            now=1_001,
        )

        self.assertEqual(row["findings"], [])
        self.assertTrue(any("제외했어요" in str(gap) for gap in row["gaps"]))

    def test_feedback_state_is_ready_for_a_later_studio_panel(self) -> None:
        request = review_agent.stage(self.root, review_agent.inspect_scope(self.root), now=1_000)
        row = review_agent.execute(self.root, request["id"], runner=lambda *_: self.result(), now=1_001)

        accepted = review_agent.decide(self.root, row["id"], "f1", "accept", "동의해요", now=1_002)
        resolved = review_agent.decide(self.root, row["id"], "f1", "resolve", now=1_003)
        reopened = review_agent.decide(self.root, row["id"], "f1", "reopen", now=1_004)

        self.assertEqual(accepted["findings"][0]["status"], "accepted")
        self.assertEqual(resolved["status"], "closed")
        self.assertEqual(reopened["status"], "open")
        panel = review_agent.panel_state(self.root)
        self.assertEqual(panel["counts"]["open"], 1)
        self.assertIn("major", panel["labels"])


class TestReviewCli(ReviewRepoCase):
    def test_yes_without_a_pending_id_cannot_bypass_the_two_step_approval(self) -> None:
        with mock.patch.object(review_agent, "run_model") as model:
            with mock.patch("os.getcwd", return_value=self.root):
                outcome = run_cli("review", "--yes", "--json")

        self.assertEqual(outcome.exit_code, errors.InvalidInput.exit_code)
        self.assertIn("--approve", json.loads(outcome.stdout)["error"]["remedy"])
        model.assert_not_called()

    def test_noninteractive_call_stops_at_odin_confirmation(self) -> None:
        with mock.patch.object(review_agent, "run_model") as model:
            with mock.patch("os.getcwd", return_value=self.root):
                outcome = run_cli("review", "--json")

        self.assertEqual(outcome.exit_code, errors.Conflict.exit_code)
        payload = json.loads(outcome.stdout)
        self.assertEqual(payload["status"], "needs_confirmation")
        self.assertIn("--approve", payload["remedy"])
        model.assert_not_called()

    def test_approved_id_runs_the_read_only_agent_and_returns_one_json_document(self) -> None:
        with mock.patch("os.getcwd", return_value=self.root):
            waiting = run_cli("review", "--json")
        request_id = json.loads(waiting.stdout)["request"]["id"]

        with mock.patch.object(review_agent, "run_model", return_value=self.result()) as model:
            with mock.patch("os.getcwd", return_value=self.root):
                outcome = run_cli("review", "--approve", request_id, "--yes", "--json")

        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(json.loads(outcome.stdout)["status"], "open")
        self.assertEqual(outcome.stderr, "")
        model.assert_called_once()

    def test_declining_the_interactive_question_never_runs_the_model(self) -> None:
        with (
            mock.patch("os.getcwd", return_value=self.root),
            mock.patch("asgard.commands.review._interactive", return_value=True),
            mock.patch("asgard.commands.review._ask", return_value=False),
            mock.patch.object(review_agent, "run_model") as model,
        ):
            outcome = run_cli("review")

        self.assertEqual(outcome.exit_code, 0)
        self.assertIn("이번에는 부르지 않았어요", outcome.output)
        model.assert_not_called()

    def test_accepting_the_interactive_question_runs_the_fixed_request(self) -> None:
        with (
            mock.patch("os.getcwd", return_value=self.root),
            mock.patch("asgard.commands.review._interactive", return_value=True),
            mock.patch("asgard.commands.review._ask", return_value=True),
            mock.patch.object(review_agent, "run_model", return_value=self.result()) as model,
        ):
            outcome = run_cli("review")

        self.assertEqual(outcome.exit_code, 0)
        self.assertIn("제안 있음", outcome.output)
        model.assert_called_once()


class TestReviewToolContract(unittest.TestCase):
    def test_submission_is_an_inspect_capability_and_never_an_apply_tool(self) -> None:
        tool = review_agent.SUBMIT_REVIEW_TOOL
        self.assertEqual(tool["x-asgard-capability"], "inspect")
        self.assertEqual(tool["name"], "submit_review")
        self.assertNotIn("patch", tool["input_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
