"""siege — 배차를 명령만으로 몰 수 있는가.

실행: uv run pytest tests/test_siege_act.py

`tests/test_siege.py` 는 읽는 절반(`commands/siege.py`)을 본다. 이 파일은 모는 절반
(`commands/siege_act.py`)과, 호스트 모드에서 그 장부가 **저절로** 적히는 경로를 본다.

여기서 지키는 계약 넷:
  · 배차 한 바퀴(Run 열기 → DAG → 시도 → 완료 보고 → 의존 해제)가 명령만으로 돈다.
  · 도메인이 거절하는 것은 여기서도 거절한다 — 종료 코드 2 이고, 장부는 안 바뀐다.
  · 저장소 뿌리 판정이 읽는 절반과 같다 — 하위 디렉터리에서 쳐도 같은 장부를 본다.
  · Claude Code·Cursor·Codex 모드의 티켓 전이가 장부를 채운다 (`hooks/quest_log.py`).

넷째가 이 파일이 생긴 까닭이다. 그 경로가 없던 동안 세 호스트 모드에서 `asgard siege` 는
언제나 빈 장부를 보여 줬고, 단위 시험으로는 안 잡혔다 — 읽는 쪽도 도메인도 각자 옳았다.
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
from typing import Any
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hookscaffold import deploy_cli, until  # noqa: E402

from asgard import orchestration as orc  # noqa: E402
from asgard.commands import siege, siege_act  # noqa: E402
from asgard.orchestration import store  # noqa: E402


class ActBase(unittest.TestCase):
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

    def json_of(self, call) -> Any:
        """`--json` 출력을 되읽는다 — 호스트 에이전트가 소비하는 바로 그 모양이다."""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = call()
        self.assertEqual(code, 0, buffer.getvalue())
        return json.loads(buffer.getvalue())

    def task_of(self, task_id: str) -> dict:
        """장부가 든 그 일감 — 빈손이면 다음 줄에서 뭘 재려 했든 그것이 곧 실패다."""
        task = orc.task_show(self.root, task_id)
        assert task is not None, f"장부에 없는 일감: {task_id}"
        return task

    def unit_of(self, run_id: str, unit: str) -> dict:
        """DAG 에 선 그 단위 — 없으면 의존을 그릴 자리조차 없다."""
        task = orc.task_for_unit(self.root, run_id, unit)
        assert task is not None, f"DAG 에 안 선 단위: {unit}"
        return task

    def quiet(self, call) -> int:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            return call()

    def start_run(self, objective: str = "결제 모듈 손보기", **kwargs) -> str:
        run = self.json_of(lambda: siege_act.run_start(objective, json_out=True, **kwargs))
        return run["id"]

    def add_task(self, run_id: str, spec: str, **kwargs) -> str:
        task = self.json_of(lambda: siege_act.run_add(run_id, spec, json_out=True, **kwargs))
        return task["id"]


class TestOneSiegeByCommandAlone(ActBase):
    """명령만으로 한 바퀴. 어느 한 동사가 빠져도 여기서 끊긴다."""

    def test_a_dependent_task_is_released_when_its_predecessor_reports_done(self):
        run_id = self.start_run(shape="graph", why="단위 둘이 의존으로 묶여요")
        first = self.add_task(run_id, "스키마 옮기기", unit_id="u-schema")
        second = self.add_task(run_id, "API 붙이기", unit_id="u-api", deps=[first])

        ready = self.json_of(lambda: siege_act.run_ready(run_id, json_out=True))
        self.assertEqual([task["id"] for task in ready], [first], "의존이 남은 일감이 배차 후보에 있다")

        dispatch = self.json_of(lambda: siege_act.run_open(first, worker="w-1", json_out=True))
        self.assertEqual(self.task_of(first)["status"], "dispatched")

        reported = self.json_of(
            lambda: siege_act.run_done(
                dispatch["id"], "succeeded", run_id=run_id, task_id=first, body="옮겼어요", json_out=True
            )
        )
        self.assertEqual(reported["task"]["status"], "completed")

        released = self.json_of(lambda: siege_act.run_ready(run_id, json_out=True))
        self.assertEqual([task["id"] for task in released], [second], "앞 일감이 끝났는데 뒤가 안 풀렸다")

    def test_the_waves_put_a_dependency_in_a_later_batch(self):
        run_id = self.start_run()
        first = self.add_task(run_id, "먼저", unit_id="u-1")
        self.add_task(run_id, "나중", unit_id="u-2", deps=[first])
        self.add_task(run_id, "옆에서 같이", unit_id="u-3")
        waves = self.json_of(lambda: siege_act.run_waves(run_id, json_out=True))
        self.assertEqual([sorted(item["label"] for item in wave) for wave in waves], [["u-1", "u-3"], ["u-2"]])

    def test_a_question_travels_from_the_worker_to_the_mailbox_and_back(self):
        run_id = self.start_run()
        task_id = self.add_task(run_id, "스키마 옮기기")
        message = self.json_of(
            lambda: siege_act.run_ask(run_id, "컬럼을 바꿔도 되나요?", options=["유지", "변경"], json_out=True)
        )
        batch = self.json_of(lambda: siege_act.run_check(run_id, json_out=True))
        self.assertIn(message["id"], [row["id"] for row in batch["messages"]])
        self.assertEqual(self.quiet(lambda: siege.run_answer(message["id"], "유지하세요")), 0)
        self.assertEqual(orc.pending_questions(self.root, run_id), [], "답한 질문이 아직 대기로 남아 있다")
        self.assertTrue(task_id)

    def test_a_gate_the_coordinator_opened_is_closed_by_decide(self):
        run_id = self.start_run()
        gate = self.json_of(lambda: siege_act.run_gate(run_id, "버전을 올릴까요?", options=["v1", "v2"], json_out=True))
        self.assertEqual(self.quiet(lambda: siege.run_decide(gate["id"], "v2")), 0)
        self.assertEqual(orc.gate_list(self.root, run_id=run_id, status="open"), [], "닫은 게이트가 아직 열려 있다")

    def test_the_circuit_breaks_after_the_attempt_budget_is_spent(self):
        run_id = self.start_run()
        task_id = self.add_task(run_id, "붙지 않는 일감")
        for _ in range(orc.MAX_ATTEMPTS):
            dispatch = self.json_of(lambda: siege_act.run_open(task_id, json_out=True))
            self.quiet(lambda: siege_act.run_done(dispatch["id"], "failed", run_id=run_id, task_id=task_id))
        self.assertEqual(self.task_of(task_id)["status"], "failed")
        self.assertEqual(self.quiet(lambda: siege_act.run_open(task_id)), 2, "회로가 끊긴 뒤에도 배차가 열린다")

    def test_the_broken_circuit_names_what_was_already_tried(self):
        """끊긴 회로가 막다른 길로 읽히면 코디네이터는 지난 시도를 안 보고 처음부터 다시 짠다.

        시도의 결과는 이미 장부에 있다 — 거절 문구가 그것을 같이 내밀어야 고를 것이 있다는
        사실이 보인다 (SWE-agent 의 재시도 루프가 상한에서 최선을 고르는 것과 같은 자리).
        """
        run_id = self.start_run()
        task_id = self.add_task(run_id, "붙지 않는 일감")
        for index in range(orc.MAX_ATTEMPTS):
            dispatch = self.json_of(lambda: siege_act.run_open(task_id, agent="asgard-thor", json_out=True))
            self.quiet(
                lambda: siege_act.run_done(
                    dispatch["id"], "failed", run_id=run_id, task_id=task_id, body=f"{index}번째 시도의 남은 것"
                )
            )
        with self.assertRaises(orc.OrchestrationError) as caught:
            orc.open_dispatch(self.root, task_id)
        message = str(caught.exception)
        self.assertIn("지난 시도", message)
        self.assertIn("asgard-thor", message, "누가 시도했는지가 거절 문구에 없다")
        self.assertIn(f"{orc.MAX_ATTEMPTS}회", message, "몇 번째 시도까지 갔는지가 안 보인다")


class TestThePlanLaysTheWholeGraph(ActBase):
    """`plan` 한 번이 그래프를 세운다 — 색인 의존, 에이전트 결속, 단위별 검증 레인."""

    def plan(self, run_id: str, units: list[dict]) -> dict:
        return self.json_of(lambda: siege_act.run_plan(run_id, json.dumps(units), json_out=True))

    def test_dependencies_are_written_by_index_so_no_id_round_trip_is_needed(self):
        run_id = self.start_run(shape="graph")
        laid = self.plan(
            run_id,
            [
                {"spec": "스키마", "unit": "u-schema"},
                {"spec": "API", "unit": "u-api", "deps": [0]},
            ],
        )
        schema, api = laid["tasks"]
        self.assertEqual(api["deps"], [schema["id"]], "색인 의존이 id 로 안 풀렸다")
        self.assertEqual(schema["status"], "ready")
        self.assertEqual(api["status"], "pending")

    def test_the_agent_is_bound_before_anything_is_dispatched(self):
        run_id = self.start_run()
        laid = self.plan(run_id, [{"spec": "API 손보기", "agent": "asgard-thor"}])
        (task,) = laid["tasks"]
        self.assertEqual(self.task_of(task["id"])["agent"], "asgard-thor")

        ready = self.json_of(lambda: siege_act.run_ready(run_id, json_out=True))
        self.assertEqual(ready[0]["agent"], "asgard-thor", "배차 후보가 누구를 띄울지 안 말한다")

    def test_a_verify_pair_waits_on_its_own_unit_and_not_on_the_rest_of_the_graph(self):
        """이 시험이 병렬 검증의 전부다 — A 의 검증이 B 의 작업과 같은 물결에 떠야 한다."""
        run_id = self.start_run(shape="graph")
        laid = self.plan(
            run_id,
            [
                {"spec": "백엔드", "agent": "asgard-thor", "verify": True},
                {"spec": "CLI", "agent": "asgard-thor", "verify": True},
            ],
        )
        backend, cli_task = laid["tasks"][:2]
        checker = next(t for t in laid["tasks"] if t["deps"] == [backend["id"]])
        self.assertEqual(checker["kind"], "verify")
        self.assertEqual(checker["agent"], "asgard-verifier", "판정을 쓰기 가능한 손에게 줬다")

        dispatch = self.json_of(lambda: siege_act.run_open(backend["id"], worker="w-1", json_out=True))
        self.quiet(lambda: siege_act.run_done(dispatch["id"], "succeeded", json_out=True))

        ready = {task["id"] for task in self.json_of(lambda: siege_act.run_ready(run_id, json_out=True))}
        self.assertIn(checker["id"], ready, "앞 단위가 끝났는데 그 검증이 안 풀렸다")
        self.assertIn(cli_task["id"], ready, "검증이 다른 단위의 작업을 붙들고 있다")

    def test_a_dependency_pointing_forward_leaves_no_half_built_graph(self):
        run_id = self.start_run()
        code = self.quiet(
            lambda: siege_act.run_plan(run_id, json.dumps([{"spec": "먼저", "deps": [1]}, {"spec": "나중"}]))
        )
        self.assertEqual(code, 2)
        self.assertEqual(orc.task_list(self.root, run_id), [], "거절한 그래프의 일감이 남았다")

    def test_a_unit_without_a_spec_is_refused(self):
        run_id = self.start_run()
        self.assertEqual(self.quiet(lambda: siege_act.run_plan(run_id, json.dumps([{"agent": "asgard-thor"}]))), 2)
        self.assertEqual(self.quiet(lambda: siege_act.run_plan(run_id, "그냥 글자")), 2)

    def test_add_grafts_one_unit_with_its_own_verifier(self):
        run_id = self.start_run()
        grafted = self.json_of(
            lambda: siege_act.run_add(run_id, "빠뜨린 단위", agent="asgard-eitri", verify=True, json_out=True)
        )
        self.assertEqual(grafted["agent"], "asgard-eitri")
        self.assertEqual(grafted["verify"]["deps"], [grafted["id"]])
        self.assertEqual(grafted["verify"]["kind"], "verify")


class TestTheDomainRefusalsSurviveTheCommandLayer(ActBase):
    """도메인이 지키는 계약을 표면이 무르게 만들지 않는다. 전부 종료 코드 2 다."""

    def test_a_finished_report_cannot_sneak_in_through_send(self):
        run_id = self.start_run()
        self.assertEqual(self.quiet(lambda: siege_act.run_send(run_id, "worker_done", body="우회")), 2)

    def test_a_completed_task_cannot_be_revived(self):
        run_id = self.start_run()
        task_id = self.add_task(run_id, "끝난 일감")
        dispatch = self.json_of(lambda: siege_act.run_open(task_id, json_out=True))
        self.quiet(lambda: siege_act.run_done(dispatch["id"], "succeeded", run_id=run_id, task_id=task_id))
        self.assertEqual(self.quiet(lambda: siege_act.run_force(task_id, "ready")), 2)

    def test_a_dependency_outside_the_run_is_refused(self):
        run_id = self.start_run()
        self.assertEqual(self.quiet(lambda: siege_act.run_add(run_id, "일감", deps=["task_nope"])), 2)

    def test_a_closed_run_takes_no_more_work(self):
        run_id = self.start_run()
        self.assertEqual(self.quiet(lambda: siege_act.run_close_cmd(run_id)), 0)
        self.assertEqual(self.quiet(lambda: siege_act.run_add(run_id, "늦은 일감")), 2)
        self.assertEqual(self.quiet(lambda: siege_act.run_gate(run_id, "늦은 질문")), 2)

    def test_a_report_meant_for_another_task_is_refused(self):
        """죽은 재시도의 뒤늦은 완료가 다른 일감을 끝낸 것으로 만들면 안 된다."""
        run_id = self.start_run()
        mine = self.add_task(run_id, "내 일감")
        other = self.add_task(run_id, "남의 일감")
        dispatch = self.json_of(lambda: siege_act.run_open(mine, json_out=True))
        self.assertEqual(
            self.quiet(lambda: siege_act.run_done(dispatch["id"], "succeeded", run_id=run_id, task_id=other)), 2
        )
        self.assertEqual(self.task_of(other)["status"], "ready", "남의 일감이 접혔다")

    def test_binding_the_same_quest_twice_reuses_one_run(self):
        """두 번째 호출이 Run 을 또 만들면 같은 퀘스트의 일감과 우편함이 둘로 갈린다."""
        first = self.json_of(lambda: siege_act.run_start("목표", quest_id="q-1", json_out=True))
        second = self.json_of(lambda: siege_act.run_start("목표", quest_id="q-1", json_out=True))
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"], "이어 쓴 Run 을 새로 연 것처럼 보고한다")
        self.assertEqual(len(orc.run_list(self.root)), 1)

    def test_a_bad_shape_never_opens_a_run(self):
        self.assertEqual(self.quiet(lambda: siege_act.run_start("목표", shape="스쿼드")), 2)
        self.assertEqual(orc.run_list(self.root), [], "거절한 명령이 Run 을 남겼다")


class TestAnAgentWithNoHandleStillReports(ActBase):
    """손잡이를 못 받은 배차가 자기 실패를 적을 수 있는가.

    호스트 모드에서 배차받은 에이전트에게 dispatch id 가 오는 길은 없다 — 장부에 세우는 호출은
    답을 안 기다리는 자식 프로세스라 그 id 가 돌아올 자리가 없다. 그래서 자기가 아는 둘,
    퀘스트와 이름으로 자기 시도를 찾는다. 이 갈래가 막히면 실패한 배차가 전부 성공으로 접힌다.
    """

    def test_quest_and_agent_settle_the_attempt_the_hook_opened(self):
        orc.note_agent(self.root, "q-boot", "asgard-thor", spec="백엔드 표면")
        code = self.quiet(
            lambda: siege_act.run_done("", "failed", quest_id="q-boot", agent="asgard-thor", body="스키마가 없어요")
        )
        self.assertEqual(code, 0)
        run_id = orc.run_list(self.root)[0]["id"]
        self.assertEqual(orc.live_agents(self.root, run_id), [], "보고한 시도가 아직 도는 중이다")
        history = [d for task in orc.task_list(self.root, run_id) for d in orc.dispatch_history(self.root, task["id"])]
        self.assertEqual([d["outcome"] for d in history], ["failed"])

    def test_a_report_with_neither_a_handle_nor_a_name_is_refused(self):
        self.assertEqual(self.quiet(lambda: siege_act.run_done("", "failed")), 2)
        self.assertEqual(self.quiet(lambda: siege_act.run_done("", "failed", quest_id="q-boot")), 2)

    def test_a_quest_with_no_live_attempt_is_refused_rather_than_invented(self):
        orc.note_agent(self.root, "q-boot", "asgard-thor", spec="백엔드 표면")
        self.assertEqual(
            self.quiet(lambda: siege_act.run_done("", "failed", quest_id="q-boot", agent="asgard-freyja")), 2
        )

    def test_the_stop_hook_does_not_reopen_what_the_agent_already_reported(self):
        """자기 보고 뒤에 오는 종료의 heal 은 아무것도 세우면 안 된다.

        접을 것이 없는 이유가 둘이고 처방이 정반대다. 유실이면 세우고 접어야 장부가 사실과 맞고,
        자기 보고면 그대로 두어야 한다 — 세우면 방금 `failed` 로 접힌 시도 옆에 `succeeded` 가
        새로 서고, 코디네이터가 읽는 마지막 줄이 그 성공이 된다.
        """
        orc.note_agent(self.root, "q-boot", "asgard-thor", spec="백엔드 표면")
        self.quiet(lambda: siege_act.run_done("", "failed", quest_id="q-boot", agent="asgard-thor", body="막혔어요"))
        self.assertEqual(self.quiet(lambda: siege_act.run_unnote("q-boot", "asgard-thor", heal=True)), 0)
        run_id = orc.run_list(self.root)[0]["id"]
        history = [d for task in orc.task_list(self.root, run_id) for d in orc.dispatch_history(self.root, task["id"])]
        self.assertEqual([d["outcome"] for d in history], ["failed"], "종료의 heal 이 성공 시도를 새로 세웠다")

    def test_a_genuinely_lost_opening_is_still_healed(self):
        """자기 보고가 없으면 heal 은 하던 대로 세우고 접는다 — 좁힌 것은 그 한 경우뿐이다."""
        self.assertEqual(self.quiet(lambda: siege_act.run_unnote("q-lost", "asgard-thinker", heal=True)), 0)
        run_id = orc.run_list(self.root)[0]["id"]
        history = [d for task in orc.task_list(self.root, run_id) for d in orc.dispatch_history(self.root, task["id"])]
        self.assertEqual([d["outcome"] for d in history], ["succeeded"], "유실된 여는 기록을 아무도 안 메웠다")

    def test_one_self_report_hides_exactly_one_stop(self):
        """한 보고가 가리는 종료는 하나다 — 이름만 보고 판정하면 그 뒤의 진짜 유실이 영영 안 메워진다.

        같은 에이전트를 두 번 부르는 것은 재시도가 아니라 일감 둘이다(`roster` 모듈 설명). 첫
        배차가 실패를 스스로 보고하고 둘째 배차의 여는 기록이 유실되면, 그 둘째가 장부에서 통째로
        빠진다 — 코디네이터에게는 돌지 않은 것으로 보인다.
        """
        orc.note_agent(self.root, "q-boot", "asgard-thor", spec="첫 표면")
        self.quiet(lambda: siege_act.run_done("", "failed", quest_id="q-boot", agent="asgard-thor", body="막혔어요"))
        self.assertEqual(self.quiet(lambda: siege_act.run_unnote("q-boot", "asgard-thor", heal=True)), 0)
        # 둘째 배차 — 여는 기록이 유실된 채 종료만 닿는다.
        self.assertEqual(self.quiet(lambda: siege_act.run_unnote("q-boot", "asgard-thor", heal=True)), 0)
        run_id = orc.run_list(self.root)[0]["id"]
        history = [d for task in orc.task_list(self.root, run_id) for d in orc.dispatch_history(self.root, task["id"])]
        self.assertEqual(
            sorted(d["outcome"] for d in history), ["failed", "succeeded"], "두 번째 배차가 장부에서 빠졌다"
        )

    def test_the_stop_hook_carries_a_failure_the_role_recorded(self):
        """훅이 접을 때도 결과는 넘어간다 — 기본은 succeeded 이고, 그것만이 아니어야 한다."""
        orc.note_agent(self.root, "q-boot", "asgard-worker", spec="단위 하나")
        self.assertEqual(
            self.quiet(
                lambda: siege_act.run_unnote("q-boot", "asgard-worker", outcome="failed", summary="못 닿았어요")
            ),
            0,
        )
        run_id = orc.run_list(self.root)[0]["id"]
        history = [d for task in orc.task_list(self.root, run_id) for d in orc.dispatch_history(self.root, task["id"])]
        self.assertEqual([d["outcome"] for d in history], ["failed"])


class TestTheAckHintCarriesTheName(ActBase):
    """안내문은 사람이 그대로 복사한다 — 이름이 빠지면 그 복사가 남의 메일까지 접는다."""

    def hint(self, run_id: str, **kwargs) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            siege_act.run_check(run_id, **kwargs)
        return buffer.getvalue()

    def test_a_named_check_is_told_to_ack_with_that_name(self):
        run_id = self.start_run()
        orc.send(self.root, run_id, "status", subject="앨리스 앞", recipient="alice")
        self.assertIn("--as alice --ack", self.hint(run_id, recipient="alice"))

    def test_an_unnamed_check_is_told_the_plain_form(self):
        run_id = self.start_run()
        orc.send(self.root, run_id, "status", subject="주인 없음")
        shown = self.hint(run_id)
        self.assertIn("--ack", shown)
        self.assertNotIn("--as", shown)


class TestRootResolution(ActBase):
    """모는 절반도 읽는 절반과 같은 뿌리를 본다 — 갈리면 하위 디렉터리의 배차가 다른 장부로 간다."""

    def test_a_subdirectory_writes_into_the_project_ledger(self):
        run_id = self.start_run()
        deep = os.path.join(self.root, "src", "asgard")
        os.makedirs(deep, exist_ok=True)
        os.chdir(deep)
        task_id = self.add_task(run_id, "하위에서 만든 일감")
        self.assertIsNotNone(orc.task_show(self.root, task_id), "일감이 프로젝트 장부에 안 들어갔다")
        self.assertFalse(os.path.exists(os.path.join(deep, ".asgard")), "하위 디렉터리에 장부가 새로 생겼다")


class TestTheHostModesFillTheLedgerOnTheirOwn(ActBase):
    """Claude Code·Cursor·Codex 의 티켓 전이가 장부를 채운다.

    세 모드에는 네이티브 Trinity 루프가 없다. `hooks/quest_log.py` 의 티켓 런타임이 유일한
    기록 경로이고, 그것이 안 적으면 세 모드에서 `asgard siege` 는 언제나 비어 있다.
    """

    def setUp(self) -> None:
        super().setUp()
        from asgard.hooks import quest_log

        self.quest_log = quest_log
        # 신원은 시험이 세운다 — 러너에는 전역 git 설정이 없어서 commit 이 exit 128 로 죽는다.
        for pair in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", self.root, "config", *pair], check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "seed"], cwd=self.root, check=True)
        # 티켓 전이는 장부를 임포트가 아니라 CLI 프로세스로 적는다 — 배포 인터프리터에
        # asgard 가 없기 때문이다. PATH 의 `asgard` 를 이 저장소의 코드로 세운다.
        # 그 조회(`asgard_hooklib.siege.ledger_call` 의 `shutil.which`)가 이 프로세스 안에서
        # 일어나므로 하위 프로세스에 env= 로 넘길 수가 없다. 대신 범위가 닫히는 patch.dict 로
        # 이 시험이 도는 동안만 바꾼다 — 예외로 빠져나가도 원래 값이 그대로 돌아온다.
        bin_dir = os.path.dirname(deploy_cli(os.path.join(self.root, "bin")))
        patched = mock.patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ.get("PATH", "")})
        patched.start()
        self.addCleanup(patched.stop)

    def mirrored(self, unit: str) -> str:
        """claim 의 장부 옮김이 **끝날 때까지** 기다린 뒤 그 Run id.

        `siege_act.run_mirror` 는 Run 열기 → 단위 Task 세우기 → 시도 열기를 이 순서로 하고
        셋을 각각 따로 커밋한다. 그 전부를 떼어 낸 프로세스가 적는다. 그래서 Task 개수만 보고
        돌아오면 마지막 걸음(`open_dispatch`)이 아직 안 끝난 장부를 단언에 넘긴다 — 26-08-12
        실측으로 12회 중 3회가 그 창에 떨어졌고, 창의 폭은 1~3ms 다. 기계가 바쁘면 그 창이
        넓어져 100ms 간격의 폴링이 안쪽을 집는다. 그래서 마지막 걸음을 기다린다.

        `until` 의 상한은 이 결함과 무관하다 — 창이 밀리초 단위이므로 상한을 올려도 중간
        상태를 집는 것은 그대로다. 그 상한을 30초에서 120초로 올린 것은 별개의 결함 때문이다
        (`hookscaffold.until` 의 독스트링에 그 실측이 적혀 있다).
        """
        until(lambda: bool(orc.run_list(self.root)))
        runs = orc.run_list(self.root)
        self.assertEqual(len(runs), 1, "티켓 전이가 배차 장부에 Run 을 안 열었다")
        self.assertTrue(
            until(lambda: (orc.task_for_unit(self.root, runs[0]["id"], unit) or {}).get("status") == "dispatched"),
            f"claim 의 장부 옮김이 시도를 안 열었다 — {unit}",
        )
        return runs[0]["id"]

    def tool(self, *args: str, stdin: str = "") -> dict:
        """호스트 모드의 에이전트가 실제로 치는 경로 — `quest-log.py` 를 프로세스로 부른다.

        퀘스트 로그는 첫 이벤트에 실행 신원을 요구하므로(`ledger_integrity`), 이벤트를 손으로
        적으면 무결성 검사에 걸린다. 진짜 입구로 들어가야 세 모드와 같은 것을 재게 된다.
        """
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        env = dict(os.environ, PYTHONPATH=os.path.realpath(src), CLAUDE_SESSION_ID="host-mode")
        proc = subprocess.run(
            [sys.executable, "-m", "asgard.hooks.quest_log", *args],
            cwd=self.root,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {"code": proc.returncode, "out": proc.stdout, "err": proc.stderr}

    def open_quest(self, qid: str, request: str = "결제 모듈 손보기") -> None:
        result = self.tool("open", qid, "--criteria", "결제가 돌아요", "--request", request)
        self.assertEqual(result["code"], 0, result["err"])

    def declare_units(self, qid: str, units: list[dict]) -> None:
        """Thinker 가 배정 단위를 todo 로 선언하는 자리 — Mode B 계약의 첫 걸음이다."""
        for unit in units:
            body = json.dumps({"role": "thinker", "event": "ticket", "ticket_status": "todo", **unit})
            result = self.tool("append", qid, stdin=body)
            self.assertEqual(result["code"], 0, result["err"])

    def ticket(self, qid: str, cmd: str, **kwargs):
        return self.quest_log.ticket_runtime(self.root, qid, cmd, session="host-mode", **kwargs)

    def test_a_claim_and_finish_build_the_graph_and_settle_it(self):
        qid = "q-host"
        self.open_quest(qid)
        self.declare_units(
            qid,
            [
                {"unit": "u-schema", "subtask": "스키마 옮기기"},
                {"unit": "u-api", "subtask": "API 붙이기", "access": ["u-schema"]},
            ],
        )
        code, claimed = self.ticket(qid, "ticket-claim", unit="u-schema", worker="w-1")
        self.assertEqual(code, 0, claimed)

        run_id = self.mirrored("u-schema")
        self.assertEqual(orc.run_list(self.root)[0]["quest_id"], qid, "Run 이 퀘스트에 안 묶였다")

        schema = self.unit_of(run_id, "u-schema")
        api = self.unit_of(run_id, "u-api")  # 아직 안 잡은 단위도 DAG 에 서야 의존을 그린다
        self.assertEqual(api["deps"], [schema["id"]], "access 가 의존으로 안 옮겨졌다")
        self.assertEqual(schema["status"], "dispatched")
        self.assertEqual(api["status"], "pending")

        code, _ = self.ticket(qid, "ticket-finish", unit="u-schema", claim_token=claimed["claim_token"], status="done")
        self.assertEqual(code, 0)
        until(lambda: self.task_of(schema["id"])["status"] == "completed")
        self.assertEqual(self.task_of(schema["id"])["status"], "completed")
        self.assertEqual(self.task_of(api["id"])["status"], "ready", "앞 단위가 끝났는데 뒤가 안 풀렸다")
        self.assertEqual(
            [m["type"] for m in orc.inbox(self.root, run_id) if m["type"] == "worker_done"],
            ["worker_done"],
            "완료 보고가 코디네이터 우편함에 안 들어갔다",
        )

    def test_the_run_carries_the_quest_objective(self):
        """Run 목록이 읽히려면 목표가 있어야 한다 — 퀘스트의 요청문이 그 자리에 온다."""
        qid = "q-goal"
        self.open_quest(qid, request="결제 모듈 손보기")
        self.declare_units(qid, [{"unit": "u-1", "subtask": "하나"}])
        self.ticket(qid, "ticket-claim", unit="u-1", worker="w-1")
        self.mirrored("u-1")
        self.assertEqual(orc.run_list(self.root)[0]["objective"], "결제 모듈 손보기")

    def test_a_failed_unit_comes_back_ready_for_the_next_attempt(self):
        qid = "q-retry"
        self.open_quest(qid)
        self.declare_units(qid, [{"unit": "u-1", "subtask": "붙지 않는 일감"}])
        _, claimed = self.ticket(qid, "ticket-claim", unit="u-1", worker="w-1")
        run_id = self.mirrored("u-1")
        self.ticket(qid, "ticket-finish", unit="u-1", claim_token=claimed["claim_token"], status="failed")
        until(lambda: self.unit_of(run_id, "u-1")["status"] == "ready")
        task = self.unit_of(run_id, "u-1")
        self.assertEqual(task["status"], "ready", "실패한 시도가 재배차를 못 받는다")
        self.assertEqual(len(orc.dispatch_history(self.root, task["id"])), 1)

    def test_the_native_loop_keeps_the_ledger_to_itself(self):
        """네이티브 모드에서는 bifrost 가 이미 적는다 — 훅이 또 적으면 한 Task 를 둘이 연다."""
        qid = "q-native"
        self.open_quest(qid)
        self.declare_units(qid, [{"unit": "u-1", "subtask": "하나"}])
        code, claimed = self.ticket(qid, "ticket-claim", unit="u-1", worker="native:sid-1:u-1")
        self.assertEqual(code, 0, claimed)
        until(lambda: bool(orc.run_list(self.root)), timeout=3.0)
        self.assertEqual(orc.run_list(self.root), [], "네이티브 claim 이 훅에서도 장부를 열었다")

    def test_the_native_worker_prefix_is_the_one_ticket_lease_sends(self):
        """판정이 기대는 문자열과 실제로 넘어오는 문자열을 한자리에서 붙든다.

        `ticket_lease._claim` 이 접두사를 바꾸면 훅은 네이티브 배차를 호스트 배차로 잘못 읽고,
        그때부터 배차가 조용히 둘씩 열린다. 그 침묵을 여기서 깬다.
        """
        import inspect

        from asgard_hooklib import tickets as tickets_lib

        from asgard.agent.heimdall import ticket_lease

        source = inspect.getsource(ticket_lease.TicketLease._claim)
        self.assertIn('f"native:', source, "ticket_lease 가 더 이상 native: 접두사를 안 보낸다")
        self.assertTrue(tickets_lib._native_loop_owns_the_ledger("native:sid:u-1"))
        self.assertFalse(tickets_lib._native_loop_owns_the_ledger("w-1"))
        self.assertFalse(tickets_lib._native_loop_owns_the_ledger(None))

    def test_a_broken_ledger_never_costs_a_ticket_transition(self):
        """장부는 파생이다 — 못 적더라도 정본의 전이는 그대로 성공해야 한다."""
        qid = "q-failopen"
        self.open_quest(qid)
        self.declare_units(qid, [{"unit": "u-1", "subtask": "하나"}])
        # 장부 자리에 디렉터리를 둔다. SQLite 는 파일을 못 열고, 그 실패가 티켓을 막으면 안 된다.
        os.makedirs(orc.db_path(self.root), exist_ok=True)
        code, claimed = self.ticket(qid, "ticket-claim", unit="u-1", worker="w-1")
        self.assertEqual(code, 0, f"장부가 안 열린다고 티켓 claim 이 실패했다: {claimed}")
        self.assertIn("claim_token", claimed)


if __name__ == "__main__":
    unittest.main()
