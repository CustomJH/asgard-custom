#!/usr/bin/env python3
"""Heimdall 시험 공용 하네스 — mocked AgentSession, API 호출 0.

FakeSession이 스크립트된 응답·verdict 툴콜·관측 커맨드를 돌려주고, effect로 워킹트리를 실제로
바꾼다 (diff-hash 물리 검증은 진짜 quest-log/gate subprocess가 수행 — 배포 형태 그대로).

시험 본문은 주제별 `test_*.py` 에 있다. 실행: uv run pytest tests/heimdall
"""

import json
import os
import subprocess
import tempfile
import unittest

from asgard.agent.heimdall import Heimdall
from asgard.agent.session import SessionResult
from asgard.i18n import t
from asgard.providers import PROVIDERS, ResolvedProvider

DONE = t("report_done")  # Trinity 최종 보고 첫 줄 — i18n 계약 앵커 (하드코딩 금지)

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
    """_session을 스크립트 큐로 대체 — 소비 순서·프롬프트를 검증 표면으로 노출."""

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
        label="",
    ):
        with self._lock:  # wave 병렬 스레드가 동시에 pop — 순서 보호
            if not self._script:
                raise AssertionError("스크립트된 세션 소진 — 예상보다 많은 역할 턴")
            s = self._script.pop(0)
            s.role = role
            # `label`(관측에 적히는 이름)은 여기 안 적는다 — 이 대역의 `s.label`은 이미 역할
            # 이름을 드는 자리라 덮어쓰면 판마다 그 단언이 무너진다.
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
        # 증거 둘 — 다중 파일 웨이브는 깊은 변경이라 증거 하한(MIN_DEEP_EVIDENCE)에 걸린다.
        # 하한 자체는 TestDeepEvidenceFloor 가 보고, 여기 시험들은 웨이브 배선을 본다.
        inp = {
            "verdict": verdict,
            "criteria": CLS_WRITE["criteria"],
            "commands": [{"cmd": "fake", "exit_code": 0}, {"cmd": "pytest -q", "exit_code": 0}],
        }
        if structural:
            inp["structural"] = True
        if sig:
            inp["failure_sig"] = sig
        if why:
            inp["why"] = why
        tool_calls = [{"name": "verdict", "input": inp}]
    if commands is None:
        commands = (
            [{"cmd": "pytest -q", "exit_code": 0}, {"cmd": "python3 -m compileall -q .", "exit_code": 0}]
            if observed
            else []
        )
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
    """승인 receipt 포함 learned 스킬 시드 — HOME이 테스트 root라 키도 격리 생성된다."""
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


PLAN_WITH_UNITS = """계획: 두 파일을 만들고 요약을 붙인다.

```json
{"units": [
  {"id": 1, "subtask": "u1.txt 생성", "files": ["u1.txt"], "criteria": ["u1.txt 존재"], "access": []},
  {"id": 2, "subtask": "u2.txt 생성", "files": ["u2.txt"], "criteria": ["u2.txt 존재"], "access": []},
  {"id": 3, "subtask": "요약 파일 생성", "files": ["sum.txt"], "criteria": ["sum.txt 존재"], "access": [1]}
]}
```"""
