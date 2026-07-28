"""Hindsight 학습 정책 — 정적 문서는 건드리지 않고 승인 record만 관찰·모델로 올린다."""

import unittest

from asgard.project_memory import learning


class FakeLearningBackend:
    def __init__(self):
        self.config = {
            "retain_strategies": {},
            "enable_observations": False,
            "enable_auto_consolidation": True,
        }
        self.models = {}
        self.consolidations = []
        self.refreshed = []

    def bank_config(self):
        return dict(self.config)

    def update_bank_config(self, updates):
        self.config.update(updates)
        return dict(self.config)

    def consolidate(self, scopes):
        self.consolidations.append(scopes)
        return {"operation_id": "consolidate-1", "deduplicated": False}

    def list_mental_models(self):
        return [dict(model) for model in self.models.values()]

    def create_mental_model(self, spec):
        self.models[spec["id"]] = {**spec, "content": "building", "is_stale": False}
        return {"operation_id": "create-" + spec["id"]}

    def update_mental_model(self, model_id, spec):
        self.models[model_id].update(spec)
        return dict(self.models[model_id])

    def refresh_mental_model(self, model_id):
        self.refreshed.append(model_id)
        return {"operation_id": "refresh-" + model_id}


class LearningTest(unittest.TestCase):
    def test_generating_placeholder_is_not_ready(self):
        self.assertFalse(learning.model_ready({"content": "Generating content..."}))
        self.assertFalse(learning.model_ready({"content": "I don't have information."}))
        self.assertTrue(learning.model_ready({"content": "# Architecture\n\nReady"}))

    def test_apply_configures_scoped_observations_and_three_models(self):
        backend = FakeLearningBackend()

        result = learning.apply(backend)

        self.assertTrue(result["config_changed"])
        self.assertTrue(backend.config["enable_observations"])
        self.assertFalse(backend.config["enable_auto_consolidation"])
        self.assertEqual(backend.consolidations, [[["record"]]])
        self.assertEqual(set(backend.models), {spec["id"] for spec in learning.MODEL_SPECS})
        self.assertTrue(all(model["trigger"]["refresh_after_consolidation"] for model in backend.models.values()))
        self.assertTrue(all(model["trigger"]["tags_match"] == "all_strict" for model in backend.models.values()))

    def test_apply_is_idempotent_and_plan_reports_ready(self):
        backend = FakeLearningBackend()
        learning.apply(backend)

        second = learning.apply(backend)
        plan = learning.plan(backend)

        self.assertFalse(second["config_changed"])
        self.assertEqual(second["models"], [])
        self.assertTrue(plan["configured"])
        self.assertEqual(plan["missing_models"], [])
        self.assertEqual(plan["drifted_models"], [])
        self.assertTrue(all(model["ready"] for model in plan["models"]))

    def test_drifted_model_is_updated_and_refreshed(self):
        backend = FakeLearningBackend()
        learning.apply(backend)
        backend.models["asgard-architecture"]["source_query"] = "stale"

        result = learning.apply(backend)

        row = next(row for row in result["models"] if row["id"] == "asgard-architecture")
        self.assertEqual(row["action"], "updated")
        self.assertEqual(backend.refreshed, ["asgard-architecture"])

    def test_empty_or_stale_model_is_refreshed(self):
        backend = FakeLearningBackend()
        learning.apply(backend)
        backend.models["asgard-architecture"]["content"] = "I don't have information."
        backend.models["asgard-decisions"]["is_stale"] = True

        result = learning.apply(backend)

        self.assertEqual({row["action"] for row in result["models"]}, {"refreshed"})
        self.assertEqual(backend.refreshed, ["asgard-architecture", "asgard-decisions"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
