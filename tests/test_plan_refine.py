"""PRD 다듬기의 두 갈래 — 문서 전체와 고른 구간.

여태 다듬기는 칸 하나짜리 하나뿐이었고, `selection`을 받아도 프롬프트가 전체 대체 본문을
요구해서 결국 칸 전체가 갈렸다. 여기서 재는 것은 그 갈림이다: **문서 전체는 고친 칸만 내고,
구간 수정은 그 구간의 대체 글만 낸다.** 그리고 둘 다 제안이므로 저장소를 건드리면 안 된다 —
`revision`이 그대로인지가 그 판정이다.

모델은 `test_plan_api._engine`과 같은 자리에서 가짜로 세운다(`providers.resolve` ·
`oneshot.complete_with`). `planner._complete`이 그 둘로만 밖에 닿기 때문에 시임이 하나면 된다.
"""

import contextlib
import json
import types
import unittest
from unittest import mock

from asgard import plan as P
from asgard.plan import build, planner


@contextlib.contextmanager
def _engine(reply, missing=()):
    """모델 호출 자리를 가로챈다 — 무슨 프롬프트가 갔는지를 남긴다.

    `reply`가 함수면 모델에 간 user 페이로드(dict)를 받아 응답 dict를 돌려준다."""
    seen: dict = {"systems": [], "users": []}

    def fake_resolve(root=None, provider=None, model=None):
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


_BODY = {section: f"- {section} 첫 줄이에요\n- {section} 둘째 줄이에요" for section in P.PRD_SECTION_IDS}


def _prd_plan(bodies: dict | None = None) -> dict:
    """다섯 칸이 다 찬 기획 하나."""
    plan = P.create_plan("팀 회고를 자동으로 모아 주는 도구")
    for section, body in (bodies or _BODY).items():
        plan = P.apply_edit(plan["id"], "section", {"section": section, "body": body})
    return plan


class TestDocumentRefine(unittest.TestCase):
    def test_the_document_proposal_carries_only_the_sections_that_change(self):
        """빈 본문·원문과 같은 본문·형상 밖 칸은 제안에 안 들어간다.

        칸 다섯 개짜리 카드 묶음에서 세 장이 '바뀐 게 없음'이면 사람은 어느 장을 봐야 하는지
        모른다. 걸러 내는 자리는 `planner.refine_document`이고 화면이 아니다."""
        plan = _prd_plan()
        reply = {
            "summary": "말투를 맞췄어요",
            "sections": {
                "overview": {"body": "- 개요를 다시 썼어요", "note": "말투를 맞췄어요"},
                "value": {"body": "", "note": "고칠 것이 없었어요"},  # 빈 본문
                "target": {"body": _BODY["target"], "note": "그대로"},  # 원문과 같음
                "success": None,  # 형상 밖
                "attributes": {"note": "본문이 없음"},  # body 자체가 없음
                "bogus": {"body": "- 모르는 칸이에요"},  # 표 밖의 sid
            },
        }
        with _engine(reply):
            result = build.propose_document(plan["id"])

        self.assertEqual([row["section"] for row in result["sections"]], ["overview"])
        row = result["sections"][0]
        self.assertEqual(row["label"], "개요")
        self.assertEqual(row["before"], _BODY["overview"])
        self.assertEqual(row["body"], "- 개요를 다시 썼어요")
        self.assertEqual(row["note"], "말투를 맞췄어요")
        self.assertEqual(result["summary"], "말투를 맞췄어요")

    def test_the_document_proposal_keeps_the_document_order(self):
        """카드 순서는 문서 순서다 — 모델이 낸 순서로 두면 같은 문서가 부를 때마다 다르게 뜬다."""
        plan = _prd_plan()
        reply = {
            "summary": "",
            "sections": {
                "success": {"body": "- 성공 지표를 숫자로 적었어요", "note": ""},
                "overview": {"body": "- 개요를 다시 썼어요", "note": ""},
            },
        }
        with _engine(reply):
            result = build.propose_document(plan["id"], "숫자를 붙여 주세요")
        self.assertEqual([row["section"] for row in result["sections"]], ["overview", "success"])

    def test_an_empty_request_falls_back_to_the_default_direction(self):
        """방향을 안 적고 눌러도 돈다 — 빈 요청을 그대로 모델에 보내지 않는다."""
        plan = _prd_plan()
        with _engine({"summary": "", "sections": {}}) as seen:
            result = build.propose_document(plan["id"], "   ")
        self.assertEqual(result["sections"], [])  # 고칠 것이 없으면 빈 목록이고 실패가 아니다
        self.assertEqual(seen["users"][-1]["request"], build._DOCUMENT_REQUEST)
        self.assertIn("일관성", seen["users"][-1]["request"])

    def test_the_document_prompt_carries_all_five_sections_and_the_settled_decisions(self):
        """다섯 칸을 한 번에 읽어야 칸끼리 어긋난 자리가 보인다. 확정한 답도 프롬프트에 같이
        들어간다 — 문서 전체를 다시 쓰는 갈래라 사람이 정한 것이 조용히 지워질 수 있다."""
        plan = _prd_plan()
        with _engine({"summary": "", "sections": {}}) as seen:
            build.propose_document(plan["id"])
        payload = seen["users"][-1]
        self.assertEqual([row["id"] for row in payload["sections"]], list(P.PRD_SECTION_IDS))
        self.assertEqual(payload["sections"][0]["body"], _BODY["overview"])
        self.assertIn("decided", payload)
        self.assertIn("confirmed_assumptions", payload)
        self.assertIn("STRICT JSON", seen["systems"][-1])

    def test_a_malformed_document_reply_is_a_failure_not_an_empty_proposal(self):
        """`sections`가 형상 밖이면 '고칠 것이 없다'가 아니라 실패다 — 둘을 같게 두면 모델이
        고장 난 것을 사람이 '다 괜찮대요'로 읽는다."""
        plan = _prd_plan()
        with _engine({"summary": "다 괜찮아요"}), self.assertRaises(ValueError):
            build.propose_document(plan["id"])

    def test_the_document_proposal_does_not_touch_the_store(self):
        """제안은 저장하지 않는다 — 반영은 사람이 누른다."""
        plan = _prd_plan()
        before = P.load_plan(plan["id"])
        reply = {"summary": "", "sections": {sid: {"body": f"- {sid} 갈아엎었어요", "note": ""} for sid in _BODY}}
        with _engine(reply):
            result = build.propose_document(plan["id"])
        after = P.load_plan(plan["id"])
        self.assertEqual(len(result["sections"]), len(P.PRD_SECTION_IDS))
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual({sid: after["prd"]["sections"][sid]["body"] for sid in _BODY}, _BODY)


class TestSelectionRefine(unittest.TestCase):
    def test_a_selection_that_is_not_in_the_body_is_rejected_before_the_model_runs(self):
        """본문에 없는 구간은 어디에 앉힐지 정할 수 없다. 모델을 부르기 전에 막는다 —
        부르고 나서 막으면 사용자는 기다린 뒤에 같은 실패를 본다."""
        plan = _prd_plan()
        with _engine({"replacement": "- 새 줄이에요", "note": ""}) as seen:
            with self.assertRaises(ValueError):
                build.propose_selection(plan["id"], "overview", "짧게", "본문에 없는 문장이에요")
            with self.assertRaises(ValueError):
                build.propose_selection(plan["id"], "overview", "짧게", "")
            with self.assertRaises(ValueError):
                build.propose_selection(plan["id"], "bogus", "짧게", "- overview 첫 줄이에요")
        self.assertEqual(seen["users"], [])

    def test_the_selection_span_points_at_the_first_occurrence(self):
        """같은 글이 두 번 나오면 첫 자리를 쓴다 — 자리를 안 정하면 반영이 엉뚱한 구간을 덮는다."""
        body = "- 같은 줄이에요\n- 다른 줄이에요\n- 같은 줄이에요"
        plan = _prd_plan({**_BODY, "value": body})
        with _engine({"replacement": "고친 줄이에요", "note": "짧게 줄였어요"}):
            result = build.propose_selection(plan["id"], "value", "짧게", "같은 줄이에요")

        self.assertEqual((result["start"], result["end"]), (2, 2 + len("같은 줄이에요")))
        self.assertEqual(result["before"], body)
        self.assertEqual(result["before"][result["start"] : result["end"]], result["selection"])
        self.assertEqual(result["replacement"], "고친 줄이에요")
        self.assertEqual(result["note"], "짧게 줄였어요")
        self.assertEqual(result["section"], "value")
        # 이 갈래가 칸 전체를 내면 화면이 안 고른 자리까지 갈아 버린다
        self.assertNotIn("body", result)
        # 화면이 하는 일과 같은 계산 — 뒤에 있는 같은 글은 그대로 남아야 한다
        spliced = body[: result["start"]] + result["replacement"] + body[result["end"] :]
        self.assertEqual(spliced, "- 고친 줄이에요\n- 다른 줄이에요\n- 같은 줄이에요")

    def test_the_selection_prompt_carries_the_surrounding_text_as_context_only(self):
        """앞뒤 글은 프롬프트에 들어가지만 돌려받지 않는다. 길이 상한도 프롬프트에 들어간다."""
        body = "- 첫 줄이에요\n- 가운데 줄이에요\n- 끝 줄이에요"
        plan = _prd_plan({**_BODY, "success": body})
        selection = "가운데 줄이에요"
        with _engine({"replacement": "- 가운데를 고쳤어요", "note": ""}) as seen:
            build.propose_selection(plan["id"], "success", "숫자를 붙여 주세요", selection)

        payload = seen["users"][-1]
        self.assertEqual(payload["selection"], selection)
        self.assertEqual(payload["text_before"], "- 첫 줄이에요\n- ")
        self.assertEqual(payload["text_after"], "\n- 끝 줄이에요")
        self.assertEqual(payload["max_chars"], len(selection) * 3)
        self.assertEqual(payload["section_label"], "성공 지표")
        self.assertIn("three times the length", seen["systems"][-1])
        self.assertNotIn("full replacement body", seen["systems"][-1])

    def test_an_empty_replacement_is_a_failure(self):
        """빈 대체 글을 그대로 돌려주면 화면이 고른 구간을 지워 버린다."""
        plan = _prd_plan()
        with _engine({"replacement": "  ", "note": "지웠어요"}), self.assertRaises(ValueError):
            build.propose_selection(plan["id"], "overview", "짧게", "- overview 첫 줄이에요")

    def test_the_selection_proposal_does_not_touch_the_store(self):
        plan = _prd_plan()
        before = P.load_plan(plan["id"])
        with _engine({"replacement": "- 훨씬 짧게요", "note": ""}):
            build.propose_selection(plan["id"], "overview", "짧게", "- overview 첫 줄이에요")
        after = P.load_plan(plan["id"])
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["prd"]["sections"]["overview"]["body"], _BODY["overview"])


class TestPlannerContract(unittest.TestCase):
    def test_the_two_lanes_use_different_prompts_from_the_section_lane(self):
        """칸 다듬기 프롬프트는 전체 대체 본문을 요구한다. 그 프롬프트를 구간 수정에 그대로
        쓰면 selection 을 같이 보내도 칸 전체가 갈린다 — 그것이 이 갈래를 나눈 이유다."""
        self.assertIn("full replacement body", planner._REFINE_SYS)
        self.assertNotIn("full replacement body", planner._SELECTION_SYS)
        self.assertIn("replacement for that passage only", planner._SELECTION_SYS)
        self.assertIn("Omit every section you leave alone", planner._DOCUMENT_SYS)
        for system in (planner._DOCUMENT_SYS, planner._SELECTION_SYS):
            self.assertIn(planner._HONESTY, system)
            self.assertIn(planner._LANGUAGE, system)
            self.assertIn(planner._JSON_ONLY, system)

    def test_refine_selection_rejects_a_section_outside_the_table(self):
        plan = _prd_plan()
        with self.assertRaises(ValueError):
            planner.refine_selection("", plan, "bogus", "짧게", "- overview 첫 줄이에요")


if __name__ == "__main__":
    unittest.main()
