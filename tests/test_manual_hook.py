#!/usr/bin/env python3
"""커스텀 매뉴얼 모드 B 훅 (manual-activate) — standalone subprocess 검증 (배포 형태 그대로).

네이티브 Heimdall은 manual.py note()를 프롬프트에 직접 주입하지만, 모드 B(Claude Code/Codex/
Cursor)는 서브에이전트가 AGENTS.md를 읽는 구조라 훅으로 보상한다. 훅은 asgard를 임포트하지
못하므로(사용자 리포에 복사되는 단일 파일) 해석과 렌더를 재구현한다 — 그 재구현이 정본과 갈라지면
"모드를 바꾸면 규칙이 달라진다"가 되고, 그건 이 패치가 막으려는 바로 그 드리프트다.

그래서 이 스위트의 중심은 **단일 출처 대조**다: 훅이 낸 본문 == manual.note() 본문 (4개 절 전부,
별칭·조각·절단·킬스위치를 다 태운 상태에서). 나머지는 클라이언트별 주입 스키마와 fail-open.

실행: uv run pytest tests/test_manual_hook.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from asgard.manual import MANUAL_NAMES, note

HOOK_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "asgard",
    "hooks",
    "manual_activate.py",
)


class ManualHookBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, ".asgard"))
        self.hooks = os.path.join(self.root, ".claude", "hooks")
        os.makedirs(self.hooks)
        shutil.copy(HOOK_SRC, os.path.join(self.hooks, "manual-activate.py"))
        # 훅과 정본이 같은 글로벌 설정을 보도록 HOME을 빈 임시 디렉터리로 고정 (양쪽 동일 조건).
        self.home = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.home.cleanup()
        self.tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        """rel은 **리포 루트 기준** — 훅과 정본이 쓰는 좌표와 같게 둔다."""
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def common(self, rel: str, text: str) -> None:
        """공통 층(홈)에 쓴다 — 훅과 정본이 같은 HOME을 보므로 양쪽이 같은 파일을 읽는다."""
        path = os.path.join(self.home.name, ".asgard", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def settings(self, section: dict) -> None:
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            json.dump({"manual": section}, handle)

    def hook(self, payload: dict, client: str = "claude-code", env_extra: dict | None = None):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR")}
        env["HOME"] = self.home.name
        env.pop("ASGARD_MANUAL", None)
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, os.path.join(self.hooks, "manual-activate.py"), client],
            input=json.dumps({"cwd": self.root, **payload}),
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
            timeout=30,
        )

    def body(self, out: str) -> str:
        """`[manual]\\n\\n` prefix (및 클라이언트별 JSON 봉투)를 벗겨 본문만."""
        out = out.strip()
        if not out:
            return ""
        if out.startswith("{"):
            parsed = json.loads(out)
            out = parsed.get("additional_context") or parsed["hookSpecificOutput"]["additionalContext"]
        assert out.startswith("[manual]"), out
        return out[len("[manual]") :].strip()

    def native(self, section: str) -> str:
        """정본 렌더 — 훅과 같은 HOME 조건에서 (글로벌 설정 유입 차단)."""
        prev = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        try:
            return note(self.root, section).strip()
        finally:
            if prev is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = prev


class TestSingleSource(ManualHookBase):
    """훅 재구현이 정본과 바이트 단위로 같은가 — 이 패치의 드리프트 방지선."""

    CASES = (
        ({"source": "startup"}, "identity"),
        ({"agent_type": "asgard-thinker"}, "thinker"),
        ({"agent_type": "asgard-worker"}, "worker"),
        ({"agent_type": "asgard-verifier"}, "verifier"),
        ({"agent_type": "asgard-freyja"}, "identity"),  # 딜리버리 = identity 절
        ({"agent_type": "asgard-loki"}, "identity"),
    )

    def assert_parity(self):
        for payload, section in self.CASES:
            with self.subTest(section=section, agent=payload.get("agent_type", "main")):
                self.assertEqual(self.body(self.hook(payload).stdout), self.native(section))

    def test_parity_simple_manual(self):
        self.write("MANUAL.md", "## API\n- v1 프리픽스.")
        self.assert_parity()

    def test_parity_with_fragments(self):
        self.write("MANUAL.md", "## Base\n- 기본")
        self.write(".asgard/manual/20-db.md", "## DB\n- 되돌릴 수 있는 마이그레이션")
        self.write(".asgard/manual/10-api.md", "## API\n- v1")
        self.assert_parity()

    def test_parity_common_layer_alone(self):
        """공통 규칙만 있는 프로젝트 — 훅이 홈을 정본과 같은 사다리로 찾는가."""
        self.common("MANUAL.md", "- 보고는 내가 쓴 언어로")
        self.assert_parity()
        self.assertIn("~/.asgard/MANUAL.md", self.body(self.hook({"source": "startup"}).stdout))

    def test_parity_both_layers_stacked(self):
        """공통 + 프로젝트 — 순서와 '나중 것이 이긴다' 문장까지 정본과 같아야 한다."""
        self.common("MANUAL.md", "- 공통: 커밋은 한국어로")
        self.common("manual/10-a.md", "- 공통 조각")
        self.write("MANUAL.md", "- 프로젝트: 커밋은 영어로")
        self.write(".asgard/manual/20-b.md", "- 프로젝트 조각")
        self.assert_parity()
        body = self.body(self.hook({"source": "startup"}).stdout)
        self.assertLess(body.index("공통: 커밋"), body.index("프로젝트: 커밋"))
        self.assertIn("repository-specific rule wins", body)

    def test_layer_note_is_absent_with_one_layer(self):
        self.write("MANUAL.md", "- 프로젝트만")
        self.assertNotIn("repository-specific rule wins", self.body(self.hook({"source": "startup"}).stdout))

    def test_hook_follows_the_agent_home_env(self):
        """에인헤랴르 배치 — ASGARD_HOME이 가리키는 에이전트의 공통 규칙을 읽어야 한다."""
        alt = os.path.join(self.home.name, ".asgard", "profiles", "loki")
        os.makedirs(alt, exist_ok=True)
        with open(os.path.join(alt, "MANUAL.md"), "w", encoding="utf-8") as handle:
            handle.write("- 로키 전용 공통 규칙")
        self.common("MANUAL.md", "- 기본 에이전트 규칙")
        out = self.hook({"source": "startup"}, env_extra={"ASGARD_HOME": alt}).stdout
        self.assertIn("로키 전용 공통 규칙", out)
        self.assertNotIn("기본 에이전트 규칙", out)

    def test_parity_across_both_homes(self):
        """루트와 `.asgard/`를 동시에 쓰는 배치에서도 훅이 정본과 같은 순서로 잇는가."""
        self.write("MANUAL.md", "- 루트 규칙")
        self.write(".asgard/MANUAL.md", "- 보조 규칙")
        self.assert_parity()
        body = self.body(self.hook({"source": "startup"}).stdout)
        self.assertLess(body.index("루트 규칙"), body.index("보조 규칙"))

    def test_parity_with_alias_and_shadowing(self):
        for i, name in enumerate(MANUAL_NAMES):
            self.write(name, f"- rule {i}")
        self.assert_parity()

    def test_parity_when_truncated(self):
        self.write("MANUAL.md", "\n".join(f"- rule {i}" for i in range(4000)))
        self.assert_parity()
        self.assertIn("truncated at the size limit", self.body(self.hook({"source": "startup"}).stdout))

    def test_parity_with_raised_cap(self):
        self.settings({"max_chars": 40000})
        self.write("MANUAL.md", "\n".join(f"- rule {i}" for i in range(2000)))
        self.assert_parity()
        self.assertNotIn("truncated at the size limit", self.body(self.hook({"source": "startup"}).stdout))

    @unittest.skipIf(sys.platform == "win32", "심볼릭 링크 생성에 권한이 필요하다 (Windows)")
    def test_parity_when_a_link_escapes_the_repo(self):
        """울타리도 정본과 같이 간다 — 모드 B가 안 막으면 모드 B로 새기만 한다.

        훅은 저장소에 복사돼 나가는 별개 파일이라, 정본에만 울타리를 치면 CC·Codex·Cursor는
        그대로 `MANUAL.md -> ~/.ssh/id_rsa`를 읽어 additionalContext로 싣는다. 여기서
        대조하는 대상은 렌더 문자열이지만, 같으려면 **해석이 먼저 같아야** 한다."""
        target = os.path.join(self.home.name, "id_rsa")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")
        os.symlink(target, os.path.join(self.root, "MANUAL.md"))
        self.write("CUSTOM.md", "- 실제 규칙")
        self.assert_parity()
        out = self.hook({"source": "startup"}).stdout
        self.assertNotIn("BEGIN OPENSSH", out)
        self.assertIn("실제 규칙", out)

    def test_parity_when_only_comments(self):
        self.write("MANUAL.md", "<!-- 안내만 -->")
        for payload, _ in self.CASES:
            self.assertEqual(self.hook(payload).stdout.strip(), "")


class TestRoleSections(ManualHookBase):
    def setUp(self):
        super().setUp()
        self.write("MANUAL.md", "## API\n- v1 프리픽스.")

    def test_worker_receives_the_manual(self):
        """charter와 갈리는 유일한 자리 — 코드를 쓰는 역할에 안 닿으면 이 계층은 의미가 없다."""
        ctx = json.loads(self.hook({"agent_type": "asgard-worker"}).stdout)["hookSpecificOutput"]
        self.assertIn("v1 프리픽스", ctx["additionalContext"])
        self.assertIn("code you write", ctx["additionalContext"])

    def test_thinker_gets_criteria_reduction(self):
        ctx = json.loads(self.hook({"agent_type": "asgard-thinker"}).stdout)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "SubagentStart")
        self.assertIn("assigned-unit criteria", ctx["additionalContext"])

    def test_verifier_does_not_replace_criteria(self):
        ctx = json.loads(self.hook({"agent_type": "asgard-verifier"}).stdout)["hookSpecificOutput"]
        self.assertIn("does not replace criteria", ctx["additionalContext"])

    def test_main_thread_has_no_role_suffix(self):
        out = self.hook({"source": "startup"}).stdout
        self.assertIn("v1 프리픽스", out)
        self.assertNotIn("assigned-unit criteria", out)

    def test_alternate_agent_keys_are_read(self):
        """호스트마다 역할 신원 키가 다르다 — 셋 다 같은 절로 접혀야 한다."""
        for key in ("agent_type", "agent_name", "subagent_type"):
            with self.subTest(key=key):
                ctx = json.loads(self.hook({key: "asgard-verifier"}).stdout)["hookSpecificOutput"]
                self.assertIn("does not replace criteria", ctx["additionalContext"])


class TestClientSchemas(ManualHookBase):
    def setUp(self):
        super().setUp()
        self.write("MANUAL.md", "- 규칙 하나")

    def test_cursor_uses_additional_context(self):
        payload = json.loads(self.hook({"source": "startup"}, client="cursor").stdout)
        self.assertIn("규칙 하나", payload["additional_context"])

    def test_cursor_subagent_also_uses_additional_context(self):
        payload = json.loads(self.hook({"agent_type": "asgard-worker"}, client="cursor").stdout)
        self.assertIn("code you write", payload["additional_context"])

    def test_claude_and_codex_main_thread_is_plain_text(self):
        for client in ("claude-code", "codex"):
            with self.subTest(client=client):
                out = self.hook({"source": "startup"}, client=client).stdout
                self.assertTrue(out.startswith("[manual]"))

    def test_unknown_client_falls_back_to_claude_code(self):
        out = self.hook({"source": "startup"}, client="bogus-tool").stdout
        self.assertTrue(out.startswith("[manual]"))

    def test_project_dir_env_wins_over_cwd(self):
        """훅은 호스트가 준 프로젝트 루트를 먼저 본다 — cwd가 서브디렉터리인 호출에서 갈린다."""
        for var in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR"):
            with self.subTest(var=var), tempfile.TemporaryDirectory() as elsewhere:
                proc = subprocess.run(
                    [sys.executable, os.path.join(self.hooks, "manual-activate.py"), "claude-code"],
                    input=json.dumps({"cwd": elsewhere}),
                    capture_output=True,
                    text=True,
                    cwd=elsewhere,
                    env={**os.environ, var: self.root, "HOME": self.home.name},
                    timeout=30,
                )
                self.assertIn("규칙 하나", proc.stdout)


class TestFailOpen(ManualHookBase):
    def test_no_manual_is_silent(self):
        for payload in ({"source": "startup"}, {"agent_type": "asgard-worker"}):
            proc = self.hook(payload)
            self.assertEqual(proc.stdout.strip(), "")
            self.assertEqual(proc.returncode, 0)

    def test_broken_stdin_is_silent_and_passes(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(self.hooks, "manual-activate.py"), "claude-code"],
            input="not json at all",
            capture_output=True,
            text=True,
            cwd=self.root,
            env={**os.environ, "HOME": self.home.name},
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)

    def test_kill_switch_settings(self):
        self.write("MANUAL.md", "- 규칙")
        self.settings({"mode": "off"})
        self.assertEqual(self.hook({"source": "startup"}).stdout.strip(), "")

    def test_kill_switch_env_beats_settings(self):
        self.write("MANUAL.md", "- 규칙")
        self.settings({"mode": "off"})
        out = self.hook({"source": "startup"}, env_extra={"ASGARD_MANUAL": "on"}).stdout
        self.assertIn("규칙", out)

    def test_broken_settings_file_is_fail_open(self):
        self.write("MANUAL.md", "- 규칙")
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertIn("규칙", self.hook({"source": "startup"}).stdout)

    def test_empty_fragment_directory_does_not_kill_the_manual(self):
        self.write("MANUAL.md", "- 규칙")
        os.makedirs(os.path.join(self.root, ".asgard", "manual"), exist_ok=True)
        self.assertIn("규칙", self.hook({"source": "startup"}).stdout)

    def test_root_manual_dir_is_not_read(self):
        """루트 `manual/`은 남의 문서 폴더 자리다 — 훅도 정본과 똑같이 안 본다."""
        self.write("manual/10-docs.md", "- 남의 문서")
        self.assertEqual(self.hook({"source": "startup"}).stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
