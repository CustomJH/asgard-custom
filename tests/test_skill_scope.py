"""범위 형상 라우터 + 판정 결함 분류 앵커.

두 축을 고정한다:
  ① 지시 → 작업 형상(slice/feature/expedition)과 규율 렌즈가 결정론이라는 것 — 같은 지시에
     같은 결속이 나와야 모델의 자율 선택 위에 얹힌 층으로 신뢰할 수 있다.
  ② 판정에 실린 결함이 소유자(기계 수리 ↔ 사람 판단)로 갈린다는 것 — 분류 불가는 사람 쪽으로
     닫힌다 (fail-closed).
"""

from __future__ import annotations

import tempfile
import unittest

from asgard.agent.heimdall.roles import work_shape_note
from asgard.agent.heimdall.toolspec import VERDICT_TOOL
from asgard.agent.heimdall.trinity import _classified_findings
from asgard.hooks.quest_log import normalize
from asgard.skill_scope import bound_skills, scope_note, work_shape
from asgard.templates.roles import ROLE_AGENTS

_WRITE = {"write_expected": True, "task_class": "standard"}


class WorkShapeTest(unittest.TestCase):
    def test_read_only_request_has_no_shape(self):
        result = work_shape("이 함수 뭐하는 거야?", {"write_expected": False, "task_class": "trivial"})
        self.assertEqual(result["shape"], "direct")

    def test_ordinary_write_is_one_slice(self):
        self.assertEqual(work_shape("로그인 화면에 소셜 로그인 버튼 추가해줘", _WRITE)["shape"], "slice")

    def test_deep_task_class_becomes_a_feature(self):
        result = work_shape("결제 흐름 손봐줘", {"write_expected": True, "task_class": "deep"})
        self.assertEqual(result["shape"], "feature")

    def test_explicit_fan_out_becomes_a_feature(self):
        result = work_shape(
            "이거 처리해줘", {"write_expected": True, "task_class": "standard", "parallel_requested": True}
        )
        self.assertEqual(result["shape"], "feature")
        self.assertIn("fan-out", result["why"])

    def test_new_surface_marker_upgrades_a_trivial_class(self):
        result = work_shape("신규 엔드포인트 추가", {"write_expected": True, "task_class": "trivial"})
        self.assertEqual(result["shape"], "feature")

    def test_multi_session_marker_becomes_an_expedition(self):
        for request in ("결제 모듈 전면 재설계해줘", "migrate the auth layer to the new provider"):
            with self.subTest(request=request):
                self.assertEqual(work_shape(request, _WRITE)["shape"], "expedition")

    def test_expedition_outranks_the_deep_class(self):
        # 예산 축(deep)이 규율 축을 덮어쓰면 원정이 기능으로 강등돼 미해결 결정이 구현 단위가 된다.
        result = work_shape("전면 재설계", {"write_expected": True, "task_class": "deep"})
        self.assertEqual(result["shape"], "expedition")

    def test_lenses_are_independent_and_can_stack(self):
        result = work_shape("이 버그 원인 찾아 고치고 회귀 테스트도 추가해줘", _WRITE)
        self.assertEqual(set(result["lenses"]), {"bug", "test"})

    def test_korean_only_request_still_binds_a_discipline(self):
        # 상류 트리거는 영어 부분 문자열이라 한국어 지시에 불발한다 — 이 층이 그 발견 실패를 메운다.
        result = work_shape("머지 충돌 해결해줘", _WRITE)
        self.assertEqual(result["lenses"], ("merge",))
        self.assertEqual(bound_skills(result), ("merge-resolution",))

    def test_shape_is_deterministic(self):
        request = "리팩터링하면서 계층 경계 정리해줘"
        self.assertEqual(work_shape(request, _WRITE), work_shape(request, _WRITE))


class ScopeNoteTest(unittest.TestCase):
    def test_read_only_turn_costs_no_tokens(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(scope_note(root, "설명해줘", {"write_expected": False}), "")

    def test_note_names_only_skills_open_to_that_role(self):
        with tempfile.TemporaryDirectory() as root:
            note = scope_note(root, "머지 충돌 해결해줘", _WRITE)
            self.assertIn("merge-resolution", note)
            # freyja 에는 배정되지 않은 스킬이라 이름이 나오면 로드 실패로 턴을 태운다.
            self.assertNotIn("merge-resolution", scope_note(root, "머지 충돌 해결해줘", _WRITE, agent="freyja"))

    def test_loader_wording_matches_the_surface(self):
        with tempfile.TemporaryDirectory() as root:
            task = "이 버그 재현해서 고쳐줘"
            self.assertIn("`load_skill` tool", scope_note(root, task, _WRITE))
            self.assertIn("asgard skills show", scope_note(root, task, _WRITE, loader="cli"))
            # Thinker 는 load_skill 표면이 없다 — 배정 단위에 이름을 싣는 판.
            self.assertIn("assignment unit", scope_note(root, task, _WRITE, loader="none"))

    def test_every_shape_carries_its_discipline(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIn("vertical slice", scope_note(root, "버튼 색 바꿔줘", _WRITE))
            self.assertIn("out of scope", scope_note(root, "신규 화면 추가", _WRITE))
            self.assertIn("decision frontier", scope_note(root, "전면 재설계해줘", _WRITE))

    def test_harness_wrapper_is_fail_open(self):
        # 조회 실패가 턴을 죽이면 안 된다 — 노트는 강화층이지 실행 경로가 아니다.
        self.assertEqual(work_shape_note("/nonexistent-root-for-scope", "설명해줘", {"write_expected": False}), "")


class VerdictFindingsTest(unittest.TestCase):
    def test_verdict_tool_declares_the_three_owners(self):
        actions = VERDICT_TOOL["input_schema"]["properties"]["findings"]["items"]["properties"]["action"]
        self.assertEqual(set(actions["enum"]), {"auto-fix", "ask-user", "no-op"})

    def test_absent_findings_keep_the_previous_path(self):
        self.assertEqual(_classified_findings({"verdict": "FAIL"}), [])
        self.assertEqual(_classified_findings({"verdict": "FAIL", "findings": "nope"}), [])

    def test_unclassifiable_finding_closes_to_the_human(self):
        rows = _classified_findings({"findings": [{"id": "f1", "description": "새 플래그가 확인 프롬프트를 건너뛴다"}]})
        self.assertEqual(rows[0]["action"], "ask-user")
        rows = _classified_findings({"findings": [{"id": "f2", "action": "whatever", "description": "x"}]})
        self.assertEqual(rows[0]["action"], "ask-user")

    def test_declared_owners_survive(self):
        rows = _classified_findings(
            {
                "findings": [
                    {"id": "f1", "action": "auto-fix", "description": "호출부 하나 누락", "file": "a.py:12"},
                    {"id": "f2", "action": "no-op", "description": "참고"},
                ]
            }
        )
        self.assertEqual([r["action"] for r in rows], ["auto-fix", "no-op"])
        self.assertEqual(rows[0]["file"], "a.py:12")

    def test_findings_without_a_description_are_dropped(self):
        self.assertEqual(_classified_findings({"findings": [{"id": "f1", "action": "auto-fix"}, "junk"]}), [])

    def test_quest_log_persists_findings_and_closes_unknown_actions(self):
        event = normalize(
            {
                "role": "verifier",
                "event": "verify",
                "findings": [
                    {"id": "f1", "action": "auto-fix", "description": "mechanical"},
                    {"id": "f2", "action": "made-up", "description": "contradicts the request"},
                ],
            },
            [],
            "q1",
            "s1",
        )
        self.assertEqual([f["action"] for f in event["findings"]], ["auto-fix", "ask-user"])

    def test_quest_log_omits_the_field_when_there_is_nothing_to_record(self):
        self.assertNotIn("findings", normalize({"role": "verifier", "event": "verify"}, [], "q1", "s1"))


class ExternalHostSurfaceTest(unittest.TestCase):
    """Codex·Cursor 는 `asgard skills resolve` 출력이 유일한 스킬 통로다 — 사이징도 여기로 나가야 한다."""

    def _resolve(self, agent: str, task: str, json_out: bool = False) -> str:
        import contextlib
        import io
        import os

        from asgard.commands.skills import run_skills_resolve

        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            cwd = os.getcwd()
            os.chdir(root)
            try:
                with contextlib.redirect_stdout(buffer):
                    self.assertEqual(run_skills_resolve(agent, task, json_out), 0)
            finally:
                os.chdir(cwd)
        return buffer.getvalue()

    def test_resolve_emits_the_shape_for_a_write_role(self):
        out = self._resolve("worker", "머지 충돌 해결해줘")
        self.assertIn("Work shape", out)
        self.assertIn("merge-resolution", out)

    def test_json_mode_carries_the_shape_alongside_the_skills(self):
        import json

        payload = json.loads(self._resolve("worker", "신규 엔드포인트 추가", json_out=True))
        self.assertEqual(payload["shape"]["shape"], "feature")
        self.assertIsInstance(payload["skills"], list)

    def test_gate_surfaces_get_no_advisory_sizing(self):
        # 판정 표면에 advisory 를 주입하지 않는다는 기존 규율 — 형상 노트도 예외가 아니다.
        for agent in ("verifier", "loki"):
            with self.subTest(agent=agent):
                self.assertNotIn("Work shape", self._resolve(agent, "머지 충돌 해결해줘"))

    def test_router_skill_teaches_the_shape_block(self):
        from asgard.templates.skill_router import MANAGED_ROUTER_SKILL_MD

        self.assertIn("Work shape", MANAGED_ROUTER_SKILL_MD)
        self.assertIn("expedition", MANAGED_ROUTER_SKILL_MD)


class RoleContractTest(unittest.TestCase):
    """모드 A/B(CC·Codex·Cursor)는 역할 .md 만 읽는다 — 규율이 여기 없으면 네이티브 전용이 된다."""

    def _role(self, name: str) -> str:
        return dict(ROLE_AGENTS)[name]

    def test_thinker_sizes_before_decomposing(self):
        body = self._role("asgard-thinker.md")
        self.assertIn("Size before you decompose", body)
        for shape in ("`slice`", "`feature`", "`expedition`"):
            self.assertIn(shape, body)
        self.assertIn("Bind the matched disciplines", body)

    def test_worker_does_not_re_judge_a_deterministic_match(self):
        body = self._role("asgard-worker.md")
        self.assertIn("[task-match]", body)
        self.assertIn("Work shape", body)

    def test_verifier_classifies_by_who_owns_the_decision(self):
        body = self._role("asgard-verifier.md")
        for token in ("`auto-fix`", "`ask-user`", "`no-op`", "fail closed", "<intent>"):
            self.assertIn(token, body)


if __name__ == "__main__":
    unittest.main()
