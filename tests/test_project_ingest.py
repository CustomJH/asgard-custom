"""문서 인제스트 테스트 — 사람이 던진 문서가 규칙대로 들어가는가.

검증 축: 추출(형식별·미지원 거절·빈 문서) / 판정(요구사항 문서 → document, 결정문 → record,
사람 지정이 자동을 덮음) / 엔티티(요구사항 ID 만·규격 이름 오탐 없음·상한) /
아이템 조립(원문 보존·전략 동반·같은 파일 = 같은 document_id) / 도구 표면(승인 없이는 안 씀).
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from asgard.project_memory import ingest

REQUIREMENTS = """# 1. 검침 수집

## 1.1 검침 수집 요구사항 1

**요구사항 ID**: METER-001 · **우선순위**: 필수

### 설명
단말은 15분 주기로 유효전력량을 수집하여 서버로 전송해야 한다.

### 수용 기준
| 항목 | 기준값 | 측정 |
|---|---|---|
| 성공률 | 99.5% | 30일 |
| 지연 | 5초 | p95 |

### 관련
METER-001 은 METER-002 에 의존한다. METER-002 는 METER-001 을 참조한다.

## 1.2 검침 수집 요구사항 2

**요구사항 ID**: METER-002 · **우선순위**: 중요
METER-002 는 RS-485 물리계층 위에서 동작하며 CRC-16 으로 검증한다.
METER-002 의 재시도 상한은 3회다.
"""

DECISION = """# 모뎀 교체 결정

2026년 3월 회의에서 LTE Cat.M1 으로 교체하기로 결정했다.
CDMA 단종이 근거이며, 다중 사업자안은 기각했다.
"""


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-ingest-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, body: str) -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def test_plain_text_formats_read_directly(self):
        for name in ("spec.md", "spec.txt", "spec.rst"):
            self.assertIn("METER-001", ingest.extract_text(self._write(name, REQUIREMENTS)))

    def test_unsupported_format_is_refused_by_name(self):
        with self.assertRaises(ingest.IngestError) as caught:
            ingest.extract_text(self._write("sheet.xlsx", "x"))
        self.assertIn("지원하지 않는", str(caught.exception))

    def test_missing_file_is_refused(self):
        with self.assertRaises(ingest.IngestError):
            ingest.extract_text(os.path.join(self.tmp, "nope.md"))

    def test_empty_document_is_refused_with_ocr_hint(self):
        with self.assertRaises(ingest.IngestError) as caught:
            ingest.prepare(self._write("blank.md", "   \n\n"))
        self.assertIn("OCR", str(caught.exception))

    def test_binary_extractors_are_wrapped_into_one_error_type(self):
        path = self._write("broken.pdf", "not a pdf")
        with self.assertRaises(ingest.IngestError):
            ingest.extract_text(path)


class ClassifyTest(unittest.TestCase):
    def test_requirements_document_picks_the_document_strategy(self):
        strategy, kind, signals = ingest.classify(REQUIREMENTS, "요구사항.md")
        self.assertEqual((strategy, kind), ("document", "specification"))
        self.assertGreaterEqual(signals["requirement_ids"], 2)

    def test_decision_note_picks_the_record_strategy(self):
        strategy, kind, _ = ingest.classify(DECISION, "modem-decision.md")
        self.assertEqual((strategy, kind), ("record", "decision"))

    def test_short_decision_wins_on_content_even_without_a_telling_name(self):
        strategy, kind, _ = ingest.classify(DECISION, "note.md")
        self.assertEqual((strategy, kind), ("record", "decision"))

    def test_ambiguous_input_falls_back_to_document(self):
        # 애매하면 원문을 그대로 두는 쪽 — LLM 추출비를 무는 오판보다 되돌리기 쉽다
        strategy, _kind, _ = ingest.classify("짧은 잡기.", "memo.md")
        self.assertEqual(strategy, ingest.DEFAULT_STRATEGY)

    def test_large_body_is_a_document_even_without_requirement_ids(self):
        strategy, _kind, _ = ingest.classify("설명 문단.\n" * 2000, "unknown.md")
        self.assertEqual(strategy, "document")


class EntityTest(unittest.TestCase):
    def test_requirement_ids_are_lifted(self):
        names = [name for name, _kind in ingest.extract_entities(REQUIREMENTS)]
        self.assertIn("METER-001", names)
        self.assertIn("METER-002", names)

    def test_standard_names_are_not_requirements(self):
        # 26-07-28 실측 결함: RS-485·CRC-16 이 REQUIREMENT 로 잡혔다. 형상이 같으니
        # 라벨이나 반복 횟수로 가른다 — 규격 이름은 스치고 지나간다.
        names = [name for name, _kind in ingest.extract_entities(REQUIREMENTS)]
        self.assertNotIn("RS-485", names)
        self.assertNotIn("CRC-16", names)

    def test_every_entity_is_typed_as_requirement(self):
        self.assertTrue(all(kind == "REQUIREMENT" for _name, kind in ingest.extract_entities(REQUIREMENTS)))

    def test_entity_count_is_capped(self):
        body = "\n".join(f"**요구사항 ID**: REQ-{index:03d}" for index in range(200))
        self.assertLessEqual(len(ingest.extract_entities(body)), ingest.MAX_ENTITIES)

    def test_labelled_id_counts_even_when_mentioned_once(self):
        names = [name for name, _kind in ingest.extract_entities("**요구사항 ID**: SOLO-001\n본문뿐이다.")]
        self.assertEqual(names, ["SOLO-001"])


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-prep-")
        self.path = os.path.join(self.tmp, "요구사항.md")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(REQUIREMENTS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_explicit_strategy_overrides_the_automatic_choice(self):
        document = ingest.prepare(self.path, strategy="record")
        self.assertEqual(document.strategy, "record")
        self.assertEqual(document.signals["auto_strategy"], "document")
        self.assertTrue(document.signals["overridden"])

    def test_unknown_strategy_is_refused(self):
        with self.assertRaises(ingest.IngestError):
            ingest.prepare(self.path, strategy="whatever")

    def test_same_file_keeps_one_document_id(self):
        # 같은 문서를 다시 던지면 갈아끼워야 한다 (교정 경로) — 새 id 가 생기면 둘이 공존한다
        self.assertEqual(ingest.prepare(self.path).document_id, ingest.prepare(self.path).document_id)

    def test_plan_separates_readable_from_unreadable(self):
        bad = os.path.join(self.tmp, "sheet.xlsx")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("x")
        ready, failed = ingest.plan([self.path, bad])
        self.assertEqual([d.name for d in ready], ["요구사항.md"])
        self.assertEqual([os.path.basename(row["path"]) for row in failed], ["sheet.xlsx"])


class ItemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-item-")
        self.path = os.path.join(self.tmp, "요구사항.md")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(REQUIREMENTS)
        self.document = ingest.prepare(self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_body_is_the_original_text(self):
        item = ingest.document_item(self.document, "bank")
        self.assertIn("단말은 15분 주기로", item["content"])  # 요약하지 않는다
        self.assertIn("Content-SHA256:", item["content"])

    def test_strategy_and_entities_ride_along(self):
        item = ingest.document_item(self.document, "bank", project_uid="u", binding_id="b")
        self.assertEqual(item["strategy"], "document")
        self.assertEqual(item["update_mode"], "replace")
        self.assertEqual(item["timestamp"], "unset")  # 규격에는 발생 시각이 없다
        self.assertIn({"text": "METER-001", "type": "REQUIREMENT"}, item["entities"])
        self.assertEqual(item["metadata"]["project_uid"], "u")
        self.assertEqual(item["metadata"]["binding_id"], "b")

    def test_metadata_carries_provenance(self):
        metadata = ingest.document_item(self.document, "bank")["metadata"]
        self.assertEqual(metadata["scope"], "project")
        self.assertEqual(metadata["status"], "active")
        self.assertEqual(metadata["origin"], "ingest")
        self.assertTrue(metadata["content_hash"])


class ToolSurfaceTest(unittest.TestCase):
    """에이전트가 부르는 표면 — 승인 없이는 공유 메모리에 쓰지 않는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-tool-")
        self.path = os.path.join(self.tmp, "요구사항.md")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(REQUIREMENTS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unconnected_project_is_refused(self):
        from asgard.agent.tools import ToolError, run_ingest_document

        with mock.patch("asgard.memory_bridge.find_config", return_value=None):
            with self.assertRaises(ToolError) as caught:
                run_ingest_document(self.tmp, {"paths": [self.path]})
        self.assertIn("연결", str(caught.exception))

    def test_untrusted_backend_is_refused(self):
        from asgard.agent.tools import ToolError, run_ingest_document

        with (
            mock.patch("asgard.memory_bridge.find_config", return_value=(self.tmp, {"engine": "hindsight"})),
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=False),
        ):
            with self.assertRaises(ToolError):
                run_ingest_document(self.tmp, {"paths": [self.path]})

    def test_empty_paths_is_refused(self):
        from asgard.agent.tools import ToolError, run_ingest_document

        with self.assertRaises(ToolError):
            run_ingest_document(self.tmp, {"paths": []})

    def test_it_stages_instead_of_writing(self):
        from asgard.agent.tools import run_ingest_document

        with (
            mock.patch("asgard.memory_bridge.find_config", return_value=(self.tmp, {"engine": "hindsight"})),
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch.object(ingest, "ensure_strategies", return_value={"changed": False, "strategies": {}}),
            mock.patch.object(
                ingest,
                "stage_documents",
                return_value=[
                    {
                        "name": "요구사항.md",
                        "kind": "specification",
                        "strategy": "document",
                        "lane": ingest.LANE_GRAPH,
                        "entities": 2,
                        "chars": 500,
                        "graph_units": 1,
                        "document_id": "asgard:doc:x",
                        "approval_id": "abc123",
                    }
                ],
            ) as staged,
        ):
            out = run_ingest_document(self.tmp, {"paths": [self.path]})
        staged.assert_called_once()
        self.assertIn("승인 대기", out)
        self.assertIn("project-approve abc123", out)

    def test_tool_is_registered_as_inspect_not_mutate(self):
        # 승인 대기 제안이므로 쓰기 권한이 필요 없다 — 권한이 넓으면 게이트가 헐거워진다
        import asgard.agent.tools as tools_module
        from asgard.agent import tool_kernel

        self.assertEqual(tools_module.INGEST_DOCUMENT_TOOL["name"], "ingest_document")
        self.assertTrue(callable(tool_kernel._ingest_document))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
