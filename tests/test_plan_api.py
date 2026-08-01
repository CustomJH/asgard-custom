"""기획 — 문서 셋의 형상·접지 게이트·편집 연산, 그리고 그 위의 루프백 계약.

이 파일이 지키는 불변식 하나: **뒤 문서는 앞 문서가 비면 만들어지지 않는다.** 규칙이라서가
아니라 재료가 없어서다. 나머지 검사는 그 불변식이 어디서도 새지 않는지를 본다 —
저장소에서도(`readiness`), 도메인 호출에서도(`require_ready`), HTTP 에서도(409).
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from asgard import plan as P
from asgard.commands import plan_api as surface
from asgard.plan import planner


def _seeded(idea: str = "팀 회고를 자동으로 모아 주는 도구", root: str = "") -> dict:
    return P.create_plan(idea, root=root)


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
        self.assertEqual(P.next_step(plan)["action"], "ask")
        plan = P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?"]})
        self.assertEqual(P.next_step(plan)["action"], "draft_prd")
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
        """문답이 대화 밖에 있으면 맥락이 갈린다 — 모델이 읽는 것과 사람이 보는 것이 달라진다."""
        plan = _seeded()
        plan = P.apply_edit(plan["id"], "questions", {"questions": ["누가 쓰나요?", "지금은 어떻게 하나요?"]})
        first = plan["intake"]["questions"][0]["id"]
        plan = P.apply_edit(plan["id"], "answer", {"question": first, "text": "스쿼드 리드"})
        self.assertEqual(plan["intake"]["questions"][0]["a"], "스쿼드 리드")
        self.assertIn("스쿼드 리드", plan["chat"][-1]["text"])
        self.assertEqual(P.readiness(plan)["intake"], {"ready": True, "asked": 2, "answered": 1, "blocked": []})

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
            self.assertEqual(sorted(view), ["next", "plan", "readiness", "tree"])
            plan_id = view["plan"]["id"]

            status, _, body = surface.dispatch("GET", f"/api/plans/{plan_id}", root=root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["next"]["action"], "ask")

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


if __name__ == "__main__":
    unittest.main()
