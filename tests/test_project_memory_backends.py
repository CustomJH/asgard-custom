"""선택형 프로젝트 메모리 backend 계약과 Hindsight 호환성."""

import json
import os
import tempfile
import unittest
from unittest import mock

from asgard import memory_bridge
from asgard.project_memory_backends import (
    BackendCapabilities,
    BackendReadiness,
    BackendWriteResult,
    HindsightBackend,
    ProjectMemoryHit,
    ProjectMemoryBinding,
    ProjectMemoryRecord,
    get_backend,
    register_backend,
)


class FakeBackend:
    engine = "fake"
    api_version = 2
    bindings = {}

    def __init__(self, settings):
        self.project_id = settings.project_id

    def capabilities(self):
        return BackendCapabilities(
            semantic_search=True,
            metadata_roundtrip=True,
            namespace_isolation=True,
            stable_replace=True,
            ownership_binding=True,
        )

    def readiness(self):
        return BackendReadiness("ready", self.engine, self.project_id)

    def recall(self, query, max_results=8):
        return []

    def retain(self, items):
        return BackendWriteResult(True, accepted_ids=tuple(item.record_id for item in items))

    def read_binding(self):
        return type(self).bindings.get(self.project_id) or ProjectMemoryBinding(
            project_uid="11111111-1111-4111-8111-111111111111",
            binding_id="22222222-2222-4222-8222-222222222222",
            project_id=self.project_id,
        )

    def write_binding(self, binding):
        type(self).bindings[self.project_id] = binding
        return BackendWriteResult(True, accepted_ids=("asgard:project-binding:v1",))

    def namespace_document_count(self):
        return 0

    def close(self):
        return None


class TestBackendSelection(unittest.TestCase):
    def test_legacy_hindsight_config_selects_builtin_backend(self):
        backend = get_backend({"server": "http://memory:8888", "bank": "demo", "timeout": 7})

        self.assertIsInstance(backend, HindsightBackend)
        assert isinstance(backend, HindsightBackend)
        self.assertEqual(backend.engine, "hindsight")
        self.assertEqual(backend.project_id, "demo")
        self.assertEqual(backend.endpoint, "http://memory:8888")
        self.assertEqual(backend.timeout, 7)

    def test_project_id_is_required_for_every_backend(self):
        with self.assertRaisesRegex(ValueError, "project_id"):
            get_backend({"engine": "hindsight", "endpoint": "http://memory:8888"})

    def test_conflicting_legacy_and_canonical_keys_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "conflicting"):
            get_backend(
                {
                    "engine": "hindsight",
                    "endpoint": "http://new",
                    "project_id": "new-project",
                    "server": "http://legacy",
                    "bank": "legacy-project",
                }
            )

    def test_invalid_backend_settings_fail_closed(self):
        for config, message in (
            ({"engine": "../plugin", "project_id": "demo"}, "engine"),
            ({"engine": "hindsight", "endpoint": "http://memory", "project_id": "demo", "timeout": 0}, "timeout"),
            (
                {"engine": "hindsight", "endpoint": "http://memory", "project_id": "demo", "options": ["bad"]},
                "options",
            ),
        ):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, message):
                get_backend(config)

    def test_registered_backend_is_selected_from_canonical_config(self):
        captured = []

        register_backend("fake", lambda settings: captured.append(settings) or FakeBackend(settings), replace=True)

        backend = get_backend(
            {
                "engine": "fake",
                "project_id": "asgard-project",
                "endpoint": "https://memory.example",
                "options": {"collection": "decisions"},
            }
        )

        self.assertEqual(backend.engine, "fake")
        self.assertEqual(backend.project_id, "asgard-project")
        self.assertEqual(captured[0].endpoint, "https://memory.example")
        self.assertEqual(captured[0].options, {"collection": "decisions"})

    def test_installed_entry_point_backend_loads_by_engine_name(self):
        class CogneeBackend(FakeBackend):
            engine = "cognee"

        class EntryPoint:
            name = "cognee"

            @staticmethod
            def load():
                return CogneeBackend

        with mock.patch.dict(os.environ, {"ASGARD_PROJECT_MEMORY_PLUGINS": "cognee"}), mock.patch(
            "asgard.project_memory_backends.importlib.metadata.entry_points", return_value=[EntryPoint()]
        ):
            backend = get_backend({"engine": "cognee", "project_id": "demo", "endpoint": "http://cognee"})

        self.assertEqual(backend.engine, "cognee")
        self.assertEqual(backend.project_id, "demo")

    def test_repo_config_cannot_load_untrusted_installed_plugin(self):
        class EntryPoint:
            name = "untrusted"

            @staticmethod
            def load():
                raise AssertionError("untrusted plugin must not execute")

        with mock.patch.dict(os.environ, {"ASGARD_PROJECT_MEMORY_PLUGINS": ""}), mock.patch(
            "asgard.project_memory_backends.importlib.metadata.entry_points", return_value=[EntryPoint()]
        ), self.assertRaisesRegex(ValueError, "not trusted"):
            get_backend({"engine": "untrusted", "project_id": "demo"})

    def test_malformed_registered_backend_is_rejected_at_creation(self):
        class BrokenBackend:
            engine = "broken"

            def __init__(self, settings):
                self.project_id = settings.project_id

        register_backend("broken", BrokenBackend, replace=True)

        with self.assertRaisesRegex(TypeError, "ProjectMemoryBackend"):
            get_backend({"engine": "broken", "project_id": "demo"})

    def test_protocol_rejection_best_effort_closes_constructed_adapter(self):
        closed = []

        class AlmostBackend:
            engine = "almost"
            api_version = 2
            project_id = "demo"

            def close(self):
                closed.append(True)

        register_backend("almost", lambda settings: AlmostBackend(), replace=True)
        with self.assertRaisesRegex(TypeError, "ProjectMemoryBackend"):
            get_backend({"engine": "almost", "project_id": "demo"})

        self.assertEqual(closed, [True])

    def test_backend_missing_required_safety_capabilities_is_rejected(self):
        class UnsafeBackend(FakeBackend):
            engine = "unsafe-test"

            def capabilities(self):
                return BackendCapabilities(semantic_search=True)

        register_backend("unsafe-test", UnsafeBackend, replace=True)
        with self.assertRaisesRegex(ValueError, "required safety capabilities"):
            get_backend({"engine": "unsafe-test", "project_id": "demo"})

    def test_backend_capabilities_must_use_canonical_model(self):
        class MalformedCapabilities(FakeBackend):
            engine = "bad-capabilities"

            def capabilities(self):
                return {"stable_replace": True}

        register_backend("bad-capabilities", MalformedCapabilities, replace=True)
        with self.assertRaisesRegex(TypeError, "BackendCapabilities"):
            get_backend({"engine": "bad-capabilities", "project_id": "demo"})

    def test_incompatible_backend_api_version_is_rejected(self):
        class FutureBackend(FakeBackend):
            engine = "future-test"
            api_version = 3

        register_backend("future-test", FutureBackend, replace=True)
        with self.assertRaisesRegex(ValueError, "API version"):
            get_backend({"engine": "future-test", "project_id": "demo"})

    def test_backend_project_id_mismatch_is_rejected(self):
        class WrongProjectBackend(FakeBackend):
            engine = "wrong-project"

            def __init__(self, settings):
                super().__init__(settings)
                self.project_id = "another-project"

        register_backend("wrong-project", WrongProjectBackend, replace=True)
        with self.assertRaisesRegex(ValueError, "project_id mismatch"):
            get_backend({"engine": "wrong-project", "project_id": "demo"})

    def test_memory_facade_routes_to_selected_backend(self):
        calls = []

        class Adapter(FakeBackend):
            engine = "adapter-test"

            def recall(self, query, max_results=8):
                calls.append(("recall", query, max_results))
                return [ProjectMemoryHit("기억", {"source": "ADR.md"}, "id-1", 0.8)]

            def retain(self, items):
                calls.append(("retain", items))
                return BackendWriteResult(True, accepted_ids=tuple(item.record_id for item in items), details={"backend": self.engine})

            def close(self):
                calls.append(("close",))

        register_backend("adapter-test", Adapter, replace=True)
        cfg = {
            "engine": "adapter-test",
            "project_id": "demo",
            "project_uid": "11111111-1111-4111-8111-111111111111",
            "binding_id": "22222222-2222-4222-8222-222222222222",
        }

        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True):
            hits = memory_bridge.server_recall(cfg, "질의", max_results=4)
            written = memory_bridge.server_retain_items(cfg, [{"content": "결정"}])

        self.assertEqual(hits[0]["document_id"], "id-1")
        self.assertEqual(written, {"backend": "adapter-test", "success": True, "items_count": 1})
        self.assertEqual(calls[0], ("recall", "질의", 4))
        retain_call = next(call for call in calls if call[0] == "retain")
        self.assertIsInstance(retain_call[1][0], ProjectMemoryRecord)
        self.assertEqual(retain_call[1][0].text, "결정")
        self.assertEqual([call for call in calls if call[0] == "close"], [("close",), ("close",)])

    def test_facade_rejects_provider_native_result_shapes(self):
        class NativeShapeBackend(FakeBackend):
            engine = "native-shape"

            def recall(self, query, max_results=8):
                return [{"provider_text": "leaked"}]

        register_backend("native-shape", NativeShapeBackend, replace=True)
        cfg = {
            "engine": "native-shape",
            "project_id": "demo",
            "project_uid": "11111111-1111-4111-8111-111111111111",
            "binding_id": "22222222-2222-4222-8222-222222222222",
        }
        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True), self.assertRaisesRegex(
            TypeError, "ProjectMemoryHit"
        ):
            memory_bridge.server_recall(cfg, "query")

    def test_facade_rejects_false_complete_write_results(self):
        class PartialSuccessBackend(FakeBackend):
            engine = "partial-success"

            def retain(self, items):
                return BackendWriteResult(True, accepted_ids=(), rejected={items[0].record_id: "not written"})

        register_backend("partial-success", PartialSuccessBackend, replace=True)
        cfg = {
            "engine": "partial-success",
            "project_id": "demo",
            "project_uid": "11111111-1111-4111-8111-111111111111",
            "binding_id": "22222222-2222-4222-8222-222222222222",
        }
        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True), self.assertRaisesRegex(
            ValueError, "inconsistent write result"
        ):
            memory_bridge.server_retain_items(
                cfg,
                [{"document_id": "decision-1", "content": "결정"}],
            )

    def test_close_failure_does_not_mask_primary_backend_failure(self):
        class FailingBackend(FakeBackend):
            engine = "failing-close"

            def recall(self, query, max_results=8):
                raise RuntimeError("primary recall failure")

            def close(self):
                raise RuntimeError("secondary close failure")

        register_backend("failing-close", FailingBackend, replace=True)
        cfg = {
            "engine": "failing-close",
            "project_id": "demo",
            "project_uid": "11111111-1111-4111-8111-111111111111",
            "binding_id": "22222222-2222-4222-8222-222222222222",
        }
        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True), self.assertRaisesRegex(
            RuntimeError, "primary recall failure"
        ):
            memory_bridge.server_recall(cfg, "query")

    def test_connect_cli_persists_selected_engine_and_options(self):
        from typer.testing import CliRunner

        from asgard.cli import app
        from asgard.settings import load_project

        class Adapter(FakeBackend):
            engine = "adapter-cli"

        register_backend("adapter-cli", Adapter, replace=True)
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {"HOME": root}), mock.patch(
            "asgard.commands.memory.os.getcwd", return_value=root
        ):
            result = CliRunner().invoke(
                app,
                [
                    "memory",
                    "connect",
                    "http://memory.example",
                    "--engine",
                    "adapter-cli",
                    "--project-id",
                    "demo",
                    "--claim",
                    "--option",
                    "collection=decisions",
                ],
            )
            config = load_project(root)["memory"]
            self.assertTrue(memory_bridge.is_backend_trusted(config))

        self.assertEqual(result.exit_code, 0, result.stdout or str(result.exception))
        self.assertEqual(config["engine"], "adapter-cli")
        self.assertEqual(config["project_id"], "demo")
        self.assertEqual(config["options"], {"collection": "decisions"})

    def test_doctor_uses_selected_backend_readiness_and_capabilities(self):
        from asgard.commands.doctor import _trinity_checks

        class Adapter(FakeBackend):
            engine = "doctor-adapter"

            def capabilities(self):
                return BackendCapabilities(
                    semantic_search=True,
                    hybrid_search=True,
                    metadata_roundtrip=True,
                    namespace_isolation=True,
                    stable_replace=True,
                    ownership_binding=True,
                )

        register_backend("doctor-adapter", Adapter, replace=True)
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {"HOME": root}):
            open(f"{root}/AGENTS.md", "w", encoding="utf-8").write("<!-- asgard:trinity -->")
            memory_bridge.write_config(
                root,
                "http://memory.example",
                "demo",
                engine="doctor-adapter",
                project_uid="11111111-1111-4111-8111-111111111111",
                binding_id="22222222-2222-4222-8222-222222222222",
            )
            found = memory_bridge.find_config(root)
            assert found is not None
            memory_bridge.trust_backend(found[1])
            check = next(row for row in _trinity_checks(root) if row["name"] == "shared memory backend")

        self.assertTrue(check["ok"])
        self.assertIn("engine=doctor-adapter", check["detail"])
        self.assertIn("hybrid_search", check["detail"])

    def test_doctor_does_not_probe_untrusted_repo_backend(self):
        from asgard.commands.doctor import _trinity_checks

        with tempfile.TemporaryDirectory() as root:
            open(f"{root}/AGENTS.md", "w", encoding="utf-8").write("<!-- asgard:trinity -->")
            memory_bridge.write_config(root, "http://untrusted.example", "demo")
            with mock.patch("asgard.project_memory_backends.get_backend") as get_backend:
                check = next(row for row in _trinity_checks(root) if row["name"] == "shared memory backend")

        self.assertFalse(check["ok"])
        self.assertIn("untrusted", check["detail"])
        get_backend.assert_not_called()


class TestHindsightBackend(unittest.TestCase):
    def test_binding_roundtrip_uses_exact_document_api(self):
        binding = ProjectMemoryBinding(
            project_uid="11111111-1111-4111-8111-111111111111",
            binding_id="22222222-2222-4222-8222-222222222222",
            project_id="demo",
        )

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size=-1):
                return json.dumps(self.payload).encode()

        backend = get_backend(
            {
                "engine": "hindsight",
                "endpoint": "http://memory:8888",
                "project_id": "demo",
                "project_uid": binding.project_uid,
                "binding_id": binding.binding_id,
            }
        )
        document = {"original_text": binding.to_json(), "id": "asgard:project-binding:v1", "bank_id": "demo"}
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[Response({"success": True, "items_count": 1}), Response(document)],
        ) as urlopen:
            result = backend.write_binding(binding)
            observed = backend.read_binding()

        self.assertTrue(result.success)
        self.assertEqual(observed, binding)
        self.assertTrue(urlopen.call_args_list[1].args[0].full_url.endswith("/documents/asgard%3Aproject-binding%3Av1"))

    def test_malformed_binding_document_fails_closed(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size=-1):
                return b'{"original_text":"not-json"}'

        backend = get_backend(
            {
                "engine": "hindsight",
                "endpoint": "http://memory:8888",
                "project_id": "demo",
                "project_uid": "11111111-1111-4111-8111-111111111111",
                "binding_id": "22222222-2222-4222-8222-222222222222",
            }
        )
        with mock.patch("urllib.request.urlopen", return_value=Response()), self.assertRaisesRegex(
            ValueError, "binding"
        ):
            backend.read_binding()

    def test_close_is_safe_for_backend_lifecycle(self):
        backend = get_backend({"server": "http://memory:8888", "bank": "demo"})
        self.assertIsNone(backend.close())

    def test_oversized_backend_response_is_rejected(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size=-1):
                return b"x" * size

        backend = get_backend({"server": "http://memory:8888", "bank": "demo"})
        with mock.patch("urllib.request.urlopen", return_value=Response()), self.assertRaisesRegex(
            ValueError, "response exceeds"
        ):
            backend.recall("query")

    def test_capabilities_and_readiness_are_backend_neutral(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size=-1):
                return b"{}"

        backend = get_backend({"server": "http://memory:8888", "bank": "demo"})
        capabilities = backend.capabilities()
        self.assertTrue(capabilities.semantic_search)
        self.assertTrue(capabilities.metadata_roundtrip)
        self.assertTrue(capabilities.namespace_isolation)
        self.assertTrue(capabilities.stable_replace)
        self.assertFalse(capabilities.hybrid_search)

        with mock.patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            readiness = backend.readiness()

        self.assertEqual(readiness.status, "ready")
        self.assertEqual(readiness.engine, "hindsight")
        self.assertEqual(readiness.project_id, "demo")
        self.assertEqual(urlopen.call_args.args[0].full_url, "http://memory:8888/openapi.json")

    def test_recall_normalizes_hindsight_results(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size=-1):
                return json.dumps(
                    {
                        "results": [
                            {
                                "text": "프로젝트 결정",
                                "metadata": {"source": "docs/adr.md"},
                                "id": "memory-1",
                                "score": 0.91,
                            }
                        ]
                    }
                ).encode()

        backend = get_backend({"server": "http://memory:8888", "bank": "demo"})
        with mock.patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            hits = backend.recall("결정", max_results=3)

        self.assertEqual(hits[0].text, "프로젝트 결정")
        self.assertEqual(hits[0].metadata["source"], "docs/adr.md")
        self.assertEqual(hits[0].document_id, "memory-1")
        self.assertEqual(hits[0].score, 0.91)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://memory:8888/v1/default/banks/demo/memories/recall")
        self.assertEqual(json.loads(request.data), {"query": "결정"})

    def test_retain_normalizes_write_result_and_preserves_items(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size=-1):
                return b'{"success": true, "items_count": 1}'

        record = ProjectMemoryRecord("decision-1", "승인된 결정", context="project decision")
        backend = get_backend({"engine": "hindsight", "endpoint": "http://memory:8888", "project_id": "demo"})
        with mock.patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            result = backend.retain([record])

        self.assertTrue(result.success)
        self.assertEqual(result.accepted_ids, ("decision-1",))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://memory:8888/v1/default/banks/demo/memories")
        self.assertEqual(
            json.loads(request.data),
            {
                "items": [
                    {
                        "content": "승인된 결정",
                        "context": "project decision",
                        "document_id": "decision-1",
                        "update_mode": "replace",
                        "tags": [],
                        "metadata": {},
                    }
                ],
                "async": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
