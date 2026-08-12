#!/usr/bin/env python3
"""Trinity × Bifrost — 순환이 배차 장부를 **통해** 도는지 확인한다.

tests/test_heimdall.py 의 FakeSession/FakeHeimdall 하네스를 그대로 쓴다 (API 호출 0). 여기서
확인하는 것은 Trinity 의 판정이 아니라 그 판정이 장부에 남는가와, 워커의 질문이 실제로 답을
받는가다.

지키는 계약:
  · 퀘스트 하나 = 열린 Run 하나. 역할 턴마다 Task + Dispatch 가 생기고 앞 턴이 의존이 된다.
  · **형상이 갈래를 고른다.** direct 는 장부를 안 열고, graph 는 wave, squad 는 영역별 위임,
    single 은 손 하나다. 신호와 계획이 엇갈리면 계획이 이기고 그 사실이 Run 에 적힌다.
  · **코디네이터가 준비도를 읽는다.** `task_list(ready=True)` 로 준비된 일감만 배차하고,
    선행 의존이 안 끝난 일감은 실행자 손에 안 들어간다.
  · 워커의 `ask_coordinator` 는 항상 답을 받는다 — 코디네이터 고리가 답하거나, 못 하면
    "가정을 명시하고 진행하라" 가 돌아간다. 침묵으로 끝나는 갈래가 없다. 묻는 스레드와
    답하는 스레드는 다르다.
  · 장부가 죽어도 순환은 돈다 (fail-open). 다만 삼킨 실패는 stderr 에 한 줄 남는다.

실행: uv run pytest tests/test_orchestration_trinity.py
"""

import contextlib
import io
import json
import os
import threading
import unittest
from unittest import mock

from heimdall.harness import CLS_WRITE, Base, FakeHeimdall, FakeSession, verifier, worker

from asgard import orchestration as orc
from asgard.agent.heimdall.bifrost import BifrostLedger, CoordinatorLoop, open_ledger

# 장부 함수는 `bifrost.ledger` 가 자기 이름으로 들고 있다 — 파사드에 꽂으면 안 닿는다.
from asgard.agent.heimdall.bifrost import ledger as ledger_module
from asgard.agent.heimdall.planning import _plan_waves
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

    def test_the_asking_thread_is_not_the_answering_thread(self):
        """묻는 쪽과 답하는 쪽이 같은 스레드면 `ask_coordinator` 는 자기 답을 기다리다 안 끝난다.

        `ask` 는 답이 달릴 때까지 워커 스레드를 세워 두고, 답은 `CoordinatorLoop` 의 데몬
        스레드가 단다. 감독 고리(`supervise`)를 부른 쪽 스레드가 답까지 맡게 바꾸면 그 순간
        교착이 되므로, 두 스레드가 다르다는 사실 자체를 여기서 고정한다.
        """
        idents: dict[str, int] = {}
        original_ask = ledger_module.ask

        def spy_ask(*args, **kwargs):
            idents["asked"] = threading.get_ident()
            return original_ask(*args, **kwargs)

        def answer(self, system, user, max_tokens=400):
            idents["answered"] = threading.get_ident()
            return "8080 으로 둬라."

        asking = self._asking_worker("포트 기본값을 8080 으로 둘까 3000 으로 둘까?")
        h = FakeHeimdall(self.root, [asking, verifier("PASS")], cls=CLS_WRITE)
        with mock.patch.object(ledger_module, "ask", spy_ask):
            with mock.patch.object(FakeHeimdall, "_complete_text", answer):
                h.handle("w1.txt 만들어")
        self.assertEqual(asking.tool_results[0][1], "8080 으로 둬라.")
        self.assertIn("asked", idents)
        self.assertIn("answered", idents, "코디네이터가 답하지 않았다")
        self.assertNotEqual(idents["asked"], idents["answered"], "묻는 스레드가 자기 질문에 답했다")

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
        with mock.patch("asgard.agent.heimdall.bifrost.ledger.run_bind", side_effect=RuntimeError("db gone")):
            h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
            out = h.handle("w1.txt 만들어")
        from asgard.i18n import t

        self.assertIn(t("report_done"), out)
        self.assertTrue(os.path.exists(os.path.join(self.root, "w1.txt")))

    def test_quest_completes_when_task_creation_fails_midway(self):
        with mock.patch("asgard.agent.heimdall.bifrost.ledger.task_create", side_effect=RuntimeError("db locked")):
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


class TestLedgerRecordsTheScheduleThatRan(Base):
    """장부에 적힌 wave 와 실행자가 돌린 wave 가 같은가 — 두 일정이 갈라져 있던 자리.

    갈라짐 사례는 계약이 지목한 그대로다: 단위 1·2 사이에 `access` 가 없고 `files` 가 겹친다.
    `_plan_waves` 는 2 를 다음 wave 로 미는데, 장부가 `access` 만 의존으로 옮기면 1·2 가 같은
    묶음에 남아 `task_list(ready=True)` 가 실행자 손에 들어가지도 않을 일감을 준비됐다고 답한다.
    단위 3 은 어느 쪽과도 안 겹쳐 wave 하나에 단위 둘이 서게 한다 — 그래야 병렬 계획 검사를
    통과한다.
    """

    OVERLAP = {
        "units": [
            {"id": 1, "subtask": "shared.py 헤더", "files": ["shared.py"], "criteria": ["헤더"], "access": []},
            {"id": 2, "subtask": "shared.py 본문", "files": ["shared.py"], "criteria": ["본문"], "access": []},
            {"id": 3, "subtask": "other.py 만들기", "files": ["other.py"], "criteria": ["other"], "access": []},
        ]
    }

    def _script(self) -> list[FakeSession]:
        plan = "계획.\n\n```json\n" + json.dumps(self.OVERLAP, ensure_ascii=False) + "\n```\n"
        return [
            FakeSession(SessionResult(text=plan, stop_reason="end_turn", commands=[]), label="thinker"),
            worker({"shared.py": "# header\n"}, self.root),
            worker({"other.py": "other\n"}, self.root),
            worker({"shared.py": "# header\nbody\n"}, self.root),
            verifier("PASS"),
        ]

    def _cls(self) -> dict:
        return {**CLS_WRITE, "parallel_requested": True, "criteria": ["shared.py·other.py 갱신"]}

    def _ledger_waves(self, run_id: str) -> list[list[str]]:
        """장부가 적은 일정 — 배정 단위 Task 의 의존에서 편 wave. 묶음 안의 순서는 정렬한다."""
        tasks = [t for t in orc.task_list(self.root, run_id) if str(t["unit_id"]).isdigit()]
        label = {t["id"]: str(t["unit_id"]) for t in tasks}
        deps = {t["id"]: [d for d in t["deps"] if d in label] for t in tasks}
        return [sorted(label[tid] for tid in wave) for wave in orc.topo_waves(list(label), deps)]

    def test_file_overlap_lands_in_the_ledger_as_a_dependency(self):
        h = FakeHeimdall(self.root, self._script(), cls=self._cls())
        h.handle("shared.py 를 헤더와 본문으로 나눠 고치고 other.py 도 병렬로 만들어")
        run_id = only_run(self.root)["id"]
        executed = [sorted(str(u["id"]) for u in wave) for wave in _plan_waves(self.OVERLAP["units"], self.root)]
        self.assertEqual(executed, [["1", "3"], ["2"]], "실행 일정 자체가 예상과 다르다")
        self.assertEqual(self._ledger_waves(run_id), executed, "장부가 적은 wave 가 실행한 wave 와 다르다")

    def test_the_deferred_unit_is_not_ready_before_the_one_it_overlaps(self):
        """겹침으로 밀린 단위는 준비 묶음에 안 들어온다 — 코디네이터가 읽는 값이 그것이다."""
        ledger = BifrostLedger(FakeHeimdall(self.root, []), "q-overlap", "겹침 직렬화")
        ledger.open_turn("WORKER", "구현")
        ledger.register_units(self.OVERLAP["units"])
        ready = ledger.ready_tasks() or []
        self.assertEqual(sorted(str(t["unit_id"]) for t in ready), ["1", "3"], "겹친 단위 2 가 준비됐다고 나온다")


UNIT_PLAN = {
    "units": [
        {"id": 1, "subtask": "a.txt 만들기", "files": ["a.txt"], "criteria": ["a"], "access": []},
        {"id": 2, "subtask": "b.txt 만들기", "files": ["b.txt"], "criteria": ["b"], "access": []},
        {"id": 3, "subtask": "c.txt 만들기", "files": ["c.txt"], "criteria": ["c"], "access": [1, 2]},
    ]
}


def plan_script(root: str) -> list[FakeSession]:
    """Thinker 가 배정 단위 셋을 내고 Worker 셋 + Verifier 가 뒤따르는 스크립트."""
    plan = "계획.\n\n```json\n" + json.dumps(UNIT_PLAN, ensure_ascii=False) + "\n```\n"
    return [
        FakeSession(SessionResult(text=plan, stop_reason="end_turn", commands=[]), label="thinker"),
        worker({"a.txt": "a\n"}, root),
        worker({"b.txt": "b\n"}, root),
        worker({"c.txt": "c\n"}, root),
        verifier("PASS"),
    ]


def plan_cls() -> dict:
    return {**CLS_WRITE, "parallel_requested": True, "criteria": ["a.txt·b.txt·c.txt 생성"]}


class TestShapeRoutes(Base):
    """형상이 **갈래를 고르는가** — 적히기만 하던 판정이 실행 경로를 정하는지.

    여태 `choose_shape` 는 `_parse_units` 가 이미 갈래를 정한 뒤에 불려서 아무것도 안 바꿨다.
    여기서 재는 것은 네 형상이 각각 다른 길로 가는가다.
    """

    # 전문 영역 둘(thor 인증 API · freyja 화면 UI)을 함께 건드리는 요청.
    CROSS = "로그인 화면 UI 를 다시 그리고 인증 API 엔드포인트도 고쳐줘"

    def test_direct_shape_opens_no_ledger_at_all(self):
        """쓰기가 없으면 Run 도 DB 도 안 생긴다 — direct 는 무세금 경로다."""
        ledger = open_ledger(FakeHeimdall(self.root, []), "q-direct", "이 코드 설명해줘", {"write_expected": False})
        self.assertFalse(ledger.enabled)
        self.assertEqual(ledger.run_id, "")
        self.assertFalse(orc.exists(self.root), "direct 인데 배차 장부 DB 가 섰다")

    def test_write_shape_opens_a_ledger(self):
        ledger = open_ledger(FakeHeimdall(self.root, []), "q-write", "w1.txt 만들어", CLS_WRITE)
        self.assertTrue(ledger.enabled)
        self.assertTrue(ledger.run_id)

    def test_single_shape_runs_one_worker_turn(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        run = only_run(self.root)
        self.assertEqual(run["shape"], "single")
        # 배정 단위의 `unit_id` 는 계획이 붙인 정수이고, 역할 턴은 이름이다 — 그것이 둘의 구분이다.
        units = [t["unit_id"] for t in orc.task_list(self.root, run["id"]) if str(t["unit_id"]).isdigit()]
        self.assertEqual(units, [], f"single 인데 배정 단위 Task 가 생겼다: {units}")

    def test_graph_shape_runs_the_wave(self):
        h = FakeHeimdall(self.root, plan_script(self.root), cls=plan_cls())
        h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        self.assertEqual(only_run(self.root)["shape"], "graph")
        for name in ("a.txt", "b.txt", "c.txt"):
            self.assertTrue(os.path.exists(os.path.join(self.root, name)), f"{name} 이 안 생겼다")

    def test_squad_shape_tells_the_worker_to_delegate_by_domain(self):
        """squad 판정이 Worker 지시로 닿는가 — 안 닿으면 워커가 영역 둘을 혼자 구현한다."""
        implementing = worker({"w1.txt": "x\n"}, self.root)
        h = FakeHeimdall(self.root, [implementing, verifier("PASS")], cls=CLS_WRITE)
        h.handle(self.CROSS)
        self.assertEqual(only_run(self.root)["shape"], "squad")
        self.assertIn("Orchestration shape: squad", implementing.prompt)
        self.assertIn("dispatch", implementing.prompt)

    def test_single_shape_carries_no_squad_instruction(self):
        implementing = worker({"w1.txt": "x\n"}, self.root)
        h = FakeHeimdall(self.root, [implementing, verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertNotIn("Orchestration shape: squad", implementing.prompt)


class TestPlanWinsOnUnitCount(Base):
    """신호와 계획이 엇갈릴 때 — 배정 단위 수는 계획이 정하고, 엇갈린 사실은 Run 에 남는다.

    감사할 수 없는 라우터는 이 계층이 없애려던 것이다. 계획이 이기는 것만으로는 부족하고,
    무엇을 이겼는지 되읽을 자리가 있어야 한다.
    """

    PARALLEL_DEEP = {**CLS_WRITE, "task_class": "deep", "parallel_requested": True}
    CROSS = TestShapeRoutes.CROSS

    def _ledger(self, request: str) -> BifrostLedger:
        return BifrostLedger(FakeHeimdall(self.root, []), "q-disagree", request)

    def test_a_thin_plan_beats_a_parallel_signal(self):
        """신호는 graph 인데 계획이 단위를 하나만 냈다 — 나눠 돌릴 일감이 없다."""
        ledger = self._ledger("w1.txt 만들어")
        pre = ledger.choose_shape(self.PARALLEL_DEEP, specialists=[])
        self.assertEqual(pre["shape"], "graph")
        decision = ledger.choose_shape(self.PARALLEL_DEEP, unit_count=1, specialists=[], planned=True)
        self.assertEqual(decision["shape"], "single")
        self.assertIn("graph", decision["disagreement"])
        self.assertIn("이견", only_run(self.root)["shape_why"])

    def test_many_units_beat_a_squad_signal(self):
        """신호는 squad 인데 계획이 단위를 넷 냈다 — 일감이 여럿이면 그래프다."""
        ledger = self._ledger(self.CROSS)
        self.assertEqual(ledger.choose_shape(CLS_WRITE)["shape"], "squad")
        decision = ledger.choose_shape(CLS_WRITE, unit_count=4, planned=True)
        self.assertEqual(decision["shape"], "graph")
        self.assertIn("squad", decision["disagreement"])
        self.assertIn("4개", decision["disagreement"])
        self.assertIn("이견", only_run(self.root)["shape_why"])

    def test_agreement_leaves_no_disagreement_line(self):
        ledger = self._ledger("w1.txt 만들어")
        decision = ledger.choose_shape(CLS_WRITE, unit_count=0, specialists=[], planned=True)
        self.assertEqual(decision["shape"], "single")
        self.assertEqual(decision["disagreement"], "")
        self.assertNotIn("이견", only_run(self.root)["shape_why"])


class TestCoordinatorReadsReady(Base):
    """코디네이터가 `task_list(ready=True)` 를 읽어 배차하는가 — Orca 의 감독 고리."""

    def _ledger(self) -> BifrostLedger:
        return BifrostLedger(FakeHeimdall(self.root, []), "q-loop", "감독 고리")

    def _chain(self, ledger: BifrostLedger) -> tuple[dict, dict]:
        """A → B 로 이어진 일감 둘. B 는 A 가 끝나기 전에는 준비되지 않는다."""
        first = orc.task_create(self.root, ledger.run_id, "a 만들기", unit_id="A")
        second = orc.task_create(self.root, ledger.run_id, "b 만들기", deps=[first["id"]], unit_id="B")
        return first, second

    def _loop(self, ledger: BifrostLedger) -> CoordinatorLoop:
        return CoordinatorLoop(FakeHeimdall(self.root, []), ledger, "감독 고리")

    def test_the_loop_dispatches_from_ready_and_settles(self):
        ledger = self._ledger()
        self._chain(ledger)
        rounds: list[list[str]] = []

        def dispatch(ready: list[dict]) -> None:
            rounds.append([str(task["unit_id"]) for task in ready])
            for task in ready:
                attempt = orc.open_dispatch(self.root, task["id"], worker="w")
                orc.worker_done(
                    self.root, ledger.run_id, task["id"], attempt["id"], "succeeded", subject="done", sender="w"
                )

        with self._loop(ledger) as loop:
            supervised = loop.supervise(dispatch)
        self.assertEqual(rounds, [["A"], ["B"]], "준비된 순서대로 배차하지 않았다")
        self.assertTrue(supervised["supervised"])
        self.assertEqual(len(supervised["reports"]), 2, "완료 보고를 못 거뒀다")
        self.assertEqual({t["status"] for t in orc.task_list(self.root, ledger.run_id)}, {"completed"})

    def test_a_task_whose_dependency_is_unsettled_is_never_dispatched(self):
        """선행이 안 끝났으면 그 일감은 `ready` 가 아니다 — 실행자 손에 아예 안 들어간다."""
        ledger = self._ledger()
        self._chain(ledger)
        rounds: list[list[str]] = []

        def dispatch(ready: list[dict]) -> None:  # 열기만 하고 정산하지 않는다
            rounds.append([str(task["unit_id"]) for task in ready])
            for task in ready:
                orc.open_dispatch(self.root, task["id"], worker="w")

        with self._loop(ledger) as loop:
            loop.supervise(dispatch)
        self.assertEqual(rounds, [["A"]], f"의존이 안 끝난 B 가 배차됐다: {rounds}")

    def test_a_blocked_dependent_is_never_dispatched(self):
        """선행이 실패하면 뒤따르는 일감은 `blocked` 이다 — 돌 수 없는 일을 배차하지 않는다."""
        ledger = self._ledger()
        first, second = self._chain(ledger)
        rounds: list[list[str]] = []

        def dispatch(ready: list[dict]) -> None:
            rounds.append([str(task["unit_id"]) for task in ready])
            for task in ready:
                attempt = orc.open_dispatch(self.root, task["id"], worker="w")
                orc.dispatch_settle(self.root, attempt["id"], "failed")
            orc.task_update(self.root, first["id"], status="failed")

        with self._loop(ledger) as loop:
            loop.supervise(dispatch)
        self.assertEqual(rounds, [["A"]])
        dependent = next(t for t in orc.task_list(self.root, ledger.run_id) if t["id"] == second["id"])
        self.assertEqual(dependent["status"], "blocked")

    def test_the_wave_turn_reads_ready_before_it_runs(self):
        """graph 갈래가 감독 고리를 거치는가 — 첫 묶음은 독립 단위 둘뿐이어야 한다."""
        original = BifrostLedger.ready_tasks
        seen: list = []

        def spy(self) -> list[dict] | None:
            rows = original(self)
            seen.append(None if rows is None else sorted(str(row["unit_id"]) for row in rows))
            return rows

        h = FakeHeimdall(self.root, plan_script(self.root), cls=plan_cls())
        with mock.patch.object(BifrostLedger, "ready_tasks", spy):
            h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        self.assertTrue(seen, "코디네이터가 준비도를 한 번도 안 읽었다")
        self.assertEqual(seen[0], ["1", "2"], f"준비도가 계획의 독립 단위와 다르다: {seen}")

    def test_the_loop_waits_for_a_settlement_that_lands_late(self):
        """실행자가 비동기로 끝나는 경우 — 고리가 정산을 기다려야 완료 보고를 거둔다."""
        ledger = self._ledger()
        first, _ = self._chain(ledger)
        finished = threading.Event()

        def settle_later(task_id: str, dispatch_id: str) -> None:
            finished.wait(2)
            orc.worker_done(self.root, ledger.run_id, task_id, dispatch_id, "succeeded", subject="늦은 보고")

        workers: list[threading.Thread] = []

        def dispatch(ready: list[dict]) -> None:
            for task in ready:
                attempt = orc.open_dispatch(self.root, task["id"], worker="w")
                thread = threading.Thread(target=settle_later, args=(task["id"], attempt["id"]))
                workers.append(thread)
                thread.start()
            finished.set()  # 배차가 돌아온 **뒤에** 정산이 들어온다

        with self._loop(ledger) as loop:
            supervised = loop.supervise(dispatch, rounds=1, wait_ms=5000)
        for thread in workers:
            thread.join(timeout=5)
        self.assertEqual([m["task_id"] for m in supervised["reports"]], [first["id"]], "늦게 온 정산을 못 거뒀다")

    def test_an_unanswered_question_is_not_acked_away(self):
        """답 못 한 질문을 확인 처리하면 워커를 세워 둔 그 메일이 '처리됨' 으로 접힌다.

        `check` 의 재생 계약은 확인 전까지 같은 묶음을 다시 준다는 것이다. 그 계약이 가장
        필요한 종류가 질문인데, 답을 안 하고 확인부터 하면 재생이 그 자리에서 끊긴다.
        """
        ledger = self._ledger()
        orc.ask(self.root, ledger.run_id, "포트를 어떻게 정할까?", sender="w")
        self.assertEqual(ledger.drain(None), [], "질문은 호출자에게 돌려주지 않는다")
        replayed = orc.check(self.root, ledger.run_id)
        self.assertEqual([m["type"] for m in replayed["messages"]], ["question"], "답 없는 질문이 확인 처리됐다")

    def test_an_answered_batch_is_acked(self):
        ledger = self._ledger()
        orc.ask(self.root, ledger.run_id, "포트를 어떻게 정할까?", sender="w")
        ledger.drain(lambda message: "8080 으로 둬라.")
        self.assertEqual(orc.check(self.root, ledger.run_id)["messages"], [], "답한 묶음이 안 확인됐다")

    def test_a_replayed_report_is_counted_once(self):
        """답 못 한 질문 때문에 묶음이 다시 와도 완료 보고는 한 번만 센다."""
        ledger = self._ledger()
        first, _ = self._chain(ledger)
        orc.ask(self.root, ledger.run_id, "이 값을 어떻게 정할까?", sender="w")

        def dispatch(ready: list[dict]) -> None:
            for task in ready:
                attempt = orc.open_dispatch(self.root, task["id"], worker="w")
                orc.worker_done(self.root, ledger.run_id, task["id"], attempt["id"], "succeeded", subject="done")

        with self._loop(ledger) as loop:
            loop._stop.set()  # 데몬이 답하지 않게 세운다 — 질문이 미답으로 남아 묶음이 재생된다
            supervised = loop.supervise(dispatch)
        self.assertEqual([m["task_id"] for m in supervised["reports"]].count(first["id"]), 1, "보고가 두 번 세어졌다")

    def test_the_loop_stops_on_an_escalation(self):
        ledger = self._ledger()
        self._chain(ledger)

        def dispatch(ready: list[dict]) -> None:
            for task in ready:
                attempt = orc.open_dispatch(self.root, task["id"], worker="w")
                orc.escalate(self.root, ledger.run_id, "오딘 판단 필요", task_id=task["id"])
                orc.worker_done(
                    self.root, ledger.run_id, task["id"], attempt["id"], "succeeded", subject="done", sender="w"
                )

        with self._loop(ledger) as loop:
            supervised = loop.supervise(dispatch)
        self.assertEqual(len(supervised["escalations"]), 1)
        self.assertEqual(supervised["rounds"], 1, "개입 요청 뒤에도 다음 묶음을 밀어 넣었다")
        self.assertEqual(supervised["dispatched"], [t["id"] for t in orc.task_list(self.root, ledger.run_id)][:1])


class TestTheHaltBecomesADecisionGate(Base):
    """멈춘 wave 가 **갚아야 할 결정**으로 장부에 남는가.

    게이트는 워커의 `ask` 의 짝이 아니라 반대편이다 (`board.gate_create` 의 계약): 저쪽은 막힌
    워커가 코디네이터에게 묻는 것이고, 이쪽은 코디네이터가 다음 갈래를 고르는 것이다. 개입
    요청을 받고 다음 묶음을 안 밀어 넣기로 한 자리에서 그 다음 갈래는 아무도 안 골랐으므로,
    거기가 게이트가 서는 유일한 자리다. 그리고 **기다리지 않는다** — 헤드리스 퀘스트에는 답할
    사람이 없어서 기다리면 `asgard run` 이 통째로 멈춘다.
    """

    def _ledger(self, qid: str = "q-gate") -> BifrostLedger:
        return BifrostLedger(FakeHeimdall(self.root, []), qid, "게이트")

    def _escalating_dispatch(self, ledger: BifrostLedger, reason: str = "스키마를 바꿔야 해요"):
        def dispatch(ready: list[dict]) -> None:
            for task in ready:
                attempt = orc.open_dispatch(self.root, task["id"], worker="w")
                orc.escalate(self.root, ledger.run_id, reason, task_id=task["id"], sender="w")
                orc.worker_done(
                    self.root, ledger.run_id, task["id"], attempt["id"], "succeeded", subject="done", sender="w"
                )

        return dispatch

    def test_a_halted_wave_opens_exactly_one_decision_gate(self):
        """개입 요청이 여럿이어도 코디네이터가 마주한 갈래는 하나다 — 요청마다 한 줄씩 쌓지 않는다."""
        ledger = self._ledger()
        turn = orc.task_create(self.root, ledger.run_id, "WORKER — 구현", unit_id="WORKER")
        ledger._turn_task = turn["id"]
        orc.task_create(self.root, ledger.run_id, "a 만들기", unit_id="A")
        with CoordinatorLoop(FakeHeimdall(self.root, []), ledger, "게이트") as loop:
            supervised = loop.supervise(self._escalating_dispatch(ledger))
        self.assertEqual(len(supervised["escalations"]), 2, "개입 요청을 못 거뒀다")
        gates = orc.gate_list(self.root, run_id=ledger.run_id, status="open")
        self.assertEqual(len(gates), 1, f"멈춘 wave 가 결정 게이트를 안 남겼다: {gates}")
        # 질문과 선택지가 **코디네이터가 마주한 갈래**를 적어야 한다 — 워커의 요청을 옮겨 적는
        # 것이 아니다. 답할 사람이 목록만 보고 무엇을 고르는지 알 수 있어야 닫을 수 있다.
        self.assertIn("멈췄어요", gates[0]["question"])
        self.assertIn("스키마를 바꿔야 해요", gates[0]["question"])
        self.assertEqual(len(gates[0]["options"]), 3, f"고를 갈래가 안 적혔다: {gates[0]['options']}")
        self.assertEqual(gates[0]["task_id"], turn["id"], "게이트가 멈춘 역할 턴에 안 매달렸다")

    def test_the_gate_is_a_record_not_a_barrier(self):
        """게이트를 열어 둔 채로도 감독 고리는 곧장 돌아온다 — 답을 기다리면 헤드리스가 멈춘다."""
        ledger = self._ledger("q-nonblocking")
        orc.task_create(self.root, ledger.run_id, "a 만들기", unit_id="A")
        done = threading.Event()

        def run() -> None:
            with CoordinatorLoop(FakeHeimdall(self.root, []), ledger, "게이트") as loop:
                loop.supervise(self._escalating_dispatch(ledger))
            done.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=20)
        self.assertTrue(done.is_set(), "열린 게이트가 감독 고리를 세워 뒀다 — 게이트는 관문이 아니다")
        self.assertEqual(len(orc.gate_list(self.root, run_id=ledger.run_id, status="open")), 1)

    def test_the_same_turn_does_not_stack_a_second_gate(self):
        """같은 턴이 다시 멈춰도 미결은 하나다 — 사람이 같은 결정을 두 번 닫게 하지 않는다."""
        ledger = self._ledger("q-once")
        ledger._turn_task = orc.task_create(self.root, ledger.run_id, "WORKER — 구현", unit_id="WORKER")["id"]
        for name in ("A", "B"):
            orc.task_create(self.root, ledger.run_id, f"{name} 만들기", unit_id=name)
        for _ in range(2):
            with CoordinatorLoop(FakeHeimdall(self.root, []), ledger, "게이트") as loop:
                loop.supervise(self._escalating_dispatch(ledger))
        gates = orc.gate_list(self.root, run_id=ledger.run_id)
        self.assertEqual(len(gates), 1, f"같은 턴의 멈춤이 게이트를 겹쳐 쌓았다: {gates}")

    def test_a_new_turn_may_open_its_own_gate(self):
        """다음 턴의 멈춤은 **다른** 멈춤이다 — WORKER 가 멈춘 자리와 WORKER_RETRY 가 멈춘 자리는 같은 갈래가 아니다."""
        ledger = self._ledger("q-next-turn")
        for role in ("WORKER", "WORKER_RETRY"):
            ledger._turn_task = orc.task_create(self.root, ledger.run_id, f"{role} — 구현", unit_id=role)["id"]
            orc.task_create(self.root, ledger.run_id, f"{role} 단위", unit_id=f"u-{role}")
            with CoordinatorLoop(FakeHeimdall(self.root, []), ledger, "게이트") as loop:
                loop.supervise(self._escalating_dispatch(ledger))
        self.assertEqual(len(orc.gate_list(self.root, run_id=ledger.run_id)), 2, "새 턴의 멈춤이 안 적혔다")

    def test_a_quest_completes_when_the_gate_cannot_be_written(self):
        """게이트를 못 적어도 퀘스트는 끝난다 — 부기가 진행을 잃게 하지 않는다 (fail-open).

        준비도를 읽는 자리에 개입 요청을 끼워 넣어 실제 병렬 퀘스트에서 wave 를 멈추게 하고,
        그 상태에서 게이트 쓰기를 깨뜨린다. 산출물 셋이 다 나와야 한다.
        """
        original = BifrostLedger.ready_tasks

        def escalating_ready(ledger: BifrostLedger) -> list[dict] | None:
            rows = original(ledger)
            if rows:
                orc.escalate(self.root, ledger.run_id, "워커가 막혔어요", sender="w")
            return rows

        h = FakeHeimdall(self.root, plan_script(self.root), cls=plan_cls())
        stderr = io.StringIO()
        with mock.patch.object(BifrostLedger, "ready_tasks", escalating_ready):
            with mock.patch.object(ledger_module, "gate_create", side_effect=RuntimeError("db locked")):
                with contextlib.redirect_stderr(stderr):
                    h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        for name in ("a.txt", "b.txt", "c.txt"):
            self.assertTrue(os.path.exists(os.path.join(self.root, name)), f"{name} 이 안 생겼다")
        self.assertIn("bifrost gate", stderr.getvalue(), "삼킨 게이트 실패가 어디에도 안 남았다")
        self.assertEqual(orc.gate_list(self.root), [], "쓰기가 깨졌는데 게이트가 남았다")

    def test_a_wave_that_never_halts_leaves_no_gate(self):
        """개입 요청이 없으면 고를 갈래도 없다 — 게이트는 정상 완주의 부산물이 아니다."""
        ledger = self._ledger("q-clean")
        orc.task_create(self.root, ledger.run_id, "a 만들기", unit_id="A")

        def dispatch(ready: list[dict]) -> None:
            for task in ready:
                attempt = orc.open_dispatch(self.root, task["id"], worker="w")
                orc.worker_done(
                    self.root, ledger.run_id, task["id"], attempt["id"], "succeeded", subject="done", sender="w"
                )

        with CoordinatorLoop(FakeHeimdall(self.root, []), ledger, "게이트") as loop:
            loop.supervise(dispatch)
        self.assertEqual(orc.gate_list(self.root, run_id=ledger.run_id), [])


class TestSupervisionIsFailOpen(Base):
    """장부가 죽어도 일은 돈다 — 다만 조용히는 아니다."""

    def test_an_unreadable_ready_view_still_runs_the_wave(self):
        h = FakeHeimdall(self.root, plan_script(self.root), cls=plan_cls())
        stderr = io.StringIO()
        with mock.patch.object(ledger_module, "task_list", side_effect=RuntimeError("db gone")):
            with contextlib.redirect_stderr(stderr):
                h.handle("a.txt·b.txt 를 병렬로 만들고 c.txt 로 합쳐")
        for name in ("a.txt", "b.txt", "c.txt"):
            self.assertTrue(os.path.exists(os.path.join(self.root, name)), f"{name} 이 안 생겼다")
        self.assertIn("⚠ bifrost", stderr.getvalue(), "삼킨 장부 실패가 어디에도 안 남았다")

    def test_a_dead_ledger_dispatches_once_without_supervision(self):
        ledger = BifrostLedger(FakeHeimdall(self.root, []), "q-dead", "장부가 죽었다")
        ledger.enabled = False
        calls: list[list[dict]] = []
        with CoordinatorLoop(FakeHeimdall(self.root, []), ledger, "장부가 죽었다") as loop:
            supervised = loop.supervise(calls.append)
        self.assertEqual(calls, [[]], "장부가 없다고 실행자를 안 불렀다")
        self.assertFalse(supervised["supervised"])

    def test_a_note_is_left_when_the_ready_view_fails(self):
        ledger = BifrostLedger(FakeHeimdall(self.root, []), "q-note", "준비도 조회 실패")
        with mock.patch.object(ledger_module, "task_list", side_effect=RuntimeError("db locked")):
            self.assertIsNone(ledger.ready_tasks())
        self.assertTrue(any("ready_tasks" in note for note in ledger.notes), f"기록이 없다: {ledger.notes}")

    def test_the_circuit_breaker_still_folds_a_unit(self):
        """설정된 시도 상한에 닿으면 그 단위는 접힌다 — 감독 고리가 그 앞을 안 가린다."""
        units = [{"id": 1, "subtask": "a 만들기", "files": ["a.txt"], "criteria": ["a"], "access": []}]
        hd = FakeHeimdall(self.root, [])
        # 칸을 새 dict 로 갈아 끼운다. `hd.policy["ticket_runtime"]` 은 quest_log.load_policy 의
        # 얕은 복사가 넘긴 DEFAULT_POLICY 의 그 dict 라, 안을 고치면 같은 프로세스의 뒤 테스트가
        # 전부 max_attempts=2 를 본다 (test_heimdall 의 wave 재배정 기대가 그렇게 깨졌다).
        hd.policy["ticket_runtime"] = {**(hd.policy.get("ticket_runtime") or {}), "max_attempts": 2}
        ledger = BifrostLedger(hd, "q-breaker", "회로 차단")
        ledger.open_turn("WORKER", "구현")
        ledger.register_units(units)
        for _ in range(2):
            self.assertTrue(ledger.open_unit(units[0]))
            ledger.settle_unit(units[0], "failed", summary="죽었다")
        task = next(t for t in orc.task_list(self.root, ledger.run_id) if t["unit_id"] == "1")
        self.assertEqual(task["status"], "failed", "상한에 닿았는데 안 접혔다")
        self.assertEqual(ledger.open_unit(units[0]), "", "회로가 끊긴 뒤에도 배차됐다")
        self.assertTrue(any("open_unit" in note for note in ledger.notes))


if __name__ == "__main__":
    unittest.main()
