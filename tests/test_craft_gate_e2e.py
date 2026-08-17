"""craft-gate 실 host E2E — **배포되는 훅 파일을 실제로 실행한다**.

실행: uv run pytest tests/test_craft_gate_e2e.py

`test_craft_gate_hook.py`와 역할이 다르다. 저쪽은 훅 모듈을 import 하고 `subprocess.run`을 목킹해서
합쳐진 판정의 **모양**을 고정한다. 그 방식으로는 절대 못 잡는 것이 넷 있고, 이 파일은 그 넷만 잡는다:

① **배포본이 실제로 도는가.** 훅은 사용자 저장소로 복사되어 stdlib 만으로 돌아야 한다. import로
   부르는 시험은 엔진이 이미 `sys.path`에 있는 프로세스에서 돌기 때문에, 훅이 실수로 엔진을
   import 해도 초록으로 통과한다 — 정작 사용자 저장소에서만 죽는다.
② **stdin/stdout 규약.** 호스트는 JSON을 stdin으로 먹이고 stdout을 JSON으로 읽는다. 목킹은
   이 경로를 통째로 건너뛴다.
③ **호스트별 차단 payload 모양.** cursor는 `followup_message`, codex는 `continue`/`stopReason`,
   claude는 `decision`/`reason`. 셋이 다르고, 틀리면 차단이 조용히 무시된다.
④ **스캐폴드가 훅을 실제로 놓는가.** 판정기가 완벽해도 파일이 안 놓이면 게이트는 없는 것이다.

엔진을 가리는 방법은 `python -S` 다. site-packages를 안 붙이므로 `import asgard`가 실패하고,
stdlib은 그대로 산다 — 사용자 저장소에서 훅이 처하는 상황과 같고, 인터프리터 경로를 찾아다니지
않아도 되어 어느 플랫폼에서나 같게 돈다.

수리 레인(`RepairLane`)은 진짜 CLI 대신 **스텁 asgard**를 PATH 에 얹고 배포본 훅을 그대로 돌린다.
`asgard craft --fix`가 무엇을 돌려주든 훅이 어떻게 처신하는지가 판정 대상이라, 판정기 구현이
아니라 payload 모양만 있으면 된다. 구 CLI(모르는 옵션으로 종료)와 죽은 수리는 진짜 CLI 로는
재현할 수 없다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from hookscaffold import isolated_home_env

# 두 게이트가 각각 하나씩 잡는 원문 — 합쳐진 판정이 출처를 잃지 않는지까지 한 번에 본다.
DEFECT = "def load(path):\n    try:\n        return open(path).read()\n    except Exception:\n        pass\n"
CLEAN = "def load(path):\n    with open(path) as handle:\n        return handle.read()\n"

# (스캐폴드 플래그, 훅 경로, argv, 세션 id, 차단 payload에서 사유가 들어가는 칸)
HOSTS = (
    ("--cursor", os.path.join(".cursor", "hooks", "craft-gate.py"), ["cursor"], "cursor", "followup_message"),
    ("--codex", os.path.join(".codex", "hooks", "craft-gate.py"), ["codex"], "default", "stopReason"),
    ("--cc", os.path.join(".claude", "hooks", "craft-gate.py"), [], "s1", "reason"),
)


# 스텁 CLI. 세 게이트 · 두 레인을 argv 로 갈라 `CRAFTGATE_STUB` 이 가리키는 표에서 payload 를 꺼낸다.
# 표에 없는 레인은 종료 코드 2 + 빈 stdout — argparse 가 모르는 옵션에 하는 것과 같고, 그것이
# `--fix` 를 모르는 구 CLI 다.
STUB = """\
import json, os, sys

argv = sys.argv[1:]
with open(os.environ["CRAFTGATE_CALLS"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv) + "\\n")
if "thor" in argv:
    lane = "thor gate"
elif "freyja-gate" in argv:
    lane = "freyja gate"
else:
    lane = "craft --fix" if "--fix" in argv else "craft"
with open(os.environ["CRAFTGATE_STUB"], encoding="utf-8") as handle:
    spec = json.load(handle).get(lane)
if spec is None:
    sys.stderr.write("asgard: error: unrecognized arguments: --fix\\n")
    raise SystemExit(2)
if spec.get("crash"):
    sys.stderr.write("Traceback (most recent call last):\\nRuntimeError: repair blew up\\n")
    raise SystemExit(1)
sys.stdout.write(json.dumps(spec, ensure_ascii=False))
raise SystemExit(1 if spec.get("blocking") else 0)
"""

# 수리 두 건과 남은 판정 하나 — "고친 것"과 "남은 것"이 차단문에서 안 섞이는지를 이 한 묶음으로 본다.
FIX = {
    "applied": [
        {"path": "src/a.py", "line": 12, "rule": "note-jargon", "before": "# 무매칭", "after": "# 일치 없음"},
        {"path": "src/b.py", "line": 4, "rule": "note-jargon", "before": "# 불요", "after": "# 불필요"},
    ],
    "refused": [],
    "files": ["src/a.py", "src/b.py"],
    "remaining_blocking": 1,
}
REMAINDER = {"rule": "unit-oversize", "path": "src/a.py", "line": 40, "detail": "본문 92줄", "fix": "쪼갠다"}
CLEAN_GATES = {"thor gate": {"blocking": []}, "freyja gate": {"blocking": []}}


def _asgard_bin() -> str | None:
    """이 시험이 쓰는 CLI. 훅은 `shutil.which("asgard")`로 찾으므로 PATH에 얹어 준다."""
    candidate = os.path.join(os.path.dirname(sys.executable), "asgard")
    return candidate if os.path.exists(candidate) else shutil.which("asgard")


@unittest.skipIf(_asgard_bin() is None, "asgard CLI 가 PATH 에 없다 — 훅이 판정기를 못 부른다")
class ShippedHookRuns(unittest.TestCase):
    """스캐폴드 → 결함 작성 → 배포본 훅 실행 → 호스트 규약대로 차단. 한 줄도 목킹하지 않는다."""

    bin: str  # skipIf가 None을 걸러내지만 타입은 그 사실을 모른다 — 여기서 고정한다

    def setUp(self):
        found = _asgard_bin()
        assert found is not None, "skipIf 가 걸러냈어야 한다"
        self.bin = found
        self.root = tempfile.mkdtemp(prefix="craftgate-e2e-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = tempfile.mkdtemp(prefix="craftgate-home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self._git("init")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=False)

    def _scaffold(self, flag: str) -> None:
        done = subprocess.run(
            [self.bin, "init", flag, "--yes", "-q"],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=180,
            env=isolated_home_env(self.home),  # 임시 루트를 사람의 프로젝트 목록에 안 남긴다
        )
        self.assertEqual(0, done.returncode, done.stderr)

    def _write(self, rel: str, body: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)

    def _sentinel(self, sid: str, rels: list[str]) -> None:
        """훅이 판정하는 것은 **이 세션이 쓴 경로**다 — 그 목록을 write_sentinel과 같은 자리에 둔다."""
        self._write(os.path.join(".asgard", "state", f"writes-{sid}.json"), json.dumps(rels))

    def _run_hook(self, hook: str, argv: list[str], payload: dict) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PATH"] = os.path.dirname(self.bin) + os.pathsep + env.get("PATH", "")
        env.pop("CLAUDE_PROJECT_DIR", None)  # payload의 cwd 로만 뿌리를 정하게 한다
        return subprocess.run(
            # `-S` = site-packages 없이. 엔진을 import 하면 여기서 죽는다 (배포본의 계약).
            [sys.executable, "-S", os.path.join(self.root, hook), *argv],
            input=json.dumps(payload),
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    def test_every_host_blocks_a_real_regression_through_its_own_protocol(self):
        for flag, hook, argv, sid, field in HOSTS:
            with self.subTest(host=flag):
                self.setUp()
                self._scaffold(flag)
                self.assertTrue(os.path.exists(os.path.join(self.root, hook)), f"{hook} 이 스캐폴드되지 않았다")
                self._write("src/leak.py", DEFECT)
                self._sentinel(sid, ["src/leak.py"])
                done = self._run_hook(hook, argv, {"cwd": self.root, "session_id": sid})

                self.assertEqual(0, done.returncode, done.stderr)  # 훅은 언제나 0 — 차단은 payload로 말한다
                self.assertNotIn("ModuleNotFoundError", done.stderr)  # stdlib 전용 계약
                payload = json.loads(done.stdout)
                self.assertIn(field, payload, f"{flag} 의 차단 칸이 없다 — 호스트가 차단을 무시한다")
                reason = str(payload[field])
                self.assertIn("craft-gate", reason)
                self.assertIn("[craft/unclosed-acquire]", reason)  # 형상 게이트
                self.assertIn("[thor gate/swallowed-exception]", reason)  # 정확성 게이트
                if flag == "--codex":
                    self.assertIs(False, payload.get("continue"))
                if flag == "--cc":
                    self.assertEqual("block", payload.get("decision"))

    def test_clean_code_is_not_blocked(self):
        """막는 쪽만 시험하면 훅을 '항상 차단'으로 바꿔도 초록이다 — 음성 대조군이 짝으로 있어야 한다."""
        self._scaffold("--cursor")
        self._write("src/ok.py", CLEAN)
        self._sentinel("cursor", ["src/ok.py"])
        done = self._run_hook(HOSTS[0][1], ["cursor"], {"cwd": self.root, "session_id": "cursor"})
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("", done.stdout.strip())

    def test_a_session_that_wrote_nothing_is_not_judged(self):
        """판정 대상은 이 세션의 쓰기다 — 센티넬이 없으면 대상이 없고, 없는 것은 통과다."""
        self._scaffold("--cursor")
        self._write("src/leak.py", DEFECT)  # 결함은 있지만 이 세션이 쓴 것이 아니다
        done = self._run_hook(HOSTS[0][1], ["cursor"], {"cwd": self.root, "session_id": "cursor"})
        self.assertEqual("", done.stdout.strip())

    def test_the_shipped_hook_never_imports_the_engine(self):
        """`-S`로 도는 것을 봤더라도 형상으로 한 번 더 못박는다.

        다음 사람이 무심코 `from ..craft import judge`를 넣으면 이 저장소 안에서는 계속 초록이고,
        사용자 저장소에서만 죽는다 — 그 종류의 결함은 실행 시험만으로 못 막는다.

        판정은 글자가 아니라 문법 트리로 한다. 부분 문자열로 찾으면 `asgard_hooklib` — 엔진이
        아니라 훅 **옆에 함께 깔리는** 라이브러리 — 이 이름이 `asgard` 로 시작한다는 이유만으로
        걸린다. 금지 대상은 이름의 생김새가 아니라 무엇을 임포트하는가다 (같은 규칙이
        tests/architecture/test_layered.py 의 `test_hooks_are_self_contained` 에 있다)."""
        import ast

        from asgard.hooks import craft_gate

        with open(craft_gate.__file__, encoding="utf-8") as handle:
            body = handle.read()
        leaks = []
        for node in ast.walk(ast.parse(body)):
            if isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    leaks.append(f"{node.lineno}: 상대 임포트 (복사본에서 즉사)")
                elif (node.module or "").split(".")[0] == "asgard":
                    leaks.append(f"{node.lineno}: from {node.module}")
            elif isinstance(node, ast.Import):
                leaks += [f"{node.lineno}: import {a.name}" for a in node.names if a.name.split(".")[0] == "asgard"]
        self.assertFalse(leaks, "배포본이 엔진을 임포트한다 (사용자 저장소에서만 죽는다):\n" + "\n".join(leaks))

    def test_the_scaffolded_copy_is_the_engine_source_byte_for_byte(self):
        """복사 배포본이 원본과 어긋나면 판정이 두 벌이 되고, 두 벌은 곧 다르게 판정한다.

        훅 표가 세 호스트에 다 있는지는 `test_mode_parity`가 본다. 여기서만 볼 수 있는 것은
        **디스크에 실제로 놓인 바이트**다 — 절단·인코딩 변환·개행 변환은 표를 봐서는 안 보인다.
        """
        from asgard.hooks import craft_gate

        with open(craft_gate.__file__, "rb") as handle:
            origin = handle.read()
        for flag, hook, _argv, _sid, _field in HOSTS:
            with self.subTest(host=flag):
                self.setUp()
                self._scaffold(flag)
                with open(os.path.join(self.root, hook), "rb") as handle:
                    self.assertEqual(origin, handle.read())


class RepairLane(unittest.TestCase):
    """craft 수리 레인 — 스텁 CLI 위에서 배포본 훅을 그대로 실행한다.

    잰다: ① 고친 사실을 남은 판정보다 먼저 말하는가, ② 다 고쳐 막을 것이 없으면 통과하되 증거를
    남기는가, ③ 수리만 한 실행이 차단 카운터를 쓰는가, ④ 구 CLI 와 죽은 수리에서 예전처럼 막는가.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="craftgate-fix-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.bin = os.path.join(self.root, "bin")
        self.table = os.path.join(self.root, "stub.json")
        self.calls = os.path.join(self.root, "calls.jsonl")
        os.makedirs(self.bin)
        self._install_stub()
        self._write("src/a.py", CLEAN)
        self._write(os.path.join(".asgard", "state", "writes-s1.json"), json.dumps(["src/a.py"]))

    def _write(self, rel: str, body: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)

    def _install_stub(self) -> None:
        """`shutil.which("asgard")`가 찾을 이름으로 스텁을 얹는다 — 훅이 CLI 를 찾는 방법 그대로다."""
        script = os.path.join(self.bin, "stub.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(STUB)
        if os.name == "nt":
            with open(os.path.join(self.bin, "asgard.bat"), "w", encoding="utf-8") as handle:
                handle.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, script))
            return
        launcher = os.path.join(self.bin, "asgard")
        with open(launcher, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, script))
        os.chmod(launcher, 0o755)

    def _hook(self) -> str:
        from asgard.hooks import craft_gate

        return craft_gate.__file__

    def _run(self, table: dict) -> subprocess.CompletedProcess:
        with open(self.table, "w", encoding="utf-8") as handle:
            json.dump(table, handle)
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env.get("PATH", "")
        env["CRAFTGATE_STUB"] = self.table
        env["CRAFTGATE_CALLS"] = self.calls
        env.pop("CLAUDE_PROJECT_DIR", None)
        return subprocess.run(
            # `-S` = site-packages 없이. 배포본이 엔진을 import 하면 여기서 죽는다.
            [sys.executable, "-S", self._hook()],
            input=json.dumps({"cwd": self.root, "session_id": "s1"}),
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    def _lanes(self) -> list[list[str]]:
        with open(self.calls, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def _counter(self) -> dict | None:
        path = os.path.join(self.root, ".asgard", "state", "craftgate-s1.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_repair_is_stated_first_and_only_the_remainder_blocks(self):
        done = self._run({"craft --fix": {"blocking": [REMAINDER], "fix": FIX}, **CLEAN_GATES})
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertNotIn("ModuleNotFoundError", done.stderr)  # stdlib 전용 계약
        reason = str(json.loads(done.stdout)["reason"])
        self.assertIn("repaired 2 finding(s)", reason)
        self.assertIn("src/a.py, src/b.py", reason)
        self.assertIn("[craft/unit-oversize]", reason)
        self.assertNotIn("note-jargon", reason)  # 고쳐진 것을 다시 고치라고 말하면 안 된다
        self.assertLess(reason.index("repaired 2 finding(s)"), reason.index("[craft/unit-oversize]"))

    def test_only_craft_is_given_the_fix_flag(self):
        """thor gate 와 freyja gate 는 수리 레인이 없다 — 고칠 수 없는 것을 재기 때문이다."""
        self._run({"craft --fix": {"blocking": [REMAINDER], "fix": FIX}, **CLEAN_GATES})
        lanes = self._lanes()
        self.assertIn("--fix", lanes[0])
        self.assertIn("craft", lanes[0])
        for argv in lanes[1:]:
            with self.subTest(argv=argv):
                self.assertNotIn("--fix", argv)

    def test_everything_repaired_passes_but_leaves_a_receipt(self):
        """막을 것이 없어졌다고 조용히 통과하면 디스크가 바뀐 것을 아무도 못 본 채 지나간다."""
        done = self._run({"craft --fix": {"blocking": [], "fix": FIX}, **CLEAN_GATES})
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("", done.stdout.strip())
        self.assertIn("repaired 2 finding(s)", done.stderr)
        self.assertIn("src/a.py, src/b.py", done.stderr)

    def test_a_repair_only_run_does_not_consume_the_block_counter(self):
        """상한 2회는 차단의 래칫이다 — 수리는 차단이 아니므로 남은 기회를 깎지 않는다."""
        self._run({"craft --fix": {"blocking": [], "fix": FIX}, **CLEAN_GATES})
        self.assertIsNone(self._counter())
        self._run({"craft --fix": {"blocking": [REMAINDER], "fix": FIX}, **CLEAN_GATES})
        self.assertEqual({"session": 1}, self._counter())

    def test_a_cli_without_the_repair_lane_blocks_exactly_as_before(self):
        """표에 `craft --fix`가 없으면 스텁은 종료 코드 2 로 죽는다 — `--fix` 를 모르는 구 CLI 다."""
        done = self._run({"craft": {"blocking": [REMAINDER]}, **CLEAN_GATES})
        reason = str(json.loads(done.stdout)["reason"])
        self.assertIn("[craft/unit-oversize]", reason)
        self.assertNotIn("repaired", reason)
        self.assertEqual(
            ["craft --fix", "craft"], ["craft --fix" if "--fix" in a else "craft" for a in self._lanes()][:2]
        )

    def test_a_crashed_repair_degrades_to_read_only_judging_not_to_allowing(self):
        done = self._run({"craft --fix": {"crash": True}, "craft": {"blocking": [REMAINDER]}, **CLEAN_GATES})
        reason = str(json.loads(done.stdout)["reason"])
        self.assertIn("[craft/unit-oversize]", reason)
        self.assertNotIn("repaired", reason)

    def test_a_clean_repair_lane_with_nothing_to_do_is_silent(self):
        """수리 0건 · 판정 0건 — 통과이고, 아무 말도 남기지 않는다 (증거는 수리가 있을 때만)."""
        empty = {"applied": [], "refused": [], "files": [], "remaining_blocking": 0}
        done = self._run({"craft --fix": {"blocking": [], "fix": empty}, **CLEAN_GATES})
        self.assertEqual("", done.stdout.strip())
        self.assertEqual("", done.stderr.strip())


if __name__ == "__main__":
    unittest.main()
