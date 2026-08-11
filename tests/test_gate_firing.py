"""훅 발화 장부 — 어느 층이 아직 값을 하는지 세는 분모.

사건 장부(`.asgard/state/gate-events.jsonl`)는 발화한 순간만 적는다. 그래서 한 번도 발화하지
않은 훅과 아직 불린 적이 없는 훅이 같은 빈칸으로 보였고, 그 상태에서는 어느 층을 지울지 고를 수
없었다. 여기서 지키는 것은 넷이다: **발화 판정이 훅의 신고가 아니라 관측인가**, **계측이 훅의
출력과 종료 코드를 한 글자도 바꾸지 않는가**, **예외로 죽은 호출이 발화와 섞이지 않는가**,
그리고 **배선이 훅 하나도 빠뜨리지 않았는가**.

실행: uv run pytest tests/test_gate_firing.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from asgard.commands.doctor.gate import _FIRING_FLOOR, _firing_check
from asgard.hooks.asgard_hooklib import firing


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        os.makedirs(os.path.join(self.root, ".asgard", "state"))
        self.addCleanup(self.dir.cleanup)

    def gates(self) -> dict:
        return firing.load(self.root).get("gates", {})

    def drive(self, gate, fn):
        """래퍼를 돌리고 (호스트가 실제로 받은 출력, 종료 코드)를 준다."""
        seen = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            with contextlib.redirect_stdout(seen), self.assertRaises(SystemExit) as caught:
                firing.run(gate, fn)
        return seen.getvalue(), caught.exception.code


class Counting(Base):
    def test_silent_hook_counts_as_a_call_but_not_a_firing(self):
        self.drive("quiet-hook", lambda: None)
        self.assertEqual(self.gates()["quiet-hook"], {"calls": 1, "fires": 0, "last_call": mock.ANY})

    def test_output_is_what_makes_it_a_firing(self):
        """발화 판정은 훅이 무엇을 했다고 말하는지가 아니라 호스트가 무엇을 받았는지다."""
        self.drive("loud-hook", lambda: print("context"))
        row = self.gates()["loud-hook"]
        self.assertEqual((row["calls"], row["fires"]), (1, 1))
        self.assertIn("last_fire", row)

    def test_nonzero_exit_is_a_firing_even_with_no_output(self):
        def blocks():
            raise SystemExit(2)

        self.drive("blocking-guard", blocks)
        self.assertEqual(self.gates()["blocking-guard"]["fires"], 1)

    def test_counts_accumulate_across_calls(self):
        for _ in range(3):
            self.drive("mixed", lambda: None)
        self.drive("mixed", lambda: print("x"))
        row = self.gates()["mixed"]
        self.assertEqual((row["calls"], row["fires"]), (4, 1))

    def test_missing_state_dir_records_nothing(self):
        """asgard 를 안 쓰는 트리에서는 잴 자리가 없다 — 계측이 파일을 새로 만들지 않는다."""
        with tempfile.TemporaryDirectory() as bare:
            firing.record(bare, "somewhere", True)
            self.assertFalse(os.path.exists(firing.counter_path(bare)))

    def test_temp_file_is_per_process(self):
        """임시 이름을 공유하면 훅 둘이 겹칠 때 잃는 것이 카운트 몇 건이 아니라 누적 전체다.

        한쪽이 `os.replace` 로 tmp 를 살린 뒤 다른 쪽 fd 가 그 파일에 계속 쓰면 장부가 깨진
        JSON 이 되고, `load()` 는 거기서 빈 장부를 준다 — 되감긴 장부에서는 발화 없는 훅이
        `_FIRING_FLOOR` 에 영영 도달하지 못하므로 이 계측이 존재하는 이유가 사라진다."""
        seen: list[str] = []
        real_open = open

        def spy(path, *args, **kwargs):
            seen.append(str(path))
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", spy):
            firing.record(self.root, "concurrent", True)
        tmps = [p for p in seen if p.endswith(".tmp")]
        self.assertTrue(tmps, seen)
        self.assertIn(str(os.getpid()), tmps[0])

    def test_corrupt_counter_does_not_block_recording(self):
        with open(firing.counter_path(self.root), "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        firing.record(self.root, "after-corruption", True)
        self.assertEqual(self.gates()["after-corruption"]["fires"], 1)


class Failures(Base):
    def test_exception_is_not_swallowed(self):
        """훅 계약이 fail-open 이라 여기서 예외를 먹으면 죽은 층이 조용해진다."""

        def explodes():
            raise RuntimeError("hook body died")

        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            with self.assertRaises(RuntimeError):
                firing.run("broken-hook", explodes)

    def test_exception_counts_as_an_error_not_a_firing(self):
        def explodes():
            raise RuntimeError("hook body died")

        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            with contextlib.suppress(RuntimeError):
                firing.run("broken-hook", explodes)
        row = self.gates()["broken-hook"]
        self.assertEqual((row["calls"], row["fires"], row["errors"]), (1, 0, 1))


class Passthrough(Base):
    def test_output_reaches_the_host_byte_for_byte(self):
        payload = json.dumps({"hookSpecificOutput": {"additionalContext": "한글 · symbols"}})
        seen, _ = self.drive("injector", lambda: print(payload))
        self.assertEqual(seen, payload + "\n")

    def test_exit_code_survives(self):
        def blocks():
            raise SystemExit(2)

        _, code = self.drive("blocking-guard", blocks)
        self.assertEqual(code, 2)

    def test_returned_code_becomes_the_exit_code(self):
        _, code = self.drive("returns-zero", lambda: 0)
        self.assertEqual(code, 0)

    def test_output_survives_a_dying_body(self):
        """죽기 전에 이미 낸 것은 호스트가 받아야 한다 — 래퍼가 버퍼를 삼키면 안 된다."""

        def prints_then_dies():
            print("partial")
            raise RuntimeError("boom")

        seen = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            with contextlib.redirect_stdout(seen), contextlib.suppress(RuntimeError):
                firing.run("dies-mid-write", prints_then_dies)
        self.assertEqual(seen.getvalue(), "partial\n")


class Events(Base):
    def rows(self) -> list[dict]:
        path = os.path.join(self.root, ".asgard", "state", "gate-events.jsonl")
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_every_event_names_the_gate_that_raised_it(self):
        """사유별 집계는 어느 층을 고칠지 말해주지 않는다 — 주인 없는 차단 21건이 그 자리였다."""
        firing.event(self.root, "verifier", "gate_block", "stale-pass", ["app.py"])
        firing.event(self.root, "craft", "gate_skipped", "no-sentinel", sid="s1")
        self.assertEqual([r["gate"] for r in self.rows()], ["verifier", "craft"])

    def test_subject_records_what_the_block_was_about(self):
        firing.event(self.root, "verifier", "gate_block", "stale-pass", ["app.py", "lib.py"])
        self.assertEqual(self.rows()[0]["subject"], ["app.py", "lib.py"])

    def test_optional_fields_stay_absent_when_not_given(self):
        firing.event(self.root, "verifier", "gate_escalate", "over-cap")
        self.assertEqual(self.rows()[0], {"event": "gate_escalate", "gate": "verifier", "code": "over-cap"})


class Wiring(unittest.TestCase):
    """훅 목록을 여기 적지 않는다 — 목록은 훅이 하나 늘 때 조용히 낡고, 그 침묵이 이 장부가
    막으려는 병과 같다. 대신 디렉토리를 훑어 불변식을 본다."""

    EXEMPT = {"__init__.py", "quest_log.py"}  # quest-log 는 게이트가 아니라 Trinity CLI 다

    def hooks(self):
        hooks_dir = os.path.dirname(firing.__file__).replace(os.sep + "asgard_hooklib", "")
        for name in sorted(os.listdir(hooks_dir)):
            if name.endswith(".py") and name not in self.EXEMPT:
                with open(os.path.join(hooks_dir, name), encoding="utf-8") as handle:
                    yield name, handle.read()

    def test_every_hook_exits_through_the_wrapper(self):
        missing = [n for n, src in self.hooks() if "firing import" not in src or 'run("' not in src]
        self.assertFalse(missing, "발화 계측이 안 붙은 훅 — 이 층은 장부에서 보이지 않는다:\n" + "\n".join(missing))

    def test_gate_name_matches_the_deployed_filename(self):
        """doctor 가 부르는 이름과 사람이 여는 파일이 같아야 한다 (배포본은 하이픈)."""
        wrong = []
        for name, src in self.hooks():
            expected = 'run("' + name[:-3].replace("_", "-") + '"'
            if expected not in src:
                wrong.append(f"{name} — {expected} 를 기대했다")
        self.assertFalse(wrong, "게이트 이름이 파일명과 어긋난다:\n" + "\n".join(wrong))


class LiveHooks(Base):
    """배선한 훅을 실제 인터프리터로 한 번씩 돌린다.

    파일을 읽어서는 임포트가 서는지 알 수 없다. 이 저장소는 그 자리에서 이미 당했다 — 훅 안
    임포트가 배포 인터프리터에서 한 번도 서지 않았는데 시험이 `PYTHONPATH=src` 로 그 실패를
    가리고 있었다. 그래서 여기서는 경로를 한 칸도 보태지 않는다: 훅은 자기 폴더를 `sys.path[0]`
    으로 삼아 `asgard_hooklib` 을 찾아야 하고, 그 자립이 곧 배포 계약이다.

    stdin 은 빈 payload 라 훅 대부분은 할 일이 없다고 판단하고 끝난다 — 여기서 보는 것은 훅이
    무엇을 했는가가 아니라 **임포트 단계를 지났는가**다."""

    FATAL = ("ImportError", "ModuleNotFoundError", "SyntaxError", "NameError", "AttributeError")

    def test_every_wired_hook_imports_without_a_path_boost(self):
        import subprocess
        import sys

        hooks_dir = os.path.dirname(firing.__file__).replace(os.sep + "asgard_hooklib", "")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["CLAUDE_PROJECT_DIR"] = self.root
        broken = []
        ran = set()
        for name, _ in Wiring().hooks():
            try:
                proc = subprocess.run(
                    [sys.executable, os.path.join(hooks_dir, name)],
                    input="{}",
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=60,
                    cwd=self.root,
                )
            except subprocess.TimeoutExpired:
                continue  # 느린 훅은 이 시험의 관심사가 아니다 — 임포트는 이미 지났다
            ran.add(name[:-3].replace("_", "-"))
            hit = [e for e in self.FATAL if e in proc.stderr]
            if hit:
                broken.append(f"{name}: {hit[0]} — {proc.stderr.strip().splitlines()[-1][:120]}")
        self.assertFalse(
            broken, "훅이 임포트 단계에서 죽는다 (fail-open 이라 실사용에선 조용하다):\n" + "\n".join(broken)
        )
        # 여기가 배선의 실물 증거다 — 위까지는 "안 죽었다"만 말하고, 계측이 실제로 도는지는
        # 장부에 줄이 생겨야 알 수 있다. 훅이 할 일이 없다고 판단하고 끝나도 호출은 세어진다.
        self.assertEqual(ran - set(self.gates()), set(), "돌았는데 장부에 안 남은 훅이 있다")


class DoctorReport(Base):
    def write_counter(self, gates: dict) -> None:
        with open(firing.counter_path(self.root), "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "gates": gates}, handle)

    def detail(self) -> str:
        checks = _firing_check(self.root)
        self.assertEqual(len(checks), 1, checks)
        return checks[0]["detail"]

    def test_says_nothing_before_anything_is_measured(self):
        self.assertEqual(_firing_check(self.root), [])

    def test_names_a_hook_that_keeps_being_called_without_firing(self):
        self.write_counter({"idle-guard": {"calls": _FIRING_FLOOR, "fires": 0}})
        self.assertIn("idle-guard", self.detail())

    def test_stays_quiet_while_the_sample_is_too_small(self):
        """몇 번 불리고 안 잡힌 것은 아직 아무 말도 하지 않는다."""
        self.write_counter({"new-guard": {"calls": _FIRING_FLOOR - 1, "fires": 0}})
        self.assertNotIn("new-guard", self.detail())

    def test_a_firing_hook_is_never_listed_as_a_deletion_candidate(self):
        self.write_counter({"working-guard": {"calls": 500, "fires": 3}})
        detail = self.detail()
        self.assertNotIn("발화 없음", detail)
        self.assertIn("1개 발화", detail)

    def test_broken_hooks_fail_the_check_while_idle_ones_do_not(self):
        """고장은 조치 대상이고 발화 없음은 삭제 후보 목록이다 — 같은 칸에 넣지 않는다."""
        self.write_counter({"idle-guard": {"calls": 999, "fires": 0}})
        self.assertTrue(_firing_check(self.root)[0]["ok"])
        self.write_counter({"dying-guard": {"calls": 999, "fires": 0, "errors": 999}})
        self.assertFalse(_firing_check(self.root)[0]["ok"])


if __name__ == "__main__":
    unittest.main()
