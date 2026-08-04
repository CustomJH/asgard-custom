"""모드 패리티 — 세 클라이언트(Claude Code·Cursor·Codex)와 네이티브가 같은 규율을 지는가.

한 모드에만 있는 게이트는 기능이 아니라 드리프트다: 사용자가 도구를 바꾸는 순간 조용히 사라진다.
여기서 보는 것은 세 가지다 — 같은 훅 표가 깔리는가, 그 훅이 각 클라이언트 설정에 배선되는가,
그리고 훅 자신이 클라이언트별 프로토콜(차단 응답·컨텍스트 주입)을 낼 줄 아는가.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from asgard.commands.doctor import _PARITY_HOOKS, _mode_parity_check
from asgard.commands.setup import hook_files, plan_files
from asgard.platform import UV_HOOK_PYTHON
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
            self.assertTrue(is_readonly_bash_safe(f"{UV_HOOK_PYTHON} {folder}/hooks/quest-log.py open q --criteria x"))


class TestCanonicalHookPython(unittest.TestCase):
    """훅 인터프리터 토큰은 배포되는 모든 표면에서 하나여야 한다.

    안내문이 시키는 명령과 권한 허용목록에 적힌 명령이 다르면 헤드리스(-p) 세션에서 모델이
    적힌 대로 친 명령이 자동 거부되고, 퀘스트 로그가 안 열려 게이트가 조용히 죽는다. 여기서
    고정하는 것은 넷이다 — (1) 안내문에 맨 `python3 …/quest-log.py`가 남아 있지 않다,
    (2) 허용목록 토큰 == 안내문 토큰, (3) 배선은 절대 경로·허용목록은 맨 토큰,
    (4) 시키는 명령이 허용목록 프리픽스에 그대로 걸린다."""

    # 안내문이 그대로 시키는 표면들 — 모델이 이 문장을 읽고 그대로 친다.
    PROSE_SURFACES = (
        "templates/agents.py",
        "templates/selftest.py",
        "templates/roles/asgard-worker.md",
        "templates/roles/asgard-thinker.md",
        "templates/roles/asgard-verifier.md",
        "failures.py",
        "hooks/verifier_gate.py",
        "hooks/subagent_gate.py",
    )
    # 맨 python3 로 quest-log 를 부르는 형태 (셸 변수·경로 표기 차이를 포괄).
    BARE = re.compile(r"python3\s+\S*quest-log\.py")

    def test_no_shipped_surface_tells_the_model_to_type_bare_python3(self):
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "asgard")
        offenders = []
        for rel in self.PROSE_SURFACES:
            path = os.path.join(src, rel)
            with open(path, encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, 1):
                    if self.BARE.search(line):
                        offenders.append(f"{rel}:{lineno}")
        self.assertEqual(
            offenders,
            [],
            "맨 python3 로 quest-log 를 부르라고 적힌 자리 — 시스템 python3 는 없을 수 있다 "
            f"(정본: {UV_HOOK_PYTHON}):\n" + "\n".join(offenders),
        )

    def test_allowlist_token_equals_the_prose_token(self):
        """허용목록의 quest-log 항목이 안내문 토큰을 반드시 담는다.

        안내문은 정적이라 언제나 uv 정본을 적는다. 이 기계의 hook_python()이 폴백을 골랐더라도
        허용목록에는 정본 토큰이 함께 실려야 한다 — 안 그러면 그 기계에서만 게이트가 죽는다."""
        allow = json.loads(cc_settings())["permissions"]["allow"]
        self.assertIn(f"Bash({UV_HOOK_PYTHON} .claude/hooks/quest-log.py *)", allow)
        with mock.patch("asgard.templates.claude.hook_python_token", return_value="py"):
            fallback = json.loads(cc_settings())["permissions"]["allow"]
        self.assertIn(f"Bash({UV_HOOK_PYTHON} .claude/hooks/quest-log.py *)", fallback)
        self.assertIn("Bash(py .claude/hooks/quest-log.py *)", fallback)

    def test_agents_md_and_gate_messages_use_the_same_token(self):
        """AGENTS.md 안내문과 게이트 차단문이 같은 토큰을 쓴다 — 차단이 가르치는 명령이 곧 정본."""
        from asgard.failures import GATE_MESSAGES
        from asgard.templates import agents_md

        self.assertIn(f"{UV_HOOK_PYTHON} <hooks>/quest-log.py open", agents_md("demo"))
        self.assertIn(f"{UV_HOOK_PYTHON} <hooks>/quest-log.py open", GATE_MESSAGES["orphan-write"])

    def test_wiring_carries_an_absolute_path_and_the_allowlist_carries_the_bare_token(self):
        """배선은 절대 경로, 허용목록·안내문은 맨 토큰 — 두 표면이 요구하는 것이 서로 다르다.

        맨 `uv` 를 배선하면 PATH 가 `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄뿐인 프로세스(독·
        Finder·launchd)에서 훅 줄이 전부 exit 127 이 되고, fail-open 계약이라 조용하다. 반대로
        허용목록에 기계별 절대 경로를 담으면 안내문이 시키는 명령과 어긋나 자동 거부된다."""
        with mock.patch("asgard.platform.shutil.which", side_effect=lambda c: f"/opt/tools/{c}"):
            from asgard.platform import hook_python, hook_python_argv, hook_python_token

            self.assertEqual(hook_python(), "/opt/tools/uv run --no-project python")
            self.assertEqual(hook_python_argv(), ["/opt/tools/uv", "run", "--no-project", "python"])
            self.assertEqual(hook_python_token(), UV_HOOK_PYTHON)
            settings = json.loads(cc_settings())
        commands = [h["command"] for event in settings["hooks"].values() for e in event for h in e["hooks"]]
        self.assertTrue(commands and all(c.startswith("/opt/tools/uv run --no-project python ") for c in commands))
        allow = settings["permissions"]["allow"]
        self.assertIn(f"Bash({UV_HOOK_PYTHON} .claude/hooks/quest-log.py *)", allow)
        self.assertEqual([], [entry for entry in allow if "/opt/tools/" in entry])

    def test_a_wiring_path_with_spaces_stays_one_shell_word(self):
        """공백이 든 경로(Windows 의 `C:/Program Files/…`)는 따옴표 없이는 두 낱말로 쪼개진다."""
        import shlex

        from asgard.platform import hook_python

        with mock.patch("asgard.platform.shutil.which", side_effect=lambda c: rf"C:\Program Files\{c}.exe"):
            command = hook_python()
        self.assertEqual(command, '"C:/Program Files/uv.exe" run --no-project python')
        self.assertEqual(shlex.split(command), ["C:/Program Files/uv.exe", "run", "--no-project", "python"])

    # 모델이 그대로 타이핑하는 명령이 실려 있는 표면 — 허용목록과 한 글자도 어긋나면 안 된다.
    # 훅 디렉토리 표기는 표면마다 다르다: 안내문은 `<hooks>`, 클라이언트별 배선은 실제 경로.
    ALLOWED_HEADS = tuple(
        f"{UV_HOOK_PYTHON} {folder}/" for folder in ("<hooks>", ".claude/hooks", ".cursor/hooks", ".codex/hooks")
    )

    def _instruction_surfaces(self) -> list[tuple[str, str]]:
        from asgard.failures import GATE_MESSAGES
        from asgard.hooks.subagent_gate import EVENT_ROLE, record_hint
        from asgard.templates import agents_md

        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "asgard")
        surfaces = [
            ("agents_md", agents_md("demo")),
            ("failures.py", "\n".join(GATE_MESSAGES.values())),
            # 렌더된 문장으로 본다 — 이 명령은 훅 디렉토리를 런타임에 채운다.
            ("subagent_gate.record_hint", "\n".join(record_hint(".claude/hooks", e) for e in EVENT_ROLE)),
        ]
        for rel in ("hooks/verifier_gate.py",) + tuple(
            f"templates/roles/asgard-{role}.md" for role in ("worker", "thinker", "verifier")
        ):
            with open(os.path.join(src, rel), encoding="utf-8") as handle:
                text = handle.read()
            # 파이썬 소스는 문자열 이어붙이기 이음매를 지운다 — 렌더된 문장 기준으로 봐야
            # `… | ` 와 `uv run …` 이 두 줄에 걸쳐 나뉘어 파이프라인이 안 보이는 일이 없다.
            surfaces.append((rel, re.sub(r"['\"]\s*\n\s*['\"]", "", text) if rel.endswith(".py") else text))
        return surfaces

    def test_every_instructed_quest_log_command_matches_the_allowlist(self):
        """시키는 명령이 허용목록 프리픽스에 그대로 걸려야 한다 — 안 걸리면 헤드리스 교착이다.

        호스트의 Bash 규칙은 원문 문자열 프리픽스로 맞추고 셸 연산자를 알아본다. 그래서
        `$CLAUDE_PROJECT_DIR/...` 절대 형태는 상대 경로 항목과 한 글자도 안 겹치고, 파이프라인은
        앞 세그먼트(`echo`)까지 허용목록을 요구한다. 둘 다 결과가 같다 — 헤드리스(-p)에서 자동
        거부 → 역할이 이벤트를 못 남김 → subagent-gate 가 종료를 다시 차단 → 교착."""
        self.assertIn(
            f"Bash({UV_HOOK_PYTHON} .claude/hooks/quest-log.py *)",
            json.loads(cc_settings())["permissions"]["allow"],
        )
        offenders = []
        for rel, text in self._instruction_surfaces():
            for match in re.finditer(r"quest-log\.py", text):
                head = text[: match.start()]
                if "python" not in head[-60:]:
                    continue  # 도구 이름 언급이지 타이핑할 명령이 아니다
                matched = next((allowed for allowed in self.ALLOWED_HEADS if head.endswith(allowed)), None)
                if not matched:
                    offenders.append(f"{rel}: …{head[-60:]}quest-log.py — 허용목록 프리픽스가 아니다")
                elif head[: -len(matched)].rstrip().endswith(("|", "&", ";")):
                    offenders.append(f"{rel}: …{head[-80:]}quest-log.py — 복합 명령의 뒷 세그먼트다")
        self.assertEqual(offenders, [], "허용목록과 어긋나는 지시 명령:\n" + "\n".join(offenders))


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
