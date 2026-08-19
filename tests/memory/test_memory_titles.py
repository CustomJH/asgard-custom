"""제목 계약 — 본문에서 뽑는 제목의 절단 자리, 제목·발췌 겹침 제거, 부르는 쪽이 지은 제목."""

from unittest import mock

from memory_base import MemoryBase

from asgard import memory
from asgard.memory import pattern
from asgard.memory.recall.rows import _fuse, _hit_row


class TestDeriveTitle(MemoryBase):
    def test_a_decimal_is_not_a_sentence_end(self):
        # 실측 26-08-19: `1.0.0` 의 첫 점에서 끊겨 제목이 `오딘은 아직 개발 중이라 1` 로 남았다.
        text = "아직 개발 중이라 1.0.0 릴리즈까지 한참 남았다고 본다."
        self.assertEqual(memory.derive_title(text), text)

    def test_odins_reported_case_end_to_end(self):
        """오딘이 실제로 지목한 페이지 — 소수점 절단과 화자 접두사가 한 문장에 겹쳐 있다."""
        self.assertEqual(
            memory.derive_title("오딘은 아직 개발 중이라 1.0.0 릴리즈까지 한참 남았다고 본다."),
            "아직 개발 중이라 1.0.0 릴리즈까지 한참 남았다고 본다.",
        )

    def test_a_version_in_a_path_does_not_end_the_title(self):
        text = "배포된 asgard 0.10.9 의 memory_context.py 가 주입 상한을 쥔다."
        self.assertEqual(memory.derive_title(text), text)

    def test_a_line_within_the_limit_is_kept_whole(self):
        text = "커밋에 서명 꼬리를 안 붙인다. 그 이유는 별도로 적혀 있다."
        self.assertEqual(memory.derive_title(text), text)

    def test_an_overlong_line_is_cut_at_the_first_sentence(self):
        first = "커밋에 서명 꼬리를 안 붙인다."
        text = first + " " + "그 이유는 MANUAL.md 에 적혀 있고 여러 저장소에서 같은 규칙을 지켜 왔다. " * 2
        self.assertGreater(len(text), memory.TITLE_MAX)
        self.assertEqual(memory.derive_title(text), first)

    def test_an_overlong_line_is_cut_at_a_word_boundary(self):
        # 낱말 길이를 상한과 어긋나게 잡는다 — 우연히 경계와 맞으면 이 시험은 아무것도 안 붙잡는다.
        text = " ".join(f"낱말{i:02d}가나다라마바사" for i in range(12))
        title = memory.derive_title(text)
        self.assertLessEqual(len(title), memory.TITLE_MAX)
        self.assertTrue(title.endswith("…"), title)
        kept = title[:-1].rstrip()
        self.assertTrue(text.startswith(kept), title)
        # 끊긴 자리 다음은 공백이거나 문장의 끝이다 — 낱말 한가운데가 아니다
        self.assertIn(text[len(kept) : len(kept) + 1], (" ", ""), title)

    def test_the_title_never_ends_mid_word_without_saying_so(self):
        text = "asgard-custom 에서 Verifier 가 매 세션을 잡아먹는 사슬은 trinity_policy 의 baseline_checks 가 비어 있다는 것이다."
        title = memory.derive_title(text)
        self.assertTrue(title.endswith("…"), title)
        self.assertNotIn(title[-2], "abcdefghijklmnopqrstuvwxyz")

    def test_an_abbreviation_is_not_a_sentence_end(self):
        # 판정 26-08-19: 마침표 뒤 공백만 보면 약어·서수가 제목 전체가 된다.
        for text in (
            "e.g. 오딘은 커밋에 서명 꼬리를 안 붙인다.",
            "Mr. Odin keeps the release notes in Linear.",
            "규칙은 3. 항목을 먼저 읽는다.",
        ):
            self.assertEqual(memory.derive_title(text), text, text)

    def test_an_abbreviation_does_not_become_the_title_of_a_long_line(self):
        text = "e.g. " + "오딘은 커밋 메시지에 서명 꼬리를 붙이지 않는다는 규칙을 여러 저장소에 걸쳐 지켜 왔다. " * 2
        title = memory.derive_title(text)
        self.assertGreater(len(title), 10, title)
        self.assertNotEqual(title, "e.g.")


class TestSpeakerPrefix(MemoryBase):
    """실측 26-08-19 (`benchmarks/memory-title`): 화자를 떼면 앞 10자가 서로 갈리는 제목이
    48장 중 32장에서 41장으로 는다 (distinct10 0.667 → 0.854)."""

    def test_the_speaker_and_its_particle_are_dropped(self):
        for text, want in (
            ("오딘은 커밋에 서명 꼬리를 안 붙인다.", "커밋에 서명 꼬리를 안 붙인다."),
            ("사용자가 justfile을 원할 때만 설치한다.", "justfile을 원할 때만 설치한다."),
            ("오딘의 기본 모델은 sonnet 으로 내려 둔다.", "기본 모델은 sonnet 으로 내려 둔다."),
        ):
            self.assertEqual(memory.derive_title(text), want)

    def test_an_identifier_keeps_its_case(self):
        # 대문자로 올리면 `asgard-seal` 이 더는 그 명령이 아니다.
        self.assertEqual(
            memory.derive_title("오딘은 asgard-seal 의 기본 모델을 sonnet 으로 내리기를 원한다."),
            "asgard-seal 의 기본 모델을 sonnet 으로 내리기를 원한다.",
        )

    def test_a_compound_noun_is_not_a_speaker(self):
        # 조사가 없으면 화자가 아니라 복합명사의 앞머리다 — 자르면 남는 것이 다른 말이 된다.
        for text in ("사용자 정의 필드는 스키마에 없다.", "사용자 인터페이스를 다시 그린다."):
            self.assertEqual(memory.derive_title(text), text, text)

    def test_a_title_that_would_be_left_too_short_keeps_the_speaker(self):
        self.assertEqual(memory.derive_title("오딘은 쉰다."), "오딘은 쉰다.")

    def test_a_title_without_a_speaker_is_untouched(self):
        text = "asgard-seal 은 변경을 사건별 커밋으로 나눈다."
        self.assertEqual(memory.derive_title(text), text)


class TestFuse(MemoryBase):
    def test_a_tail_and_head_overlap_is_joined_once(self):
        title = "오딘은 아스가르드가 cpu 를 너무 많이 먹는 것 같다며 원인을 분석해 메모리"
        snippet = "너무 많이 먹는 것 같다며 원인을 분석해 메모리 최적화 작업을 하도록 요청했다."
        self.assertEqual(
            _fuse(title, snippet),
            "오딘은 아스가르드가 cpu 를 너무 많이 먹는 것 같다며 원인을 분석해 메모리 최적화 작업을 하도록 요청했다.",
        )

    def test_a_truncation_mark_does_not_hide_the_overlap(self):
        # 발췌 끝의 말줄임표를 비교에 넣으면 포함 관계가 깨져 같은 문장이 두 번 실린다.
        title = "helios-application 의 2차 메모리는 backend 회수가 7.5~9.0초인데 자동 주입 대기 상한이 5초라 매 턴 조"
        snippet = "helios-application 의 2차 메모리는 backend 회수가 7.5~9.0초인데 자동 주입 대기 상한이 5초라 매 턴…"
        self.assertEqual(_fuse(title, snippet), title)

    def test_a_snippet_that_carries_the_title_replaces_it(self):
        title = "오딘은 커밋에 서명 꼬리를 안 붙인다"
        snippet = "오딘은 커밋에 서명 꼬리를 안 붙인다. 그 규칙은 MANUAL.md 에 적혀 있다."
        self.assertEqual(_fuse(title, snippet), snippet)

    def test_joining_keeps_the_truncation_mark(self):
        title = "오딘은 아스가르드가 cpu 를 너무 많이 먹는 것 같다며 원인을 분석해 메모리"
        snippet = "너무 많이 먹는 것 같다며 원인을 분석해 메모리 최적화 작업을 하도록…"
        fused = _fuse(title, snippet)
        assert fused is not None
        self.assertTrue(fused.endswith("…"), fused)

    def test_unrelated_pieces_are_not_joined(self):
        self.assertIsNone(_fuse("오딘은 커밋 서명을 안 붙인다", "훅 배포는 --no-cache 로 한다"))

    def test_a_hit_row_never_says_the_same_sentence_twice(self):
        hit = {
            "title": "오딘은 helios-asgard 와 helios-application 이 같은 2차 메모리를 보면 같이 관리",
            "snippet": "ios-asgard 와 helios-application 이 같은 2차 메모리를 보면 같이 관리되어야 한다고 본다.",
            "kind": "user",
        }
        row = _hit_row(hit)
        self.assertEqual(row.count("같이 관리"), 1, row)
        self.assertIn("한다고 본다", row)


class TestTitleFromTheCaller(MemoryBase):
    def test_ingest_keeps_the_title_it_was_given(self):
        memory.ingest(
            "오딘은 아직 개발 중이라 1.0.0 릴리즈까지 한참 남았다고 본다.", kind="user", title="1.0.0 릴리즈 시점"
        )
        meta, body = self._page("100-릴리즈-시점")
        self.assertEqual(meta["title"], "1.0.0 릴리즈 시점")
        self.assertNotIn(meta["title"], body)

    def test_an_approved_proposal_still_carries_its_title(self):
        from asgard.memory import propose

        with mock.patch.object(propose, "autosave_enabled", return_value=False):
            staged = propose.submit("오딘은 터미널 문체로 해요체를 쓴다.", kind="user", title="터미널 문체")
        _action, slug = propose.commit(staged["id"])
        self.assertEqual(self._page(slug)[0]["title"], "터미널 문체")

    def test_a_pattern_observation_uses_the_title_the_model_wrote(self):
        plan = {
            "observations": [
                {
                    "kind": "explicit",
                    "title": "1.0.0 릴리즈 시점",
                    "text": "오딘은 아직 개발 중이라 1.0.0 릴리즈까지 한참 남았다고 본다.",
                    "evidence": [1],
                    "grounding": 0.9,
                    "confidence": "low",
                }
            ]
        }
        result = pattern.apply_pattern(self.tmp, plan, self.d)
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(self._page(result["applied"][0]["slug"])[0]["title"], "1.0.0 릴리즈 시점")

    def test_the_memory_save_tool_carries_the_title_it_was_given(self):
        from asgard.agent.heimdall.roles import MEMORY_SAVE_TOOL, _memory_save_support

        self.assertIn("title", MEMORY_SAVE_TOOL["input_schema"]["properties"])
        saved: list[tuple[str, str]] = []
        _note, _tools, handlers = _memory_save_support(saved)
        handlers["memory_save"](
            {"title": "커밋 서명 꼬리", "text": "오딘은 커밋 메시지에 Co-Authored-By 꼬리를 안 붙인다.", "kind": "user"}
        )
        self.assertEqual(len(saved), 1)
        meta, body = self._page(saved[0][1])
        self.assertEqual(meta["title"], "커밋 서명 꼬리")
        self.assertNotIn(meta["title"], body)


class TestRetitle(MemoryBase):
    def _truncated_page(self) -> tuple[str, str]:
        body = "아직 개발 중이라 1.0.0 릴리즈까지 한참 남았다고 본다."
        slug, _ = memory.add(body, title="아직 개발 중이라 1", kind="user")
        return slug, body

    def test_lint_reports_a_title_copied_from_the_body_and_cut(self):
        slug, _ = self._truncated_page()
        finding = next(f for f in memory.lint(self.d) if f["code"] == "title-truncated")
        self.assertEqual(finding["slug"], slug)

    def test_retitle_rewrites_the_title_and_leaves_body_and_slug_alone(self):
        slug, body = self._truncated_page()
        changed = memory.retitle(self.d)
        self.assertEqual([(s, o) for s, o, _n in changed], [(slug, "아직 개발 중이라 1")])
        meta, kept = self._page(slug)
        self.assertEqual(meta["title"], body)
        self.assertEqual(kept.strip(), body)
        self.assertEqual([f for f in memory.lint(self.d) if f["code"] == "title-truncated"], [])

    def test_a_truncated_title_is_still_a_retitle_target(self):
        """말줄임표가 붙으면 본문의 접두사가 아니게 된다 — 그 판정이 가장 나아질 제목을 놓쳤다."""
        # 실제로 남아 있던 다섯 장의 모양 — 화자로 시작하고 말줄임표로 끝난다.
        body = "오딘은 " + "여러 저장소에 걸쳐 같은 규칙을 지켜 왔고 그 근거는 MANUAL.md 에 적혀 있다. " * 2
        slug, _ = memory.add(body, title=body[:40].rstrip() + "…", kind="user")
        changed = memory.retitle(self.d)
        self.assertEqual([s for s, _o, _n in changed], [slug])
        self.assertFalse(self._page(slug)[0]["title"].startswith("오딘"))

    def test_a_title_the_caller_wrote_is_left_alone(self):
        memory.add("오딘은 아직 개발 중이라 1.0.0 릴리즈까지 한참 남았다고 본다.", title="릴리즈 시점", kind="user")
        self.assertEqual(memory.retitle(self.d), [])
