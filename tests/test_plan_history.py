"""PRD 본문 편집의 되돌리기 — 칸마다 직전 본문 하나.

이 파일이 지키는 불변식 둘:
  · 본문을 쓰는 연산은 **덮어쓰기 전에** 지금 본문을 `previous`로 민다. 단, 값이 같으면
    안 민다 — 화면의 자동 저장이 안 바뀐 본문을 다시 보내도 직전 글이 안 지워져야 한다.
  · `section.undo`는 맞바꾸기다 — 두 번 부르면 제자리다. 그래서 다시하기가 같은 손잡이다.

저장소는 `conftest`의 `ASGARD_STUDIO_HOME` 픽스처가 테스트마다 새 자리로 옮긴다. 그래서
여기서는 실제 `plans.json`을 통과시켜 잰다 — `previous`가 검사와 저장을 통과하지 못하면
왕복 한 번에 사라지기 때문이다.
"""

import unittest

from asgard import plan as P


def _seeded() -> dict:
    return P.create_plan("팀 회고를 자동으로 모아 주는 도구")


def _section(plan_id: str, sid: str) -> dict:
    """저장소에서 다시 읽은 칸 하나 — 메모리 위의 초안이 아니라 파일을 통과한 값이다."""
    return P.load_plan(plan_id)["prd"]["sections"][sid]


class TestPreviousBody(unittest.TestCase):
    def test_a_new_plan_starts_with_an_empty_previous_in_every_box(self):
        plan = P.new_plan("회고 도구")
        for sid in P.PRD_SECTION_IDS:
            self.assertEqual(plan["prd"]["sections"][sid], {"body": "", "previous": ""})

    def test_writing_a_box_pushes_the_body_that_was_there(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "첫 판"})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "둘째 판"})
        self.assertEqual(_section(plan["id"], "overview"), {"body": "둘째 판", "previous": "첫 판"})

    def test_only_one_previous_is_kept_per_box(self):
        """세 번 써도 남는 것은 직전 본문 하나다 — 목록으로 늘리지 않는다."""
        plan = _seeded()
        for body in ("첫 판", "둘째 판", "셋째 판"):
            P.apply_edit(plan["id"], "section", {"section": "overview", "body": body})
        self.assertEqual(_section(plan["id"], "overview"), {"body": "셋째 판", "previous": "둘째 판"})

    def test_saving_the_same_body_again_does_not_push(self):
        """자동 저장은 안 바뀐 본문도 보낸다 — 그때 밀면 되돌리기가 아무것도 안 한다."""
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "첫 판"})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "둘째 판"})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "둘째 판"})
        self.assertEqual(_section(plan["id"], "overview"), {"body": "둘째 판", "previous": "첫 판"})

    def test_writing_one_box_leaves_the_other_boxes_alone(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "개요 한 줄"})
        self.assertEqual(_section(plan["id"], "value"), {"body": "", "previous": ""})


class TestSectionsOp(unittest.TestCase):
    def test_one_revision_pushes_every_box_it_writes(self):
        """문서 전체 다듬기를 반영해도 칸마다 자기 직전 글이 남는다."""
        plan = _seeded()
        P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 첫 판", "value": "가치 첫 판"}})
        P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 둘째 판", "value": "가치 둘째 판"}})
        saved = P.load_plan(plan["id"])["prd"]["sections"]
        self.assertEqual(saved["overview"], {"body": "개요 둘째 판", "previous": "개요 첫 판"})
        self.assertEqual(saved["value"], {"body": "가치 둘째 판", "previous": "가치 첫 판"})

    def test_a_box_whose_body_did_not_change_keeps_its_previous(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 첫 판", "value": "가치 첫 판"}})
        P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 둘째 판", "value": "가치 첫 판"}})
        saved = P.load_plan(plan["id"])["prd"]["sections"]
        self.assertEqual(saved["overview"], {"body": "개요 둘째 판", "previous": "개요 첫 판"})
        self.assertEqual(saved["value"], {"body": "가치 첫 판", "previous": ""})

    def test_an_unknown_box_writes_nothing_at_all(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "개요 첫 판"})
        with self.assertRaises(ValueError) as caught:
            P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 둘째 판", "nope": "x"}})
        self.assertIn("nope", str(caught.exception))
        self.assertEqual(_section(plan["id"], "overview"), {"body": "개요 첫 판", "previous": ""})


class TestUndo(unittest.TestCase):
    def test_undo_swaps_the_two_bodies(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "사람이 쓴 글"})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "모델이 고친 글"})
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        self.assertEqual(_section(plan["id"], "overview"), {"body": "사람이 쓴 글", "previous": "모델이 고친 글"})

    def test_pressing_undo_twice_lands_where_it_started(self):
        """맞바꾸기라 다시하기가 공짜다 — 같은 손잡이를 다시 누르면 돌아온다."""
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "사람이 쓴 글"})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "모델이 고친 글"})
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        self.assertEqual(_section(plan["id"], "overview"), {"body": "모델이 고친 글", "previous": "사람이 쓴 글"})

    def test_undo_after_the_sections_op_returns_each_box_on_its_own(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 첫 판", "value": "가치 첫 판"}})
        P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 둘째 판", "value": "가치 둘째 판"}})
        P.apply_edit(plan["id"], "section.undo", {"section": "value"})
        saved = P.load_plan(plan["id"])["prd"]["sections"]
        self.assertEqual(saved["overview"]["body"], "개요 둘째 판")
        self.assertEqual(saved["value"]["body"], "가치 첫 판")

    def test_an_empty_previous_is_refused_with_a_line_the_reader_can_read(self):
        """되돌릴 것이 없는데 맞바꾸면 사람이 쓴 본문이 빈 글로 갈린다."""
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "첫 판"})
        with self.assertRaises(ValueError) as caught:
            P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        self.assertEqual(str(caught.exception), "되돌릴 것이 없어요")
        self.assertEqual(_section(plan["id"], "overview"), {"body": "첫 판", "previous": ""})

    def test_an_unknown_box_is_refused_in_the_same_words_as_the_write_op(self):
        plan = _seeded()
        with self.assertRaises(ValueError) as write_failed:
            P.apply_edit(plan["id"], "section", {"section": "nope", "body": "x"})
        with self.assertRaises(ValueError) as undo_failed:
            P.apply_edit(plan["id"], "section.undo", {"section": "nope"})
        self.assertEqual(str(undo_failed.exception), str(write_failed.exception))
        self.assertIn("nope", str(undo_failed.exception))

    def test_undo_is_one_of_the_named_ops(self):
        """화면과 서버가 아는 연산 목록이 갈리면 `unknown_edit`으로만 나타난다."""
        self.assertIn("section.undo", P.OPS)


class TestOlderDocuments(unittest.TestCase):
    def test_a_document_saved_before_previous_existed_still_loads(self):
        """`SCHEMA_VERSION`을 안 올린 근거 — 옛 문서는 빈 `previous`가 채워져 그대로 통과한다."""
        plan = P.new_plan("회고 도구")
        for row in plan["prd"]["sections"].values():
            row.pop("previous")
        checked = P.validate_plan(plan)
        self.assertEqual(checked["schema"], 2)
        for sid in P.PRD_SECTION_IDS:
            self.assertEqual(checked["prd"]["sections"][sid], {"body": "", "previous": ""})

    def test_an_older_document_can_be_saved_and_then_undone(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "옛 본문"})
        older = P.load_plan(plan["id"])
        del older["prd"]["sections"]["overview"]["previous"]
        P.save_plan(older)
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "새 본문"})
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        self.assertEqual(_section(plan["id"], "overview")["body"], "옛 본문")

    def test_a_previous_over_the_text_limit_is_refused(self):
        plan = P.new_plan("회고 도구")
        plan["prd"]["sections"]["overview"]["previous"] = "가" * 8001
        with self.assertRaises(ValueError) as caught:
            P.validate_plan(plan)
        self.assertIn("previous", str(caught.exception))


class TestUntouchedContracts(unittest.TestCase):
    def test_previous_is_not_progress(self):
        """`readiness`는 `previous`를 안 센다 — 되돌릴 글이 있는 것은 채운 칸이 아니다."""
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "개요 한 줄"})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": ""})
        ready = P.readiness(P.load_plan(plan["id"]))
        self.assertFalse(ready["prd"]["ready"])
        self.assertEqual(ready["prd"]["filled"], 0)

    def test_the_review_card_reads_only_the_body(self):
        """심사는 `body`만 본다 — `previous`에 남은 옛 글이 점수를 올리면 안 된다."""
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "개요 두 줄\n그리고 이유"})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": ""})
        card = P.review(P.load_plan(plan["id"]))
        self.assertFalse(card["sections"]["overview"]["filled"])
        self.assertGreaterEqual(card["blocking"], 1)


if __name__ == "__main__":
    unittest.main()
