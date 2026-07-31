"""모드 패리티 — 세 클라이언트(Claude Code·Cursor·Codex)와 네이티브가 같은 규율을 지는가.

한 모드에만 있는 게이트는 기능이 아니라 드리프트다: 사용자가 도구를 바꾸는 순간 조용히 사라진다.
여기서 보는 것은 세 가지다 — 같은 훅 표가 깔리는가, 그 훅이 각 클라이언트 설정에 배선되는가,
그리고 훅 자신이 클라이언트별 프로토콜(차단 응답·컨텍스트 주입)을 낼 줄 아는가.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from asgard.commands.doctor import _PARITY_HOOKS, _mode_parity_check
from asgard.commands.setup import hook_files, plan_files
from asgard.templates import cc_settings, codex_config, cursor_hooks_json

# 세 모드에 같은 규율로 서야 하는 계층 — 훅 이름이 곧 계약이다.
DISCIPLINES = (
    "readonly-guard",
    "secret-guard",
    "unattended-context",
    "craft-gate",
    "budget-guard",
    "charter-activate",
    "manual-activate",
    "agent-activate",
    "lagom-activate",
    "lagom-tracker",
    "lagom-subagent",
    "memory-activate",
    "map-activate",
    "verifier-gate",
    "subagent-gate",
    "write-sentinel",
    "tutor-note",
    "git-guard",
    "release-guard",
    "failure-tracker",
)


def _hook_payload(script: str, payload: dict, argv: list[str]) -> tuple[int, str]:
    """훅을 in-process로 돌린 (exit code, stdout) — 스캐폴드 없이 소스 자체를 판정한다."""
    import importlib

    module = importlib.import_module("asgard.hooks." + script)
    out = io.StringIO()
    with (
        mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
        mock.patch("sys.stdout", out),
        mock.patch("sys.argv", ["hook", *argv]),
    ):
        try:
            module.main()
        except SystemExit as exc:
            return int(exc.code or 0), out.getvalue()
    return 0, out.getvalue()


class TestScaffoldParity(unittest.TestCase):
    def test_hook_table_is_one_table(self):
        """훅 표는 클라이언트별로 갈라지지 않는다 — CC statusLine만 예외."""
        cc = {os.path.basename(p) for p, _ in hook_files("/h", "claude-code")}
        cursor = {os.path.basename(p) for p, _ in hook_files("/h", "cursor")}
        codex = {os.path.basename(p) for p, _ in hook_files("/h", "codex")}
        self.assertEqual(cursor, codex)
        self.assertEqual(cc - cursor, {"lagom-statusline.sh"})

    def test_every_client_gets_every_parity_hook(self):
        with (
            mock.patch("asgard.templates.agent_models.load_global", return_value={}),
            mock.patch("asgard.templates.agent_models.load_project", return_value={}),
        ):
            files = {path for path, _ in plan_files(cc=True, cursor=True, codex=True, root="/workspace")[0]}
        for folder in (".claude", ".cursor", ".codex"):
            for name in _PARITY_HOOKS:
                self.assertIn(f"/workspace/{folder}/hooks/{name}", files, f"{folder} 에 {name} 없음")

    def test_every_client_config_wires_every_discipline(self):
        configs = {
            "claude-code": cc_settings(),
            "cursor": cursor_hooks_json(),
            "codex": codex_config(),
        }
        for client, text in configs.items():
            for name in DISCIPLINES:
                self.assertIn(name, text, f"{client} 설정에 {name} 미배선")

    def test_codex_config_parses(self):
        import tomllib

        config = tomllib.loads(codex_config())
        events = config["hooks"]
        self.assertIn("craft-gate", json.dumps(events["SubagentStop"]))
        self.assertIn("unattended-context", json.dumps(events["UserPromptSubmit"]))
        self.assertIn("secret-guard", json.dumps(events["PreToolUse"]))

    def test_cursor_injection_rides_session_start(self):
        """Cursor의 beforeSubmitPrompt는 컨텍스트 주입 통로가 없다 — 주입은 sessionStart에 선다."""
        hooks = json.loads(cursor_hooks_json())["hooks"]
        session = json.dumps(hooks["sessionStart"])
        for name in ("lagom-activate", "charter-activate", "unattended-context", "memory-activate"):
            self.assertIn(name, session)
        self.assertIn("craft-gate", json.dumps(hooks["subagentStop"]))
        self.assertIn("secret-guard", json.dumps(hooks["preToolUse"]))


class TestHookProtocolParity(unittest.TestCase):
    SECRET = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "AKIAABCDEFGHIJKLMNOP"}}

    def test_secret_guard_blocks_in_every_mode(self):
        code, out = _hook_payload("secret_guard", self.SECRET, [])
        self.assertEqual(code, 2)  # Claude Code
        code, out = _hook_payload("secret_guard", self.SECRET, ["codex"])
        self.assertEqual(code, 2)
        code, out = _hook_payload("secret_guard", self.SECRET, ["cursor"])
        self.assertEqual(code, 0)  # Cursor는 exit이 아니라 permission JSON이 차단 신호
        self.assertEqual(json.loads(out)["permission"], "deny")
        self.assertIn("user_message", out)  # snake_case — cursor.com/docs/hooks

    def test_secret_guard_allows_clean_write_with_explicit_cursor_allow(self):
        clean = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "x = 1"}}
        self.assertEqual(_hook_payload("secret_guard", clean, [])[0], 0)
        code, out = _hook_payload("secret_guard", clean, ["cursor"])
        self.assertEqual((code, json.loads(out)["permission"]), (0, "allow"))

    def test_control_surface_is_protected_in_every_mode(self):
        with tempfile.TemporaryDirectory() as root:
            for folder in (".claude", ".cursor", ".codex", ".agents", ".asgard"):
                payload = {
                    "agent_type": "asgard-worker",  # 쓰기 권한 역할이어도 통제 표면은 작업 대상이 아니다
                    "tool_name": "Write",
                    "tool_input": {"file_path": f"{folder}/hooks/x.py"},
                    "cwd": root,
                }
                self.assertEqual(_hook_payload("readonly_guard", payload, [])[0], 2, folder)
                self.assertEqual(_hook_payload("readonly_guard", payload, ["codex"])[0], 2, folder)
                code, out = _hook_payload("readonly_guard", payload, ["cursor"])
                self.assertEqual((code, json.loads(out)["permission"]), (0, "deny"), folder)

    def test_readonly_roles_are_blocked_in_every_mode(self):
        with tempfile.TemporaryDirectory() as root:
            payload = {
                "agent_type": "asgard-verifier",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/x.py"},
                "cwd": root,
            }
            self.assertEqual(_hook_payload("readonly_guard", payload, [])[0], 2)
            self.assertEqual(_hook_payload("readonly_guard", payload, ["codex"])[0], 2)
            self.assertEqual(json.loads(_hook_payload("readonly_guard", payload, ["cursor"])[1])["permission"], "deny")

    def test_main_session_write_is_allowed_identically_in_every_mode(self):
        """MAIN_WORKER — 메인 세션이 배정된 역할을 직접 수행하는 자리. 세 모드 판정이 같아야 한다.

        Cursor·Codex의 도구 훅엔 역할 신원 자체가 없다(agent_type 부재). 신원 부재를 읽기전용으로
        읽으면 그 두 모드에선 Worker의 쓰기까지 전부 막히고, CC 에선 subagent-gate가 유닛 마커
        없는 Worker 디스패치를 거부해 우회로도 없다 — 양쪽 차단은 교착이다."""
        with tempfile.TemporaryDirectory() as root:
            payload = {"tool_name": "Write", "tool_input": {"file_path": "src/x.py"}, "cwd": root}
            self.assertEqual(_hook_payload("readonly_guard", payload, [])[0], 0)
            self.assertEqual(_hook_payload("readonly_guard", payload, ["codex"])[0], 0)
            code, out = _hook_payload("readonly_guard", payload, ["cursor"])
            self.assertEqual((code, json.loads(out)["permission"]), (0, "allow"))

    def test_context_injection_speaks_each_client_schema(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".asgard"))
            with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
                json.dump({"charter": {"through_line": "북극성", "coherence": ["c1"]}}, handle, ensure_ascii=False)
            payload = {"cwd": root}
            self.assertIn("[charter]", _hook_payload("charter_activate", payload, ["claude-code"])[1])
            cursor_out = json.loads(_hook_payload("charter_activate", payload, ["cursor"])[1])
            self.assertIn("[charter]", cursor_out["additional_context"])
            sub = {**payload, "agent_type": "asgard-thinker"}
            codex_out = json.loads(_hook_payload("charter_activate", sub, ["codex"])[1])
            self.assertEqual(codex_out["hookSpecificOutput"]["hookEventName"], "SubagentStart")

    def test_unattended_contract_reaches_every_mode(self):
        payload = {"permission_mode": "bypassPermissions"}
        self.assertIn("Canon 8", _hook_payload("unattended_context", payload, ["claude-code"])[1])
        self.assertIn(
            "Canon 8", json.loads(_hook_payload("unattended_context", payload, ["cursor"])[1])["additional_context"]
        )
        codex = json.loads(_hook_payload("unattended_context", payload, ["codex"])[1])
        self.assertIn("Canon 8", codex["hookSpecificOutput"]["additionalContext"])

    def test_quest_bookkeeping_is_allowed_from_every_client_hook_dir(self):
        """읽기전용 레인의 퀘스트 기장 허용은 훅이 사는 디렉토리와 무관해야 한다."""
        from asgard.hooks.readonly_guard import is_readonly_bash_safe

        for folder in (".claude", ".cursor", ".codex"):
            self.assertTrue(is_readonly_bash_safe(f"python3 {folder}/hooks/quest-log.py open q --criteria x"))


class TestNativeParity(unittest.TestCase):
    def test_unattended_note_follows_the_env_signal(self):
        from asgard.agent.heimdall.roles import unattended_note

        with mock.patch.dict(os.environ, {"ASGARD_UNATTENDED": "1"}):
            self.assertIn("Canon 8", unattended_note())
        with mock.patch.dict(os.environ, {"ASGARD_UNATTENDED": "0"}):
            self.assertEqual(unattended_note(), "")

    def test_native_shape_ratchet_shares_the_hook_budget(self):
        from asgard.agent.heimdall.trinity import _CRAFT_MAX_BLOCKS, _craft_blocking
        from asgard.hooks import craft_gate

        self.assertEqual(_CRAFT_MAX_BLOCKS, craft_gate.MAX_BLOCKS)
        self.assertEqual(_craft_blocking(os.getcwd(), []), [])  # 대상 없음 = 판정 없음

    def test_native_shape_ratchet_reports_both_gates(self):
        """craft(예산)와 thor gate(정확성)를 따로 부른다 — 한쪽 고장이 다른 쪽을 삼키지 않게."""
        from asgard.agent.heimdall import trinity

        class _Report:
            def __init__(self, blocking):
                self.blocking = blocking

        from dataclasses import dataclass

        @dataclass
        class _Finding:
            rule: str
            path: str
            line: int
            detail: str
            fix: str
            unit: str = ""

        finding = _Finding("unit-oversize", "a.py", 1, "too long", "split")
        with (
            mock.patch("asgard.craft.judge", return_value=_Report([finding])),
            mock.patch("asgard.thor_gate.judge", side_effect=RuntimeError("gate down")),
        ):
            out = trinity._craft_blocking("/root", ["a.py"])
        self.assertEqual([row["gate"] for row in out], ["craft"])


class TestDoctorParityCheck(unittest.TestCase):
    def test_missing_hook_in_one_client_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            for folder in (".claude", ".cursor"):
                os.makedirs(os.path.join(root, folder, "hooks"))
                for name in _PARITY_HOOKS:
                    with open(os.path.join(root, folder, "hooks", name), "w"):
                        pass
            with open(os.path.join(root, ".claude", "settings.json"), "w", encoding="utf-8") as handle:
                handle.write(cc_settings())
            with open(os.path.join(root, ".cursor", "hooks.json"), "w", encoding="utf-8") as handle:
                handle.write(cursor_hooks_json())
            os.remove(os.path.join(root, ".cursor", "hooks", "craft-gate.py"))
            checks = {check["name"]: check for check in _mode_parity_check(root)}
            self.assertTrue(checks["mode parity (CC)"]["ok"])
            self.assertFalse(checks["mode parity (Cursor)"]["ok"])
            self.assertIn("craft-gate.py", checks["mode parity (Cursor)"]["detail"])
            self.assertNotIn("mode parity (Codex)", checks)  # 미설치 클라이언트는 진단 대상이 아니다


if __name__ == "__main__":
    unittest.main()
