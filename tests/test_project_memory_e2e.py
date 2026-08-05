"""프로젝트 메모리 E2E — 실 HTTP 서버를 세워 기록·회수·회고·진화를 전 구간 검증한다.

목킹이 아니라 진짜 소켓이다. HindsightBackend의 urllib 경로·URL 조립·바운디드 읽기·
바인딩 왕복이 전부 실행된다. 서버는 두 모습으로 세운다.

  LLM 있는 서버  — reflect가 서버에서 합성된다 (평시)
  LLM 없는 서버  — reflect가 실패한다. 그때 이쪽 provider가 Git 정본을 근거로 답해야 한다
                   (서버 사정이 지식의 사정이 되지 않는다는 계약)

진화 패스는 "출처 파일이 사라진 record"를 코드가 재확인한 뒤에만 승인 대기로 올린다 —
LLM이 뭐라 하든 파일이 살아 있으면 기각된다.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from asgard import memory_bridge, memory_context
from asgard.project_memory import evolve as evolve_mod
from asgard.project_memory import reflect as reflect_mod
from asgard.project_memory.canonical import save_canonical_record
from asgard.project_memory.records import ProjectRecord
from asgard.project_memory_backends import HindsightBackend, get_backend


def hindsight_backend(cfg: dict) -> HindsightBackend:
    """스키마 판독은 Hindsight 고유 계약이라 프로토콜 타입으로는 부를 수 없다.
    구현체를 실제로 받았는지 확인하고 넘긴다 — 못 받았으면 그 자체가 결함이다."""
    backend = get_backend(cfg)
    assert isinstance(backend, HindsightBackend), f"expected HindsightBackend, got {type(backend).__name__}"
    return backend


class FakeServer(ThreadingHTTPServer):
    """가짜 Hindsight의 상태를 들고 있는 서버 — 핸들러는 요청마다 새로 만들어지므로
    뱅크·호출 기록은 서버가 소유해야 한다. 그 소유 관계를 타입으로도 적어 둔다."""

    documents: dict[str, dict]
    openapi: dict
    retain_calls: list
    llm_enabled: bool


class FakeHindsight(BaseHTTPRequestHandler):
    """뱅크 하나를 메모리에 들고 있는 최소 Hindsight. 상태는 서버 인스턴스가 소유한다."""

    protocol_version = "HTTP/1.1"
    server: FakeServer  # 위 소유 관계 — 좁히지 않으면 상태 접근이 전부 미지의 속성이 된다

    def log_message(self, format: str, *args: object) -> None:  # pragma: no cover - 테스트 출력 오염 방지
        return

    def _send(self, code: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 계약
        store = self.server.documents
        if self.path == "/openapi.json":
            return self._send(200, self.server.openapi)
        if self.path.endswith("/documents?limit=1&offset=0"):
            items = [{"id": document_id} for document_id in list(store)[:1]]
            return self._send(200, {"items": items, "limit": 1, "offset": 0, "total": len(store)})
        if self.path.endswith("/stats"):
            return self._send(200, {"total_documents": len(store)})
        if "/documents/" in self.path:
            from urllib.parse import unquote

            document_id = unquote(self.path.rsplit("/documents/", 1)[1])
            row = store.get(document_id)
            if row is None:
                return self._send(404, {"error": "not found"})
            return self._send(200, {"original_text": row["content"], "metadata": row["metadata"]})
        return self._send(404, {"error": "unknown route"})

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 계약
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode() or "{}")
        store = self.server.documents
        if self.path.endswith("/memories"):
            self.server.retain_calls.append(payload)
            for item in payload.get("items") or []:
                store[str(item.get("document_id"))] = {
                    "content": str(item.get("content") or ""),
                    "metadata": dict(item.get("metadata") or {}),
                }
            return self._send(200, {"success": True})
        if self.path.endswith("/memories/recall"):
            query = str(payload.get("query") or "").lower()
            terms = {word for word in query.split() if len(word) >= 2}
            results = [
                {
                    "document_id": document_id,
                    "text": row["content"],
                    "metadata": row["metadata"],
                    "score": sum(1 for term in terms if term in row["content"].lower()),
                }
                for document_id, row in store.items()
                if any(term in row["content"].lower() for term in terms)
            ]
            results.sort(key=lambda row: -row["score"])
            return self._send(200, {"results": results, "chunks": {}})
        if self.path.endswith("/reflect"):
            if not self.server.llm_enabled:
                # LLM 없는 배포의 실제 모습 — 색인은 살아 있고 합성만 못 한다
                return self._send(503, {"error": "no reasoning model configured"})
            return self._send(200, {"text": "서버가 합성한 답", "based_on": {"memories": list(store)[:3]}})
        return self._send(404, {"error": "unknown route"})


class ProjectMemoryE2EBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-pm-e2e-")
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp
        self.root = os.path.join(self.tmp, "project")
        os.makedirs(self.root, exist_ok=True)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.server = FakeServer(("127.0.0.1", 0), FakeHindsight)
        self.server.documents = {}
        self.server.llm_enabled = True
        self.server.retain_calls = []
        # 기본 스키마 — timestamp를 받는 서버
        self.server.openapi = {
            "openapi": "3.1.0",
            "components": {
                "schemas": {
                    "RetainItem": {
                        "type": "object",
                        "properties": {
                            "content": {},
                            "context": {},
                            "document_id": {},
                            "update_mode": {},
                            "tags": {},
                            "metadata": {},
                            "timestamp": {},
                            "entities": {},
                            "strategy": {},
                            "observation_scopes": {},
                        },
                    }
                }
            },
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cfg = {
            "engine": "hindsight",
            "endpoint": self.endpoint,
            "project_id": "e2e-bank",
            "project_uid": "11111111-1111-4111-8111-111111111111",
            "binding_id": "22222222-2222-4222-8222-222222222222",
            "timeout": 5,
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self._home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_source(self, relative: str, text: str) -> str:
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return relative

    def _record(self, record_id: str, title: str, content: str, source: str) -> ProjectRecord:
        record = ProjectRecord(
            record_id=record_id,
            kind="component",
            title=title,
            content=content,
            source=source,
            source_revision="rev-1",
            importance="high",
            confidence="verified",
        )
        save_canonical_record(self.root, record)
        return record


class RecordAndRecallTest(ProjectMemoryE2EBase):
    def test_binding_write_and_read_round_trip(self):
        from asgard.project_memory_backends import ProjectMemoryBinding

        backend = get_backend(self.cfg)
        try:
            self.assertEqual(backend.readiness().status, "ready")
            self.assertIsNone(backend.read_binding())
            marker = ProjectMemoryBinding(
                project_uid=str(self.cfg["project_uid"]),
                binding_id=str(self.cfg["binding_id"]),
                project_id=str(self.cfg["project_id"]),
            )
            self.assertTrue(backend.write_binding(marker).success)
            self.assertEqual(backend.read_binding(), marker)
            self.assertEqual(backend.namespace_document_count(), 1)
        finally:
            backend.close()

    def test_synced_record_comes_back_from_recall(self):
        from asgard.project_memory import scan_project, sync_artifacts

        self._write_source(
            "README.md",
            "# Routing service\n\nresolve_route is the single entry point for route resolution.\n",
        )
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        candidates = scan_project(self.root, changed_paths=[])
        self.assertEqual([row.path for row in candidates], ["README.md"])
        with (
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch("asgard.memory_bridge.verify_backend_binding"),
        ):
            plan = memory_bridge.backend_target(self.cfg)
            self.assertEqual(plan["project_id"], "e2e-bank")
            result = sync_artifacts(self.root, self.cfg, candidates, force=True, expected_plan_id=None)
        self.assertTrue(result.get("success"), result.get("error"))
        self.assertTrue(self.server.documents, "the backend should hold the projected artifact")
        backend = get_backend(self.cfg)
        try:
            hits = backend.recall("resolve_route", max_results=5)
        finally:
            backend.close()
        self.assertTrue(hits)
        self.assertIn("resolve_route", hits[0].text)


class ReflectFallbackTest(ProjectMemoryE2EBase):
    def setUp(self):
        super().setUp()
        self._write_source("src/router.py", "def resolve_route(request):\n    return request\n")
        self._record(
            "component.router",
            "라우터 해석 진입점",
            "resolve_route 는 요청을 받아 라우트를 해석하는 이 서비스의 단일 진입점이다.",
            "src/router.py",
        )

    def test_backend_llm_answers_when_the_server_has_one(self):
        backend = get_backend(self.cfg)
        try:
            with mock.patch.object(reflect_mod, "_complete", side_effect=AssertionError("local must not run")):
                output = reflect_mod.reflect(self.root, backend, "라우터 진입점은 무엇인가", cfg=self.cfg)
        finally:
            backend.close()
        self.assertEqual(output["source"], "backend")
        self.assertEqual(output["text"], "서버가 합성한 답")

    def test_local_provider_answers_when_the_server_has_no_llm(self):
        self.server.llm_enabled = False
        backend = get_backend(self.cfg)
        try:
            with mock.patch.object(reflect_mod, "_complete", return_value="정본 근거로 합성한 답") as call:
                output = reflect_mod.reflect(self.root, backend, "라우터 해석 진입점", cfg=self.cfg)
        finally:
            backend.close()
        self.assertEqual(output["source"], "local")
        self.assertEqual(output["text"], "정본 근거로 합성한 답")
        self.assertIn("backend fallback", output["detail"])
        # 근거는 Git 정본에서 온다 — 서버가 아무것도 못 해도 남아 있는 쪽
        payload = json.loads(call.call_args[0][2])
        self.assertEqual(payload["evidence"][0]["origin"], "canonical")
        self.assertEqual(payload["evidence"][0]["id"], "component.router")

    def test_backend_mode_refuses_to_answer_instead_of_falling_back(self):
        self.server.llm_enabled = False
        backend = get_backend(self.cfg)
        try:
            with self.assertRaises(reflect_mod.ReflectUnavailable):
                reflect_mod.reflect(self.root, backend, "라우터", cfg={**self.cfg, "reflect": "backend"})
        finally:
            backend.close()

    def test_local_mode_never_asks_the_server(self):
        backend = get_backend(self.cfg)
        try:
            with mock.patch.object(reflect_mod, "_complete", return_value="로컬 전용 답"):
                output = reflect_mod.reflect(self.root, backend, "라우터 해석", cfg={**self.cfg, "reflect": "local"})
        finally:
            backend.close()
        self.assertEqual(output["source"], "local")
        self.assertNotIn("backend fallback", output["detail"])

    def test_no_matching_evidence_is_reported_not_invented(self):
        self.server.llm_enabled = False
        backend = get_backend(self.cfg)
        try:
            with mock.patch.object(reflect_mod, "_complete", side_effect=AssertionError("must not synthesize")):
                output = reflect_mod.reflect(self.root, backend, "완전히 무관한 질문 zzzz", cfg=self.cfg)
        finally:
            backend.close()
        self.assertEqual(output["text"], "")
        self.assertIn("no canonical record", output["detail"])


class EvolveTest(ProjectMemoryE2EBase):
    def setUp(self):
        super().setUp()
        self._write_source("src/router.py", "def resolve_route(request):\n    return request\n")
        self._record(
            "component.router",
            "라우터 해석 진입점",
            "resolve_route 는 요청을 받아 라우트를 해석하는 단일 진입점이다.",
            "src/router.py",
        )
        self._record(
            "component.legacy",
            "폐기된 라우터",
            "legacy_route 는 예전 라우팅 경로를 담당하던 진입점이다.",
            "src/legacy.py",
        )

    def test_missing_source_is_a_deterministic_signal(self):
        sig = evolve_mod.signals(self.root)
        self.assertEqual(sig["missing_sources"], ["component.legacy"])
        self.assertEqual(sig["active"], 2)

    def test_an_adjacent_prefix_path_is_outside_the_repository(self):
        """`/repo` 가 `/repo-notes` 를 자기 안이라고 말하면 안 된다 — 봉쇄는 글자가 아니라 성분이다.

        접두사로 세면 `../project-notes/…` 가 저장소를 벗어나 놓고 존재 판정을 받는다. 그리고
        저장소 밖 파일은 대개 없으므로 그 record 는 "source 가 사라졌다"로 읽혀 폐기 후보로
        올라간다 — 못 보는 자리를 봤다고 말하는 셈이다."""
        neighbour = os.path.join(os.path.dirname(self.root), os.path.basename(self.root) + "-notes")
        os.makedirs(neighbour, exist_ok=True)
        self.assertFalse(evolve_mod._missing_source(self.root, "../project-notes/absent.md"))
        self.assertFalse(evolve_mod._missing_source(self.root, "../project-notes/"))
        # 저장소 안쪽 판정은 그대로다
        self.assertFalse(evolve_mod._missing_source(self.root, "src/router.py"))
        self.assertTrue(evolve_mod._missing_source(self.root, "src/legacy.py"))

    def test_retire_is_rechecked_against_the_repository(self):
        sig = evolve_mod.signals(self.root)
        accepted, dropped = evolve_mod.validate_ops(
            [
                {"op": "retire", "record_id": "component.legacy", "why": "파일이 사라졌다"},
                {"op": "retire", "record_id": "component.router", "why": "낡았다고 생각한다"},
            ],
            self.root,
            sig,
        )
        self.assertEqual([op["record_id"] for op in accepted], ["component.legacy"])
        self.assertIn("source still exists", dropped[0]["reason"])

    def test_insight_must_cite_records_that_exist(self):
        sig = evolve_mod.signals(self.root)
        accepted, dropped = evolve_mod.validate_ops(
            [
                {
                    "op": "insight",
                    "title": "라우팅은 진입점 하나로 모인다",
                    "text": "두 record 모두 라우팅 진입점을 단일 함수로 서술한다 — 경로가 하나라는 계약이다.",
                    "sources": ["component.router", "component.legacy"],
                },
                {
                    "op": "insight",
                    "title": "존재하지 않는 근거",
                    "text": "이 통찰은 있지도 않은 record 를 근거로 든다는 점에서 검증을 통과할 수 없다.",
                    "sources": ["component.ghost", "component.router"],
                },
            ],
            self.root,
            sig,
        )
        self.assertEqual(len(accepted), 1)
        self.assertIn("do not exist", dropped[0]["reason"])

    def test_apply_stages_for_approval_and_never_writes_directly(self):
        sig = evolve_mod.signals(self.root)
        accepted, _ = evolve_mod.validate_ops(
            [{"op": "retire", "record_id": "component.legacy", "why": "파일 소실"}], self.root, sig
        )
        plan = {"ops": accepted, "dropped": [], "signals": sig}
        with (
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch("asgard.memory_bridge.verify_backend_binding"),
        ):
            result = evolve_mod.apply_evolve(self.root, self.cfg, plan)
        self.assertEqual(len(result["staged"]), 1, result["failed"])
        self.assertTrue(result["staged"][0]["approval_id"])
        # 승인 전에는 backend도 정본도 건드리지 않는다
        self.assertEqual(self.server.documents, {})
        from asgard.project_memory.canonical import load_canonical_records

        statuses = {record.record_id: record.status for record, _p, _d in load_canonical_records(self.root)}
        self.assertEqual(statuses["component.legacy"], "active")

    def test_contradiction_is_report_only(self):
        sig = evolve_mod.signals(self.root)
        accepted, _ = evolve_mod.validate_ops(
            [{"op": "contradiction", "a": "component.router", "b": "component.legacy", "why": "둘 다 단일 진입점"}],
            self.root,
            sig,
        )
        result = evolve_mod.apply_evolve(self.root, self.cfg, {"ops": accepted, "dropped": [], "signals": sig})
        self.assertEqual(result["staged"], [])
        self.assertEqual(len(result["reported"]), 1)

    def test_plan_needs_no_llm_when_there_is_nothing_to_review(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty, exist_ok=True)
        with mock.patch.object(evolve_mod, "_complete", side_effect=AssertionError("must not call the LLM")):
            plan = evolve_mod.plan_evolve(empty)
        self.assertEqual(plan["ops"], [])


class EvolveWakeTest(ProjectMemoryE2EBase):
    """자율 — 이 패스에는 26-08-06 까지 부르는 손이 없었다 (evolve_note 는 호출자가 0이었다)."""

    def setUp(self):
        super().setUp()
        from asgard.settings import save_project

        save_project(self.root, "project_memory", dict(self.cfg))

    def test_wake_spawns_the_pass_once_and_then_waits_out_the_interval(self):
        with mock.patch("asgard.memory.norn.spawn_pass", return_value=True) as spawn:
            first = evolve_mod.wake(self.root)
            second = evolve_mod.wake(self.root)
        self.assertIn("프로젝트 메모리 진화", first or "")
        self.assertIsNone(second)  # 간격 안 — 매 턴 다시 띄우지 않는다
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(spawn.call_args.args[1:], ("memory", "project-evolve", "--apply"))

    def test_wake_is_silent_where_project_memory_is_not_connected(self):
        """안 붙인 사람에게 2차 진화는 존재하지 않는 기능이다 — 상기시키는 줄은 소음이다."""
        loose = os.path.join(self.tmp, "unconnected")
        os.makedirs(loose, exist_ok=True)
        with mock.patch("asgard.memory.norn.spawn_pass", return_value=True) as spawn:
            self.assertIsNone(evolve_mod.wake(loose))
        self.assertEqual(spawn.call_count, 0)

    def test_wake_never_pays_for_the_llm_itself(self):
        """due 판정은 상태 파일 하나다 — 신호 수집도 LLM 왕복도 자식 몫이다."""
        with (
            mock.patch.object(evolve_mod, "signals", side_effect=AssertionError("wake 가 카탈로그를 훑었다")),
            mock.patch.object(evolve_mod, "_complete", side_effect=AssertionError("wake 가 LLM 을 불렀다")),
            mock.patch("asgard.memory.norn.spawn_pass", return_value=True),
        ):
            self.assertIsNotNone(evolve_mod.wake(self.root))

    def test_the_switch_turns_it_off(self):
        with (
            mock.patch.object(evolve_mod, "auto_enabled", return_value=False),
            mock.patch("asgard.memory.norn.spawn_pass", return_value=True) as spawn,
        ):
            self.assertIsNone(evolve_mod.wake(self.root))
        self.assertEqual(spawn.call_count, 0)


class InventoryCoverageTest(ProjectMemoryE2EBase):
    """전수 등록 — 점수 미달 파일도 backend에서 찾을 수 있어야 한다.

    26-07-28 실측 배경: 이 저장소에서 등록 대상이 4994 중 217개(4.3%) 뿐이었고 repl.py·
    session.py 같은 핵심 소스가 통째로 빠져 있었다. digest 계층은 본문 대신 머리글만 보내
    비용을 파일 수에 비례시키지 않으면서 "무엇이 있는지"를 회수 가능하게 만든다."""

    def _tree(self):
        # 하나는 점수를 넘고(README=55), 하나는 못 넘는다(평범한 소스)
        self._write_source("README.md", "# Service\n\nThe routing service entry point.\n")
        self._write_source(
            "src/widget_helper.py",
            '"""Widget helper — formats widget rows for the dashboard."""\n\ndef format_widget(row):\n    return row\n',
        )
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)

    def test_low_score_file_is_invisible_without_inventory(self):
        from asgard.project_memory import scan_project

        self._tree()
        paths = [c.path for c in scan_project(self.root, changed_paths=[])]
        self.assertIn("README.md", paths)
        self.assertNotIn("src/widget_helper.py", paths)  # 이것이 고치려는 격차다

    def test_inventory_registers_it_as_digest_and_recall_finds_it(self):
        from asgard.project_memory import scan_project, sync_artifacts

        self._tree()
        candidates = scan_project(self.root, changed_paths=[], inventory=True)
        tiers = {c.path: c.tier for c in candidates}
        self.assertEqual(tiers.get("README.md"), "full")
        self.assertEqual(tiers.get("src/widget_helper.py"), "digest")

        with (
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch("asgard.memory_bridge.verify_backend_binding"),
        ):
            result = sync_artifacts(self.root, self.cfg, candidates, force=True, expected_plan_id=None)
        self.assertTrue(result.get("success"), result.get("error"))

        backend = get_backend(self.cfg)
        try:
            hits = backend.recall("widget_helper", max_results=5)
        finally:
            backend.close()
        self.assertTrue(hits, "digest 계층이 회수되지 않으면 전수 등록의 의미가 없다")
        self.assertIn("src/widget_helper.py", hits[0].text)

    def test_digest_carries_the_header_not_the_body(self):
        from asgard.project_memory import artifact_item, scan_project

        self._tree()
        by_path = {c.path: c for c in scan_project(self.root, changed_paths=[], inventory=True)}
        digest = artifact_item(by_path["src/widget_helper.py"], "e2e-bank", "rev-1")
        self.assertIn("Path: src/widget_helper.py", digest["content"])
        self.assertIn("Widget helper", digest["content"])  # 요약은 넣는다
        self.assertNotIn("def format_widget", digest["content"])  # 본문은 안 넣는다
        self.assertEqual(digest["metadata"]["tier"], "digest")
        # 계층과 무관하게 결정론 검증의 근거는 실제 파일이다
        self.assertEqual(digest["metadata"]["source"], "src/widget_helper.py")
        self.assertTrue(digest["metadata"]["content_hash"])

    def test_digest_passes_the_same_trust_gate_as_full(self):
        from asgard.memory_context import _eligible_for_automatic_context
        from asgard.project_memory import artifact_item, scan_project, sync_artifacts

        self._tree()
        candidates = scan_project(self.root, changed_paths=[], inventory=True)
        with (
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch("asgard.memory_bridge.verify_backend_binding"),
        ):
            sync_artifacts(self.root, self.cfg, candidates, force=True, expected_plan_id=None)
        by_path = {c.path: c for c in candidates}
        # sync가 만드는 것과 같은 item 이어야 한다 — 소유권 신원이 빠지면 게이트가 (정당하게) 막는다
        item = artifact_item(
            by_path["src/widget_helper.py"],
            "e2e-bank",
            "rev-1",
            project_uid=str(self.cfg["project_uid"]),
            binding_id=str(self.cfg["binding_id"]),
        )
        self.assertTrue(
            _eligible_for_automatic_context(self.root, dict(item["metadata"]), self.cfg),
            "digest 도 신뢰 게이트를 통과해야 자동 주입 경로에 닿는다",
        )
        # 신원이 없으면 계층과 무관하게 막힌다 (게이트가 살아 있다는 반대 증거)
        anonymous = artifact_item(by_path["src/widget_helper.py"], "e2e-bank", "rev-1")
        self.assertFalse(_eligible_for_automatic_context(self.root, dict(anonymous["metadata"]), self.cfg))


class RetainCapabilityTest(ProjectMemoryE2EBase):
    """서버 스키마가 정본 — 문서가 아니라 /openapi.json이 무엇을 보낼지 정한다.

    26-07-28 조사: Hindsight 문서 두 곳이 어긋난다(SDK 쪽은 entities·observation_scopes를
    retain 인자로 적고 HTTP 레퍼런스는 없다고 한다). 버전을 추측하는 대신 스키마를 읽는다."""

    def _payload(self, *, timeless: bool):
        from asgard.project_memory_backends import ProjectMemoryRecord

        return ProjectMemoryRecord(
            record_id="asgard:artifact:probe",
            text="[ProjectArtifact:component]\nPath: src/x.py\n",
            metadata={"origin": "deterministic"},
            tags=("project:e2e-bank",),
            context="asgard project artifact",
            timeless=timeless,
        )

    def test_schema_is_read_from_the_server(self):
        backend = hindsight_backend(self.cfg)
        try:
            self.assertIn("timestamp", backend.retain_fields())
            self.assertIn("content", backend.retain_fields())
        finally:
            backend.close()

    def test_timeless_artifact_is_sent_as_unset_when_supported(self):
        backend = get_backend(self.cfg)
        try:
            self.assertTrue(backend.retain([self._payload(timeless=True)]).success)
        finally:
            backend.close()
        item = self.server.retain_calls[-1]["items"][0]
        self.assertEqual(item.get("timestamp"), "unset")

    def test_conversation_turn_keeps_its_real_time(self):
        backend = get_backend(self.cfg)
        try:
            backend.retain([self._payload(timeless=False)])
        finally:
            backend.close()
        self.assertNotIn("timestamp", self.server.retain_calls[-1]["items"][0])

    def test_bridge_preserves_hindsight_learning_fields_end_to_end(self):
        from asgard import memory_bridge

        item = {
            "content": "[ProjectRecord:decision]\nRecord: decision.memory\n\nHindsight를 프로젝트 기억으로 쓴다.",
            "context": "asgard project decision",
            "document_id": "asgard:record:decision-memory",
            "update_mode": "replace",
            "strategy": "record",
            "timestamp": "unset",
            "observation_scopes": "shared",
            "entities": [{"text": "Hindsight", "type": "SYSTEM"}],
            "tags": ["project:e2e-bank", "kind:decision"],
            "metadata": {
                "scope": "project",
                "kind": "decision",
                "project_uid": self.cfg["project_uid"],
                "binding_id": self.cfg["binding_id"],
            },
        }
        with (
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch("asgard.memory_bridge.verify_backend_binding"),
        ):
            result = memory_bridge.server_retain_items(self.cfg, [item])

        self.assertTrue(result["success"])
        sent = self.server.retain_calls[-1]["items"][0]
        self.assertEqual(sent["strategy"], "record")
        self.assertEqual(sent["timestamp"], "unset")
        self.assertEqual(sent["observation_scopes"], "shared")
        self.assertEqual(sent["entities"], [{"text": "Hindsight", "type": "SYSTEM"}])

    def test_unknown_field_is_not_sent_to_an_older_server(self):
        # timestamp를 모르는 서버 — 스키마에 없으면 보내지 않는다 (400을 만들지 않는다)
        self.server.openapi["components"]["schemas"]["RetainItem"]["properties"].pop("timestamp")
        backend = hindsight_backend(self.cfg)
        try:
            self.assertNotIn("timestamp", backend.retain_fields())
            backend.retain([self._payload(timeless=True)])
        finally:
            backend.close()
        self.assertNotIn("timestamp", self.server.retain_calls[-1]["items"][0])

    def test_unreadable_schema_falls_back_to_base_fields(self):
        self.server.openapi = {"openapi": "3.1.0"}  # components 없음
        backend = hindsight_backend(self.cfg)
        try:
            fields = backend.retain_fields()
        finally:
            backend.close()
        self.assertNotIn("timestamp", fields)
        self.assertIn("content", fields)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class EvolveRelateTest(EvolveTest):
    """relate — 이미 성립하던 관계를 적어 두는 연산. 관계 어휘는 정본(records.RELATIONS)이 정한다."""

    def test_a_typed_relation_between_two_active_records_is_accepted(self):
        sig = evolve_mod.signals(self.root)

        accepted, _ = evolve_mod.validate_ops(
            [
                {
                    "op": "relate",
                    "a": "component.router",
                    "b": "component.legacy",
                    "relation": "supersedes",
                    "why": "새 진입점이 옛 경로를 대체한다",
                }
            ],
            self.root,
            sig,
        )

        self.assertEqual([(op["a"], op["relation"]) for op in accepted], [("component.router", "supersedes")])

    def test_an_invented_relation_name_is_refused(self):
        sig = evolve_mod.signals(self.root)

        accepted, dropped = evolve_mod.validate_ops(
            [{"op": "relate", "a": "component.router", "b": "component.legacy", "relation": "derived_from"}],
            self.root,
            sig,
        )

        self.assertEqual(accepted, [])
        self.assertIn("unknown relation", dropped[0]["reason"])

    def test_applying_a_relation_never_truncates_the_record_body(self):
        sig = evolve_mod.signals(self.root)
        accepted, _ = evolve_mod.validate_ops(
            [{"op": "relate", "a": "component.router", "b": "component.legacy", "relation": "supersedes"}],
            self.root,
            sig,
        )

        record = evolve_mod._relate_record(self.root, accepted[0]["a"], accepted[0]["relation"], accepted[0]["b"])

        original = next(
            r for r, _p, _d in evolve_mod.load_canonical_records(self.root) if r.record_id == "component.router"
        )
        self.assertEqual(record.content, original.content)  # 덧붙이는 연산이 지우는 연산이 되면 안 된다
        self.assertIn({"type": "supersedes", "target": "component.legacy"}, list(record.relations))


class RelationExpansionTest(ProjectMemoryE2EBase):
    """2차 회수의 관계 확장 — backend는 말이 닮은 것을 찾고, 관계는 말이 안 닮은 이웃을 데려온다."""

    def setUp(self):
        super().setUp()
        from asgard.project_memory import ProjectRecord, save_canonical_record

        for record in (
            ProjectRecord(
                "policy.retry",
                "policy",
                "재시도 정책",
                "외부 호출은 지수 백오프로 3회까지 재시도한다.",
                "docs/retry.md",
                "r1",
                relations=({"type": "dependsOn", "target": "contract.ratelimit"},),
            ),
            ProjectRecord(
                "contract.ratelimit",
                "contract",
                "레이트리밋 계약",
                "공급자는 분당 40회를 넘기면 429 를 돌려준다.",
                "docs/rate.md",
                "r1",
            ),
            ProjectRecord(
                "component.unrelated",
                "component",
                "로고 렌더러",
                "로고 렌더러는 SVG 를 인라인으로 그리고 외부 요청을 하지 않는다.",
                "src/logo.py",
                "r1",
            ),
        ):
            save_canonical_record(self.root, record)

    def test_an_outgoing_relation_brings_the_neighbour_with_its_type(self):
        found = memory_context._relation_neighbors(self.root, {"policy.retry"})

        self.assertEqual([rid for rid, _edge, _text in found], ["contract.ratelimit"])
        self.assertIn("dependsOn", found[0][1])

    def test_the_walk_is_bidirectional_because_being_depended_on_is_also_a_fact(self):
        found = memory_context._relation_neighbors(self.root, {"contract.ratelimit"})

        self.assertEqual([rid for rid, _edge, _text in found], ["policy.retry"])
        self.assertIn("⁻", found[0][1])  # 들어오는 관계임이 표기에 남는다

    def test_an_unrelated_record_pulls_nothing(self):
        self.assertEqual(memory_context._relation_neighbors(self.root, {"component.unrelated"}), [])

    def test_the_seed_never_returns_as_its_own_neighbour(self):
        found = memory_context._relation_neighbors(self.root, {"policy.retry", "contract.ratelimit"})

        self.assertEqual(found, [])  # 둘 다 이미 적중했으면 새로 딸려올 것이 없다

    def test_expansion_is_capped(self):
        from asgard.project_memory import ProjectRecord, save_canonical_record

        for index in range(6):
            save_canonical_record(
                self.root,
                ProjectRecord(
                    f"component.leaf{index}",
                    "component",
                    f"잎 컴포넌트 {index}",
                    f"잎 컴포넌트 {index} 는 재시도 정책을 그대로 따르며 자체 백오프를 두지 않는다.",
                    f"src/l{index}.py",
                    "r1",
                    relations=({"type": "dependsOn", "target": "policy.retry"},),
                ),
            )

        found = memory_context._relation_neighbors(self.root, {"policy.retry"})

        self.assertLessEqual(len(found), memory_context.RELATION_EXPANSION_CAP)
