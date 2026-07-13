#!/usr/bin/env python3
"""Lagom (CUS-211) — 모드×이벤트 매트릭스 + 상태 전이 + resolve + 렌더 + fail-open + 적대.

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
            return open(os.path.join(self.root, ".asgard", "lagom-mode")).read().strip()
        except FileNotFoundError:
            return None


# ── 렌더 (CUS-206) — 단일 소스 + 모드 필터 ──────────────────────────────────────────


class TestRender(unittest.TestCase):
    def test_off_is_empty(self):
        self.assertEqual(render_lagom("off"), "")
        self.assertEqual(render_lagom("review"), "")  # 세션 스킬 — 렌더 대상 아님
        self.assertEqual(render_lagom(""), "")

    def test_mode_filter_rows_and_examples(self):
        for mode in ("lite", "full", "ultra"):
            body = render_lagom(mode)
            self.assertIn("모드: %s" % mode, body)  # __MODE__ 치환
            self.assertIn("| **%s** |" % mode, body)
            self.assertIn("- %s:" % mode, body)
            for other in {"lite", "full", "ultra"} - {mode}:
                self.assertNotIn("| **%s** |" % other, body)  # 타 모드 표 행 제거
                self.assertNotIn("- %s:" % other, body)  # 타 모드 예시 제거

    def test_common_body_survives_every_mode(self):
        """안전 예외·원문 불변·persistence 는 마커 없는 공통 본문 — 전 모드 생존 (적대 방어의 근거)."""
        for mode in ("lite", "full", "ultra"):
            body = render_lagom(mode)
            self.assertIn("안전 예외", body)
            self.assertIn("입력 검증", body)
            self.assertIn("byte-for-byte", body)
            self.assertIn("persistence", body)
            self.assertIn("auto-clarity", body)
            self.assertIn("러너블 체크", body)

    def test_agents_md_carries_static_section(self):
        from asgard.templates import agents_md

        txt = agents_md("demo")
        self.assertIn("asgard:lagom", txt)
        self.assertIn("stop lagom", txt)
        self.assertNotIn("__LAGOM__", txt)


# ── resolve (CUS-207) — 2계층 + precedence ──────────────────────────────────────────


class TestResolve(LagomBase):
    def test_precedence_default_full(self):
        self.assertEqual(lagom.default_mode(self.root), "full")

    def test_precedence_project_config(self):
        self.set_config("ultra")
        self.assertEqual(lagom.default_mode(self.root), "ultra")

    def test_precedence_env_beats_config(self):
        self.set_config("ultra")
        os.environ["LAGOM_MODE"] = "lite"
        try:
            self.assertEqual(lagom.default_mode(self.root), "lite")
        finally:
            del os.environ["LAGOM_MODE"]

    def test_precedence_flag_beats_env(self):
        os.environ["LAGOM_MODE"] = "lite"
        try:
            self.assertEqual(lagom.default_mode(self.root, flag="off"), "off")
        finally:
            del os.environ["LAGOM_MODE"]

    def test_state_beats_default(self):
        self.set_config("ultra")
        lagom.write_state(self.root, "lite")
        self.assertEqual(lagom.current_mode(self.root), "lite")
        lagom.clear_state(self.root)
        self.assertEqual(lagom.current_mode(self.root), "ultra")

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
        self.assertIn("효율 사다리", lagom.note(self.root))


# ── 모드×이벤트 매트릭스 (CUS-208/213/214) ───────────────────────────────────────────


class TestActivateMatrix(LagomBase):
    """SessionStart — off=클리어·무주입 / 활성=상태 기록+모드 필터 주입, 매처 4종."""

    def test_matrix_modes(self):
        for mode, expect_inject in (("off", False), ("lite", True), ("full", True), ("ultra", True)):
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
        self.set_config("ultra")
        lagom.write_state(self.root, "lite")
        p = self.hook("lagom_activate.py", {"source": "resume"})
        self.assertIn("mode=lite", p.stdout)
        self.assertEqual(self.state(), "lite")

    def test_env_override(self):
        p = self.hook("lagom_activate.py", {"source": "startup"}, env_extra={"LAGOM_MODE": "ultra"})
        self.assertIn("mode=ultra", p.stdout)


class TestTrackerMatrix(LagomBase):
    """UserPromptSubmit — 전환·영속·비활성·보상. off 존중."""

    def test_switch_roundtrip(self):
        self.set_config("full")
        for target in ("ultra", "off", "lite"):
            p = self.hook("lagom_tracker.py", {"prompt": "/lagom %s" % target})
            self.assertEqual(p.returncode, 0)
            self.assertEqual(self.state(), target)
        self.assertIn("mode → lite", p.stdout)
        self.assertIn("| **lite** |", p.stdout)  # 활성 전환은 새 모드 캐논 동봉

    def test_switch_to_off_injects_nothing(self):
        p = self.hook("lagom_tracker.py", {"prompt": "/lagom off"})
        self.assertNotIn("사다리", p.stdout)
        self.assertEqual(self.state(), "off")

    def test_default_persists_config(self):
        p = self.hook("lagom_tracker.py", {"prompt": "/lagom default ultra"})
        self.assertIn("영속", p.stdout)
        self.assertEqual(self.state(), "ultra")
        conf = open(os.path.join(self.root, ".asgard", "config.toml")).read()
        self.assertIn('mode = "ultra"', conf)
        # 새 세션 재현 — 상태 클리어 후 activate 가 영속값을 집는다
        lagom.clear_state(self.root)
        p = self.hook("lagom_activate.py", {"source": "startup"})
        self.assertIn("mode=ultra", p.stdout)

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
            self.assertIn("유효한 모드가 아니다", p.stdout)
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
        self.set_config("ultra")
        p = self.hook("lagom_tracker.py", {"prompt": "/lagom"})
        self.assertIn("ultra", p.stdout)


class TestSubagentMatrix(LagomBase):
    """SubagentStart — 활성 재주입, verifier 제외, matcher, off/부재 무개입."""

    def payload(self, agent):
        return {"agent_type": agent}

    def test_matrix_modes(self):
        for mode, expect in (("off", False), ("lite", True), ("full", True), ("ultra", True)):
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
        lagom.write_state(self.root, "ultra")
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
            ("lagom_tracker.py", {"prompt": "/lagom ultra"}),
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
    """LLM 행동 적대는 라이브 벤치(CUS-212) 몫 — 여기선 주입되는 계약 텍스트의 불변식을 검증:
    프롬프트 재료 자체에 안전 예외·원문 불변·off 존중이 모드 불문 존재해야 방어가 성립한다."""

    def test_ultra_keeps_safety_exceptions(self):
        """ultra(가장 공격적)에서도 안전 예외·러너블 체크·명시 요청 존중이 주입된다."""
        self.set_config("ultra")
        p = self.hook("lagom_activate.py", {"source": "startup"})
        for needle in ("안전 예외", "입력 검증", "데이터 손실", "러너블 체크", "재논쟁 없이 구현"):
            self.assertIn(needle, p.stdout)

    def test_every_mode_keeps_byte_preservation(self):
        for mode in ("lite", "full", "ultra"):
            self.assertTrue(lagom.write_state(self.root, mode))
            p = self.hook("lagom_activate.py", {"source": "resume"})
            self.assertIn("byte-for-byte", p.stdout)
            self.assertIn("auto-clarity", p.stdout)

    def test_gate_standard_not_lowered_in_canon(self):
        """캐논이 게이트 완화를 명시적으로 금지 — verifier 게이트 신뢰 원칙."""
        for mode in ("lite", "full", "ultra"):
            self.assertIn("게이트", render_lagom(mode))
            self.assertIn("검증 면제가 아니다", render_lagom(mode))

    def test_verifier_role_keeps_criteria(self):
        """verifier 역할 md — lagom: 마커 인지가 기준 완화로 표현되지 않는지."""
        from asgard.templates.roles import ROLE_AGENTS

        body = dict(ROLE_AGENTS)["asgard-verifier.md"]
        self.assertIn("lagom:", body)
        self.assertIn("검증 면제가 아니다", body)
        self.assertIn("FAIL 이다", body)


# ── 네이티브 통합 (CUS-209) — heimdall 주입 재료 ─────────────────────────────────────


class TestNativeIntegration(LagomBase):
    def test_note_appends_current_mode(self):
        self.set_config("lite")
        n = lagom.note(self.root)
        self.assertIn("| **lite** |", n)
        lagom.write_state(self.root, "ultra")  # 세션 전환이 이긴다
        self.assertIn("| **ultra** |", lagom.note(self.root))

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

    def test_agents_skills_scaffold_for_codex_cursor(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=False, cursor=False, codex=True, root=self.root)
        paths = [p for p, _ in files]
        self.assertTrue(any(".agents" in p and "asgard-lagom-review" in p for p in paths))


if __name__ == "__main__":
    unittest.main()
