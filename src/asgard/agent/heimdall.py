"""Heimdall 오케스트레이터 (CUS-137) — 네이티브 Trinity 순환.

구조 (CUS-135/142 합의):
  Odin 요청 → [분류] → DIRECT (write 없음, 무세금)
                    → Trinity: 퀘스트 로그 open → 매 턴 전이 함수(quest-log next, 결정론) →
                      역할 세션(child context) → 퀘스트 로그 기록(하니스가 결정론 수행) →
                      Verifier verdict 툴 → 게이트(verifier-gate, 루프 종료 지점) → close

Claude Code 모드 B 와의 차이: 거기선 모델이 quest-log CLI 를 스스로 실행하지만, 네이티브에선
**하니스가 퀘스트 로그을 기록**한다 — 프로토콜 준수가 모델 순응이 아니라 코드 경로다. 훅 자체는
subprocess 배포 형태로 재사용 (36/36 테스트된 계약, 재구현 금지). 상태는 같은 .asgard/ —
Claude Code/Codex/Cursor 세션과 퀘스트 로그을 이어 쓴다 (크로스툴 연속성).

중첩 디스패치 (CUS-142): Worker 에 dispatch 툴 — 딜리버리 전문가(child context, depth 1)에
위임하고 배정 근거를 delegate 이벤트로 퀘스트 로그에 남긴다. 딜리버리는 재위임 불가 (툴 미제공).
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Callable

from ..providers import ResolvedProvider, resolve_trinity
from ..templates import agents_md
from ..templates.roles import ROLE_AGENTS
from .session import AgentSession, gate, make_client, ql

MAX_TRINITY_TURNS = 12  # budget_priors.deep — 이 위는 폭주로 간주, Odin 보고

# 전이 상태 → [trinity.<role>] 설정 키 (역할별 provider 배치)
_ROLE_KEY = {
    "THINKER": "thinker",
    "THINKER_REPLAN": "thinker",
    "WORKER": "worker",
    "WORKER_RETRY": "worker",
    "VERIFIER": "verifier",
}

# ── 모델 티어 (CUS-177) — 정책 tier → anthropic 모델. 상황별 호출: 역할 기본 + full-verify/재계획 승급.
# 명시 placement([trinity.<role>])나 사용자 지정 모델은 존중 — 티어 매핑은 기본 모델일 때만 적용.
_TIER_MODELS = {
    "fast": "claude-haiku-4-5-20251001",
    "standard": "claude-sonnet-5",
    "high": "claude-opus-4-8",
    "max": "claude-fable-5",
}
_TIER_UP = {"fast": "standard", "standard": "high", "high": "max", "max": "max"}
# 딜리버리 전문가 기본 티어 — 정책 파일 "delivery" 로 조정 (freyja/thor=구현, loki=read-only 반례 탐색)
_DELIVERY_TIERS = {"freyja": "standard", "thor": "standard", "loki": "fast"}

# 역할 심볼 (AGENTS.md 이모지 일관) — REPL 전이 표시에 씀
_ROLE_ICON = {
    "THINKER": "🧠",
    "THINKER_REPLAN": "🧠",
    "WORKER": "🔨",
    "WORKER_RETRY": "🔨",
    "VERIFIER": "⚖️",
    "BASELINE_VERIFY": "🛡",
    "DONE": "✔",
    "DIRECT_DONE": "→",
    "ESCALATE_ODIN": "⚠",
}


def _transition_line(role: str, why: str) -> str:
    from .. import theme, ui

    icon = _ROLE_ICON.get(role, "◇")
    return f"\n  {ui.paint(theme.ansi(theme.PRIMARY), icon)} {ui.bold(role)} {ui.dim('· ' + why)}\n"


NATIVE_NOTE = """

## 네이티브 세션 규칙 (하니스 자동화)
이 세션은 Asgard 네이티브 루프다. 퀘스트 로그 기록·전이 함수·verifier-gate 는 **하니스가 자동
수행**한다 — quest-log 명령을 직접 실행하지 마라 (이중 기록). Verifier 판정은 verdict 툴로만
제출한다. 완료 선언은 여전히 금지 — 판정은 Verifier + 게이트 몫이다 (Canon 10)."""


def _role_body(fname: str) -> str:
    body = dict(ROLE_AGENTS)[fname]
    parts = body.split("---", 2)  # frontmatter 제거 — 네이티브에선 모델/툴 선언 무의미
    return parts[2] if len(parts) == 3 else body


# CUS-129 딜리버리 계층 — templates/roles/asgard-{freyja,thor,loki}.md 가 단일 소스 (CC 스캐폴드와 공유)
_DELIVERY = {g: _role_body(f"asgard-{g}.md") for g in ("freyja", "thor", "loki")}

VERDICT_TOOL = {
    "name": "verdict",
    "description": "Verifier 전용 — 구조화 판정 제출. 검증 명령을 직접 실행한 뒤에만 호출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["PASS", "FAIL", "ESCALATE"]},
            "criteria": {"type": "array", "items": {"type": "string"}},
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}, "exit_code": {"type": "integer"}},
                    "required": ["cmd", "exit_code"],
                },
            },
            "failure_sig": {"type": "string", "description": "FAIL 시 동종 실패 시그니처"},
            "structural": {
                "type": "boolean",
                "description": "FAIL 이 접근 자체의 결함(구조적)이면 true — Thinker 재계획 트리거 (경미한 수정 가능 결함은 false)",
            },
            "why": {"type": "string"},
        },
        "required": ["verdict", "criteria", "commands"],
    },
}


# ── 게이트 차단 사유 → (시그니처, 수리 역할) — CUS-174. 동일 시그니처 2회 = 수리 불가 → ESCALATE ──
_GATE_SIGS = (
    ("판정(PASS/ESCALATE) 레코드가 없", "no-verdict"),
    ("stale PASS", "stale-pass"),
    ("성공 기준(criteria)", "no-criteria"),
    ("검증 명령 증거", "no-evidence"),
    ("베이스라인 체크 red", "baseline-red"),
    ("full-verify 필요", "micro-pass"),
    ("퀘스트 로그가 없", "orphan-write"),
)


def _gate_sig(reason: str) -> str:
    return next((sig for needle, sig in _GATE_SIGS if needle in reason), "other")


def _gate_repair(sig: str) -> tuple[str, str]:
    """차단 사유별 수리 턴 — criteria 부재만 계획 보강, baseline red 는 코드 수리(Worker),
    나머지는 전부 신선 증거 재검증."""
    if sig == "no-criteria":
        return "THINKER_REPLAN", "게이트: criteria 부재 — 계획 보강 필요"
    if sig == "baseline-red":
        return "WORKER_RETRY", "게이트: 하네스 베이스라인 red — 실패한 체크를 수정 (CUS-187)"
    return "VERIFIER", f"게이트 차단({sig}) — 신선한 증거로 재검증"


# ── 결정론 pre-LLM 분류 (CUS-179, helios 디스패치 패턴) — 명백 케이스만, 모호하면 None → LLM 폴백 ──
_DESTRUCTIVE_PAT = re.compile(
    r"rm\s+-rf|git\s+push\s+--force|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f"
    r"|drop\s+(table|database)|truncate\s+table|mkfs|dd\s+if=|전부\s*(삭제|지워)|다\s*지워|싹\s*지워",
    re.IGNORECASE,
)
_WRITE_VERBS = (
    "만들", "생성해", "수정해", "고쳐", "추가해", "구현해", "작성해", "바꿔", "변경해", "리팩터", "빼줘",
    "삭제해", "지워", "적용해", "옮겨", "설치해", "fix ", "implement", "refactor", "rename ", "install ",
)  # fmt: skip
_READ_VERBS = (
    "설명해", "알려", "뭐야", "무엇", "어떻게 동작", "왜 ", "읽어줘", "분석해줘", "보여줘", "요약해", "조회",
    "explain", "what is", "what does", "how does", "why does", "describe", "summarize", "몇 개", "몇개", "?",
)  # fmt: skip


def classify_heuristic(request: str) -> dict | None:
    """순수 함수 1차 분류 — LLM 토큰 0. 확실할 때만 판정하고 나머지는 None (안전 우선).

    read-only 판정은 write 동사가 전혀 없을 때만 — 오판 시 write 가 게이트를 우회하므로
    (DIRECT), write 쪽 오판(불필요한 trinity 세금)보다 훨씬 보수적으로 잡는다."""
    low = " ".join(request.split()).lower()
    base = {
        "write_expected": False,
        "ambiguous": False,
        "destructive": False,
        "external_research": False,
        "shared": False,
        "criteria": [],
        "task_class": "standard",
    }
    if _DESTRUCTIVE_PAT.search(low):
        return {**base, "write_expected": True, "destructive": True, "task_class": "deep"}
    has_w = any(v in low for v in _WRITE_VERBS)
    has_r = any(v in low for v in _READ_VERBS)
    if has_r and not has_w:
        return base  # 명백 read-only — DIRECT 무세금
    if has_w and not has_r:
        # 명백 write — criteria 는 못 뽑는다 (기본 criterion 사용). task_class 는 LLM 없이 보수적 standard.
        return {**base, "write_expected": True}
    return None  # 모호 — LLM 폴백


def _pred_fields(d: dict) -> dict:
    return {k: d.get(k) for k in ("write_expected", "ambiguous", "destructive", "task_class")}


# ── Worker wave 병렬 (CUS-176, Fugu Conductor analog) — 배정 단위 {id, subtask, files, criteria, access} ──
_UNITS_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def _parse_units(plan: str) -> list[dict] | None:
    """Thinker 계획 말미의 ```json {"units":[...]}``` 블록 파싱 — 실패/단일 단위는 None (기존 단일 경로)."""
    m = None
    for m_ in _UNITS_RE.finditer(plan or ""):
        m = m_  # 마지막 블록이 배정 단위
    if not m:
        return None
    try:
        units = json.loads(m.group(1)).get("units")
        if not isinstance(units, list) or not (2 <= len(units) <= 6):
            return None
        out, seen = [], set()
        for i, u in enumerate(units):
            if not isinstance(u, dict):
                return None
            subtask = u.get("subtask")
            if not subtask:
                return None
            uid = u.get("id", i + 1)
            if uid in seen:
                return None
            seen.add(uid)
            files, crit, acc = u.get("files"), u.get("criteria"), u.get("access")
            out.append(
                {
                    "id": uid,
                    "subtask": str(subtask),
                    "files": [str(f) for f in files] if isinstance(files, list) else [],
                    "criteria": [str(c) for c in crit] if isinstance(crit, list) else [],
                    "access": list(acc) if isinstance(acc, list) else [],
                }
            )
        return out
    except Exception:
        return None


def _plan_waves(units: list[dict]) -> list[list[dict]]:
    """access 의존 위상 정렬 + 파일 겹침 직렬화 — 같은 wave 안은 병렬 안전 (hermes 경로 겹침 게이트)."""
    done: set = set()
    waves: list[list[dict]] = []
    remaining = list(units)
    while remaining:
        ready = [u for u in remaining if set(u.get("access") or []) <= done]
        if not ready:
            ready = [remaining[0]]  # 순환/미지 의존 — 순차 강등 (막히지 않는다)
        wave: list[dict] = []
        files_used: set[str] = set()
        for u in ready:
            fs = set(u.get("files") or [])
            if fs & files_used:
                continue  # 파일 겹침 — 다음 wave 로 직렬화
            wave.append(u)
            files_used |= fs
        if not wave:
            wave = [ready[0]]
        waves.append(wave)
        ids = {u["id"] for u in wave}
        done |= ids
        remaining = [u for u in remaining if u["id"] not in ids]
    return waves


# Thinker 에게 요구하는 배정 단위 출력 계약 (네이티브) — 독립 단위는 wave 병렬로 실행된다
_UNITS_NOTE = (
    "\n\n계획 마지막에 Worker 배정 단위를 JSON 블록으로 산출하라 (독립 단위는 병렬 실행):\n"
    '```json\n{"units":[{"id":1,"subtask":"...","files":["경로"],"criteria":["..."],"access":[]}]}\n```\n'
    "access = 이 단위가 결과를 참조해야 하는 선행 단위 id 목록 (독립이면 빈 배열 — 격리 실행됨). "
    "파일이 겹치는 단위는 같은 파일을 access 없이 나누지 마라. 단일 작업이면 units 1개."
)


def _log_classify(root: str, entry: dict) -> None:
    """classify 텔레메트리 (CUS-179) — predicted vs actual 감사 데이터. append-only, fail-open."""
    try:
        d = os.path.join(root, ".asgard")
        os.makedirs(d, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry}
        with open(os.path.join(d, "classify.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── API 오류 회복 (CUS-180, hermes recovery-hint 패턴 최소판) ──
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_FATAL_STATUS = {400, 401, 403, 404, 422}


def classify_api_error(e: Exception) -> str:
    """ "retryable" | "fatal" — 분류는 1회, 재시도 루프는 멍청하게 (hermes error_classifier 패턴)."""
    status = getattr(e, "status_code", None)
    if status in _RETRY_STATUS:
        return "retryable"
    if status in _FATAL_STATUS:
        return "fatal"
    name = e.__class__.__name__.lower()
    if "usagecap" in name:  # 구독 한도 도달 (claude_cli) — 재시도로 뚫지 않는다 (CUS-191)
        return "fatal"
    if any(k in name for k in ("timeout", "connection", "overloaded", "ratelimit", "internalserver")):
        return "retryable"
    return "retryable" if status is None else "fatal"  # 미상 = 일시 오류로 간주 (1회 재시도 가치)


DISPATCH_TOOL = {
    "name": "dispatch",
    "description": "딜리버리 전문가에게 하위 작업 위임 (freyja=UI/UX, thor=빌드/인프라, loki=adversarial). "
    "위임 전 누구에게·왜를 고민하고 why 에 근거를 남겨라 — 퀘스트 로그에 기록된다.",
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
    return _role_body(fname) + NATIVE_NOTE


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
    def __init__(
        self,
        rp: ResolvedProvider,
        root: str,
        on_text: Callable[[str], None],
        on_status: Callable[[str | None], None] | None = None,
    ):
        self.rp, self.root, self.on_text = rp, root, on_text
        self.on_status = on_status or (lambda s: None)
        self._clients: dict[tuple, object] = {}  # (provider, base_url, key_source) → SDK 클라이언트
        self.client = self._client_for(rp)
        # 역할별 provider 배치 ([trinity.<role>]) — 미충족은 기본 provider 로 fail-open + 경고 1회
        from ..providers import TRINITY_EXTRA_ROLES, TRINITY_ROLES

        self.role_rp: dict[str, ResolvedProvider] = {}
        for role, rrp in resolve_trinity(root, rp, TRINITY_ROLES + TRINITY_EXTRA_ROLES).items():
            if rrp is not rp and rrp.missing:
                on_text(f"⚠ [trinity.{role}] 미충족({'; '.join(rrp.missing)}) — 기본 provider 사용\n")
                rrp = rp
            self.role_rp[role] = rrp
        # trinity-policy.json — roles tier/effort·budget_priors·delivery 티어 소비 (CUS-177/181)
        from ..hooks.quest_log import active_quest, load_policy

        self.policy = load_policy(root)
        self.identity = _identity(root)
        self.total_tokens = 0  # 세션 누적 (status line 사용량)
        self._sleep = time.sleep  # 재시도 백오프 — 테스트 주입점 (CUS-180)
        dangling = active_quest(root)
        if dangling:  # 이전 세션 중단으로 남은 ACTIVE 퀘스트 — 조용히 덮지 않는다 (CUS-180)
            on_text(f"⚠ 미완 퀘스트 발견({dangling}) — 이전 세션 중단 흔적. 이어서 검증하거나 quest-log close 필요.\n")

    def _client_for(self, rp: ResolvedProvider):
        key = (rp.profile.name, rp.base_url, rp.key_source)
        if key not in self._clients:
            self._clients[key] = make_client(rp)
        return self._clients[key]

    def _add_tokens(self, n: int) -> None:
        self.total_tokens += n

    def _session(
        self,
        system: str,
        extra_tools=None,
        handlers=None,
        quiet=False,
        role: str | None = None,
        model: str | None = None,
    ) -> AgentSession:
        rp = self.role_rp.get(role or "", self.rp)
        if model and model != rp.model:  # 상황별 모델 스왑 (CUS-177) — provider 는 유지, 모델만
            from dataclasses import replace

            rp = replace(rp, model=model)
        return AgentSession(
            self._client_for(rp),
            rp,
            self.root,
            system,
            extra_tools=extra_tools,
            tool_handlers=handlers,
            on_text=(lambda s: None) if quiet else self.on_text,
            on_tokens=self._add_tokens,
            on_status=self.on_status,
        )

    def _model_for(self, role_key: str, bump: bool = False) -> str | None:
        """정책 tier → 상황별 모델 (CUS-177). None = 스왑 없음 (해당 세션 rp.model 그대로).

        존중 규칙: ① 역할에 명시 placement 가 있으면 그 모델 ② 기본 provider 가 anthropic 이
        아니면 티어 매핑 불가 ③ 사용자가 기본 모델을 바꿨으면(config model=) 그 선택 유지.
        bump = 상황 승급 (full-verify·재계획 2회+) — 티어 사다리 한 칸 위 (high→max=fable)."""
        rp = self.role_rp.get(role_key, self.rp)
        if rp is not self.rp:
            return None  # 명시 placement 존중
        # claude_cli 도 티어 매핑 가능 — CLI 가 full 모델 ID 를 그대로 해석한다 (CUS-190)
        if rp.profile.api_mode not in ("anthropic", "claude_cli") or rp.model != rp.profile.default_model:
            return None
        tier = str((self.policy.get("roles", {}).get(role_key) or {}).get("tier", "standard"))
        if bump:
            tier = _TIER_UP.get(tier, tier)
        return _TIER_MODELS.get(tier)

    def _delivery_model(self, agent: str) -> str | None:
        """딜리버리 전문가 모델 — 정책 "delivery" 티어 (기본: freyja/thor=sonnet, loki=haiku)."""
        rp = self.rp
        if rp.profile.api_mode not in ("anthropic", "claude_cli") or rp.model != rp.profile.default_model:
            return None
        tier = str((self.policy.get("delivery") or {}).get(agent, _DELIVERY_TIERS.get(agent, "standard")))
        return _TIER_MODELS.get(tier)

    def _classify(self, request: str) -> dict:
        # 1차 결정론 휴리스틱 (LLM 토큰 0, CUS-179) — 명백 케이스만. 모호하면 LLM 폴백.
        d = classify_heuristic(request)
        if d is not None:
            _log_classify(self.root, {"event": "classify", "source": "heuristic", **_pred_fields(d)})
            return d
        # structured-output 강제 대신 "JSON 만 출력" + 관대한 파싱 — 두 트랜스포트(및 nemotron 류
        # JSON-mode 불확실 모델) 공통. 파싱 실패는 안전 기본값(write 로 간주 → 게이트가 잡는다).
        sysmsg = (
            "과업 분류기. 요청을 읽고 아래 JSON 만 출력한다 (설명 금지, JSON 앞뒤 텍스트 금지). "
            "write_expected = 파일을 생성·수정해야 하는 과업이면 true. "
            "**질문·계산·설명·조회처럼 답만 하면 되는 것은 false** (예: '1+1?', '이 함수 설명해'). "
            "criteria 는 write 과업일 때만, 명령으로 확인 가능한 형태로. "
            "task_class = trivial(파일 1개 소형)|standard|deep(멀티파일·리팩터·리스크). "
            '{"write_expected":bool,"ambiguous":bool,"destructive":bool,'
            '"external_research":bool,"shared":bool,"criteria":[str],"task_class":str}'
        )
        try:
            raw = self._complete_text(sysmsg, request, max_tokens=2000)
            s = raw[raw.index("{") : raw.rindex("}") + 1]
            d = json.loads(s)
            for k in ("write_expected", "ambiguous", "destructive", "external_research", "shared"):
                d[k] = bool(d.get(k))
            d["criteria"] = [str(c) for c in (d.get("criteria") or [])]
            if d.get("task_class") not in ("trivial", "standard", "deep"):
                d["task_class"] = "standard"
            _log_classify(self.root, {"event": "classify", "source": "llm", **_pred_fields(d)})
            return d
        except Exception:
            d = {
                "write_expected": True,
                "ambiguous": True,
                "destructive": False,
                "external_research": False,
                "shared": False,
                "criteria": [],
                "task_class": "deep",  # 파싱 실패 = 미상 — 최대 예산으로 안전하게
            }
            _log_classify(self.root, {"event": "classify", "source": "fallback", **_pred_fields(d)})
            return d

    def _complete_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """비스트리밍 단발 completion — 트랜스포트 무관 (classify 등 내부 판단용).
        [trinity.classify] placement 가 있으면 그 provider/모델 사용 (저비용 분류, CUS-179)."""
        rp = self.role_rp.get("classify", self.rp)
        client = self._client_for(rp)
        if rp.profile.api_mode == "claude_cli":
            from .claude_native import complete_text

            return complete_text(system, user, model=rp.model, root=self.root)
        if rp.profile.api_mode == "anthropic":
            resp = client.messages.create(
                model=rp.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
            )
            return "".join(b.text for b in resp.content if b.type == "text")
        resp = client.chat.completions.create(
            model=rp.model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""

    def _run_turn(
        self, make: Callable[[], AgentSession], prompt: str, fallback: Callable[[], AgentSession] | None = None
    ):
        """역할 턴 실행 + 오류 회복 (CUS-180) — retryable 은 jittered backoff ≤2회 재시도,
        소진 시 placement 폴백 1회 (기본 provider), fatal 은 즉시 표면화."""
        delay = 2.0
        for attempt in range(3):
            try:
                return make().run(prompt)
            except Exception as e:
                if classify_api_error(e) != "retryable" or attempt == 2:
                    if fallback is not None:
                        self.on_text(f"⚠ provider 오류({e.__class__.__name__}) — 기본 provider 폴백 1회\n")
                        return fallback().run(prompt)
                    raise
                self.on_text(f"⚠ provider 일시 오류({e.__class__.__name__}) — {delay:.0f}s 후 재시도\n")
                self._sleep(delay + random.uniform(0, delay / 2))
                delay = min(delay * 2, 30.0)
        raise RuntimeError("unreachable")

    # ── 딜리버리 디스패치 (CUS-142, depth 1) ─────────────────────────────
    def _dispatch_handler(self, sid: str, worker_result_writes: list[str]):
        def handler(inp: dict) -> str:
            agent, task, why = inp["agent"], inp["task"], inp.get("why", "")
            from .. import theme, ui

            self.on_text(
                f"\n  {ui.paint(theme.ansi(theme.PRIMARY), '⤷')} {ui.bold(agent)} {ui.dim('위임 · ' + why[:80])}\n"
            )
            ql(
                self.root,
                "append",
                session=sid,
                stdin=json.dumps(
                    {
                        "role": "worker",
                        "event": "delegate",
                        "commands": [{"cmd": f"dispatch:{agent} — {why[:120]}", "exit_code": 0}],
                    }
                ),
            )
            # dispatch 툴 미제공 = 재위임 불가. 모델은 딜리버리 티어 (freyja/thor=standard, loki=fast)
            child = self._session(_DELIVERY[agent] + "\n\n" + self.identity, model=self._delivery_model(agent))
            r = child.run(task)
            worker_result_writes.extend(r.writes)
            return f"[{agent}] {r.text[-2000:]}"

        return handler

    def _run_worker_waves(self, sid: str, request: str, units: list[dict], budget_note: str) -> None:
        """배정 단위 wave 병렬 실행 (CUS-176) — access list 격리 + 파일 겹침 직렬화.

        격리 원칙 (Fugu §3.2.2 orchestration collapse 방지): 각 단위는 자기 subtask +
        access 에 명시된 선행 단위 결과만 본다 — 같은 wave 의 다른 단위 궤적은 안 보인다.
        work 이벤트는 단위별 기록 (unit 필드), 병렬 출력은 quiet — wave 요약만 표시."""
        from concurrent.futures import ThreadPoolExecutor

        results: dict = {}  # unit id → 결과 텍스트 (access 컨텍스트 소스)
        all_writes: list[str] = []
        wrp = self.role_rp.get("worker", self.rp)
        used_model = f"{wrp.profile.name}:{self._model_for('worker') or wrp.model}"

        def run_unit(u: dict):
            writes: list[str] = []

            def mk():
                return self._session(
                    _role_prompt("asgard-worker.md"),
                    extra_tools=[DISPATCH_TOOL],
                    handlers={"dispatch": self._dispatch_handler(sid, writes)},
                    role="worker",
                    model=self._model_for("worker"),
                    quiet=True,
                )

            access_ctx = "".join(
                f"\n[선행 단위 {a} 결과]\n{results[a][:1500]}\n" for a in (u.get("access") or []) if a in results
            )
            prompt = (
                f"과업: {request}\n\n배정 단위 {u['id']}: {u['subtask']}\n"
                f"대상 파일: {', '.join(u['files']) or '(미지정)'}\n"
                f"criteria: {u['criteria']}\n{access_ctx}\n"
                f"배정 단위 범위만 구현하라 (Canon 7) — 다른 단위의 파일을 건드리지 마라.{budget_note}"
            )
            return u, self._run_turn(mk, prompt), writes

        for wave in _plan_waves(units):
            ids = ", ".join(str(u["id"]) for u in wave)
            self.on_text(f"\n  ⛓ wave [{ids}] — {'병렬 %d단위' % len(wave) if len(wave) > 1 else '단독'}\n")
            if len(wave) == 1:
                outs = [run_unit(wave[0])]
            else:
                with ThreadPoolExecutor(max_workers=min(3, len(wave))) as ex:
                    outs = list(ex.map(run_unit, wave))
            for u, r, writes in outs:
                unit_writes = writes + [w for w in r.writes if w not in writes]
                all_writes.extend(w for w in unit_writes if w not in all_writes)
                results[u["id"]] = r.text[-2000:]
                self.on_text(f"  ⬢ 단위 {u['id']} 완료 · 파일 {len(unit_writes)}개\n")
                ql(
                    self.root,
                    "append",
                    session=sid,
                    stdin=json.dumps(
                        {
                            "role": "worker",
                            "event": "work",
                            "unit": u["id"],
                            "changed_files": unit_writes[:50],
                            "commands": r.commands[-20:],
                            "model": used_model,
                        }
                    ),
                )
        _record_writes(self.root, sid, all_writes)

    def _escalate(self, sid: str) -> None:
        """ESCALATE 퀘스트 로그 기록 — verify 이벤트는 verdict 필수 (없으면 quest_log 가 거부, 조용히 유실)."""
        ql(
            self.root,
            "append",
            "--verdict",
            "ESCALATE",
            session=sid,
            stdin=json.dumps({"role": "verifier", "event": "verify"}),
        )

    # ── Trinity 순환 ─────────────────────────────────────────────────────
    def _trinity(self, request: str, cls: dict, pre_work=None, standard: bool = False) -> str:
        import uuid

        qid = f"native-{int(time.time())}-{uuid.uuid4().hex[:6]}"  # 초 단위 충돌 방지 (CUS-184)
        sid = qid
        args = ["open", qid] + [
            x for c in (cls["criteria"] or ["요청 충족을 검증 명령으로 입증"]) for x in ("--criteria", c)
        ]
        ql(self.root, *args, session=sid)
        if pre_work is not None:  # DIRECT 오분류 소급 편입 (CUS-178) — 이미 실행된 write 를 work 로 기록
            _record_writes(self.root, sid, list(pre_work.writes))
            ql(
                self.root,
                "append",
                session=sid,
                stdin=json.dumps(
                    {
                        "role": "worker",
                        "event": "work",
                        "changed_files": list(pre_work.writes)[:50],
                        "commands": pre_work.commands[-20:],
                    }
                ),
            )
        # 턴 예산 = budget_priors[task_class] (CUS-181) — T→W→V 최소 순환 아래로는 안 내려간다
        priors = self.policy.get("budget_priors") or {}
        budget = int((priors.get(cls.get("task_class") or "deep") or {}).get("turns", MAX_TRINITY_TURNS))
        budget = max(3, min(budget, MAX_TRINITY_TURNS))
        flag_args = [
            f
            for f, on in (
                ("--ambiguous", cls["ambiguous"]),
                ("--external-research", cls["external_research"]),
                ("--shared", cls["shared"]),
                ("--write-expected", True),
            )
            if on
        ]  # 게이트-우선은 전이 함수 기본값 (CUS-189) — 별도 플래그 없음, 물리 가드가 판정
        # 게이트-우선은 Thinker 를 생략한다 — Worker 가 계획 없이 뛰지 않게 criteria 를 계획 자리에.
        plan_ctx = ("성공 기준: " + "; ".join(map(str, cls["criteria"]))) if standard else ""
        explored: list[str] = []  # Thinker 관찰 명령 — Worker 재탐색 세금 절감 (CUS-182 최소판, 힌트 전용)
        structural = False  # 직전 FAIL 이 구조적 — 다음 next 에 --structural 전달 (CUS-171)
        last_fail: dict | None = None  # 직전 FAIL 상세 — WORKER_RETRY 에 주입 (CUS-172)
        fail_history: list[str] = []  # 턴별 실패 이력 — THINKER_REPLAN 에 주입 (CUS-172)
        gate_sigs: dict[str, int] = {}  # 게이트 차단 사유별 카운트 (CUS-174)
        gate_blocks = 0
        replans = 0  # 재계획 횟수 — 2회+ 는 clean-slate: thinker_alt placement 또는 티어 승급 (CUS-177)
        pending: tuple[str, str] | None = None  # 게이트 수리 강제 턴 — next 우회

        for t in range(1, budget + 3):  # +2 = grace 판정 턴 + 종료(DONE/게이트) 여지 (CUS-181)
            if pending:
                role, why = pending
                pending = None
                level = "full"  # 수리 재검증은 상위 레벨로 — micro 부족이 차단 사유일 수 있다
            else:
                nx_args = flag_args + (["--structural"] if structural else [])
                nxt = json.loads(ql(self.root, "next", *nx_args, session=sid).stdout or "{}")
                role, why = nxt.get("next_role", ""), nxt.get("why", "")
                level = nxt.get("verify_level", "micro")
            if t > budget and role not in ("VERIFIER", "BASELINE_VERIFY", "DONE", "ESCALATE_ODIN", "DIRECT_DONE"):
                break  # 예산 소진 — grace 는 판정·종료 전용, 새 작업 턴 금지 (CUS-181)
            # 잔량 자기규제 (helios budget-guard 패턴) — 80% 도달 시 범위 축소 지시
            budget_note = f"\n(턴 {t}/{budget}" + (
                " — 예산 80% 도달: 범위를 좁히고 핵심 criteria 우선, 가정은 `가정:` 으로 기록)"
                if t >= max(2, int(budget * 0.8))
                else ")"
            )
            # 상황별 (역할, 모델) 배정 — Trinity per-turn assignment 의 하니스 판 (CUS-177)
            if role == "THINKER_REPLAN":
                replans += 1
            role_key = _ROLE_KEY.get(role, "")
            alt = (
                role == "THINKER_REPLAN" and replans >= 2 and self.role_rp.get("thinker_alt", self.rp) is not self.rp
            )  # clean-slate: 같은 모델의 재계획이 반복 실패 — 다른 시선 투입 (Fugu §4.4)
            sess_role = "thinker_alt" if alt else role_key
            bump = (role == "VERIFIER" and level == "full") or (role_key == "thinker" and replans >= 2 and not alt)
            model = self._model_for(sess_role, bump=bump) if role_key else None
            rrp = self.role_rp.get(sess_role, self.rp)
            used_model = f"{rrp.profile.name}:{model or rrp.model}"  # 퀘스트 로그 기록용 (CUS-177→127 데이터)
            if rrp is not self.rp:  # 역할별 배치가 있으면 어떤 모델이 뛰는지 표시
                why += f" · {rrp.profile.name}:{rrp.model}"
            elif model and model != self.rp.model:
                why += f" · {model}"
            self.on_text(_transition_line(role, why))

            if role == "BASELINE_VERIFY":
                # 게이트-우선 판정 턴 (CUS-188) — LLM 토큰 0, 하네스가 프로젝트 체크로 판정 기록
                p = ql(self.root, "verify-baseline", session=sid)
                try:
                    bj = json.loads(p.stdout or "{}")
                except Exception:
                    bj = {}
                if p.returncode != 0 or not bj.get("verdict"):
                    pending = ("VERIFIER", "베이스라인 판정 불가 — LLM Verifier 폴백")
                    continue
                self.on_text(f"  ⚖ 베이스라인 {bj.get('baseline')} → {bj['verdict']}\n")
                if bj["verdict"] == "FAIL":
                    failing = ", ".join(map(str, bj.get("failing") or [])) or "(퀘스트 로그 baseline.results 참조)"
                    last_fail = {"sig": "baseline-red", "why": f"하네스 베이스라인 체크 실패: {failing}"}
                    fail_history.append(f"baseline-red: {failing[:200]}")
                continue
            if role == "DONE":
                blocked, reason = gate(self.root, sid)
                if blocked:  # 전이/게이트 판정 불일치 — 사유별 수리 턴 강제 (무수리 재시도 금지, CUS-174)
                    gate_blocks += 1
                    sig = _gate_sig(reason)
                    gate_sigs[sig] = gate_sigs.get(sig, 0) + 1
                    self.on_text(f"⛔ gate({sig}): {reason[:200]}\n")
                    if gate_sigs[sig] >= 2:  # 동일 사유 재차단 = 수리 불가 — fail-open 위장 대신 정직 보고
                        self._escalate(sid)
                        return (
                            f"⚠ Odin 결정 필요 — 게이트 동일 사유({sig}) {gate_sigs[sig]}회 차단, 수리 실패. "
                            f"퀘스트 로그: .asgard/quest/{qid}.jsonl"
                        )
                    pending = _gate_repair(sig)
                    if sig == "baseline-red":  # 실패 체크 상세를 수리 턴에 주입 (CUS-172 경로 재사용)
                        last_fail = {"sig": sig, "why": reason[:500]}
                    continue
                ql(self.root, "close", session=sid)
                return self._final_report(qid, sid, gate_blocks)
            if role == "ESCALATE_ODIN":
                self._escalate(sid)
                return f"⚠ Odin 결정 필요 — {why}"
            if role == "DIRECT_DONE":
                return self._direct(request)

            if role in ("THINKER", "THINKER_REPLAN"):
                if role == "THINKER_REPLAN":
                    hist = "\n".join(f"- {h}" for h in fail_history[-5:]) or "- (기록 없음)"
                    prompt = (
                        f"과업: {request}\n\n(재계획: {why})\n\n실패 이력:\n{hist}\n\n"
                        "같은 접근의 문구만 바꾼 재시도는 같은 실패다 — 접근 자체를 재설계하라 (Canon 9)."
                    )
                else:
                    prompt = f"과업: {request}"
                mk = lambda sr=sess_role, m=model: self._session(_role_prompt("asgard-thinker.md"), role=sr, model=m)  # noqa: E731
                fb = (lambda: self._session(_role_prompt("asgard-thinker.md"))) if rrp is not self.rp else None
                r = self._run_turn(mk, prompt + _UNITS_NOTE + budget_note, fb)
                plan_ctx = r.text
                # 탐색 캐시 힌트 (CUS-182) — 게이트 증거 아님, 컨텍스트 힌트만 ("게이트는 메모리 불신")
                explored = list(dict.fromkeys(str(c.get("cmd", ""))[:80] for c in r.commands if isinstance(c, dict)))[
                    :15
                ]
                structural = False  # 재계획으로 소비됨
                ql(
                    self.root,
                    "append",
                    session=sid,
                    stdin=json.dumps(
                        {"role": "thinker", "event": "plan", "criteria": cls["criteria"], "model": used_model}
                    ),
                )
            elif role in ("WORKER", "WORKER_RETRY"):
                units = _parse_units(plan_ctx) if role == "WORKER" else None
                if units:  # wave 병렬 디스패치 (CUS-176) — 재시도는 단일 경로 (실패 컨텍스트 집중)
                    self._run_worker_waves(sid, request, units, budget_note)
                    continue
                writes: list[str] = []

                def mk_worker(m=model, w=writes, s_id=sid, rl="worker"):
                    return self._session(
                        _role_prompt("asgard-worker.md"),
                        extra_tools=[DISPATCH_TOOL],
                        handlers={"dispatch": self._dispatch_handler(s_id, w)},
                        role=rl,
                        model=m,
                    )

                retry_note = ""
                if role == "WORKER_RETRY" and last_fail:  # 실패 컨텍스트 전달 — 백지 재작업 금지 (CUS-172)
                    retry_note = (
                        f"\nFAILED: {last_fail.get('sig') or 'unknown'}\n"
                        f"사유: {(last_fail.get('why') or '')[:500]}\n"
                        f"criteria: {'; '.join(map(str, last_fail.get('criteria') or []))[:300]}\n"
                        f"검증 명령 관측: {json.dumps(last_fail.get('commands') or [], ensure_ascii=False)[:400]}\n"
                        "위 실패 지점을 직접 수정하라 — 처음부터 다시 만들지 마라."
                    )
                elif role == "WORKER_RETRY":
                    retry_note = "(재시도 — 직전 FAIL 사유를 수정하라)"
                plan_part = plan_ctx[:4000] + (
                    f"\n…(계획 절단 — 원문 {len(plan_ctx)}자)" if len(plan_ctx) > 4000 else ""
                )  # silent truncation 금지 (CUS-183)
                explore_note = (
                    ("\nThinker 관찰 이력 (동일 명령 재탐색 불필요): " + "; ".join(explored)[:600]) if explored else ""
                )
                fb = (lambda mw=mk_worker: mw(m=None, rl=None)) if rrp is not self.rp else None
                r = self._run_turn(
                    mk_worker, f"과업: {request}\n\n계획:\n{plan_part}{explore_note}\n{retry_note}{budget_note}", fb
                )
                writes.extend(r.writes)
                _record_writes(self.root, sid, writes)
                ql(
                    self.root,
                    "append",
                    session=sid,
                    stdin=json.dumps(
                        {
                            "role": "worker",
                            "event": "work",
                            "changed_files": writes[:50],
                            "commands": r.commands[-20:],
                            "model": used_model,
                        }
                    ),
                )
            elif role == "VERIFIER":
                # 퀘스트 로그 관측 diff 컨텍스트 — 검증자가 "diff 없음"으로 헛FAIL 하지 않게 물리 관측을
                # 손에 쥐여준다 (판정은 여전히 직접 명령 실행으로).
                st = {}
                try:
                    st = json.loads(ql(self.root, "state", session=sid).stdout or "{}")
                except Exception:
                    pass
                changed = ", ".join((st.get("changed_files") or [])[:20]) or "(없음)"

                def mk_verifier(m=model, rl="verifier"):
                    return self._session(
                        _role_prompt("asgard-verifier.md"),
                        extra_tools=[VERDICT_TOOL],
                        handlers={"verdict": lambda i: "판정 접수"},
                        role=rl,
                        model=m,
                    )

                fb = (lambda mv=mk_verifier: mv(m=None, rl=None)) if rrp is not self.rp else None
                r = self._run_turn(
                    mk_verifier,
                    f"검증하라. 요청: {request}\ncriteria: {cls['criteria']}\n"
                    f"required level: {level}\n"
                    f"하니스 관측 변경 파일: {changed} (diff_lines={st.get('diff_lines', '?')}) — "
                    f"`git diff` / 파일 열람 / 실행으로 직접 확인하라.\n"
                    f"Worker 해설은 입력이 아니다 — diff 와 명령 실행으로만 판정. 판정은 반드시 verdict 툴로 제출.\n"
                    f"FAIL 이 접근 자체의 결함이면 structural=true 로 제출하라 (재계획 트리거).",
                    fb,
                )
                # 마지막 verdict 호출이 최종 판정 (다중 호출 시 정정 인정, CUS-173)
                v = next((c["input"] for c in reversed(r.tool_calls) if c["name"] == "verdict"), None)
                observed = [c for c in r.commands if isinstance(c, dict)]  # 하니스 관측 — 위조 불가
                if not v:
                    v = {
                        "verdict": "FAIL",
                        "criteria": cls["criteria"],
                        "failure_sig": "no-verdict-submitted",
                        "why": "verdict 툴 미제출",
                    }
                elif v.get("verdict") == "PASS" and not any(c.get("exit_code") == 0 for c in observed):
                    # 증거 없는 PASS 무효 — verifier 가 명령을 실제 실행하지 않았다 (Goodhart, CUS-173)
                    v = {
                        "verdict": "FAIL",
                        "criteria": v.get("criteria") or cls["criteria"],
                        "failure_sig": "no-verification-evidence",
                        "why": "PASS 주장에 하니스 관측 성공 명령이 없음 — 검증 명령을 직접 실행해야 한다",
                    }
                # 증거는 하니스 관측 명령만 기록 — 모델 자가보고 commands 는 버린다 (CUS-173)
                ev = {
                    "role": "verifier",
                    "event": "verify",
                    "criteria": v.get("criteria") or cls["criteria"],
                    "commands": observed[-20:],
                    "model": used_model,
                }
                if v.get("failure_sig"):
                    ev["failure_sig"] = v["failure_sig"]
                structural = bool(v.get("structural")) and v.get("verdict") == "FAIL"
                if v.get("verdict") == "FAIL":
                    last_fail = {
                        "sig": v.get("failure_sig"),
                        "why": v.get("why", ""),
                        "criteria": v.get("criteria") or [],
                        "commands": observed[-5:],
                    }
                    fail_history.append(
                        f"{v.get('failure_sig') or 'unknown'}: {(v.get('why') or '')[:200]}"
                        + (" [구조적]" if structural else "")
                    )
                else:
                    last_fail = None
                ql(
                    self.root,
                    "append",
                    "--verdict",
                    str(v["verdict"]),
                    "--level",
                    level,
                    session=sid,
                    stdin=json.dumps(ev),
                )
            else:
                return f"⚠ 미지의 전이 상태 '{role}' — Odin 보고 (퀘스트 로그: .asgard/quest/{qid}.jsonl)"

        return (
            f"⚠ 턴 예산({budget}) 소진 — Odin 보고 (grace 판정까지 완료 실패). 퀘스트 로그: .asgard/quest/{qid}.jsonl"
        )

    def _final_report(self, qid: str, sid: str, gate_blocks: int) -> str:
        """퀘스트 로그만 소스로 하는 구조화 최종 보고 (CUS-183) — 가정 표면화 + 게이트 이력."""
        events = []
        try:
            for line in open(os.path.join(self.root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8"):
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            pass
        roles = [e.get("role", "?") for e in events if e.get("event") in ("plan", "work", "verify")]
        assumptions = sorted(
            {c for e in events for c in (e.get("criteria") or []) if str(c).strip().startswith("가정:")}
        )
        last_pass = next((e for e in reversed(events) if e.get("event") == "verify" and e.get("verdict") == "PASS"), {})
        cmds = [c for c in (last_pass.get("commands") or []) if isinstance(c, dict)]
        lines = ["과업 완수 — Verifier PASS + diff-hash 일치, 퀘스트 로그 닫힘."]
        lines.append(f"턴 {len(events)} · 역할 {'→'.join(roles[-8:]) or '-'}")
        if cmds:
            lines.append(
                "증거: " + "; ".join(f"{c.get('cmd', '?')[:60]} (exit {c.get('exit_code')})" for c in cmds[:4])
            )
        if assumptions:
            lines.append("가정 (Canon 8 — Odin 검토 필요):")
            lines.extend(f"  · {a}" for a in assumptions[:8])
        if gate_blocks:
            lines.append(f"⚠ 게이트 차단 {gate_blocks}회 후 통과 — 수리 이력은 퀘스트 로그 참조")
        return "\n".join(lines)

    def _worktree_dirty(self) -> str:
        """git status --porcelain 스냅샷 — DIRECT 전후 비교로 bash 우회 write 까지 감지 (CUS-178)."""
        import subprocess

        try:
            p = subprocess.run(
                ["git", "-C", self.root, "status", "--porcelain"], capture_output=True, text=True, timeout=30
            )
            return p.stdout if p.returncode == 0 else ""
        except Exception:
            return ""

    def _direct(self, request: str) -> str:
        """DIRECT 응답 — 본문은 on_text 로 이미 스트리밍됨. 빈 문자열 반환해 이중 출력 방지.
        예외: refusal 안내는 스트림에 안 실린 합성 텍스트 — 그것만 반환.

        가드 (CUS-178): classify 오판으로 DIRECT 세션이 파일을 쓰면 — editor writes 또는
        워킹트리 fingerprint 변화 — 소급 퀘스트를 열어 Verifier 판정 + 게이트를 강제한다.
        mode B 의 orphan-write 봉인의 네이티브 등가물 (native 엔 Stop 훅이 없다)."""
        before = self._worktree_dirty()
        r = self._session(self.identity).run(request)
        if r.writes or self._worktree_dirty() != before:
            _log_classify(self.root, {"event": "misroute", "route": "direct", "actual_write": True})
            self.on_text("\n⚠ DIRECT 분류였지만 write 감지 — 소급 검증 경로 진입 (Canon 10)\n")
            cls = {
                "write_expected": True,
                "ambiguous": False,
                "destructive": False,
                "external_research": False,
                "shared": False,
                "criteria": [],
                "task_class": "standard",
            }
            return self._trinity(request, cls, pre_work=r)
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
            _log_classify(self.root, {"event": "route", "route": "refused-destructive"})
            return "⚠ 파괴 작업 감지 — Odin 명시 동의 필요 (Canon 3). 대상과 함께 재요청하세요."
        if not cls["write_expected"]:
            _log_classify(self.root, {"event": "route", "route": "direct"})
            return self._direct(request)  # DIRECT — 무세금
        # 게이트-우선(STANDARD) 라우팅 (CUS-188) — 비민감 소형 write 는 Worker 직행 + 하네스 베이스라인.
        # deep/ambiguous/shared 는 상시 Trinity. task_class 미상(None)은 deep 취급 (안전 기본값).
        standard = cls.get("task_class") in ("trivial", "standard") and not (cls["ambiguous"] or cls["shared"])
        _log_classify(self.root, {"event": "route", "route": "standard" if standard else "trinity"})
        try:
            return self._trinity(request, cls, standard=standard)
        except Exception as e:  # dangling 방지 (CUS-180) — 퀘스트는 ACTIVE 로 남고 정직하게 보고
            return (
                f"⚠ 세션 오류로 Trinity 중단 ({e.__class__.__name__}: {str(e)[:200]}) — "
                "퀘스트가 ACTIVE 로 남아 있음. 재요청 시 이어서 검증하거나 quest-log close 하세요."
            )
