"""PRD 본문 편집의 되돌리기 — 칸마다 직전 본문 하나.

이 파일이 지키는 불변식 셋:
  · `section`은 `snapshot`이 참일 때만 지금 본문을 `previous`로 민다. 거짓이거나 없으면 본문만
    쓴다 — 타이핑을 받는 자동 저장이 그 한 칸을 쓰면 정작 제안 반영을 못 되돌린다.
  · `sections`(문서 전체 반영)는 제안 반영 전용이라 늘 민다.
  · 값이 같으면 어느 쪽도 안 민다. `section.undo`는 맞바꾸기라 두 번 부르면 제자리다 —
    그래서 다시하기가 같은 손잡이다.

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


def _typed(plan_id: str, sid: str, body: str) -> None:
    """화면의 자동 저장이 보내는 그대로 — `snapshot` 키가 아예 없다."""
    P.apply_edit(plan_id, "section", {"section": sid, "body": body})


def _taken(plan_id: str, sid: str, body: str) -> None:
    """제안을 반영하는 자리가 보내는 그대로(`proposal-take`·`docprop-take`)."""
    P.apply_edit(plan_id, "section", {"section": sid, "body": body, "snapshot": True})


class TestPreviousBody(unittest.TestCase):
    def test_a_new_plan_starts_with_an_empty_previous_in_every_box(self):
        plan = P.new_plan("회고 도구")
        for sid in P.PRD_SECTION_IDS:
            self.assertEqual(plan["prd"]["sections"][sid], {"body": "", "previous": ""})

    def test_a_write_that_asks_for_a_snapshot_pushes_the_body_that_was_there(self):
        plan = _seeded()
        _taken(plan["id"], "overview", "첫 판")
        _taken(plan["id"], "overview", "둘째 판")
        self.assertEqual(_section(plan["id"], "overview"), {"body": "둘째 판", "previous": "첫 판"})

    def test_a_write_without_a_snapshot_writes_the_body_and_nothing_else(self):
        """자동 저장이 이 길로 온다 — 타이핑이 `previous`를 쓰면 제안 반영을 못 되돌린다."""
        plan = _seeded()
        _typed(plan["id"], "overview", "첫 판")
        _typed(plan["id"], "overview", "둘째 판")
        self.assertEqual(_section(plan["id"], "overview"), {"body": "둘째 판", "previous": ""})

    def test_a_snapshot_that_is_false_is_the_same_as_no_snapshot_at_all(self):
        plan = _seeded()
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "첫 판", "snapshot": False})
        P.apply_edit(plan["id"], "section", {"section": "overview", "body": "둘째 판", "snapshot": False})
        self.assertEqual(_section(plan["id"], "overview"), {"body": "둘째 판", "previous": ""})

    def test_a_write_without_a_snapshot_leaves_the_previous_that_is_already_there(self):
        """반영 뒤의 타이핑이 되돌릴 글을 밀어내면 안 된다 — 이 층이 있는 이유가 그 반영이다."""
        plan = _seeded()
        _typed(plan["id"], "overview", "사람이 쓴 글")
        _taken(plan["id"], "overview", "모델이 고친 글")
        _typed(plan["id"], "overview", "모델이 고친 글에 한 줄 더")
        self.assertEqual(
            _section(plan["id"], "overview"),
            {"body": "모델이 고친 글에 한 줄 더", "previous": "사람이 쓴 글"},
        )

    def test_only_one_previous_is_kept_per_box(self):
        """세 번 반영해도 남는 것은 직전 본문 하나다 — 목록으로 늘리지 않는다."""
        plan = _seeded()
        for body in ("첫 판", "둘째 판", "셋째 판"):
            _taken(plan["id"], "overview", body)
        self.assertEqual(_section(plan["id"], "overview"), {"body": "셋째 판", "previous": "둘째 판"})

    def test_saving_the_same_body_again_does_not_push(self):
        """같은 제안을 두 번 눌러도 밀지 않는다 — 밀면 `previous`가 지금 본문과 같아진다."""
        plan = _seeded()
        _taken(plan["id"], "overview", "첫 판")
        _taken(plan["id"], "overview", "둘째 판")
        _taken(plan["id"], "overview", "둘째 판")
        self.assertEqual(_section(plan["id"], "overview"), {"body": "둘째 판", "previous": "첫 판"})

    def test_writing_one_box_leaves_the_other_boxes_alone(self):
        plan = _seeded()
        _taken(plan["id"], "overview", "개요 한 줄")
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
        _typed(plan["id"], "overview", "개요 첫 판")
        with self.assertRaises(ValueError) as caught:
            P.apply_edit(plan["id"], "sections", {"sections": {"overview": "개요 둘째 판", "nope": "x"}})
        self.assertIn("nope", str(caught.exception))
        self.assertEqual(_section(plan["id"], "overview"), {"body": "개요 첫 판", "previous": ""})

    def test_this_op_pushes_even_when_the_payload_says_not_to(self):
        """`sections`는 제안 반영 전용이라 `snapshot`을 안 본다 — 화면이 안 보내도 늘 민다."""
        plan = _seeded()
        _typed(plan["id"], "overview", "사람이 쓴 글")
        P.apply_edit(plan["id"], "sections", {"sections": {"overview": "모델이 고친 글"}, "snapshot": False})
        self.assertEqual(
            _section(plan["id"], "overview"),
            {"body": "모델이 고친 글", "previous": "사람이 쓴 글"},
        )


class TestUndo(unittest.TestCase):
    def test_undo_swaps_the_two_bodies(self):
        plan = _seeded()
        _typed(plan["id"], "overview", "사람이 쓴 글")
        _taken(plan["id"], "overview", "모델이 고친 글")
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        self.assertEqual(_section(plan["id"], "overview"), {"body": "사람이 쓴 글", "previous": "모델이 고친 글"})

    def test_pressing_undo_twice_lands_where_it_started(self):
        """맞바꾸기라 다시하기가 공짜다 — 같은 손잡이를 다시 누르면 돌아온다."""
        plan = _seeded()
        _typed(plan["id"], "overview", "사람이 쓴 글")
        _taken(plan["id"], "overview", "모델이 고친 글")
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
        _typed(plan["id"], "overview", "첫 판")
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


class TestTypingDoesNotEatTheSlot(unittest.TestCase):
    """`snapshot`을 가른 이유 그대로의 시나리오 — 사람이 쓴다 · 제안을 반영한다 · 또 친다."""

    def test_undo_after_a_proposal_and_more_typing_lands_on_what_the_person_wrote(self):
        plan = _seeded()
        for body in ("사람이 쓴 첫 줄", "사람이 쓴 첫 줄과 둘째 줄", "사람이 쓴 원래 글"):
            _typed(plan["id"], "overview", body)
        _taken(plan["id"], "overview", "모델이 고친 글")
        for body in ("모델이 고친 글에 한 줄 더", "모델이 고친 글에 두 줄 더", "모델이 고친 글에 세 줄 더"):
            _typed(plan["id"], "overview", body)
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        self.assertEqual(_section(plan["id"], "overview")["body"], "사람이 쓴 원래 글")

    def test_pressing_undo_again_brings_back_the_typing_that_came_after_the_proposal(self):
        """맞바꾸기라 반영 뒤에 친 줄도 안 버려진다 — 되돌린 뒤 다시 누르면 그 글로 돌아온다."""
        plan = _seeded()
        _typed(plan["id"], "overview", "사람이 쓴 원래 글")
        _taken(plan["id"], "overview", "모델이 고친 글")
        _typed(plan["id"], "overview", "모델이 고친 글에 한 줄 더")
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        P.apply_edit(plan["id"], "section.undo", {"section": "overview"})
        self.assertEqual(_section(plan["id"], "overview")["body"], "모델이 고친 글에 한 줄 더")

    def test_typing_alone_never_raises_the_undo_handle(self):
        """화면은 `previous`가 비었으면 손잡이를 안 세운다 — 타이핑만 한 칸이 그 자리다."""
        plan = _seeded()
        for body in ("한", "한 줄", "한 줄을 적어요"):
            _typed(plan["id"], "overview", body)
        self.assertEqual(_section(plan["id"], "overview")["previous"], "")


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
        _typed(plan["id"], "overview", "옛 본문")
        older = P.load_plan(plan["id"])
        del older["prd"]["sections"]["overview"]["previous"]
        P.save_plan(older)
        _taken(plan["id"], "overview", "새 본문")
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
        _typed(plan["id"], "overview", "개요 한 줄")
        _taken(plan["id"], "overview", "")
        ready = P.readiness(P.load_plan(plan["id"]))
        self.assertFalse(ready["prd"]["ready"])
        self.assertEqual(ready["prd"]["filled"], 0)

    def test_the_review_card_reads_only_the_body(self):
        """심사는 `body`만 본다 — `previous`에 남은 옛 글이 점수를 올리면 안 된다."""
        plan = _seeded()
        _typed(plan["id"], "overview", "개요 두 줄\n그리고 이유")
        _taken(plan["id"], "overview", "")
        card = P.review(P.load_plan(plan["id"]))
        self.assertFalse(card["sections"]["overview"]["filled"])
        self.assertGreaterEqual(card["blocking"], 1)


if __name__ == "__main__":
    unittest.main()
