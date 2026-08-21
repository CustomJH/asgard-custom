#!/usr/bin/env python3
"""병렬 단위의 수명 — lease 가 워커 한 턴을 버티는가, 회수가 살아 있는 것을 안 죽이는가.

26-08-21 실측이 이 파일의 이유다. 명령 표면 점검을 단위 일곱으로 나눠 돌렸더니:

  05:51:05  일곱 전부 in_progress (attempt 1)
  05:58:42  일곱 전부 failed / "lease expired"   ← 그때 기본 lease 300초, 실제 구간 486~804초
  05:58:59  재청구 (attempt 2)
  05:59:11~06:04:29  일곱 전부 done

죽은 단위는 하나도 없었다. 만료만 났고, 그 만료를 `ticket-recover` 가 실패로 접었다.
호스트 모드(Claude Code·Cursor·Codex)에서는 코디네이터가 자기 턴 안에 갇혀 있어 하트비트를
보낼 손이 없으므로, lease 가 턴보다 짧으면 **구조적으로** 매번 만료된다.

퀘스트는 프로세스 입구(`python -m asgard.hooks.quest_log`)로 연다 — 첫 이벤트에 실행 신원이
필요해서 이벤트를 손으로 적으면 무결성 검사에 걸린다.

실행: uv run pytest tests/test_ticket_lease.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from asgard_hooklib import tickets as tickets_module
from asgard_hooklib.ledger import fold_tickets, load_events
from asgard_hooklib.tickets import DEFAULT_LEASE_SECONDS, RECOVER_GRACE_SECONDS, ticket_runtime

# lease 가 덮어야 하는 구간 (초) — 티켓 `claim` 부터 `finish` 까지, 단위 일곱의 실측이다.
# `.asgard/quest/command-surface-check-260821.jsonl` 의 ticket 이벤트에서 쟀고, `.asgard/orchestration.db` 의
# 배차 소요(485.7~803.3초)와 1초 안에서 일치한다. 서브에이전트가 자기 안에서 돈 시간이 아니다 —
# 그것은 claim 보다 늦게 시작해 finish 보다 일찍 끝나므로 항상 짧고, 리스를 그 값으로 잡으면
# 매번 모자란다.
OBSERVED_WORKER_TURNS = (486, 486, 486, 559, 634, 793, 804)
NOW = 1_000_000.0


class TicketBase(unittest.TestCase):
    qid = "q-lease"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self._git_repo()
        self.tool("open", self.qid, "--criteria", "단위가 돌아요")

    def _git_repo(self) -> None:
        """쓰기 퀘스트는 시작 트리를 잡을 수 있는 Git 저장소를 요구한다 — 판정할 diff 의 밑변이다."""
        env = dict(
            os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e"
        )
        for argv in (
            ["git", "init", "-q"],
            ["git", "add", "-A"],
            ["git", "commit", "-q", "-m", "seed", "--allow-empty"],
        ):
            subprocess.run(argv, cwd=self.root, env=env, check=True, capture_output=True)

    def tool(self, *args: str, stdin: str = "") -> dict:
        src = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "src"))
        env = dict(os.environ, PYTHONPATH=src, CLAUDE_SESSION_ID="host-mode")
        proc = subprocess.run(
            [sys.executable, "-m", "asgard.hooks.quest_log", *args],
            cwd=self.root,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return {"out": proc.stdout, "err": proc.stderr}

    def declare(self, *units: str) -> None:
        """Thinker 가 배정 단위를 todo 로 세우는 자리."""
        for unit in units:
            body = json.dumps({"role": "thinker", "event": "ticket", "ticket_status": "todo", "unit": unit})
            self.tool("append", self.qid, "--json", body)

    def call(self, cmd: str, at: float = NOW, **kwargs):
        """`at` 시각에 이 전이를 부른다 — 잠들지 않고 만료를 재현한다."""
        clock = mock.Mock()
        clock.time.return_value = at
        kwargs.setdefault("unit", None)  # ticket-recover 는 단위를 안 겨냥할 수 있다.
        with mock.patch.object(tickets_module, "time", clock):
            return ticket_runtime(self.root, self.qid, cmd, session="host-mode", **kwargs)

    def statuses(self) -> dict[str, str]:
        return {uid: t["status"] for uid, t in fold_tickets(load_events(self.root, self.qid)).items()}


class TestLeaseOutlivesAWorkerTurn(unittest.TestCase):
    def test_the_default_lease_covers_every_turn_we_measured(self):
        self.assertGreater(
            DEFAULT_LEASE_SECONDS,
            max(OBSERVED_WORKER_TURNS),
            "기본 lease 가 실측한 가장 긴 워커 턴보다 짧다 — 그 단위는 매번 헛되이 만료된다",
        )

    def test_the_policy_default_agrees_with_the_runtime_default(self):
        """두 곳에 손으로 적힌 값은 한쪽만 낡는다."""
        from asgard_hooklib.policy import DEFAULT_POLICY

        self.assertEqual(DEFAULT_POLICY["ticket_runtime"]["lease_seconds"], DEFAULT_LEASE_SECONDS)


class TestRecoverDoesNotBuryTheLiving(TicketBase):
    def _claimed(self, *units: str, lease: int = 60) -> None:
        self.declare(*units)
        for unit in units:
            code, _ = self.call("ticket-claim", unit=unit, worker=f"w-{unit}", lease_seconds=lease)
            self.assertEqual(code, 0)

    def test_a_lease_that_just_expired_is_left_alone(self):
        self._claimed("1", lease=60)
        # 만료 1초 뒤 — 유예 안이다. 이 자리가 26-08-21 에 살아 있는 워커 일곱을 죽였다.
        code, payload = self.call("ticket-recover", at=NOW + 61)
        self.assertEqual(code, 0)
        self.assertEqual(payload["recovered"], [], "만료 직후를 죽음으로 읽었다")
        self.assertEqual(self.statuses()["1"], "in_progress")

    def test_a_ticket_quiet_past_the_grace_is_recovered(self):
        self._claimed("1", lease=60)
        code, payload = self.call("ticket-recover", at=NOW + 61 + RECOVER_GRACE_SECONDS)
        self.assertEqual(code, 0)
        self.assertEqual([r["unit"] for r in payload["recovered"]], ["1"])
        self.assertEqual(self.statuses()["1"], "failed")

    def test_recover_can_be_aimed_at_one_unit(self):
        """전부를 뒤집는 것이 유일한 선택지면, 하나가 죽었을 때 나머지가 같이 죽는다."""
        self._claimed("1", "2", "3", lease=60)
        code, payload = self.call("ticket-recover", unit="2", older_than=0, at=NOW + 61)
        self.assertEqual(code, 0)
        self.assertEqual([r["unit"] for r in payload["recovered"]], ["2"])
        statuses = self.statuses()
        self.assertEqual(statuses["1"], "in_progress", "겨냥하지 않은 단위가 뒤집혔다")
        self.assertEqual(statuses["3"], "in_progress", "겨냥하지 않은 단위가 뒤집혔다")

    def test_older_than_zero_still_reclaims_a_known_dead_worker(self):
        """워커가 확실히 죽었을 때는 기다릴 이유가 없다 — 유예는 기본값이지 벽이 아니다."""
        self._claimed("1", lease=60)
        _, payload = self.call("ticket-recover", older_than=0, at=NOW + 61)
        self.assertEqual([r["unit"] for r in payload["recovered"]], ["1"])

    def test_a_finished_unit_is_never_touched(self):
        self.declare("1")
        _, claim = self.call("ticket-claim", unit="1", worker="w-1", lease_seconds=60)
        self.call("ticket-finish", unit="1", claim_token=claim["claim_token"], status="done")
        _, payload = self.call("ticket-recover", older_than=0, at=NOW + 10_000)
        self.assertEqual(payload["recovered"], [])
        self.assertEqual(self.statuses()["1"], "done")

    def test_the_grace_is_not_zero(self):
        """유예가 0 이면 이 파일이 기록한 사고가 그대로 다시 난다."""
        self.assertGreater(RECOVER_GRACE_SECONDS, 0)


class TestTheDefaultActuallyReachesTheProject(unittest.TestCase):
    """코드 기본값을 올려도 설정 파일이 그것을 가리면 아무 일도 안 일어난다.

    26-08-21 실측: `lease_seconds` 기본값을 300 에서 1800 으로 올린 뒤에도 이 저장소의 유효값은
    300 이었다. `load_policy` 가 최상위 `update` 라 프로젝트가 적어 둔 `ticket_runtime` dict 가
    코드 기본값을 통째로 갈아 끼웠기 때문이다. 그때 그 설정은 `trinity_policy` 키 15개 중
    12개가 기본값과 글자까지 같았다 — 고른 것이 아니라 베낀 것이다."""

    def _root_with(self, policy: dict) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, ".asgard"), exist_ok=True)
        with open(os.path.join(tmp.name, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as fh:
            json.dump({"trinity_policy": policy}, fh)
        return tmp.name

    def _policy(self, root: str) -> dict:
        from asgard_hooklib.policy import load_policy

        return load_policy(root)

    def test_a_partial_nested_override_keeps_the_other_defaults(self):
        from asgard_hooklib.policy import DEFAULT_POLICY

        got = self._policy(self._root_with({"ticket_runtime": {"isolation": False}}))["ticket_runtime"]
        self.assertFalse(got["isolation"], "적어 둔 값이 안 먹었다")
        self.assertEqual(got["lease_seconds"], DEFAULT_POLICY["ticket_runtime"]["lease_seconds"])
        self.assertEqual(got["max_attempts"], DEFAULT_POLICY["ticket_runtime"]["max_attempts"])

    def test_an_explicit_value_still_wins(self):
        """고른 값을 병합이 되돌리면 그것도 결함이다."""
        got = self._policy(self._root_with({"ticket_runtime": {"lease_seconds": 42}}))
        self.assertEqual(got["ticket_runtime"]["lease_seconds"], 42)

    def test_a_scalar_key_is_replaced_whole(self):
        self.assertEqual(self._policy(self._root_with({"baseline_timeout": 600}))["baseline_timeout"], 600)

    def test_a_key_the_default_does_not_have_is_kept(self):
        self.assertEqual(self._policy(self._root_with({"a_key_from_the_future": 1}))["a_key_from_the_future"], 1)

    def test_the_merge_does_not_edit_what_the_caller_passed(self):
        from asgard_hooklib.policy import merge_policy

        override = {"nested": {"a": 9}}
        base = merge_policy({"nested": {"a": 1, "b": 2}}, override)
        self.assertEqual(override, {"nested": {"a": 9}}, "넘긴 dict 를 고쳤다")
        self.assertEqual(base["nested"], {"a": 9, "b": 2})

    def test_every_nested_default_survives_a_partial_override(self):
        """축은 `ticket_runtime` 이 아니라 **dict 값을 가진 모든 키**다.

        한 겹에서 멈춘 판은 `roles` 와 `budget_priors` 에서 같은 사고를 냈다 — 둘 다 두 겹이고,
        소비처가 조용한 폴백이라 값이 사라져도 화면에서는 정상과 구분이 안 된다. 축을 손목록으로
        적으면 다음에 늘어난 키에서 또 샌다."""
        import copy

        from asgard_hooklib.policy import DEFAULT_POLICY, merge_policy

        for key, default in DEFAULT_POLICY.items():
            if not isinstance(default, dict) or not default:
                continue
            first = sorted(default)[0]
            with self.subTest(policy_key=key):
                got = merge_policy(copy.deepcopy(DEFAULT_POLICY), {key: {first: default[first]}})[key]
                self.assertEqual(got, default, f"`{key}` 의 하위 키 하나만 적었더니 나머지가 사라졌다")

    def test_the_merge_follows_a_dict_all_the_way_down(self):
        """두 번째 층의 **모든** 자리를 돈다.

        키가 둘 이상인 안쪽 dict 만 재던 판은 `budget_priors` 를 통째로 건너뛰었다 — 그 안의
        `trivial` 이 키 하나뿐이라 조건에서 조용히 빠졌고, 직전 판정이 든 두 반례 중 하나가
        시험에서 사라져 있었다. 빈 dict 를 덮는 형태로 재면 키 개수와 무관하게 성립한다."""
        import copy

        from asgard_hooklib.policy import DEFAULT_POLICY, merge_policy

        pairs = [
            (key, inner_name, inner)
            for key, default in DEFAULT_POLICY.items()
            if isinstance(default, dict)
            for inner_name, inner in default.items()
            if isinstance(inner, dict) and inner
        ]
        self.assertTrue(pairs, "두 겹짜리 정책 자리가 없다 — 이 시험의 전제가 사라졌다")
        for key, inner_name, inner in pairs:
            with self.subTest(policy_key=f"{key}.{inner_name}"):
                # 빈 dict 를 덮어도 두 번째 층 기본값이 전부 남아야 한다.
                got = merge_policy(copy.deepcopy(DEFAULT_POLICY), {key: {inner_name: {}}})
                self.assertEqual(got[key][inner_name], inner, "두 겹 아래 기본값이 사라졌다")
                # 그리고 적어 둔 값은 그 층에서도 이겨야 한다.
                touch = sorted(inner)[0]
                got = merge_policy(copy.deepcopy(DEFAULT_POLICY), {key: {inner_name: {touch: "바뀐값"}}})
                self.assertEqual(got[key][inner_name][touch], "바뀐값", "적어 둔 값이 안 먹었다")
                for other in inner:
                    if other != touch:
                        self.assertEqual(got[key][inner_name][other], inner[other], "형제 기본값이 사라졌다")

    def test_a_list_value_is_replaced_whole(self):
        """리스트 원소를 짝지을 기준이 없다 — 합치려 들면 그것이 새 암묵 계약이 된다."""
        from asgard_hooklib.policy import merge_policy

        got = merge_policy({"baseline_checks": ["a", "b"]}, {"baseline_checks": ["c"]})
        self.assertEqual(got["baseline_checks"], ["c"])


if __name__ == "__main__":
    unittest.main()
