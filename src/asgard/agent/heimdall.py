"""Heimdall 오케스트레이터 (CUS-137) — 네이티브 Trinity 순환.

구조 (CUS-135/142 합의):
  Odin 요청 → [분류] → DIRECT (write 없음, 무세금)
                    → Trinity: 원장 open → 매 턴 전이 함수(quest-log next, 결정론) →
                      역할 세션(child context) → 원장 기록(하니스가 결정론 수행) →
                      Verifier verdict 툴 → 게이트(verifier-gate, 루프 종료 지점) → close

Claude Code 모드 B 와의 차이: 거기선 모델이 quest-log CLI 를 스스로 실행하지만, 네이티브에선
**하니스가 원장을 기록**한다 — 프로토콜 준수가 모델 순응이 아니라 코드 경로다. 훅 자체는
subprocess 배포 형태로 재사용 (36/36 테스트된 계약, 재구현 금지). 상태는 같은 .asgard/ —
Claude Code/Codex/Cursor 세션과 원장을 이어 쓴다 (크로스툴 연속성).

중첩 디스패치 (CUS-142): Worker 에 dispatch 툴 — 딜리버리 전문가(child context, depth 1)에
위임하고 배정 근거를 delegate 이벤트로 원장에 남긴다. 딜리버리는 재위임 불가 (툴 미제공).
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable

from ..agents import ROLE_AGENTS
from ..providers import ResolvedProvider
from ..templates import agents_md
from .session import AgentSession, SessionResult, gate, make_client, ql

MAX_TRINITY_TURNS = 12  # budget_priors.deep — 이 위는 폭주로 간주, Odin 보고

# 역할 심볼 (AGENTS.md 이모지 일관) — REPL 전이 표시에 씀
_ROLE_ICON = {
    "THINKER": "🧠", "THINKER_REPLAN": "🧠", "WORKER": "🔨", "WORKER_RETRY": "🔨",
    "VERIFIER": "⚖️", "DONE": "✔", "DIRECT_DONE": "→", "ESCALATE_ODIN": "⚠",
}


def _transition_line(role: str, why: str) -> str:
    from .. import theme, ui
    icon = _ROLE_ICON.get(role, "◇")
    return f"\n  {ui.paint(theme.ansi(theme.PRIMARY), icon)} {ui.bold(role)} {ui.dim('· ' + why)}\n"

NATIVE_NOTE = """

## 네이티브 세션 규칙 (하니스 자동화)
이 세션은 Asgard 네이티브 루프다. 퀘스트 원장 기록·전이 함수·verifier-gate 는 **하니스가 자동
수행**한다 — quest-log 명령을 직접 실행하지 마라 (이중 기록). Verifier 판정은 verdict 툴로만
제출한다. 완료 선언은 여전히 금지 — 판정은 Verifier + 게이트 몫이다 (Canon 10)."""

_DELIVERY = {  # CUS-142 v1 — CUS-129 딜리버리 계층의 네이티브 표면 (친숙한 신만)
    "freyja": "# asgard-freyja — 🌹 UI/UX 전문가 (딜리버리)\n프론트엔드·스타일·접근성 전담. "
              "Worker 계약 상속: 배정 범위만, 완료 선언 금지, 관찰 선행. 재위임 불가.",
    "thor": "# asgard-thor — ⚡ 빌드·인프라 전문가 (딜리버리)\n빌드 파이프라인·CI·패키징 전담. "
            "Worker 계약 상속: 배정 범위만, 완료 선언 금지. 재위임 불가.",
    "loki": "# asgard-loki — 🐍 adversarial 전문가 (딜리버리)\n엣지케이스·반례·회귀 탐색 전담. "
            "코드 수정 금지(관찰·재현만). 재위임 불가.",
}

VERDICT_TOOL = {
    "name": "verdict",
    "description": "Verifier 전용 — 구조화 판정 제출. 검증 명령을 직접 실행한 뒤에만 호출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["PASS", "FAIL", "ESCALATE"]},
            "criteria": {"type": "array", "items": {"type": "string"}},
            "commands": {"type": "array", "items": {"type": "object", "properties": {
                "cmd": {"type": "string"}, "exit_code": {"type": "integer"}},
                "required": ["cmd", "exit_code"]}},
            "failure_sig": {"type": "string", "description": "FAIL 시 동종 실패 시그니처"},
            "why": {"type": "string"},
        },
        "required": ["verdict", "criteria", "commands"],
    },
}

DISPATCH_TOOL = {
    "name": "dispatch",
    "description": "딜리버리 전문가에게 하위 작업 위임 (freyja=UI/UX, thor=빌드/인프라, loki=adversarial). "
                   "위임 전 누구에게·왜를 고민하고 why 에 근거를 남겨라 — 원장에 기록된다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "enum": list(_DELIVERY)},
            "task": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["agent", "task", "why"],
    },
}

def _identity(root: str) -> str:
    p = os.path.join(root, "AGENTS.md")
    if os.path.exists(p):
        try:
            return open(p, encoding="utf-8").read() + NATIVE_NOTE
        except Exception:
            pass
    return agents_md(os.path.basename(root)) + NATIVE_NOTE  # 내장 정체성 (스캐폴드 불요)


def _role_prompt(fname: str) -> str:
    body = dict(ROLE_AGENTS)[fname]
    parts = body.split("---", 2)  # frontmatter 제거 — 네이티브에선 모델/툴 선언 무의미
    return (parts[2] if len(parts) == 3 else body) + NATIVE_NOTE


def _record_writes(root: str, sid: str, writes: list[str]) -> None:
    """write-sentinel 대응 — 네이티브 세션의 write 흔적을 게이트가 보는 파일에 기록."""
    if not writes:
        return
    d = os.path.join(root, ".asgard")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f"writes-{sid}.json")
    try:
        prev = json.load(open(f))
    except Exception:
        prev = []
    merged = prev + [w for w in writes if w not in prev]
    json.dump(merged[:500], open(f, "w"))


class Heimdall:
    def __init__(self, rp: ResolvedProvider, root: str, on_text: Callable[[str], None],
                 on_status: Callable[[str | None], None] | None = None):
        self.rp, self.root, self.on_text = rp, root, on_text
        self.on_status = on_status or (lambda s: None)
        self.client = make_client(rp)
        self.identity = _identity(root)
        self.total_tokens = 0  # 세션 누적 (status line 사용량)

    def _add_tokens(self, n: int) -> None:
        self.total_tokens += n

    def _session(self, system: str, extra_tools=None, handlers=None, quiet=False) -> AgentSession:
        return AgentSession(self.client, self.rp, self.root, system,
                            extra_tools=extra_tools, tool_handlers=handlers,
                            on_text=(lambda s: None) if quiet else self.on_text,
                            on_tokens=self._add_tokens, on_status=self.on_status)

    def _classify(self, request: str) -> dict:
        # structured-output 강제 대신 "JSON 만 출력" + 관대한 파싱 — 두 트랜스포트(및 nemotron 류
        # JSON-mode 불확실 모델) 공통. 파싱 실패는 안전 기본값(write 로 간주 → 게이트가 잡는다).
        sysmsg = ("과업 분류기. 요청을 읽고 아래 JSON 만 출력한다 (설명 금지, JSON 앞뒤 텍스트 금지). "
                  "write_expected = 파일을 생성·수정해야 하는 과업이면 true. "
                  "**질문·계산·설명·조회처럼 답만 하면 되는 것은 false** (예: '1+1?', '이 함수 설명해'). "
                  "criteria 는 write 과업일 때만, 명령으로 확인 가능한 형태로. "
                  '{"write_expected":bool,"ambiguous":bool,"destructive":bool,'
                  '"external_research":bool,"shared":bool,"criteria":[str]}')
        raw = self._complete_text(sysmsg, request, max_tokens=2000)
        try:
            s = raw[raw.index("{"):raw.rindex("}") + 1]
            d = json.loads(s)
            for k in ("write_expected", "ambiguous", "destructive", "external_research", "shared"):
                d[k] = bool(d.get(k))
            d["criteria"] = [str(c) for c in (d.get("criteria") or [])]
            return d
        except Exception:
            return {"write_expected": True, "ambiguous": True, "destructive": False,
                    "external_research": False, "shared": False, "criteria": []}

    def _complete_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """비스트리밍 단발 completion — 트랜스포트 무관 (classify 등 내부 판단용)."""
        if self.rp.profile.api_mode == "anthropic":
            resp = self.client.messages.create(
                model=self.rp.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}])
            return "".join(b.text for b in resp.content if b.type == "text")
        resp = self.client.chat.completions.create(
            model=self.rp.model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content or ""

    # ── 딜리버리 디스패치 (CUS-142, depth 1) ─────────────────────────────
    def _dispatch_handler(self, sid: str, worker_result_writes: list[str]):
        def handler(inp: dict) -> str:
            agent, task, why = inp["agent"], inp["task"], inp.get("why", "")
            from .. import theme, ui
            self.on_text(f"\n  {ui.paint(theme.ansi(theme.PRIMARY), '⤷')} {ui.bold(agent)} {ui.dim('위임 · ' + why[:80])}\n")
            ql(self.root, "append", session=sid, stdin=json.dumps(
                {"role": "worker", "event": "delegate",
                 "commands": [{"cmd": f"dispatch:{agent} — {why[:120]}", "exit_code": 0}]}))
            child = self._session(_DELIVERY[agent] + "\n\n" + self.identity)  # dispatch 툴 미제공 = 재위임 불가
            r = child.run(task)
            worker_result_writes.extend(r.writes)
            return f"[{agent}] {r.text[-2000:]}"
        return handler

    # ── Trinity 순환 ─────────────────────────────────────────────────────
    def _trinity(self, request: str, cls: dict) -> str:
        qid = f"native-{int(time.time())}"
        sid = qid
        args = ["open", qid] + [x for c in (cls["criteria"] or ["요청 충족을 검증 명령으로 입증"])
                                for x in ("--criteria", c)]
        ql(self.root, *args, session=sid)
        flag_args = [f for f, on in (("--ambiguous", cls["ambiguous"]),
                                     ("--external-research", cls["external_research"]),
                                     ("--shared", cls["shared"]), ("--write-expected", True)) if on]
        plan_ctx = ""  # Thinker 계획을 Worker 에 전달

        for _ in range(MAX_TRINITY_TURNS):
            nxt = json.loads(ql(self.root, "next", *flag_args, session=sid).stdout or "{}")
            role, why = nxt.get("next_role", ""), nxt.get("why", "")
            self.on_text(_transition_line(role, why))

            if role == "DONE":
                blocked, reason = gate(self.root, sid)
                if blocked:  # 전이/게이트 판정 불일치 방어 — 재검증 유도
                    self.on_text(f"⛔ gate: {reason[:200]}\n")
                    continue
                ql(self.root, "close", session=sid)
                return "과업 완수 — Verifier PASS + diff-hash 일치, 원장 닫힘."
            if role == "ESCALATE_ODIN":
                ql(self.root, "append", session=sid, stdin=json.dumps(
                    {"role": "verifier", "event": "verify"}), )
                return f"⚠ Odin 결정 필요 — {why}"
            if role == "DIRECT_DONE":
                return self._direct(request)

            if role in ("THINKER", "THINKER_REPLAN"):
                r = self._session(_role_prompt("asgard-thinker.md")).run(
                    f"과업: {request}\n\n(재계획: {why})" if role == "THINKER_REPLAN" else f"과업: {request}")
                plan_ctx = r.text
                ql(self.root, "append", session=sid, stdin=json.dumps(
                    {"role": "thinker", "event": "plan", "criteria": cls["criteria"]}))
            elif role in ("WORKER", "WORKER_RETRY"):
                writes: list[str] = []
                s = self._session(_role_prompt("asgard-worker.md"), extra_tools=[DISPATCH_TOOL],
                                  handlers={"dispatch": self._dispatch_handler(sid, writes)})
                r = s.run(f"과업: {request}\n\n계획:\n{plan_ctx[:4000]}\n\n"
                          + ("(재시도 — 직전 FAIL 사유를 수정하라)" if role == "WORKER_RETRY" else ""))
                writes.extend(r.writes)
                _record_writes(self.root, sid, writes)
                ql(self.root, "append", session=sid, stdin=json.dumps(
                    {"role": "worker", "event": "work", "changed_files": writes[:50],
                     "commands": r.commands[-20:]}))
            elif role == "VERIFIER":
                level = nxt.get("verify_level", "micro")
                # 원장 관측 diff 컨텍스트 — 검증자가 "diff 없음"으로 헛FAIL 하지 않게 물리 관측을
                # 손에 쥐여준다 (판정은 여전히 직접 명령 실행으로).
                st = {}
                try:
                    st = json.loads(ql(self.root, "state", session=sid).stdout or "{}")
                except Exception:
                    pass
                changed = ", ".join((st.get("changed_files") or [])[:20]) or "(없음)"
                s = self._session(_role_prompt("asgard-verifier.md"),
                                  extra_tools=[VERDICT_TOOL], handlers={"verdict": lambda i: "판정 접수"})
                r = s.run(f"검증하라. 요청: {request}\ncriteria: {cls['criteria']}\n"
                          f"required level: {level}\n"
                          f"원장 관측 변경 파일: {changed} (diff_lines={st.get('diff_lines', '?')}) — "
                          f"`git diff` / 파일 열람 / 실행으로 직접 확인하라.\n"
                          f"Worker 해설은 입력이 아니다 — diff 와 명령 실행으로만 판정. 판정은 반드시 verdict 툴로 제출.")
                v = next((c["input"] for c in r.tool_calls if c["name"] == "verdict"), None)
                if not v:
                    v = {"verdict": "FAIL", "criteria": cls["criteria"], "commands": [],
                         "failure_sig": "no-verdict-submitted"}
                ev = {"role": "verifier", "event": "verify", "criteria": v.get("criteria") or cls["criteria"],
                      "commands": v.get("commands") or []}
                if v.get("failure_sig"):
                    ev["failure_sig"] = v["failure_sig"]
                ql(self.root, "append", "--verdict", v["verdict"], "--level", level,
                   session=sid, stdin=json.dumps(ev))
            else:
                return f"⚠ 미지의 전이 상태 '{role}' — Odin 보고 (원장: .asgard/quest/{qid}.jsonl)"

        return f"⚠ 턴 예산({MAX_TRINITY_TURNS}) 소진 — Odin 보고. 원장: .asgard/quest/{qid}.jsonl"

    def _direct(self, request: str) -> str:
        """DIRECT 응답 — 본문은 on_text 로 이미 스트리밍됨. 빈 문자열 반환해 이중 출력 방지.
        예외: refusal 안내는 스트림에 안 실린 합성 텍스트 — 그것만 반환."""
        r = self._session(self.identity).run(request)
        return r.text if r.stop_reason == "refusal" else ""

    # ── 진입점 ───────────────────────────────────────────────────────────
    def handle(self, request: str) -> str:
        from ..i18n import t
        self.on_status(t("thinking"))  # 분류도 모델 호출 — 침묵 구간 커버
        try:
            cls = self._classify(request)
        finally:
            self.on_status(None)
        if cls["destructive"]:
            return "⚠ 파괴 작업 감지 — Odin 명시 동의 필요 (Canon 3). 대상과 함께 재요청하세요."
        if not cls["write_expected"]:
            return self._direct(request)  # DIRECT — 무세금
        return self._trinity(request, cls)
