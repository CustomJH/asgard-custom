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


def instruction_surfaces() -> list[tuple[str, str]]:
    """모델이 그대로 읽는 지침 표면 전부 — 렌더된 문장 기준."""
    from asgard.failures import GATE_MESSAGES
    from asgard.hooks.asgard_hooklib.transition import DISPATCH_HOW
    from asgard.hooks.subagent_gate import EVENT_ROLE, record_hint
    from asgard.templates import agents_md

    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "asgard")
    surfaces = [
        ("agents_md", agents_md("demo")),
        ("failures.py", "\n".join(GATE_MESSAGES.values())),
        # 매 턴 모델에게 도착하는 한 줄 — 배정된 역할을 어디에 세우는지는 여기서만 말한다.
        ("transition.DISPATCH_HOW", "\n".join(DISPATCH_HOW.values())),
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


class TestScaffoldParity(unittest.TestCase):
    def test_hook_table_is_one_table(self):
        """훅 표는 클라이언트별로 갈라지지 않는다 — CC 에만 깔리는 statusLine 스크립트만 예외.
        그 스크립트도 배선은 안 한다 (호스트 상태줄은 호스트 몫)."""
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
            # 닫혀 있는 것은 판정의 물리 대조가 못 보는 하네스 상태와, 이 가드의 뿌리를 정하는
            # 설정 파일 둘뿐이다. 나머지 스캐폴드는 diff 스냅샷 안이라 평범한 작업 대상이다.
            for target in (".asgard/state/x.json", ".claude/settings.json", ".claude/settings.local.json"):
                payload = {
                    "agent_type": "asgard-worker",  # 쓰기 권한 역할이어도 하네스 상태는 작업 대상이 아니다
                    "tool_name": "Write",
                    "tool_input": {"file_path": target},
                    "cwd": root,
                }
                self.assertEqual(_hook_payload("readonly_guard", payload, [])[0], 2, target)
                self.assertEqual(_hook_payload("readonly_guard", payload, ["codex"])[0], 2, target)
                code, out = _hook_payload("readonly_guard", payload, ["cursor"])
                self.assertEqual((code, json.loads(out)["permission"]), (0, "deny"), target)

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

    def test_no_host_wiring_carries_a_path_that_only_exists_on_this_machine(self):
        """세 호스트 배선 어디에도 스캐폴드를 만든 기계의 경로가 안 들어간다.

        배선 파일은 팀에 커밋돼 전달된다 (`commands/setup.py` 의 gitignore 블록). 거기 이 기계의
        uv 절대 경로가 박히면 저장소를 받은 다른 기계에서 훅 줄이 전부 exit 127 이 되고, 훅 계약이
        fail-open 이라 그 죽음은 조용하다. 그렇다고 맨 `uv` 도 못 적는다 — PATH 가
        `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄뿐인 프로세스(독·Finder·launchd)가 그것을 못 찾는다.
        배선은 저장소 안 런처를 부르고, 어느 uv 를 쓸지는 런처가 그 기계 위에서 정한다.

        재는 축이 양쪽이다: 기계별 경로가 **없다**와 런처를 **부른다**. 앞 축만 재면 배선이 통째로
        비어도 통과하고, 뒤 축만 재면 런처 뒤에 절대 경로가 따라붙어도 통과한다."""
        with mock.patch("asgard.platform.shutil.which", side_effect=lambda c: f"/opt/tools/{c}"):
            from asgard.platform import hook_python_argv, hook_python_token

            # 배선이 아니라 doctor 가 지금 여기서 한 번 돌려 보는 형태다 — 여기에는 절대 경로가 맞다.
            self.assertEqual(hook_python_argv(), ["/opt/tools/uv", "run", "--no-project", "python"])
            self.assertEqual(hook_python_token(), UV_HOOK_PYTHON)
            settings = json.loads(cc_settings())
            codex = codex_config()
            cursor = json.loads(cursor_hooks_json())
        # 환경 프리플라이트는 파이썬 없이 도는 sh 라 이 계약의 대상이 아니다 (templates/env.py).
        commands = [
            h["command"]
            for event in settings["hooks"].values()
            for e in event
            for h in e["hooks"]
            if "env-setup." not in h["command"]
        ]
        commands += [
            entry["command"]
            for event in cursor["hooks"].values()
            for entry in event
            if "env-setup." not in entry["command"]
        ]
        commands += [line for line in codex.splitlines() if "command = " in line and "env-setup." not in line]
        self.assertTrue(commands)
        self.assertEqual([], [c for c in commands if "/opt/tools/" in c], "배선에 이 기계의 경로가 실렸다")
        self.assertEqual([], [c for c in commands if "/asgard-python" not in c and not c.lstrip().startswith("# ")])
        allow = settings["permissions"]["allow"]
        self.assertIn(f"Bash({UV_HOOK_PYTHON} .claude/hooks/quest-log.py *)", allow)
        self.assertEqual([], [entry for entry in allow if "/opt/tools/" in entry])

    def test_a_resolved_interpreter_path_with_spaces_stays_one_argv_word(self):
        """`C:/Program Files/…` 는 낱말 하나다 — doctor 는 이 argv 를 셸 없이 그대로 실행한다."""
        from asgard.platform import hook_python_argv

        with mock.patch("asgard.platform.shutil.which", side_effect=lambda c: rf"C:\Program Files\{c}.exe"):
            argv = hook_python_argv()
        self.assertEqual(argv, ["C:/Program Files/uv.exe", "run", "--no-project", "python"])

    # 모델이 그대로 타이핑하는 명령이 실려 있는 표면 — 허용목록과 한 글자도 어긋나면 안 된다.
    # 훅 디렉토리 표기는 표면마다 다르다: 안내문은 `<hooks>`, 클라이언트별 배선은 실제 경로.
    ALLOWED_HEADS = tuple(
        f"{UV_HOOK_PYTHON} {folder}/" for folder in ("<hooks>", ".claude/hooks", ".cursor/hooks", ".codex/hooks")
    )

    def _instruction_surfaces(self) -> list[tuple[str, str]]:
        return instruction_surfaces()

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


class TestVerifierDispatchEscape(unittest.TestCase):
    """판정자 배차를 면제하는 탈출구는 도구가 없을 때만 열린다.

    Opus 5 세션의 기본 시스템 프롬프트에는 `Do not call the AgentTool unless the user requested it`
    이 들어 있다. 오딘이 건 설정이 아니라 Claude Code 실행 파일에서 오므로 이 저장소는 그것을
    못 고친다. 확인은 저장소 밖에서 한다 — `strings ~/.local/share/claude/versions/<버전> | grep
    "unless the user requested it"` 이 26-08-19 에 2.1.235 에서 그 문장을 냈다. 버전이 오르면
    사라질 수도 있다. 이 시험이 걸리면 문구부터 다시 재라.

    그 문장은 서브에이전트를 주면서 부르지 말라고 한다. 이 저장소의 탈출구는 전부 "호스트가
    서브에이전트를 안 준다"를 조건으로 쓴다. 둘을 구분하는 절이 탈출구 옆에 없으면 모델이 기본
    지시를 도구 부재로 읽는다. 26-08-19 에 두 번 샜다. 벤치 회차 하나는 그 문장을 인용하며
    `"mode":"A-fallback"` 을 자칭했다. 그러고는 자기 diff 를 자기가 PASS 로 적었다. 다른 세션은
    배차는 했지만 없는 충돌을 오딘에게 보고했다."""

    # 탈출구를 여는 말 셋. 어느 표면에 나타나든 구분절이 같은 창 안에 있어야 한다.
    ESCAPE = re.compile(r"no subagent tool at all|mode A fallback|verifier_independence=false")
    DISTINCTION = re.compile(r"unless the user asked is not that")
    WINDOW = 400  # 문장 경계를 세는 대신 근접 창으로 본다 — 표면마다 문단 모양이 다르다

    def test_every_escape_clause_rules_out_a_host_default(self):
        offenders = []
        for rel, text in instruction_surfaces():
            for match in self.ESCAPE.finditer(text):
                near = text[max(0, match.start() - self.WINDOW) : match.end() + self.WINDOW]
                if not self.DISTINCTION.search(near):
                    quote = text[max(0, match.start() - 70) : match.end() + 70]
                    offenders.append(f"{rel}: …{' '.join(quote.split())}…")
        self.assertEqual(offenders, [], "탈출구 옆에 구분절이 없다:\n" + "\n".join(offenders))

    def test_the_distinction_is_worded_the_same_way_everywhere(self):
        """표지가 표면마다 다르면 위 검사가 조용히 반만 돈다."""
        carrying = [rel for rel, text in instruction_surfaces() if self.DISTINCTION.search(text)]
        self.assertEqual(
            sorted(carrying),
            ["agents_md", "failures.py", "hooks/verifier_gate.py", "transition.DISPATCH_HOW"],
        )


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
    @staticmethod
    def _lay_down(root: str) -> None:
        """sync 가 하는 것과 같게 — 패키지본을 바이트 그대로 복사한다.

        빈 파일을 두면 판본 검사가 정당하게 뒤처짐으로 잡는다: 이름이 같다고 같은 파일이 아니다."""
        import shutil

        from asgard import hooks as _hooks

        source_dir = os.path.dirname(_hooks.__file__)
        for folder in (".claude", ".cursor"):
            os.makedirs(os.path.join(root, folder, "hooks"), exist_ok=True)
            for name in _PARITY_HOOKS:
                source = os.path.join(source_dir, name.replace("-", "_"))
                target = os.path.join(root, folder, "hooks", name)
                if name.endswith(".py") and os.path.isfile(source):
                    shutil.copy2(source, target)
                else:
                    open(target, "w").close()
        with open(os.path.join(root, ".claude", "settings.json"), "w", encoding="utf-8") as handle:
            handle.write(cc_settings())
        with open(os.path.join(root, ".cursor", "hooks.json"), "w", encoding="utf-8") as handle:
            handle.write(cursor_hooks_json())

    def test_missing_hook_in_one_client_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            self._lay_down(root)
            os.remove(os.path.join(root, ".cursor", "hooks", "craft-gate.py"))
            checks = {check["name"]: check for check in _mode_parity_check(root)}
            self.assertTrue(checks["mode parity (CC)"]["ok"], checks["mode parity (CC)"]["detail"])
            self.assertFalse(checks["mode parity (Cursor)"]["ok"])
            self.assertIn("craft-gate.py", checks["mode parity (Cursor)"]["detail"])
            self.assertNotIn("mode parity (Codex)", checks)  # 미설치 클라이언트는 진단 대상이 아니다

    def test_a_deployed_copy_that_fell_behind_is_reported(self):
        """이름과 배선만 보던 판은 판본 드리프트를 통째로 못 봤다.

        배포된 `quest-log.py` 가 패키지본보다 50줄 뒤처져 같은 저장소에서 네이티브와 Claude
        Code 가 서로 다른 베이스라인을 검출하고 있었는데, doctor 는 "동일 규율 배선"이라고
        적었다 (26-08-05 감사)."""
        with tempfile.TemporaryDirectory() as root:
            self._lay_down(root)
            with open(os.path.join(root, ".claude", "hooks", "quest-log.py"), "a", encoding="utf-8") as handle:
                handle.write("\n# 예전 판에는 없던 줄\n")
            checks = {check["name"]: check for check in _mode_parity_check(root)}
            self.assertFalse(checks["mode parity (CC)"]["ok"])
            self.assertIn("quest-log.py", checks["mode parity (CC)"]["detail"])
            self.assertIn("판본 뒤처짐", checks["mode parity (CC)"]["detail"])
            self.assertTrue(checks["mode parity (Cursor)"]["ok"], checks["mode parity (Cursor)"]["detail"])


if __name__ == "__main__":
    unittest.main()
