"""짝 저장소의 완료 증명 — 가드가 여는 자리를 증거층이 따라가는가.

`additional_roots` 로 선언한 저장소는 가드가 정당한 작업 대상으로 인정해 쓰기를 허용한다.
그런데 증거를 모으는 두 층이 세션 뿌리 하나만 보던 동안, 허용된 바로 그 자리에서만 Canon 10
강제가 통째로 꺼져 있었다 (26-08-11 재현): 퀘스트를 안 열어도 `orphan-write` 가 안 걸리고,
판정 뒤 변조도 `stale-pass` 가 안 걸렸다. 세션 저장소 안에서 하는 같은 일은 둘 다 걸렸다.

그래서 여기서 보는 것은 하나다 — **같은 일이 어느 저장소에서 벌어지든 판정이 같은가.**
각 시험은 짝 저장소 쪽만 주장하지 않고 세션 저장소 쪽을 대조군으로 함께 잰다.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from asgard_hooklib.tree import (
    current_tree_ref,
    diff_state,
    dirty_in_roots,
    peer_current,
    peer_roots,
    peer_snapshot,
    snapshot_ref,
    stale_pass_scope,
)

from asgard.hooks import write_sentinel


def _git(root: str, *args: str) -> None:
    subprocess.run(["git", "-C", root, *args], capture_output=True, check=True)


def _repo(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    return path


def _write(path: str, body: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


class PairSandbox(unittest.TestCase):
    """세션 저장소 하나 + 선언된 짝 저장소 하나 — helios-asgard ↔ helios-application 의 형상."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = os.path.realpath(self.tmp.name)
        self.repo = _repo(os.path.join(base, "session-repo"))
        self.pair = _repo(os.path.join(base, "pair-repo"))
        _write(os.path.join(self.repo, "own.txt"), "own\n")
        _write(os.path.join(self.pair, "logic.ts"), "export const rate = 1;\n")
        _write(
            os.path.join(self.repo, ".asgard", "asgard-setting-project.json"),
            json.dumps({"paths": {"additional_roots": ["../pair-repo"]}}),
        )
        for root in (self.repo, self.pair):
            _git(root, "add", "-A")
            _git(root, "commit", "-qm", "base")
        patch = mock.patch.dict(os.environ, {"HOME": base}, clear=False)
        patch.start()
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.addCleanup(patch.stop)

    def sentinel(self, file_path: str, sid: str = "s1") -> list[str]:
        """PostToolUse 를 한 번 태우고 그 세션의 write 저널을 돌려준다."""
        payload = {
            "cwd": self.repo,
            "session_id": sid,
            "tool_name": "Write",
            "tool_input": {"file_path": file_path},
            "tool_response": {},
        }
        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            mock.patch("sys.argv", ["hook"]),
            mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.repo}, clear=False),
        ):
            with self.assertRaises(SystemExit):
                write_sentinel.main()
        journal = os.path.join(self.repo, ".asgard", "state", f"writes-{sid}.json")
        with open(journal, encoding="utf-8") as handle:
            return json.load(handle)


class TestTheSentinelRecordsWhatTheGuardAllows(PairSandbox):
    def test_a_write_into_the_declared_pair_repo_is_recorded(self) -> None:
        _write(os.path.join(self.pair, "logic.ts"), "export const rate = 2;\n")
        self.assertEqual(self.sentinel(os.path.join(self.pair, "logic.ts")), ["../pair-repo/logic.ts"])

    def test_the_session_repo_notation_is_unchanged(self) -> None:
        """대조군 — 세션 저장소 안의 표기는 예전 그대로여야 한다 (귀속 집합이 이 표기로 대조된다)."""
        self.assertEqual(self.sentinel(os.path.join(self.repo, "own.txt")), ["own.txt"])

    def test_a_path_outside_every_root_is_still_dropped(self) -> None:
        """뿌리 밖은 여전히 안 적는다 — 스크래치패드의 일회용 스크립트가 코드처럼 심판받으면
        그 판정이 서브에이전트의 보고를 밀어낸다 (26-08-05 실측)."""
        outside = os.path.join(os.path.dirname(self.repo), "scratch", "probe.py")
        _write(outside, "print(1)\n")
        journal = os.path.join(self.repo, ".asgard", "state", "writes-s1.json")
        self.sentinel(outside)
        with open(journal, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [])


class TestDirtyIsMeasuredInTheOwningRepo(PairSandbox):
    def test_a_dirty_pair_file_is_seen(self) -> None:
        _write(os.path.join(self.pair, "logic.ts"), "export const rate = 3;\n")
        self.assertEqual(dirty_in_roots(self.repo, ["../pair-repo/logic.ts"]), ["../pair-repo/logic.ts"])

    def test_a_clean_pair_file_is_not_reported(self) -> None:
        """되돌린 write 는 차단 사유가 아니다 — 세션 저장소 쪽과 같은 규칙이다."""
        self.assertEqual(dirty_in_roots(self.repo, ["../pair-repo/logic.ts"]), [])

    def test_the_session_repo_still_works(self) -> None:
        _write(os.path.join(self.repo, "own.txt"), "changed\n")
        self.assertEqual(dirty_in_roots(self.repo, ["own.txt"]), ["own.txt"])


class TestTheVerdictHashFollowsThePairRepo(PairSandbox):
    def setUp(self) -> None:
        super().setUp()
        self.base_ref = snapshot_ref(self.repo)
        self.peer_base = peer_snapshot(self.repo)

    def test_the_pair_repo_is_discovered_as_a_peer(self) -> None:
        self.assertEqual([label for label, _ in peer_roots(self.repo)], ["../pair-repo"])
        self.assertIn("../pair-repo", self.peer_base)

    def test_an_unchanged_tree_is_still_empty(self) -> None:
        digest, changed, _, _ = diff_state(self.repo, self.base_ref, peer_base=self.peer_base)
        self.assertEqual(changed, [])
        self.assertEqual(digest, hashlib.sha256(b"").hexdigest())

    def test_a_pair_repo_edit_moves_the_hash_and_names_the_file(self) -> None:
        before, _, _, _ = diff_state(self.repo, self.base_ref, peer_base=self.peer_base)
        _write(os.path.join(self.pair, "logic.ts"), "export const rate = 4242;\n")
        after, changed, lines, _ = diff_state(self.repo, self.base_ref, peer_base=self.peer_base)
        self.assertNotEqual(after, before)
        self.assertEqual(changed, ["../pair-repo/logic.ts"])
        self.assertGreater(lines, 0)  # 큰 diff 판정도 짝 저장소의 질량을 세야 한다

    def test_without_a_baseline_the_pair_repo_is_invisible(self) -> None:
        """구 로그(기준선을 안 적은 퀘스트)는 예전대로 동작한다 — 이 자리는 write 저널이 잡는다."""
        _write(os.path.join(self.pair, "logic.ts"), "export const rate = 9;\n")
        _, changed, _, _ = diff_state(self.repo, self.base_ref, peer_base=None)
        self.assertEqual(changed, [])

    def test_the_pair_harness_state_is_excluded(self) -> None:
        """짝 저장소의 `.asgard` 는 그 저장소의 하네스 상태다 — 판정 해시에 넣으면 자기참조가 된다."""
        _write(os.path.join(self.pair, ".asgard", "state", "note.json"), "{}\n")
        _, changed, _, _ = diff_state(self.repo, self.base_ref, peer_base=self.peer_base)
        self.assertEqual(changed, [])

    def test_a_pass_seals_both_trees(self) -> None:
        sealed = peer_current(self.repo)
        self.assertIn("../pair-repo", sealed)
        _write(os.path.join(self.pair, "logic.ts"), "export const rate = -1;\n")
        self.assertNotEqual(peer_current(self.repo)["../pair-repo"], sealed["../pair-repo"])


class TestStalePassSeesThePairRepo(PairSandbox):
    """PASS 뒤에 짝 저장소가 움직이면 재검증이다 — 세션 저장소와 같은 규칙."""

    def _pass_event(self) -> dict:
        return {
            "event": "verify",
            "verdict": "PASS",
            "tree_ref": current_tree_ref(self.repo),
            "peer_tree": peer_current(self.repo),
            "changed_files": ["../pair-repo/logic.ts"],
        }

    def _events(self) -> list[dict]:
        # 귀속 집합 — Worker 가 관측한 변경 파일. 비면 fail-safe 로 무조건 stale 이라 판정이 공짜다.
        return [{"event": "work", "changed_files": ["../pair-repo/logic.ts"]}]

    def test_an_untouched_tree_is_not_stale(self) -> None:
        stale, _ = stale_pass_scope(self.repo, self._pass_event(), self._events(), ["../pair-repo/logic.ts"])
        self.assertEqual(stale, [])

    def test_a_pair_repo_edit_after_pass_is_stale(self) -> None:
        last_pass = self._pass_event()
        _write(os.path.join(self.pair, "logic.ts"), "export const rate = -1;\n")
        stale, _ = stale_pass_scope(self.repo, last_pass, self._events(), ["../pair-repo/logic.ts"])
        self.assertEqual(stale, ["../pair-repo/logic.ts"])

    def test_a_session_repo_edit_after_pass_is_still_stale(self) -> None:
        last_pass = self._pass_event()
        last_pass["changed_files"] = ["own.txt"]
        _write(os.path.join(self.repo, "own.txt"), "changed\n")
        stale, _ = stale_pass_scope(
            self.repo, last_pass, [{"event": "work", "changed_files": ["own.txt"]}], ["own.txt"]
        )
        self.assertEqual(stale, ["own.txt"])


if __name__ == "__main__":
    unittest.main()
