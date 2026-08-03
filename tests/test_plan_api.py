"""기획 — 문서 셋의 형상·접지 게이트·편집 연산, 그리고 그 위의 루프백 계약.

이 파일이 지키는 불변식 하나: **뒤 문서는 앞 문서가 비면 만들어지지 않는다.** 규칙이라서가
아니라 재료가 없어서다. 나머지 검사는 그 불변식이 어디서도 새지 않는지를 본다 —
저장소에서도(`readiness`), 도메인 호출에서도(`require_ready`), HTTP 에서도(409).
"""

import contextlib
import json
import os
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from unittest import mock

from asgard import plan as P
from asgard.commands import plan_api as surface
from asgard.plan import build, intake, planner


def _seeded(idea: str = "팀 회고를 자동으로 모아 주는 도구", root: str = "") -> dict:
    return P.create_plan(idea, root=root)


@contextlib.contextmanager
def _engine(reply, missing=()):
    """모델 호출 자리를 가로챈다 — 무엇으로 불렀는지와 무슨 프롬프트가 갔는지를 남긴다.

    `reply`가 함수면 모델에 간 user 페이로드(dict)를 받아 응답 dict를 돌려준다."""
    seen: dict = {"resolved": [], "systems": [], "users": []}

    def fake_resolve(root=None, provider=None, model=None):
        seen["resolved"].append({"root": root, "provider": provider, "model": model})
        return types.SimpleNamespace(missing=list(missing), model=model or "default", profile=None)

    def fake_complete_with(resolved, root, system, user, max_tokens=3000):
        seen["systems"].append(system)
        seen["users"].append(json.loads(user))
        payload = reply(seen["users"][-1]) if callable(reply) else reply
        return json.dumps(payload, ensure_ascii=False)

    with (
        mock.patch("asgard.providers.resolve", fake_resolve),
        mock.patch("asgard.agent.oneshot.complete_with", fake_complete_with),
    ):
        yield seen


def _round(payload: dict) -> dict:
    """단계의 필수 축마다 열린 질문 하나씩 — 판정은 전부 missing."""
    axes = [row["id"] for row in payload["axes"] if row["required"]]
    return {
        "assessment": [{"axis": axis, "state": "missing"} for axis in axes],
        "questions": [
            {"axis": axis, "kind": "open", "target": "", "q": f"{payload['stage']}/{axis} 를 알려 주세요"}
            for axis in axes
        ],
        "opened_axes": [],
        "stage_done": False,
    }


def _answer_all(plan: dict) -> dict:
    for row in plan["intake"]["questions"]:
        if row["state"] == "open":
            plan = P.apply_edit(plan["id"], "answer", {"question": row["id"], "text": "지난주에 그랬어요"})
    return plan


_PRD_REPLY = {
    "sections": {sid: f"- {sid} 초안" for sid in P.PRD_SECTION_IDS},
    "attributes": {"category": "협업 도구", "roles": ["스쿼드 리드"], "environments": ["웹"]},
    "assumptions": [{"axis": "success_signal", "text": "석 달 뒤 회고 참여율로 잰다고 봤어요"}],
    "checks": [{"axis": "user", "q": "스쿼드 리드가 매일 여는 게 맞을까요?"}],
}


def _with_overview(plan: dict) -> dict:
    return P.apply_edit(plan["id"], "section", {"section": "overview", "body": "- 회고를 자동으로 모은다"})


def _with_feature(plan: dict) -> dict:
    plan = P.apply_edit(plan["id"], "item.save", {"item": {"level": 1, "title": "회고 수집"}})
    parent = plan["spec"]["items"][0]["id"]
    return P.apply_edit(plan["id"], "item.save", {"item": {"level": 2, "parent": parent, "title": "슬랙에서 긁어오기"}})


class TestPlanShape(unittest.TestCase):
    def test_a_plan_starts_from_one_line_with_nothing_to_choose(self):
        """문을 열면 고를 것이 없다 — 산출물도 방법도 묻지 않는다.

        앞선 형상은 `create_plan(root, title, method, deliverable)` 이었다: 첫 화면이
        고르기 두 판이었다는 뜻이다. 이제 들어오는 것은 한 줄뿐이다."""
        plan = _seeded()
        self.assertEqual(plan["phase"], "intake")
        self.assertEqual(plan["intake"]["questions"], [])
        self.assertEqual([turn["role"] for turn in plan["chat"]], ["user"])
        self.assertEqual(plan["chat"][0]["text"], "팀 회고를 자동으로 모아 주는 도구")
        self.assertEqual(plan["title"], "팀 회고를 자동으로 모아 주는 도구")
        self.assertEqual(sorted(plan["prd"]["sections"]), sorted(P.PRD_SECTION_IDS))

    def test_a_plan_does_not_live_in_a_project_folder(self):
        """기획은 폴더가 아니라 **워크스페이스**에 산다.

        여태 정본은 `<프로젝트>/.asgard/plan/plans.json` 이었다. 그래서 코드가 없는 아이디어는
        적을 자리가 없었고, 창을 어디서 여느냐가 목록을 갈랐다. 이제 자리는 하나다."""
        home = os.environ["ASGARD_STUDIO_HOME"]
        self.assertEqual(P.store_path(), os.path.join(home, "plans.json"))
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            self.assertEqual(plan["root"], "")  # 폴더 링크는 선택이고 기본은 없음
            self.assertFalse(os.path.exists(os.path.join(root, ".asgard", "plan")))
            self.assertIn(plan["id"], [head["id"] for head in P.list_plans()["plans"]])

    def test_a_plan_may_point_at_a_folder_without_moving_into_it(self):
        """폴더는 **거는 값**이지 사는 자리가 아니다 — 걸어도 정본은 워크스페이스에 남는다."""
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded(root=root)
            self.assertEqual(plan["root"], os.path.abspath(root))
            self.assertFalse(os.path.exists(os.path.join(root, ".asgard", "plan")))
            # 목록은 전체가 기본이고, 폴더는 거를 때만 쓴다
            self.assertEqual(len(P.list_plans()["plans"]), 1)
            self.assertEqual(len(P.list_plans(root)["plans"]), 1)
            self.assertEqual(P.list_plans(os.path.join(root, "elsewhere"))["plans"], [])

            plan = P.apply_edit(plan["id"], "root", {"root": ""})
            self.assertEqual(plan["root"], "")

    def test_a_folder_bound_plan_store_is_imported_once_and_the_original_is_kept(self):
        """폴더에 갇혀 있던 기획은 들여오되 원본은 안 지운다 — 돌아갈 곳이 있어야 한다."""
        with tempfile.TemporaryDirectory() as root:
            source = P.project_store_path(root)
            os.makedirs(os.path.dirname(source), exist_ok=True)
            stranded = P.new_plan("폴더에 갇힌 기획")
            with open(source, "w", encoding="utf-8") as handle:
                json.dump({"schema": P.SCHEMA_VERSION, "active_plan_id": None, "plans": [stranded]}, handle)

            self.assertEqual(P.pending_roots([root]), [os.path.abspath(root)])
            result = P.import_root(root)
            self.assertEqual((result["imported"], result["plans"]), (True, 1))
            head = P.list_plans()["plans"][0]
            self.assertEqual((head["id"], head["root"]), (stranded["id"], os.path.abspath(root)))
            self.assertTrue(os.path.isfile(source))

            self.assertEqual(P.pending_roots([root]), [])
            self.assertEqual(P.import_root(root)["plans"], 0)
            self.assertEqual(len(P.list_plans()["plans"]), 1)

    def test_the_import_route_keeps_the_count_and_the_list_apart(self):
        """둘 다 `plans` 라는 이름을 쓴다 — 겹치면 화면이 '기획 [object]건'을 말한다."""
        with tempfile.TemporaryDirectory() as root:
            source = P.project_store_path(root)
            os.makedirs(os.path.dirname(source), exist_ok=True)
            with open(source, "w", encoding="utf-8") as handle:
                json.dump(
                    {"schema": P.SCHEMA_VERSION, "active_plan_id": None, "plans": [P.new_plan("폴더에 갇힌 기획")]},
                    handle,
                )
            status, _, body = surface.dispatch("POST", "/api/plans/import", json.dumps({"root": root}).encode(), root)
            payload = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual((payload["imported"]["imported"], payload["imported"]["plans"]), (True, 1))
            self.assertEqual([head["title"] for head in payload["plans"]], ["폴더에 갇힌 기획"])
            self.assertEqual(payload["pending"], [])

        status, _, body = surface.dispatch("POST", "/api/plans/import", b"{}")
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, "invalid_plan"))
        self.assertEqual(surface.dispatch("GET", "/api/plans/import")[0], 405)

    def test_an_empty_idea_is_refused(self):
        with self.assertRaises(ValueError):
            P.create_plan("   ")

    def test_revision_guards_a_concurrent_write(self):
        plan = _seeded()
        stale = json.loads(json.dumps(plan))
        P.apply_edit(plan["id"], "title", {"title": "다른 이름"})
        with self.assertRaises(P.RevisionConflict):
            P.save_plan(stale)

    def test_the_old_stage_store_is_set_aside_not_destroyed(self):
        """스키마가 갈리면 지우지 않는다 — 옮길 자리가 없을 뿐이다."""
        legacy = {"schema": 1, "active_plan_id": None, "plans": [{"id": "old", "stages": []}]}
        os.makedirs(os.path.dirname(P.store_path()), exist_ok=True)
        with open(P.store_path(), "w", encoding="utf-8") as handle:
            json.dump(legacy, handle)
        self.assertEqual(P.list_plans()["plans"], [])
        with open(P.legacy_path(), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), legacy)


class TestGrounding(unittest.TestCase):
    def test_each_document_is_blocked_until_its_input_exists(self):
        plan = _seeded()
        ready = P.readiness(plan)
        self.assertEqual(ready["spec"]["blocked"], ["prd.overview"])
        self.assertEqual(ready["flow"]["blocked"], ["prd.overview", "spec.feature"])

        plan = _with_overview(plan)
        ready = P.readiness(plan)
        self.assertTrue(ready["spec"]["ready"])
        self.assertEqual(ready["flow"]["blocked"], ["spec.feature"])

        plan = _with_feature(plan)
        self.assertTrue(P.readiness(plan)["flow"]["ready"])

    def test_require_ready_names_what_is_missing_in_the_user_s_words(self):
        plan = _seeded()
        with self.assertRaisesRegex(P.PlanNotReady, "개요"):
            P.require_ready(plan, "spec")
        plan = _with_overview(plan)
        with self.assertRaisesRegex(P.PlanNotReady, "기능"):
            P.require_ready(plan, "flow")

    def test_the_cursor_cannot_move_to_a_document_with_no_input(self):
        """`phase`는 커서지 진척이 아니다 — 그래도 재료 없는 자리에는 못 선다."""
        plan = _seeded()
        with self.assertRaises(P.PlanNotReady):
            P.set_phase(plan, "spec")
        P.set_phase(plan, "prd")
        self.assertEqual(plan["phase"], "prd")

    def test_next_step_walks_the_documents_in_order(self):
        plan = _seeded()
        # 갈래를 안 고르면 물을 것을 못 고른다 — 그래서 choose_mode 가 맨 앞이다.
        self.assertEqual(P.next_step(plan)["action"], "choose_mode")
        plan = P.set_mode(plan["id"], "guided")
        self.assertEqual(P.next_step(plan)["action"], "ask")
        plan = P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?"]})
        self.assertEqual(P.next_step(plan)["action"], "answer")
        plan = P.apply_edit(plan["id"], "intake.skip", {"id": plan["intake"]["questions"][0]["id"]})
        self.assertEqual(P.next_step(plan)["action"], "ask")
        for section in P.PRD_SECTION_IDS:
            plan = P.apply_edit(plan["id"], "section", {"section": section, "body": "- 내용"})
        self.assertEqual(P.next_step(plan)["action"], "draft_spec")
        plan = _with_feature(plan)
        self.assertEqual(P.next_step(plan)["action"], "draft_flow")


class TestEdits(unittest.TestCase):
    def test_only_named_operations_exist(self):
        plan = _seeded()
        with self.assertRaises(P.UnknownOp):
            P.apply_edit(plan["id"], "drop_database", {})
        self.assertIn("item.save", P.OPS)

    def test_answering_a_question_also_lands_in_the_conversation(self):
        """문답이 대화 밖에 있으면 맥락이 갈린다 — 모델이 읽는 것과 사람이 보는 것이 달라진다.

        물은 쪽과 답한 쪽은 **따로** 적힌다. 한 줄에 묶으면 화면이 그 줄을 누가 말한 것으로도
        못 세워서 문답 표를 대화 밖에 한 번 더 그리게 되고, 같은 답이 두 자리에 선다."""
        plan = _seeded()
        plan = P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?", "지금은 어떻게 하나요?"]})
        first = plan["intake"]["questions"][0]["id"]
        plan = P.apply_edit(plan["id"], "answer", {"question": first, "text": "스쿼드 리드"})
        self.assertEqual(plan["intake"]["questions"][0]["a"], "스쿼드 리드")
        self.assertEqual(
            [(turn["role"], turn["text"]) for turn in plan["chat"][-2:]],
            [("asgard", "누가 쓰나요?"), ("user", "스쿼드 리드")],
        )
        onboarding = P.readiness(plan)["intake"]
        self.assertEqual(
            {key: onboarding[key] for key in ("asked", "answered", "blocked")},
            {"asked": 2, "answered": 1, "blocked": []},
        )

    def test_skipping_a_question_also_lands_in_the_conversation(self):
        """건너뛴 것도 대화에 남는다 — 안 남기면 화면이 그 기록을 대화 밖에 따로 들어야 한다."""
        plan = _seeded()
        plan = P.apply_edit(plan["id"], "questions", {"questions": ["언제 여나요?"]})
        first = plan["intake"]["questions"][0]["id"]
        plan = P.apply_edit(plan["id"], "intake.skip", {"id": first})
        self.assertEqual(plan["intake"]["questions"][0]["state"], "skipped")
        self.assertEqual(
            [(turn["role"], turn["text"]) for turn in plan["chat"][-2:]],
            [("asgard", "언제 여나요?"), ("user", "건너뛰었어요")],
        )

    def test_an_empty_answer_leaves_the_conversation_alone(self):
        """빈 답은 아직 안 한 것이다 — 대화에 적으면 안 한 일이 한 것으로 남는다."""
        plan = _seeded()
        plan = P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?"]})
        before = len(plan["chat"])
        first = plan["intake"]["questions"][0]["id"]
        plan = P.apply_edit(plan["id"], "answer", {"question": first, "text": "   "})
        self.assertEqual(len(plan["chat"]), before)
        self.assertEqual(plan["intake"]["questions"][0]["state"], "open")

    def test_asking_the_same_question_twice_does_nothing(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?"]})
        plan = P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?", "언제 쓰나요?"]})
        self.assertEqual([row["q"] for row in plan["intake"]["questions"]], ["누가 쓰나요?", "언제 쓰나요?"])

    def test_deleting_a_requirement_takes_its_children_and_frees_the_nodes(self):
        plan = _with_feature(_with_overview(_seeded()))
        top, feature = plan["spec"]["items"][0]["id"], plan["spec"]["items"][1]["id"]
        plan = P.apply_edit(plan["id"], "item.save", {"item": {"level": 3, "parent": feature, "title": "채널 고르기"}})
        plan = P.apply_edit(
            plan["id"], "node.save", {"node": {"type": "page", "title": "회고 목록", "source": feature}}
        )
        self.assertEqual(len(plan["spec"]["items"]), 3)

        plan = P.apply_edit(plan["id"], "item.delete", {"id": top})
        self.assertEqual(plan["spec"]["items"], [])
        # 노드는 남되 끊어진 출처는 지워진다 — 가리키는 곳이 없는 링크는 거짓말이다
        self.assertEqual(plan["flow"]["nodes"][0]["source"], "")

    def test_deleting_a_node_takes_the_edges_that_touched_it(self):
        plan = _with_feature(_with_overview(_seeded()))
        plan = P.apply_edit(plan["id"], "node.save", {"node": {"type": "start", "title": "진입"}})
        plan = P.apply_edit(plan["id"], "node.save", {"node": {"type": "page", "title": "목록"}})
        first, second = (row["id"] for row in plan["flow"]["nodes"])
        plan = P.apply_edit(plan["id"], "edge.save", {"edge": {"from": first, "to": second}})
        self.assertEqual(len(plan["flow"]["edges"]), 1)

        plan = P.apply_edit(plan["id"], "node.delete", {"id": second})
        self.assertEqual(plan["flow"]["edges"], [])

    def test_a_second_start_node_is_refused(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "node.save", {"node": {"type": "start", "title": "진입"}})
        with self.assertRaisesRegex(ValueError, "at most one start"):
            P.apply_edit(plan["id"], "node.save", {"node": {"type": "start", "title": "또 진입"}})

    def test_a_spec_item_cannot_become_its_own_ancestor(self):
        plan = _seeded()
        plan = P.apply_edit(plan["id"], "item.save", {"item": {"level": 1, "title": "뿌리"}})
        top = plan["spec"]["items"][0]["id"]
        plan = P.apply_edit(plan["id"], "item.save", {"item": {"level": 2, "parent": top, "title": "자식"}})
        child = plan["spec"]["items"][1]["id"]
        with self.assertRaisesRegex(ValueError, "cycle|parentless"):
            P.apply_edit(plan["id"], "item.save", {"item": {"id": top, "level": 2, "parent": child}})

    def test_a_child_is_inserted_next_to_its_parent_not_at_the_end(self):
        """끝에 붙이면 트리 뷰에서 형제와 떨어져 나타난다."""
        plan = _seeded()
        plan = P.apply_edit(plan["id"], "item.save", {"item": {"level": 1, "title": "첫째"}})
        first = plan["spec"]["items"][0]["id"]
        plan = P.apply_edit(plan["id"], "item.save", {"item": {"level": 1, "title": "둘째"}})
        plan = P.apply_edit(plan["id"], "item.save", {"item": {"level": 2, "parent": first, "title": "자식"}})
        self.assertEqual([row["title"] for row in plan["spec"]["items"]], ["첫째", "자식", "둘째"])

    def test_spec_tree_nests_by_parent(self):
        plan = _with_feature(_with_overview(_seeded()))
        tree = P.spec_tree(plan)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["children"][0]["title"], "슬랙에서 긁어오기")


class TestIntakeSchema(unittest.TestCase):
    """온보딩 스키마는 **순수 가산**이다 — 옛 문서가 그대로 통과하고, 새 필드는 저장에도 남는다."""

    def test_a_plan_written_before_the_added_fields_still_loads(self):
        """가산 필드가 없는 `{id, q, a}` 문서. 여기서 막으면 사용자의 `plans.json`이 통째로 거부된다."""
        plan = _seeded()
        old = json.loads(json.dumps(plan))
        old["intake"] = {"idea": "옛 기획", "questions": [{"id": "q-old", "q": "누가 쓰나요?", "a": "리드"}]}
        old.pop("engine")
        checked = P.validate_plan(old)
        row = checked["intake"]
        self.assertEqual((row["mode"], row["stage"], row["rounds"]), ("", "entry", 0))
        self.assertEqual((row["coverage"], row["assumptions"]), ({}, []))
        self.assertEqual(checked["engine"], {"provider": "", "model": ""})
        # 답이 있는 옛 줄은 answered 로 읽힌다 — state 칸이 없다고 열린 질문으로 되살아나면 안 된다
        self.assertEqual(checked["intake"]["questions"][0]["state"], "answered")
        self.assertEqual(checked["intake"]["questions"][0]["axis"], "")

    def test_the_schema_version_stays_at_two_so_the_legacy_lane_never_fires(self):
        """3으로 올리면 `_archive_legacy`가 사용자의 기획을 통째로 비켜 놓는다."""
        self.assertEqual(P.SCHEMA_VERSION, 2)

    def test_the_added_fields_survive_a_save(self):
        """`_checked_intake`가 행을 `{id, q, a}` 로만 재조립하던 자리 — 안 고치면 매 저장마다 사라진다."""
        plan = P.set_mode(_seeded()["id"], "guided")
        plan = P.mutate(
            plan["id"],
            lambda draft: draft["intake"]["questions"].append(
                {
                    "id": "q-seed",
                    "q": "지금은 어떻게 하고 있나요?",
                    "a": "",
                    "axis": "current_alternative",
                    "kind": "follow_up",
                    "parent": "",
                    "stage": "frame",
                    "state": "open",
                }
            ),
        )
        plan = P.mutate(plan["id"], lambda draft: intake.mark(draft["intake"]["coverage"], "problem", "thin"))
        plan = P.mutate(plan["id"], lambda draft: intake.note_assumption(draft["intake"], "role"))

        reloaded = P.load_plan(plan["id"])
        row = reloaded["intake"]["questions"][0]
        self.assertEqual(
            (row["axis"], row["kind"], row["stage"], row["state"]),
            ("current_alternative", "follow_up", "frame", "open"),
        )
        self.assertEqual(reloaded["intake"]["coverage"]["problem"]["state"], "thin")
        self.assertEqual(reloaded["intake"]["assumptions"][0]["axis"], "role")
        self.assertEqual(reloaded["intake"]["mode"], "guided")

    def test_the_axis_and_stage_tables_are_the_ones_the_research_named(self):
        """축 id와 단계 id는 코드가 든다 — 모델이 매번 지어내면 커버리지를 셀 수 없다."""
        self.assertEqual(
            [axis for axis, _, _ in P.INTAKE_AXES],
            [
                "problem",
                "current_alternative",
                "user",
                "usage_moment",
                "success_signal",
                "non_goal",
                "environment",
                "role",
                "constraint",
                "why_now",
                "risk_unknown",
                "product_category",
            ],
        )
        self.assertEqual([stage for stage, *_ in P.INTAKE_STAGES], ["entry", "frame", "scope", "ground", "confirm"])
        # 축 → PRD 칸 대응은 정본 다섯 칸 안에서만 산다
        self.assertTrue(all(section in P.PRD_SECTION_IDS for _, _, section in P.INTAKE_AXES))
        self.assertEqual(len(intake.REQUIRED_AXES), 9)

    def test_an_unknown_axis_or_stage_is_dropped_rather_than_stored(self):
        plan = _seeded()
        plan = P.mutate(plan["id"], lambda draft: draft["intake"]["coverage"].__setitem__("무엇", {"state": "covered"}))
        self.assertEqual(P.load_plan(plan["id"])["intake"]["coverage"], {})
        plan = P.mutate(plan["id"], lambda draft: draft["intake"].__setitem__("stage", "없는단계"))
        self.assertEqual(P.load_plan(plan["id"])["intake"]["stage"], "entry")


class TestOnboardingMode(unittest.TestCase):
    def test_the_mode_is_chosen_once(self):
        plan = _seeded()
        self.assertEqual(plan["intake"]["mode"], "")
        plan = P.set_mode(plan["id"], "guided")
        self.assertEqual((plan["intake"]["mode"], plan["intake"]["stage"]), ("guided", "frame"))
        # 같은 갈래를 다시 주는 것은 통과한다 — 화면이 재시도할 수 있다
        self.assertEqual(P.set_mode(plan["id"], "guided")["intake"]["mode"], "guided")
        with self.assertRaisesRegex(ValueError, "이미 다른 갈래"):
            P.set_mode(plan["id"], "auto")

    def test_the_auto_lane_stands_at_the_confirm_stage_from_the_start(self):
        """자동초안은 문답을 안 돈다 — 검증만 남으므로 확인 단계로 바로 간다."""
        plan = P.set_mode(_seeded()["id"], "auto")
        self.assertEqual(plan["intake"]["stage"], "confirm")
        self.assertEqual(P.next_step(plan)["action"], "draft_prd")

    def test_a_plan_may_be_created_with_a_mode_and_an_engine(self):
        plan = P.create_plan("회고 도구", mode="auto", engine={"provider": "nvidia", "model": "some-model"})
        self.assertEqual(plan["intake"]["mode"], "auto")
        self.assertEqual(plan["engine"], {"provider": "nvidia", "model": "some-model"})

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            P.create_plan("회고 도구", mode="빠르게")
        plan = _seeded()
        with self.assertRaises(ValueError):
            P.set_mode(plan["id"], "")


class TestOnboardingRounds(unittest.TestCase):
    """단계 루프 — 지금 단계의 안 덮인 축만 묻고, 상한은 코드가 센다."""

    def test_one_stage_at_a_time_and_one_question_on_screen(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        with _engine(_round) as seen:
            plan = P.ask(plan["id"])
        self.assertEqual(seen["users"][0]["stage"], "frame")
        self.assertEqual([row["stage"] for row in plan["intake"]["questions"]], ["frame"] * 3)
        self.assertEqual(plan["intake"]["rounds"], 1)

        # 대화 턴은 open_question 하나로 굴러간다 — 세 개를 한꺼번에 세우지 않는다
        onboarding = P.readiness(plan)["intake"]
        self.assertEqual(onboarding["open_question"]["q"], plan["intake"]["questions"][0]["q"])
        self.assertEqual(onboarding["stage"], "frame")
        self.assertEqual((onboarding["covered"], onboarding["axes"]), (0, 9))

        plan = _answer_all(plan)
        self.assertIsNone(P.readiness(plan)["intake"]["open_question"])
        self.assertEqual(P.readiness(plan)["intake"]["covered"], 3)

        with _engine(_round) as seen:
            plan = P.ask(plan["id"])
        self.assertEqual(seen["users"][0]["stage"], "scope")

    def test_a_stage_asks_at_most_three_and_the_interview_at_most_twelve(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        flood = {
            "assessment": [],
            "questions": [
                {"axis": axis, "kind": "open", "target": "", "q": f"{axis} 를 알려 주세요"} for axis in intake.AXIS_IDS
            ],
            "opened_axes": [],
            "stage_done": False,
        }
        with _engine(flood):
            plan = P.ask(plan["id"])
        self.assertEqual(len(plan["intake"]["questions"]), 3)

        for _ in range(6):
            plan = _answer_all(plan)
            with _engine(flood):
                plan = P.ask(plan["id"])
        self.assertLessEqual(len(plan["intake"]["questions"]), 12)
        self.assertLessEqual(plan["intake"]["rounds"], 5)

    def test_a_thin_answer_is_followed_up_once_and_then_frozen_as_an_assumption(self):
        plan = P.set_mode(_seeded()["id"], "guided")

        def thin(payload):
            return {
                "assessment": [{"axis": "problem", "state": "thin"}],
                "questions": [
                    {
                        "axis": "problem",
                        "kind": "follow_up",
                        "target": "",
                        "q": f"가장 최근은 언제였어요? {len(payload['answers'])}",
                    }
                ],
                "opened_axes": [],
                "stage_done": False,
            }

        with _engine(thin):
            plan = P.ask(plan["id"])
        self.assertEqual(plan["intake"]["questions"][0]["kind"], "follow_up")
        plan = _answer_all(plan)
        with _engine(thin):
            plan = P.ask(plan["id"])
        # 축당 되묻기 1회 — 두 번째 thin 은 가정으로 굳고 같은 축을 다시 묻지 않는다
        self.assertEqual([row["kind"] for row in plan["intake"]["questions"]], ["follow_up"])
        self.assertEqual(plan["intake"]["coverage"]["problem"]["state"], "assumed")
        self.assertEqual([item["axis"] for item in plan["intake"]["assumptions"]], ["problem"])

    def test_a_skipped_question_locks_its_axis_and_is_never_asked_again(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        with _engine(_round):
            plan = P.ask(plan["id"])
        first = plan["intake"]["questions"][0]
        plan = P.apply_edit(plan["id"], "intake.skip", {"id": first["id"]})
        self.assertEqual(plan["intake"]["questions"][0]["state"], "skipped")
        self.assertEqual(plan["intake"]["coverage"][first["axis"]]["state"], "skipped")
        self.assertEqual([item["axis"] for item in plan["intake"]["assumptions"]], [first["axis"]])

        # 건너뛴 축은 커버리지에서 정리된 것으로 세되, 근거 있는 칸에서는 빠진다
        onboarding = P.readiness(plan)["intake"]
        self.assertEqual(onboarding["covered"], 1)
        self.assertNotIn(intake.AXIS_SECTION[first["axis"]], onboarding["grounded_sections"])

        for row in plan["intake"]["questions"][1:]:
            plan = P.apply_edit(plan["id"], "answer", {"question": row["id"], "text": "지난주에 그랬어요"})
        with _engine(_round) as seen:
            plan = P.ask(plan["id"])
        self.assertEqual(seen["users"][0]["stage"], "scope")
        self.assertNotIn(first["axis"], [row["axis"] for row in plan["intake"]["questions"] if row["stage"] == "scope"])

    def test_a_skipped_axis_gets_exactly_one_yes_no_check_in_the_confirm_stage(self):
        """건너뛴 축은 다시 안 묻는다 — 예외는 확인 단계의 예·아니오 하나뿐이다."""

        def stage_round(payload):
            if payload["stage"] != "confirm":
                return _round(payload)
            return {
                "assessment": [],
                "questions": [
                    {"axis": item["axis"], "kind": "check", "target": "", "q": f"{item['axis']} 가정이 맞을까요?"}
                    for item in payload["assumptions"]
                ],
                "opened_axes": [],
                "stage_done": True,
            }

        plan = P.set_mode(_seeded()["id"], "guided")
        skipped = ""
        for _ in range(20):
            step = P.next_step(plan)["action"]
            if step == "ask":
                with _engine(stage_round):
                    plan = P.ask(plan["id"])
            elif step == "answer":
                question = P.readiness(plan)["intake"]["open_question"]
                if not skipped and question["kind"] == "open":
                    skipped = question["axis"]
                    plan = P.apply_edit(plan["id"], "intake.skip", {"id": question["id"]})
                else:
                    plan = P.apply_edit(plan["id"], "answer", {"question": question["id"], "text": "지난주에요"})
            else:
                break

        checks = [row for row in plan["intake"]["questions"] if row["kind"] == "check"]
        self.assertEqual([row["axis"] for row in checks], [skipped])
        self.assertEqual(plan["intake"]["coverage"][skipped]["state"], "skipped")
        self.assertTrue(all(item["confirmed"] for item in plan["intake"]["assumptions"]))
        self.assertEqual(intake.pending_checks(plan["intake"]), [])
        self.assertLessEqual(plan["intake"]["rounds"], 5)
        self.assertLessEqual(len(plan["intake"]["questions"]), 12)

    def test_answering_moves_the_axis_to_covered_and_grounds_its_prd_section(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        with _engine(_round):
            plan = P.ask(plan["id"])
        problem = next(row for row in plan["intake"]["questions"] if row["axis"] == "problem")
        plan = P.apply_edit(plan["id"], "answer", {"question": problem["id"], "text": "지난 화요일에 로그를 놓쳤어요"})
        self.assertEqual(plan["intake"]["coverage"]["problem"]["state"], "covered")
        self.assertEqual(plan["intake"]["questions"][0]["state"], "answered")
        self.assertIn("value", P.readiness(plan)["intake"]["grounded_sections"])

    def test_asking_stops_when_every_required_axis_is_settled(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        plan = P.mutate(
            plan["id"],
            lambda draft: [intake.mark(draft["intake"]["coverage"], axis, "covered") for axis in intake.REQUIRED_AXES],
        )
        self.assertFalse(P.readiness(plan)["intake"]["can_ask"])
        self.assertTrue(P.readiness(plan)["intake"]["ready"])
        self.assertEqual(P.next_step(plan)["action"], "draft_prd")
        with _engine(_round) as seen:
            plan = P.ask(plan["id"])
        self.assertEqual(seen["users"], [])  # 모델을 안 부른다


class TestAutoLane(unittest.TestCase):
    """질문 없이 PRD 초안 — 대신 가정을 꺼내고, 추측한 역할·환경을 안 적고, 사후 확인을 붙인다."""

    def test_creating_an_auto_plan_does_not_draft_the_prd_in_the_same_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            body = json.dumps({"idea": "회고 도구", "mode": "auto"}).encode()
            status, _, raw = surface.dispatch("POST", "/api/plans", body, root)
            view = json.loads(raw)
            self.assertEqual(status, 201)
            self.assertEqual(view["plan"]["intake"]["mode"], "auto")
            self.assertEqual(view["plan"]["prd"]["sections"]["overview"]["body"], "")
            self.assertEqual(view["next"]["action"], "draft_prd")

    def test_the_auto_draft_keeps_roles_and_environments_out_of_the_document(self):
        """역할은 기능 명세서가, 환경은 유저 플로우가 그대로 소비한다 — 추측 하나가 뒤 문서 둘로 번진다."""
        plan = P.set_mode(_seeded()["id"], "auto")
        with _engine(_PRD_REPLY) as seen:
            plan = P.draft_prd(plan["id"])
        self.assertIn("답을 못 들어서 제가 채웠어요", seen["systems"][0])
        self.assertEqual(plan["prd"]["attributes"]["roles"], [])
        self.assertEqual(plan["prd"]["attributes"]["environments"], [])
        self.assertEqual(plan["prd"]["attributes"]["category"], "협업 도구")

        axes = {item["axis"] for item in plan["intake"]["assumptions"]}
        self.assertIn("role", axes)
        self.assertIn("environment", axes)
        self.assertIn("success_signal", axes)

    def test_the_auto_draft_leaves_at_most_three_yes_no_checks_and_next_step_points_at_them(self):
        plan = P.set_mode(_seeded()["id"], "auto")
        with _engine(_PRD_REPLY):
            plan = P.draft_prd(plan["id"])
        checks = [row for row in plan["intake"]["questions"] if row["kind"] == "check"]
        self.assertEqual(len(checks), 1)
        self.assertLessEqual(len(checks), 3)
        self.assertEqual(checks[0]["stage"], "confirm")
        # PRD 를 쓴 뒤에도 확인 질문이 먼저다 — 지나치면 근거 없는 PRD 가 명세서의 입력이 된다
        self.assertEqual(P.next_step(plan)["action"], "answer")

        plan = P.apply_edit(plan["id"], "answer", {"question": checks[0]["id"], "text": "예"})
        self.assertTrue(any(item["confirmed"] for item in plan["intake"]["assumptions"]))
        # 추측을 맞다고 확인한 것은 근거가 아니다 — 축은 assumed 로 남고 그 칸은 근거 없는 칸이다
        self.assertEqual(plan["intake"]["coverage"]["user"]["state"], "assumed")
        self.assertEqual(P.readiness(plan)["intake"]["grounded_sections"], [])
        self.assertEqual(P.next_step(plan)["action"], "draft_spec")

    def test_the_guided_draft_keeps_the_old_marker_and_fills_the_attributes(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        plan = P.mutate(
            plan["id"],
            lambda draft: [
                intake.mark(draft["intake"]["coverage"], axis, "covered") for axis in ("role", "environment")
            ],
        )
        with _engine(_PRD_REPLY) as seen:
            plan = P.draft_prd(plan["id"])
        self.assertIn(" (확인 필요)", seen["systems"][0])
        self.assertNotIn("답을 못 들어서 제가 채웠어요", seen["systems"][0])
        self.assertEqual(plan["prd"]["attributes"]["roles"], ["스쿼드 리드"])
        self.assertEqual(plan["prd"]["attributes"]["environments"], ["웹"])
        # 답을 못 들은 축은 두 갈래 모두 가정으로 굳는다 — 근거 없는 칸을 그냥 두지 않는다
        self.assertEqual(plan["intake"]["coverage"]["problem"]["state"], "assumed")


class TestEngineChoice(unittest.TestCase):
    def test_the_plan_engine_reaches_resolve(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        plan = P.set_engine(plan["id"], "nvidia", "some/model")
        self.assertEqual(plan["engine"], {"provider": "nvidia", "model": "some/model"})
        with _engine(_round) as seen:
            P.ask(plan["id"])
        self.assertEqual(
            {key: seen["resolved"][0][key] for key in ("provider", "model")},
            {"provider": "nvidia", "model": "some/model"},
        )

    def test_an_empty_engine_falls_back_to_the_default_of_that_place(self):
        plan = P.set_mode(_seeded()["id"], "guided")
        with _engine(_round) as seen:
            P.ask(plan["id"])
        self.assertEqual(seen["resolved"][0]["provider"], None)
        self.assertEqual(seen["resolved"][0]["model"], None)

    def test_a_failure_names_the_engine_it_tried(self):
        """기획마다 다른 엔진을 걸 수 있게 된 순간, 이유에 엔진 이름이 없으면 손쓸 곳을 못 찾는다."""
        plan = P.set_mode(_seeded()["id"], "guided")
        P.set_engine(plan["id"], "nvidia", "some/model")
        with _engine(_round, missing=["API 키가 없어요"]):
            with self.assertRaisesRegex(RuntimeError, "nvidia · some/model"):
                P.ask(plan["id"])

        P.set_engine(plan["id"], "", "")
        with _engine(_round, missing=["API 키가 없어요"]):
            with self.assertRaisesRegex(RuntimeError, "기본"):
                P.ask(plan["id"])

    def test_a_broken_engine_comes_back_as_502_with_the_reason(self):
        with tempfile.TemporaryDirectory() as root:
            plan = P.set_mode(_seeded()["id"], "guided")
            P.set_engine(plan["id"], "nvidia", "some/model")
            with _engine(_round, missing=["API 키가 없어요"]):
                status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/ask", b"{}", root)
            self.assertEqual(status, 502)
            payload = json.loads(body)
            self.assertEqual(payload["error"]["code"], "planner_failed")
            self.assertIn("nvidia · some/model", payload["error"]["message"])


class TestOnboardingRoutes(unittest.TestCase):
    def test_the_mode_and_engine_routes_return_the_whole_view(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch(
                "POST", f"/api/plans/{plan['id']}/engine", b'{"provider":"nvidia","model":"m"}', root
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["plan"]["engine"], {"provider": "nvidia", "model": "m"})

            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/mode", b'{"mode":"guided"}', root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["next"]["action"], "ask")

            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/mode", b'{"mode":"auto"}', root)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "invalid_plan")

    def test_the_list_carries_the_axis_and_stage_tables_and_the_head_carries_the_engine(self):
        """화면이 표를 베껴 적으면 표가 둘이 되고, 언젠가 그중 하나만 고친다."""
        with tempfile.TemporaryDirectory() as root:
            plan = P.create_plan("회고 도구", mode="guided", engine={"provider": "nvidia", "model": "m"})
            P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?"]})
            status, _, body = surface.dispatch("GET", "/api/plans", root=root)
            payload = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual([row["id"] for row in payload["axes"]], list(intake.AXIS_IDS))
            self.assertEqual([row["id"] for row in payload["stages"]], list(intake.STAGE_IDS))

            head = payload["plans"][0]
            self.assertEqual(head["engine"], {"provider": "nvidia", "model": "m"})
            self.assertEqual((head["mode"], head["intake_asked"], head["intake_answered"]), ("guided", 1, 0))

    def test_the_readiness_intake_carries_what_the_conversation_turn_needs(self):
        with tempfile.TemporaryDirectory() as root:
            plan = P.set_mode(_seeded()["id"], "guided")
            with _engine(_round):
                P.ask(plan["id"])
            status, _, body = surface.dispatch("GET", f"/api/plans/{plan['id']}", root=root)
            onboarding = json.loads(body)["readiness"]["intake"]
            self.assertEqual(status, 200)
            for key in ("mode", "stage", "rounds", "coverage", "covered", "axes", "open_question"):
                self.assertIn(key, onboarding)
            self.assertEqual(len(onboarding["coverage"]), len(intake.AXIS_IDS))
            self.assertEqual(sorted(onboarding["open_question"]), ["axis", "id", "kind", "parent", "q", "stage"])

    def test_skip_goes_through_the_one_edit_door(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            plan = P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?"]})
            question = plan["intake"]["questions"][0]["id"]
            status, _, body = surface.dispatch(
                "POST",
                f"/api/plans/{plan['id']}/edit",
                json.dumps({"op": "intake.skip", "id": question}).encode(),
                root,
            )
            self.assertEqual(status, 200)
            self.assertIsNone(json.loads(body)["readiness"]["intake"]["open_question"])
            self.assertIn("intake.skip", P.OPS)


class TestPlannerMaterialization(unittest.TestCase):
    """모델의 임시 key를 저장소 id로 옮기는 자리 — 여기서 새면 저장소가 통째로 거부한다."""

    def test_items_are_linked_by_key_even_when_the_parent_comes_later(self):
        rows = [
            {"key": "f1", "level": 2, "parent": "r1", "title": "슬랙 수집", "criteria": ["채널을 고를 수 있다"]},
            {"key": "r1", "level": 1, "parent": "", "title": "회고 수집", "source": "overview"},
        ]
        items = planner._materialize_items(rows, ["스쿼드 리드"])
        by_title = {row["title"]: row for row in items}
        self.assertEqual(by_title["슬랙 수집"]["parent"], by_title["회고 수집"]["id"])
        self.assertEqual(by_title["회고 수집"]["source"], "overview")
        self.assertEqual(by_title["슬랙 수집"]["criteria"], ["채널을 고를 수 있다"])

    def test_items_that_would_be_refused_are_dropped_not_smuggled_through(self):
        """층과 부모가 어긋난 항목은 저장소가 어차피 막는다 — 여기서 조용히 떨어뜨린다."""
        rows = [
            {"key": "r1", "level": 1, "parent": "", "title": "뿌리"},
            {"key": "x", "level": 3, "parent": "", "title": "부모 없는 상세"},
            {"key": "y", "level": 1, "parent": "r1", "title": "부모 있는 요구사항"},
            {"key": "z", "level": 9, "title": "없는 층"},
        ]
        self.assertEqual([row["title"] for row in planner._materialize_items(rows, [])], ["뿌리"])

    def test_an_unknown_role_survives_but_a_known_one_is_snapped_to_the_prd_spelling(self):
        rows = [{"key": "r", "level": 1, "parent": "", "title": "t", "role": "SQUAD LEAD"}]
        self.assertEqual(planner._materialize_items(rows, ["Squad Lead"])[0]["role"], "Squad Lead")

    def test_a_second_start_node_is_demoted_rather_than_failing_the_whole_draft(self):
        payload = {
            "sections": [{"key": "s1", "title": "회고"}],
            "nodes": [
                {"key": "a", "type": "start", "title": "진입", "section": "s1"},
                {"key": "b", "type": "start", "title": "또 진입", "section": "s1", "source": "i-known"},
                {"key": "c", "type": "action", "title": "저장", "section": "nope", "source": "i-ghost"},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "b"}, {"from": "a", "to": "gone"}],
        }
        flow = planner._materialize_flow(payload, {"i-known"})
        self.assertEqual([node["type"] for node in flow["nodes"]], ["start", "page", "action"])
        # 없는 기능·없는 구획을 가리키는 값은 지운다: 가리키는 곳이 없는 링크는 거짓말이다
        self.assertEqual(flow["nodes"][1]["source"], "i-known")
        self.assertEqual(flow["nodes"][2]["source"], "")
        self.assertEqual(flow["nodes"][2]["section"], "")
        self.assertEqual(len(flow["edges"]), 1)

    def test_a_materialized_draft_is_accepted_by_the_store_as_is(self):
        plan = _with_overview(_seeded())
        items = planner._materialize_items(
            [
                {"key": "r", "level": 1, "parent": "", "title": "회고 수집"},
                {"key": "f", "level": 2, "parent": "r", "title": "슬랙 수집"},
            ],
            [],
        )
        plan = P.mutate(plan["id"], lambda draft: draft["spec"].__setitem__("items", items))
        flow = planner._materialize_flow(
            {
                "sections": [{"key": "s", "title": "회고"}],
                "nodes": [
                    {"key": "a", "type": "start", "title": "진입", "section": "s"},
                    {"key": "b", "type": "page", "title": "목록", "section": "s", "source": items[1]["id"]},
                ],
                "edges": [{"from": "a", "to": "b", "label": "열기"}],
            },
            {row["id"] for row in items},
        )
        plan = P.mutate(plan["id"], lambda draft: draft.__setitem__("flow", flow))
        self.assertEqual(P.readiness(plan)["flow"], {"ready": True, "nodes": 2, "edges": 1, "blocked": []})

    def test_json_is_read_out_of_a_fenced_reply(self):
        self.assertEqual(planner._parse('```json\n{"a": 1}\n```')["a"], 1)
        with self.assertRaises(ValueError):
            planner._parse("죄송하지만 도와드릴 수 없습니다")


class TestDispatch(unittest.TestCase):
    def test_this_module_serves_data_not_a_second_planning_page(self):
        """기획 화면은 Studio 하나다 — 이 표면은 데이터만 낸다."""
        self.assertEqual(surface.dispatch("GET", "/")[0], 404)
        self.assertEqual(surface.dispatch("GET", "/index.html")[0], 404)
        self.assertFalse(hasattr(surface, "render_html"))

    def test_logo_and_health_routes(self):
        status, ctype, body = surface.dispatch("GET", "/asset/logo")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

        status, ctype, body = surface.dispatch("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(body), {"ok": True, "surface": "plan"})

    def test_head_is_allowed_but_mutation_and_unknown_routes_are_not(self):
        self.assertEqual(surface.dispatch("HEAD", "/health")[0], 200)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(surface.dispatch(method, "/")[0], 405)
        self.assertEqual(surface.dispatch("GET", "/missing")[0], 404)

    def test_one_round_trip_carries_the_document_progress_and_next_step(self):
        """나눠 주면 왕복마다 어긋난다 — 화면은 한 번에 받는다."""
        with tempfile.TemporaryDirectory() as root:
            status, _, body = surface.dispatch("POST", "/api/plans", b'{"idea":"\xed\x9a\x8c\xea\xb3\xa0"}', root)
            self.assertEqual(status, 201)
            view = json.loads(body)
            self.assertEqual(sorted(view), ["grades", "next", "plan", "readiness", "review", "tree"])
            plan_id = view["plan"]["id"]

            status, _, body = surface.dispatch("GET", f"/api/plans/{plan_id}", root=root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["next"]["action"], "choose_mode")

            status, _, body = surface.dispatch("GET", "/api/plans", root=root)
            head = json.loads(body)["plans"][0]
            self.assertEqual((head["prd_filled"], head["prd_total"], head["features"]), (0, 5, 0))

    def test_edits_go_through_one_door_and_unknown_ones_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch(
                "POST",
                f"/api/plans/{plan['id']}/edit",
                json.dumps({"op": "section", "section": "overview", "body": "- 한 줄"}).encode(),
                root,
            )
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["readiness"]["spec"]["ready"])

            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/edit", b'{"op":"nope"}', root)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "unknown_edit")

    def test_generating_a_downstream_document_too_early_is_409_not_400(self):
        """재료가 없어 못 만드는 것은 잘못된 요청이 아니라 **아직 이른 요청**이다."""
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/spec", b"{}", root)
            self.assertEqual(status, 409)
            payload = json.loads(body)
            self.assertEqual(payload["error"]["code"], "not_ready")
            self.assertIn("개요", payload["error"]["message"])

            _with_overview(plan)
            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/flow", b"{}", root)
            self.assertEqual(status, 409)
            self.assertIn("기능", json.loads(body)["error"]["message"])

    def test_unknown_actions_and_missing_plans_are_named(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/teleport", b"{}", root)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "unknown_action")

            status, _, body = surface.dispatch("GET", "/api/plans/nope", root=root)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "plan_not_found")

    def test_put_guards_the_revision_and_the_path_id(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch("PUT", f"/api/plans/{plan['id']}", json.dumps(plan).encode(), root)
            self.assertEqual(status, 200)
            status, _, body = surface.dispatch("PUT", f"/api/plans/{plan['id']}", json.dumps(plan).encode(), root)
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(body)["error"]["code"], "plan_conflict")

            status, _, _ = surface.dispatch("PUT", "/api/plans/other", json.dumps(plan).encode(), root)
            self.assertEqual(status, 400)

    def test_delete_removes_the_plan_and_returns_the_remaining_list(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/delete", b"{}", root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["plans"], [])


class TestHostGuard(unittest.TestCase):
    def test_loopback_allowed(self):
        for host in ("127.0.0.1", "127.0.0.1:8767", "localhost:8767", "[::1]:8767", "LOCALHOST"):
            self.assertTrue(surface.host_allowed(host), host)

    def test_external_rejected(self):
        for host in (None, "", "evil.example", "evil.example:8767", "10.0.0.5:80"):
            self.assertFalse(surface.host_allowed(host), repr(host))

    def test_origin_must_be_loopback_when_present(self):
        self.assertTrue(surface.origin_allowed(None))
        self.assertTrue(surface.origin_allowed("http://127.0.0.1:8767"))
        self.assertFalse(surface.origin_allowed("https://evil.example"))


class TestLiveServer(unittest.TestCase):
    def test_roundtrip_security_headers_and_mutation_guard(self):
        with tempfile.TemporaryDirectory() as root:
            httpd = surface._bind("127.0.0.1", 0, root)
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["surface"], "plan")
                    self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

                evil_host = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.example"})
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(evil_host, timeout=5)
                self.assertEqual(rejected.exception.code, 403)

                untrusted = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/plans",
                    data=b'{"idea":"x"}',
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(untrusted, timeout=5)
                self.assertEqual(rejected.exception.code, 403)

                trusted = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/plans",
                    data=json.dumps({"idea": "새 기획"}).encode(),
                    headers={"Content-Type": "application/json", "X-Asgard-Plan": "1"},
                )
                with urllib.request.urlopen(trusted, timeout=5) as response:
                    self.assertEqual(response.status, 201)
                    self.assertEqual(json.loads(response.read())["plan"]["title"], "새 기획")
            finally:
                httpd.shutdown()
                httpd.server_close()


class TestReviewInTheView(unittest.TestCase):
    """심사는 한 왕복에 같이 온다 — 화면이 점수를 따로 물으면 문서와 점수가 어긋난 순간이 생긴다."""

    def test_the_view_carries_the_review_card_and_the_grade_names(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch("GET", f"/api/plans/{plan['id']}", root=root)
            self.assertEqual(status, 200)
            view = json.loads(body)
            card = view["review"]
            self.assertEqual(sorted(card), ["assumptions", "blocking", "findings", "grade", "score", "sections"])
            # 지적이 하나도 없는 칸도 들어간다 — 화면이 배지를 못 다는 칸이 있으면 안 된다.
            self.assertEqual(sorted(card["sections"]), sorted(P.PRD_SECTION_IDS))
            self.assertEqual((card["score"], card["grade"]), (view["readiness"]["prd"]["score"], "draft"))
            # 등급 이름표는 서버가 든다 — 화면이 HTML 에 베껴 적으면 정본이 둘이 된다.
            self.assertEqual(sorted(view["grades"]), sorted(P.GRADES))
            self.assertEqual(view["grades"]["draft"], P.GRADE_LABEL["draft"])

    def test_a_low_score_does_not_close_the_next_document(self):
        """심사는 보여 주는 장치다 — 기능 명세서를 여는 판정은 그대로 개요 한 칸이다."""
        with tempfile.TemporaryDirectory() as root:
            plan = _with_overview(_seeded())
            view = json.loads(surface.dispatch("GET", f"/api/plans/{plan['id']}", root=root)[2])
            self.assertLess(view["review"]["score"], 100)
            self.assertEqual(view["review"]["blocking"], 0)
            self.assertTrue(view["readiness"]["spec"]["ready"])


class TestRefineLanes(unittest.TestCase):
    """다듬기 세 갈래 — `scope`와 `selection`이 어느 문으로 가는지가 계약이다."""

    @contextlib.contextmanager
    def _lanes(self):
        """세 제안 함수를 이름표로 바꿔 끼운다 — 무엇이 불렸고 무엇으로 불렸는지만 본다."""
        seen: dict = {}

        def note(name):
            def call(*args, **kwargs):
                seen[name] = (args, kwargs)
                return {"lane": name}

            return call

        with (
            mock.patch.object(build, "propose_document", note("document")),
            mock.patch.object(build, "propose_section", note("section")),
            mock.patch.object(build, "propose_selection", note("selection")),
        ):
            yield seen

    def _refine(self, plan_id: str, payload: dict, root: str):
        return surface.dispatch("POST", f"/api/plans/{plan_id}/refine", json.dumps(payload).encode(), root)

    def test_document_scope_takes_the_whole_document(self):
        with tempfile.TemporaryDirectory() as root, self._lanes() as seen:
            plan = _seeded()
            status, _, body = self._refine(plan["id"], {"scope": "document", "request": "말투를 맞춰 줘"}, root)
            self.assertEqual((status, json.loads(body)), (200, {"lane": "document"}))
            self.assertEqual(seen["document"][0][:2], (plan["id"], "말투를 맞춰 줘"))
            self.assertEqual(sorted(seen), ["document"])

    def test_a_selection_wins_over_the_section_lane(self):
        """좁은 범위가 우선한다 — 고른 글이 들어오면 칸 전체를 다시 쓰지 않는다."""
        with tempfile.TemporaryDirectory() as root, self._lanes() as seen:
            plan = _seeded()
            payload = {"section": "overview", "request": "짧게", "selection": "한 줄"}
            status, _, body = self._refine(plan["id"], payload, root)
            self.assertEqual((status, json.loads(body)), (200, {"lane": "selection"}))
            self.assertEqual(seen["selection"][0][:4], (plan["id"], "overview", "짧게", "한 줄"))
            self.assertEqual(sorted(seen), ["selection"])

    def test_the_section_lane_never_gets_the_selection(self):
        """칸 전체 프롬프트는 대체 본문을 요구한다 — 고른 글을 함께 넘기면 칸이 그 뜻으로 다시 쓰인다."""
        with tempfile.TemporaryDirectory() as root, self._lanes() as seen:
            plan = _seeded()
            status, _, body = self._refine(plan["id"], {"section": "overview", "request": "짧게"}, root)
            self.assertEqual((status, json.loads(body)), (200, {"lane": "section"}))
            self.assertEqual(seen["section"][0][:4], (plan["id"], "overview", "짧게", ""))
            self.assertEqual(sorted(seen), ["section"])

    def test_a_selection_outside_the_body_is_400_before_the_model_runs(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _with_overview(_seeded())
            payload = {"section": "overview", "request": "짧게", "selection": "본문에 없는 글"}
            status, _, body = self._refine(plan["id"], payload, root)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "invalid_plan")


class TestExportRoute(unittest.TestCase):
    """내보내기는 읽기다 — JSON 관문 밖의 GET 이고 본문은 마크다운 원문이다."""

    def test_export_answers_markdown_from_the_one_source(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _with_overview(_seeded())
            status, ctype, body = surface.dispatch("GET", f"/api/plans/{plan['id']}/export", root=root)
            self.assertEqual(status, 200)
            self.assertEqual(ctype, "text/markdown; charset=utf-8")
            text = body.decode("utf-8")
            self.assertEqual(text, P.to_markdown(P.load_plan(plan["id"])))
            self.assertTrue(text.startswith("# "))
            for heading in ("## 개요", "## 속성", "## 가정", "## 심사"):
                self.assertIn(heading, text)

    def test_head_is_allowed_and_a_missing_plan_is_404(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            self.assertEqual(surface.dispatch("HEAD", f"/api/plans/{plan['id']}/export", root=root)[0], 200)
            status, _, body = surface.dispatch("GET", "/api/plans/nope/export", root=root)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "plan_not_found")

    def test_export_is_not_a_write(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            status, _, body = surface.dispatch("POST", f"/api/plans/{plan['id']}/export", b"{}", root)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "unknown_action")


class TestSectionsEdit(unittest.TestCase):
    """문서 전체 제안을 받는 자리 — 여러 칸이 **한 개정에** 저장된다."""

    def _edit(self, plan_id: str, payload: dict, root: str):
        return surface.dispatch("POST", f"/api/plans/{plan_id}/edit", json.dumps(payload).encode(), root)

    def test_many_sections_land_in_one_revision(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            before = plan["revision"]
            payload = {"op": "sections", "sections": {"overview": "- 한 줄", "value": "- 값"}}
            status, _, body = self._edit(plan["id"], payload, root)
            self.assertEqual(status, 200)
            view = json.loads(body)
            sections = view["plan"]["prd"]["sections"]
            self.assertEqual((sections["overview"]["body"], sections["value"]["body"]), ("- 한 줄", "- 값"))
            self.assertEqual(view["plan"]["revision"], before + 1)
            self.assertEqual(view["readiness"]["prd"]["filled"], 2)

    def test_one_unknown_section_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            plan = _seeded()
            payload = {"op": "sections", "sections": {"overview": "- 한 줄", "teleport": "- 없는 칸"}}
            status, _, body = self._edit(plan["id"], payload, root)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "invalid_plan")
            self.assertEqual(P.load_plan(plan["id"])["prd"]["sections"]["overview"]["body"], "")


if __name__ == "__main__":
    unittest.main()
