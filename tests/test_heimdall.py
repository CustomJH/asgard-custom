#!/usr/bin/env python3
"""Heimdall _trinity/_classify 오케스트레이션 하네스 (CUS-175) — mocked AgentSession, API 호출 0.

FakeSession 이 스크립트된 응답·verdict 툴콜·관측 커맨드를 돌려주고, effect 로 워킹트리를 실제로
바꾼다 (diff-hash 물리 검증은 진짜 quest-log/gate subprocess 가 수행 — 배포 형태 그대로).

커버 경로: 해피패스 / verifier ESCALATE 전이(CUS-171) / structural FAIL→재계획(CUS-171) /
재시도 실패 컨텍스트(CUS-172) / no-verdict·무증거 PASS 합성 FAIL(CUS-173) /
게이트 차단 수리→동일 사유 ESCALATE(CUS-174) / classify 기본값·destructive 거부.

실행: uv run pytest tests/test_heimdall.py
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from asgard.agent.heimdall import Heimdall
from asgard.agent.session import SessionResult
from asgard.providers import PROVIDERS, ResolvedProvider

CLS_WRITE = {
    "write_expected": True,
    "ambiguous": False,
    "destructive": False,
    "external_research": False,
    "shared": False,
    "criteria": ["w1.txt 생성 확인"],
}


class FakeSession:
    """AgentSession 대역 — run() 이 스크립트 결과 반환 + effect 로 워킹트리 변경."""

    def __init__(self, result: SessionResult, effect=None, label=""):
        self.result, self.effect, self.label = result, effect, label
        self.prompt: str | None = None
        self.role: str | None = None

    def run(self, user_content: str) -> SessionResult:
        self.prompt = user_content
        if self.effect:
            self.effect()
        return self.result


class FakeHeimdall(Heimdall):
    """_session 을 스크립트 큐로 대체 — 소비 순서·프롬프트를 검증 표면으로 노출."""

    def __init__(self, root: str, sessions: list[FakeSession], cls: dict | None = None, model: str = "claude-x"):
        import threading

        self._lock = threading.Lock()
        self._script = list(sessions)
        self.consumed: list[FakeSession] = []
        self._cls = cls
        default = ResolvedProvider(profile=PROVIDERS["anthropic"], model=model, api_key="k")
        self.texts: list[str] = []
        super().__init__(default, root, on_text=self.texts.append)

    def _session(self, system, extra_tools=None, handlers=None, quiet=False, role=None, model=None):
        with self._lock:  # wave 병렬 스레드가 동시에 pop — 순서 보호
            if not self._script:
                raise AssertionError("스크립트된 세션 소진 — 예상보다 많은 역할 턴")
            s = self._script.pop(0)
            s.role = role
            s.model = model
            self.consumed.append(s)
            return s

    def _classify(self, request):
        if self._cls is None:
            return super()._classify(request)
        return dict(self._cls)


def worker(files: dict[str, str] | None = None, root: str = "", text: str = "done"):
    def effect():
        for rel, body in (files or {}).items():
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p) or root, exist_ok=True)
            open(p, "w").write(body)

    return FakeSession(
        SessionResult(
            text=text,
            stop_reason="end_turn",
            commands=[{"cmd": "true", "exit_code": 0}],
            writes=list(files or {}),
        ),
        effect=effect,
        label="worker",
    )


def verifier(verdict="PASS", observed=True, structural=False, sig=None, why="", no_tool=False):
    tool_calls = []
    if not no_tool:
        inp = {"verdict": verdict, "criteria": CLS_WRITE["criteria"], "commands": [{"cmd": "fake", "exit_code": 0}]}
        if structural:
            inp["structural"] = True
        if sig:
            inp["failure_sig"] = sig
        if why:
            inp["why"] = why
        tool_calls = [{"name": "verdict", "input": inp}]
    return FakeSession(
        SessionResult(
            text="verified",
            stop_reason="end_turn",
            commands=[{"cmd": "pytest -q", "exit_code": 0}] if observed else [],
            tool_calls=tool_calls,
        ),
        label="verifier",
    )


def thinker(plan="계획: w1.txt 를 만든다", commands=None):
    return FakeSession(SessionResult(text=plan, stop_reason="end_turn", commands=commands or []), label="thinker")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.root  # 글로벌 config 오염 차단

        def run(*a):
            subprocess.run(a, cwd=self.root, capture_output=True, check=True)

        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        open(os.path.join(self.root, "f.txt"), "w").write("base\n")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "init")

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        self._tmp.cleanup()

    def quest_log_text(self):
        d = os.path.join(self.root, ".asgard", "quest")
        out = []
        for f in sorted(os.listdir(d)):
            if f.endswith(".jsonl"):
                out.append(open(os.path.join(d, f)).read())
        return "\n".join(out)


class TestTrinityLoop(Base):
    def test_happy_path_closes_quest_with_report(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertIn("증거", out)  # 구조화 보고 (CUS-183)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier"])

    def test_verifier_escalate_reaches_odin_without_worker_spin(self):
        # CUS-171: ESCALATE 데드스테이트 — 이전엔 WORKER 폴스루로 12턴 공회전
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("ESCALATE")], cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn("Odin 결정 필요", out)
        self.assertEqual(len(h.consumed), 2)  # ESCALATE 후 추가 역할 턴 없음

    def test_structural_fail_goes_straight_to_replan(self):
        # CUS-171: structural FAIL → 3-strike 없이 THINKER_REPLAN
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="wrong-approach", why="접근 자체가 틀림"),
            thinker("재설계 계획"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        labels = [s.label for s in h.consumed]
        self.assertEqual(labels, ["worker", "verifier", "thinker", "worker", "verifier"])
        replan = h.consumed[2]
        self.assertIn("실패 이력", replan.prompt)
        self.assertIn("wrong-approach", replan.prompt)

    def test_retry_gets_failure_context(self):
        # CUS-172: FAILED/Diagnosis 재디스패치 — 백지 재작업 금지
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", sig="test-fails", why="assert 1==2 실패"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        retry = h.consumed[2]
        self.assertIn("FAILED: test-fails", retry.prompt)
        self.assertIn("assert 1==2", retry.prompt)

    def test_no_verdict_synthesizes_fail(self):
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier(no_tool=True),
            worker({"w1.txt": "y\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertIn("no-verdict-submitted", self.quest_log_text())

    def test_evidenceless_pass_becomes_fail(self):
        # CUS-173: 관측 성공 명령 없는 PASS = 무효 — FAIL 합성 + 관측 커맨드만 기록
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier("PASS", observed=False),
            worker({"w1.txt": "y\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        log = self.quest_log_text()
        self.assertIn("no-verification-evidence", log)
        self.assertNotIn('"cmd":"fake"', log.replace(" ", ""))  # 자가보고 commands 미기록

    def test_verify_event_records_harness_observed_commands(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        ver = [e for e in events if e.get("event") == "verify"][-1]
        self.assertEqual([c["cmd"] for c in ver["commands"]], ["pytest -q"])  # 관측만, 자가보고 아님

    def test_gate_same_reason_twice_escalates(self):
        # CUS-174: 무수리 fail-open 위장 제거 — 동일 사유 2회 차단 → 정직한 ESCALATE
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier("PASS"),
            verifier("PASS"),  # 게이트 수리 재검증 턴
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        with mock.patch("asgard.agent.heimdall.gate", return_value=(True, "stale PASS — 물리 대조 불일치")):
            out = h.handle("w1.txt 만들어")
        self.assertIn("Odin 결정 필요", out)
        self.assertIn("stale-pass", out)
        self.assertNotIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier", "verifier"])

    def test_gate_block_then_repair_passes(self):
        # 첫 차단은 수리 턴(재검증)으로 회복 — 보고에 차단 이력 표기
        seq = [worker({"w1.txt": "x\n"}, self.root), verifier("PASS"), verifier("PASS")]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        real_gate = [(True, "stale PASS — 물리 대조 불일치"), (False, "")]
        with mock.patch("asgard.agent.heimdall.gate", side_effect=real_gate):
            out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertIn("차단 1회", out)


OPUS_DEFAULT = PROVIDERS["anthropic"].default_model  # 티어 매핑은 기본 모델일 때만 적용


class TestModelTiers(Base):
    """상황별 모델 티어 (CUS-177) — opus/fable/sonnet/haiku 를 역할·상황이 결정."""

    def _h(self, sessions=None, model=OPUS_DEFAULT):
        return FakeHeimdall(self.root, sessions or [], cls=CLS_WRITE, model=model)

    def test_policy_tiers_map_roles_to_models(self):
        h = self._h()
        self.assertEqual(h._model_for("worker"), "claude-sonnet-5")
        self.assertEqual(h._model_for("thinker"), "claude-opus-4-8")
        self.assertEqual(h._model_for("verifier"), "claude-opus-4-8")
        self.assertEqual(h._model_for("verifier", bump=True), "claude-fable-5")  # full-verify 승급

    def test_delivery_tiers(self):
        h = self._h()
        self.assertEqual(h._delivery_model("freyja"), "claude-sonnet-5")
        self.assertEqual(h._delivery_model("thor"), "claude-sonnet-5")
        self.assertEqual(h._delivery_model("loki"), "claude-haiku-4-5-20251001")

    def test_explicit_placement_wins_over_tier(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n'
        )
        h = self._h()
        self.assertIsNone(h._model_for("worker"))  # placement 존중 — 스왑 없음
        self.assertEqual(Heimdall._session(h, "sys", role="worker").rp.model, "m1")

    def test_user_custom_model_not_overridden(self):
        h = self._h(model="claude-x")  # 사용자가 기본 모델을 바꿈 — 티어 매핑 비활성
        self.assertIsNone(h._model_for("worker"))
        self.assertIsNone(h._delivery_model("loki"))

    def test_session_model_override_swaps_model_only(self):
        h = self._h()
        # FakeHeimdall 은 _session 을 대체하므로 실제 구현을 직접 호출
        s = Heimdall._session(h, "sys", role="worker", model="claude-sonnet-5")
        self.assertEqual(s.rp.model, "claude-sonnet-5")
        self.assertEqual(s.rp.profile.name, "anthropic")
        self.assertEqual(h.role_rp["worker"].model, OPUS_DEFAULT)  # 원본 불변

    def test_worker_turn_uses_standard_tier(self):
        h = self._h([worker({"w1.txt": "x\n"}, self.root), verifier("PASS")])
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertEqual(h.consumed[0].model, "claude-sonnet-5")  # worker=standard
        self.assertEqual(h.consumed[1].model, "claude-opus-4-8")  # verifier micro=high

    def test_quest_events_record_used_model(self):
        # CUS-177 → CUS-127 데이터 축: 실사용 provider:model 이 로그에 남는다
        h = self._h([worker({"w1.txt": "x\n"}, self.root), verifier("PASS")])
        h.handle("w1.txt 만들어")
        d = os.path.join(self.root, ".asgard", "quest")
        log = "\n".join(open(os.path.join(d, f)).read() for f in os.listdir(d) if f.endswith(".jsonl"))
        self.assertIn("anthropic:claude-sonnet-5", log)  # work 이벤트
        self.assertIn("anthropic:claude-opus-4-8", log)  # verify 이벤트

    def test_second_replan_uses_thinker_alt_placement(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker_alt]\nprovider = "ollama"\nmodel = "alt-m"\n'
        )
        seq = [
            worker({"w1.txt": "a\n"}, self.root),
            verifier("FAIL", structural=True, sig="s1"),
            thinker("재계획 1"),
            worker({"w1.txt": "b\n"}, self.root),
            verifier("FAIL", structural=True, sig="s2"),
            thinker("재계획 2 — clean slate"),
            worker({"w1.txt": "c\n"}, self.root),
            verifier("PASS"),
        ]
        h = self._h(seq)
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        thinkers = [s for s in h.consumed if s.label == "thinker"]
        self.assertEqual(thinkers[0].role, "thinker")  # 1차 재계획 = 기본 배치
        self.assertEqual(thinkers[1].role, "thinker_alt")  # 2차 = clean-slate 대체 모델


class TestClassify(Base):
    def test_parse_failure_defaults_to_gated_write(self):
        h = FakeHeimdall(self.root, [], cls=None)
        h._complete_text = lambda *a, **k: "이건 JSON 이 아님"
        d = Heimdall._classify(h, "뭔가 대충 처리해줘")  # 휴리스틱 불확정 → LLM 폴백 → 파싱 실패
        self.assertTrue(d["write_expected"] and d["ambiguous"])  # 안전 기본값 → 게이트 경로
        self.assertEqual(d["task_class"], "deep")  # 미상 = 최대 예산

    def test_destructive_refused_without_sessions(self):
        cls = dict(CLS_WRITE, destructive=True)
        h = FakeHeimdall(self.root, [], cls=cls)
        out = h.handle("전부 지워")
        self.assertIn("파괴 작업 감지", out)
        self.assertEqual(h.consumed, [])


class TestClassifyHeuristic(Base):
    """결정론 pre-LLM 분류 (CUS-179) — 명백 케이스 LLM 호출 0."""

    def test_obvious_cases_no_llm(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        read_only = [
            "이 함수 설명해줘",
            "왜 여기서 에러가 나지?",
            "what does this function do",
            "README 요약해줘",
            "파일이 몇 개 있어?",
        ]
        writes = [
            "app.py 만들어줘",
            "버그 고쳐",
            "테스트 추가해줘",
            "implement the parser in parser.py",
            "이 모듈 리팩터해줘",
        ]
        destructive = ["rm -rf ./build 실행해", "git push --force 해", "임시 파일 다 지워"]
        for q in read_only:
            d = ch(q)
            self.assertIsNotNone(d, q)
            self.assertFalse(d["write_expected"], q)
        for q in writes:
            d = ch(q)
            self.assertIsNotNone(d, q)
            self.assertTrue(d["write_expected"], q)
            self.assertFalse(d["destructive"], q)
        for q in destructive:
            d = ch(q)
            self.assertIsNotNone(d, q)
            self.assertTrue(d["destructive"], q)

    def test_ambiguous_falls_back_to_llm(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        self.assertIsNone(ch("로그인 화면이 이상함"))  # 동사 신호 없음
        self.assertIsNone(ch("버그 설명해주고 고쳐줘"))  # read+write 혼재

    def test_classify_uses_heuristic_without_client_call(self):
        h = FakeHeimdall(self.root, [], cls=None)

        def boom(*a, **k):
            raise AssertionError("LLM 호출 금지 — 휴리스틱이 처리해야 함")

        h._complete_text = boom
        d = Heimdall._classify(h, "이 함수 설명해줘")
        self.assertFalse(d["write_expected"])

    def test_telemetry_logged(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        log = open(os.path.join(self.root, ".asgard", "classify.jsonl")).read()
        self.assertIn('"route": "trinity"', log.replace('":"', '": "'))


class TestErrorRecovery(Base):
    """API 오류 회복 (CUS-180) — recovery-hint 분류 + 백오프 + 폴백."""

    class _Boom(Exception):
        def __init__(self, status=None):
            super().__init__("boom")
            if status is not None:
                self.status_code = status

    def test_retryable_backs_off_then_succeeds(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        sleeps: list[float] = []
        h._sleep = sleeps.append
        ok = SessionResult(text="ok", stop_reason="end_turn")
        attempts = []

        class S:
            def run(_, p):
                attempts.append(1)
                if len(attempts) < 3:
                    raise self._Boom(429)
                return ok

        r = h._run_turn(lambda: S(), "p")
        self.assertEqual(r.text, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(sleeps), 2)  # jittered backoff 2회

    def test_fatal_raises_immediately(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        attempts = []

        class S:
            def run(_, p):
                attempts.append(1)
                raise self._Boom(401)

        with self.assertRaises(self._Boom):
            h._run_turn(lambda: S(), "p")
        self.assertEqual(len(attempts), 1)  # 재시도 0

    def test_fatal_uses_fallback_once(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        ok = SessionResult(text="fb", stop_reason="end_turn")

        class Bad:
            def run(_, p):
                raise self._Boom(401)

        class Good:
            def run(_, p):
                return ok

        r = h._run_turn(lambda: Bad(), "p", fallback=lambda: Good())
        self.assertEqual(r.text, "fb")

    def test_trinity_exception_reports_dangling_quest(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)  # 세션 스크립트 없음 → 첫 역할 턴에서 예외
        out = h.handle("w1.txt 만들어")
        self.assertIn("Trinity 중단", out)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_dangling_active_warned_on_init(self):
        os.makedirs(os.path.join(self.root, ".asgard", "quest"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "quest", "ACTIVE"), "w").write("old-quest\n")
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        self.assertTrue(any("미완 퀘스트" in t for t in h.texts))


class TestBudget(Base):
    """budget priors 배선 (CUS-181) — task-class 턴 예산 + 80% 자기규제 + grace 판정."""

    def _cls(self):
        return dict(CLS_WRITE, task_class="trivial")  # trivial=1 → 최소 순환 3 으로 클램프

    def test_grace_verifier_completes_after_budget(self):
        seq = [
            worker({"w1.txt": "a\n"}, self.root),  # t1
            verifier("FAIL", sig="s1"),  # t2
            worker({"w1.txt": "b\n"}, self.root),  # t3 (예산 마지막)
            verifier("PASS"),  # t4 = grace 판정
        ]
        h = FakeHeimdall(self.root, seq, cls=self._cls())
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertIn("턴 3/3", h.consumed[2].prompt)  # 80% 도달 자기규제 주입
        self.assertIn("범위를 좁히고", h.consumed[2].prompt)

    def test_budget_exhaustion_honest_report(self):
        seq = [
            worker({"w1.txt": "a\n"}, self.root),
            verifier("FAIL", sig="s1"),
            worker({"w1.txt": "b\n"}, self.root),
            verifier("FAIL", sig="s2"),  # grace 판정도 FAIL → 다음 작업 턴은 예산 밖
        ]
        h = FakeHeimdall(self.root, seq, cls=self._cls())
        out = h.handle("w1.txt 만들어")
        self.assertIn("예산", out)
        self.assertNotIn("과업 완수", out)


PLAN_WITH_UNITS = """계획: 두 파일을 만들고 요약을 붙인다.

```json
{"units": [
  {"id": 1, "subtask": "u1.txt 생성", "files": ["u1.txt"], "criteria": ["u1.txt 존재"], "access": []},
  {"id": 2, "subtask": "u2.txt 생성", "files": ["u2.txt"], "criteria": ["u2.txt 존재"], "access": []},
  {"id": 3, "subtask": "요약 파일 생성", "files": ["sum.txt"], "criteria": ["sum.txt 존재"], "access": [1]}
]}
```"""


class TestWaveParallel(Base):
    """Worker wave 병렬 + access list 격리 (CUS-176, Fugu Conductor analog)."""

    def test_parse_units_valid_and_fallbacks(self):
        from asgard.agent.heimdall import _parse_units

        units = _parse_units(PLAN_WITH_UNITS)
        self.assertEqual([u["id"] for u in units], [1, 2, 3])
        self.assertIsNone(_parse_units("계획만 있고 블록 없음"))
        self.assertIsNone(_parse_units('```json\n{"units": [{"id": 1, "subtask": "하나뿐"}]}\n```'))  # 단일 = 기존 경로
        self.assertIsNone(_parse_units("```json\n{깨진 json}\n```"))

    def test_plan_waves_topology_and_file_overlap(self):
        from asgard.agent.heimdall import _plan_waves

        units = [
            {"id": 1, "files": ["a.py"], "access": []},
            {"id": 2, "files": ["b.py"], "access": []},
            {"id": 3, "files": ["c.py"], "access": [1, 2]},
        ]
        waves = _plan_waves(units)
        self.assertEqual([[u["id"] for u in w] for w in waves], [[1, 2], [3]])
        overlap = [{"id": 1, "files": ["a.py"], "access": []}, {"id": 2, "files": ["a.py"], "access": []}]
        self.assertEqual([[u["id"] for u in w] for w in _plan_waves(overlap)], [[1], [2]])  # 겹침 직렬화

    def test_wave_execution_isolation_and_unit_events(self):
        cls = dict(CLS_WRITE, ambiguous=True)  # ambiguous write → THINKER 선행 (계획이 wave 의 입력)
        seq = [
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker"),
            worker({"u1.txt": "1\n"}, self.root, text="unit-result-A"),
            worker({"u2.txt": "2\n"}, self.root, text="unit-result-B"),
            worker({"sum.txt": "s\n"}, self.root, text="unit-result-C"),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)
        out = h.handle("u1, u2 만들고 요약")
        self.assertIn("과업 완수", out)
        workers = [s for s in h.consumed if s.label == "worker"]
        self.assertEqual(len(workers), 3)
        prompts = [w.prompt for w in workers]
        # 단위 1·2 (wave 1) — 격리: 선행 컨텍스트 없음, 서로의 결과 미노출
        wave1 = [p for p in prompts if "배정 단위 3" not in p]
        self.assertEqual(len(wave1), 2)
        for p in wave1:
            self.assertNotIn("선행 단위", p)
            self.assertNotIn("unit-result", p)
        # 단위 3 (wave 2) — access [1] 의 결과만 주입
        p3 = next(p for p in prompts if "배정 단위 3" in p)
        self.assertIn("[선행 단위 1 결과]", p3)
        self.assertNotIn("[선행 단위 2 결과]", p3)
        # work 이벤트 단위별 기록 (unit 필드)
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        units_logged = [e.get("unit") for e in events if e.get("event") == "work"]
        self.assertEqual(sorted(u for u in units_logged if u is not None), [1, 2, 3])

    def test_retry_after_wave_uses_single_path(self):
        cls = dict(CLS_WRITE, ambiguous=True)
        seq = [
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker"),
            worker({"u1.txt": "1\n"}, self.root),
            worker({"u2.txt": "2\n"}, self.root),
            worker({"sum.txt": "s\n"}, self.root),
            verifier("FAIL", sig="broken"),
            worker({"u1.txt": "fix\n"}, self.root),  # WORKER_RETRY — wave 아님, 실패 컨텍스트 집중
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)
        out = h.handle("u1, u2 만들고 요약")
        self.assertIn("과업 완수", out)
        retry = h.consumed[5]
        self.assertIn("FAILED: broken", retry.prompt)


class TestDirectGuard(Base):
    """DIRECT 가드 (CUS-178) — 오분류 write 소급 편입."""

    def _cls_read(self):
        return dict(CLS_WRITE, write_expected=False, criteria=[])

    def test_direct_write_enters_retro_verification(self):
        direct = worker({"sneaky.txt": "oops\n"}, self.root)  # DIRECT 세션이 파일을 씀
        seq = [direct, verifier("PASS")]
        h = FakeHeimdall(self.root, seq, cls=self._cls_read())
        out = h.handle("그냥 이거 처리해줘")
        self.assertIn("과업 완수", out)  # 소급 quest → Verifier → 게이트 → close
        self.assertIn("misroute", open(os.path.join(self.root, ".asgard", "classify.jsonl")).read())

    def test_direct_readonly_stays_taxless(self):
        direct = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("이 함수 뭐하는거야")
        self.assertEqual(len(h.consumed), 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))


class TestExplorationHint(Base):
    """탐색 캐시 최소판 (CUS-182) — Thinker 관찰 명령을 Worker 에 힌트로 전달 (게이트 증거 아님)."""

    def test_worker_gets_thinker_observations(self):
        cls = dict(CLS_WRITE, ambiguous=True)  # THINKER 선행 경로
        seq = [
            thinker("계획: w1 을 만든다", commands=[{"cmd": "grep -rn foo src/", "exit_code": 0}]),
            worker({"w1.txt": "x\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        w = next(s for s in h.consumed if s.label == "worker")
        self.assertIn("grep -rn foo src/", w.prompt)
        self.assertIn("재탐색 불필요", w.prompt)


class TestHookParity(Base):
    """quest_log ↔ verifier_gate 복제 코드 동등성 (CUS-184) — 어긋나면 게이트↔전이 판정 분열."""

    def test_sensitive_path_segment_matching(self):
        from asgard.hooks.quest_log import sensitive_path as q
        from asgard.hooks.verifier_gate import sensitive_path as g

        needles = ["hooks", "ci", ".github", "auth", "migration", "db"]
        cases = {
            "circle.py": False,  # 'ci' substring 오탐 회귀 (CUS-184)
            "ci/config.yml": True,
            ".github/workflows/x.yml": True,
            "hooks/deploy.py": True,
            "src/authentication.py": True,  # 4자+ needle 은 세그먼트 내 부분 일치
            "src/circuit.py": False,
            "db/migrations/0001.py": True,
            "readme.md": False,
        }
        for path, want in cases.items():
            self.assertEqual(q(path, needles), want, f"quest_log: {path}")
            self.assertEqual(g(path, needles), want, f"verifier_gate: {path}")

    def test_evidenceless_pass_cannot_close_or_transition_done(self):
        # CUS-170 깊이 테스트 발견 구멍: 무증거 PASS → close → LAST 면제로 게이트 우회
        import subprocess
        import sys as _sys

        def ql(*args, stdin=""):
            return subprocess.run(
                [_sys.executable, "-m", "asgard.hooks.quest_log", *args, "--session", "ev"],
                input=stdin, capture_output=True, text=True, cwd=self.root, timeout=30,
            )  # fmt: skip

        ql("open", "q-ev", "--criteria", "c")
        open(os.path.join(self.root, "f.txt"), "a").write("x\n")
        ql("append", stdin=json.dumps({"role": "worker", "event": "work"}))
        ql("append", "--verdict", "PASS", "--level", "full",
           stdin=json.dumps({"role": "verifier", "event": "verify", "commands": []}))  # fmt: skip
        nxt = json.loads(ql("next", "--write-expected").stdout)
        self.assertEqual(nxt["next_role"], "VERIFIER")  # DONE 금지 — 재검증 지시
        self.assertIn("증거", nxt["why"])
        self.assertEqual(ql("close").returncode, 1)  # close 거부
        # 증거 추가 후엔 통과
        ql("append", "--verdict", "PASS", "--level", "full",
           stdin=json.dumps({"role": "verifier", "event": "verify",
                             "commands": [{"cmd": "python3 -c 1", "exit_code": 0}]}))  # fmt: skip
        self.assertEqual(json.loads(ql("next", "--write-expected").stdout)["next_role"], "DONE")
        self.assertEqual(ql("close").returncode, 0)

    def test_gate_orphan_last_exemption_requires_evidence(self):
        # 강제 close(LAST 생성) 후에도 무증거 PASS 면 게이트가 orphan write 를 차단해야 한다
        import subprocess
        import sys as _sys

        def ql(*args, stdin=""):
            return subprocess.run(
                [_sys.executable, "-m", "asgard.hooks.quest_log", *args, "--session", "ev2"],
                input=stdin, capture_output=True, text=True, cwd=self.root, timeout=30,
            )  # fmt: skip

        ql("open", "q-ev2", "--criteria", "c")
        open(os.path.join(self.root, "f.txt"), "a").write("y\n")
        ql("append", stdin=json.dumps({"role": "worker", "event": "work"}))
        ql("append", "--verdict", "PASS", "--level", "full",
           stdin=json.dumps({"role": "verifier", "event": "verify", "commands": []}))  # fmt: skip
        self.assertEqual(ql("close", "--force").returncode, 0)  # 우회 시나리오 재현 (LAST 생성)
        json.dump(["f.txt"], open(os.path.join(self.root, ".asgard", "writes-ev2.json"), "w"))
        p = subprocess.run(
            [_sys.executable, "-m", "asgard.hooks.verifier_gate"],
            input=json.dumps({"session_id": "ev2", "cwd": self.root}),
            capture_output=True, text=True, cwd=self.root, timeout=60,
        )  # fmt: skip
        self.assertIn('"block"', p.stdout)  # 무증거 LAST 는 면제 불가

    def test_diff_state_parity(self):
        import subprocess

        from asgard.hooks.quest_log import diff_state as q
        from asgard.hooks.verifier_gate import diff_state as g

        head = subprocess.run(
            ["git", "-C", self.root, "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        open(os.path.join(self.root, "f.txt"), "a").write("delta\n")
        open(os.path.join(self.root, "new.txt"), "w").write("n\n")
        os.makedirs(os.path.join(self.root, "__pycache__"), exist_ok=True)
        open(os.path.join(self.root, "__pycache__", "x.pyc"), "w").write("junk")
        self.assertEqual(q(self.root, head), g(self.root, head))
        self.assertIn("new.txt", q(self.root, head)[1])
        self.assertNotIn("__pycache__/x.pyc", q(self.root, head)[1])  # junk 제외 유지


class TestStandardRoute(Base):
    """게이트-우선 (CUS-188) — ordinary write 는 Worker 직행 + 하네스 베이스라인 판정, LLM Verifier 0."""

    def policy(self, **kw):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w") as f:
            json.dump(kw, f)

    def test_standard_closes_without_llm_verifier(self):
        self.policy(baseline_checks=["true"])
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root)], cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker"])  # verifier LLM 미소비
        self.assertIn('"harness"', self.quest_log_text())  # 판정 주체 = 하네스
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_standard_red_gives_worker_retry_with_failing_check(self):
        self.policy(baseline_checks=["test -f fixed.txt"])
        seq = [worker({"w1.txt": "x\n"}, self.root), worker({"fixed.txt": "y\n"}, self.root)]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("고쳐줘")
        self.assertIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "worker"])
        self.assertIn("baseline-red", seq[1].prompt or "")  # 실패 체크가 재시도 컨텍스트로 전달

    def test_missing_task_class_stays_trinity(self):
        # task_class 미상(None) = 안전 기본값 — 기존 LLM Verifier 경로 유지
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
