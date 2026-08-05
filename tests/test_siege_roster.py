"""배차 장부가 **누구를 불렀는지** 말하는가.

실행: uv run pytest tests/test_siege_roster.py

`tests/test_siege_act.py` 는 배정 단위 티켓이 장부를 채우는 것까지 붙든다. 그 아래로 두 칸이
비어 있었다:

  · 호출된 에이전트가 어디에도 안 적혔다. 호스트 3모드에서 장부에 오르는 것은 단위 티켓뿐이라,
    Verifier 도 딜리버리 전문가도 부른 적 없는 것처럼 남았다.
  · 적힌 것조차 안 보였다. `siege show` 는 시도 횟수만 세고 그 시도를 누가 들었는지는 말하지
    않아서, 네이티브가 이미 적어 둔 `agent` 칸이 사람 눈에 닿지 않았다.

둘은 한 쌍이다. 적히지 않으면 보일 것이 없고, 안 보이면 적힌 것이 쓸모가 없다.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hookscaffold import deploy_cli, until  # noqa: E402

from asgard import orchestration as orc  # noqa: E402
from asgard.commands import siege  # noqa: E402
from asgard.orchestration import store  # noqa: E402


def _shown(row: dict | None) -> dict:
    """장부 조회의 결과 — 빈손이면 다음 줄에서 뭘 재려 했든 그것이 곧 실패다."""
    assert row is not None, "장부 조회가 빈손이다"
    return row


class RosterBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        subprocess.run(["git", "init", "-q", self.root], check=True, capture_output=True)
        self._cwd = os.getcwd()
        self.addCleanup(lambda: os.chdir(self._cwd))
        os.chdir(self.root)
        override = os.environ.pop(store.STATE_ENV, None)
        if override is not None:
            self.addCleanup(os.environ.__setitem__, store.STATE_ENV, override)

    def capture(self, call) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            call()
        return buffer.getvalue()


class TestOneCallIsOneRow(RosterBase):
    """에이전트 호출 하나가 Task 하나 + Dispatch 하나로 선다."""

    def test_the_call_records_which_agent_ran_it(self):
        dispatch = orc.note_agent(self.root, "q-1", "asgard-thor", spec="결제 API 손보기")
        self.assertEqual(dispatch["agent"], "asgard-thor")
        self.assertEqual(dispatch["state"], "ready")
        run = orc.run_list(self.root)[0]
        self.assertEqual(run["quest_id"], "q-1")
        self.assertEqual([t["spec"] for t in orc.task_list(self.root, run["id"])], ["결제 API 손보기"])

    def test_two_calls_to_one_agent_are_two_tasks(self):
        """같은 에이전트를 두 표면에 부르는 것은 재시도가 아니다 — 한 Task 에 합치면 회로
        차단이 두 번째 호출을 '2회 실패' 로 읽는다."""
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="첫 표면")
        orc.close_agent(self.root, "q-1", "asgard-thor")
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="둘째 표면")
        run = orc.run_list(self.root)[0]
        self.assertEqual(len(orc.task_list(self.root, run["id"])), 2)

    def test_a_nested_call_hangs_under_its_caller(self):
        orc.note_agent(self.root, "q-1", "asgard-worker", spec="상위 일감")
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="아래 일감", caller="asgard-worker")
        run = orc.run_list(self.root)[0]
        tasks = {t["spec"]: t for t in orc.task_list(self.root, run["id"])}
        self.assertEqual(tasks["아래 일감"]["parent_id"], tasks["상위 일감"]["id"])

    def test_a_nameless_agent_is_refused(self):
        """이름 없는 행은 장부의 유일한 물음('누구를 불렀나')에 답하지 못한다."""
        with self.assertRaises(orc.OrchestrationError):
            orc.note_agent(self.root, "q-1", "", spec="이름 없는 호출")

    def test_closing_settles_the_live_attempt(self):
        opened = orc.note_agent(self.root, "q-1", "asgard-verifier", spec="독립 판정")
        closed = orc.close_agent(self.root, "q-1", "asgard-verifier", summary="판정 FAIL")
        self.assertEqual(closed["dispatch"]["id"], opened["id"])
        self.assertEqual(closed["dispatch"]["state"], "settled")
        self.assertEqual(closed["dispatch"]["summary"], "판정 FAIL")

    def test_closing_what_was_never_opened_is_refused(self):
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="하나")
        with self.assertRaises(orc.OrchestrationError):
            orc.close_agent(self.root, "q-1", "asgard-freyja")

    def test_closing_never_takes_a_unit_ticket(self):
        """단위 티켓의 수명은 ticket-finish 가 쥔다. 이름만으로 고르면 훅의 종료가 그 시도를
        먼저 접고, 뒤따르는 ticket-finish 는 정산할 것을 잃는다."""
        run = orc.run_create(self.root, "단위가 도는 Run", quest_id="q-1")
        task = orc.task_create(self.root, run["id"], "u-1 일감", unit_id="u-1")
        ticket = orc.open_dispatch(self.root, task["id"], worker="w-1", role="worker", agent="asgard-worker")
        with self.assertRaises(orc.OrchestrationError):
            orc.close_agent(self.root, "q-1", "asgard-worker")
        self.assertEqual(_shown(orc.dispatch_show(self.root, dispatch_id=ticket["id"]))["state"], "ready")

    def test_live_agents_names_who_is_still_out(self):
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="아직 도는 중")
        orc.note_agent(self.root, "q-1", "asgard-freyja", spec="이미 끝난 것")
        orc.close_agent(self.root, "q-1", "asgard-freyja")
        run = orc.run_list(self.root)[0]
        self.assertEqual([d["agent"] for d in orc.live_agents(self.root, run["id"])], ["asgard-thor"])


class TestTheHumanSurfaceNamesTheAgent(RosterBase):
    """`siege show` 가 시도마다 누가 들었고 지금 어떻게 됐는지를 말한다."""

    def test_each_attempt_line_carries_the_agent_and_its_state(self):
        orc.note_agent(self.root, "q-1", "asgard-verifier", spec="독립 판정")
        orc.close_agent(self.root, "q-1", "asgard-verifier", summary="판정 FAIL")
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="백엔드 수리")
        run = orc.run_list(self.root)[0]

        out = self.capture(lambda: siege.run_show(run["id"]))
        self.assertIn("asgard-verifier", out, "누가 판정했는지가 화면에 없다")
        self.assertIn("판정 FAIL", out, "그 시도가 무엇을 남겼는지가 화면에 없다")
        self.assertIn("asgard-thor", out)
        self.assertIn("도는 중", out, "아직 답이 안 온 시도가 끝난 것처럼 보인다")

    def test_an_attempt_without_an_agent_still_names_its_worker(self):
        run = orc.run_create(self.root, "손으로 몬 Run", quest_id="q-1")
        task = orc.task_create(self.root, run["id"], "손으로 만든 일감")
        orc.open_dispatch(self.root, task["id"], worker="heimdall-main", role="WORKER")
        self.assertIn("heimdall-main", self.capture(lambda: siege.run_show(run["id"])))

    def test_the_run_list_names_who_is_still_running(self):
        """목록의 다른 칸은 전부 지나간 일이다 — 이 줄이 없으면 무엇이 아직 돌고 있는지를
        알려면 Run 마다 `siege show` 를 쳐야 한다."""
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="아직 도는 중")
        orc.note_agent(self.root, "q-1", "asgard-freyja", spec="이미 끝난 것")
        orc.close_agent(self.root, "q-1", "asgard-freyja")
        out = self.capture(siege.run_runs)
        self.assertIn("asgard-thor", out)
        self.assertNotIn("asgard-freyja", out, "끝난 에이전트가 아직 도는 것처럼 보인다")

    def test_the_json_shape_still_carries_every_attempt(self):
        orc.note_agent(self.root, "q-1", "asgard-thor", spec="하나")
        run = orc.run_list(self.root)[0]
        payload = json.loads(self.capture(lambda: siege.run_show(run["id"], json_out=True)))
        self.assertEqual([a["agent"] for a in payload["tasks"][0]["attempts_detail"]], ["asgard-thor"])


class TestTheHostHookRecordsTheCall(RosterBase):
    """호스트 3모드에서 에이전트 호출이 장부에 오르는 유일한 자리 — 디스패치 훅.

    네이티브 루프(`agent/heimdall/bifrost.py`)는 같은 것을 프로세스 안에서 적는다. 세 호스트
    모드에는 그 루프가 없어서, 이 훅이 안 적으면 `asgard siege` 는 어떤 에이전트가 불렸는지
    영영 말하지 못한다.
    """

    def setUp(self) -> None:
        super().setUp()
        # 신원은 시험이 세운다 — 러너에는 전역 git 설정이 없어서 commit 이 exit 128 로 죽는다.
        for pair in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", self.root, "config", *pair], check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "seed"], cwd=self.root, check=True)
        self.src = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "src"))
        self.qid = "q-hook"
        # 세션 키를 인자로 고정한다. `host_session_id()` 는 호스트가 내보내는 환경변수를 여러
        # 이름으로 찾으므로, 시험을 돌리는 사람의 셸에 그 이름이 있으면 포인터 파일 이름이
        # 달라져 아래의 "퀘스트 밖" 갈래가 엉뚱한 이유로 깨진다.
        proc = subprocess.run(
            [sys.executable, "-m", "asgard.hooks.quest_log", "open", self.qid, "--criteria", "돌아요"]
            + ["--session", "host-mode"],
            cwd=self.root,
            env=dict(os.environ, PYTHONPATH=self.src),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # 훅은 장부를 임포트가 아니라 CLI 프로세스로 적는다 — 배포 인터프리터에 asgard 가
        # 없기 때문이다. PATH 의 `asgard` 가 이 저장소의 코드가 되게 얹는다.
        self.bin = os.path.join(self.root, "bin")
        deploy_cli(self.bin)

    def hook(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "asgard.hooks.subagent_gate"],
            cwd=self.root,
            env=dict(
                os.environ,
                PYTHONPATH=self.src,
                CLAUDE_PROJECT_DIR=self.root,
                PATH=self.bin + os.pathsep + os.environ.get("PATH", ""),
            ),
            input=json.dumps({"session_id": "host-mode", "cwd": self.root, **payload}),
            capture_output=True,
            text=True,
            timeout=120,
        )

    def settled(self, count: int = 1) -> list[dict]:
        """장부에 시도가 `count` 건 설 때까지 기다린 뒤 그 Run 의 Task 를 돌려준다."""
        until(lambda: bool(orc.run_list(self.root)))
        runs = orc.run_list(self.root)
        self.assertEqual(len(runs), 1, "디스패치가 장부에 아무것도 안 남겼다")
        until(lambda: len(orc.task_list(self.root, runs[0]["id"])) >= count)
        # 시도 행도 기다린다 — Task 와 같은 프로세스가 적지만 같은 순간은 아니다. Task 만 보고
        # 곧바로 `live_agents` 를 읽으면 빈 목록이 나온다 (26-08-06 러너 실측: 로컬 6회 연속
        # 통과, ubuntu 러너 전수 병렬에서 한 건 빨강). 이 대기가 이 함수 독스트링의 계약이다.
        until(lambda: len(orc.live_agents(self.root, runs[0]["id"])) >= count)
        return orc.task_list(self.root, runs[0]["id"])

    def dispatch_payload(self, target: str, prompt: str, caller: str = "") -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "agent_type": caller,
            "tool_input": {"subagent_type": target, "prompt": prompt},
        }

    def test_a_dispatch_puts_the_agent_on_the_ledger(self):
        self.hook(self.dispatch_payload("asgard-thor", "결제 API 를 손봐라"))
        tasks = self.settled()
        attempts = orc.live_agents(self.root, orc.run_list(self.root)[0]["id"])
        self.assertEqual([a["agent"] for a in attempts], ["asgard-thor"])
        self.assertEqual(tasks[0]["spec"], "결제 API 를 손봐라")

    def test_a_specialist_stop_closes_its_row(self):
        """딜리버리 전문가는 로그 규율의 대상이 아니다. 그래도 접어야 한다 — 안 접으면
        이미 끝난 에이전트가 `siege show` 에서 영영 '도는 중' 으로 남는다."""
        self.hook(self.dispatch_payload("asgard-freyja", "화면을 손봐라"))
        self.settled()
        run = orc.run_list(self.root)[0]
        self.hook({"hook_event_name": "SubagentStop", "agent_type": "asgard-freyja"})
        until(lambda: not orc.live_agents(self.root, run["id"]))
        self.assertEqual(orc.live_agents(self.root, run["id"]), [], "끝난 에이전트가 도는 중으로 남았다")
        self.assertEqual(orc.task_list(self.root, run["id"])[0]["status"], "completed")

    def test_a_unit_dispatch_is_left_to_the_ticket(self):
        """단위 마커가 붙은 호출의 수명은 ticket-claim/finish 가 쥔다. 훅이 또 열면 한 Task 를
        둘이 연다."""
        self.hook(self.dispatch_payload("asgard-worker", "[ASGARD_UNIT:u-1]\n스키마를 옮겨라"))
        until(lambda: bool(orc.run_list(self.root)), timeout=3.0)
        self.assertEqual(orc.run_list(self.root), [], "단위 호출을 훅이 장부에 또 열었다")

    def test_the_first_line_of_the_prompt_becomes_the_task(self):
        self.hook(self.dispatch_payload("asgard-thor", "\n\n결제 경로 정리\n\n자세한 지시는 아래에"))
        self.assertEqual(self.settled()[0]["spec"], "결제 경로 정리")

    def test_a_unit_ticket_names_the_agent_that_claimed_it(self):
        """티켓은 워커 id 만 든다(`w-1`). 어떤 에이전트가 그 id 로 돌았는지는 디스패치 시점에만
        알 수 있고, 그 영수증이 없으면 장부의 이름 칸이 빈 채로 남는다."""
        from asgard.hooks import quest_log

        body = json.dumps({"role": "thinker", "event": "ticket", "ticket_status": "todo", "unit": "u-1"})
        proc = subprocess.run(
            [sys.executable, "-m", "asgard.hooks.quest_log", "append", self.qid, "--session", "host-mode"],
            cwd=self.root,
            env=dict(os.environ, PYTHONPATH=self.src),
            input=body,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.hook(self.dispatch_payload("asgard-worker", "[ASGARD_UNIT:u-1]\n스키마를 옮겨라"))
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        self.addCleanup(os.environ.__setitem__, "PATH", os.environ["PATH"].split(os.pathsep, 1)[1])
        code, _ = quest_log.ticket_runtime(self.root, self.qid, "ticket-claim", unit="u-1", session="s", worker="w-1")
        self.assertEqual(code, 0)
        until(lambda: bool(orc.run_list(self.root)))
        run = orc.run_list(self.root)[0]
        until(lambda: orc.task_for_unit(self.root, run["id"], "u-1") is not None)
        task = _shown(orc.task_for_unit(self.root, run["id"], "u-1"))
        self.assertEqual(_shown(orc.dispatch_show(self.root, task_id=task["id"]))["agent"], "asgard-worker")

    def test_a_dispatch_outside_a_quest_records_nothing(self):
        """활성 퀘스트가 없으면 DIRECT·탐사 디스패치다 — 장부를 열 자리가 아니다."""
        os.remove(os.path.join(self.root, ".asgard", "quest", "sessions", "host-mode.active"))
        self.hook(self.dispatch_payload("asgard-thor", "그냥 찾아보기"))
        until(lambda: orc.exists(self.root), timeout=3.0)
        self.assertFalse(orc.exists(self.root), "퀘스트 밖 디스패치가 장부를 만들었다")


class TestTheWiringReachesEveryAgent(RosterBase):
    """세 호스트의 종료 훅이 역할 셋에만 걸려 있으면 나머지 에이전트는 접히지 않는다."""

    def test_claude_settles_every_agent_not_only_the_three_roles(self):
        from asgard.templates.claude import cc_settings

        stops = json.loads(cc_settings())["hooks"]["SubagentStop"]
        gate = [entry for entry in stops if "subagent-gate" in json.dumps(entry)]
        self.assertEqual(len(gate), 1, "종료 훅이 하나가 아니면 규율이 두 번 돈다")
        self.assertNotIn("matcher", gate[0], "역할 매처가 남으면 전문가의 시도가 안 접힌다")

    def test_cursor_settles_every_agent(self):
        from asgard.templates.cursor import cursor_hooks_json

        stops = json.loads(cursor_hooks_json())["hooks"]["subagentStop"]
        gate = [entry for entry in stops if "subagent-gate" in json.dumps(entry)]
        self.assertEqual(len(gate), 1)
        self.assertNotIn("matcher", gate[0])

    def test_codex_settles_every_agent(self):
        import tomllib

        from asgard.templates.codex import codex_config

        stops = tomllib.loads(codex_config())["hooks"]["SubagentStop"]
        gate = [entry for entry in stops if "subagent-gate" in json.dumps(entry)]
        self.assertEqual(len(gate), 1)
        self.assertNotIn("matcher", gate[0])


if __name__ == "__main__":
    unittest.main()
