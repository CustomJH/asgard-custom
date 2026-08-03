"""스튜디오 에이전트 표면 — 창에서 고친 값이 실제로 그 에이전트를 바꾸는가.

여기서 지키는 것은 다섯이다.
  · 주소가 실제로 걸려 있다 — 그래서 전부 `studio.dispatch`/`dispatch_post`를 통해 잰다.
    모듈 함수를 직접 부르면 재료는 맞는데 문이 없는 상태를 못 잡는다.
  · 창에서 고친 설정을 그 에이전트의 런타임(`profiles.scoped` + `settings.load_global`)이 본다.
    이 한 줄이 이 표면의 값어치다 — 못 보면 화면은 저장했다고 말하고 기계는 안 바뀐다.
  · 창에서 적은 정체성이 다음 세션의 프롬프트(`profiles.note`)에 실린다.
  · 파괴는 확인을 요구한다 — `confirm` 없는 삭제는 409 이고, 그 문장은 잃을 쪽수를 든다.
  · 격리 — 한 에이전트를 고쳐도 다른 에이전트의 파일은 한 바이트도 안 바뀐다.

격리 방식은 tests/test_profiles.py 와 같다: TemporaryDirectory + HOME 패치. 에이전트는
프로젝트가 아니라 **기계**에 속하므로, 홈을 안 옮기면 이 스위트가 사용자의 진짜
`~/.asgard`에 에이전트를 세운다.
"""

import ast
import json
import os
import tempfile
import unittest
from unittest import mock

from asgard import profiles, settings, swarm
from asgard.commands import studio
from asgard.commands.studio import agents as studio_agents

_MODULE_PATH = os.path.join(os.path.dirname(studio_agents.__file__), "agents.py")


def _clean_env(home: str) -> dict[str, str]:
    """ASGARD_* 를 전부 걷어낸 환경 — 남아 있으면 해석 사다리가 임시 홈을 안 본다."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASGARD_")}
    env["HOME"] = home
    env["ASGARD_MEMORY_SEMANTIC"] = "off"  # 임베딩 모델 다운로드 밀폐 (conftest와 같은 규율)
    return env


class AgentSurfaceCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-studio-agents-")
        self.home = self._tmp.name
        self._env = mock.patch.dict(os.environ, _clean_env(self.home), clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self.home, "proj")
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)

    def get(self, path: str, **params: str) -> tuple[int, dict]:
        status, _, body = studio.dispatch("GET", path, {k: [v] for k, v in params.items()}, self.root)
        return status, json.loads(body)

    def post(self, path: str, payload: dict) -> tuple[int, dict]:
        status, _, body = studio.dispatch_post(path, payload, self.root)
        return status, json.loads(body)

    def make(self, name: str, **kw: object) -> dict:
        status, data = self.post("/api/agents/create", {"name": name, **kw})
        self.assertEqual(status, 200, data)
        return data


class TestListing(AgentSurfaceCase):
    def test_the_listing_shows_what_was_made_and_who_is_active(self):
        """만든 에이전트가 목록에 있고, 활성이 맞게 짚인다 — 창이 답해야 할 첫 물음이다."""
        self.make("loki-qa", description="검증을 맡는다")
        status, data = self.get("/api/agents")

        self.assertEqual(status, 200)
        rows = {row["id"]: row for row in data["agents"]}
        self.assertIn("loki-qa", rows)
        self.assertEqual(rows["loki-qa"]["description"], "검증을 맡는다")
        self.assertEqual(data["active"], "default")  # 만들기는 활성을 안 옮긴다
        self.assertTrue(rows["default"]["active"])
        self.assertFalse(rows["loki-qa"]["active"])

        self.post("/api/agents/use", {"name": "loki-qa"})
        _, after = self.get("/api/agents")
        self.assertEqual(after["active"], "loki-qa")
        self.assertTrue({row["id"]: row for row in after["agents"]}["loki-qa"]["active"])

    def test_the_listing_carries_the_machine_and_the_project_in_one_trip(self):
        """명부(기계)와 배치(프로젝트)는 한 왕복이다 — 갈라 물으면 그 사이의 변경이 서로의 결과처럼 보인다."""
        self.make("freyja-ui")
        self.post("/api/agents/bind", {"name": "freyja-ui", "role": "worker"})

        _, data = self.get("/api/agents")

        for key in ("agents", "active", "builtin_available", "root", "binding", "swarm", "missing", "warning"):
            self.assertIn(key, data)
        self.assertEqual(data["root"], profiles.root())
        self.assertEqual(data["binding"]["roles"], {"worker": "freyja-ui"})
        # 선언 안 함은 null 이다 — 빈 문자열로 주면 화면이 "기본 에이전트를 골랐다"로 읽는다
        self.assertIsNone(data["binding"]["default"])
        self.assertFalse(data["swarm"])  # 역할 하나로는 스웜이 아니다
        self.assertEqual(data["missing"], [])

    def test_the_detail_carries_identity_and_config_together(self):
        """상세 한 왕복 — 정체성과 설정을 따로 받으면 그 사이의 저장이 이 화면의 값처럼 보인다."""
        self.make("saga-doc")
        status, data = self.get("/api/agent", name="saga-doc")

        self.assertEqual(status, 200)
        row_keys = ("id", "name", "description", "based_on", "capabilities", "path", "active", "memory_pages")
        detail_keys = ("identity", "identity_path", "identity_meaningful", "config", "config_view", "config_path")
        for key in row_keys + detail_keys:
            self.assertIn(key, data)
        self.assertEqual(data["id"], "saga-doc")
        # 갓 만든 에이전트의 AGENT.md 는 주석뿐이다 — 파일은 있으나 프롬프트에는 안 실린다
        self.assertFalse(data["identity_meaningful"])
        self.assertTrue(data["identity_path"].endswith(profiles.IDENTITY))


class TestConfigReachesTheRuntime(AgentSurfaceCase):
    def test_a_saved_section_is_what_that_agent_actually_runs_with(self):
        """이 표면의 값어치 — 창에서 고친 값을 그 에이전트의 런타임이 본다."""
        self.make("loki-qa")

        status, data = self.post(
            "/api/agents/config", {"name": "loki-qa", "section": "provider", "values": {"name": "codex"}}
        )

        self.assertEqual(status, 200, data)
        self.assertEqual(data["config"]["provider"], {"name": "codex"})
        self.assertEqual(data["config_view"]["provider"]["name"], "codex")
        with profiles.scoped("loki-qa"):
            self.assertEqual(settings.load_global()["provider"]["name"], "codex")

    def test_the_own_view_and_the_merged_view_are_told_apart(self):
        """물려받은 값과 자기가 적은 값은 다른 칸이다 — 합치면 뿌리의 값을 자기 값으로 오해한다."""
        settings.save_global("ui", {"density": "compact"})  # 기계 뿌리(default)에 적는다
        self.make("loki-qa")

        _, data = self.post(
            "/api/agents/config", {"name": "loki-qa", "section": "provider", "values": {"name": "codex"}}
        )

        self.assertNotIn("ui", data["config"])  # 자기가 적은 것에는 없다
        self.assertEqual(data["config_view"]["ui"]["density"], "compact")  # 실효 값에는 있다

    def test_a_missing_section_or_values_is_refused(self):
        self.make("loki-qa")
        self.assertEqual(self.post("/api/agents/config", {"name": "loki-qa", "values": {}})[0], 400)
        self.assertEqual(self.post("/api/agents/config", {"name": "loki-qa", "section": "provider"})[0], 400)


class TestIdentityReachesThePrompt(AgentSurfaceCase):
    def test_a_written_identity_is_carried_into_the_prompt(self):
        """창에서 적은 정체성이 다음 세션에 실린다 — 안 실리면 저장은 장식이다."""
        self.make("loki-qa")
        body = "너는 검증만 한다. 고치지 않는다."

        status, data = self.post("/api/agents/identity", {"name": "loki-qa", "body": body})

        self.assertEqual(status, 200, data)
        self.assertEqual(data["chars"], len(body))
        self.assertTrue(data["meaningful"])
        self.assertIn(body, profiles.note("loki-qa"))
        _, detail = self.get("/api/agent", name="loki-qa")
        self.assertEqual(detail["identity"], body)
        self.assertTrue(detail["identity_meaningful"])

    def test_a_comment_only_identity_is_reported_as_silent(self):
        """주석뿐인 본문은 저장은 되되 프롬프트엔 안 실린다 — 화면이 그 사실을 말할 수 있어야 한다."""
        self.make("loki-qa")

        _, data = self.post("/api/agents/identity", {"name": "loki-qa", "body": "<!-- 아직 안 적음 -->"})

        self.assertFalse(data["meaningful"])
        self.assertEqual(profiles.note("loki-qa"), "")


class TestDestructionAsksFirst(AgentSurfaceCase):
    def test_delete_without_confirm_is_refused_and_names_the_loss(self):
        """확인 없는 삭제는 409 — 그 문장에 잃을 기억 쪽수가 들어간다."""
        self.make("loki-qa")
        pages = os.path.join(profiles.profile_dir("loki-qa"), "memory", "pages")
        os.makedirs(pages, exist_ok=True)
        for n in range(3):
            with open(os.path.join(pages, f"p{n}.md"), "w", encoding="utf-8") as handle:
                handle.write("기억 한 쪽")

        status, body = self.post("/api/agents/delete", {"name": "loki-qa"})

        self.assertEqual(status, 409)
        self.assertIn("3", body["error"]["message"])
        self.assertTrue(body["error"]["remedy"])
        self.assertEqual(body["error"]["detail"]["memory_pages"], 3)
        self.assertTrue(os.path.isdir(profiles.profile_dir("loki-qa")))  # 아무것도 안 지웠다

    def test_delete_with_confirm_actually_removes_it(self):
        self.make("loki-qa")

        status, data = self.post("/api/agents/delete", {"name": "loki-qa", "confirm": True})

        self.assertEqual(status, 200, data)
        self.assertEqual(data["deleted"], "loki-qa")
        self.assertFalse(os.path.isdir(profiles.profile_dir("loki-qa")))

    def test_the_default_agent_cannot_be_deleted(self):
        status, body = self.post("/api/agents/delete", {"name": "default", "confirm": True})
        self.assertEqual(status, 400)
        self.assertTrue(body["error"]["remedy"])


class TestSwitchingIsNotSilent(AgentSurfaceCase):
    def test_the_switch_says_what_it_changed(self):
        """활성 전환은 이 기계 전체를 바꾼다 — 응답이 그 사실을 들어야 창이 확인을 붙일 수 있다."""
        self.make("loki-qa")

        status, data = self.post("/api/agents/use", {"name": "loki-qa"})

        self.assertEqual(status, 200, data)
        self.assertEqual(data["active"], "loki-qa")
        self.assertEqual(data["previous"], "default")
        self.assertEqual(data["scope"], "machine")  # 프로젝트가 아니라 기계다
        self.assertIn("loki-qa", data["note"])
        self.assertEqual(profiles.sticky(), "loki-qa")

    def test_an_unknown_name_is_not_quietly_raised_into_a_new_agent(self):
        """목록 밖의 이름은 오타다 — 조용히 세우면 만든 적 없는 에이전트로 기계가 돈다."""
        status, body = self.post("/api/agents/use", {"name": "typo-agent"})

        self.assertEqual(status, 404)
        self.assertTrue(body["error"]["remedy"])
        self.assertFalse(os.path.isdir(profiles.profile_dir("typo-agent")))
        self.assertEqual(profiles.sticky(), "default")


class TestUnknownNames(AgentSurfaceCase):
    def test_every_surface_answers_an_unknown_name_with_404_and_a_remedy(self):
        """없는 이름을 고쳤다고 말하면 기록이 거짓이 된다 — 그리고 처방 없는 404 는 막다른 길이다."""
        calls = [
            ("GET", "/api/agent", {"name": "ghost"}),
            ("POST", "/api/agents/describe", {"name": "ghost", "description": "x"}),
            ("POST", "/api/agents/identity", {"name": "ghost", "body": "x"}),
            ("POST", "/api/agents/config", {"name": "ghost", "section": "provider", "values": {}}),
            ("POST", "/api/agents/rename", {"name": "ghost", "to": "spirit"}),
            ("POST", "/api/agents/bind", {"name": "ghost", "role": "worker"}),
            ("POST", "/api/agents/delete", {"name": "ghost", "confirm": True}),
        ]
        for method, path, payload in calls:
            with self.subTest(path=path):
                status, body = self.get(path, **payload) if method == "GET" else self.post(path, payload)
                self.assertEqual(status, 404)
                self.assertEqual(body["error"]["code"], "agent_not_found")
                self.assertIn("ghost", body["error"]["message"])
                self.assertTrue(body["error"]["remedy"], "404 에 다음 걸음이 없으면 막다른 길이다")

    def test_a_blank_name_is_a_400_not_a_404(self):
        """안 골랐다와 지워진 걸 고쳤다는 다른 사실이다."""
        status, body = self.post("/api/agents/identity", {"body": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "name_required")


class TestIsolation(AgentSurfaceCase):
    def test_editing_one_agent_leaves_the_other_untouched(self):
        """격리가 이 계층의 전부다 — 창에서 고쳤다고 옆 에이전트가 흔들리면 안 된다."""
        self.make("loki-qa")
        self.make("freyja-ui")
        other = profiles.profile_dir("freyja-ui")
        before = {
            os.path.relpath(os.path.join(base, f), other): open(os.path.join(base, f), "rb").read()
            for base, _dirs, files in os.walk(other)
            for f in files
        }

        self.post("/api/agents/config", {"name": "loki-qa", "section": "provider", "values": {"name": "codex"}})
        self.post("/api/agents/identity", {"name": "loki-qa", "body": "검증만 한다"})
        self.post("/api/agents/describe", {"name": "loki-qa", "description": "검증 담당", "capabilities": ["review"]})

        after = {
            os.path.relpath(os.path.join(base, f), other): open(os.path.join(base, f), "rb").read()
            for base, _dirs, files in os.walk(other)
            for f in files
        }
        self.assertEqual(before, after)
        with profiles.scoped("freyja-ui"):
            self.assertEqual(settings.load_global().get("provider", {}).get("name"), None)
        self.assertEqual(profiles.note("freyja-ui"), "")


class TestManifestAndBinding(AgentSurfaceCase):
    def test_describe_writes_the_sentence_the_swarm_routes_on(self):
        self.make("loki-qa")

        status, data = self.post(
            "/api/agents/describe", {"name": "loki-qa", "description": "검증만 한다", "capabilities": ["review", "test"]}
        )

        self.assertEqual(status, 200, data)
        self.assertEqual(data["manifest"]["description"], "검증만 한다")
        self.assertEqual(profiles.manifest("loki-qa")["capabilities"], ["review", "test"])

    def test_binding_two_roles_to_two_agents_is_a_swarm(self):
        """역할이 서로 다른 에이전트로 갈리는 순간이 스웜이다 — 판정은 엔진의 것 그대로."""
        self.make("loki-qa")
        self.make("freyja-ui")

        self.post("/api/agents/bind", {"name": "freyja-ui", "role": "worker"})
        status, data = self.post("/api/agents/bind", {"name": "loki-qa", "role": "verifier"})

        self.assertEqual(status, 200, data)
        self.assertTrue(data["swarm"])
        self.assertEqual(swarm.binding(self.root)["roles"], {"worker": "freyja-ui", "verifier": "loki-qa"})
        # 배치 칸은 목록과 같은 모양이어야 한다 — 한 창 안에서 같은 키가 두 모양이면 그게 결함이다
        self.assertIsNone(data["binding"]["default"])
        self.assertEqual(data["binding"], self.get("/api/agents")[1]["binding"])

        _, dropped = self.post("/api/agents/unbind", {"role": "verifier"})
        self.assertEqual(dropped["binding"]["roles"], {"worker": "freyja-ui"})
        self.assertFalse(dropped["swarm"])

    def test_rename_moves_the_home_and_the_memory_with_it(self):
        """이름은 곧 홈 디렉터리다 — 바꾸면 기억과 설정이 함께 따라가야 한다."""
        self.make("loki-qa")
        self.post("/api/agents/config", {"name": "loki-qa", "section": "provider", "values": {"name": "codex"}})

        status, data = self.post("/api/agents/rename", {"name": "loki-qa", "to": "loki-verify"})

        self.assertEqual(status, 200, data)
        self.assertEqual(data["renamed"], "loki-verify")
        self.assertFalse(os.path.isdir(profiles.profile_dir("loki-qa")))
        with profiles.scoped("loki-verify"):
            self.assertEqual(settings.load_global()["provider"]["name"], "codex")

    def test_rename_onto_an_existing_name_is_a_conflict(self):
        self.make("loki-qa")
        self.make("freyja-ui")
        status, body = self.post("/api/agents/rename", {"name": "loki-qa", "to": "freyja-ui"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "agent_exists")

    def test_binding_refuses_a_mode_and_a_role_at_once(self):
        """역할이 모드보다 좁다 — 둘을 함께 적으면 어느 쪽이 이겼는지 아무도 못 말한다."""
        self.make("loki-qa")
        status, body = self.post("/api/agents/bind", {"name": "loki-qa", "mode": "native", "role": "worker"})
        self.assertEqual(status, 400)
        self.assertTrue(body["error"]["remedy"])


class TestCreateFailures(AgentSurfaceCase):
    def test_a_duplicate_name_is_a_conflict_not_a_silent_overwrite(self):
        self.make("loki-qa")
        status, body = self.post("/api/agents/create", {"name": "loki-qa"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "agent_exists")

    def test_an_illegal_name_is_refused_with_the_rule(self):
        status, body = self.post("/api/agents/create", {"name": "Loki QA!"})
        self.assertEqual(status, 400)
        self.assertTrue(body["error"]["remedy"])

    def test_a_reserved_name_is_refused(self):
        """예약어는 CLI 하위 명령과 겹친다 — 판정은 엔진(`profiles.validate`)의 것이다."""
        self.assertEqual(self.post("/api/agents/create", {"name": "memory"})[0], 400)


class TestChainAndWiring(unittest.TestCase):
    def test_the_material_module_never_looks_up_the_chain(self):
        """agents 는 orchestration 과 routes 사이다 — routes·server·파사드를 부르면 사슬이 순환한다."""
        with open(_MODULE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        banned = {"routes", "server", "__init__"}
        offending = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                siblings = {node.module.split(".")[0]} if node.module else {alias.name for alias in node.names}
                offending.extend(sorted(siblings & banned))
        self.assertFalse(offending, f"사슬을 거슬러 오르는 임포트: {offending}")

    def test_every_address_is_actually_mounted(self):
        """재료만 있고 문이 없으면 이 층은 도달하지 않는다 — 없는 주소는 404 텍스트로 떨어진다."""
        from asgard.commands.studio import routes

        for path in (
            "/api/agents/create",
            "/api/agents/use",
            "/api/agents/describe",
            "/api/agents/identity",
            "/api/agents/config",
            "/api/agents/rename",
            "/api/agents/bind",
            "/api/agents/unbind",
            "/api/agents/delete",
        ):
            with self.subTest(path=path):
                with open(routes.__file__, encoding="utf-8") as handle:
                    self.assertIn(f'"{path}"', handle.read())


if __name__ == "__main__":
    unittest.main()
