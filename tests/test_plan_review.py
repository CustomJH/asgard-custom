"""PRD 심사·내보내기·다중 칸 편집.

이 파일이 지키는 불변식 둘:
  · 심사는 **판정을 안 바꾼다** — 점수가 아무리 낮아도 개요가 차면 기능 명세서가 열린다.
  · 같은 문서는 늘 같은 점수를 낸다 — 모델을 안 부르므로 왕복마다 값이 흔들릴 자리가 없다.
"""

import unittest

from asgard import plan as P
from asgard.plan import intake

# `asgard.plan.review` 라는 이름은 패키지에서 **함수**다(`__init__` 이 그 이름으로 내보낸다).
# 모듈 안의 다른 값이 필요하면 여기처럼 모듈에서 직접 들여온다.
from asgard.plan.review import CHECK_IDS, REVIEW_CHECKS, checks_table, review


def _plan(**bodies) -> dict:
    """다섯 칸 중 준 칸만 채운 기획 하나 — 저장은 안 한다(심사는 순수 함수다)."""
    plan = P.new_plan("팀 회고를 자동으로 모아 주는 도구")
    for sid, body in bodies.items():
        plan["prd"]["sections"][sid]["body"] = body
    return plan


def _covered(plan: dict, *axes: str) -> dict:
    for axis in axes or intake.AXIS_IDS:
        intake.mark(plan["intake"]["coverage"], axis, "covered", source="q-1")
    return plan


def _ids(card: dict, section: str = "") -> list[str]:
    return [row["id"] for row in card["findings"] if not section or row["section"] == section]


_GOOD = {
    "overview": "회고를 자동으로 모아요.\n지금 만드는 이유는 수집이 손으로 돌기 때문이에요.",
    "value": "문제는 회고 기록이 흩어진다는 것이에요.\n우리는 채널에서 바로 모아요.",
    "target": "스쿼드 리드가 주간 회고 직후에 열어요.\n시나리오는 슬랙에서 시작해요.",
    "success": "회고 참여율을 40%에서 70%로 3개월 안에 올려요.\n위험은 채널 권한이에요.",
    "attributes": "협업 도구예요.\n웹에서 돌아요.",
}


def _solid() -> dict:
    plan = _covered(_plan(**_GOOD))
    plan["prd"]["attributes"] = {"category": "협업 도구", "roles": ["스쿼드 리드"], "environments": ["웹"]}
    return plan


class TestReviewChecks(unittest.TestCase):
    def test_a_clean_prd_has_nothing_to_say(self):
        card = review(_solid())
        self.assertEqual(card["findings"], [])
        self.assertEqual((card["score"], card["grade"], card["blocking"]), (100, "solid", 0))

    def test_an_empty_box_is_reported_and_only_the_overview_blocks(self):
        card = review(_plan())
        self.assertEqual(_ids(card, "overview"), ["section.empty"])
        self.assertEqual(_ids(card, "value"), ["section.empty"])
        self.assertEqual([row["severity"] for row in card["findings"] if row["id"] == "section.empty"][0], "block")
        self.assertEqual(card["blocking"], 1)
        self.assertNotIn("section.empty", _ids(review(_solid())))

    def test_a_one_line_box_is_thin_but_the_attributes_box_is_not(self):
        plan = _covered(_plan(**{**_GOOD, "value": "회고 기록이 흩어져요.", "attributes": "협업 도구예요."}))
        plan["prd"]["attributes"] = {"category": "협업 도구", "roles": ["리드"], "environments": ["웹"]}
        card = review(plan)
        self.assertIn("section.thin", _ids(card, "value"))
        # 속성 설정은 산문이 아니라 값이 든 칸이라 줄 수로 재지 않는다
        self.assertNotIn("section.thin", _ids(card, "attributes"))
        self.assertNotIn("section.thin", _ids(review(_solid())))

    def test_a_success_metric_without_a_number_cannot_be_measured(self):
        plan = _covered(_plan(**{**_GOOD, "success": "회고가 활발해지면 성공이에요.\n분기마다 봐요."}))
        self.assertIn("success.unmeasurable", _ids(review(plan), "success"))
        self.assertNotIn("success.unmeasurable", _ids(review(_solid()), "success"))

    def test_a_success_metric_without_a_timeframe_is_only_a_note(self):
        plan = _covered(_plan(**{**_GOOD, "success": "참여율 40%를 70%로 올려요.\n위험은 권한이에요."}))
        card = review(plan)
        self.assertIn("success.no_timeframe", _ids(card, "success"))
        self.assertEqual([row["severity"] for row in card["findings"] if row["id"] == "success.no_timeframe"], ["note"])
        # 기준선·목표·기한 셋이 다 있는 칸은 조용하다
        self.assertNotIn("success.no_timeframe", _ids(review(_solid()), "success"))

    def test_roles_and_environments_are_checked_apart_from_the_body(self):
        plan = _covered(_plan(**_GOOD))
        plan["prd"]["attributes"] = {"category": "협업 도구", "roles": [], "environments": []}
        card = review(plan)
        self.assertEqual(_ids(card, "attributes"), ["attributes.roles_missing", "attributes.environments_missing"])
        self.assertNotIn("attributes.roles_missing", _ids(review(_solid())))

    def test_a_check_marker_left_in_the_body_is_counted(self):
        body = "스쿼드 리드가 열어요. (확인 필요)\n주간 회고 직후예요. (확인 필요 — 답을 못 들었어요)"
        plan = _covered(_plan(**{**_GOOD, "target": body}))
        plan["prd"]["attributes"] = {"category": "협업 도구", "roles": ["리드"], "environments": ["웹"]}
        card = review(plan)
        marker = [row for row in card["findings"] if row["id"] == "marker.unresolved"]
        self.assertEqual(len(marker), 1)
        self.assertIn("2군데", marker[0]["detail"])
        self.assertEqual(card["sections"]["target"]["markers"], 2)
        self.assertNotIn("marker.unresolved", _ids(review(_solid())))

    def test_an_unconfirmed_assumption_is_a_finding_of_the_whole_document(self):
        plan = _solid()
        intake.note_assumption(plan["intake"], "success_signal")
        card = review(plan)
        found = [row for row in card["findings"] if row["id"] == "assumption.unconfirmed"]
        self.assertEqual((len(found), found[0]["section"]), (1, ""))
        self.assertIn("1건", found[0]["detail"])
        self.assertEqual(card["assumptions"][0]["section"], intake.AXIS_SECTION["success_signal"])
        self.assertFalse(card["assumptions"][0]["confirmed"])

        plan["intake"]["assumptions"][0]["confirmed"] = True
        self.assertNotIn("assumption.unconfirmed", _ids(review(plan)))

    def test_a_box_no_answer_grounds_is_marked_as_written_by_the_draft(self):
        """근거 판정은 `intake.grounded_sections` 가 정본이다 — 여기서 표를 다시 적지 않는다."""
        plan = _plan(**_GOOD)
        plan["prd"]["attributes"] = {"category": "협업 도구", "roles": ["리드"], "environments": ["웹"]}
        card = review(plan)
        self.assertIn("section.ungrounded", _ids(card, "value"))
        self.assertFalse(card["sections"]["value"]["grounded"])

        card = review(_solid())
        self.assertNotIn("section.ungrounded", _ids(card))
        self.assertTrue(card["sections"]["value"]["grounded"])

    def test_every_check_id_is_in_the_exported_table(self):
        """화면이 표를 베껴 적지 않게 내보내는 값 — 이름이 갈리면 칩에 빈 이름이 뜬다."""
        plan = _plan(**{**_GOOD, "success": "잘 되면 좋아요."})
        intake.note_assumption(plan["intake"], "problem")
        card = review(plan)
        self.assertLessEqual({row["id"] for row in card["findings"]}, set(CHECK_IDS))
        self.assertEqual([row["id"] for row in checks_table()], list(CHECK_IDS))
        self.assertEqual(P.REVIEW_CHECKS, REVIEW_CHECKS)
        for row in card["findings"] + review(_plan())["findings"]:
            self.assertTrue(row["label"] and row["detail"] and row["fix"])
            self.assertIn(row["severity"], ("block", "warn", "note"))


class TestGrades(unittest.TestCase):
    def test_the_three_grades_come_from_the_severities(self):
        draft = review(_plan())
        self.assertEqual((draft["grade"], draft["blocking"] > 0), ("draft", True))

        plan = _covered(_plan(**{**_GOOD, "success": "회고가 활발해지면 좋아요.\n위험은 권한이에요."}))
        plan["prd"]["attributes"] = {"category": "협업 도구", "roles": ["리드"], "environments": ["웹"]}
        workable = review(plan)
        self.assertEqual((workable["grade"], workable["blocking"]), ("workable", 0))

        self.assertEqual(review(_solid())["grade"], "solid")
        self.assertEqual(set(P.GRADES), {"draft", "workable", "solid"})

    def test_the_same_document_always_scores_the_same(self):
        plan = _covered(_plan(**{**_GOOD, "target": "리드가 열어요."}))
        first, second = review(plan), review(plan)
        self.assertEqual(first, second)
        self.assertTrue(0 <= first["score"] <= 100)
        self.assertLess(first["score"], review(_solid())["score"])


class TestReadinessCarriesTheScore(unittest.TestCase):
    def test_the_score_rides_along_but_does_not_gate(self):
        """심사는 보여 주는 값이다 — 개요가 차면 지적이 남아도 기능 명세서가 열린다."""
        plan = P.create_plan("팀 회고를 자동으로 모아 주는 도구")
        empty = P.readiness(plan)["prd"]
        self.assertEqual((empty["ready"], empty["grade"], empty["blocking"]), (False, "draft", 1))

        plan = P.apply_edit(plan["id"], "section", {"section": "overview", "body": "회고를 모아요."})
        ready = P.readiness(plan)
        self.assertTrue(ready["prd"]["ready"])
        self.assertEqual(ready["prd"]["blocking"], 0)
        self.assertEqual(ready["prd"]["grade"], "workable")
        self.assertLess(ready["prd"]["score"], 100)
        self.assertEqual(ready["spec"]["blocked"], [])


class TestMarkdownExport(unittest.TestCase):
    def test_the_document_carries_every_box_the_screen_shows(self):
        plan = _solid()
        plan["title"] = "회고 수집기"
        intake.note_assumption(plan["intake"], "success_signal", "석 달 뒤 참여율로 잰다고 봤어요")
        text = P.to_markdown(plan)

        self.assertTrue(text.startswith("# 회고 수집기\n"))
        for _, label, _ in P.PRD_SECTIONS:
            self.assertIn(f"## {label}\n", text)
        for body in _GOOD.values():
            for line in body.splitlines():
                self.assertIn(line, text)
        self.assertIn("- 사용자 역할: 스쿼드 리드", text)
        self.assertIn("- 서비스 환경: 웹", text)
        self.assertIn("(미확인) 석 달 뒤 참여율로 잰다고 봤어요", text)
        self.assertIn("## 심사", text)
        self.assertIn("점수 92/100", text)
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("\n\n\n", text)

    def test_an_empty_box_keeps_its_heading(self):
        """빠뜨린 칸과 아직 안 쓴 칸은 받는 쪽에서 구별이 안 된다."""
        text = P.to_markdown(_plan())
        self.assertIn("## 개요\n\n(아직 비어 있어요)", text)
        self.assertIn("- 제품 갈래: (아직 비어 있어요)", text)
        self.assertIn("- 초안이 근거 없이 채운 자리는 없어요.", text)
        self.assertIn("[block] 개요", text)

    def test_a_clean_document_says_so(self):
        text = P.to_markdown(_solid())
        self.assertIn("- 걸린 지적이 없어요.", text)
        self.assertIn("막는 지적 0건 · 지적 전체 0건", text)


class TestSectionsEdit(unittest.TestCase):
    def test_several_boxes_land_in_one_revision(self):
        """칸마다 따로 보내면 개정이 칸 수만큼 늘고, 중간에 막히면 절반만 반영된 문서가 남는다."""
        plan = P.create_plan("팀 회고를 자동으로 모아 주는 도구")
        before = plan["revision"]
        plan = P.apply_edit(
            plan["id"],
            "sections",
            {"sections": {"overview": "회고를 모아요.", "value": "기록이 흩어져요.", "success": "참여율 70%예요."}},
        )
        self.assertEqual(plan["revision"], before + 1)
        self.assertEqual(plan["prd"]["sections"]["overview"]["body"], "회고를 모아요.")
        self.assertEqual(plan["prd"]["sections"]["value"]["body"], "기록이 흩어져요.")
        self.assertEqual(plan["prd"]["sections"]["success"]["body"], "참여율 70%예요.")
        self.assertEqual(plan["prd"]["sections"]["target"]["body"], "")
        self.assertIn("sections", P.OPS)

    def test_an_unknown_box_is_refused_and_nothing_is_written(self):
        plan = P.create_plan("팀 회고를 자동으로 모아 주는 도구")
        with self.assertRaises(ValueError):
            P.apply_edit(plan["id"], "sections", {"sections": {"overview": "회고를 모아요.", "roadmap": "3분기"}})
        stored = P.load_plan(plan["id"])
        self.assertEqual(stored["prd"]["sections"]["overview"]["body"], "")
        self.assertEqual(stored["revision"], plan["revision"])
        with self.assertRaises(ValueError):
            P.apply_edit(plan["id"], "sections", {"sections": {}})


if __name__ == "__main__":
    unittest.main()
