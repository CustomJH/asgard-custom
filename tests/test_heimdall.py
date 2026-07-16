#!/usr/bin/env python3
"""Heimdall _trinity/_classify 오케스트레이션 하네스 — mocked AgentSession, API 호출 0.

FakeSession 이 스크립트된 응답·verdict 툴콜·관측 커맨드를 돌려주고, effect 로 워킹트리를 실제로
바꾼다 (diff-hash 물리 검증은 진짜 quest-log/gate subprocess 가 수행 — 배포 형태 그대로).

커버 경로: 해피패스 / verifier ESCALATE 전이 / structural FAIL→재계획 /
재시도 실패 컨텍스트 / no-verdict·무증거 PASS 합성 FAIL /
게이트 차단 수리→동일 사유 ESCALATE / classify 기본값·destructive 거부.

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

CLS_DIRECT = {
    "write_expected": False,
    "ambiguous": False,
    "destructive": False,
    "external_research": False,
    "shared": False,
    "criteria": [],
}


class FakeSession:
    """AgentSession 대역 — run() 이 스크립트 결과 반환 + effect 로 워킹트리 변경."""

    def __init__(self, result: SessionResult, effect=None, label=""):
        self.result, self.effect, self.label = result, effect, label
        self.prompt: str = ""  # 마지막 run() 프롬프트 — assertIn 검증 표면 (미실행 = "")
        self.system: str = ""  # 이 역할 세션의 system 프롬프트 — charter/lagom 주입 검증 표면
        self.role: str | None = None
        self.model: str | None = None
        self.readonly: bool = False
        self.rp_override: ResolvedProvider | None = None

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

    def _session(
        self,
        system,
        extra_tools=None,
        handlers=None,
        quiet=False,
        role=None,
        model=None,
        readonly=False,
        rp_override=None,
    ):
        with self._lock:  # wave 병렬 스레드가 동시에 pop — 순서 보호
            if not self._script:
                raise AssertionError("스크립트된 세션 소진 — 예상보다 많은 역할 턴")
            s = self._script.pop(0)
            s.role = role
            s.model = model
            s.readonly = readonly
            s.rp_override = rp_override
            s.system = system or ""
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
        self.assertIn("증거", out)  # 구조화 보고
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier"])

    def test_prose_artifact_style_failure_forces_worker_retry_before_close(self):
        seq = [
            worker({"guide.md": "혁신적 RAGX는 신뢰성을 보장한다.\n"}, self.root),
            verifier("PASS"),
            worker({"guide.md": "RAGX는 JSON 키를 정렬하는 13줄짜리 Python 도구다.\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "criteria": ["guide.md 작성"]})
        out = h.handle("RAGX 소개를 guide.md에 작성해. 사실: Python 13줄, JSON 키 정렬")
        self.assertIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier", "worker", "verifier"])
        self.assertIn("Lagom 문체 불변식", h.consumed[1].system)
        self.assertNotIn("효율 사다리", h.consumed[1].system)  # 전체 Lagom 주입으로 판정 기준을 흔들지 않는다
        self.assertIn("lagom-style", h.consumed[2].prompt)
        self.assertNotIn("혁신적", open(os.path.join(self.root, "guide.md"), encoding="utf-8").read())

    def test_completed_native_turn_is_retained_and_surfaces_approval_proposal(self):
        from asgard.project_memory import CompletionProposalResult, TurnRetentionResult

        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        with (
            mock.patch(
                "asgard.memory_bridge.find_config",
                return_value=(
                    self.root,
                    {"server": "http://memory", "bank": "demo", "auto_retain_turns": True},
                ),
            ),
            mock.patch(
                "asgard.project_memory.retain_turn", return_value=TurnRetentionResult("retained", "asgard:turn:1")
            ) as retain,
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch(
                "asgard.project_memory.propose_completion",
                return_value=CompletionProposalResult("proposed", "approval-1", "completion.1", "사용자 승인 제안"),
            ) as propose,
        ):
            out = h.handle("w1.txt 만들어")
        self.assertIn("사용자 승인 제안", out)
        self.assertEqual(retain.call_args.kwargs["user_text"], "w1.txt 만들어")
        self.assertIn("과업 완수", retain.call_args.kwargs["assistant_text"])
        self.assertTrue(propose.call_args.kwargs["verified"])
        self.assertIn("w1.txt", propose.call_args.kwargs["changed_files"])

    def test_exploring_direct_turn_appends_distill_nudge(self):
        """탐색(커맨드 ≥3)이 있었던 DIRECT 턴 — 실존 경로 인용 시 ingest 승인 넛지가 붙는다."""
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        open(os.path.join(self.root, "src", "app.py"), "w").write("X = 1\n")
        direct = FakeSession(
            SessionResult(
                text="답은 src/app.py 의 X 상수에 있다",
                stop_reason="end_turn",
                commands=[{"cmd": f"grep {i}", "exit_code": 0} for i in range(3)],
            ),
            label="direct",
        )
        h = FakeHeimdall(self.root, [direct], cls=CLS_DIRECT)
        out = h.handle("X 값이 어디 있는지 확인해줘")
        self.assertIn("🧠 탐색 발견 저장 후보", out)
        self.assertIn('asgard memory ingest "', out)
        self.assertIn("src/app.py", out)
        self.assertIn("--kind reference", out)

    def test_shallow_direct_turn_stays_silent(self):
        """탐색이 없던 DIRECT 턴(커맨드 < 문턱) — 넛지 소음 없음."""
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        open(os.path.join(self.root, "src", "app.py"), "w").write("X = 1\n")
        direct = FakeSession(
            SessionResult(text="답은 src/app.py 에 있다", stop_reason="end_turn", commands=[]),
            label="direct",
        )
        h = FakeHeimdall(self.root, [direct], cls=CLS_DIRECT)
        out = h.handle("X 값이 어디 있는지 확인해줘")
        self.assertNotIn("탐색 발견 저장 후보", out)

    def test_memory_kill_switch_suppresses_distill_nudge(self):
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        open(os.path.join(self.root, "src", "app.py"), "w").write("X = 1\n")
        direct = FakeSession(
            SessionResult(
                text="답은 src/app.py 에 있다",
                stop_reason="end_turn",
                commands=[{"cmd": "grep", "exit_code": 0}] * 3,
            ),
            label="direct",
        )
        h = FakeHeimdall(self.root, [direct], cls=CLS_DIRECT)
        with mock.patch.dict(os.environ, {"ASGARD_MEMORY_INJECT": "off"}):
            out = h.handle("X 값이 어디 있는지 확인해줘")
        self.assertNotIn("탐색 발견 저장 후보", out)

    def test_verifier_escalate_reaches_odin_without_worker_spin(self):
        # ESCALATE 데드스테이트 회귀 방지 — 이전엔 WORKER 폴스루로 12턴 공회전
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("ESCALATE")], cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn("Odin 결정 필요", out)
        self.assertEqual(len(h.consumed), 2)  # ESCALATE 후 추가 역할 턴 없음

    def test_structural_fail_goes_straight_to_replan(self):
        # structural FAIL → 3-strike 없이 THINKER_REPLAN
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
        # FAILED/Diagnosis 재디스패치 — 백지 재작업 금지
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
        # 관측 성공 명령 없는 PASS = 무효 — FAIL 합성 + 관측 커맨드만 기록
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
        # 무수리 fail-open 위장 제거 — 동일 사유 2회 차단 → 정직한 ESCALATE
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


class TestCharterInjection(Base):
    """Charter (프로젝트 북극성) — through-line/coherence 가 라이브 Trinity 순환에서 올바른
    역할 프롬프트에만 도달하고, evidence-first 게이트를 훼손하지 않음을 검증."""

    def _set_charter(self, charter):
        d = os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "asgard-setting-project.json"), "w", encoding="utf-8") as f:
            json.dump({"charter": charter}, f)

    def test_charter_reaches_thinker_and_verifier_not_worker(self):
        self._set_charter({"through_line": "TL관통원칙", "coherence": ["C1일관성"]})
        # structural replan 경로 = thinker 턴을 강제 (해피패스는 thinker 생략)
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="wrong-approach", why="접근 틀림"),
            thinker("재설계"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)  # 게이트 정상 통과 — charter 가 순환을 막지 않음
        by = {}
        for s in h.consumed:
            by.setdefault(s.label, s)
        # Thinker: 관통 원칙 + coherence 를 criteria 로 환원 지시 (설계①/협업②)
        self.assertIn("TL관통원칙", by["thinker"].system)
        self.assertIn("C1일관성", by["thinker"].system)
        # Verifier: 렌즈로 주입되되 criteria 대체 아님 명시 (판단③, evidence-first 보존)
        self.assertIn("TL관통원칙", by["verifier"].system)
        self.assertIn("criteria 를 대체하지 않", by["verifier"].system)
        # Worker: charter 전혀 무주입 — worker.md+lagom 만 (Fugu 격리, CC 훅과 패리티)
        self.assertNotIn("C1일관성", by["worker"].system)
        self.assertNotIn("프로젝트 북극성", by["worker"].system)

    def test_no_charter_no_injection(self):
        # 미설정이면 프롬프트 무변화 (토큰 회귀 없음)
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        for s in h.consumed:
            self.assertNotIn("프로젝트 북극성", s.system)


class TestRoutePriorsE2E(Base):
    """Bayesian-lite — 종결 outcome 기록 + prior 가 승격 문턱을 실제로 낮추는 e2e."""

    def read_priors(self):
        return json.load(open(os.path.join(self.root, ".asgard", "state", "route-priors.json")))

    def outcomes(self):
        path = os.path.join(self.root, ".asgard", "state", "classify.jsonl")
        events = [json.loads(ln) for ln in open(path) if ln.strip()]
        return [e for e in events if e.get("event") == "outcome"]

    def test_happy_path_records_pass_outcome_and_prior(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertEqual(self.read_priors()["classes"]["deep"], {"n": 1, "red": 0})  # task_class 미상 = deep
        (out,) = self.outcomes()
        self.assertEqual((out["task_class"], out["result"], out["baseline_red"]), ("deep", "pass", False))
        first = json.loads(self.quest_log_text().splitlines()[0])
        self.assertEqual(first["risk"].get("task_class"), "deep")  # open 이 클래스를 기록

    def test_escalate_records_outcome(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("ESCALATE")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        (out,) = self.outcomes()
        self.assertEqual(out["result"], "escalate")
        self.assertEqual(self.read_priors()["classes"]["deep"]["n"], 1)

    def test_red_majority_prior_promotes_on_first_red(self):
        # baseline red 상시(false 체크) + standard 클래스 과반-red 이력 → 첫 red 에 THINKER_REPLAN
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w") as f:
            json.dump({"baseline_checks": ["false"]}, f)
        with open(os.path.join(self.root, ".asgard", "state", "route-priors.json"), "w") as f:
            json.dump({"schema": 1, "classes": {"standard": {"n": 3, "red": 2}}}, f)
        seq = [
            worker({"w1.txt": "a\n"}, self.root),
            thinker("재설계 1"),
            worker({"w1.txt": "b\n"}, self.root),
            thinker("재설계 2"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("w1.txt 만들어")
        self.assertIn("턴 예산", out)  # 체크가 영원히 red — 예산 소진으로 정직 종료
        labels = [s.label for s in h.consumed]
        self.assertEqual(labels[:2], ["worker", "thinker"])  # red 1회 만에 재계획 (기본 문턱 2 아님)
        self.assertIn("prior", "".join(h.texts))  # 전이 사유에 prior 하향 표기
        self.assertEqual(self.read_priors()["classes"]["standard"], {"n": 4, "red": 3})
        (out_ev,) = self.outcomes()
        self.assertEqual((out_ev["result"], out_ev["baseline_red"]), ("budget-exhausted", True))


OPUS_DEFAULT = PROVIDERS["anthropic"].default_model  # 티어 매핑은 기본 모델일 때만 적용


class TestModelTiers(Base):
    """상황별 모델 티어 — opus/fable/sonnet/haiku 를 역할·상황이 결정."""

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

    def test_fallback_override_uses_default_provider_but_keeps_capability_role(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )
        h = self._h()

        session = Heimdall._session(h, "sys", role="thinker", rp_override=h.rp)

        self.assertEqual(session.rp.profile.name, h.rp.profile.name)
        self.assertEqual(session.role, "thinker")

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
        # 모델 티어 → route-priors 데이터 축: 실사용 provider:model 이 로그에 남는다
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

    def test_placed_verifier_fallback_keeps_verifier_capability_role(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.verifier]\nprovider = "ollama"\nmodel = "placed-v"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="verifier")
        h = self._h([worker({"w1.txt": "x\n"}, self.root), failed, verifier("PASS")])
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        verifier_sessions = [s for s in h.consumed if s.label == "verifier"]
        self.assertEqual([s.role for s in verifier_sessions], ["verifier", "verifier"])
        self.assertTrue(all(s.readonly for s in verifier_sessions))

    def test_placed_thinker_fallback_keeps_thinker_capability_role(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="bad-plan"),
            failed,
            thinker("fallback plan"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = self._h(seq)
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        thinker_sessions = [s for s in h.consumed if s.label == "thinker"]
        self.assertEqual([s.role for s in thinker_sessions], ["thinker", "thinker"])
        self.assertTrue(all(s.readonly for s in thinker_sessions))


class TestClassify(Base):
    def test_parse_failure_defaults_to_gated_write(self):
        h = FakeHeimdall(self.root, [], cls=None)
        mock.patch.object(h, "_complete_text", lambda *a, **k: "이건 JSON 이 아님").start()
        self.addCleanup(mock.patch.stopall)
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
    """결정론 pre-LLM 분류 — 명백 케이스 LLM 호출 0."""

    def test_obvious_cases_no_llm(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        read_only = [
            "이 함수 설명해줘",
            "왜 여기서 에러가 나지?",
            "what does this function do",
            "README 요약해줘",
            "파일이 몇 개 있어?",
            "README.md 첫 제목만 읽고 답해. 파일은 수정하지 마.",
            "pwd와 README 첫 줄을 보여줘. 파일 수정 금지.",
            "describe config.py without changing any files",
        ]
        writes = [
            "app.py 만들어줘",
            "버그 고쳐",
            "테스트 추가해줘",
            "implement the parser in parser.py",
            "이 모듈 리팩터해줘",
            # 벤치 실측 — "완성해줘" 가 동사 리스트 밖이라 LLM 폴백으로 새던 케이스
            "우리 API 서비스에 요청 rate limit 기능을 완성해줘. limiter.py에 골격만 있고 아직 동작하지 않아.",
        ]
        destructive = ["rm -rf ./build 실행해", "git push --force 해", "임시 파일 다 지워"]
        for q in read_only:
            d = ch(q)
            assert d is not None, q  # ty 내로잉 — assertIsNotNone 은 타입을 못 좁힌다
            self.assertFalse(d["write_expected"], q)
        for q in writes:
            d = ch(q)
            assert d is not None, q
            self.assertTrue(d["write_expected"], q)
            self.assertFalse(d["destructive"], q)
        for q in destructive:
            d = ch(q)
            assert d is not None, q
            self.assertTrue(d["destructive"], q)

    def test_ambiguous_falls_back_to_llm(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        self.assertIsNone(ch("로그인 화면이 이상함"))  # 동사 신호 없음
        self.assertIsNone(ch("버그 설명해주고 고쳐줘"))  # read+write 혼재

    def test_classify_uses_heuristic_without_client_call(self):
        h = FakeHeimdall(self.root, [], cls=None)

        def boom(*a, **k):
            raise AssertionError("LLM 호출 금지 — 휴리스틱이 처리해야 함")

        mock.patch.object(h, "_complete_text", boom).start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "이 함수 설명해줘")
        self.assertFalse(d["write_expected"])

    def test_telemetry_logged(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        log = open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read()
        self.assertIn('"route": "trinity"', log.replace('":"', '": "'))


class TestErrorRecovery(Base):
    """API 오류 회복 — recovery-hint 분류 + 백오프 + 폴백."""

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
            def run(_, user_content):
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
            def run(_, user_content):
                attempts.append(1)
                raise self._Boom(401)

        with self.assertRaises(self._Boom):
            h._run_turn(lambda: S(), "p")
        self.assertEqual(len(attempts), 1)  # 재시도 0

    def test_fatal_uses_fallback_once(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        ok = SessionResult(text="fb", stop_reason="end_turn")

        class Bad:
            def run(_, user_content):
                raise self._Boom(401)

        class Good:
            def run(_, user_content):
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
    """budget priors 배선 — task-class 턴 예산 + 80% 자기규제 + grace 판정."""

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
    """Worker wave 병렬 + access list 격리 (Fugu Conductor analog)."""

    def test_parse_units_valid_and_fallbacks(self):
        from asgard.agent.heimdall import _parse_units

        units = _parse_units(PLAN_WITH_UNITS) or []
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

    def test_wave_worker_supplies_default_provider_fallback(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.worker]\nprovider = "ollama"\nmodel = "placed-w"\n'
        )
        fallback_session = worker(text="fallback")
        h = FakeHeimdall(self.root, [fallback_session])
        captured = {}

        def capture(_make, _prompt, fallback=None, fallback_prompt=None):
            captured["fallback"] = fallback
            return SessionResult(text="primary", stop_reason="end_turn")

        unit = {"id": 1, "subtask": "u1", "files": [], "criteria": [], "access": []}
        with mock.patch.object(h, "_run_turn", side_effect=capture):
            h._run_worker_waves("wave-fallback", "task", [unit], "")

        self.assertTrue(callable(captured["fallback"]))
        session = captured["fallback"]()
        self.assertIs(session.rp_override, h.rp)
        self.assertEqual(session.role, "worker")

    def test_wave_partial_failure_records_success_units_before_raise(self):
        """CUS-247 — 한 단위 fatal 이어도 성공 단위의 완료 처리·writes 기록을 확정한 뒤 전파.
        기존 ex.map 은 lazy 예외 재발생으로 성공 단위의 ql append·_record_writes 까지 끊었다."""
        units = [
            {"id": 1, "subtask": "a", "files": ["ok.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["bad.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])

        def turn(_make, prompt, fallback=None, fallback_prompt=None):
            if "배정 단위 2" in prompt:
                raise RuntimeError("fatal-unit-2")
            return SessionResult(text="ok", stop_reason="end_turn", writes=["ok.txt"])

        with mock.patch.object(h, "_run_turn", side_effect=turn):
            with self.assertRaises(RuntimeError) as cm:
                h._run_worker_waves("wave-partial", "task", units, "")
        self.assertIn("fatal-unit-2", str(cm.exception))  # fatal = Trinity 중단 의미론 유지
        recorded = json.load(open(os.path.join(self.root, ".asgard", "state", "writes-wave-partial.json")))
        self.assertIn("ok.txt", recorded)  # 성공 단위 쓰기가 게이트 증거로 남는다
        joined = "".join(h.texts)
        self.assertIn("단위 1 완료", joined)
        self.assertIn("단위 2 실패", joined)

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
    """DIRECT 가드 — 오분류 write 소급 편입."""

    def _cls_read(self):
        return dict(CLS_WRITE, write_expected=False, criteria=[])

    def test_direct_write_enters_retro_verification(self):
        direct = worker({"sneaky.txt": "oops\n"}, self.root)  # DIRECT 세션이 파일을 씀
        seq = [direct, verifier("PASS")]
        h = FakeHeimdall(self.root, seq, cls=self._cls_read())
        out = h.handle("그냥 이거 처리해줘")
        self.assertIn("과업 완수", out)  # 소급 quest → Verifier → 게이트 → close
        self.assertIn("misroute", open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read())

    def test_direct_readonly_stays_taxless(self):
        direct = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("이 함수 뭐하는거야")
        self.assertEqual(len(h.consumed), 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_active_lagom_buffers_and_rewrites_direct_output_once(self):
        direct = FakeSession(
            SessionResult(text="혁신적 RAGX는 즉시 배포 가능하다.", stop_reason="end_turn"), label="direct"
        )
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(
            h, "_rewrite_lagom_text", return_value="RAGX는 JSON 키를 정렬하는 13줄짜리 도구다."
        ) as rewrite:
            h.handle("RAGX 소개를 답해. 사실: 13줄, JSON 키 정렬")
        rewrite.assert_called_once()
        self.assertEqual(h.last_response_text, "RAGX는 JSON 키를 정렬하는 13줄짜리 도구다.")
        self.assertNotIn("혁신적", "".join(h.texts))
        self.assertIn(h.last_response_text, "".join(h.texts))

    def test_active_lagom_fails_closed_when_rewrite_still_violates_style(self):
        direct = FakeSession(SessionResult(text="혁신적 결과다.", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(h, "_rewrite_lagom_text", return_value="강력한 결과다."):
            h.handle("결과를 설명해")
        self.assertIn("문체 검사를 통과하지 못", h.last_response_text)
        self.assertNotIn("혁신적", "".join(h.texts))
        self.assertNotIn("강력한", "".join(h.texts))

    def test_lagom_off_keeps_direct_streaming_without_rewrite(self):
        old = os.environ.get("LAGOM_MODE")
        os.environ["LAGOM_MODE"] = "off"
        try:
            direct = FakeSession(SessionResult(text="혁신적 결과다.", stop_reason="end_turn"), label="direct")
            h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
            with mock.patch.object(h, "_rewrite_lagom_text") as rewrite:
                h.handle("결과를 설명해")
            rewrite.assert_not_called()
            self.assertEqual(h.last_response_text, "혁신적 결과다.")
        finally:
            if old is None:
                os.environ.pop("LAGOM_MODE", None)
            else:
                os.environ["LAGOM_MODE"] = old


class TestExplorationHint(Base):
    """탐색 캐시 최소판 — Thinker 관찰 명령을 Worker 에 힌트로 전달 (게이트 증거 아님)."""

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
    """quest_log ↔ verifier_gate 복제 코드 동등성 — 어긋나면 게이트↔전이 판정 분열."""

    def test_sensitive_path_segment_matching(self):
        from asgard.hooks.quest_log import sensitive_path as q
        from asgard.hooks.verifier_gate import sensitive_path as g

        needles = ["hooks", "ci", ".github", "auth", "migration", "db"]
        cases = {
            "circle.py": False,  # 'ci' substring 오탐 회귀 방지
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
        # 깊이 테스트가 발견한 구멍: 무증거 PASS → close → LAST 면제로 게이트 우회
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
        # 강제 close 는 LAST 미기록 — 그리고 구버전 quest-log 가 남긴 LAST 라도
        # 무증거 PASS 면 게이트가 orphan write 를 차단해야 한다 (심층 방어)
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
        forced = ql("close", "--force")
        self.assertEqual(forced.returncode, 0)
        self.assertFalse(json.loads(forced.stdout).get("gate_exempt", True))
        last = os.path.join(self.root, ".asgard", "quest", "LAST")
        self.assertFalse(os.path.exists(last))  # forced close 는 게이트 면제(LAST)를 만들지 않는다
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)
        json.dump(["f.txt"], open(os.path.join(self.root, ".asgard", "state", "writes-ev2.json"), "w"))

        def gate():
            return subprocess.run(
                [_sys.executable, "-m", "asgard.hooks.verifier_gate"],
                input=json.dumps({"session_id": "ev2", "cwd": self.root}),
                capture_output=True, text=True, cwd=self.root, timeout=60,
            )  # fmt: skip

        self.assertIn('"block"', gate().stdout)  # LAST 없음 → orphan write 차단
        open(last, "w").write("q-ev2\n")  # 구버전 quest-log 가 남긴 LAST 시뮬레이션
        self.assertIn('"block"', gate().stdout)  # 무증거 LAST 는 면제 불가

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
    """게이트-우선 — ordinary write 는 Worker 직행 + 하네스 베이스라인 판정, LLM Verifier 0."""

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


class TestDirectHistory(Base):
    """REPL 턴 간 대화 맥락 — DIRECT 후속 질문이 직전 문답을 받는다 (Trinity 경로는 안 받음)."""

    def test_direct_followup_gets_history(self):
        cls_ro = {**CLS_WRITE, "write_expected": False, "criteria": []}
        s1 = FakeSession(SessionResult(text="답1", stop_reason="end_turn"), label="direct")
        s2 = FakeSession(SessionResult(text="답2", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [s1, s2], cls=cls_ro)
        h.handle("파이썬 버전 뭐야?")
        h.handle("그건 왜?")
        self.assertNotIn("이전 문답", s1.prompt)  # 첫 턴은 맥락 없음
        self.assertIn("이전 문답", s2.prompt)
        self.assertIn("파이썬 버전 뭐야?", s2.prompt)
        self.assertIn("답1", s2.prompt)


class TestDeliveryMemoryIsolation(Base):
    """개인 메모리 스냅샷은 코디네이터(DIRECT) 전용 (memory v3 P1 — heimdall 주석 계약).
    26-07-15 리뷰: identity 에 memory_note 가 합쳐지며 딜리버리 자식(freyja/thor/loki)까지
    누출 — 특히 loki 는 Verifier 반례 탐색자라 게이트 무결성 훼손."""

    def setUp(self):
        super().setUp()
        from asgard import memory

        os.environ[memory.MEMORY_ENV] = os.path.join(self.root, "mem")
        memory.add("게이트 불신 원칙", title="gate-rule", kind="insight")

    def tearDown(self):
        from asgard import memory

        os.environ.pop(memory.MEMORY_ENV, None)
        super().tearDown()

    def test_identity_split(self):
        h = FakeHeimdall(self.root, [])
        self.assertIn("<memory-context", h.identity)  # 코디네이터 표면엔 주입
        self.assertNotIn("<memory-context", h.delivery_identity)  # 딜리버리 표면은 무주입
        self.assertEqual(h.identity, h.delivery_identity + h.memory_note)

    def test_dispatch_child_system_is_memory_free(self):
        captured = {}

        class Capture(FakeHeimdall):
            def _session(
                self,
                system,
                extra_tools=None,
                handlers=None,
                quiet=False,
                role=None,
                model=None,
                readonly=False,
                rp_override=None,
            ):
                captured["system"] = system
                return super()._session(system, extra_tools, handlers, quiet, role, model, readonly)

        h = Capture(self.root, [worker(root=self.root)])
        h._dispatch_handler("s1", [])({"agent": "freyja", "task": "버튼 라벨 수정", "why": "w"})
        self.assertNotIn("<memory-context", captured["system"])
        self.assertIn("asgard-freyja", captured["system"])  # role 본문은 그대로


class TestMemoryRoleMatrix(Base):
    """감사 매트릭스: DIRECT·Thinker = 스냅샷+회수, standard Worker = 요청 관련 회수만,
    deep Worker/Verifier = 직접 무주입. provider allowlist가 모든 전송 표면을 게이트."""

    def setUp(self):
        super().setUp()
        from asgard import memory

        os.environ[memory.MEMORY_ENV] = os.path.join(self.root, "mem")
        memory.add("Odin 은 pytest -q 스타일 검증을 선호한다", title="pytest-pref", kind="user")
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write("\n/mem/\n")

    def tearDown(self):
        from asgard import memory

        os.environ.pop(memory.MEMORY_ENV, None)
        super().tearDown()

    def test_thinker_injected_worker_verifier_not(self):
        systems = []

        class Cap(FakeHeimdall):
            def _session(
                self,
                system,
                extra_tools=None,
                handlers=None,
                quiet=False,
                role=None,
                model=None,
                readonly=False,
                rp_override=None,
            ):
                systems.append(system)
                return super()._session(system, extra_tools, handlers, quiet, role, model, readonly)

        cls = {**CLS_WRITE, "task_class": "deep", "shared": True}  # shared → THINKER 선행
        h = Cap(self.root, [thinker(), worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=cls)
        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")
        self.assertEqual([s.label for s in h.consumed], ["thinker", "worker", "verifier"])
        self.assertIn("<memory-context", systems[0])  # Thinker 시스템 = 스냅샷
        self.assertIn("<memory-recall", h.consumed[0].prompt)  # Thinker 과업 = 회수 블록
        self.assertNotIn("<memory-context", systems[1])  # Worker 무주입
        self.assertNotIn("<memory-recall", h.consumed[1].prompt)
        self.assertNotIn("<memory-context", systems[2])  # Verifier 무주입 (게이트 무결성)
        self.assertNotIn("<memory-recall", h.consumed[2].prompt)

    def test_direct_prompt_gets_recall(self):
        cls = {**CLS_WRITE, "write_expected": False, "criteria": []}
        s = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [s], cls=cls)
        h.handle("pytest 검증 선호가 뭐였지?")
        self.assertIn("<memory-recall", s.prompt)
        self.assertIn("pytest-pref", s.prompt)

    def test_provider_allowlist_blocks_identity(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write('[memory]\nproviders = ["ollama"]\n')
        h = FakeHeimdall(self.root, [])  # 기본 provider = anthropic — allowlist 밖
        self.assertEqual(h.memory_note, "")
        self.assertNotIn("<memory-context", h.identity)
        self.assertTrue(h._memory_snap)  # 스냅샷 자체는 존재 — 게이트가 막았을 뿐

    def test_thinker_fallback_rebuilds_prompt_for_disallowed_provider(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[memory]\nproviders = ["ollama"]\n\n'
            '[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        fallback = thinker("fallback plan")
        cls = {**CLS_WRITE, "task_class": "deep", "shared": True}
        h = FakeHeimdall(
            self.root,
            [failed, fallback, worker({"w1.txt": "x\n"}, self.root), verifier("PASS")],
            cls=cls,
        )

        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")

        self.assertIn("<memory-recall", failed.prompt)
        self.assertNotIn("<memory-recall", fallback.prompt)
        self.assertNotIn("pytest-pref", fallback.prompt)

    def test_thinker_fallback_adds_recall_only_for_allowed_default_provider(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[memory]\nproviders = ["anthropic"]\n\n'
            '[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        fallback = thinker("fallback plan")
        cls = {**CLS_WRITE, "task_class": "deep", "shared": True}
        h = FakeHeimdall(
            self.root,
            [failed, fallback, worker({"w1.txt": "x\n"}, self.root), verifier("PASS")],
            cls=cls,
        )

        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")

        self.assertNotIn("<memory-recall", failed.prompt)
        self.assertIn("<memory-recall", fallback.prompt)
        self.assertIn("pytest-pref", fallback.prompt)

    def test_standard_worker_gets_bounded_task_relevant_recall(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w").write(
            json.dumps({"baseline_checks": ["true"]})
        )
        work = worker({"w1.txt": "x\n"}, self.root)
        h = FakeHeimdall(self.root, [work], cls={**CLS_WRITE, "task_class": "standard"})

        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")

        self.assertIn("<memory-recall", work.prompt)
        self.assertIn("pytest-pref", work.prompt)
        self.assertNotIn("<memory-context", work.system)


if __name__ == "__main__":
    unittest.main(verbosity=1)
