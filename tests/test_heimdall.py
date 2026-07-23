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
import threading
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
    """AgentSession 대역 — run() 결과·파일 effect·주입 도구 호출을 스크립트한다."""

    def __init__(self, result: SessionResult, effect=None, label="", tool_script=None):
        self.result, self.effect, self.label = result, effect, label
        self.prompt: str = ""  # 마지막 run() 프롬프트 — assertIn 검증 표면 (미실행 = "")
        self.system: str = ""  # 이 역할 세션의 system 프롬프트 — charter/lagom 주입 검증 표면
        self.role: str | None = None
        self.model: str | None = None
        self.readonly: bool = False
        self.quiet: bool = False
        self.rp_override: ResolvedProvider | None = None
        self.cwd: str = ""
        self.tool_script = list(tool_script or [])
        self.injected_handlers: dict = {}
        self.tool_results: list = []

    def run(self, user_content: str) -> SessionResult:
        self.prompt = user_content
        if self.effect:
            self.effect()
        for name, args in self.tool_script:
            if name not in self.injected_handlers:
                raise AssertionError(f"미배선 도구 호출: {name}")
            self.tool_results.append((name, self.injected_handlers[name](args)))
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
        self.policy.setdefault("ticket_runtime", {})["isolation"] = False

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
        cwd=None,
    ):
        with self._lock:  # wave 병렬 스레드가 동시에 pop — 순서 보호
            if not self._script:
                raise AssertionError("스크립트된 세션 소진 — 예상보다 많은 역할 턴")
            s = self._script.pop(0)
            s.role = role
            s.model = model
            s.readonly = readonly
            s.quiet = quiet
            s.rp_override = rp_override
            s.cwd = cwd or self.root
            s.system = system or ""
            s.injected_handlers = handlers or {}
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


def verifier(verdict="PASS", observed=True, structural=False, sig=None, why="", no_tool=False, commands=None):
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
    if commands is None:
        commands = [{"cmd": "pytest -q", "exit_code": 0}] if observed else []
    return FakeSession(
        SessionResult(
            text="verified",
            stop_reason="end_turn",
            commands=commands,
            tool_calls=tool_calls,
        ),
        label="verifier",
    )


def thinker(plan="계획: w1.txt 를 만든다", commands=None):
    return FakeSession(SessionResult(text=plan, stop_reason="end_turn", commands=commands or []), label="thinker")


def seed_learned_skill(root: str, name: str, *, triggers: str, agent: str) -> None:
    """승인 receipt 포함 learned 스킬 시드 — HOME 이 테스트 root 라 키도 격리 생성된다."""
    from asgard import skill_bank

    d = os.path.join(root, ".asgard", "skills", name)
    os.makedirs(d, exist_ok=True)
    text = f"---\nname: {name}\ndescription: d\ntriggers: {triggers}\nagent: {agent}\n---\n\n{name} 본문\n"
    open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8").write(text)
    receipt = skill_bank.approval_receipt(root, name, text, create_key=True)
    json.dump(receipt, open(os.path.join(d, skill_bank.APPROVAL_FILE), "w", encoding="utf-8"))


def seed_map_canary(root: str) -> None:
    from asgard.code_map import refresh_map

    refresh_map(root)
    path = os.path.join(root, ".asgard", "map", "navigation.md")
    open(path, "w", encoding="utf-8").write("# map: navigation\n\n- `f.txt` — MAP_CANARY navigation target\n")


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

    def test_noop_quest_observational_verifier_pass_closes(self):
        # 무변경 과업(오분류된 인사 등) — verifier 의 트리 관측(git status/diff)만으로 PASS 성립.
        # 종전엔 관측 명령이 전부 trivial 로 걸러져 PASS 가 영구 무효화되는 교착이었다 (26-07-21 실측).
        h = FakeHeimdall(
            self.root,
            [
                worker(None, self.root),  # 아무 것도 쓰지 않는 no-op work
                verifier("PASS", commands=[{"cmd": "git status --porcelain", "exit_code": 0}]),
            ],
            cls=CLS_WRITE,
        )
        out = h.handle("변경이 필요 없는 요청")
        self.assertIn("과업 완수", out)
        self.assertNotIn("PASS 무효화", "".join(h.texts))

    def test_pass_invalidation_is_visible_and_recoverable(self):
        # diff 가 있는 퀘스트의 관측-only PASS 는 여전히 무효 (Goodhart 유지) — 단 무효화 사실이
        # 화면에 표시된다 (사용자가 "PASS 직후 FAIL 재시도"라는 모순 화면을 보지 않게, 판정층 정직성)
        h = FakeHeimdall(
            self.root,
            [
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS", commands=[{"cmd": "git status --porcelain", "exit_code": 0}]),  # 무효화
                worker({"w1.txt": "x\n"}, self.root),  # WORKER_RETRY
                verifier("PASS"),  # 실증거(pytest) PASS
            ],
            cls=CLS_WRITE,
        )
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertIn("PASS 무효화", "".join(h.texts))

    def test_dual_mode_runs_two_readonly_thinkers_then_one_worker(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker_alt]\nprovider = "ollama"\nmodel = "alt-m"\n'
        )
        h = FakeHeimdall(
            self.root,
            [
                thinker("계획 A: 호출자를 먼저 찾는다"),
                thinker("계획 B: 회귀 테스트를 먼저 쓴다"),
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
            cls=CLS_WRITE,
        )
        h.dual_mode = True

        out = h.handle("w1.txt 만들어")

        self.assertIn("과업 완수", out)
        planners = h.consumed[:2]
        self.assertEqual({s.role for s in planners}, {"thinker", "thinker_alt"})
        self.assertTrue(all(s.readonly for s in planners))
        worker_session = h.consumed[2]
        self.assertEqual(worker_session.role, "worker")
        self.assertIn("계획 A", worker_session.prompt)
        self.assertIn("계획 B", worker_session.prompt)
        self.assertIn("하나의 최소 구현으로 합성", worker_session.prompt)

    def test_external_research_reenters_thinker_before_implementation(self):
        research = FakeSession(
            SessionResult(
                text="https://example.com/source — observed fact",
                stop_reason="end_turn",
                commands=[{"cmd": "web_fetch https://example.com/source", "exit_code": 0}],
            ),
            label="worker",
        )
        replanner = thinker("조사 결과에 맞춰 w1.txt를 만든다")
        implementation = worker({"w1.txt": "fact-backed\n"}, self.root)
        h = FakeHeimdall(
            self.root,
            [research, replanner, implementation, verifier("PASS")],
            cls={**CLS_WRITE, "external_research": True},
        )

        out = h.handle("외부 자료를 조사해 근거 기반 w1.txt를 만들어")

        self.assertIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "thinker", "worker", "verifier"])
        self.assertIn("[ASGARD_RESEARCH]", research.prompt)
        self.assertIn("scrapling-official", research.system)
        self.assertNotEqual(research.cwd, self.root)
        self.assertIn("https://example.com/source — observed fact", replanner.prompt)
        self.assertIn("미검증 데이터", replanner.prompt)

    def test_dual_mode_rejects_same_model_before_opening_quest(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        h.dual_mode = True

        out = h.handle("w1.txt 만들어")

        self.assertIn("서로 다른 Thinker 모델", out)
        self.assertEqual(h.consumed, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_close_rejection_cannot_be_reported_as_verified_completion(self):
        import subprocess

        from asgard.agent import heimdall

        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        real_ql = heimdall.ql

        def reject_close(root, *args, **kwargs):
            if args and args[0] == "close":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="stale close")
            return real_ql(root, *args, **kwargs)

        with mock.patch("asgard.agent.heimdall.trinity.ql", side_effect=reject_close):
            out = h.handle("w1.txt 만들어")

        self.assertIn("close 거부", out)
        self.assertNotIn("과업 완수", out)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))
        self.assertIsNone(h._last_completion)

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
        self.assertIn("⠶ 탐색 발견 저장 후보", out)
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

    def test_pass_with_unresolved_failed_verification_command_becomes_fail(self):
        incomplete = verifier("PASS")
        incomplete.result.commands = [
            {"cmd": "python -m pytest tests/test_w1.py -q", "exit_code": 1},
            {"cmd": "python -c \"open('w1.txt')\"", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "present\n"}, self.root),
            incomplete,
            worker({"missing.txt": "expected\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        self.assertIn("과업 완수", h.handle("w1.txt와 missing.txt 만들어"))
        self.assertIn("unresolved-verification-failure", self.quest_log_text())

    def test_grep_no_match_is_absence_evidence_not_unresolved_failure(self):
        # grep/rg 매치 0건(exit 1)은 '패턴 부재' 확인의 성공 — 미해소 실패로 세면 정당한 PASS 가
        # 뒤집혀 Worker 재시도+재검증 2턴이 공짜로 낭비된다 (26-07-23 감사).
        absence = verifier("PASS")
        absence.result.commands = [
            {"cmd": "grep -Fx forbidden w1.txt", "exit_code": 1},
            {"cmd": "rg legacy_symbol", "exit_code": 1},
            {"cmd": "git grep TODO -- w1.txt", "exit_code": 1},
            {"cmd": "grep -Fx present w1.txt", "exit_code": 0},
        ]
        h = FakeHeimdall(self.root, [worker({"w1.txt": "present\n"}, self.root), absence], cls=CLS_WRITE)
        self.assertIn("과업 완수", h.handle("w1.txt 만들어"))
        self.assertNotIn("unresolved-verification-failure", self.quest_log_text())

    def test_failed_verification_command_is_resolved_by_exact_successful_rerun(self):
        resolved = verifier("PASS")
        resolved.result.commands = [
            {"cmd": "pytest -q", "exit_code": 1},
            {"cmd": "pytest -q", "exit_code": 0},
        ]
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), resolved], cls=CLS_WRITE)
        self.assertIn("과업 완수", h.handle("w1.txt 만들어"))
        self.assertNotIn("unresolved-verification-failure", self.quest_log_text())

    def test_failed_runner_is_resolved_by_equivalent_runner_success(self):
        # 26-07-22 실측: 격리 클론에 .venv 가 없어 `uv run pytest` 환경 실패 → 같은 대상을
        # `python -m pytest` 로 통과시켰는데 신원 불일치로 PASS 무효화 → 헛 재시도 턴 전체 소모.
        resolved = verifier("PASS")
        resolved.result.commands = [
            {"cmd": "uv run pytest tests/test_memory.py -q", "exit_code": 1},
            {"cmd": "python -m pytest tests/test_memory.py -q", "exit_code": 0},
        ]
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), resolved], cls=CLS_WRITE)
        self.assertIn("과업 완수", h.handle("w1.txt 만들어"))
        self.assertNotIn("unresolved-verification-failure", self.quest_log_text())

    def test_failed_runner_with_different_target_stays_unresolved(self):
        different = verifier("PASS")
        different.result.commands = [
            {"cmd": "uv run pytest tests/test_a.py -q", "exit_code": 1},
            {"cmd": "python -m pytest tests/test_b.py -q", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            different,
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        self.assertIn("과업 완수", h.handle("w1.txt 만들어"))
        self.assertIn("unresolved-verification-failure", self.quest_log_text())

    def test_truncated_command_collision_does_not_resolve_failed_verification(self):
        collision = verifier("PASS")
        collision.result.commands = [
            {"cmd": "x" * 200, "command_hash": "failed-full-command", "exit_code": 1},
            {"cmd": "x" * 200, "command_hash": "different-success-command", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            collision,
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        self.assertIn("과업 완수", h.handle("w1.txt 만들어"))
        self.assertIn("unresolved-verification-failure", self.quest_log_text())

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
        with mock.patch("asgard.agent.heimdall.trinity.gate", return_value=(True, "stale PASS — 물리 대조 불일치")):
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
        with mock.patch("asgard.agent.heimdall.trinity.gate", side_effect=real_gate):
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


class TestDeliveryCanonInjection(Base):
    """딜리버리 정본 카탈로그 — 도메인 매칭 과업의 Thinker 프롬프트에만 정본 존재를 알린다.

    실증 근거(26-07-21 bilskirnir 4모드 실증): Thinker 가 저장소 문서 검색만으로 "정본 부재"를
    확정하고 응답 봉투를 발명해 verify 계약으로 고정 → thor 미디스패치·정책 우회 (2/2 재현)."""

    def _consumed_by_label(self, h):
        by = {}
        for s in h.consumed:
            by.setdefault(s.label, s)
        return by

    def test_matched_task_reaches_thinker_prompt_only(self):
        # structural replan 경로 = thinker 턴을 강제 (해피패스는 thinker 생략)
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="wrong-approach", why="접근 틀림"),
            thinker("재설계"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("신규 백엔드 API 설계 — 하우스 룰 준수로 w1.txt 만들어")
        self.assertIn("과업 완수", out)  # 주입이 순환을 막지 않음
        by = self._consumed_by_label(h)
        self.assertIn("딜리버리 정본 (계획 구속", by["thinker"].prompt)
        self.assertIn("asgard-thor-bilskirnir", by["thinker"].prompt)
        # Worker: 계획 구속 노트 대신 착수 힌트만 — 정본 소유 전문가 dispatch 지시 (관찰-정지 방어)
        self.assertNotIn("딜리버리 정본 (계획 구속", by["worker"].prompt)
        self.assertIn("딜리버리 정본 힌트", by["worker"].prompt)
        self.assertIn("dispatch", by["worker"].prompt)
        self.assertNotIn("딜리버리 정본", by["verifier"].prompt)

    def test_unmatched_task_no_injection(self):
        from asgard.agent.heimdall.roles import delivery_canon_note, worker_canon_hint

        self.assertEqual(delivery_canon_note(self.root, "readme 문서 오탈자 정리"), "")
        self.assertEqual(worker_canon_hint(self.root, "readme 문서 오탈자 정리"), "")


class TestBlockedEvidenceParity(Base):
    """가드 차단 호출은 실행된 적 없는 명령이다 — 미해소 실패로 PASS 를 강등시키지 않는다.

    실증 근거(26-07-21): claude_cli 트랜스포트에서 readonly 가드가 거부한 `git -C "$(pwd)" …` 가
    is_error→exit 1 로 증거에 승격, 동등 명령으로 이미 해소했어도 unresolved-verification-failure 로
    PASS 가 강등돼 턴 예산을 태웠다. 커널 경로(blocked 미기록)와 패리티."""

    def _verifier_with(self, commands):
        return FakeSession(
            SessionResult(
                text="verified",
                stop_reason="end_turn",
                commands=commands,
                tool_calls=[
                    {
                        "name": "verdict",
                        "input": {
                            "verdict": "PASS",
                            "criteria": CLS_WRITE["criteria"],
                            "commands": [{"cmd": "fake", "exit_code": 0}],
                        },
                    }
                ],
            ),
            label="verifier",
        )

    def test_blocked_failure_does_not_demote_pass(self):
        cmds = [
            {"cmd": "javac -version", "exit_code": 1, "blocked": True},
            {"cmd": "pytest -q", "exit_code": 0},
        ]
        seq = [worker({"w1.txt": "x\n"}, self.root), self._verifier_with(cmds)]
        out = FakeHeimdall(self.root, seq, cls=CLS_WRITE).handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)

    def test_executed_failure_still_demotes_pass(self):
        cmds = [
            {"cmd": "javac -version", "exit_code": 1},
            {"cmd": "pytest -q", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            self._verifier_with(cmds),
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        events = [json.loads(line) for line in self.quest_log_text().splitlines() if line.strip()]
        failures = [event for event in events if event.get("event") == "verify" and event.get("verdict") == "FAIL"]
        self.assertEqual(failures[0]["failure_sig"], "unresolved-verification-failure")


class TestRunnerIdentity(unittest.TestCase):
    """러너 래퍼 정규화 — 동등 러너 신원 일치, 다른 대상·파싱 불가는 그대로 (fail-safe)."""

    def setUp(self):
        from asgard.agent.heimdall.trinity import _runner_identity

        self.identity = _runner_identity

    def test_wrapper_variants_share_identity(self):
        for cmd in (
            "pytest tests -q",
            "uv run pytest tests -q",
            "uv run --no-cache pytest tests -q",
            "python -m pytest tests -q",
            "python3 -m pytest tests -q",
            ".venv/bin/pytest tests -q",
            "env UV_CACHE_DIR=.cache/uv uv run pytest tests -q",
        ):
            self.assertEqual(self.identity(cmd), "pytest tests -q", cmd)

    def test_python_dash_c_smoke_variants_share_identity(self):
        self.assertEqual(
            self.identity("uv run python -c 'import m; m.f()'"),
            self.identity("python3 -c 'import m; m.f()'"),
        )

    def test_distinct_targets_stay_distinct(self):
        self.assertNotEqual(self.identity("pytest tests/a.py -q"), self.identity("pytest tests/b.py -q"))

    def test_unparsable_command_falls_back_to_raw(self):
        self.assertEqual(self.identity('pytest "unclosed'), 'pytest "unclosed')


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
        # standard 클래스 과반-red 이력 → 첫 Verifier red 에 THINKER_REPLAN
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "state", "route-priors.json"), "w") as f:
            json.dump({"schema": 1, "classes": {"standard": {"n": 3, "red": 2}}}, f)
        seq = [
            worker({"w1.txt": "a\n"}, self.root),
            verifier("FAIL", sig="broken"),
            thinker("재설계 1"),
            worker({"w1.txt": "b\n"}, self.root),
            verifier("ESCALATE"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("w1.txt 만들어")
        self.assertIn("Odin", out)
        labels = [s.label for s in h.consumed]
        self.assertEqual(labels[:3], ["worker", "verifier", "thinker"])  # red 1회 만에 재계획
        self.assertIn("prior", "".join(h.texts))  # 전이 사유에 prior 하향 표기
        self.assertEqual(self.read_priors()["classes"]["standard"], {"n": 4, "red": 2})
        (out_ev,) = self.outcomes()
        self.assertEqual((out_ev["result"], out_ev["baseline_red"]), ("escalate", False))


OPUS_DEFAULT = PROVIDERS["anthropic"].default_model


class TestModelTiers(Base):
    """상황별 모델 티어 — opus/fable/sonnet/haiku 를 역할·상황이 결정."""

    def _h(self, sessions=None, model=OPUS_DEFAULT):
        return FakeHeimdall(self.root, sessions or [], cls=CLS_WRITE, model=model)

    def test_policy_tiers_map_roles_to_models(self):
        h = self._h()
        # worker 정책 티어는 standard 지만 코디네이터(opus=high)가 하한 — 위임 손은 세션 모델 아래로 안 내려간다
        self.assertEqual(h._model_for("worker"), "claude-opus-4-8")
        self.assertEqual(h._model_for("thinker"), "claude-opus-4-8")
        self.assertEqual(h._model_for("verifier"), "claude-opus-4-8")
        self.assertEqual(h._model_for("verifier", bump=True), "claude-fable-5")  # full-verify 승급

    def _set_coordinator(self, h, model):
        # role_rp 가 동일 rp 객체를 공유하므로 in-place 변이 (placement 오인 방지)
        h.rp.model = model

    def test_coordinator_tier_floor(self):
        # 프론티어 코디네이터(max) — 전 역할이 fable 로 승급, bump 는 이미 천장
        h = self._h()
        self._set_coordinator(h, "claude-fable-5")
        self.assertEqual(h._model_for("worker"), "claude-fable-5")
        self.assertEqual(h._model_for("verifier"), "claude-fable-5")
        self.assertEqual(h._model_for("worker", bump=True), "claude-fable-5")
        # 코디네이터가 역할 티어보다 낮으면(haiku=fast) 하한은 무효 — 정책 티어 유지
        h2 = self._h()
        self._set_coordinator(h2, "claude-haiku-4-5-20251001")
        self.assertEqual(h2._model_for("worker"), "claude-sonnet-5")
        self.assertEqual(h2._model_for("verifier"), "claude-opus-4-8")

    def test_delivery_tiers(self):
        h = self._h()
        self.assertEqual(h._delivery_model("freyja"), "claude-opus-4-8")
        self.assertEqual(h._delivery_model("thor"), "claude-opus-4-8")
        self.assertEqual(h._delivery_model("loki"), "claude-haiku-4-5-20251001")
        h.policy["delivery"]["thor"] = "custom"
        self.assertIsNone(h._delivery_model("thor"))

    def test_cli_aliases_keep_low_tier_role_floors(self):
        h = self._h(model="haiku")
        self.assertEqual(h._model_for("worker"), "claude-sonnet-5")
        self.assertEqual(h._model_for("verifier"), "claude-opus-4-8")
        self.assertEqual(h._delivery_model("thor"), "claude-sonnet-5")
        self.assertEqual(h._delivery_model("loki"), "claude-haiku-4-5-20251001")

    def test_explicit_delivery_placement_wins_over_floor(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thor]\nprovider = "ollama"\nmodel = "m1"\n'
        )
        h = self._h()
        self.assertIsNone(h._delivery_model("thor"))
        self.assertEqual(Heimdall._session(h, "sys", role="thor").rp.model, "m1")

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

    def test_worker_turn_floors_at_coordinator_tier(self):
        h = self._h([worker({"w1.txt": "x\n"}, self.root), verifier("PASS")])
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertEqual(h.consumed[0].model, "claude-opus-4-8")  # worker=standard 이나 코디네이터(high) 하한
        self.assertEqual(h.consumed[1].model, "claude-opus-4-8")  # verifier micro=high

    def test_quest_events_record_used_model(self):
        # 모델 티어 → route-priors 데이터 축: 실사용 provider:model 이 로그에 남는다
        h = self._h([worker({"w1.txt": "x\n"}, self.root), verifier("PASS")])
        h.handle("w1.txt 만들어")
        d = os.path.join(self.root, ".asgard", "quest")
        log = "\n".join(open(os.path.join(d, f)).read() for f in os.listdir(d) if f.endswith(".jsonl"))
        self.assertIn('"role":"worker","event":"work"', log)
        self.assertIn("anthropic:claude-opus-4-8", log)  # work·verify — 코디네이터 하한으로 동일 티어

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
    def test_parse_failure_with_write_verb_defaults_to_gated_write(self):
        h = FakeHeimdall(self.root, [], cls=None)
        mock.patch.object(h, "_complete_text", lambda *a, **k: "이건 JSON 이 아님").start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "버그 설명해주고 고쳐줘")  # read+write 혼재 → 휴리스틱 불확정 → 파싱 실패
        self.assertTrue(d["write_expected"])  # write 신호 존재 → 게이트 경로
        # 파싱 실패는 분류기 장애지 요청의 모호함이 아니다 — ambiguous 로 게이트-우선을 박탈하거나
        # deep(12턴)으로 최대 예산을 태우지 않는다 (26-07-23 감사). 물리 가드가 승격을 판정한다.
        self.assertFalse(d["ambiguous"])
        self.assertEqual(d["task_class"], "standard")

    def test_parse_failure_without_write_verb_fails_open_to_direct(self):
        # 분류기가 JSON 대신 대화체로 응답(인사 등) → 파싱 실패. write 동사가 없으면 DIRECT
        # fail-open — DIRECT 는 read-only + Canon 10 소급 검증이 실제 write 를 잡는다.
        # 구 기본값(무조건 write+deep)은 인사 하나가 deep 예산을 태우는 경로였다 (26-07-21 실측).
        h = FakeHeimdall(self.root, [], cls=None)
        mock.patch.object(h, "_complete_text", lambda *a, **k: "안녕하세요! 무엇을 도와드릴까요?").start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "뭔가 대충 처리해줘")  # write 동사 없음 + 휴리스틱 불확정
        self.assertFalse(d["write_expected"])
        self.assertEqual(d["task_class"], "standard")

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
            "로고 시스템을 실제 산출물로 제작해줘",
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

    def test_smalltalk_routes_direct_no_llm(self):
        # 인사·감사·수긍은 결정론으로 DIRECT — LLM 분류기가 인사에 인사로 답해(JSON 파싱 실패)
        # Trinity 를 태우던 경로 차단 (26-07-21 "안녕" 실측: deep 예산 소진)
        from asgard.agent.heimdall import classify_heuristic as ch

        smalltalk = [
            "안녕",
            "안녕하세요!",
            "hi",
            "hello~",
            "고마워",
            "감사합니다",
            "ㅋㅋㅋ",
            "넵",
            "수고하셨습니다",
            "thanks!",
            "잘가",
            "응 좋아",
        ]
        for q in smalltalk:
            d = ch(q)
            assert d is not None, q
            self.assertFalse(d["write_expected"], q)
        # 인사가 실제 과업에 섞이면 스몰톡이 아니다 — write 동사가 정상 우선
        mixed = ch("안녕, login.py 버그 고쳐줘")
        assert mixed is not None
        self.assertTrue(mixed["write_expected"])

    def test_memory_instruction_routes_direct_no_llm(self):
        # 기억 지시가 어느 동사 표에도 없어 LLM 폴백 trivial 로 흐르고, 모델이 저장 없이
        # "기억했다" 허위 확답하던 경로 (26-07-21 실측) — 결정론 DIRECT + memory_save 계약으로 봉인.
        from asgard.agent.heimdall import classify_heuristic as ch
        from asgard.agent.heimdall import memory_write_intent

        d = ch("내 이름은 썬더오브갓이야. 기억해줘.")
        assert d is not None
        self.assertFalse(d["write_expected"])
        for q in (
            "내 이름은 썬더오브갓이야. 기억해줘.",
            "이 규칙 잊지 마",
            "내 생일은 3월 3일이야. 기억해",
            "메모리에 저장해: 배포는 금요일 금지",
            "please remember my timezone is KST",
        ):
            self.assertTrue(memory_write_intent(q), q)
        # 회상 질문·과거형은 저장 지시가 아니다 — 오탐이면 폴백 ingest 가 잡담을 영구 저장한다
        for q in (
            "내 이름 기억해?",
            "우리 지난주에 뭐 했는지 기억하고 있어?",
            "do you remember my name?",
        ):
            self.assertFalse(memory_write_intent(q), q)
        # 혼합(기억 + repo write)은 여전히 write 분기 — Trinity 게이트 우선
        mixed = ch("이 규칙 기억해두고 config.py 수정해줘")
        assert mixed is not None
        self.assertTrue(mixed["write_expected"])

    def test_explicit_parallel_write_routes_through_deep_planning(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        requests = [
            "alpha.py와 beta.py를 독립 Worker 단위로 분해해 병렬 구현해줘",
            "implement the parser with parallel subagents and a TODO list",
        ]
        for request in requests:
            classified = ch(request)
            assert classified is not None
            self.assertTrue(classified["write_expected"])
            self.assertTrue(classified["parallel_requested"])
            self.assertEqual(classified["task_class"], "deep")

    def test_explicit_parallel_write_actually_runs_thinker_and_wave(self):
        h = FakeHeimdall(
            self.root,
            [
                thinker(PLAN_WITH_UNITS),
                worker({"u1.txt": "1\n"}, self.root),
                worker({"u2.txt": "2\n"}, self.root),
                worker({"sum.txt": "12\n"}, self.root),
                verifier("PASS"),
            ],
            cls=None,
        )

        out = h.handle("u1과 u2를 독립 Worker 단위로 분해해 병렬 구현해줘")

        self.assertIn("과업 완수", out)
        self.assertEqual(
            [session.label for session in h.consumed], ["thinker", "worker", "worker", "worker", "verifier"]
        )

    def test_explicit_parallel_write_replans_instead_of_collapsing_invalid_graph_to_one_worker(self):
        invalid = '```json\n{"units":[{"id":1,"subtask":"monolith","files":["u1.txt"],"access":[]}]}\n```'
        h = FakeHeimdall(
            self.root,
            [
                thinker(invalid),
                thinker(PLAN_WITH_UNITS),
                worker({"u1.txt": "1\n"}, self.root),
                worker({"u2.txt": "2\n"}, self.root),
                worker({"sum.txt": "12\n"}, self.root),
                verifier("PASS"),
            ],
            cls=None,
        )

        out = h.handle("u1과 u2를 독립 Worker 단위로 분해해 병렬 구현해줘")

        self.assertIn("과업 완수", out)
        self.assertEqual(
            [session.label for session in h.consumed],
            ["thinker", "thinker", "worker", "worker", "worker", "verifier"],
        )
        self.assertIn("invalid-parallel-plan", self.quest_log_text())

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
        # 침묵 break 금지 — 어떤 전이가 왜 못 뛰었는지 Odin 보고에 실린다 (26-07-22 실측:
        # grace PASS 후 베이스라인 red 수리 전이가 막혔는데 "판정 실패"로 오독되는 보고).
        # 전이명은 승격 규칙(동종 red 2회 → THINKER_REPLAN)에 따라 달라진다 — 형식만 봉인.
        self.assertIn("미실행 전이 ", out)


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

    @staticmethod
    def isolated_worker(rel: str, body: str):
        session = FakeSession(SessionResult(text="isolated", stop_reason="end_turn", writes=[]), label="worker")

        def effect():
            path = os.path.join(session.cwd, rel)
            os.makedirs(os.path.dirname(path) or session.cwd, exist_ok=True)
            open(path, "w").write(body)

        session.effect = effect
        return session

    def test_wave_isolation_merges_physical_deltas_not_self_reported_writes(self):
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt", "b.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["a.txt", "b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [self.isolated_worker("a.txt", "a"), self.isolated_worker("b.txt", "b")])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-isolated", session="wave-isolated")
        h._run_worker_waves("wave-isolated", "task", units, "")
        self.assertEqual(open(os.path.join(self.root, "a.txt")).read(), "a")
        self.assertEqual(open(os.path.join(self.root, "b.txt")).read(), "b")
        events = [json.loads(line) for line in self.quest_log_text().splitlines()]
        changed = {
            event["unit"]: event["changed_files"]
            for event in events
            if event.get("event") == "work" and event.get("unit") in (1, 2)
        }
        self.assertEqual(changed, {1: ["a.txt"], 2: ["b.txt"]})

    def test_isolated_unit_accepts_declared_root_dot_path(self):
        rel = ".github/workflows/ci.yml"
        unit = {"id": 1, "subtask": "workflow", "files": [rel], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [self.isolated_worker(rel, "name: ci\n")])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-dot-path", session="wave-dot-path")
        h._run_worker_waves("wave-dot-path", "task", [unit], "")
        self.assertEqual(open(os.path.join(self.root, rel)).read(), "name: ci\n")

    def test_disjoint_isolated_units_execute_in_parallel_then_merge(self):
        import threading

        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(
            self.root,
            [
                FakeSession(SessionResult(text="a", stop_reason="end_turn")),
                FakeSession(SessionResult(text="b", stop_reason="end_turn")),
            ],
        )
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        barrier = threading.Barrier(2)
        root_was_clean = []

        def turn(make, prompt, fallback=None, fallback_prompt=None):
            session = make()
            rel = "a.txt" if "배정 단위 1" in prompt else "b.txt"
            root_was_clean.append(not os.path.exists(os.path.join(self.root, rel)))
            barrier.wait(timeout=5)
            open(os.path.join(session.cwd, rel), "w").write(rel)
            return SessionResult(text=rel, stop_reason="end_turn", writes=[])

        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-real-parallel", session="wave-real-parallel")
        with mock.patch.object(h, "_run_turn", side_effect=turn):
            h._run_worker_waves("wave-real-parallel", "task", units, "")
        self.assertEqual(root_was_clean, [True, True])
        self.assertEqual(open(os.path.join(self.root, "a.txt")).read(), "a.txt")
        self.assertEqual(open(os.path.join(self.root, "b.txt")).read(), "b.txt")

    def test_wave_isolation_rejects_undeclared_actual_writes_without_touching_root(self):
        open(os.path.join(self.root, "shared.txt"), "w").write("user\n")
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(
            self.root,
            [self.isolated_worker("shared.txt", "one\n"), self.isolated_worker("shared.txt", "two\n")],
        )
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-overlap", session="wave-overlap")
        with self.assertRaisesRegex(RuntimeError, "scope violation"):
            h._run_worker_waves("wave-overlap", "task", units, "")
        self.assertEqual(open(os.path.join(self.root, "shared.txt")).read(), "user\n")

    def test_parse_units_valid_and_fallbacks(self):
        from asgard.agent.heimdall import _parse_units

        units = _parse_units(PLAN_WITH_UNITS) or []
        self.assertEqual([u["id"] for u in units], [1, 2, 3])
        self.assertIsNone(_parse_units('```json\n{"units":[{"id":1,"subtask":"a"},{"id":"1","subtask":"b"}]}\n```'))
        self.assertIsNone(_parse_units("계획만 있고 블록 없음"))
        self.assertIsNone(_parse_units('```json\n{"units": [{"id": 1, "subtask": "하나뿐"}]}\n```'))  # 단일 = 기존 경로
        self.assertIsNone(_parse_units("```json\n{깨진 json}\n```"))
        self.assertIsNone(
            _parse_units(
                '```json\n{"units":[{"id":1,"subtask":"a","access":[99]},{"id":2,"subtask":"b","access":[]}]}\n```'
            )
        )
        self.assertIsNone(
            _parse_units(
                '```json\n{"units":[{"id":1,"subtask":"a","access":[2]},{"id":2,"subtask":"b","access":[1]}]}\n```'
            )
        )

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
        aliases = [
            {"id": 1, "files": ["src"], "access": []},
            {"id": 2, "files": ["./src/A.py"], "access": []},
            {"id": 3, "files": ["src/a.py"], "access": []},
        ]
        self.assertEqual([[u["id"] for u in w] for w in _plan_waves(aliases, self.root)], [[1], [2], [3]])
        with self.assertRaisesRegex(ValueError, "dependency graph"):
            _plan_waves([{"id": 1, "files": [], "access": [2]}, {"id": 2, "files": [], "access": [1]}])

    def test_resume_snapshot_reuses_done_units_and_returns_only_retryable_work(self):
        from asgard.agent.heimdall import _resume_snapshot, ql

        ql(
            self.root,
            "open",
            "resume-q",
            "--criteria",
            "resume criteria",
            "--request",
            "original resumable task",
            session="resume-q",
        )
        units = [
            {"id": 1, "subtask": "done", "files": ["a.txt"], "criteria": ["a"], "access": []},
            {"id": 2, "subtask": "pending", "files": ["b.txt"], "criteria": ["b"], "access": [1]},
        ]
        for unit in units:
            ql(
                self.root,
                "append",
                session="resume-q",
                stdin=json.dumps(
                    {
                        "role": "thinker",
                        "event": "ticket",
                        "ticket_status": "todo",
                        "unit": unit["id"],
                        "subtask": unit["subtask"],
                        "changed_files": unit["files"],
                        "criteria": unit["criteria"],
                        "access": unit["access"],
                    }
                ),
            )
        claim = json.loads(ql(self.root, "ticket-claim", "--unit", "1", "--worker", "old", session="resume-q").stdout)
        ql(
            self.root,
            "ticket-finish",
            "--unit",
            "1",
            "--claim-token",
            claim["claim_token"],
            "--status",
            "done",
            session="resume-q",
        )
        snapshot = _resume_snapshot(self.root, "resume-q")
        self.assertEqual(snapshot["completed"], [1])
        self.assertEqual([unit["id"] for unit in snapshot["units"]], [2])
        self.assertEqual(snapshot["units"][0]["access"], [])
        self.assertEqual(snapshot["criteria"], ["resume criteria"])
        self.assertEqual(snapshot["request"], "original resumable task")
        h = FakeHeimdall(self.root, [])
        with mock.patch.object(h, "_trinity", return_value="resumed") as resumed:
            self.assertEqual(h.resume("resume-q"), "resumed")
        call = resumed.call_args
        self.assertEqual(call.args[0], "original resumable task")
        self.assertEqual([unit["id"] for unit in call.kwargs["resume_units"]], [2])
        self.assertEqual(call.kwargs["resume_qid"], "resume-q")
        resumed_cls = call.args[1]
        self.assertFalse(resumed_cls["ambiguous"])
        self.assertFalse(resumed_cls["external_research"])
        self.assertFalse(resumed_cls["shared"])

    def test_wave_execution_isolation_and_unit_events(self):
        seed_map_canary(self.root)
        cls = dict(CLS_WRITE, ambiguous=True, parallel_requested=True)
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
        thinker_session = next(session for session in h.consumed if session.label == "thinker")
        verifier_session = next(session for session in h.consumed if session.label == "verifier")
        self.assertIn("MAP_CANARY", thinker_session.system)
        self.assertNotIn("MAP_CANARY", verifier_session.system)
        workers = [s for s in h.consumed if s.label == "worker"]
        self.assertEqual(len(workers), 3)
        self.assertTrue(all("MAP_CANARY" in session.system for session in workers))
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
        ticket_statuses = {
            unit: [e.get("ticket_status") for e in events if e.get("event") == "ticket" and e.get("unit") == unit]
            for unit in (1, 2, 3)
        }
        self.assertEqual(ticket_statuses[1], ["todo", "in_progress", "done"])
        self.assertEqual(ticket_statuses[2], ["todo", "in_progress", "done"])
        self.assertEqual(ticket_statuses[3], ["todo", "in_progress", "done"])
        from asgard.hooks.quest_log import load_events, load_policy, summarize

        quest_file = next(
            name for name in os.listdir(os.path.join(self.root, ".asgard", "quest")) if name.endswith(".jsonl")
        )
        quest_id = quest_file.removesuffix(".jsonl")
        state = summarize(self.root, quest_id, load_events(self.root, quest_id), load_policy(self.root))
        self.assertEqual(state["ticket_counts"], {"done": 3})
        self.assertEqual([ticket["id"] for ticket in state["tickets"]], [1, 2, 3])
        self.assertTrue(all(ticket["attempt"] == 1 for ticket in state["tickets"]))
        self.assertTrue(all(ticket["claim_token_hash"] for ticket in state["tickets"]))

    def test_fast_sibling_keeps_lease_while_waiting_for_slow_fan_in(self):
        import time

        plan = (
            '```json\n{"units":['
            '{"id":1,"subtask":"fast","files":["u1.txt"],"criteria":["u1"],"access":[]},'
            '{"id":2,"subtask":"slow","files":["u2.txt"],"criteria":["u2"],"access":[]}'
            "]}\n```"
        )
        fast = worker({"u1.txt": "1\n"}, self.root)
        slow = worker({"u2.txt": "2\n"}, self.root)
        slow_effect = slow.effect
        assert slow_effect is not None

        def delayed():
            time.sleep(3.2)
            slow_effect()

        slow.effect = delayed
        h = FakeHeimdall(
            self.root,
            [thinker(plan), fast, slow, verifier("PASS")],
            cls=dict(CLS_WRITE, ambiguous=True, parallel_requested=True),
        )
        h.policy.setdefault("ticket_runtime", {})["lease_seconds"] = 2
        self.assertIn("과업 완수", h.handle("u1과 u2를 병렬 구현해줘"))

    def test_wave_worker_supplies_default_provider_fallback(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.worker]\nprovider = "ollama"\nmodel = "placed-w"\n'
        )
        fallback_session = worker(text="fallback")
        h = FakeHeimdall(self.root, [fallback_session])
        captured = {}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-fallback", session="wave-fallback")

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
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-partial", session="wave-partial")

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
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        statuses = {
            unit: [e.get("ticket_status") for e in events if e.get("event") == "ticket" and e.get("unit") == unit]
            for unit in (1, 2)
        }
        self.assertEqual(statuses[1], ["todo", "in_progress", "done"])
        self.assertEqual(
            statuses[2],
            ["todo", "in_progress", "failed", "in_progress", "failed", "in_progress", "blocked"],
        )

    def test_capture_failure_joins_all_wave_heartbeats(self):
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-capture-error", session="wave-capture-error")
        result = SessionResult(text="ok", stop_reason="end_turn")
        with (
            mock.patch.object(h, "_run_turn", return_value=result),
            mock.patch("asgard.agent.unit_workspace.UnitWorkspace.capture", side_effect=RuntimeError("capture failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                h._run_worker_waves("wave-capture-error", "task", units, "")
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
        from asgard.hooks.quest_log import fold_tickets, load_events

        tickets = fold_tickets(load_events(self.root, "wave-capture-error"))
        self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_completion_error_still_joins_failed_sibling_heartbeat(self):
        units = [
            {"id": 1, "subtask": "success", "files": [], "criteria": [], "access": []},
            {"id": 2, "subtask": "failure", "files": [], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql as real_ql

        real_ql(self.root, "open", "wave-completion-error", session="wave-completion-error")

        def turn(_make, prompt, fallback=None, fallback_prompt=None):
            if "배정 단위 2" in prompt:
                raise RuntimeError("worker failed")
            return SessionResult(text="ok", stop_reason="end_turn")

        def fail_work_append(root, *args, stdin="", session="native"):
            if args and args[0] == "append" and json.loads(stdin or "{}").get("event") == "work":
                return subprocess.CompletedProcess(args, 1, "", "forced work append failure")
            return real_ql(root, *args, stdin=stdin, session=session)

        with (
            mock.patch.object(h, "_run_turn", side_effect=turn),
            mock.patch("asgard.agent.heimdall.waves.ql", side_effect=fail_work_append),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced work append failure"):
                h._run_worker_waves("wave-completion-error", "task", units, "")
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
        from asgard.hooks.quest_log import fold_tickets, load_events

        tickets = fold_tickets(load_events(self.root, "wave-completion-error"))
        self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_raised_postprocess_errors_settle_every_claim(self):
        scenarios = ("record-writes", "work-append")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                qid = f"wave-raised-{scenario}"
                units = [{"id": 1, "subtask": "success", "files": [], "criteria": [], "access": []}]
                h = FakeHeimdall(self.root, [])
                from asgard.agent.heimdall import ql as real_ql
                from asgard.hooks.quest_log import fold_tickets, load_events

                real_ql(self.root, "open", qid, session=qid)

                def raised_ql(root, *args, stdin="", session="native"):
                    if (
                        scenario == "work-append"
                        and args
                        and args[0] == "append"
                        and json.loads(stdin or "{}").get("event") == "work"
                    ):
                        raise OSError("raised work append")
                    return real_ql(root, *args, stdin=stdin, session=session)

                patches = [
                    mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
                    mock.patch("asgard.agent.heimdall.waves.ql", side_effect=raised_ql),
                ]
                if scenario == "record-writes":
                    patches.append(
                        mock.patch("asgard.agent.heimdall.waves._record_writes", side_effect=OSError("writes failed"))
                    )
                with (
                    patches[0],
                    patches[1],
                    patches[2] if len(patches) == 3 else mock.patch.object(h, "history", h.history),
                ):
                    with self.assertRaises(OSError):
                        h._run_worker_waves(qid, "task", units, "")
                self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
                tickets = fold_tickets(load_events(self.root, qid))
                self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_workspace_close_error_settles_claims_and_joins_heartbeats(self):
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql
        from asgard.hooks.quest_log import fold_tickets, load_events

        ql(self.root, "open", "wave-close-error", session="wave-close-error")
        with (
            mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
            mock.patch("asgard.agent.heimdall.waves.ExitStack.close", side_effect=OSError("close failed")),
        ):
            with self.assertRaisesRegex(OSError, "close failed"):
                h._run_worker_waves("wave-close-error", "task", units, "")
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
        tickets = fold_tickets(load_events(self.root, "wave-close-error"))
        self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_finish_failure_shortens_unsettled_claim_lease(self):
        unit = {"id": 1, "subtask": "a", "files": [], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql as real_ql

        real_ql(self.root, "open", "wave-finish-error", session="wave-finish-error")
        shortened = []

        def fail_finish(root, *args, stdin="", session="native"):
            if args and args[0] == "ticket-finish":
                return subprocess.CompletedProcess(args, 1, "", "finish unavailable")
            if args and args[0] == "ticket-heartbeat" and args[args.index("--lease-seconds") + 1] == "1":
                shortened.append(args)
            return real_ql(root, *args, stdin=stdin, session=session)

        with (
            mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
            mock.patch("asgard.agent.heimdall.waves.ql", side_effect=fail_finish),
        ):
            with self.assertRaisesRegex(RuntimeError, "finish unavailable"):
                h._run_worker_waves("wave-finish-error", "task", [unit], "")
        self.assertTrue(shortened)
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))

    def test_finish_and_lease_shortening_failures_are_both_surfaced(self):
        unit = {"id": 1, "subtask": "a", "files": [], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql as real_ql

        real_ql(self.root, "open", "wave-control-error", session="wave-control-error")

        def fail_control(root, *args, stdin="", session="native"):
            if args and args[0] == "ticket-finish":
                return subprocess.CompletedProcess(args, 1, "", "finish unavailable")
            if args and args[0] == "ticket-heartbeat" and args[args.index("--lease-seconds") + 1] == "1":
                return subprocess.CompletedProcess(args, 1, "", "lease shortening rejected")
            return real_ql(root, *args, stdin=stdin, session=session)

        with (
            mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
            mock.patch("asgard.agent.heimdall.waves.ql", side_effect=fail_control),
        ):
            with self.assertRaises(RuntimeError) as raised:
                h._run_worker_waves("wave-control-error", "task", [unit], "")
        self.assertIn("finish unavailable", str(raised.exception))
        self.assertIn("lease shortening rejected", str(raised.exception))
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))

    def test_wave_retries_only_failed_ticket_with_new_claim(self):
        unit = {"id": 1, "subtask": "flaky", "files": ["flaky.txt"], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-retry", session="wave-retry")
        attempts = 0

        def turn(_make, _prompt, fallback=None, fallback_prompt=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient")
            return SessionResult(text="ok", stop_reason="end_turn", writes=["flaky.txt"])

        with mock.patch.object(h, "_run_turn", side_effect=turn):
            h._run_worker_waves("wave-retry", "task", [unit], "")
        self.assertEqual(attempts, 2)
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        statuses = [e.get("ticket_status") for e in events if e.get("event") == "ticket" and e.get("unit") == 1]
        self.assertEqual(statuses, ["todo", "in_progress", "failed", "in_progress", "done"])
        from asgard.hooks.quest_log import fold_tickets

        ticket = fold_tickets(events)["1"]
        self.assertEqual(ticket["attempt"], 2)
        self.assertEqual(ticket["status"], "done")

    def test_retry_after_wave_replans_and_preserves_unit_scope(self):
        cls = dict(CLS_WRITE, ambiguous=True, parallel_requested=True)
        seq = [
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker"),
            worker({"u1.txt": "1\n"}, self.root),
            worker({"u2.txt": "2\n"}, self.root),
            worker({"sum.txt": "s\n"}, self.root),
            verifier("FAIL", sig="broken"),
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker-replan"),
            worker({"u1.txt": "fix1\n"}, self.root),
            worker({"u2.txt": "fix2\n"}, self.root),
            worker({"sum.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)
        out = h.handle("u1, u2 만들고 요약")
        self.assertIn("과업 완수", out)
        replan = h.consumed[5]
        self.assertEqual(replan.label, "thinker-replan")
        self.assertIn("broken", replan.prompt)

    def test_structural_replan_executes_new_units_as_a_wave(self):
        cls = dict(CLS_WRITE, ambiguous=True, parallel_requested=True)
        seq = [
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker"),
            worker({"u1.txt": "1\n"}, self.root),
            worker({"u2.txt": "2\n"}, self.root),
            worker({"sum.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="bad-plan"),
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker-replan"),
            worker({"u1.txt": "1\n"}, self.root),
            worker({"u2.txt": "2\n"}, self.root),
            worker({"sum.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)

        out = h.handle("u1, u2 만들고 요약")

        self.assertIn("과업 완수", out)
        workers = [session for session in h.consumed if session.label == "worker"]
        self.assertEqual(len(workers), 6)
        self.assertEqual(sum("배정 단위 3" in session.prompt for session in workers), 2)


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
        seed_map_canary(self.root)
        direct = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("이 함수 뭐하는거야")
        self.assertEqual(len(h.consumed), 1)
        self.assertIn("MAP_CANARY", direct.system)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_active_lagom_streams_live_and_appends_rewrite_as_canonical(self):
        # 26-07-23: 검사 전 전량 버퍼링은 REPL 을 '먹통 → 한번에 팍' 으로 보이게 했다.
        # 새 계약: DIRECT 는 라곰 활성에도 라이브 스트리밍, 위반 시에만 교정 표식+정본을 덧붙인다.
        direct = FakeSession(
            SessionResult(text="혁신적 RAGX는 즉시 배포 가능하다.", stop_reason="end_turn"), label="direct"
        )
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(
            h, "_rewrite_lagom_text", return_value="RAGX는 JSON 키를 정렬하는 13줄짜리 도구다."
        ) as rewrite:
            h.handle("RAGX 소개를 답해. 사실: 13줄, JSON 키 정렬")
        rewrite.assert_called_once()
        self.assertFalse(direct.quiet)  # 스트리밍 계약 — DIRECT 세션의 on_text 는 살아 있다
        self.assertEqual(h.last_response_text, "RAGX는 JSON 키를 정렬하는 13줄짜리 도구다.")
        joined = "".join(h.texts)
        self.assertIn("⠶", joined)  # 교정 표식(언어 중립 글리프) — 초안과 정본이 갈렸음을 알린다
        self.assertIn(h.last_response_text, joined)

    def test_active_lagom_fails_closed_when_rewrite_still_violates_style(self):
        direct = FakeSession(SessionResult(text="혁신적 결과다.", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(h, "_rewrite_lagom_text", return_value="강력한 결과다."):
            h.handle("결과를 설명해")
        self.assertIn("문체 검사를 통과하지 못", h.last_response_text)
        # 정본(닫는 문구)은 교정 블록으로 표시되고, 실패한 재작성문이 정본 자리를 차지하지 않는다
        self.assertIn("문체 검사를 통과하지 못", "".join(h.texts))
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


class TestMemoryWriteTurn(Base):
    """기억 지시 턴 — memory_save 계약 + 실행 증거 봉합.

    26-07-21 실측 봉인: 모델이 ingest 없이 "기억했다" 허위 확답(2회 재현) → 도구 호출 성공이
    유일한 증거이고, 미호출은 원문 결정론 폴백으로 디스크에 반드시 남는다."""

    def _cls_read(self):
        return dict(CLS_WRITE, write_expected=False, criteria=[])

    def _pages(self):
        d = os.path.join(self.root, ".asgard", "memory", "pages")  # HOME=root 격리 — memory_dir 등가
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_memory_intent_opens_save_tool_and_records_evidence(self):
        direct = FakeSession(
            SessionResult(text="기억했다.", stop_reason="end_turn"),
            label="direct",
            tool_script=[("memory_save", {"text": "사용자 이름은 썬더오브갓", "kind": "user"})],
        )
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("내 이름은 썬더오브갓이야. 기억해줘.")
        self.assertIn("memory_save 계약", direct.system)  # 계약 주입
        self.assertTrue(any("썬더오브갓" in f for f in self._pages()))  # 디스크 진실
        self.assertIn("위그드라실에 새겼어요", h.last_response_text)
        self.assertNotIn("원문 폴백", h.last_response_text)

    def test_fabricated_claim_without_tool_falls_back_to_verbatim_ingest(self):
        direct = FakeSession(
            SessionResult(text="세션 메모리에 기록되었습니다.", stop_reason="end_turn"), label="direct"
        )
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("내 별명은 번개주먹이야. 기억해줘.")
        self.assertTrue(any("번개주먹" in f for f in self._pages()))
        self.assertIn("원문 폴백", h.last_response_text)
        log = open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read()
        self.assertIn("memory_write", log)
        self.assertIn("fallback", log)

    def test_plain_direct_turn_gets_no_memory_tool(self):
        direct = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("이 함수 뭐하는거야")
        self.assertNotIn("memory_save", direct.injected_handlers)
        self.assertNotIn("memory_save 계약", direct.system)
        self.assertEqual(self._pages(), [])


class TestExplorationHint(Base):
    """탐색 캐시 최소판 — Thinker 관찰 명령을 Worker 에 힌트로 전달 (게이트 증거 아님)."""

    def test_worker_gets_thinker_observations(self):
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="bad-plan"),
            thinker("계획: w1 을 만든다", commands=[{"cmd": "grep -rn foo src/", "exit_code": 0}]),
            worker({"w1.txt": "x\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=dict(CLS_WRITE, ambiguous=True))
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        w = [s for s in h.consumed if s.label == "worker"][1]
        self.assertIn("grep -rn foo src/", w.prompt)
        self.assertIn("재탐색 불필요", w.prompt)


class TestHookParity(Base):
    """quest_log ↔ verifier_gate 복제 코드 동등성 — 어긋나면 게이트↔전이 판정 분열."""

    def test_sensitive_path_segment_matching(self):
        from asgard.hooks.quest_log import sensitive_path as q
        from asgard.hooks.verifier_gate import sensitive_path as g

        needles = ["hooks", "ci", ".github", "auth", "authentication", "migration", "migrations", "db"]
        cases = {
            "circle.py": False,  # 'ci' substring 오탐 회귀 방지
            "ci/config.yml": True,
            ".github/workflows/x.yml": True,
            "hooks/deploy.py": True,
            "src/authentication.py": True,  # 파생형은 needle 목록에 명시 (substring 매칭 아님)
            "src/oauth.py": False,  # 'auth' 4자+ substring 오탐 회귀 방지 (26-07-23 감사)
            "src/author.py": False,  # 'auth' prefix 오탐 회귀 방지
            "src/auth.py": True,  # [._-] 토큰 정확 일치
            "src/db_pool.py": True,  # 토큰 일치 — db
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
    """ordinary write는 안전 가드가 허용하면 baseline으로 닫고, 아니면 Verifier로 승격한다."""

    def policy(self, **kw):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w") as f:
            json.dump(kw, f)

    def test_standard_closes_with_green_baseline(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        h = FakeHeimdall(
            self.root,
            [worker({"w1.txt": "x\n", "test_w1.py": "def test_w1(): assert True\n"}, self.root)],
            cls={**CLS_WRITE, "task_class": "standard"},
        )
        out = h.handle("w1.txt 만들어")
        self.assertIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker"])
        self.assertIn('"harness"', self.quest_log_text())
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_ambiguous_deep_write_starts_single_worker_without_thinker(self):
        work = worker({"w1.txt": "x\n"}, self.root)
        h = FakeHeimdall(
            self.root,
            [work, verifier("PASS")],
            cls={**CLS_WRITE, "ambiguous": True, "task_class": "deep"},
        )

        out = h.handle("모호한 부분은 합리적으로 판단해서 w1.txt 만들어")

        self.assertIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier"])
        self.assertIn("성공 기준:", work.prompt)

    def test_standard_red_gives_worker_retry_with_failing_check(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        seq = [
            worker(
                {
                    "w1.txt": "x\n",
                    "test_fixed.py": "from pathlib import Path\n\ndef test_fixed(): assert Path('fixed.txt').exists()\n",
                },
                self.root,
            ),
            worker({"fixed.txt": "y\n"}, self.root),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("고쳐줘")
        self.assertIn("과업 완수", out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "worker"])
        self.assertIn("baseline-red", seq[1].prompt or "")  # 실패 체크가 재시도 컨텍스트로 전달

    def test_invalid_verdict_is_recorded_as_fail_instead_of_crashing(self):
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier("Pass"),
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("고쳐줘")
        self.assertIn("과업 완수", out)
        events = [json.loads(line) for line in self.quest_log_text().splitlines() if line.strip()]
        failures = [event for event in events if event.get("event") == "verify" and event.get("verdict") == "FAIL"]
        self.assertEqual(failures[0]["failure_sig"], "invalid-verdict-submitted")

    def test_empty_classifier_criteria_is_bound_to_request_for_every_role(self):
        cls = {**CLS_WRITE, "criteria": [], "task_class": "standard"}
        seq = [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")]
        h = FakeHeimdall(self.root, seq, cls=cls)
        request = "Create w1.txt containing x"
        out = h.handle(request)
        self.assertIn("과업 완수", out)
        self.assertIn(request, seq[1].prompt)
        self.assertNotIn("criteria: []", seq[1].prompt)
        opened = json.loads(self.quest_log_text().splitlines()[0])
        self.assertEqual(opened["criteria"], [f"요청 본문과 변경 결과가 일치함: {request}"])

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
                cwd=None,
            ):
                captured["system"] = system
                return super()._session(system, extra_tools, handlers, quiet, role, model, readonly)

        seed_map_canary(self.root)
        h = Capture(self.root, [worker(root=self.root)])
        h._prepare_map("버튼 라벨 수정")
        h._dispatch_handler("s1", [])({"agent": "freyja", "task": "버튼 라벨 수정", "why": "w"})
        self.assertNotIn("<memory-context", captured["system"])
        self.assertIn("asgard-freyja", captured["system"])  # role 본문은 그대로
        self.assertIn("MAP_CANARY", captured["system"])


class TestNativeThorSquad(Base):
    """thor-lead 물리 fan-out — split(비중첩 병합)·tournament(패치 회수) 두 계약."""

    def _capture_heimdall(self, sessions):
        calls = []

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
                cwd=None,
            ):
                calls.append({"role": role, "system": system, "tools": extra_tools or [], "handlers": handlers or {}})
                return super()._session(system, extra_tools, handlers, quiet, role, model, readonly, rp_override, cwd)

        return Capture(self.root, sessions), calls

    def test_lead_gets_bounded_squad_tool_and_children_do_not(self):
        lead = worker(root=self.root, text="lead ready")
        child_a = worker(root=self.root, text="a")
        child_b = worker(root=self.root, text="b")
        h, calls = self._capture_heimdall([lead, child_a, child_b])
        writes = []
        h._dispatch_handler("s1", writes)({"agent": "thor-lead", "task": "대형 백엔드 과업", "why": "다표면 분할"})

        self.assertEqual(calls[0]["role"], "thor-lead")
        self.assertIn("백엔드 전문가", calls[0]["system"])  # 선언이 아니라 Thor 코어 본문 물리 상속
        self.assertIn("사전 진단 게이트", calls[0]["system"])
        self.assertIn("asgard-thor-einherjar", calls[0]["system"])
        self.assertEqual([t["name"] for t in calls[0]["tools"]], ["load_skill", "dispatch_thor_squad"])
        self.assertIn(
            "에인헤랴르 편대 (팀 백엔드 작업)",
            calls[0]["handlers"]["load_skill"]({"name": "asgard-thor-einherjar"}),
        )
        squad = calls[0]["handlers"]["dispatch_thor_squad"]
        result = json.loads(
            squad(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "핸들러 계층 정리", "scope": ["src/api"], "why": "표면 분리"},
                        {"id": "db", "task": "저장 계층 정리", "scope": ["src/db"], "why": "표면 분리"},
                    ],
                }
            )
        )
        self.assertEqual(result["mode"], "split")
        self.assertEqual({r["id"] for r in result["results"]}, {"api", "db"})
        self.assertEqual(result["failures"], [])
        self.assertEqual([c["role"] for c in calls[1:]], ["thor", "thor"])
        self.assertTrue(all([t["name"] for t in c["tools"]] == ["load_skill"] for c in calls[1:]))
        for c in calls[1:]:
            self.assertNotIn("에인헤랴르 편대 (팀 백엔드 작업)", c["system"])  # 서브에 편대 프로토콜 본문 무주입

    def test_split_rejects_overlapping_scopes_at_declaration(self):
        h = FakeHeimdall(self.root, [])
        with self.assertRaises(ValueError):
            h._thor_squad_handler("s1", [], self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "a", "task": "t", "scope": ["src/api"], "why": "w"},
                        {"id": "b", "task": "t", "scope": ["src/api/handlers"], "why": "w"},  # 프리픽스 교차
                    ],
                }
            )

    def test_split_children_cannot_write_outside_scope(self):
        def escaping_child(name: str):
            session = FakeSession(SessionResult(text=name, stop_reason="end_turn", writes=["unauthorized.txt"]))

            def effect():
                open(os.path.join(session.cwd, "unauthorized.txt"), "w").write(name)

            session.effect = effect
            return session

        h = FakeHeimdall(self.root, [escaping_child("a"), escaping_child("b")])
        result = json.loads(
            h._thor_squad_handler("s1", [], self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "t", "scope": ["src/api"], "why": "w"},
                        {"id": "db", "task": "t", "scope": ["src/db"], "why": "w"},
                    ],
                }
            )
        )
        self.assertEqual(result["results"], [])
        self.assertEqual({failure["id"] for failure in result["failures"]}, {"api", "db"})
        self.assertTrue(all("scope violation" in failure["error"] for failure in result["failures"]))
        self.assertFalse(os.path.exists(os.path.join(self.root, "unauthorized.txt")))

    def test_split_merges_scoped_writes(self):
        def scoped_child():
            session = FakeSession(SessionResult(text="scoped", stop_reason="end_turn"))

            def effect():
                unit = "api" if "편대 단위 api" in session.prompt else "db"
                rel = f"src/{unit}/service.py"
                session.result.writes = [rel]
                path = os.path.join(session.cwd, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").write(f"# {unit}\n")

            session.effect = effect
            return session

        h = FakeHeimdall(self.root, [scoped_child(), scoped_child()])
        writes = []
        result = json.loads(
            h._thor_squad_handler("s1", writes, self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "t", "scope": ["src/api"], "why": "w"},
                        {"id": "db", "task": "t", "scope": ["src/db"], "why": "w"},
                    ],
                }
            )
        )
        self.assertEqual(result["failures"], [])
        self.assertEqual(set(writes), {"src/api/service.py", "src/db/service.py"})
        for unit in ("api", "db"):
            self.assertIn(unit, open(os.path.join(self.root, f"src/{unit}/service.py")).read())

    def test_squad_children_discover_learned_skills_and_load_on_demand(self):
        seed_learned_skill(self.root, "migration-lesson", triggers="마이그레이션", agent="thor")
        children = [
            FakeSession(SessionResult(text="a", stop_reason="end_turn")),
            FakeSession(SessionResult(text="b", stop_reason="end_turn")),
        ]
        h = FakeHeimdall(self.root, children)
        result = json.loads(
            h._thor_squad_handler("s1", [], self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "api 마이그레이션", "scope": ["src/api"], "why": "w"},
                        {"id": "db", "task": "db 마이그레이션", "scope": ["src/db"], "why": "w"},
                    ],
                }
            )
        )

        self.assertEqual(result["failures"], [])
        for child in h.consumed:
            self.assertIn("migration-lesson", child.system)
            self.assertNotIn("migration-lesson 본문", child.system)
            self.assertIn(
                "migration-lesson 본문",
                child.injected_handlers["load_skill"]({"name": "migration-lesson"}),
            )

    def test_tournament_collects_patches_without_applying(self):
        def variant_child(marker: str):
            session = FakeSession(SessionResult(text=marker, stop_reason="end_turn"))

            def effect():
                rel = "src/core/fix.py"
                session.result.writes = [rel]
                path = os.path.join(session.cwd, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").write(f"# variant {marker}\n")

            session.effect = effect
            return session

        h = FakeHeimdall(self.root, [variant_child("v1"), variant_child("v2")])
        writes = []
        result = json.loads(
            h._thor_squad_handler("s1", writes, self.root)(
                {
                    "mode": "tournament",
                    "tasks": [
                        # 토너먼트는 같은 난제 — scope 중첩이 허용된다
                        {"id": "v1", "task": "t", "scope": ["src/core"], "why": "접근 A"},
                        {"id": "v2", "task": "t", "scope": ["src/core"], "why": "접근 B"},
                    ],
                }
            )
        )
        self.assertEqual(result["mode"], "tournament")
        self.assertEqual(result["failures"], [])
        self.assertIn("본류 미적용", result["note"])
        # 본류에는 미적용 — 패치 파일만 회수된다 (승자 적용·검증은 대장 몫)
        self.assertFalse(os.path.exists(os.path.join(self.root, "src/core/fix.py")))
        for vid in ("v1", "v2"):
            rel = f"deliverables/thor-tournament/{vid}.patch"
            self.assertIn(rel, writes)
            body = open(os.path.join(self.root, rel), "rb").read().decode("utf-8", "replace")
            self.assertIn("src/core/fix.py", body)


class TestFrozenSnapshotIntegration(Base):
    """감사 공백 ①: 생성 후 메모리를 변경해도 기존 Heimdall 인스턴스의 system 바이트는 불변.

    frozen snapshot 계약(캐시 정합성)의 통합 회귀 — 구성요소 테스트가 아니라 실제 인스턴스의
    identity/system 바이트를 직접 대조한다. recall(프롬프트 측)은 라이브가 계약이므로 미대상."""

    def test_memory_mutation_after_construction_keeps_system_bytes_frozen(self):
        from asgard import memory

        old_env = os.environ.get(memory.MEMORY_ENV)
        os.environ[memory.MEMORY_ENV] = os.path.join(self.root, "mem")
        self.addCleanup(
            lambda: (
                os.environ.pop(memory.MEMORY_ENV, None)
                if old_env is None
                else os.environ.__setitem__(memory.MEMORY_ENV, old_env)
            )
        )
        memory.add("동결 전 사실 알파", title="alpha-fact", kind="note")
        turns = [
            FakeSession(SessionResult(text="답1", stop_reason="end_turn"), label="direct"),
            FakeSession(SessionResult(text="답2", stop_reason="end_turn"), label="direct"),
        ]
        h = FakeHeimdall(self.root, turns, cls=CLS_DIRECT)
        identity_before = h.identity
        self.assertIn("alpha-fact", identity_before)  # 스냅샷이 실제로 실렸는지 전제 확인
        h.handle("알파 사실이 뭐였지")
        memory.add("세션 중 추가된 사실 베타", title="beta-fact", kind="note")  # 생성 후 변이
        h.handle("알파 사실이 뭐였지")  # 동일 요청 — request 파생 주입분까지 동일 조건
        self.assertEqual(turns[0].system, turns[1].system)  # system 바이트 불변
        self.assertNotIn("beta-fact", turns[1].system)
        self.assertEqual(h.identity, identity_before)  # 동결 원본 자체도 불변


class TestMemoryRoleMatrix(Base):
    """감사 매트릭스: DIRECT·호출된 Thinker = 스냅샷+회수, standard Worker = 요청 관련 회수만,
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

    def test_replan_thinker_injected_worker_verifier_not(self):
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
                cwd=None,
            ):
                systems.append(system)
                return super()._session(system, extra_tools, handlers, quiet, role, model, readonly, rp_override, cwd)

        cls = {**CLS_WRITE, "task_class": "deep", "shared": True}
        h = Cap(
            self.root,
            [
                worker({"w1.txt": "bad\n"}, self.root),
                verifier("FAIL", structural=True, sig="bad-plan"),
                thinker("재설계"),
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
            cls=cls,
        )
        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier", "thinker", "worker", "verifier"])
        role_systems = list(zip((s.role for s in h.consumed), systems, strict=True))
        thinker_session = next(s for s in h.consumed if s.label == "thinker")
        self.assertIn("<memory-context", next(system for role, system in role_systems if role == "thinker"))
        self.assertIn("<memory-recall", thinker_session.prompt)
        for role, system in role_systems:
            if role in ("worker", "verifier"):
                self.assertNotIn("<memory-context", system)
        for session in h.consumed:
            if session.role in ("worker", "verifier"):
                self.assertNotIn("<memory-recall", session.prompt)

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
            '[memory]\nproviders = ["ollama"]\n\n[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        fallback = thinker("fallback plan")
        cls = {**CLS_WRITE, "task_class": "deep"}
        h = FakeHeimdall(
            self.root,
            [
                worker({"w1.txt": "bad\n"}, self.root),
                verifier("FAIL", structural=True, sig="bad-plan"),
                failed,
                fallback,
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
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
            '[memory]\nproviders = ["anthropic"]\n\n[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        fallback = thinker("fallback plan")
        cls = {**CLS_WRITE, "task_class": "deep"}
        h = FakeHeimdall(
            self.root,
            [
                worker({"w1.txt": "bad\n"}, self.root),
                verifier("FAIL", structural=True, sig="bad-plan"),
                failed,
                fallback,
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
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


class TestTurnRecapCollector(unittest.TestCase):
    """턴 recap 집계(_record_tool) — 툴 카운트·수정 파일(view 제외·root 상대화)·커맨드 첫 단어."""

    def test_record_tool_aggregates_tools_files_and_commands(self):
        from types import SimpleNamespace
        from typing import cast

        from asgard.agent.heimdall import core

        # _state_lock/turn_recap/root 만 쓰는 최소 대역 — ty invalid-argument-type 내로잉 (45297ac 처방)
        hd = cast(
            core.Heimdall, SimpleNamespace(_state_lock=threading.Lock(), turn_recap=core._new_recap(), root="/repo")
        )
        core.Heimdall._record_tool(hd, "bash", {"command": "pytest -q tests"})
        core.Heimdall._record_tool(hd, "bash", {"command": "pytest -x"})
        core.Heimdall._record_tool(
            hd, "str_replace_based_edit_tool", {"command": "str_replace", "path": "/repo/src/a.py"}
        )
        core.Heimdall._record_tool(hd, "str_replace_based_edit_tool", {"command": "view", "path": "/repo/src/b.py"})
        core.Heimdall._record_tool(hd, "str_replace_based_edit_tool", {"command": "create", "path": "src/c.py"})

        self.assertEqual(hd.turn_recap["tools"]["bash"], 2)
        self.assertEqual(hd.turn_recap["tools"]["str_replace_based_edit_tool"], 3)
        # view 제외·절대경로 상대화·파일별 작업 종류와 횟수
        self.assertEqual(
            hd.turn_recap["files"], {"src/a.py": {"op": "edit", "n": 1}, "src/c.py": {"op": "create", "n": 1}}
        )
        self.assertEqual(hd.turn_recap["cmds"], {"pytest": 2})

    def test_memory_write_outcome_records_recap_event(self):
        from types import SimpleNamespace
        from typing import cast

        from asgard.agent.heimdall import core

        with tempfile.TemporaryDirectory() as root:
            # _state_lock/turn_recap/root 만 쓰는 최소 대역 — cast 는 소비 직전 1회 (ty 내로잉, 45297ac 처방)
            ns = SimpleNamespace(_state_lock=threading.Lock(), turn_recap=core._new_recap(), root=root)
            ns._recap_event = lambda text: core.Heimdall._recap_event(cast(core.Heimdall, ns), text)
            hd = cast(core.Heimdall, ns)

            notice = core.Heimdall._memory_write_outcome(hd, "pytest 선호 기억해", [("created", "pytest-pref")])

        self.assertIn("pytest-pref", notice)
        self.assertEqual(hd.turn_recap["events"], ["carved into Yggdrasil: pytest-pref"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
