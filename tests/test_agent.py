#!/usr/bin/env python3
"""네이티브 에이전트 루프 결정론 슬라이스 (CUS-137/142) — API 호출 없는 부분 전부.

툴 계약(text_editor/bash)·경로 격리·git-guard 배선·퀘스트 로그 래퍼(ql/gate)·delegate 이벤트·
write-sentinel 미러. 라이브 루프(실 모델)는 tests/e2e_trinity.sh 의 start 아암(CUS-140) 몫.

실행: uv run pytest tests/test_agent.py  (asgard 패키지 임포트 필요 — subprocess 가 -m 으로 훅 실행)
"""

import json
import os
import subprocess
import tempfile
import unittest

from asgard.agent import tools as T
from asgard.agent.heimdall import _record_writes
from asgard.agent.session import gate, ql


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

        def run(*a):
            return subprocess.run(a, cwd=self.root, capture_output=True, check=True)

        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        open(os.path.join(self.root, "f.txt"), "w").write("base\n")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "init")

    def tearDown(self):
        self._tmp.cleanup()


class TestEditor(Base):
    def test_create_view_roundtrip(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": "a/b.py", "file_text": "x = 1\n"}, w)
        self.assertEqual(w, [os.path.join("a", "b.py")])
        out = T.run_editor(self.root, {"command": "view", "path": "a/b.py"}, [])
        self.assertIn("x = 1", out)

    def test_str_replace_requires_exactly_one_match(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": "c.txt", "file_text": "aa\naa\n"}, w)
        with self.assertRaises(T.ToolError):  # 2회 매치
            T.run_editor(self.root, {"command": "str_replace", "path": "c.txt", "old_str": "aa", "new_str": "bb"}, w)
        T.run_editor(self.root, {"command": "str_replace", "path": "c.txt", "old_str": "aa\naa", "new_str": "bb"}, w)
        self.assertEqual(open(os.path.join(self.root, "c.txt")).read(), "bb\n")

    def test_path_escape_rejected(self):
        for bad in ("../evil.txt", "/etc/passwd", "a/../../evil"):
            with self.assertRaises(T.ToolError, msg=bad):
                T.run_editor(self.root, {"command": "create", "path": bad, "file_text": "x"}, [])

    def test_insert_bounds(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": "d.txt", "file_text": "1\n2\n"}, w)
        T.run_editor(self.root, {"command": "insert", "path": "d.txt", "insert_line": 1, "insert_text": "x"}, w)
        self.assertEqual(open(os.path.join(self.root, "d.txt")).read(), "1\nx\n2\n")
        with self.assertRaises(T.ToolError):
            T.run_editor(self.root, {"command": "insert", "path": "d.txt", "insert_line": 99, "insert_text": "x"}, w)


class TestBash(Base):
    def test_runs_and_captures_exit(self):
        out, code = T.run_bash(self.root, {"command": "echo hi"})
        self.assertEqual((out, code), ("hi", 0))

    def test_git_guard_blocks_force_push(self):
        with self.assertRaises(T.ToolError):
            T.run_bash(self.root, {"command": "git push --force origin main"})

    def test_restart_is_ack(self):
        out, code = T.run_bash(self.root, {"restart": True})
        self.assertEqual(code, 0)


class TestLedgerWiring(Base):
    """네이티브 루프가 쓰는 subprocess 계약 — 훅을 배포 형태 그대로."""

    def test_full_cycle_gate_pass(self):
        sid = "native-t1"
        self.assertEqual(ql(self.root, "open", "q1", "--criteria", "c", session=sid).returncode, 0)
        open(os.path.join(self.root, "f.txt"), "a").write("more\n")
        _record_writes(self.root, sid, ["f.txt"])
        ql(
            self.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "work",
                    "changed_files": ["f.txt"],
                    "commands": [{"cmd": "true", "exit_code": 0}],
                }
            ),
        )
        ql(
            self.root,
            "append",
            "--verdict",
            "PASS",
            "--level",
            "micro",
            session=sid,
            stdin=json.dumps({"role": "verifier", "event": "verify", "commands": [{"cmd": "true", "exit_code": 0}]}),
        )
        blocked, _ = gate(self.root, sid)
        self.assertFalse(blocked)
        self.assertEqual(ql(self.root, "close", session=sid).returncode, 0)

    def test_gate_blocks_unverified_write(self):
        sid = "native-t2"
        ql(self.root, "open", "q2", "--criteria", "c", session=sid)
        open(os.path.join(self.root, "f.txt"), "a").write("tamper\n")
        _record_writes(self.root, sid, ["f.txt"])
        blocked, reason = gate(self.root, sid)
        self.assertTrue(blocked)
        self.assertIn("PASS", reason)

    def test_delegate_event_accepted(self):
        sid = "native-t3"
        ql(self.root, "open", "q3", "--criteria", "c", session=sid)
        p = ql(
            self.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "delegate",
                    "commands": [{"cmd": "dispatch:freyja — 프론트 전담", "exit_code": 0}],
                }
            ),
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        log = open(os.path.join(self.root, ".asgard", "quest", "q3.jsonl")).read()
        self.assertIn('"delegate"', log)

    def test_record_writes_merges(self):
        _record_writes(self.root, "s", ["a.py"])
        _record_writes(self.root, "s", ["a.py", "b.py"])
        data = json.load(open(os.path.join(self.root, ".asgard", "writes-s.json")))
        self.assertEqual(data, ["a.py", "b.py"])


class TestRoleProviders(Base):
    """[trinity.<role>] 역할별 provider 배치 — Trinity 모델 융합 축 (API 호출 없음)."""

    def setUp(self):
        super().setUp()
        self._home = os.environ.get("HOME")  # 글로벌 ~/.asgard/config.toml 오염 차단
        os.environ["HOME"] = self.root

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        super().tearDown()

    def _default(self):
        from asgard.providers import PROVIDERS, ResolvedProvider

        return ResolvedProvider(profile=PROVIDERS["anthropic"], model="claude-x", api_key="k")

    def _write_config(self, body: str):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(body)

    def test_no_config_all_roles_default(self):
        from asgard.providers import resolve_trinity

        default = self._default()
        m = resolve_trinity(self.root, default)
        self.assertEqual(sorted(m), ["thinker", "verifier", "worker"])
        self.assertTrue(all(rp is default for rp in m.values()))

    def test_role_section_places_provider(self):
        from asgard.providers import resolve_trinity

        self._write_config('[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n')
        default = self._default()
        m = resolve_trinity(self.root, default)
        self.assertIs(m["thinker"], default)
        self.assertEqual(m["worker"].profile.name, "ollama")
        self.assertEqual(m["worker"].model, "m1")
        self.assertEqual(m["worker"].missing, [])  # ollama 는 keyless — 배치 즉시 유효

    def test_heimdall_session_routes_by_role(self):
        from asgard.agent.heimdall import Heimdall

        self._write_config('[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n')
        h = Heimdall(self._default(), self.root, on_text=lambda s: None)
        self.assertEqual(h._session("sys", role="worker").rp.profile.name, "ollama")
        self.assertEqual(h._session("sys", role="thinker").rp.profile.name, "anthropic")
        self.assertEqual(h._session("sys").rp.profile.name, "anthropic")  # 딜리버리/DIRECT = 기본

    def test_heimdall_missing_role_falls_back(self):
        from asgard.agent.heimdall import Heimdall

        # openai_compat 는 base_url·키 필수 — 미충족이면 경고 + 기본 provider 폴백
        self._write_config('[trinity.verifier]\nprovider = "openai_compat"\nmodel = "m2"\n')
        warns = []
        h = Heimdall(self._default(), self.root, on_text=warns.append)
        self.assertEqual(h._session("sys", role="verifier").rp.profile.name, "anthropic")
        self.assertTrue(any("trinity.verifier" in w for w in warns))

    def test_save_config_section_roundtrip_preserves_others(self):
        from asgard.providers import project_section, save_config_section

        self._write_config('[provider]\nname = "anthropic"\n')
        save_config_section(self.root, "trinity.worker", {"provider": "ollama", "model": "m1"})
        save_config_section(self.root, "bridge", {"claude-code": True, "codex": False})
        txt = open(os.path.join(self.root, ".asgard", "config.toml")).read()
        self.assertIn("[provider]", txt)  # 기존 섹션 보존
        self.assertEqual(project_section(self.root, "trinity"), {"worker": {"provider": "ollama", "model": "m1"}})
        self.assertEqual(project_section(self.root, "bridge"), {"claude-code": True, "codex": False})
        # 섹션 교체 (중복 없이) + 제거
        save_config_section(self.root, "trinity.worker", {"provider": "nvidia"})
        self.assertEqual(project_section(self.root, "trinity"), {"worker": {"provider": "nvidia"}})
        save_config_section(self.root, "trinity.worker", None)
        self.assertEqual(project_section(self.root, "trinity"), {})
        self.assertIn("[provider]", open(os.path.join(self.root, ".asgard", "config.toml")).read())

    def test_bridge_flags_default_off_and_config(self):
        from asgard.providers import bridge_flags

        self.assertEqual(bridge_flags(self.root), {"claude-code": False, "codex": False, "cursor": False})
        self._write_config("[bridge]\nclaude-code = true\ncursor = true\n")
        flags = bridge_flags(self.root)
        self.assertTrue(flags["claude-code"] and flags["cursor"])
        self.assertFalse(flags["codex"])

    def test_role_list_reports_placements(self):
        import contextlib
        import io

        from asgard.commands.role import run_role_list

        self._write_config('[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n[bridge]\ncodex = true\n')
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(run_role_list(), 0)
        finally:
            os.chdir(cwd)
        out = json.loads(buf.getvalue())
        self.assertTrue(out["bridge"]["codex"])
        self.assertTrue(out["roles"]["worker"]["placed"])
        self.assertEqual(out["roles"]["worker"]["provider"], "ollama")
        self.assertFalse(out["roles"]["thinker"]["placed"])

    def test_role_run_rejects_bad_role_and_no_quest(self):
        from asgard.commands.role import run_role_run

        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(run_role_run("odin", "t"), 2)  # 미지의 역할
            self.assertEqual(run_role_run("worker", "t"), 1)  # 활성 quest 없음
        finally:
            os.chdir(cwd)

    def test_escalate_records_verdict(self):
        from asgard.agent.heimdall import Heimdall

        sid = "native-esc"
        ql(self.root, "open", "q-esc", "--criteria", "c", session=sid)
        h = Heimdall(self._default(), self.root, on_text=lambda s: None)
        h._escalate(sid)
        log = open(os.path.join(self.root, ".asgard", "quest", "q-esc.jsonl")).read()
        self.assertIn('"ESCALATE"', log)  # verdict 없던 기존 append 는 조용히 거부되던 경로
        # ESCALATE 후 close 허용 (quest_log 계약)
        self.assertEqual(ql(self.root, "close", session=sid).returncode, 0)


class TestDeliveryAgents(unittest.TestCase):
    """딜리버리 계층 CC 배선 (CUS-129) — 템플릿 계약·소스 단일화, API 호출 없음."""

    def _tpl(self, name):
        from asgard.templates.roles import ROLE_AGENTS

        return dict(ROLE_AGENTS)[name]

    def test_library_has_roles_and_delivery(self):
        from asgard.templates.roles import ROLE_AGENTS

        names = {f for f, _ in ROLE_AGENTS}
        self.assertLessEqual(
            {f"asgard-{n}.md" for n in ("thinker", "worker", "verifier", "freyja", "thor", "loki")}, names
        )

    def test_delivery_frontmatter_blocks_redelegation(self):
        # freyja/thor: write 가능하되 Agent 금지. loki: read-only allowlist (Agent·Write·Edit 부재).
        for n in ("freyja", "thor"):
            self.assertIn("disallowedTools: Agent", self._tpl(f"asgard-{n}.md"))
        loki_fm = self._tpl("asgard-loki.md").split("---")[1]
        self.assertIn("tools: Read, Grep, Glob, Bash", loki_fm)
        self.assertNotIn("Agent", loki_fm.split("tools:")[1].splitlines()[0])

    def test_trinity_agents_can_nest(self):
        # worker 는 tools 무제한(Agent 상속) → 중첩 디스패치 가능. verifier 는 allowlist 에 Agent 명시.
        self.assertNotIn("tools:", self._tpl("asgard-worker.md").split("---")[1])
        self.assertIn("Agent", self._tpl("asgard-verifier.md").split("---")[1])
        self.assertNotIn("tools:", self._tpl("asgard-thinker.md").split("---")[1].replace("tools: Read", ""))

    def test_heimdall_delivery_derives_from_templates(self):
        from asgard.agent.heimdall import _DELIVERY

        self.assertEqual(sorted(_DELIVERY), ["freyja", "loki", "thor"])
        for g, body in _DELIVERY.items():
            self.assertIn(f"asgard-{g}", body)
            self.assertNotIn("name:", body)  # frontmatter 누출 없음

    def test_agents_md_mandates_mode_b(self):
        from asgard.templates.agents import agents_md

        self.assertIn("반드시 별도 서브에이전트", agents_md("p"))


class TestHeadlessProceed(unittest.TestCase):
    """무인 승인 해소 계약 (CUS-169) — headless 에서 승인 대기 무작업 종료 금지."""

    def _tpl(self, name):
        from asgard.templates.roles import ROLE_AGENTS

        return dict(ROLE_AGENTS)[name]

    def test_canon8_headless_proceeds_with_assumptions(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("무인이면 진행", md)
        self.assertIn("승인 대기로 끝내지 않는다", md)

    def test_canon3_reversible_code_change_not_destructive(self):
        from asgard.templates.agents import agents_md

        self.assertIn("커밋으로 되돌릴 수 있는 코드 변경", agents_md("p"))

    def test_trinity_escalate_blocker_only_and_callers_in_scope(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("ESCALATE 는 승인 요청이 아니라", md)
        self.assertIn("과업의 일부다", md)  # 깨진 caller 복구 = 범위 안

    def test_thinker_forbids_option_wait(self):
        self.assertIn("승인 대기 금지", self._tpl("asgard-thinker.md"))
        self.assertIn("가정: ...", self._tpl("asgard-thinker.md"))

    def test_verifier_escalate_not_for_approval(self):
        self.assertIn("승인·확인 요청 용도 금지", self._tpl("asgard-verifier.md"))


class TestRunPrompt(unittest.TestCase):
    """asgard run — headless 단발 실행 (CUS-193). Heimdall/preflight 을 대역으로 결정론 검증."""

    def setUp(self):
        import io
        import sys as _sys

        from asgard.commands import start as S

        self.S = S
        self._preflight, self._stdout = S.preflight, _sys.stdout
        self._unattended = os.environ.pop("ASGARD_UNATTENDED", None)
        self.out = io.StringIO()
        _sys.stdout = self.out

    def tearDown(self):
        import sys as _sys

        self.S.preflight = self._preflight
        _sys.stdout = self._stdout
        if self._unattended is not None:
            os.environ["ASGARD_UNATTENDED"] = self._unattended
        else:
            os.environ.pop("ASGARD_UNATTENDED", None)

    def _patch(self, result_text="과업 완수 — 보고", tokens=1234):
        import asgard.agent.heimdall as H

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        class FakeHeimdall:
            def __init__(self, rp, root, on_text, on_status=None):
                self.total_tokens = tokens
                on_text("stream-line\n")

            def handle(self, prompt):
                return result_text

        self.S.preflight = lambda root, provider=None, model=None: ([{"ok": True}], FakeRP())
        orig = H.Heimdall
        H.Heimdall = FakeHeimdall
        self.addCleanup(lambda: setattr(H, "Heimdall", orig))

    def test_json_output_and_exit_zero(self):
        self._patch()
        rc = self.S.run_prompt("작업해줘", json_out=True)
        self.assertEqual(rc, 0)
        d = json.loads(self.out.getvalue())
        self.assertEqual(d["result"], "과업 완수 — 보고")
        self.assertEqual(d["tokens"], 1234)
        self.assertEqual(os.environ.get("ASGARD_UNATTENDED"), "1")  # Canon 8 headless 신호

    def test_warning_result_exits_one(self):
        self._patch(result_text="⚠ Odin 결정 필요 — 게이트 차단")
        self.assertEqual(self.S.run_prompt("작업해줘", json_out=True), 1)

    def test_preflight_failure_exits_two(self):
        self.S.preflight = lambda root, provider=None, model=None: (
            [{"ok": False, "name": "k", "detail": "", "fix": ""}],
            None,
        )
        self.assertEqual(self.S.run_prompt("작업해줘"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
