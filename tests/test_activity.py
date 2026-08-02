"""활동 스트림 — 도는 동안 무엇을 하는지가 창까지 닿는가.

여기서 지키는 계약은 셋이다. ① 경로가 없으면 아무 일도 안 일어난다(관측이 실행을 막지
않는다). ② 반만 적힌 줄은 안 읽고 다음 차례에 온전하게 다시 만난다. ③ 여는 사건과 닫는
사건이 창에서 한 줄로 접힌다 — 도는 동안은 '지금', 끝나면 소요시간을 단 기록.
"""

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from asgard import activity
from asgard.commands import studio


class ActivityEmitCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="asgard-activity-")
        self.target = os.path.join(self.folder, "events.jsonl")
        activity._stopped = False
        activity._seq = 0

    def _rows(self):
        rows, _ = activity.read_log(self.target)
        return rows

    def test_no_path_is_no_op(self):
        """경로가 없으면 조용히 아무것도 안 한다 — 터미널 세션이 파일을 만들면 안 된다."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(activity.ENV_PATH, None)
            self.assertFalse(activity.enabled())
            activity.emit("tool.start", name="bash")  # 던져도 아무 일 없음
        self.assertFalse(os.path.exists(self.target))

    def test_emit_writes_one_json_line_each(self):
        with mock.patch.dict(os.environ, {activity.ENV_PATH: self.target}):
            activity.emit("tool.start", id="c1", sym="$", detail="uv run pytest")
            activity.emit("tool.end", id="c1", ok=True, secs=1.4)
        rows = self._rows()
        self.assertEqual([r["kind"] for r in rows], ["tool.start", "tool.end"])
        self.assertEqual(rows[0]["detail"], "uv run pytest")
        self.assertEqual(rows[1]["secs"], 1.4)
        self.assertEqual([r["seq"] for r in rows], [1, 2])

    def test_empty_values_are_dropped(self):
        """빈 값은 안 넣는다 — 창이 `role: ''`을 역할 이름으로 그리면 빈 칸이 생긴다."""
        with mock.patch.dict(os.environ, {activity.ENV_PATH: self.target}):
            activity.emit("tool.start", id="c1", role="", agent=None, sym="$")
        row = self._rows()[0]
        self.assertNotIn("role", row)
        self.assertNotIn("agent", row)
        self.assertEqual(row["sym"], "$")

    def test_emit_never_raises_on_bad_path(self):
        """못 적어도 실행은 계속된다. 관측이 예외를 올리면 그건 관측이 아니라 관문이다."""
        with mock.patch.dict(os.environ, {activity.ENV_PATH: os.path.join(self.folder, "no", "such", "f.jsonl")}):
            activity.emit("tool.start", name="bash")  # 예외 없이 통과해야 한다

    def test_parallel_writers_do_not_interleave(self):
        """wave·편대는 병렬로 부른다 — 한 줄이 반씩 섞이면 소비자가 통째로 못 읽는다."""
        with mock.patch.dict(os.environ, {activity.ENV_PATH: self.target}):
            threads = [
                threading.Thread(target=lambda i=i: [activity.emit("tool.start", id=f"c{i}", detail="x" * 200)] * 1)
                for i in range(16)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        rows = self._rows()
        self.assertEqual(len(rows), 16)
        self.assertTrue(all(r["detail"] == "x" * 200 for r in rows))


class ActivityReadCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="asgard-activity-read-")
        self.target = os.path.join(self.folder, "events.jsonl")

    def test_partial_trailing_line_is_left_for_next_read(self):
        """반만 적힌 마지막 줄은 안 읽고 offset도 안 옮긴다 — 그 사건이 유실되면 안 된다."""
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "tool.start", "id": "c1"}) + "\n")
            fh.write('{"kind": "tool.e')  # 아직 안 닫힌 줄
        rows, offset = activity.read_log(self.target)
        self.assertEqual([r["kind"] for r in rows], ["tool.start"])
        with open(self.target, "a", encoding="utf-8") as fh:
            fh.write('nd", "id": "c1"}\n')
        rows, _ = activity.read_log(self.target, offset)
        self.assertEqual([r["kind"] for r in rows], ["tool.end"])

    def test_read_resumes_from_offset_without_repeats(self):
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "a"}) + "\n")
        rows, offset = activity.read_log(self.target)
        self.assertEqual(len(rows), 1)
        rows, offset = activity.read_log(self.target, offset)
        self.assertEqual(rows, [])
        with open(self.target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "b"}) + "\n")
        rows, _ = activity.read_log(self.target, offset)
        self.assertEqual([r["kind"] for r in rows], ["b"])

    def test_corrupt_line_is_skipped_not_fatal(self):
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write("not json\n")
            fh.write(json.dumps({"kind": "ok"}) + "\n")
        rows, _ = activity.read_log(self.target)
        self.assertEqual([r["kind"] for r in rows], ["ok"])

    def test_missing_file_reads_empty(self):
        rows, offset = activity.read_log(os.path.join(self.folder, "absent.jsonl"), 0)
        self.assertEqual((rows, offset), ([], 0))

    def test_open_log_creates_and_prunes(self):
        root = tempfile.mkdtemp(prefix="asgard-activity-root-")
        made = [activity.open_log(root, f"task{i}") for i in range(activity._KEEP + 5)]
        folder = os.path.dirname(made[0])
        left = [n for n in os.listdir(folder) if n.endswith(".jsonl")]
        self.assertLessEqual(len(left), activity._KEEP)
        self.assertTrue(os.path.exists(made[-1]))  # 방금 연 것은 반드시 살아 있다
        # `.asgard/`는 저장소에 안 샌다 — 활동 파일이 그 폴더의 첫 기록자여도
        with open(os.path.join(root, ".asgard", ".gitignore"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "*")


class StudioAbsorbCase(unittest.TestCase):
    """읽어 온 사건이 창이 그릴 수 있는 모양으로 접히는가."""

    def setUp(self):
        with studio.state._TASK_LOCK:
            studio.state._TASKS.clear()
            studio.state._TASKS["t1"] = {"id": "t1", "status": "running", "activity": [], "now": None}

    def _task(self):
        with studio.state._TASK_LOCK:
            return dict(studio.state._TASKS["t1"])

    def test_start_then_end_folds_into_one_row(self):
        studio.tasks._absorb("t1", [{"kind": "tool.start", "id": "c1", "sym": "$", "detail": "pytest", "ts": 100.0}])
        live = self._task()
        self.assertEqual(live["now"]["detail"], "pytest")
        self.assertEqual(live["activity"], [])  # 도는 동안은 '지금'일 뿐 기록이 아니다
        studio.tasks._absorb("t1", [{"kind": "tool.end", "id": "c1", "ok": True, "secs": 2.1, "ts": 102.1}])
        live = self._task()
        self.assertIsNone(live["now"])
        self.assertEqual(len(live["activity"]), 1)
        row = live["activity"][0]
        self.assertEqual((row["sym"], row["detail"], row["secs"], row["ok"]), ("$", "pytest", 2.1, True))
        self.assertEqual(row["ts"], 100.0)  # 시작 시각을 쓴다 — 목록은 시작 순서로 읽힌다

    def test_unmatched_end_is_kept(self):
        """짝을 못 찾은 완료도 남긴다 — 놓친 시작보다 잘못 지운 완료가 화면을 더 망친다."""
        studio.tasks._absorb("t1", [{"kind": "tool.end", "id": "zz", "ok": False, "secs": 0.4}])
        rows = self._task()["activity"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])

    def test_failed_tool_keeps_ok_false(self):
        studio.tasks._absorb("t1", [{"kind": "tool.start", "id": "c1", "sym": "$", "detail": "bad", "ts": 1.0}])
        studio.tasks._absorb("t1", [{"kind": "tool.end", "id": "c1", "ok": False, "secs": 0.2}])
        self.assertFalse(self._task()["activity"][0]["ok"])

    def test_role_sets_step_and_leaves_a_trail(self):
        studio.tasks._absorb("t1", [{"kind": "role", "role": "WORKER", "why": "배정 단위 1", "ts": 5.0}])
        live = self._task()
        self.assertEqual(live["step"], {"role": "WORKER", "why": "배정 단위 1"})
        self.assertEqual(live["activity"][0]["kind"], "role")

    def test_todo_replaces_whole_board(self):
        """보드는 전체 상태로 온다 — 놓친 줄이 있어도 마지막 한 건이면 화면이 복원된다."""
        studio.tasks._absorb("t1", [{"kind": "todo", "items": [{"id": "u1", "text": "a", "state": "todo"}]}])
        studio.tasks._absorb("t1", [{"kind": "todo", "items": [{"id": "u1", "text": "a", "state": "done"}]}])
        todos = self._task()["todos"]
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["state"], "done")

    def test_run_end_clears_the_live_row(self):
        studio.tasks._absorb("t1", [{"kind": "tool.start", "id": "c1", "sym": "$", "detail": "x", "ts": 1.0}])
        studio.tasks._absorb("t1", [{"kind": "run.end", "ok": True}])
        self.assertIsNone(self._task()["now"])

    def test_activity_is_capped(self):
        rows = []
        for i in range(studio.tasks._ACTIVITY_CAP + 40):
            rows += [
                {"kind": "tool.start", "id": f"c{i}", "sym": "$", "detail": f"cmd{i}", "ts": float(i)},
                {"kind": "tool.end", "id": f"c{i}", "ok": True, "secs": 0.1},
            ]
        studio.tasks._absorb("t1", rows)
        log = self._task()["activity"]
        self.assertEqual(len(log), studio.tasks._ACTIVITY_CAP)
        self.assertEqual(log[-1]["detail"], f"cmd{studio.tasks._ACTIVITY_CAP + 39}")  # 최신이 남는다

    def test_absorb_on_unknown_task_is_silent(self):
        studio.tasks._absorb("gone", [{"kind": "tool.start", "id": "c1"}])  # 예외 없이 통과


class SessionEmitCase(unittest.TestCase):
    """실제 툴 실행 경로가 사건을 흘리는가 — 여기가 터미널과 창이 갈라지는 단일 초크포인트다."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="asgard-activity-session-")
        self.target = os.path.join(self.root, "events.jsonl")
        activity._stopped = False
        activity._seq = 0

    def _session(self):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        return AgentSession(None, rp, self.root, "sys", role="worker")

    def test_execute_emits_start_and_end_with_the_terminal_vocabulary(self):
        from asgard.agent.session import SessionResult, _Call

        session = self._session()
        result = SessionResult(text="", stop_reason="")
        with mock.patch.dict(os.environ, {activity.ENV_PATH: self.target}):
            session._execute(_Call("c1", "bash", {"command": "echo hi"}), result)
        rows, _ = activity.read_log(self.target)
        kinds = [r["kind"] for r in rows]
        self.assertIn("tool.start", kinds)
        self.assertIn("tool.end", kinds)
        start = next(r for r in rows if r["kind"] == "tool.start")
        # 창이 받는 값은 독의 상태 행이 쓰는 바로 그 (기호, 한 줄)이다 — 창 전용 문구가 아니다
        self.assertEqual(start["sym"], "$")
        self.assertEqual(start["detail"], "echo hi")
        self.assertEqual(start["role"], "worker")
        self.assertEqual(start["id"], "c1")
        end = next(r for r in rows if r["kind"] == "tool.end")
        self.assertEqual(end["id"], "c1")
        self.assertTrue(end["ok"])
        self.assertIsInstance(end["secs"], (int, float))

    def test_failed_tool_reports_not_ok(self):
        from asgard.agent.session import SessionResult, _Call

        session = self._session()
        result = SessionResult(text="", stop_reason="")
        with mock.patch.dict(os.environ, {activity.ENV_PATH: self.target}):
            # 경로 탈출은 툴 층이 거부한다 — 실패가 창까지 실패로 도착해야 한다
            session._execute(_Call("c9", "str_replace_based_edit_tool", {"command": "view", "path": "../../x"}), result)
        rows, _ = activity.read_log(self.target)
        end = next(r for r in rows if r["kind"] == "tool.end")
        # False는 값이다 — 빼 버리면 창이 실패한 도구를 성공으로 그린다 (빈 문자열·None만 뺀다)
        self.assertIs(end["ok"], False)

    def test_terminal_session_writes_nothing(self):
        """경로가 없는 세션(= 사람이 보는 터미널)은 파일을 안 만든다."""
        from asgard.agent.session import SessionResult, _Call

        session = self._session()
        result = SessionResult(text="", stop_reason="")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(activity.ENV_PATH, None)
            session._execute(_Call("c1", "bash", {"command": "echo hi"}), result)
        self.assertFalse(os.path.exists(self.target))


class StudioLiveRunCase(unittest.TestCase):
    """진짜 자식 프로세스를 띄워서 — 창이 **끝나기 전에** 무슨 일인지 아는가.

    여기가 이 기능의 요점이다. 여태 `_run_task`는 `communicate()`로 자식이 끝나기를 기다렸고,
    그동안 창이 가진 것은 상태 문자열 하나뿐이었다. 이 판은 자식이 아직 도는 동안 창의 작업
    사전에 '지금 이 도구를 쓰는 중'이 들어오는지를 실제 프로세스로 확인한다."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="asgard-activity-run-")
        with studio.state._TASK_LOCK:
            studio.state._TASKS.clear()

    def _child(self, script: str) -> list[str]:
        import sys

        return [sys.executable, "-c", script]

    def test_activity_reaches_the_window_while_the_child_is_still_running(self):
        # 자식은 사건을 적고, 창이 그것을 봤다는 표시(파일)를 기다린 뒤에야 끝난다 —
        # 이 순서가 성립해야 '끝나기 전에 보인다'가 증명된다.
        gate = os.path.join(self.root, "seen.flag")
        script = (
            "import json,os,time\n"
            "p=os.environ['ASGARD_EVENT_LOG']\n"
            "def w(o):\n"
            "    f=open(p,'a',encoding='utf-8');f.write(json.dumps(o)+'\\n');f.close()\n"
            "w({'kind':'role','role':'WORKER','why':'배정 단위 1'})\n"
            "w({'kind':'tool.start','id':'c1','sym':'$','detail':'uv run pytest -q','ts':time.time()})\n"
            f"gate={gate!r}\n"
            "for _ in range(300):\n"
            "    if os.path.exists(gate): break\n"
            "    time.sleep(0.05)\n"
            "w({'kind':'tool.end','id':'c1','ok':True,'secs':1.2})\n"
            "print(json.dumps({'result':'끝','tokens':7}))\n"
        )
        with studio.state._TASK_LOCK:
            studio.state._TASKS["live"] = {
                "id": "live",
                "status": "queued",
                "created": 1,
                "updated": 1,
                "root": self.root,
                "command": self._child(script),
                "turns": [],
            }
        runner = threading.Thread(target=studio.tasks._run_task, args=("live", self.root), daemon=True)
        runner.start()
        try:
            live = self._await(lambda t: t.get("now") is not None, "자식이 도는 동안 '지금'이 안 채워졌다")
            self.assertEqual(live["now"]["detail"], "uv run pytest -q")
            self.assertEqual(live["now"]["sym"], "$")
            self.assertEqual(live["step"]["role"], "WORKER")  # 실제로 밟은 단계 — 고정 레일이 아니다
            self.assertEqual(live["status"], "running")
        finally:
            with open(gate, "w"):  # 자식을 놓아 준다
                pass
            runner.join(timeout=30)
        with studio.state._TASK_LOCK:
            done = dict(studio.state._TASKS["live"])
        self.assertEqual(done["status"], "ready")
        self.assertIsNone(done["now"])  # 끝난 작업에 '지금'이 남으면 화면이 안 멈춘다
        tools = [r for r in done["activity"] if r["kind"] == "tool"]
        self.assertEqual(len(tools), 1)
        self.assertEqual((tools[0]["detail"], tools[0]["secs"], tools[0]["ok"]), ("uv run pytest -q", 1.2, True))

    def test_last_event_is_not_lost_at_exit(self):
        """자식이 끝나는 순간에 적힌 마지막 줄도 읽는다 — 감시가 신호만 보고 그만두면 늘 빠진다."""
        script = (
            "import json,os\n"
            "p=os.environ['ASGARD_EVENT_LOG']\n"
            "f=open(p,'a',encoding='utf-8')\n"
            "f.write(json.dumps({'kind':'tool.start','id':'z','sym':'→','detail':'read a.py','ts':1.0})+'\\n')\n"
            "f.write(json.dumps({'kind':'tool.end','id':'z','ok':True,'secs':0.3})+'\\n')\n"
            "f.close()\n"
            "print(json.dumps({'result':'끝'}))\n"
        )
        with studio.state._TASK_LOCK:
            studio.state._TASKS["quick"] = {
                "id": "quick",
                "status": "queued",
                "created": 1,
                "updated": 1,
                "root": self.root,
                "command": self._child(script),
                "turns": [],
            }
        studio.tasks._run_task("quick", self.root)
        with studio.state._TASK_LOCK:
            done = dict(studio.state._TASKS["quick"])
        tools = [r for r in done["activity"] if r["kind"] == "tool"]
        self.assertEqual([t["detail"] for t in tools], ["read a.py"])

    def _await(self, predicate, message, timeout=30.0):
        import time as _t

        deadline = _t.monotonic() + timeout
        while _t.monotonic() < deadline:
            with studio.state._TASK_LOCK:
                live = dict(studio.state._TASKS["live"])
            if predicate(live):
                return live
            _t.sleep(0.05)
        self.fail(message)


class ConcurrentLabelCase(unittest.TestCase):
    """편대가 도는 동안 독의 한 줄이 넷을 다 말하는가."""

    def _label(self, rows):
        from asgard.agent.heimdall.core import _concurrent_label

        return _concurrent_label(rows)

    def test_single_session_reads_as_before(self):
        self.assertEqual(self._label([{"role": "worker", "status": "$ pytest"}]), "worker · $ pytest")

    def test_single_session_without_status(self):
        self.assertEqual(self._label([{"role": "worker", "status": ""}]), "worker")

    def test_every_concurrent_session_is_named(self):
        rows = [{"role": f"thor:u{i}", "status": f"$ cmd{i}"} for i in range(3)]
        label = self._label(rows)
        self.assertTrue(label.startswith("×3 "))
        for i in range(3):
            self.assertIn(f"thor:u{i}", label)  # 뒤쪽이 통째로 잘려 나가면 안 된다


if __name__ == "__main__":
    unittest.main()
