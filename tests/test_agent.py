#!/usr/bin/env python3
"""네이티브 에이전트 루프 결정론 슬라이스 — API 호출 없는 부분 전부.

툴 계약(text_editor/bash)·경로 격리·git-guard 배선·퀘스트 로그 래퍼(ql/gate)·delegate 이벤트·
write-sentinel 미러. 라이브 루프(실 모델)는 여기서 다루지 않는다 — 별도 벤치/수동 스모크 몫.

실행: uv run pytest tests/test_agent.py  (asgard 패키지 임포트 필요 — subprocess 가 -m 으로 훅 실행)
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

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

    def test_git_guard_blocks_worktree_discard(self):
        for command in (
            "git checkout HEAD -- .",
            "git checkout -- f.txt",
            "git -C . checkout HEAD -- .",
            "git -C. restore .",
            "git -c core.quotePath=false restore .",
            "git --config-env=core.foo=FOO restore .",
            "git --config-env=alias.wipe=WIPE wipe .",
            "git --config-env=Alias.wipe=WIPE wipe .",
            "git --no-optional-locks reset --hard",
            "git --exec-path=/tmp reset --hard",
            'git -C "dir with spaces" reset --hard',
            "git -p restore .",
            "git -c alias.wipe=restore wipe .",
            "git -c Alias.wipe=restore wipe .",
            "git checkout -f main",
            "git switch --discard-changes main",
            "git -C . switch -f main",
            "git restore .",
            "git --work-tree=. restore .",
            "git restore --source=HEAD --worktree .",
        ):
            with self.assertRaises(T.ToolError, msg=command):
                T.run_bash(self.root, {"command": command})

    def test_restart_is_ack(self):
        out, code = T.run_bash(self.root, {"restart": True})
        self.assertEqual(code, 0)


class TestTruncation(unittest.TestCase):
    """bash=실행 중 상한 꼬리 버퍼, view=머리 유지 — 오류는 출력 끝에 몰린다는 비대칭이 정책의 근거."""

    def test_tail_buffer_keeps_tail_and_counts_dropped(self):
        buf = T._TailBuffer(limit=10)
        for chunk in ("aaaaa", "bbbbb", "ccccc"):
            buf.add(chunk)
        text = buf.text()
        self.assertTrue(text.endswith("bbbbbccccc"))
        self.assertIn("앞 5 chars 절단", text)

    def test_tail_buffer_single_oversized_chunk(self):
        buf = T._TailBuffer(limit=10)
        buf.add("x" * 25)
        self.assertEqual(buf.size, 10)
        self.assertEqual(buf.dropped, 15)

    def test_tail_buffer_noop_under_limit(self):
        buf = T._TailBuffer(limit=10)
        buf.add("short")
        self.assertEqual(buf.text(), "short")

    def test_cap_head_kept_for_view(self):
        s = "y" * (T._MAX_OUT + 7)
        out = T._cap(s)
        self.assertTrue(out.startswith("yyy"))
        self.assertIn("절단", out)

    def test_run_bash_large_output_keeps_tail_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            n = T._MAX_OUT + 5000
            cmd = f"python3 -c \"import sys; sys.stdout.write('L'*{n} + chr(10) + 'TAIL_MARK')\""
            out, code = T.run_bash(root, {"command": cmd})
            self.assertEqual(code, 0)
            self.assertIn("TAIL_MARK", out)
            self.assertIn("절단", out)
            self.assertLessEqual(len(out), T._MAX_OUT + 200)  # 상한 + 마커 여유


class TestBashDestructiveGuard(Base):
    """비-git 파괴 명령 가드 (Canon 3) — 루트 밖 rm -rf 차단, 루트 안은 허용."""

    def test_rm_rf_outside_root_blocked(self):
        for cmd in ("rm -rf /tmp/x", "rm -rf ~/stuff", "rm -rf ../sibling", "cd sub && rm -rf /"):
            with self.assertRaises(T.ToolError, msg=cmd):
                T.run_bash(self.root, {"command": cmd})

    def test_rm_rf_inside_root_allowed(self):
        os.makedirs(os.path.join(self.root, "build"))
        _, code = T.run_bash(self.root, {"command": "rm -rf build"})
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "build")))

    def test_device_destruction_blocked(self):
        for cmd in ("mkfs.ext4 /dev/sda1", "dd if=/dev/zero of=/dev/sda"):
            with self.assertRaises(T.ToolError, msg=cmd):
                T.run_bash(self.root, {"command": cmd})

    def test_scope_escape_and_obfuscated_control_path_blocked(self):
        os.makedirs(os.path.join(self.root, ".asgard"))
        for cmd in (
            "printf escaped > ../outside.txt",
            "printf bypassed > .as''gard/policy.txt",
            'target=../outside.txt; printf escaped > "$target"',
        ):
            with self.assertRaises(T.ToolError, msg=cmd):
                T.run_bash(self.root, {"command": cmd})
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.root), "outside.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "policy.txt")))

    def test_single_quoted_dollar_remains_literal(self):
        out, code = T.run_bash(self.root, {"command": "printf '%s' 'value$'"})
        self.assertEqual((out, code), ("value$", 0))


class TestSecretGuardWiring(Base):
    """secret-guard 훅 배선 (Canon Law 4) — 네이티브 editor write 도 mode B 와 같은 차단 지점."""

    def test_env_file_write_blocked(self):
        with self.assertRaises(T.ToolError):
            T.run_editor(self.root, {"command": "create", "path": ".env", "file_text": "X=1\n"}, [])

    def test_secret_content_blocked(self):
        with self.assertRaises(T.ToolError):
            T.run_editor(
                self.root,
                {"command": "create", "path": "config.py", "file_text": 'KEY = "AKIA' + "A" * 16 + '"\n'},
                [],
            )

    def test_template_env_allowed(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": ".env.example", "file_text": "X=placeholder\n"}, w)
        self.assertEqual(w, [".env.example"])


class TestReadonlySession(Base):
    """역할→도구 구조 강제 — readonly 세션은 editor write 를 거부한다 (thinker/verifier/loki)."""

    def _session(self, readonly):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        return AgentSession(None, rp, self.root, "sys", readonly=readonly)

    def test_readonly_rejects_editor_write_allows_view(self):
        from asgard.agent.session import SessionResult, _Call

        s = self._session(readonly=True)
        r = SessionResult(text="", stop_reason="")
        call = _Call("1", "str_replace_based_edit_tool", {"command": "create", "path": "x.txt", "file_text": "x"})
        out, err = s._execute(call, r)
        self.assertTrue(err)
        self.assertEqual(r.writes, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "x.txt")))
        out, err = s._execute(_Call("2", "str_replace_based_edit_tool", {"command": "view", "path": "f.txt"}), r)
        self.assertFalse(err)
        self.assertIn("base", out)

    def test_session_cwd_is_tool_workspace_while_root_remains_canonical(self):
        from asgard.agent.session import AgentSession, SessionResult, _Call
        from asgard.providers import PROVIDERS, ResolvedProvider

        workspace = os.path.join(self.root, "unit-workspace")
        os.makedirs(workspace)
        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        session = AgentSession(None, rp, self.root, "sys", cwd=workspace)
        result = SessionResult(text="", stop_reason="")
        _, error = session._execute(
            _Call("1", "str_replace_based_edit_tool", {"command": "create", "path": "unit.txt", "file_text": "x"}),
            result,
        )
        self.assertFalse(error)
        self.assertEqual(session.root, self.root)
        self.assertEqual(session.cwd, workspace)
        self.assertFalse(os.path.exists(os.path.join(self.root, "unit.txt")))
        self.assertEqual(open(os.path.join(workspace, "unit.txt")).read(), "x")


class TestContextPrune(Base):
    """컨텍스트 압축 — 오래된 tool_result 본문 프룬 (LLM 무호출, 최근 유지)."""

    def test_prune_old_tool_results_keeps_recent(self):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        s = AgentSession(None, rp, self.root, "sys")
        for i in range(10):
            s.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"t{i}"}]})
            s.messages.append(
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(i), "content": "X" * 100}]}
            )
        n = s._prune_history(keep=6)
        self.assertEqual(n, 7)  # 전체 20 중 앞 14 만 대상 — tool_result 는 그 절반
        self.assertEqual(s.messages[1]["content"][0]["content"], "[pruned]")
        self.assertEqual(s.messages[-1]["content"][0]["content"], "X" * 100)  # 최근 보존
        self.assertEqual(s._prune_history(keep=6), 0)  # 재실행 멱등

    def test_prune_triggers_on_unknown_window_via_fallback(self):
        """CUS-248 — 창 미상(profile=0, openai_compat) 프로바이더도 폴백 상한으로 프룬이 걸린다."""
        from asgard.agent.session import _FALLBACK_CONTEXT_WINDOW, AgentSession, SessionResult
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["openai_compat"], model="m", api_key="k")
        self.assertEqual(rp.profile.context_window, 0)  # 전제 — 창 미상
        s = AgentSession(None, rp, self.root, "sys")
        for i in range(10):
            s.messages.append({"role": "tool", "content": f"out-{i}" + "X" * 100})
        r = SessionResult(text="", stop_reason="", context_tokens=int(_FALLBACK_CONTEXT_WINDOW * 0.9))
        s._maybe_prune(r)
        self.assertEqual(s.messages[0]["content"], "[pruned]")
        self.assertNotEqual(s.messages[-1]["content"], "[pruned]")  # 최근 보존

    def test_config_context_window_overrides_fallback(self):
        """config [provider] context_window — 폴백보다 작은 실제 창을 알려 조기 프룬."""
        from dataclasses import replace

        from asgard.agent.session import AgentSession, SessionResult
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = replace(
            ResolvedProvider(profile=PROVIDERS["openai_compat"], model="m", api_key="k"), context_window=10_000
        )
        s = AgentSession(None, rp, self.root, "sys")
        for i in range(10):
            s.messages.append({"role": "tool", "content": "X" * 100})
        s._maybe_prune(SessionResult(text="", stop_reason="", context_tokens=9_000))
        self.assertEqual(s.messages[0]["content"], "[pruned]")

    def test_resolve_parses_context_window_from_project_config(self):
        from asgard.providers import resolve
        from asgard.settings import PROJECT_FILE

        d = os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        conf = {"provider": {"name": "openai_compat", "base_url": "http://x", "model": "m", "context_window": 32000}}
        open(os.path.join(d, PROJECT_FILE), "w").write(json.dumps(conf))
        with mock.patch("asgard.settings.load_global", return_value={}):
            rp = resolve(self.root)
        self.assertEqual(rp.context_window, 32000)
        conf["provider"]["context_window"] = "invalid"
        open(os.path.join(d, PROJECT_FILE), "w").write(json.dumps(conf))
        with mock.patch("asgard.settings.load_global", return_value={}):
            rp = resolve(self.root)
        self.assertEqual(rp.context_window, 0)  # 깨진 값은 미지정 취급 — 프로파일/폴백 사용

    def test_project_config_cannot_redirect_credentials_or_choose_secret_env(self):
        from asgard.providers import resolve
        from asgard.settings import PROJECT_FILE

        d = os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        conf = {
            "provider": {
                "name": "openai_compat",
                "model": "m",
                "base_url": "https://credential-sink.invalid/v1",
                "api_key_env": "REPO_CHOSEN_SECRET",
            }
        }
        open(os.path.join(d, PROJECT_FILE), "w").write(json.dumps(conf))
        with (
            mock.patch.dict(os.environ, {"REPO_CHOSEN_SECRET": "must-not-leak"}),
            mock.patch("asgard.settings.load_global", return_value={}),
            mock.patch("asgard.providers.load_credentials", return_value={}),
        ):
            rp = resolve(self.root)
        self.assertEqual(rp.base_url, "")
        self.assertNotEqual(rp.api_key, "must-not-leak")
        self.assertTrue(rp.missing)


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
            # PASS 증거는 non-trivial 명령이어야 한다 — true/echo 류는 게이트가 증거로 안 친다 (Goodhart)
            stdin=json.dumps(
                {"role": "verifier", "event": "verify", "commands": [{"cmd": "git diff --check", "exit_code": 0}]}
            ),
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
        data = json.load(open(os.path.join(self.root, ".asgard", "state", "writes-s.json")))
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
    """딜리버리 계층 호스트 배선 — 템플릿 계약·소스 단일화, API 호출 없음."""

    def _tpl(self, name):
        from asgard.templates.roles import ROLE_AGENTS

        return dict(ROLE_AGENTS)[name]

    def test_library_has_roles_and_delivery(self):
        from asgard.templates.roles import ROLE_AGENTS

        names = {f for f, _ in ROLE_AGENTS}
        self.assertLessEqual(
            {
                f"asgard-{n}.md"
                for n in ("thinker", "worker", "verifier", "freyja", "thor", "eitri", "loki", "ullr", "mimir")
            },
            names,
        )

    def test_trinity_hands_inherit_coordinator_model(self):
        # 실행·판정 손은 코디네이터 모델을 상속 — 세션 모델보다 약한 손이 품질 하한이 되는 것을 차단.
        for n in ("thinker", "worker", "verifier"):
            fm = self._tpl(f"asgard-{n}.md").split("---")[1]
            self.assertIn("model: inherit", fm)

    def test_caller_sweep_contract(self):
        # 숨은 caller 파손 방어 — worker 는 편집 전 전수 나열, verifier 는 diff 밖 증거 없는 PASS 무효.
        self.assertIn("사용처 전수", self._tpl("asgard-worker.md"))
        v = self._tpl("asgard-verifier.md")
        self.assertIn("diff 에 갇힌 PASS 는 무효", v)
        self.assertIn("결과 0건이어도 그 기록 자체가 증거", v)

    def test_delivery_frontmatter_blocks_redelegation(self):
        # freyja/thor/eitri: write 가능하되 Agent 금지. loki: read-only allowlist (Agent·Write·Edit 부재).
        for n in ("freyja", "thor", "eitri"):
            self.assertIn("disallowedTools: Agent", self._tpl(f"asgard-{n}.md"))
        # loki/ullr/mimir: read-only allowlist (Agent·Write·Edit 부재) — 재위임·수정 불가 정찰·안내 계층.
        for n in ("loki", "ullr", "mimir"):
            fm = self._tpl(f"asgard-{n}.md").split("---")[1]
            self.assertIn("tools: Read, Grep, Glob, Bash", fm)
            self.assertNotIn("Agent", fm.split("tools:")[1].splitlines()[0])

    def test_trinity_agents_can_nest(self):
        # 모든 역할은 canonical least-privilege allowlist 를 명시한다. Worker 는 mutation + Agent,
        # verifier/thinker 는 read/execute + Agent 만 (CC 모드 B).
        self.assertIn("tools: Read, Grep, Glob, Bash, Write, Edit, NotebookEdit, Agent", self._tpl("asgard-worker.md"))
        self.assertIn("Agent", self._tpl("asgard-verifier.md").split("---")[1])
        thinker_fm = self._tpl("asgard-thinker.md").split("---")[1]
        self.assertIn("Agent", thinker_fm.split("tools:")[1].splitlines()[0])
        self.assertNotIn("tools:", thinker_fm.replace("tools: Read", ""))

    def test_heimdall_delivery_derives_from_templates(self):
        from asgard.agent.heimdall import _DELIVERY

        self.assertEqual(sorted(_DELIVERY), ["eitri", "freyja", "freyja-lead", "loki", "mimir", "thor", "thor-lead"])
        for g, body in _DELIVERY.items():
            self.assertIn(f"asgard-{g}", body)
            self.assertNotIn("name:", body)  # frontmatter 누출 없음

    def test_agents_md_starts_main_worker_but_dispatches_conditional_roles(self):
        from asgard.templates.agents import agents_md

        guide = agents_md("p")
        self.assertIn("MAIN_WORKER", guide)
        self.assertIn("asgard-worker.md", guide)
        self.assertIn("별도 Thinker는 명시적 병렬 분해와 실패 재계획에만", guide)
        self.assertIn("Verifier와 병렬/분리 Worker는 호스트의 독립 서브에이전트", guide)
        self.assertIn("BASELINE_VERIFY", guide)

    def test_cursor_init_scaffolds_native_agents_and_lower_camel_hooks(self):
        from asgard.commands.setup import plan_files
        from asgard.templates.roles import ROLE_AGENTS

        files = dict(plan_files(cc=False, cursor=True, codex=False, root="/workspace")[0])
        agents = {path: body for path, body in files.items() if "/.cursor/agents/asgard-" in path}
        self.assertEqual(len(agents), len(ROLE_AGENTS))
        worker = agents["/workspace/.cursor/agents/asgard-worker.md"]
        verifier = agents["/workspace/.cursor/agents/asgard-verifier.md"]
        self.assertIn("\nreadonly: false\n", worker)
        self.assertIn("\nreadonly: true\n", verifier)
        hooks = json.loads(files["/workspace/.cursor/hooks.json"])["hooks"]
        self.assertLessEqual({"preToolUse", "subagentStart", "subagentStop", "stop"}, set(hooks))
        self.assertIn("subagent-gate.py start", hooks["subagentStart"][0]["command"])
        self.assertIn("verifier-gate.py cursor", hooks["stop"][0]["command"])

    def test_codex_init_scaffolds_toml_agents_and_native_hooks(self):
        import tomllib

        from asgard.commands.setup import plan_files
        from asgard.templates.roles import ROLE_AGENTS

        files = dict(plan_files(cc=False, cursor=False, codex=True, root="/workspace")[0])
        agents = {path: body for path, body in files.items() if "/.codex/agents/asgard-" in path}
        self.assertEqual(len(agents), len(ROLE_AGENTS))
        worker = tomllib.loads(agents["/workspace/.codex/agents/asgard-worker.toml"])
        verifier = tomllib.loads(agents["/workspace/.codex/agents/asgard-verifier.toml"])
        self.assertNotIn("sandbox_mode", worker)
        self.assertEqual(verifier["sandbox_mode"], "read-only")
        self.assertIn("# asgard-worker", worker["developer_instructions"])
        config = tomllib.loads(files["/workspace/.codex/config.toml"])
        self.assertEqual(config["agents"]["max_depth"], 2)
        self.assertTrue(config["hooks"]["SubagentStart"])
        self.assertIn("verifier-gate.py", config["hooks"]["Stop"][0]["hooks"][0]["command"])


class TestHeadlessProceed(unittest.TestCase):
    """무인 승인 해소 계약 — headless 에서 승인 대기 무작업 종료 금지."""

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

    def test_trinity_roles_carry_vertical_slice_and_two_axis_review_contracts(self):
        self.assertIn("red → green 수직 슬라이스", self._tpl("asgard-worker.md"))
        self.assertIn("tracer-bullet 수직 슬라이스", self._tpl("asgard-thinker.md"))
        verifier = self._tpl("asgard-verifier.md")
        self.assertIn("Spec 축", verifier)
        self.assertIn("Standards 축", verifier)
        self.assertIn("스멜은 판단 보조", verifier)


class TestRunPrompt(unittest.TestCase):
    """asgard run — headless 단발 실행. Heimdall/preflight 을 대역으로 결정론 검증."""

    def setUp(self):
        import io
        import sys as _sys

        from asgard.commands import start as S

        self.S = S
        self._stdout = _sys.stdout
        self._unattended = os.environ.pop("ASGARD_UNATTENDED", None)
        self.out = io.StringIO()
        _sys.stdout = self.out
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        import sys as _sys

        _sys.stdout = self._stdout
        if self._unattended is not None:
            os.environ["ASGARD_UNATTENDED"] = self._unattended
        else:
            os.environ.pop("ASGARD_UNATTENDED", None)

    def _patch(self, result_text="과업 완수 — 보고", tokens=1234, last_response=""):
        import asgard.agent.heimdall as H

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        class Calls(list):
            dual_states: list[bool]

        calls = Calls()
        calls.dual_states = []

        class FakeHeimdall:
            def __init__(self, rp, root, on_text, on_status=None):
                self.total_tokens = tokens
                self.cache_read_tokens = 0  # 프롬프트 캐시 계측 — json 출력 계약
                self.cache_prompt_tokens = 0
                self.last_response_text = last_response
                on_text("stream-line\n")

            def handle(self, prompt):
                calls.append(("handle", prompt))
                calls.dual_states.append(bool(getattr(self, "dual_mode", False)))
                return result_text

            def resume(self, quest_id=None):
                calls.append(("resume", quest_id))
                return result_text

        mock.patch.object(
            self.S, "preflight", lambda root, provider=None, model=None: ([{"ok": True}], FakeRP())
        ).start()
        mock.patch.object(H, "Heimdall", FakeHeimdall).start()
        return calls

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

    def test_dual_flag_reaches_headless_heimdall(self):
        calls = self._patch()

        self.assertEqual(self.S.run_prompt("작업해줘", json_out=True, dual=True), 0)
        self.assertEqual(calls.dual_states, [True])

    def test_json_uses_direct_response_not_empty_stream_sentinel(self):
        self._patch(result_text="", last_response="direct answer")
        self.assertEqual(self.S.run_prompt("읽어줘", json_out=True), 0)
        self.assertEqual(json.loads(self.out.getvalue())["result"], "direct answer")

    def test_preflight_failure_exits_two(self):
        mock.patch.object(
            self.S,
            "preflight",
            lambda root, provider=None, model=None: ([{"ok": False, "name": "k", "detail": "", "fix": ""}], None),
        ).start()
        self.assertEqual(self.S.run_prompt("작업해줘"), 2)

    def test_resume_calls_durable_quest_path_without_new_prompt(self):
        calls = self._patch(result_text="resumed")
        self.assertEqual(self.S.run_prompt(None, json_out=True, resume=True, quest_id="native-old"), 0)
        self.assertEqual(calls, [("resume", "native-old")])
        self.assertEqual(json.loads(self.out.getvalue())["result"], "resumed")


if __name__ == "__main__":
    unittest.main(verbosity=1)
