"""프로젝트 레인이 후보를 버리거나 회수에 실패했을 때 주입면이 남기는 흔적.

버린 뒤 아무 말도 안 하면 "기억할 게 없다"와 "정본을 잃어 전량 탈락했다"가 화면에서 같아진다.
여기서 잡는 것은 그 두 상태의 구별이고, 동시에 **정상일 때는 종전과 바이트가 같다**는 쪽이다 —
매 턴 들어가는 글이라 한 줄이 늘 붙으면 그 자체가 결함이다.
"""

import os
import shutil
import tempfile
import unittest
from typing import Any
from unittest import mock

from asgard import memory, memory_context, project_memory
from asgard.memory_context import project_recall_note, recall_note

PROJECT_UID = "proj-uid-drop"
BINDING_ID = "binding-drop"


class DropSilenceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-drop-silence-")
        self.root = os.path.join(self.tmp, "project")
        os.makedirs(self.root)
        self.old_home = os.environ.get("HOME")
        self.old_memory = os.environ.get(memory.MEMORY_ENV)
        os.environ["HOME"] = self.tmp
        os.environ[memory.MEMORY_ENV] = os.path.join(self.tmp, "personal-memory")
        trust = mock.patch("asgard.memory_context.is_backend_trusted", return_value=True)
        trust.start()
        self.addCleanup(trust.stop)

    def tearDown(self):
        for key, value in (("HOME", self.old_home), (memory.MEMORY_ENV, self.old_memory)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self) -> dict:
        return {"server": "http://x", "bank": "asgard", "project_uid": PROJECT_UID, "binding_id": BINDING_ID}

    def foreign_hit(self, content: str) -> dict:
        """정본 불일치로 탈락할 후보 — 자격 태그는 다 맞고 소유만 남의 프로젝트다."""
        return {
            "text": content,
            "metadata": {
                "record_id": "decision.foreign",
                "kind": "decision",
                "scope": "project",
                "status": "active",
                "confidence": "verified",
                "source": "docs/adr.md",
                "project_uid": "someone-else",
                "binding_id": "someone-else",
            },
        }

    def canonical_hit(self, content: str, record_id="decision.mine") -> dict:
        fields: dict[str, Any] = {
            "kind": "decision",
            "source": "docs/adr.md",
            "source_revision": "HEAD=verified",
            "importance": "high",
            "confidence": "verified",
            "status": "active",
        }
        record = project_memory.ProjectRecord(
            record_id=record_id, title="회수 흔적 회귀 기록", content=content, **fields
        )
        project_memory.save_canonical_record(self.root, record)
        item = project_memory.record_item(record, "asgard", project_uid=PROJECT_UID, binding_id=BINDING_ID)
        return {"text": item["content"], "metadata": item["metadata"]}

    def note(self, query: str, hits, single_lane: bool = False) -> str:
        recall = mock.patch("asgard.memory_context.server_recall", **hits)
        with (
            mock.patch("asgard.memory_context.find_config", return_value=(self.root, self.cfg())),
            recall,
        ):
            surface = project_recall_note if single_lane else recall_note
            return surface(query, start=self.root)


class TestADroppedLaneLeavesATrace(DropSilenceCase):
    def test_a_lane_that_dropped_every_candidate_says_how_many_and_why(self):
        hits = [
            self.foreign_hit("프로젝트 메모리 엔진은 Hindsight 로 운영한다는 결정이다."),
            self.foreign_hit("프로젝트 메모리 회수 예산은 3000자라는 결정이다."),
        ]
        note = self.note("프로젝트 메모리 결정", {"return_value": hits})
        self.assertIn("정본 불일치 2건", note)
        self.assertIn("asgard memory project-recall --unfiltered", note)

    def test_a_lane_with_nothing_to_consider_stays_byte_identical(self):
        self.assertEqual(self.note("프로젝트 메모리 결정", {"return_value": []}), "")

    def test_a_lane_that_loaded_a_row_does_not_explain_itself(self):
        hits = [
            self.canonical_hit("프로젝트 메모리 엔진은 Hindsight 로 운영한다는 결정이다."),
            self.foreign_hit("프로젝트 메모리 예산은 3000자라는 남의 저장소 결정이다."),
        ]
        note = self.note("프로젝트 메모리 결정", {"return_value": hits})
        self.assertIn("Hindsight", note)
        self.assertNotIn("제외", note)
        self.assertNotIn("--unfiltered", note)

    def test_a_recall_that_never_answered_leaves_the_same_kind_of_line(self):
        note = self.note("프로젝트 메모리 결정", {"side_effect": TimeoutError("read timed out")})
        self.assertIn("회수 실패", note)
        self.assertIn("asgard memory project-recall --unfiltered", note)

    def test_a_healthy_abstention_is_not_worth_a_line(self):
        """질의와 어휘가 안 겹쳐 기권한 것은 고장이 아니다 — 이것까지 알리면 거의 매 턴 한 줄이 붙는다."""
        hits = [self.canonical_hit("프로덕션 기본 배포 리전은 서울 ap-northeast-2 이다.")]
        self.assertEqual(self.note("모바일 최소 지원 운영체제 버전은?", {"return_value": hits}), "")

    def test_the_rows_only_surface_stays_rows_only(self):
        """`memory.pattern.gather_evidence` 가 이 문자열을 LLM 근거로 넣는다 — 안내문이 섞이면 기록 행세를 한다."""
        hits = [self.foreign_hit("프로젝트 메모리 엔진은 Hindsight 로 운영한다는 결정이다.")]
        note = self.note("프로젝트 메모리 결정", {"return_value": hits}, single_lane=True)
        self.assertEqual(note, "")

    def test_the_line_never_grows_into_a_paragraph(self):
        """매 턴 들어가는 글이다 — 사유가 전부 켜져도 한 줄에서 끝나야 한다."""
        full = memory_context.project_drop_note(dict.fromkeys(memory_context.DROP_REASONS, 999))
        unreached = memory_context.project_drop_note({memory_context.DROP_UNREACHED: 1})
        for line in (full, unreached):
            self.assertLessEqual(len(line), 200, line)
            self.assertNotIn("\n", line)
        self.assertEqual(memory_context.project_drop_note({}), "")


if __name__ == "__main__":
    unittest.main()
