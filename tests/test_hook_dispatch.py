"""주입 훅 디스패처 — 합쳐도 같은 것이 나오는가, 하나가 죽어도 나머지가 나오는가.

프로세스가 훅마다 따로일 때는 두 가지가 공짜였다. 하나가 터져도 나머지 주입이 나오는 것과,
채널이 섞이지 않는 것. 합치면 둘 다 코드가 지켜야 하므로 여기서 고정한다.

경계도 여기서 잰다: 가드 8종과 증거 훅 3종은 디스패처 안에 **들어가면 안 된다**. 그 둘이
조용히 죽으면 화면에는 아무것도 안 뜨는데 판정만 얕아진다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from asgard.commands.doctor.wiring import _HOOK_IN_COMMAND
from asgard.templates import cc_settings

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "src" / "asgard" / "hooks" / "hook_dispatch.py"

# 절대 합치지 않는 것 — 신뢰 경계 판정(가드)과 판정의 입력을 만드는 자리(증거 훅).
GUARDS = (
    "budget-guard",
    "craft-gate",
    "git-guard",
    "readonly-guard",
    "release-guard",
    "secret-guard",
    "subagent-gate",
    "verifier-gate",
)
EVIDENCE = ("failure-tracker", "verifier-context", "write-sentinel")

_PLAIN = "import sys\ndef main():\n    sys.stdout.write(%r)\n"
_CONTEXT = (
    "import json, sys\n"
    "def main():\n"
    "    sys.stdout.write(json.dumps({'hookSpecificOutput': "
    "{'hookEventName': %r, 'additionalContext': %r}}, ensure_ascii=False) + '\\n')\n"
)
_MESSAGE = "import json, sys\ndef main():\n    sys.stdout.write(json.dumps({'systemMessage': %r}) + '\\n')\n"
_BOOM = "def main():\n    raise RuntimeError('deliberate')\n"
_SILENT = "def main():\n    return 0\n"
_ECHO_STDIN = "import json, sys\ndef main():\n    sys.stdout.write(json.load(sys.stdin)['prompt'])\n"
_ECHO_ARGV = "import sys\ndef main():\n    sys.stdout.write('|'.join(sys.argv[1:]))\n"


class _Bed:
    """훅 몇 개를 임시 폴더에 놓고 디스패처를 돌리는 자리."""

    def __init__(self, tmp: str) -> None:
        self.tmp = tmp

    def hook(self, name: str, body: str) -> str:
        path = os.path.join(self.tmp, name + ".py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def run(self, event: str, hooks: list, payload: dict | None = None) -> tuple:
        argv = [sys.executable, str(DISPATCH)]
        for spec in hooks:
            argv += ["--", *(spec if isinstance(spec, list) else [spec])]
        body = {"hook_event_name": event, "cwd": self.tmp, **(payload or {})}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": self.tmp}  # 실제 저장소 장부를 안 건드린다
        proc = subprocess.run(
            argv, input=json.dumps(body).encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


def _context_of(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


class TestMerge(unittest.TestCase):
    def test_context_keeps_wiring_order_and_one_newline_between_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [
                bed.hook("a", _PLAIN % "첫째"),
                bed.hook("b", _CONTEXT % ("UserPromptSubmit", "둘째")),
                bed.hook("c", _PLAIN % "셋째"),
            ]
            code, out, err = bed.run("UserPromptSubmit", hooks)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(_context_of(out), "첫째\n둘째\n셋째")

    def test_a_silent_hook_adds_no_separator(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [
                bed.hook("a", _PLAIN % "첫째"),
                bed.hook("quiet", _SILENT),
                bed.hook("c", _PLAIN % "셋째"),
            ]
            self.assertEqual(_context_of(bed.run("UserPromptSubmit", hooks)[1]), "첫째\n셋째")

    def test_session_start_context_stays_plain_stdout(self):
        """SessionStart 의 주입 통로는 평문이다 — JSON 으로 싸면 호스트가 그 문자열을 그대로 넣는다."""
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [bed.hook("a", _PLAIN % "캐논"), bed.hook("b", _PLAIN % "매뉴얼")]
            self.assertEqual(bed.run("SessionStart", hooks)[1], "캐논\n매뉴얼")

    def test_messages_and_context_ride_one_object_without_mixing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [
                bed.hook("ctx", _CONTEXT % ("UserPromptSubmit", "모델이 읽을 것")),
                bed.hook("msg", _MESSAGE % "사람이 읽을 것"),
            ]
            body = json.loads(bed.run("UserPromptSubmit", hooks)[1])
            self.assertEqual(body["hookSpecificOutput"]["additionalContext"], "모델이 읽을 것")
            self.assertEqual(body["systemMessage"], "사람이 읽을 것")

    def test_stop_messages_join_without_a_context_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [bed.hook("m1", _MESSAGE % "메모리"), bed.hook("m2", _MESSAGE % "되짚기")]
            body = json.loads(bed.run("Stop", hooks)[1])
            self.assertEqual(body, {"systemMessage": "메모리\n\n되짚기"})

    def test_every_hook_reads_the_same_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [bed.hook("e1", _ECHO_STDIN), bed.hook("e2", _ECHO_STDIN)]
            out = bed.run("UserPromptSubmit", hooks, {"prompt": "요청"})[1]
            self.assertEqual(_context_of(out), "요청\n요청")

    def test_a_hooks_own_arguments_reach_it_unchanged(self):
        """tutor-note 는 `claude brief` 처럼 인자로 자리가 갈린다. 디스패처가 인자를 하나 끼워
        넣으면 `sys.argv[2]` 가 밀려 `brief` 대신 `note` 화면이 뜬다 — 조각 인자는 그대로 간다."""
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [[bed.hook("e", _ECHO_ARGV), "claude", "brief"]]
            self.assertEqual(_context_of(bed.run("UserPromptSubmit", hooks)[1]), "claude|brief")


class TestFailOpen(unittest.TestCase):
    def test_a_hook_that_raises_does_not_take_the_others_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [
                bed.hook("a", _PLAIN % "첫째"),
                bed.hook("boom", _BOOM),
                bed.hook("c", _PLAIN % "셋째"),
            ]
            code, out, err = bed.run("UserPromptSubmit", hooks)
            self.assertEqual(code, 0)
            self.assertEqual(_context_of(out), "첫째\n셋째")
            # 삼킨다는 것까지 본다. `_run_one` 의 `except BaseException` 을 빼면 예외가 스레드
            # 밖으로 나가 threading 의 기본 훅이 stderr 에 역추적을 찍는데, 주입 결과는 그대로라
            # 출력만 보는 검사는 그 회귀를 못 잡는다.
            self.assertNotIn("Traceback", err)

    def test_a_hook_that_will_not_even_import_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [
                bed.hook("a", _PLAIN % "첫째"),
                bed.hook("broken", "def main(:\n"),  # 문법 오류 — 임포트에서 죽는다
                os.path.join(tmp, "absent.py"),  # 아예 없는 파일
                bed.hook("c", _PLAIN % "셋째"),
            ]
            code, out, _err = bed.run("UserPromptSubmit", hooks)
            self.assertEqual(code, 0)
            self.assertEqual(_context_of(out), "첫째\n셋째")

    def test_a_hook_that_exits_nonzero_does_not_block_the_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [
                bed.hook("a", _PLAIN % "첫째"),
                bed.hook("bail", "import sys\ndef main():\n    sys.exit(2)\n"),
            ]
            code, out, _err = bed.run("UserPromptSubmit", hooks)
            self.assertEqual(code, 0)  # 주입 훅에는 차단 권한이 없다 — 가드만 exit 2 를 쓴다
            self.assertEqual(_context_of(out), "첫째")

    def test_every_hook_stays_silent_and_the_dispatcher_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = _Bed(tmp)
            hooks = [bed.hook("q1", _SILENT), bed.hook("q2", _SILENT)]
            self.assertEqual(bed.run("UserPromptSubmit", hooks)[1], "")


class TestWiringBoundary(unittest.TestCase):
    """배선이 합쳐도 되는 것만 합치는가 — 이 시험이 항목 7 의 안전 경계다."""

    def setUp(self):
        self.config = json.loads(cc_settings())["hooks"]

    def _commands(self, event: str) -> list:
        return [h.get("command", "") for block in self.config[event] for h in block.get("hooks", [])]

    def _dispatched(self, event: str) -> list:
        """한 이벤트에서 디스패처가 안고 가는 훅 이름 — 명령줄에 적힌 경로 그대로.

        `doctor` 가 배선을 읽는 정규식과 같은 것을 쓴다. 이름만 적는 문법으로 바뀌면 이 시험이
        먼저 빈 목록을 보게 되고, 그건 진단이 13종을 못 보게 된다는 뜻이다."""
        names = []
        for command in self._commands(event):
            if "hook-dispatch.py" not in command:
                continue
            names += [n for n in _HOOK_IN_COMMAND.findall(command) if n != "hook-dispatch"]
        return names

    def test_no_guard_or_evidence_hook_is_inside_a_dispatch_segment(self):
        for event in self.config:
            merged = set(self._dispatched(event))
            self.assertEqual(merged & set(GUARDS), set(), f"{event}: 가드가 디스패처 안에 있다")
            self.assertEqual(merged & set(EVIDENCE), set(), f"{event}: 증거 훅이 디스패처 안에 있다")

    def test_pre_and_post_tool_use_keep_one_process_per_hook(self):
        """도구 호출 레인은 손대지 않는다 — PreToolUse 는 가드뿐이고 PostToolUse 는 합칠 것이 없다."""
        for event in ("PreToolUse", "PostToolUse", "SubagentStop"):
            for command in self._commands(event):
                self.assertNotIn("hook-dispatch.py", command, event)

    def test_no_hook_was_lost_in_the_move(self):
        """합치기는 프로세스만 줄인다 — 이벤트마다 닿는 훅 명단은 합치기 전과 같아야 한다.

        아래는 합치기 직전 `.claude/settings.json` 전수(26-08-14). 여기서 한 이름이 빠지면
        그 계층은 조용히 꺼지고, 꺼진 계층은 화면에 아무것도 안 띄운다."""
        expected = {
            "SessionStart": {
                "lagom-activate",
                "memory-activate",
                "charter-activate",
                "manual-activate",
                "agent-activate",
                "map-activate",
            },
            "UserPromptSubmit": {
                "budget-guard",
                "unattended-context",
                "lagom-tracker",
                "memory-activate",
                "charter-activate",
                "manual-activate",
                "agent-activate",
                "map-activate",
                "scope-activate",
                "siege-inbox",
                "tutor-note",
            },
            "SubagentStart": {
                "lagom-subagent",
                "charter-activate",
                "manual-activate",
                "agent-activate",
                "map-activate",
                "scope-activate",
                "dispatch-context",
                "verifier-context",
                "memory-activate",
                "subagent-gate",
            },
            "Stop": {"verifier-gate", "memory-activate", "map-activate", "failure-tracker", "tutor-note"},
        }
        for event, names in expected.items():
            reached = {n for command in self._commands(event) for n in _HOOK_IN_COMMAND.findall(command)}
            self.assertEqual(reached - {"hook-dispatch"}, names, event)

    def test_a_merged_hook_is_not_also_wired_on_its_own_in_the_same_event(self):
        """같은 이벤트에 두 번 걸리면 주입이 두 벌 간다 — 합치다 남긴 자리를 잡는다."""
        for event in self.config:
            merged = self._dispatched(event)
            self.assertEqual(len(merged), len(set(merged)), f"{event}: 디스패처 안에 같은 훅이 둘")
            standalone = {
                name
                for command in self._commands(event)
                if "hook-dispatch.py" not in command
                for name in _HOOK_IN_COMMAND.findall(command)
            }
            self.assertEqual(standalone & set(merged), set(), f"{event}: 합친 훅이 따로도 걸려 있다")


if __name__ == "__main__":
    unittest.main()
