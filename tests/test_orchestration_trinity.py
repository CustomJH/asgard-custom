#!/usr/bin/env python3
"""Trinity × Bifrost — 순환이 배차 장부를 **통해** 도는지 확인한다.

tests/test_heimdall.py 의 FakeSession/FakeHeimdall 하네스를 그대로 쓴다 (API 호출 0). 여기서
확인하는 것은 Trinity 의 판정이 아니라 그 판정이 장부에 남는가와, 워커의 질문이 실제로 답을
받는가다.

지키는 계약:
  · 퀘스트 하나 = 열린 Run 하나. 역할 턴마다 Task + Dispatch 가 생기고 앞 턴이 의존이 된다.
  · 형상(single/graph/squad)이 Run 에 적히고, 계획이 배정 단위를 내면 graph 로 갱신된다.
  · 워커의 `ask_coordinator` 는 항상 답을 받는다 — 코디네이터 고리가 답하거나, 못 하면
    "가정을 명시하고 진행하라" 가 돌아간다. 침묵으로 끝나는 갈래가 없다.
  · 장부가 죽어도 순환은 돈다 (fail-open).

실행: uv run pytest tests/test_orchestration_trinity.py
"""

import json
import os
import unittest
from unittest import mock

from test_heimdall import CLS_WRITE, Base, FakeHeimdall, FakeSession, verifier, worker

from asgard import orchestration as orc
from asgard.agent.heimdall.bifrost import BifrostLedger
from asgard.agent.session import SessionResult


def runs(root: str) -> list[dict]:
    return orc.run_list(root)


def only_run(root: str) -> dict:
    found = runs(root)
    assert len(found) == 1, f"Run 이 {len(found)}개 — 퀘스트 하나에 Run 하나여야 한다"
    return found[0]


class TestQuestBindsARun(Base):
    def test_quest_opens_exactly_one_run(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        run = only_run(self.root)
        self.assertTrue(run["quest_id"])
        self.assertEqual(run["status"], "closed")  # DONE 턴이 닫는다

    def test_role_turns_become_a_dependency_chain(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        run = only_run(self.root)
        tasks = orc.task_list(self.root, run["id"])
        roles = [t["unit_id"] for t in tasks]
        self.assertIn("WORKER", roles)
        self.assertIn("VERIFIER", roles)
        # 두 번째 턴부터는 직전 턴이 의존이다 — 순환의 순서가 DAG 로 남는다.
        chained = [t for t in tasks if t["deps"]]
        self.assertTrue(chained, "역할 턴 어디에도 의존이 없다")
        for task in chained:
            self.assertTrue(set(task["deps"]) <= {t["id"] for t in tasks})

    def test_each_turn_records_a_settled_dispatch(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        run = only_run(self.root)
        for task in orc.task_list(self.root, run["id"]):
            attempts = orc.dispatch_history(self.root, task["id"])
            self.assertTrue(attempts, f"{task['unit_id']} 턴에 Dispatch 가 없다")
            self.assertEqual(attempts[-1]["state"], "settled")
            self.assertEqual(attempts[-1]["outcome"], "succeeded")

    def test_dispatch_records_the_model_that_ran_the_turn(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        run = only_run(self.root)
        models = {orc.dispatch_history(self.root, t["id"])[-1]["model"] for t in orc.task_list(self.root, run["id"])}
        self.assertTrue(any("claude-x" in m for m in models), f"턴 모델이 안 남았다: {models}")


class TestShapeIsRecorded(Base):
    def test_single_hand_quest_is_shaped_single(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertEqual(only_run(self.root)["shape"], "single")

    def test_shape_carries_its_reason(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertTrue(only_run(self.root)["shape_why"])


class TestSpecialistsReachTheShape(Base):
    """전문 영역이 둘 이상 걸리면 squad 로 적히는가.

    형상 판정에는 전문가 목록 입력이 처음부터 있었지만 아무도 그 값을 넘기지 않아 squad 가
    한 번도 안 골라지고 있었다. 여기서 고정하는 것은 **매칭 결과가 형상까지 도달하는가** 다 —
    어느 스킬이 매칭되는가는 스킬 레지스트리의 계약이고 이 테스트의 관심이 아니다.
    """

    # thor(인증 API)와 freyja(화면 UI) 둘을 함께 건드리는 요청. 한쪽만 걸리는 요청과 대조된다.
    CROSS = "로그인 화면 UI 를 다시 그리고 인증 API 엔드포인트도 고쳐줘"
    SINGLE = "결제 API 를 만들어줘"

    def _run(self, request: str) -> dict:
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle(request)
        return only_run(self.root)

    def test_two_domains_make_a_squad(self):
        run = self._run(self.CROSS)
        self.assertEqual(run["shape"], "squad")
        self.assertIn("freyja", run["shape_why"])  # 사유가 어느 영역인지 밝힌다

    def test_one_domain_stays_single(self):
        self.assertEqual(self._run(self.SINGLE)["shape"], "single")

    def _ledger(self, request: str) -> BifrostLedger:
        """장부 하나만 세운다 — 아래 셋은 순환이 아니라 장부의 계약을 재는 것이라 세션이 없다."""
        return BifrostLedger(FakeHeimdall(self.root, []), "q-shape", request)

    def test_the_ledger_measures_the_matcher_once(self):
        """형상은 계획 전후로 두 번 골라지는데 과업 텍스트는 그 사이에 안 변한다.

        매처 한 번이 스킬 리졸버를 세 번(thor·freyja·eitri) 돌리므로 재계산은 그냥 낭비다.
        재는 것은 장부의 몫뿐이다 — Worker 착수 힌트도 같은 매처를 부르지만 그건 다른 소비처다.
        """
        import asgard.agent.heimdall.roles as roles

        ledger = self._ledger(self.CROSS)
        with mock.patch.object(roles, "_delivery_matches", wraps=roles._delivery_matches) as spy:
            self.assertEqual(ledger.choose_shape(CLS_WRITE)["shape"], "squad")
            self.assertEqual(ledger.choose_shape(CLS_WRITE)["shape"], "squad")
        self.assertEqual(spy.call_count, 1, f"매처를 {spy.call_count}번 돌렸다")

    def test_an_explicit_empty_list_turns_matching_off(self):
        """빈 목록을 넘기는 것과 안 넘기는 것은 다른 뜻이다 — 안 넘기면 장부가 직접 잰다."""
        self.assertEqual(self._ledger(self.CROSS).choose_shape(CLS_WRITE, specialists=[])["shape"], "single")

    def test_a_dead_matcher_falls_back_to_no_specialists(self):
        """매처가 죽어도 형상 선택은 답을 낸다 — squad 만 못 고를 뿐이다."""
        import asgard.agent.heimdall.roles as roles

        ledger = self._ledger(self.CROSS)
        with mock.patch.object(roles, "_delivery_matches", side_effect=RuntimeError("registry gone")):
            self.assertEqual(ledger.choose_shape(CLS_WRITE)["shape"], "single")


class TestWorkerCanAsk(Base):
    """워커의 질문이 실제로 답을 받는가 — 이 계층의 유일한 왕복."""

    def _asking_worker(self, question: str) -> FakeSession:
        session = worker({"w1.txt": "x\n"}, self.root)
        session.tool_script = [("ask_coordinator", {"question": question, "tried": "리포를 읽었다"})]
        return session

    def test_scope_question_is_answered_without_a_model_call(self):
        """규율이 이미 정해 둔 답은 모델을 안 부른다 — 결정론 경로."""
        asking = self._asking_worker("다른 단위의 파일을 만져도 되나?")
        h = FakeHeimdall(self.root, [asking, verifier("PASS")], cls=CLS_WRITE)
        with mock.patch.object(FakeHeimdall, "_complete_text", side_effect=AssertionError("모델을 불렀다")):
            h.handle("w1.txt 만들어")
        name, answer = asking.tool_results[0]
        self.assertEqual(name, "ask_coordinator")
        self.assertIn("아니다", answer)

    def test_open_question_is_answered_by_the_coordinator(self):
        asking = self._asking_worker("포트 기본값을 8080 으로 둘까 3000 으로 둘까?")
        h = FakeHeimdall(self.root, [asking, verifier("PASS")], cls=CLS_WRITE)
        with mock.patch.object(FakeHeimdall, "_complete_text", return_value="8080 으로 둬라."):
            h.handle("w1.txt 만들어")
        self.assertEqual(asking.tool_results[0][1], "8080 으로 둬라.")

    def test_a_question_is_never_left_silent(self):
        """코디네이터 모델이 죽어도 워커는 답을 받는다 — 침묵으로 끝나는 갈래가 없다."""
        asking = self._asking_worker("이 값을 어떻게 정할까?")
        h = FakeHeimdall(self.root, [asking, verifier("PASS")], cls=CLS_WRITE)
        with mock.patch.object(FakeHeimdall, "_complete_text", side_effect=RuntimeError("provider down")):
            h.handle("w1.txt 만들어")
        answer = asking.tool_results[0][1]
        self.assertIn("가정:", answer)

    def test_empty_question_is_rejected_without_a_round_trip(self):
        session = worker({"w1.txt": "x\n"}, self.root)
        session.tool_script = [("ask_coordinator", {"question": "  ", "tried": ""})]
        h = FakeHeimdall(self.root, [session, verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertIn("비어 있다", session.tool_results[0][1])

    def test_answered_question_is_recorded_in_the_run(self):
        asking = self._asking_worker("다른 단위의 파일을 만져도 되나?")
        h = FakeHeimdall(self.root, [asking, verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        run = only_run(self.root)
        questions = [m for m in orc.inbox(self.root, run["id"], limit=50) if m["type"] == "question"]
        self.assertEqual(len(questions), 1)
        self.assertIsNotNone(questions[0]["answered_at"])
        self.assertEqual(orc.pending_questions(self.root, run["id"]), [])


class TestLedgerResumes(Base):
    """같은 퀘스트를 이어 받았을 때 장부가 DB 에서 복원되는가 (감사 높음-1).

    복원이 없으면 중복 방지가 프로세스 메모리에만 있어, 재개된 퀘스트는 배정 단위 Task 를
    두 벌 갖는다. 그러면 시도 횟수가 두 Task 로 갈려 회로 차단이 영영 안 걸리고, 두 번째
    묶음은 의존 없는 별개 그래프가 되어 "순환의 순서" 라는 이 표의 존재 이유가 무너진다.
    """

    UNITS = [
        {"id": 1, "subtask": "a 만들기", "files": ["a.txt"], "criteria": ["a"], "access": []},
        {"id": 2, "subtask": "b 만들기", "files": ["b.txt"], "criteria": ["b"], "access": [1]},
    ]

    def _ledger(self) -> BifrostLedger:
        return BifrostLedger(FakeHeimdall(self.root, []), "q-resume", "이어 받는 퀘스트")

    def test_units_are_not_duplicated_across_processes(self):
        first = self._ledger()
        first.open_turn("WORKER", "구현")
        first.register_units(self.UNITS)

        second = self._ledger()  # 프로세스 재시작 — 같은 qid 로 같은 Run 에 다시 붙는다
        self.assertEqual(second.run_id, first.run_id, "재개인데 Run 이 갈렸다")
        second.register_units(self.UNITS)

        by_unit: dict[str, int] = {}
        for task in orc.task_list(self.root, first.run_id):
            by_unit[task["unit_id"]] = by_unit.get(task["unit_id"], 0) + 1
        self.assertEqual(by_unit.get("1"), 1, f"배정 단위가 두 벌이 됐다: {by_unit}")
        self.assertEqual(by_unit.get("2"), 1, f"배정 단위가 두 벌이 됐다: {by_unit}")
        self.assertEqual(by_unit.get("WORKER"), 1)

    def test_attempts_keep_accumulating_on_the_same_task(self):
        """재개 후에도 같은 Task 에 시도가 쌓여야 회로 차단이 산다."""
        first = self._ledger()
        first.open_turn("WORKER", "구현")
        first.register_units(self.UNITS)
        first.open_unit(self.UNITS[0])
        first.settle_unit(self.UNITS[0], "failed", summary="죽었다")

        second = self._ledger()
        second.register_units(self.UNITS)
        dispatch_id = second.open_unit(self.UNITS[0])
        self.assertTrue(dispatch_id, "재개한 장부가 단위를 못 열었다")
        task = next(t for t in orc.task_list(self.root, second.run_id) if t["unit_id"] == "1")
        self.assertEqual(task["attempts"], 2, "시도 횟수가 갈렸다")

    def test_a_dead_unit_dispatch_is_reclaimed_on_resume(self):
        """정산 없이 사라진 단위 시도가 회수되어 재개가 그 단위를 다시 연다."""
        first = self._ledger()
        first.open_turn("WORKER", "구현")
        first.register_units(self.UNITS)
        self.assertTrue(first.open_unit(self.UNITS[0]))  # 여기서 프로세스가 죽는다

        second = self._ledger()
        second.register_units(self.UNITS)
        self.assertTrue(second.open_unit(self.UNITS[0]), "죽은 시도가 자리를 막아 재개가 못 열었다")

    def test_a_failed_turn_does_not_block_the_next_one(self):
        """실패한 역할 턴을 의존으로 달면 다음 턴이 blocked 이 되어 순환의 수리 전이가 막힌다."""
        ledger = self._ledger()
        for _ in range(3):  # 회로가 끊길 때까지 같은 역할이 실패한다
            dispatch = ledger.open_turn("WORKER", "구현")
            ledger.settle_turn(dispatch, "failed", summary="죽었다")
        verifier = ledger.open_turn("VERIFIER", "판정")
        self.assertTrue(verifier, "선행 턴이 실패했다고 다음 턴이 배차를 못 받았다")


class TestFailureIsRecorded(Base):
    def test_a_turn_that_dies_settles_as_failed(self):
        """세션이 죽으면 그 시도는 failed 로 남는다 — handle() 은 예외를 보고로 바꿔 삼킨다."""
        boom = FakeSession(SessionResult(text="", stop_reason="end_turn"), label="worker")
        h = FakeHeimdall(self.root, [boom], cls=CLS_WRITE)
        # run 을 직접 대입하면 클래스 메서드를 인스턴스 속성으로 덮는다. patch.object 는
        # 같은 일을 하면서 테스트가 끝날 때 원래 메서드를 되돌린다.
        with mock.patch.object(boom, "run", side_effect=RuntimeError("worker died")):
            out = h.handle("w1.txt 만들어")
        self.assertIn("Trinity", out)
        run = only_run(self.root)
        states = [
            orc.dispatch_history(self.root, t["id"])[-1]["state"]
            for t in orc.task_list(self.root, run["id"])
            if orc.dispatch_history(self.root, t["id"])
        ]
        self.assertIn("failed", states)

    def test_the_run_stays_open_when_the_quest_does(self):
        """중단된 퀘스트의 Run 은 안 닫힌다 — 닫힌 Run 은 '끝났다'는 뜻이다."""
        boom = FakeSession(SessionResult(text="", stop_reason="end_turn"), label="worker")
        h = FakeHeimdall(self.root, [boom], cls=CLS_WRITE)
        with mock.patch.object(boom, "run", side_effect=RuntimeError("worker died")):
            h.handle("w1.txt 만들어")
        self.assertEqual(only_run(self.root)["status"], "open")


class TestFailOpen(Base):
    """장부가 죽어도 순환은 돈다 — 배차 기록을 얻으려고 작업을 잃지 않는다."""

    def test_quest_completes_when_the_ledger_cannot_open(self):
        with mock.patch("asgard.agent.heimdall.bifrost.run_bind", side_effect=RuntimeError("db gone")):
            h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
            out = h.handle("w1.txt 만들어")
        from asgard.i18n import t

        self.assertIn(t("report_done"), out)
        self.assertTrue(os.path.exists(os.path.join(self.root, "w1.txt")))

    def test_quest_completes_when_task_creation_fails_midway(self):
        with mock.patch("asgard.agent.heimdall.bifrost.task_create", side_effect=RuntimeError("db locked")):
            h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
            out = h.handle("w1.txt 만들어")
        from asgard.i18n import t

        self.assertIn(t("report_done"), out)


class TestWaveUnitsBecomeTasks(Base):
    """배정 단위가 Task 가 되고, 계획이 선언한 `access` 가 그대로 의존이 된다.

    단위 1·2 는 독립이고 3 이 둘에 의존한다. 병렬 요청이 유효하려면 wave 하나에 단위가 둘
    이상이어야 하므로(`trinity._worker_turn` 의 invalid-parallel-plan 검사) 이 형상이 최소
    표본이다 — 단위가 일렬로만 의존하는 계획은 Trinity 가 병렬 계획으로 인정하지 않는다.
    """

    UNITS = {
        "units": [
            {"id": 1, "subtask": "a.txt 만들기", "files": ["a.txt"], "criteria": ["a"], "access": []},
            {"id": 2, "subtask": "b.txt 만들기", "files": ["b.txt"], "criteria": ["b"], "access": []},
            {"id": 3, "subtask": "c.txt 만들기", "files": ["c.txt"], "criteria": ["c"], "access": [1, 2]},
        ]
    }

    def _script(self) -> list[FakeSession]:
        plan = "계획.\n\n```json\n" + json.dumps(self.UNITS, ensure_ascii=False) + "\n```\n"
        return [
            FakeSession(SessionResult(text=plan, stop_reason="end_turn", commands=[]), label="thinker"),
            worker({"a.txt": "a\n"}, self.root),
            worker({"b.txt": "b\n"}, self.root),
            worker({"c.txt": "c\n"}, self.root),
            verifier("PASS"),
        ]

    def _cls(self) -> dict:
        return {**CLS_WRITE, "parallel_requested": True, "criteria": ["a.txt·b.txt·c.txt 생성"]}

    def test_units_are_registered_with_access_as_dependencies(self):
        h = FakeHeimdall(self.root, self._script(), cls=self._cls())
        h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        units = {t["unit_id"]: t for t in orc.task_list(self.root, only_run(self.root)["id"])}
        self.assertLessEqual({"1", "2", "3"}, set(units), "배정 단위가 Task 로 안 올라갔다")
        self.assertEqual(units["1"]["deps"], [])
        self.assertEqual(units["2"]["deps"], [])
        self.assertEqual(
            sorted(units["3"]["deps"]),
            sorted([units["1"]["id"], units["2"]["id"]]),
            "access=[1,2] 가 의존으로 안 옮겨졌다",
        )

    def test_unit_dispatches_settle(self):
        h = FakeHeimdall(self.root, self._script(), cls=self._cls())
        h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        units = [t for t in orc.task_list(self.root, only_run(self.root)["id"]) if t["unit_id"] in ("1", "2", "3")]
        for unit in units:
            attempts = orc.dispatch_history(self.root, unit["id"])
            self.assertTrue(attempts, f"단위 {unit['unit_id']} 에 Dispatch 가 없다")
            self.assertEqual(attempts[-1]["outcome"], "succeeded")

    def test_dependencies_survive_a_plan_that_lists_units_out_of_order(self):
        """계획이 의존 단위를 선행 단위보다 앞에 적어도 의존이 살아남는가 (감사 발견).

        목록 순서대로 만들면 단위 3 을 만들 때 1·2 가 아직 없어서 `access` 가 조용히 사라지고,
        순서가 있는 일이 전부 ready 가 되어 병렬로 돈다.
        """
        reversed_units = {"units": list(reversed(self.UNITS["units"]))}
        plan = "계획.\n\n```json\n" + json.dumps(reversed_units, ensure_ascii=False) + "\n```\n"
        script = [
            FakeSession(SessionResult(text=plan, stop_reason="end_turn", commands=[]), label="thinker"),
            worker({"a.txt": "a\n"}, self.root),
            worker({"b.txt": "b\n"}, self.root),
            worker({"c.txt": "c\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, script, cls=self._cls())
        h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        units = {t["unit_id"]: t for t in orc.task_list(self.root, only_run(self.root)["id"])}
        self.assertLessEqual({"1", "2", "3"}, set(units))
        self.assertEqual(
            sorted(units["3"]["deps"]),
            sorted([units["1"]["id"], units["2"]["id"]]),
            "목록 순서 때문에 의존이 사라졌다",
        )

    def test_graph_shape_is_recorded_once_the_plan_lands(self):
        h = FakeHeimdall(self.root, self._script(), cls=self._cls())
        h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        self.assertEqual(only_run(self.root)["shape"], "graph")


if __name__ == "__main__":
    unittest.main()
