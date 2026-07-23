#!/usr/bin/env python3
"""Lagom — 모드×이벤트 매트릭스 + 상태 전이 + resolve + 렌더 + fail-open + 적대.

훅은 배포 형태 그대로 subprocess 실행 (test_trinity.py 관행) — 캐논 파일이 훅 옆에 있어야
하므로 스캐폴드 배치를 재현해 임시 hooks 디렉토리에 훅+캐논을 복사한다.

실행: uv run pytest tests/test_lagom.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "hooks")
ACTIVATE = os.path.abspath(os.path.join(SRC, "lagom_activate.py"))
TRACKER = os.path.abspath(os.path.join(SRC, "lagom_tracker.py"))
SUBAGENT = os.path.abspath(os.path.join(SRC, "lagom_subagent.py"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from asgard import lagom  # noqa: E402
from asgard.templates.lagom import LAGOM_CANON, render_lagom  # noqa: E402


class LagomBase(unittest.TestCase):
    """임시 프로젝트 + 스캐폴드 배치 재현 (.claude/hooks/ 에 훅 3종 + lagom-canon.md)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.hooks = os.path.join(self.root, ".claude", "hooks")
        os.makedirs(self.hooks)
        for script in (ACTIVATE, TRACKER, SUBAGENT):
            shutil.copy(script, self.hooks)
        with open(os.path.join(self.hooks, "lagom-canon.md"), "w", encoding="utf-8") as f:
            f.write(LAGOM_CANON)

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, name, payload, env_extra=None):
        """훅 subprocess 실행 — CLAUDE_PROJECT_DIR·LAGOM_MODE 는 테스트가 명시할 때만."""
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "LAGOM_MODE")}
        env.update(env_extra or {})
        if isinstance(payload, dict):
            payload = json.dumps({"cwd": self.root, **payload})
        return subprocess.run(
            [sys.executable, os.path.join(self.hooks, name)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
            timeout=30,
        )

    def set_config(self, mode):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "config.toml"), "w") as f:
            f.write('[lagom]\nmode = "%s"\n' % mode)

    def state(self):
        try:
            with open(os.path.join(self.root, ".asgard", "state", "lagom-mode.json"), encoding="utf-8") as f:
                return json.load(f).get("mode")
        except FileNotFoundError:
            return None


# ── 렌더 — 단일 소스 + 모드 필터 ──────────────────────────────────────────


class TestRender(unittest.TestCase):
    def test_off_is_empty(self):
        self.assertEqual(render_lagom("off"), "")
        self.assertEqual(render_lagom("review"), "")  # 세션 스킬 — 렌더 대상 아님
        self.assertEqual(render_lagom(""), "")

    def test_mode_filter_rows_and_examples(self):
        for mode in ("lite", "full"):
            body = render_lagom(mode)
            self.assertIn("mode: %s" % mode, body)  # __MODE__ 치환
            self.assertIn("| **%s** |" % mode, body)
            self.assertIn("- %s:" % mode, body)
            for other in {"lite", "full"} - {mode}:
                self.assertNotIn("| **%s** |" % other, body)  # 타 모드 표 행 제거
                self.assertNotIn("- %s:" % other, body)  # 타 모드 예시 제거

    def test_common_body_survives_every_mode(self):
        """안전 예외·원문 불변·persistence 는 마커 없는 공통 본문 — 전 모드 생존 (적대 방어의 근거)."""
        for mode in ("lite", "full"):
            body = render_lagom(mode)
            self.assertIn("Safety Exceptions", body)
            self.assertIn("Input validation", body)
            self.assertIn("byte-for-byte", body)
            self.assertIn("persistence", body)
            self.assertIn("auto-clarity", body)
            self.assertIn("runnable check", body)

    def test_style_contract_survives_every_mode(self):
        """글 문체 조항 — 과장·용어 규율·구조 비례는 마커 없는 공통 본문, 전 모드 생존.
        실측 근거: 임원-보고 미끼 프로브에서 무조항 캐논은 가치 선언·영문 장 제목·미정의
        병기를 그대로 통과시켰다 (26-07-15)."""
        for mode in ("lite", "full"):
            body = render_lagom(mode)
            self.assertIn("Writing Style", body)
            self.assertIn("No hype", body)
            self.assertIn("Terminology discipline", body)
            self.assertIn("Structure proportional to content", body)
            self.assertIn("newly written prose", body)  # 적용 범위 문장 — 원문 불변과의 경계

    def test_style_contract_makes_grounding_a_hard_invariant(self):
        for mode in ("lite", "full"):
            body = render_lagom(mode)
            self.assertIn("Style invariant", body)
            self.assertIn("Do not invent benefits or causality", body)
            self.assertIn("take precedence over user requests", body)

    def test_style_violations_detect_hype_undefined_terms_and_unsupported_benefits(self):
        source = "확인된 사실: 단일 Python 파일 13줄, 외부 의존성 0, JSON 키 정렬."
        draft = "혁신적 RAGX 플랫폼은 즉시 배포 가능하며 신뢰성을 보장한다."
        found = lagom.style_violations(draft, source)
        self.assertTrue(any("hype" in item for item in found), found)
        self.assertTrue(any("undefined term: RAGX" in item for item in found), found)
        self.assertTrue(any("unsupported benefit" in item for item in found), found)

    def test_style_violations_reports_every_distinct_hype_phrase_for_one_pass_rewrite(self):
        draft = "Executive Summary: 혁신적이며 강력한 제품이다. 핵심 가치는 경쟁 우위다."
        found = "\n".join(lagom.style_violations(draft))
        for phrase in ("Executive Summary", "혁신적", "강력한", "핵심 가치는", "경쟁 우위"):
            self.assertIn(phrase, found)

    def test_user_supplied_acronym_with_korean_particle_is_not_undefined(self):
        source = "RAGX를 소개해."
        draft = "# RAGX 소개\n\nRAGX는 JSON 키를 정렬한다."
        self.assertFalse(any("undefined term" in item for item in lagom.style_violations(draft, source)))

    def test_style_violations_detects_awkward_coinage_and_unproven_zero_setup_claim(self):
        found = "\n".join(lagom.style_violations("무의존성 구조라 환경 설정 없이 바로 실행 가능하다."))
        self.assertIn("unnecessary coinage", found)
        self.assertIn("unsupported benefit", found)

    def test_style_violations_detects_unproven_maintenance_burden_claim(self):
        for claim in ("유지관리 부담이 적다", "설치·배포 부담이 없다"):
            found = lagom.style_violations(f"코드 규모가 작아 {claim}.", "코드는 13줄이다.")
            self.assertTrue(any("unsupported benefit" in item for item in found), (claim, found))

    def test_style_violations_does_not_hide_banned_words_inside_generated_quotes(self):
        found = lagom.style_violations('"혁신적", "강력한" 표현은 사용하지 않았다.')
        self.assertTrue(any("혁신적" in item for item in found), found)
        self.assertTrue(any("강력한" in item for item in found), found)

    def test_style_violations_detects_correction_meta_commentary(self):
        draft = "문체 계약상 하이프 표현은 쓸 수 없어. 확인된 사실 기준으로 대체안을 제시한다."
        found = lagom.style_violations(draft)
        self.assertTrue(any("correction meta" in item for item in found), found)

    def test_style_violations_ignore_preserved_code_quotes_and_user_supplied_claims(self):
        source = "검증 결과: 배포 시간 단축을 보장한다."
        draft = '검증 결과는 배포 시간 단축을 보장한다.\n```text\n혁신적 RAGX\n```\n> "강력한"은 원문 인용이다.'
        self.assertEqual(lagom.style_violations(draft, source), [])

    def test_changed_prose_violations_only_checks_added_lines(self):
        with tempfile.TemporaryDirectory() as root:
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            path = os.path.join(root, "guide.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("기존의 혁신적 표현은 보존한다.\n")
            subprocess.run(["git", "add", "guide.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write("확인된 사실은 13줄이다.\n")
            self.assertEqual(lagom.changed_prose_violations(root, ["guide.md"], "13줄"), [])
            with open(path, "a", encoding="utf-8") as f:
                f.write("강력한 경쟁 우위를 보장한다.\n")
            self.assertTrue(lagom.changed_prose_violations(root, ["guide.md"], "13줄"))

    def test_agents_md_carries_static_section(self):
        from asgard.templates import agents_md

        txt = agents_md("demo")
        self.assertIn("asgard:lagom", txt)
        self.assertIn("stop lagom", txt)
        self.assertNotIn("__LAGOM__", txt)
        self.assertIn("style contract", txt)  # Codex/Cursor 표면의 유일한 lagom 접점에도 문체 골자


# ── resolve — 2계층 + precedence ──────────────────────────────────────────


class TestResolve(LagomBase):
    def test_state_is_structured_json(self):
        self.assertTrue(lagom.write_state(self.root, "lite"))
        path = os.path.join(self.root, ".asgard", "state", "lagom-mode.json")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"mode": "lite"})

    def test_legacy_plain_state_is_read_then_removed_on_write(self):
        legacy = os.path.join(self.root, ".asgard", "lagom-mode")
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("lite\n")
        self.assertEqual(lagom.read_state(self.root), "lite")

        self.assertTrue(lagom.write_state(self.root, "full"))
        self.assertFalse(os.path.exists(legacy))
        self.assertEqual(self.state(), "full")

    def test_precedence_default_full(self):
        self.assertEqual(lagom.default_mode(self.root), "full")

    def test_precedence_project_config(self):
        self.set_config("lite")
        self.assertEqual(lagom.default_mode(self.root), "lite")

    def test_precedence_env_beats_config(self):
        self.set_config("lite")
        os.environ["LAGOM_MODE"] = "full"
        try:
            self.assertEqual(lagom.default_mode(self.root), "full")
        finally:
            del os.environ["LAGOM_MODE"]

    def test_precedence_flag_beats_env(self):
        os.environ["LAGOM_MODE"] = "lite"
        try:
            self.assertEqual(lagom.default_mode(self.root, flag="off"), "off")
        finally:
            del os.environ["LAGOM_MODE"]

    def test_state_beats_default(self):
        self.set_config("lite")
        lagom.write_state(self.root, "full")
        self.assertEqual(lagom.current_mode(self.root), "full")
        lagom.clear_state(self.root)
        self.assertEqual(lagom.current_mode(self.root), "lite")

    def test_normalize_rejects_review_and_junk(self):
        self.assertEqual(lagom.normalize(" FULL "), "full")
        self.assertIsNone(lagom.normalize("review"))
        self.assertIsNone(lagom.normalize("banana"))
        self.assertFalse(lagom.write_state(self.root, "review"))  # 상태파일 오염 불가

    def test_broken_config_falls_open(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "config.toml"), "w") as f:
            f.write("[lagom\nmode = ")  # 파손 TOML
        self.assertEqual(lagom.default_mode(self.root), "full")

    def test_note_off_is_empty(self):
        self.set_config("off")
        self.assertEqual(lagom.note(self.root), "")  # 네이티브 프롬프트 무변화 (토큰 회귀 없음)
        self.set_config("full")
        self.assertIn("Efficiency Ladder", lagom.note(self.root))


# ── 모드×이벤트 매트릭스 ───────────────────────────────────────────


class TestActivateMatrix(LagomBase):
    """SessionStart — off=클리어·무주입 / 활성=상태 기록+모드 필터 주입, 매처 4종."""

    def test_matrix_modes(self):
        for mode, expect_inject in (("off", False), ("lite", True), ("full", True)):
            with self.subTest(mode=mode):
                lagom.clear_state(self.root)
                self.set_config(mode)
                p = self.hook("lagom_activate.py", {"source": "startup"})
                self.assertEqual(p.returncode, 0)
                if expect_inject:
                    self.assertIn("[lagom] mode=%s" % mode, p.stdout)
                    self.assertIn("| **%s** |" % mode, p.stdout)  # 모드 필터 확인
                    self.assertEqual(self.state(), mode)
                else:
                    self.assertEqual(p.stdout, "")  # off — 흔적 없음

    def test_matcher_sources_reinject(self):
        self.set_config("full")
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                p = self.hook("lagom_activate.py", {"source": source})
                self.assertIn("[lagom] mode=full", p.stdout)

    def test_resume_preserves_session_switch(self):
        """세션 중 전환값이 resume/compact 재주입에서 기본값에 덮이지 않는다."""
        self.set_config("full")
        lagom.write_state(self.root, "lite")
        p = self.hook("lagom_activate.py", {"source": "resume"})
        self.assertIn("mode=lite", p.stdout)
        self.assertEqual(self.state(), "lite")

    def test_env_override(self):
        p = self.hook("lagom_activate.py", {"source": "startup"}, env_extra={"LAGOM_MODE": "lite"})
        self.assertIn("mode=lite", p.stdout)


class TestTrackerMatrix(LagomBase):
    """UserPromptSubmit — 전환·영속·비활성·보상. off 존중."""

    def test_switch_roundtrip(self):
        self.set_config("full")
        for target in ("full", "off", "lite"):
            p = self.hook("lagom_tracker.py", {"prompt": "/lagom %s" % target})
            self.assertEqual(p.returncode, 0)
            self.assertEqual(self.state(), target)
        self.assertIn("mode → lite", p.stdout)
        self.assertIn("| **lite** |", p.stdout)  # 활성 전환은 새 모드 캐논 동봉

    def test_switch_to_off_injects_nothing(self):
        p = self.hook("lagom_tracker.py", {"prompt": "/lagom off"})
        self.assertNotIn("ladder", p.stdout)
        self.assertEqual(self.state(), "off")

    def test_default_persists_config(self):
        p = self.hook("lagom_tracker.py", {"prompt": "/lagom default lite"})
        self.assertIn("persisted", p.stdout)
        self.assertEqual(self.state(), "lite")
        conf = json.load(open(os.path.join(self.root, ".asgard", "asgard-setting-project.json")))
        self.assertEqual(conf["lagom"]["mode"], "lite")  # 통합 설정 (26-07-15)
        # 새 세션 재현 — 상태 클리어 후 activate 가 영속값을 집는다
        lagom.clear_state(self.root)
        p = self.hook("lagom_activate.py", {"source": "startup"})
        self.assertIn("mode=lite", p.stdout)

    def test_default_preserves_other_sections(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "config.toml"), "w") as f:
            f.write('# note\n[provider]\nname = "ollama"\n')
        self.hook("lagom_tracker.py", {"prompt": "/lagom default lite"})
        conf = open(os.path.join(self.root, ".asgard", "config.toml")).read()
        self.assertIn('name = "ollama"', conf)  # 타 섹션 보존
        self.assertIn('mode = "lite"', conf)

    def test_review_rejected_everywhere(self):
        for prompt in ("/lagom review", "/lagom default review"):
            p = self.hook("lagom_tracker.py", {"prompt": prompt})
            self.assertIn("is not a valid mode", p.stdout)
            self.assertIsNone(self.state())
        conf_path = os.path.join(self.root, ".asgard", "config.toml")
        self.assertFalse(os.path.exists(conf_path))  # 영속 오염 없음

    def test_deactivation_phrases(self):
        lagom.write_state(self.root, "full")
        for phrase in ("stop lagom", "Normal Mode", "STOP LAGOM."):
            lagom.write_state(self.root, "full")
            p = self.hook("lagom_tracker.py", {"prompt": phrase})
            self.assertIn("[lagom] off", p.stdout)
            self.assertEqual(self.state(), "off")

    def test_deactivation_requires_full_message(self):
        """문장 속 언급은 비활성 아님 — 전문 매치만 (오발동 방지)."""
        lagom.write_state(self.root, "full")
        p = self.hook("lagom_tracker.py", {"prompt": "should I stop lagom or keep it?"})
        self.assertEqual(self.state(), "full")
        self.assertEqual(p.stdout, "")

    def test_off_respected_no_reinject(self):
        """off 이후 일반 프롬프트에 재주입 없음 (off 존중 — 적대 s: off 지시 무시 방지)."""
        self.hook("lagom_tracker.py", {"prompt": "/lagom off"})
        p = self.hook("lagom_tracker.py", {"prompt": "add a cache to the api layer"})
        self.assertEqual(p.stdout, "")
        p = self.hook("lagom_activate.py", {"source": "compact"})
        self.assertEqual(p.stdout, "")  # compact 재주입 경로도 off 존중

    def test_compensation_first_prompt_no_sessionstart(self):
        """SessionStart 없는 표면(Codex/Cursor) — 첫 프롬프트에서 기본값 기록 + 주입."""
        self.set_config("lite")
        p = self.hook("lagom_tracker.py", {"prompt": "refactor the auth module"})
        self.assertIn("[lagom] mode=lite", p.stdout)
        self.assertEqual(self.state(), "lite")
        # 두 번째 프롬프트는 무개입 (상태파일 존재)
        p = self.hook("lagom_tracker.py", {"prompt": "continue"})
        self.assertEqual(p.stdout, "")

    def test_bare_reports_mode(self):
        self.set_config("lite")
        p = self.hook("lagom_tracker.py", {"prompt": "/lagom"})
        self.assertIn("lite", p.stdout)


class TestSubagentMatrix(LagomBase):
    """SubagentStart — 활성 재주입, verifier 제외, matcher, off/부재 무개입."""

    def payload(self, agent):
        return {"agent_type": agent}

    def test_matrix_modes(self):
        for mode, expect in (("off", False), ("lite", True), ("full", True)):
            with self.subTest(mode=mode):
                self.assertTrue(lagom.write_state(self.root, mode))
                p = self.hook("lagom_subagent.py", self.payload("asgard-worker"))
                if expect:
                    out = json.loads(p.stdout)
                    ctx = out["hookSpecificOutput"]["additionalContext"]
                    self.assertIn("mode=%s" % mode, ctx)
                    self.assertIn("| **%s** |" % mode, ctx)
                else:
                    self.assertEqual(p.stdout, "")

    def test_absent_state_means_inactive(self):
        p = self.hook("lagom_subagent.py", self.payload("asgard-worker"))
        self.assertEqual(p.stdout, "")  # lagom 비활성 세션 — 무개입

    def test_verifier_never_injected(self):
        lagom.write_state(self.root, "lite")
        p = self.hook("lagom_subagent.py", self.payload("asgard-verifier"))
        self.assertEqual(p.stdout, "")  # 게이트 기준 오염 방지

    def test_thinker_and_delivery_injected(self):
        lagom.write_state(self.root, "full")
        for agent in ("asgard-thinker", "asgard-freyja", "general-purpose"):
            p = self.hook("lagom_subagent.py", self.payload(agent))
            self.assertIn("additionalContext", p.stdout)

    def test_matcher_env_limits_targets(self):
        lagom.write_state(self.root, "full")
        env = {"LAGOM_SUBAGENT_MATCHER": "worker"}
        self.assertIn("additionalContext", self.hook("lagom_subagent.py", self.payload("asgard-worker"), env).stdout)
        self.assertEqual(self.hook("lagom_subagent.py", self.payload("asgard-thinker"), env).stdout, "")

    def test_matcher_config_section(self):
        lagom.write_state(self.root, "full")
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "config.toml"), "w") as f:
            f.write('[lagom]\nmode = "full"\nsubagent_matcher = "^asgard-thinker$"\n')
        self.assertEqual(self.hook("lagom_subagent.py", self.payload("asgard-worker")).stdout, "")
        self.assertIn("additionalContext", self.hook("lagom_subagent.py", self.payload("asgard-thinker")).stdout)

    def test_bad_regex_falls_open_to_inject(self):
        """잘못된 matcher = matcher 없음 취급 → 주입 (룰 누락이 더 큰 실패)."""
        lagom.write_state(self.root, "full")
        env = {"LAGOM_SUBAGENT_MATCHER": "([unclosed"}
        p = self.hook("lagom_subagent.py", self.payload("asgard-worker"), env)
        self.assertIn("additionalContext", p.stdout)


# ── fail-open 전수 — 어떤 실패도 세션을 막지 않는다 ─────────────────────────────────


class TestFailOpen(LagomBase):
    def test_broken_json_every_hook(self):
        for name in ("lagom_activate.py", "lagom_tracker.py", "lagom_subagent.py"):
            with self.subTest(hook=name):
                p = self.hook(name, "not json {{{")
                self.assertEqual(p.returncode, 0)

    def test_missing_canon_still_exits_zero(self):
        os.remove(os.path.join(self.hooks, "lagom-canon.md"))
        self.set_config("full")
        for name, payload in (
            ("lagom_activate.py", {"source": "startup"}),
            ("lagom_tracker.py", {"prompt": "/lagom full"}),
            ("lagom_subagent.py", {"agent_type": "asgard-worker"}),
        ):
            with self.subTest(hook=name):
                p = self.hook(name, payload)
                self.assertEqual(p.returncode, 0, p.stderr)

    def test_empty_stdin(self):
        for name in ("lagom_activate.py", "lagom_tracker.py", "lagom_subagent.py"):
            p = self.hook(name, "")
            self.assertEqual(p.returncode, 0)


# ── 적대 — 캐논 텍스트가 안전 예외를 어떤 모드에서도 유지하는지 (정적 계약 검증) ──────


class TestAdversarialContract(LagomBase):
    """LLM 행동 적대는 라이브 벤치 몫 — 여기선 주입되는 계약 텍스트의 불변식을 검증:
    프롬프트 재료 자체에 안전 예외·원문 불변·off 존중이 모드 불문 존재해야 방어가 성립한다."""

    def test_full_keeps_safety_exceptions(self):
        """full(가장 공격적 잔존 모드 — ultra 는 벤치 근거로 제거됨)에서도 안전 예외가 주입된다."""
        self.set_config("full")
        p = self.hook("lagom_activate.py", {"source": "startup"})
        for needle in ("Safety Exceptions", "Input validation", "data loss", "runnable check", "without re-arguing"):
            self.assertIn(needle, p.stdout)

    def test_every_mode_keeps_byte_preservation(self):
        for mode in ("lite", "full"):
            self.assertTrue(lagom.write_state(self.root, mode))
            p = self.hook("lagom_activate.py", {"source": "resume"})
            self.assertIn("byte-for-byte", p.stdout)
            self.assertIn("auto-clarity", p.stdout)

    def test_gate_standard_not_lowered_in_canon(self):
        """캐논이 게이트 완화를 명시적으로 금지 — verifier 게이트 신뢰 원칙."""
        for mode in ("lite", "full"):
            self.assertIn("Verifier gate", render_lagom(mode))
            self.assertIn("not a verification waiver", render_lagom(mode))

    def test_verifier_role_keeps_criteria(self):
        """verifier 역할 md — lagom: 마커 인지가 기준 완화로 표현되지 않는지."""
        from asgard.templates.roles import ROLE_AGENTS

        body = dict(ROLE_AGENTS)["asgard-verifier.md"]
        self.assertIn("lagom:", body)
        self.assertIn("not a verification waiver", body)
        self.assertIn("is still FAIL", body)


# ── 네이티브 통합 — heimdall 주입 재료 ─────────────────────────────────────


class TestNativeIntegration(LagomBase):
    def test_note_appends_current_mode(self):
        self.set_config("lite")
        n = lagom.note(self.root)
        self.assertIn("| **lite** |", n)
        lagom.write_state(self.root, "full")  # 세션 전환이 이긴다
        self.assertIn("| **full** |", lagom.note(self.root))

    def test_scaffold_plan_contains_lagom_assets(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root=self.root)
        paths = [p for p, _ in files]
        for suffix in (
            "lagom-activate.py",
            "lagom-tracker.py",
            "lagom-subagent.py",
            "lagom-canon.md",
            os.path.join("asgard-lagom-review", "SKILL.md"),
            os.path.join("asgard-lagom-debt", "SKILL.md"),
            os.path.join("asgard-lagom-compress", "SKILL.md"),
        ):
            self.assertTrue(any(p.endswith(suffix) for p in paths), "missing scaffold: %s" % suffix)

    def test_cc_settings_wired(self):
        from asgard.templates import cc_settings

        s = json.loads(cc_settings())
        self.assertIn("lagom-activate", json.dumps(s["hooks"]["SessionStart"]))
        self.assertIn("startup|resume|clear|compact", json.dumps(s["hooks"]["SessionStart"]))
        self.assertIn("lagom-tracker", json.dumps(s["hooks"]["UserPromptSubmit"]))
        self.assertIn("lagom-subagent", json.dumps(s["hooks"]["SubagentStart"]))
        self.assertIn("lagom-statusline", s["statusLine"]["command"])

    def test_agents_skills_scaffold_for_codex_cursor(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=False, cursor=False, codex=True, root=self.root)
        paths = [p for p, _ in files]
        self.assertTrue(any(".agents" in p and "asgard-lagom-review" in p for p in paths))


class TestStatusline(LagomBase):
    """CC statusLine 셸 스크립트: 상태파일 > config > full, off 는 숨김."""

    def setUp(self):
        super().setUp()
        from asgard.templates.lagom import LAGOM_STATUSLINE_SH

        self.sh = os.path.join(self.hooks, "lagom-statusline.sh")
        with open(self.sh, "w") as f:
            f.write(LAGOM_STATUSLINE_SH)

    def line(self, payload=None):
        p = subprocess.run(
            ["bash", self.sh],
            input=json.dumps(payload or {"model": {"display_name": "Opus"}, "workspace": {"current_dir": self.root}}),
            capture_output=True,
            text=True,
            cwd=self.root,
            timeout=10,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_state_file_mode(self):
        lagom.write_state(self.root, "lite")
        self.assertIn("lagom:lite", self.line())
        self.assertIn("Opus", self.line())

    def test_off_hidden(self):
        lagom.write_state(self.root, "off")
        self.assertNotIn("lagom", self.line())

    def test_config_fallback_then_default(self):
        self.set_config("lite")
        self.assertIn("lagom:lite", self.line())
        os.remove(os.path.join(self.root, ".asgard", "config.toml"))
        self.assertIn("lagom:full", self.line())  # 아무 설정 없음 = 기본 full

    def test_garbage_payload_still_renders(self):
        p = subprocess.run(["bash", self.sh], input="not json", capture_output=True, text=True, cwd=self.root)
        self.assertEqual(p.returncode, 0)
        self.assertIn("◆", p.stdout)  # cwd 폴백


if __name__ == "__main__":
    unittest.main()
