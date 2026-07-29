#!/usr/bin/env python3
"""에이전트 정체성 모드 B 훅 (agent-activate) — standalone subprocess 검증 (배포 형태 그대로).

네이티브 Heimdall 은 profiles.note() 를 역할 세션 프롬프트에 직접 얹는다. 모드 B(Claude Code/
Codex/Cursor)는 호스트가 세션을 소유하므로 훅으로 보상한다. 훅은 asgard 를 임포트하지 못하므로
(사용자 리포에 복사되는 단일 파일) 배치 해석과 렌더를 재구현한다 — 그 재구현이 정본과 갈라지면
"도구를 바꾸면 다른 에이전트가 답한다"가 되고, 그게 이 레인이 막으려는 바로 그 드리프트다.

그래서 중심은 둘이다:
  ① 렌더 단일 출처 — 훅 본문 == profiles.note() 본문 (바이트)
  ② 배치 해석 단일 출처 — 훅이 고른 에이전트 == swarm.resolve() 가 고른 에이전트
     (역할 > 모드 > 프로젝트 대표 > 루트 활성, 그리고 없는 이름은 fail-open)

실행: uv run pytest tests/test_agent_hook.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOK_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "asgard",
    "hooks",
    "agent_activate.py",
)


class AgentHookBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, ".asgard"))
        self.hooks = os.path.join(self.root, ".claude", "hooks")
        os.makedirs(self.hooks)
        shutil.copy(HOOK_SRC, os.path.join(self.hooks, "agent-activate.py"))
        # 훅과 정본이 같은 뿌리를 보도록 HOME 을 빈 임시 디렉터리로 고정 (양쪽 동일 조건).
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    # ── 정본 쪽 (같은 HOME 조건에서 실행) ──────────────────────────────────────────

    def _with_home(self, fn):
        prev = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        try:
            return fn()
        finally:
            if prev is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = prev

    def make(self, name: str, identity: str | None = None, display: str | None = None) -> None:
        from asgard import profiles

        def _do():
            profiles.create(name, display=display)
            if identity is not None:
                with open(os.path.join(profiles.profile_dir(name), profiles.IDENTITY), "w", encoding="utf-8") as f:
                    f.write(identity)

        self._with_home(_do)

    def bind(self, name: str, *, mode: str | None = None, role: str | None = None) -> None:
        from asgard import swarm

        self._with_home(lambda: swarm.bind(self.root, name, mode=mode, role=role))

    def use(self, name: str) -> None:
        from asgard import profiles

        self._with_home(lambda: profiles.set_active(name))

    def native_note(self, name: str) -> str:
        from asgard import profiles

        return self._with_home(lambda: profiles.note(name)).strip()

    def native_pick(self, *, mode: str | None = None, role: str | None = None) -> str:
        from asgard import swarm

        return self._with_home(lambda: swarm.resolve(self.root, mode=mode, role=role))

    # ── 훅 쪽 (서브프로세스 — 배포 형태 그대로) ──────────────────────────────────────

    def hook(self, payload: dict | None = None, client: str = "claude-code"):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CURSOR_", "ASGARD_"))}
        env["HOME"] = self.home.name
        return subprocess.run(
            [sys.executable, os.path.join(self.hooks, "agent-activate.py"), client],
            input=json.dumps({"cwd": self.root, **(payload or {})}),
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
            timeout=30,
        )

    def body(self, out: str) -> str:
        """`[agent]\\n\\n` prefix (및 클라이언트별 JSON 봉투) 를 벗겨 본문만."""
        out = out.strip()
        if not out:
            return ""
        if out.startswith("{"):
            parsed = json.loads(out)
            out = parsed.get("additional_context") or parsed["hookSpecificOutput"]["additionalContext"]
        assert out.startswith("[agent]"), out
        return out[len("[agent]") :].strip()


class TestRenderIsSingleSource(AgentHookBase):
    def test_hook_body_is_byte_identical_to_the_native_render(self):
        self.make("loki-qa", identity="Hunt counterexamples. Never patch — only prove.", display="로키")
        self.use("loki-qa")
        result = self.hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.body(result.stdout), self.native_note("loki-qa"))

    def test_display_name_and_id_both_appear_when_they_differ(self):
        self.make("loki-qa", identity="body", display="로키")
        self.use("loki-qa")
        self.assertIn("로키 (loki-qa)", self.body(self.hook().stdout))

    def test_truncation_matches_the_native_limit(self):
        from asgard.profiles import IDENTITY_MAX

        self.make("wordy", identity="\n".join(f"line {i} — padding padding padding" for i in range(1200)))
        self.use("wordy")
        body = self.body(self.hook().stdout)
        self.assertIn("truncated at the size limit", body)
        self.assertEqual(body, self.native_note("wordy"))
        self.assertLess(len(body), IDENTITY_MAX + 2000)


class TestPlacementIsSingleSource(AgentHookBase):
    def setUp(self):
        super().setUp()
        for name in ("alpha", "beta", "gamma"):
            self.make(name, identity=f"I am {name}.")

    def _picked(self, body: str) -> str:
        for name in ("alpha", "beta", "gamma"):
            if f"I am {name}." in body:
                return name
        return ""

    def test_role_beats_mode_beats_default_beats_sticky(self):
        self.use("gamma")
        self.assertEqual(self._picked(self.body(self.hook().stdout)), "gamma")  # 루트 활성

        self.bind("beta")  # 프로젝트 대표
        self.assertEqual(self._picked(self.body(self.hook().stdout)), "beta")

        self.bind("alpha", mode="claude-code")  # 모드 고정
        self.assertEqual(self._picked(self.body(self.hook().stdout)), "alpha")

        self.bind("gamma", role="worker")  # 역할 배치 — 서브에이전트 턴에서만
        picked = self._picked(self.body(self.hook({"agent_type": "asgard-worker"}).stdout))
        self.assertEqual(picked, "gamma")
        # 같은 프로젝트, 메인 스레드는 여전히 모드 고정
        self.assertEqual(self._picked(self.body(self.hook().stdout)), "alpha")

    def test_hook_and_native_agree_on_every_axis(self):
        self.use("gamma")
        self.bind("beta")
        self.bind("alpha", mode="claude-code")
        self.bind("gamma", role="verifier")
        for payload, mode, role in (
            ({}, "claude-code", None),
            ({"agent_type": "asgard-verifier"}, "claude-code", "verifier"),
            ({"agent_type": "asgard-thinker"}, "claude-code", "thinker"),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self._picked(self.body(self.hook(payload).stdout)), self.native_pick(mode=mode, role=role)
                )

    def test_cursor_mode_binding_is_honoured_by_the_cursor_client(self):
        self.bind("alpha", mode="claude-code")
        self.bind("beta", mode="cursor")
        self.assertEqual(self._picked(self.body(self.hook(client="cursor").stdout)), "beta")
        self.assertEqual(self._picked(self.body(self.hook(client="claude-code").stdout)), "alpha")

    def test_missing_agent_fails_open_to_the_root_active_one(self):
        """프로젝트 설정은 리포에 실려 남의 기계로 간다 — 없는 이름이 세션을 막으면 순손실."""
        self.use("alpha")
        path = os.path.join(self.root, ".asgard", "asgard-setting-project.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"agents": {"default": "ghost", "roles": {"worker": "also-ghost"}}}, handle)
        result = self.hook({"agent_type": "asgard-worker"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self._picked(self.body(result.stdout)), "alpha")


class TestContainerHome(AgentHookBase):
    """컨테이너 안에서 CC/Codex 를 돌리는 경우 — 훅이 호스트가 아니라 그 볼륨을 읽어야 한다.

    실측 26-07-29: 훅의 `sticky()` 가 모르는 `ASGARD_HOME` 을 DEFAULT 로 접어, 컨테이너
    에이전트가 **호스트의 `~/.asgard`** 를 자기 정체성으로 받고 있었다. 기억은 맞는 곳에
    쓰면서 정체성만 남의 것이 되는, 제일 알아채기 어려운 형태의 어긋남이다."""

    def setUp(self):
        super().setUp()
        self.container = os.path.join(self.tmp.name, "opt", "agent-data")
        os.makedirs(self.container, exist_ok=True)
        with open(os.path.join(self.container, "AGENT.md"), "w", encoding="utf-8") as handle:
            handle.write("나는 컨테이너 전용 에이전트다. 로그 분석만 한다.")
        # 호스트 쪽에는 다른 정체성을 심어 둔다 — 잘못 읽으면 이게 나온다.
        os.makedirs(os.path.join(self.home.name, ".asgard"), exist_ok=True)
        with open(os.path.join(self.home.name, ".asgard", "AGENT.md"), "w", encoding="utf-8") as handle:
            handle.write("나는 호스트의 기본 에이전트다.")

    def hook(self, payload=None, client="claude-code"):  # type: ignore[override]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CURSOR_", "ASGARD_"))}
        env["HOME"] = self.home.name
        env["ASGARD_HOME"] = self.container
        return subprocess.run(
            [sys.executable, os.path.join(self.hooks, "agent-activate.py"), client],
            input=json.dumps({"cwd": self.root, **(payload or {})}),
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
            timeout=30,
        )

    def test_hook_reads_the_volume_not_the_host(self):
        body = self.body(self.hook().stdout)
        self.assertIn("로그 분석만 한다", body)
        self.assertNotIn("호스트의 기본 에이전트", body)

    def test_hook_matches_the_native_render_for_a_volume_home(self):
        from asgard import profiles

        prev = dict(os.environ)
        os.environ["HOME"] = self.home.name
        os.environ["ASGARD_HOME"] = self.container
        try:
            native = profiles.note().strip()
        finally:
            os.environ.clear()
            os.environ.update(prev)
        self.assertEqual(self.body(self.hook().stdout), native)

    def test_header_names_the_volume(self):
        self.assertIn("agent-data", self.body(self.hook().stdout))


class TestClientSchemas(AgentHookBase):
    def setUp(self):
        super().setUp()
        self.make("solo", identity="I am solo.")
        self.use("solo")

    def test_cursor_uses_additional_context(self):
        payload = json.loads(self.hook(client="cursor").stdout)
        self.assertIn("additional_context", payload)

    def test_subagent_uses_hook_specific_output(self):
        payload = json.loads(self.hook({"agent_type": "asgard-worker"}).stdout)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SubagentStart")

    def test_main_thread_is_plain_text(self):
        self.assertTrue(self.hook().stdout.startswith("[agent]"))


class TestSilenceAndFailOpen(AgentHookBase):
    def test_no_agents_at_all_means_no_output(self):
        """프로파일을 안 쓰는 설치 — 프롬프트가 이 계층 도입 전과 바이트 단위로 같아야 한다."""
        result = self.hook()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_comment_only_identity_stays_silent(self):
        """`agent create` 가 배송하는 안내 템플릿 그대로면 무주입 (토큰 회귀 0)."""
        from asgard import profiles

        self._with_home(lambda: profiles.create("plain"))
        self.use("plain")
        self.assertEqual(self.hook().stdout, "")

    def test_broken_settings_do_not_block_the_session(self):
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        result = self.hook()
        self.assertEqual(result.returncode, 0)

    def test_garbage_stdin_does_not_block_the_session(self):
        result = subprocess.run(
            [sys.executable, os.path.join(self.hooks, "agent-activate.py"), "claude-code"],
            input="not json at all",
            capture_output=True,
            text=True,
            cwd=self.root,
            env={**os.environ, "HOME": self.home.name},
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
