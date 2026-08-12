#!/usr/bin/env python3
"""커스텀 매뉴얼 (루트 `MANUAL.md`) 단위 테스트 — 해석 · 렌더 · 손잡이.

이 계층의 실패 양식은 전부 **조용하다**: 이름을 틀려도, 주석 밖으로 안 꺼내도, 별칭 둘을 만들어
하나가 가려져도, 상한에 잘려도 에이전트는 평소처럼 돈다. 그래서 검사는 "켜졌나"가 아니라 "안
켜지는 각 경로가 관측되는가"를 본다.

핵심 계약:
  · 미설정 = 빈 문자열 (프롬프트 무변화, 토큰 회귀 없음)
  · 집은 메인 루트, `.asgard/`는 보조 — 두 자리는 서로 안 가리고 루트가 먼저 실린다
  · 주석뿐인 시작 템플릿 = 없는 것과 동일 (배송해도 주입 0)
  · 별칭 우선순위는 MANUAL_NAMES 나열 순서 하나로 고정, 진 파일은 shadowed로 관측된다
  · 매뉴얼은 캐논을 못 이긴다 — 권위 문단에 그 경계가 반드시 실린다
  · verifier 절은 "criteria 대체 아님"을 반드시 포함 (evidence-first 보존)

실행: uv run pytest tests/test_manual.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from hookscaffold import isolated_home_env

from asgard import manual as M
from asgard.manual import MANUAL_NAMES
from asgard.templates.manual import MANUAL_STARTER_MD


class ManualBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".asgard"))
        # 글로벌 설정이 테스트 판정에 새지 않도록 HOME을 빈 임시 디렉터리로 격리한다.
        self._home = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"HOME": self._home.name}, clear=False)
        self._env.start()
        os.environ.pop("ASGARD_MANUAL", None)

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        """rel은 **리포 루트 기준** 상대경로 — 로더가 쓰는 좌표와 같게 둔다."""
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def common(self, rel: str, text: str) -> str:
        """공통 층(활성 에이전트 홈)에 쓴다 — 이 기계의 모든 프로젝트에 걸리는 자리."""
        path = os.path.join(M.home(), rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def settings(self, section: dict) -> None:
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            json.dump({"manual": section}, handle)


class TestDiscovery(ManualBase):
    def test_absent_is_none(self):
        self.assertIsNone(M.load_manual(self.root))
        for sec in M.SECTIONS:
            self.assertEqual(M.note(self.root, sec), "")  # 프롬프트 무변화

    def test_missing_asgard_dir_is_none(self):
        with tempfile.TemporaryDirectory() as bare:
            self.assertIsNone(M.load_manual(bare))  # fail-open

    def test_root_is_the_home(self):
        self.write("MANUAL.md", "## API\n- v1 prefix.")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["MANUAL.md"])
        self.assertIn("v1 prefix", loaded["body"])

    def test_asgard_dir_still_works_alone(self):
        self.write(".asgard/MANUAL.md", "- 보조 자리")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], [".asgard/MANUAL.md"])

    def test_root_and_asgard_both_load_root_first(self):
        """두 자리는 서로 가리지 않는다 — 별칭 가림은 같은 디렉터리 안에서만."""
        self.write("MANUAL.md", "- 루트 규칙")
        self.write(".asgard/MANUAL.md", "- 보조 규칙")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["MANUAL.md", ".asgard/MANUAL.md"])
        self.assertEqual(loaded["shadowed"], [])
        self.assertLess(loaded["body"].index("루트 규칙"), loaded["body"].index("보조 규칙"))

    def test_each_alias_is_recognized_alone_in_both_places(self):
        for sub in ("", ".asgard"):
            for name in M.MANUAL_NAMES:
                rel = f"{sub}/{name}" if sub else name
                with self.subTest(rel=rel), tempfile.TemporaryDirectory() as root:
                    path = os.path.join(root, rel)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write("- rule")
                    loaded = M.load_manual(root)
                    assert loaded is not None
                    self.assertEqual(loaded["sources"], [rel])

    def test_alias_precedence_follows_declaration_order(self):
        """한 디렉터리에 넷을 다 만들면 MANUAL.md만 이기고 나머지는 shadowed로 관측된다."""
        for i, name in enumerate(M.MANUAL_NAMES):
            self.write(name, f"- rule {i}")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["MANUAL.md"])
        self.assertEqual(loaded["shadowed"], list(M.MANUAL_NAMES[1:]))
        self.assertIn("rule 0", loaded["body"])
        self.assertNotIn("rule 1", loaded["body"])  # 진 파일은 한 글자도 안 실린다

    def test_shadowing_is_per_directory(self):
        self.write("CUSTOM.md", "- 루트 별칭")
        self.write(".asgard/RULES.md", "- 보조 별칭")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["CUSTOM.md", ".asgard/RULES.md"])
        self.assertEqual(loaded["shadowed"], [])

    def test_lower_alias_wins_when_higher_absent(self):
        self.write("RULES.md", "- only rules")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["RULES.md"])


class TestCommonLayer(ManualBase):
    """공통(홈) 층 — 이 기계의 모든 프로젝트. 프로젝트 층과 섞였을 때의 순서·표시가 계약이다."""

    def test_common_alone_reaches_a_project_with_no_manual(self):
        self.common("MANUAL.md", "- 보고는 내가 쓴 언어로.")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["~/.asgard/MANUAL.md"])
        self.assertEqual(loaded["common"], ["~/.asgard/MANUAL.md"])
        self.assertEqual(loaded["project"], [])
        self.assertIn("보고는 내가 쓴 언어로", M.note(self.root))

    def test_common_applies_to_every_project(self):
        self.common("MANUAL.md", "- 공통 규칙")
        with tempfile.TemporaryDirectory() as other:
            loaded = M.load_manual(other)
            assert loaded is not None
            self.assertIn("공통 규칙", loaded["body"])

    def test_project_rules_come_after_common_ones(self):
        """충돌 해소가 순서에 달려 있다 — 나중(=더 구체적인 프로젝트 규칙)이 우선한다."""
        self.common("MANUAL.md", "- 공통: 커밋은 한국어로")
        self.write("MANUAL.md", "- 프로젝트: 커밋은 영어로")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["~/.asgard/MANUAL.md", "MANUAL.md"])
        self.assertLess(loaded["body"].index("공통:"), loaded["body"].index("프로젝트:"))

    def test_layer_note_appears_only_when_both_layers_load(self):
        """한 층뿐이면 '나중 것이 우선한다'는 잡음이다 — 두 층이 실제로 실렸을 때만 붙는다."""
        self.write("MANUAL.md", "- 프로젝트만")
        self.assertNotIn("repository-specific rule wins", M.note(self.root))
        self.common("MANUAL.md", "- 공통도")
        out = M.note(self.root)
        self.assertIn("repository-specific rule wins", out)
        self.assertIn("machine-wide rules", out)

    def test_common_fragments_load_in_filename_order(self):
        self.common("MANUAL.md", "- 공통 본문")
        self.common("manual/20-b.md", "- 공통 B")
        self.common("manual/10-a.md", "- 공통 A")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(
            loaded["sources"], ["~/.asgard/MANUAL.md", "~/.asgard/manual/10-a.md", "~/.asgard/manual/20-b.md"]
        )

    def test_common_aliases_shadow_within_the_home_only(self):
        self.common("MANUAL.md", "- 공통 정본")
        self.common("RULES.md", "- 공통 별칭")
        self.write("MANUAL.md", "- 프로젝트")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["~/.asgard/MANUAL.md", "MANUAL.md"])
        self.assertEqual(loaded["shadowed"], ["~/.asgard/RULES.md"])

    def test_is_common_splits_the_two_layers(self):
        common_path = self.common("MANUAL.md", "- x")
        self.write("MANUAL.md", "- y")
        self.assertTrue(M.is_common(common_path))
        self.assertFalse(M.is_common(os.path.join(self.root, "MANUAL.md")))

    def test_kill_switch_takes_both_layers_down(self):
        self.common("MANUAL.md", "- 공통")
        self.write("MANUAL.md", "- 프로젝트")
        with mock.patch.dict(os.environ, {"ASGARD_MANUAL": "off"}):
            self.assertIsNone(M.load_manual(self.root))

    def test_same_file_is_not_loaded_twice(self):
        """홈 안에서 asgard를 돌리면 두 층이 같은 파일을 가리킨다 — 한 번만 실려야 한다."""
        home = M.home()
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "MANUAL.md"), "w", encoding="utf-8") as handle:
            handle.write("- 한 번만")
        loaded = M.load_manual(home)
        assert loaded is not None
        self.assertEqual(len(loaded["sources"]), 1)
        self.assertEqual(loaded["body"].count("한 번만"), 1)


class TestFragments(ManualBase):
    def test_fragments_append_after_the_primaries(self):
        self.write("MANUAL.md", "- base")
        self.write(".asgard/manual/20-db.md", "- db")
        self.write(".asgard/manual/10-api.md", "- api")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["MANUAL.md", ".asgard/manual/10-api.md", ".asgard/manual/20-db.md"])
        self.assertLess(loaded["body"].index("- api"), loaded["body"].index("- db"))

    def test_fragments_alone_without_primary(self):
        self.write(".asgard/manual/10-api.md", "- api only")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], [".asgard/manual/10-api.md"])

    def test_root_manual_dir_is_not_read(self):
        """루트 `manual/`은 남의 문서 폴더와 부딪힐 자리다 — 아예 안 본다."""
        self.write("manual/10-docs.md", "- 남의 문서")
        self.assertIsNone(M.load_manual(self.root))

    def test_non_markdown_fragments_ignored(self):
        self.write("MANUAL.md", "- base")
        self.write(".asgard/manual/notes.txt", "- not markdown")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["MANUAL.md"])

    def test_fragment_cap_reports_dropped(self):
        for i in range(M.FRAGMENT_CAP + 3):
            self.write(f".asgard/manual/{i:03d}.md", f"- r{i}")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(len(loaded["sources"]), M.FRAGMENT_CAP)
        self.assertEqual(len(loaded["dropped"]), 3)  # 조용히 자르지 않는다 — doctor·CLI가 말한다

    def test_empty_fragment_not_listed_as_source(self):
        self.write("MANUAL.md", "- base")
        self.write(".asgard/manual/10-empty.md", "\n\n")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["MANUAL.md"])


@unittest.skipIf(sys.platform == "win32", "심볼릭 링크 생성에 권한이 필요하다 (Windows)")
class TestSymlinkFence(ManualBase):
    """저장소 밖을 가리키는 링크는 안 넣는다.

    왜 이 검사가 있는가: `os.path.isfile`도 `os.listdir`도 링크를 따라가고 `.md` 판정은
    **링크 이름**에 걸린다. git은 트리 밖을 가리키는 링크도 그대로 커밋하므로, 울타리가
    없으면 저장소가 `MANUAL.md -> ~/.ssh/id_rsa` 하나만 담아도 그 내용이 매 세션 프롬프트로
    나간다. 매뉴얼 로더는 도구 호출이 아니라서 판독 게이트(`hooks/secret_guard.py`)가 보는
    자리가 아니다 — 여기서 안 막으면 아무도 안 막는다.

    울타리는 **프로젝트 층에만** 친다. 공통 층(홈)은 오딘 자신의 디렉터리이고 자기 노트를
    링크로 걸어 두는 것은 정당한 사용이다."""

    def secret(self, name: str, text: str) -> str:
        """리포 **밖**의 파일 — 링크가 노리는 표적."""
        path = os.path.join(self._home.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_root_manual_linking_outside_the_repo_is_not_loaded(self):
        target = self.secret("id_rsa", "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")
        os.symlink(target, os.path.join(self.root, "MANUAL.md"))
        self.assertIsNone(M.load_manual(self.root))
        self.assertNotIn("BEGIN OPENSSH", M.note(self.root))
        self.assertEqual(M.discover(self.root)["escaped"], [os.path.join(self.root, "MANUAL.md")])

    def test_fragment_linking_outside_the_repo_is_not_loaded(self):
        target = self.secret("dotenv", "AWS_SECRET_ACCESS_KEY=hunter2\n")
        self.write("MANUAL.md", "- 성한 규칙")
        os.makedirs(os.path.join(self.root, ".asgard", "manual"), exist_ok=True)
        os.symlink(target, os.path.join(self.root, ".asgard", "manual", "00-x.md"))
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["MANUAL.md"])  # 성한 것은 계속 들어간다
        self.assertNotIn("hunter2", loaded["body"])

    def test_escaped_alias_lets_the_next_one_win(self):
        """울타리 밖은 **없는 것으로 친다** — 가려진 게 아니라 후보에서 빠진다."""
        os.symlink(self.secret("id_rsa", "secret"), os.path.join(self.root, "MANUAL.md"))
        self.write("CUSTOM.md", "- 실제 규칙")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertEqual(loaded["sources"], ["CUSTOM.md"])
        self.assertEqual(loaded["shadowed"], [])

    def test_link_staying_inside_the_repo_still_works(self):
        """링크 자체를 금하지 않는다 — 저장소 안에서 문서를 모아 두는 구성은 정상이다."""
        self.write("docs/rules.md", "- 저장소 안 규칙")
        os.symlink(os.path.join(self.root, "docs", "rules.md"), os.path.join(self.root, "MANUAL.md"))
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertIn("저장소 안 규칙", loaded["body"])
        self.assertEqual(M.discover(self.root)["escaped"], [])

    def test_common_layer_may_link_anywhere(self):
        """홈은 오딘의 자리다 — 거기에 쓸 수 있는 자는 이미 더 나은 수를 갖는다."""
        notes = os.path.join(self._home.name, "my-notes.md")
        with open(notes, "w", encoding="utf-8") as handle:
            handle.write("- 내 공통 규칙")
        os.makedirs(M.home(), exist_ok=True)
        os.symlink(notes, os.path.join(M.home(), "MANUAL.md"))
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertIn("내 공통 규칙", loaded["body"])


class TestInertness(ManualBase):
    def test_comment_only_file_is_not_a_manual(self):
        self.write("MANUAL.md", "<!-- just a note -->\n\n")
        self.assertIsNone(M.load_manual(self.root))
        self.assertEqual(M.note(self.root), "")

    def test_shipped_starter_template_injects_nothing(self):
        """시작 템플릿을 배송해도 프롬프트는 한 글자도 안 늘어난다 — 이 계층의 토큰 회귀 0 근거."""
        self.write("MANUAL.md", MANUAL_STARTER_MD)
        self.assertIsNone(M.load_manual(self.root))
        self.assertEqual(M.note(self.root), "")

    def test_starter_template_has_no_stray_comment_terminator(self):
        """주석 안에 종료 기호를 글자로 쓰면 거기서 주석이 끝나 안내문 절반이 프롬프트에 들어간다."""
        self.assertEqual(M._COMMENT.sub("", MANUAL_STARTER_MD).strip(), "")

    def test_text_outside_comments_activates(self):
        self.write("MANUAL.md", MANUAL_STARTER_MD + "\n## API\n- v1 prefix.\n")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertIn("v1 prefix", loaded["body"])
        self.assertNotIn("HOW TO USE IT", loaded["body"])  # 안내문은 여전히 안 들어간다


class TestMarker(ManualBase):
    """루트 `MANUAL.md`는 흔한 이름이다 — 아스가르드가 깐 자리인지 구분할 수단이 있어야 한다."""

    def test_starter_carries_the_marker(self):
        self.write("MANUAL.md", MANUAL_STARTER_MD)
        self.assertTrue(M.has_marker(os.path.join(self.root, "MANUAL.md")))

    def test_marker_lives_in_a_comment_so_it_never_reaches_the_model(self):
        self.write("MANUAL.md", MANUAL_STARTER_MD + "\n- 규칙\n")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertNotIn(M.MARKER, loaded["body"])
        self.assertTrue(M.has_marker(os.path.join(self.root, "MANUAL.md")))  # 파일에는 남아 있다

    def test_foreign_document_has_no_marker(self):
        self.write("MANUAL.md", "# 제품 사용 설명서\n\n전원을 켜세요.\n")
        self.assertFalse(M.has_marker(os.path.join(self.root, "MANUAL.md")))
        self.assertIsNotNone(M.load_manual(self.root))  # 막지는 않는다 — 관측만 한다

    def test_missing_file_has_no_marker(self):
        self.assertFalse(M.has_marker(os.path.join(self.root, "MANUAL.md")))


class TestSizeLimit(ManualBase):
    def test_truncates_at_cap_and_says_so(self):
        self.write("MANUAL.md", "\n".join(f"- rule {i}" for i in range(4000)))
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertTrue(loaded["truncated"])
        self.assertLessEqual(loaded["chars"], M.MAX_CHARS)
        self.assertIn("truncated at the size limit", M.note(self.root))

    def test_cut_lands_on_a_line_boundary(self):
        """규칙 한 줄이 반토막 나면 없느니만 못하다."""
        self.write("MANUAL.md", "\n".join(f"- rule {i}" for i in range(4000)))
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertFalse(loaded["body"].splitlines()[-1].endswith("- rul"))

    def test_max_chars_setting_raises_the_cap(self):
        body = "\n".join(f"- rule {i}" for i in range(2000))  # 기본 상한 초과, 40000 미만
        self.assertGreater(len(body), M.MAX_CHARS)
        self.settings({"max_chars": 40000})
        self.write("MANUAL.md", body)
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertFalse(loaded["truncated"])
        self.assertEqual(M.max_chars(self.root), 40000)

    def test_max_chars_is_clamped_both_ways(self):
        self.settings({"max_chars": 0})
        self.assertEqual(M.max_chars(self.root), M.MIN_CHARS)
        self.settings({"max_chars": 10**9})
        self.assertEqual(M.max_chars(self.root), M.CEIL_CHARS)

    def test_broken_max_chars_falls_back_to_default(self):
        self.settings({"max_chars": "매우큼"})
        self.assertEqual(M.max_chars(self.root), M.MAX_CHARS)


class TestKillSwitch(ManualBase):
    def test_project_setting_off(self):
        self.write("MANUAL.md", "- rule")
        self.settings({"mode": "off"})
        self.assertFalse(M.enabled(self.root))
        self.assertIsNone(M.load_manual(self.root))
        self.assertEqual(M.note(self.root), "")

    def test_env_beats_settings(self):
        self.write("MANUAL.md", "- rule")
        self.settings({"mode": "off"})
        with mock.patch.dict(os.environ, {"ASGARD_MANUAL": "on"}):
            self.assertTrue(M.enabled(self.root))
            self.assertIsNotNone(M.load_manual(self.root))

    def test_env_off(self):
        self.write("MANUAL.md", "- rule")
        with mock.patch.dict(os.environ, {"ASGARD_MANUAL": "off"}):
            self.assertIsNone(M.load_manual(self.root))

    def test_default_is_on(self):
        self.assertTrue(M.enabled(self.root))

    def test_broken_settings_file_is_fail_open(self):
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.write("MANUAL.md", "- rule")
        self.assertTrue(M.enabled(self.root))
        self.assertIsNotNone(M.load_manual(self.root))


class TestRender(ManualBase):
    def setUp(self):
        super().setUp()
        self.write("MANUAL.md", "## API\n- v1 prefix.")

    def test_every_section_carries_the_body_and_the_source_names(self):
        for sec in M.SECTIONS:
            with self.subTest(section=sec):
                out = M.note(self.root, sec)
                self.assertIn("v1 prefix", out)
                self.assertIn("MANUAL.md", out)  # 어디서 왔는지가 항상 붙는다

    def test_authority_bounds_are_stated(self):
        """매뉴얼이 캐논을 이기면 '규칙 파일 한 줄로 안전 바닥이 열린다' — 경계가 문장으로 있어야 한다."""
        out = M.note(self.root, "identity")
        self.assertIn("never replace the Canon", out)
        for law in ("Canon 2", "3 (consent", "4 (secret"):
            self.assertIn(law, out)

    def test_identity_has_no_role_suffix(self):
        identity = M.note(self.root, "identity")
        self.assertNotIn("assigned-unit criteria", identity)
        self.assertNotIn("FAIL", identity)

    def test_thinker_asks_for_criteria_reduction(self):
        self.assertIn("assigned-unit criteria", M.note(self.root, "thinker"))

    def test_worker_scopes_rules_to_the_change(self):
        out = M.note(self.root, "worker")
        self.assertIn("code you write", out)
        self.assertIn("do not retrofit", out)  # 범위 존중 (Canon 7)

    def test_verifier_does_not_replace_criteria(self):
        out = M.note(self.root, "verifier")
        self.assertIn("FAIL", out)
        self.assertIn("does not replace criteria", out)  # evidence-first 보존

    def test_unknown_section_falls_back_to_body_only(self):
        out = M.note(self.root, "bogus")
        self.assertIn("v1 prefix", out)
        self.assertNotIn("assigned-unit criteria", out)

    def test_note_is_prefixed_so_it_concatenates_safely(self):
        """프롬프트 조각들은 문자열 이어붙이기로 조립된다 — 앞 개행이 없으면 앞 절과 붙어 버린다."""
        self.assertTrue(M.note(self.root, "identity").startswith("\n\n"))


class TestScaffold(unittest.TestCase):
    """배송 계약 — 자리를 깔되 프롬프트는 안 늘리고, 팀이 공유할 수 있고, 재실행이 안 덮는다."""

    def test_plan_files_ships_the_starter_at_the_repo_root(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/proj")
        table = dict(files)
        self.assertIn(os.path.join("/proj", "MANUAL.md"), table)
        self.assertEqual(table[os.path.join("/proj", "MANUAL.md")], MANUAL_STARTER_MD)
        # 자리는 하나만 깐다 — 무해한 템플릿이 두 군데 있으면 어느 쪽에 써야 하는지가 흐려진다.
        self.assertNotIn(os.path.join("/proj", ".asgard", "MANUAL.md"), table)

    def test_root_manual_sits_next_to_agents_md(self):
        """ "저건 아스가르드 것, 이건 내 것"이 첫 화면에서 읽혀야 한다 — 그게 루트를 고른 이유다."""
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/proj")
        names = [os.path.relpath(p, "/proj") for p, _ in files]
        self.assertIn("AGENTS.md", names)
        self.assertIn("MANUAL.md", names)

    def test_asgard_side_stays_shareable(self):
        """보조 자리를 쓰는 사람도 팀 공유가 돼야 한다 — 루트 블록과 자가 무시가 합의해야 한다."""
        from asgard.commands.setup import _ASGARD_GITIGNORE, _GITIGNORE_BLOCK

        for name in MANUAL_NAMES:
            with self.subTest(name=name):
                self.assertIn(f"!.asgard/{name}\n", _GITIGNORE_BLOCK)
                self.assertIn(f"!{name}\n", _ASGARD_GITIGNORE)
        self.assertIn("!.asgard/manual/**\n", _GITIGNORE_BLOCK)
        self.assertIn("!manual/**\n", _ASGARD_GITIGNORE)

    def test_sync_keeps_a_written_manual_in_both_places(self):
        from asgard.commands.sync import _policy

        self.assertEqual(_policy("/r", os.path.join("/r", "MANUAL.md")), "keep")
        self.assertEqual(_policy("/r", os.path.join("/r", ".asgard", "MANUAL.md")), "keep")

    def test_common_starter_is_inert_and_marked(self):
        """공통 자리도 배송하되 주입은 0 — 프로젝트 템플릿과 같은 계약이다."""
        from asgard.templates.manual import COMMON_MANUAL_STARTER_MD

        self.assertEqual(M._COMMENT.sub("", COMMON_MANUAL_STARTER_MD).strip(), "")
        self.assertIn(M.MARKER, COMMON_MANUAL_STARTER_MD)
        # 두 템플릿은 서로 다른 것을 말해야 한다 — 같은 글이면 어느 자리에 뭘 쓸지 안 갈린다.
        self.assertNotEqual(COMMON_MANUAL_STARTER_MD, MANUAL_STARTER_MD)
        self.assertIn("EVERY repository", COMMON_MANUAL_STARTER_MD)
        self.assertIn("THIS FILE IS FOR **THIS** REPOSITORY", MANUAL_STARTER_MD)
        # 각 템플릿이 상대 층을 가리켜야 사용자가 "그건 저기 쓰세요"를 읽는다.
        self.assertIn("~/.asgard/MANUAL.md", MANUAL_STARTER_MD)
        self.assertIn("that repository's root", COMMON_MANUAL_STARTER_MD)

    def test_agents_md_points_at_the_manual(self):
        """4모드 전부가 AGENTS.md를 (직접이든 브릿지로든) 읽는다 — 발견성의 공통 자리."""
        from asgard.templates import agents_md

        text = agents_md("proj")
        self.assertIn("<!-- >>> asgard:manual >>> -->", text)
        self.assertIn("`MANUAL.md` next to this file", text)
        self.assertIn("never replace it", text)


class TestNativeWiring(unittest.TestCase):
    """네이티브(모드 A) 프롬프트가 매뉴얼을 실제로 들고 가는가."""

    def _read(self, *parts: str) -> str:
        """소스 앵커 — 패키지면 그 안의 모든 모듈을 이어 붙인다.

        조립식이 어느 파일에 사는지는 이 앵커가 볼 일이 아니다. 한 파일만 보면 그 줄을 옆
        모듈로 옮기는 것만으로 계약이 사라진 것처럼 보인다."""
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "asgard")
        path = os.path.join(base, *parts)
        if not os.path.exists(path) and path.endswith(".py") and os.path.isdir(path[:-3]):
            path = path[:-3]  # `trinity.py` → `trinity/` 패키지
        if os.path.isdir(path):
            return "\n".join(
                open(os.path.join(path, name), encoding="utf-8").read()
                for name in sorted(os.listdir(path))
                if name.endswith(".py")
            )
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def _heimdall(self, root: str):
        from asgard.agent.heimdall.core import Heimdall
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="claude-x", api_key="k")
        return Heimdall(rp, root, on_text=lambda *_: None)

    def test_live_session_prompts_carry_the_manual(self):
        """소스 grep이 아니라 실제로 조립된 프롬프트 문자열을 본다 — 배선의 최종 증거."""
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "MANUAL.md"), "w", encoding="utf-8") as handle:
                handle.write("## API\n- v1 프리픽스 규칙.\n")
            hd = self._heimdall(root)
            for attr in ("identity", "delivery_identity", "manual_identity", "manual_worker"):
                with self.subTest(attr=attr):
                    self.assertIn("v1 프리픽스 규칙", getattr(hd, attr))
            self.assertIn("code you write", hd.manual_worker)
            self.assertIn("assigned-unit criteria", hd._manual_note(hd.root, "thinker"))
            self.assertIn("does not replace criteria", hd._manual_note(hd.root, "verifier"))

    def test_no_manual_leaves_the_prompt_byte_identical(self):
        """토큰 회귀 0 — 매뉴얼 없는 프로젝트의 정체성은 이 계층 도입 전과 같아야 한다."""
        with tempfile.TemporaryDirectory() as root:
            hd = self._heimdall(root)
            self.assertEqual(hd.manual_identity, "")
            self.assertEqual(hd.manual_worker, "")

    def test_worker_prompt_carries_the_manual_in_both_lanes(self):
        # 웨이브 레인은 실행 없이는 프롬프트가 안 만들어진다 — 조립식은 소스 앵커로 고정한다.
        for module in (("agent", "heimdall", "trinity.py"), ("agent", "heimdall", "waves.py")):
            with self.subTest(module=module[-1]):
                self.assertIn("hd.manual_worker", self._read(*module))

    def test_thinker_and_verifier_prompts_carry_their_sections(self):
        trinity = self._read("agent", "heimdall", "trinity.py")
        self.assertIn('hd._manual_note(hd.root, "thinker")', trinity)
        self.assertIn('hd._manual_note(hd.root, "verifier")', trinity)


def _asgard_bin() -> str | None:
    candidate = os.path.join(os.path.dirname(sys.executable), "asgard")
    return candidate if os.path.exists(candidate) else shutil.which("asgard")


@unittest.skipIf(_asgard_bin() is None, "asgard CLI 가 PATH 에 없다 — 스캐폴드를 실물로 못 돌린다")
class TestScaffoldE2E(unittest.TestCase):
    """진짜 `asgard init`을 두 번 돌린다 — 사용자가 쓴 규칙을 재스캐폴드가 덮으면 Canon 3 급 사고다."""

    bin: str

    def setUp(self):
        found = _asgard_bin()
        assert found is not None
        self.bin = found
        self.root = tempfile.mkdtemp(prefix="manual-e2e-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = tempfile.mkdtemp(prefix="manual-home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        subprocess.run(["git", "init"], cwd=self.root, capture_output=True, check=False)

    def init(self, *extra: str) -> None:
        done = subprocess.run(
            [self.bin, "init", "--cc", "--yes", "-q", *extra],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=180,
            env=isolated_home_env(self.home),  # 임시 루트를 사람의 프로젝트 목록에 안 남긴다
        )
        self.assertEqual(0, done.returncode, done.stderr)

    @property
    def path(self) -> str:
        return os.path.join(self.root, "MANUAL.md")

    def test_starter_lands_at_the_root_and_injects_nothing(self):
        self.init()
        self.assertTrue(os.path.exists(self.path))
        self.assertTrue(os.path.exists(os.path.join(self.root, "AGENTS.md")))  # 나란히
        self.assertIsNone(M.load_manual(self.root))  # 자리는 있고 프롬프트는 그대로

    def test_git_can_share_the_manual_and_its_fragments(self):
        self.init()
        os.makedirs(os.path.join(self.root, ".asgard", "manual"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "manual", "10-api.md"), "w", encoding="utf-8") as handle:
            handle.write("- v1")
        for rel in ("MANUAL.md", ".asgard/manual/10-api.md"):
            with self.subTest(rel=rel):
                ignored = subprocess.run(
                    ["git", "check-ignore", "-q", rel], cwd=self.root, capture_output=True, check=False
                )
                self.assertNotEqual(0, ignored.returncode, f"{rel} 이 무시된다 — 팀 공유 불가")

    def test_reinit_does_not_clobber_written_rules(self):
        self.init()
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("## API\n- v1 프리픽스.\n")
        self.init("--force")
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "## API\n- v1 프리픽스.\n")
        loaded = M.load_manual(self.root)
        assert loaded is not None
        self.assertIn("v1 프리픽스", loaded["body"])

    def test_a_pre_existing_root_manual_is_never_overwritten(self):
        """이미 MANUAL.md를 가진 리포에 설치해도 그 문서는 그대로 남는다 (실리는 건 doctor가 짚는다)."""
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("# 제품 사용 설명서\n\n전원을 켜세요.\n")
        self.init()
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# 제품 사용 설명서\n\n전원을 켜세요.\n")
        self.assertFalse(M.has_marker(os.path.join(self.root, "MANUAL.md")))

    def _doctor_row(self) -> dict:
        done = subprocess.run(
            [self.bin, "doctor", "--json"], cwd=self.root, capture_output=True, text=True, timeout=180
        )
        rows = [c for c in json.loads(done.stdout)["checks"] if c["name"] == "custom manual"]
        self.assertEqual(1, len(rows), done.stdout[:400])
        return rows[0]

    def test_doctor_flags_a_big_stranger_document(self):
        """루트 이름이 흔한 대가 — 남의 문서가 통째로 실리면 조용히 두지 않고 짚는다 (막지는 않는다)."""
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("# 제품 사용 설명서\n\n" + "\n".join(f"{i}. 전원을 켜세요." for i in range(900)))
        self.init()
        row = self._doctor_row()
        self.assertFalse(row["ok"])
        self.assertIn("MANUAL.md", row["detail"])
        self.assertIsNotNone(M.load_manual(self.root))  # 차단이 아니라 관측이다

    def test_doctor_is_quiet_for_a_hand_written_manual(self):
        """사용자가 손으로 쓴 짧은 규칙엔 표식이 없다 — 그걸 매번 경고하면 경고가 배경음이 된다."""
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("## API\n- v1 프리픽스.\n")
        self.init()
        row = self._doctor_row()
        self.assertTrue(row["ok"], row["detail"])
        self.assertIn("4-mode injected", row["detail"])

    def test_init_seeds_the_common_manual_once(self):
        """공통 자리는 리포 밖이라 스캐폴드 목록에 못 넣는다 — init이 없을 때만 따로 깐다."""
        with tempfile.TemporaryDirectory() as fake_home:
            env = isolated_home_env(fake_home)
            done = subprocess.run(
                [self.bin, "init", "--cc", "--yes", "-q"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            self.assertEqual(0, done.returncode, done.stderr)  # 깨진 init 을 "안 깔았다"로 오독하지 않는다
            common = os.path.join(fake_home, ".asgard", "MANUAL.md")
            self.assertTrue(os.path.exists(common))
            with open(common, "w", encoding="utf-8") as handle:
                handle.write("- 내가 쓴 공통 규칙\n")
            again = subprocess.run(
                [self.bin, "init", "--cc", "--yes", "-q", "--force"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            self.assertEqual(0, again.returncode, again.stderr)  # 안 돈 init 은 안 덮은 것의 증거가 못 된다
            with open(common, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "- 내가 쓴 공통 규칙\n")  # 두 번째 init이 안 덮는다

    def test_hook_is_scaffolded_and_wired(self):
        self.init()
        self.assertTrue(os.path.exists(os.path.join(self.root, ".claude", "hooks", "manual-activate.py")))
        with open(os.path.join(self.root, ".claude", "settings.json"), encoding="utf-8") as handle:
            self.assertIn("manual-activate", handle.read())


if __name__ == "__main__":
    unittest.main()
