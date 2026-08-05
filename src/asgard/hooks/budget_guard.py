#!/usr/bin/env python3
# Asgard budget-guard — 세션 소비의 상한. 낭비를 사후에 감사하지 않고 **쓰기 전에** 막는다.
#
# 왜 필요한가: v0.6.21에서 Trinity Verifier 과잉으로 3.3M 토큰을 태웠고, 그걸 찾은 것은
# 사후 감사였다. 같은 일이 다시 나면 또 사후에 찾는다 — 구조적으로 막는 층이 없었다.
#
# ── 선행 연구와 그 실패 (ref/asgard-helios/hooks/asgard-budget-guard.mjs) ──────────────
# 헬리오스에 같은 의도의 훅이 있었다. 3지점 배선(PreToolUse/SubagentStart/SubagentStop)에
# 6시간 윈도우 누적, hardCeiling 300k, opus 호출 8회 상한까지 설계는 옳았다. 그런데 계측원이
# SubagentStop 페이로드의 `usage.total_tokens` 였고, 그 필드는 오지 않는다. 운영 DB 실측:
#
#     post 이벤트 89건 — total_tokens가 non-null 인 건 0건, 87건은 agent_type조차 빈 문자열
#     pre 이벤트에 찍힌 session_tokens 값: 0
#
# 즉 토큰 기반 hard ceiling은 **한 번도 발화한 적 없는 죽은 코드**였다. 살아 있던 것은 호출
# 횟수 카운터뿐이다. 그래서 이 훅의 첫 번째 계약은 계측원을 바꾸는 것이다.
#
# ── 계측원: 트랜스크립트 (26-07-27 실측 확정) ────────────────────────────────────────
# Claude Code는 세션 JSONL에 메시지별 usage를 그대로 적는다. 두 레인이 모두 잡힌다:
#
#   메인 레인   assistant 행의 message.usage
#                 → input_tokens · output_tokens · cache_creation_input_tokens · cache_read_input_tokens
#   에이전트   Task 도구의 toolUseResult
#                 → agentType · resolvedModel · totalTokens · usage (같은 4필드)
#
# 헬리오스가 못 찾던 agent_type이 여기 있다. 훅 페이로드가 아니라 디스크가 정본이다.
#
# ── 지점은 둘, 거부는 하나 ──────────────────────────────────────────────────────────
# 트랜스크립트 381세션 실측에서 상위 소비 세션(29.3M·28.8M·24.5M cost unit)은 **서브에이전트
# 호출이 0** 이었다. 진짜 지출은 메인 레인에서 난다. Task 스폰만 재면 최대 지출을 통째로
# 놓친다. 그래서 UserPromptSubmit(턴 시작 전)과 PreToolUse(Agent)(스폰 전) 둘 다에서 잰다.
# 거부는 그중 스폰 지점에만 있다.
#
# UserPromptSubmit 의 거부(exit 2)는 방금 입력한 프롬프트를 지운다. 지워진 프롬프트는 이미 나간
# 지출을 되돌리지 못하고, 트랜스크립트는 자라기만 하므로 다음 프롬프트도 같은 자리에서 지워진다.
# 상한 문구는 "마무리하고 무엇이 남았는지 보고하라"인데, 그 문구를 읽어야 할 모델의 턴이 시작되지
# 않는다 — 설정을 고치기 전에는 세션 안에서 빠져나올 통로가 없다. 그래서 메인 레인은 상한에서도
# 지시를 컨텍스트에 넣고 턴을 연다. PreToolUse 의 거부는 도구 호출 하나가 거절되고 모델이 사유를
# 읽는 자리라 다르다: 세션은 살아 있고 남은 일은 메인 레인에서 이어진다.
#
# ── 왜 원시 토큰이 아니라 가중 비용 단위인가 ──────────────────────────────────────────
# 같은 실측에서 한 세션의 cache_read가 14.4M, output이 106k 였다. 원시 합으로 상한을 걸면
# 캐시 읽기가 지표를 통째로 지배해 "비싼 세션"과 "긴 세션"을 구별하지 못한다. 캐시 읽기는 입력
# 대비 1/10 가격이라 그 구별이 바로 돈이다. 가중치는 표준 비율(입력 1 · 출력 5 · 캐시쓰기 1.25 ·
# 캐시읽기 0.1)을 기본값으로 두되 설정에서 바꿀 수 있다 — 전부 1로 두면 원시 합이 된다.
# 네 성분은 언제나 따로 기록한다. 가중치는 가정이고, 가정이 바뀌어도 관측은 남아야 한다.
#
# ── 기본 한도의 근거 ────────────────────────────────────────────────────────────────
# 381세션 분포: p50 220,933 · p75 1,325,794 · p90 6,271,519 · p95 13,680,984 · p99 24,504,250.
# 경고 6,000,000(p90 바로 아래) · 차단 15,000,000(p95와 p99 사이). 임의의 숫자를 박으면 게이트가
# 오탐으로 죽는다 — 이 문턱이면 정상 작업의 95% 이상이 차단을 느끼지 못하고, 걸리는 것은 실측
# 분포의 꼬리뿐이다. 경고는 상위 10% 대역에서 먼저 울려 차단이 예고 없이 오지 않게 한다.
#
# 오류는 전부 allow (fail-open). 예산 가드가 죽어서 세션이 멈추는 것은 예산 초과보다 나쁘다.
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

# 와이어 포맷은 공용 라이브러리가 쥔다. 정책(어느 호스트에 무엇을 낼지)은 이 파일에 남는다 —
# 아래 emit 이 다른 주입 훅과 다른 것은 드리프트가 아니라 호스트가 강제한 것이다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.inject import client, cursor_context, host_context  # noqa: E402

ACTIONS = {"prompt", "task"}

# 표준 상대 단가 — 입력 1 기준. 설정 budget.weights로 덮어쓴다.
WEIGHTS = {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.1}

# 트랜스크립트 usage 필드 → 내부 성분 이름 (Claude Code JSONL 스키마, 26-07-27 확인)
_USAGE_FIELDS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_creation_input_tokens": "cache_write",
    "cache_read_input_tokens": "cache_read",
}

DEFAULTS = {
    "enforce": "block",  # block | warn | off
    "session_cost_units": 15_000_000,  # p95(13.7M)와 p99(24.5M) 사이 — 381세션 실측
    "warn_cost_units": 6_000_000,  # p90(6.27M) 바로 아래 — 차단 전에 먼저 울린다
    "agent_cost_units": 3_000_000,  # 한 역할이 세션 내내 쓸 수 있는 누적 상한
    "agent_calls": 24,  # 한 역할의 세션 내 호출 횟수 상한
}

# 차단 사유 — 전송 표면 계약은 메시지 서두의 `[gate:<code>]` 태그 (failures.py 규약과 동일 어휘).
# verifier_gate의 GATE_MESSAGES 와는 별개 표다 (다른 게이트, 다른 코드 공간).
# 상한을 올리는 길은 **`asgard budget --set` 하나**로 적는다. 설정 파일을 직접 고치라고 적던
# 문장은 통제 표면 가드가 막는 편집을 지시했고 (readonly_guard 는 `.asgard/` 아래 편집을 어느
# 역할에도 안 연다), 역할은 그 앞에서 멈추거나 우회로를 찾았다 (26-08-05).
GATE_MESSAGES = {
    "budget-ceiling": (
        "Session spend {spent} cost units has reached the ceiling ({limit}). "
        "Finish the deliverable in hand, report what is done and what remains, and start no new "
        "work in this session. Subagent dispatch is refused from here under the default "
        "`budget.enforce: block`. Raising the ceiling is Odin's call, not yours — report that you "
        "hit it and name the command (`asgard budget --set session_cost_units=<n>`). The limit is "
        "one number for every model, so a session on a large-context model reaches it in fewer turns."
    ),
    "budget-agent-ceiling": (
        "Subagent role `{role}` has consumed {spent} cost units this session (limit {limit}). "
        "Do the remaining work in the main lane, or report that the ceiling needs raising "
        "(`asgard budget --set agent_cost_units=<n>`)."
    ),
    "budget-agent-calls": (
        "Subagent role `{role}` has been dispatched {spent} times this session (limit {limit}). "
        "Repeated dispatch of the same role is the shape of a loop, not of progress — "
        "reconsider the approach (Canon 9), or report that the limit needs raising "
        "(`asgard budget --set agent_calls=<n>`)."
    ),
}


def gate_message(code: str, **params) -> str:
    template = GATE_MESSAGES.get(code)
    if not template:
        return f"[gate:{code}]"
    return f"[gate:{code}] " + template.format(**params)


# ── 소비 집계 ────────────────────────────────────────────────────────────────────────
@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0

    def add(self, other: "Usage") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_write += other.cache_write
        self.cache_read += other.cache_read

    @property
    def raw(self) -> int:
        """가중치 없는 원시 합 — 관측 보존용. 상한 판정에는 쓰지 않는다."""
        return self.input + self.output + self.cache_write + self.cache_read

    def cost_units(self, weights: dict | None = None) -> float:
        w = {**WEIGHTS, **(weights or {})}
        return (
            self.input * float(w["input"])
            + self.output * float(w["output"])
            + self.cache_write * float(w["cache_write"])
            + self.cache_read * float(w["cache_read"])
        )


@dataclass
class Ledger:
    main: Usage = field(default_factory=Usage)
    agents: dict = field(default_factory=dict)  # role -> Usage
    agent_calls: dict = field(default_factory=dict)  # role -> int
    models: dict = field(default_factory=dict)  # model -> call count
    read_error: str = ""  # 조용한 절단 금지 — 못 읽었으면 그 사실을 넣는다

    def total(self) -> Usage:
        out = Usage()
        out.add(self.main)
        for usage in self.agents.values():
            out.add(usage)
        return out

    def cost_units(self, weights: dict | None = None) -> float:
        return self.total().cost_units(weights)


def _usage_from(raw) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    out = Usage()
    seen = False
    for field_name, attr in _USAGE_FIELDS.items():
        value = raw.get(field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value < 0:
            continue
        setattr(out, attr, getattr(out, attr) + int(value))
        seen = True
    return out if seen else None


def read_ledger(path: str) -> Ledger:
    """트랜스크립트 JSONL을 두 레인으로 집계한다. 못 읽으면 빈 집계 + read_error.

    메인 레인은 assistant 행의 message.usage, 에이전트 레인은 Task 결과의 toolUseResult 다.
    한 행이 깨져도 나머지는 센다 — 부분 관측이 무관측보다 낫고, 부분이라는 사실은 read_error가 진다."""
    ledger = Ledger()
    if not path:
        ledger.read_error = "no transcript path"
        return ledger
    try:
        handle = open(path, encoding="utf-8", errors="ignore")
    except Exception as exc:
        ledger.read_error = f"open failed: {type(exc).__name__}"
        return ledger
    broken = 0
    with handle:
        for line in handle:
            if '"usage"' not in line and '"toolUseResult"' not in line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                broken += 1
                continue
            if not isinstance(row, dict):
                continue
            message = row.get("message")
            if isinstance(message, dict):
                usage = _usage_from(message.get("usage"))
                if usage:
                    ledger.main.add(usage)
                    model = str(message.get("model") or "")
                    if model:
                        ledger.models[model] = ledger.models.get(model, 0) + 1
            result = row.get("toolUseResult")
            if isinstance(result, dict):
                role = str(result.get("agentType") or "").strip()
                if role:
                    ledger.agent_calls[role] = ledger.agent_calls.get(role, 0) + 1
                    usage = _usage_from(result.get("usage"))
                    if usage:
                        ledger.agents.setdefault(role, Usage()).add(usage)
                    model = str(result.get("resolvedModel") or "")
                    if model:
                        ledger.models[model] = ledger.models.get(model, 0) + 1
    if broken:
        ledger.read_error = f"{broken} unparsable line(s)"
    return ledger


# ── 판정 ────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Verdict:
    action: str  # "allow" | "warn" | "block"
    code: str = ""
    message: str = ""
    spent: float = 0.0
    limit: float = 0.0


def _num(value, fallback):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return value if value > 0 else fallback


def verdict(ledger: Ledger, limits: dict, role: str = "") -> Verdict:
    """세션 상한 → 역할 누적 상한 → 역할 호출 상한 순으로 본다. 판정은 순수 — IO 없음.

    role은 이번에 스폰하려는 서브에이전트다. 빈 문자열이면 세션 상한만 본다 (메인 레인 지점).
    역할 상한은 **이미 쓴 것**으로 판정한다 — 앞으로 얼마나 쓸지는 알 수 없고, 알 수 없는 것으로
    막으면 게이트가 추측을 시작한다."""
    weights = limits.get("weights") if isinstance(limits.get("weights"), dict) else None
    spent = ledger.cost_units(weights)

    ceiling = _num(limits.get("session_cost_units"), DEFAULTS["session_cost_units"])
    if spent >= ceiling:
        return Verdict(
            "block",
            "budget-ceiling",
            gate_message("budget-ceiling", spent=f"{spent:,.0f}", limit=f"{ceiling:,.0f}"),
            spent,
            ceiling,
        )

    if role:
        agent_ceiling = _num(limits.get("agent_cost_units"), DEFAULTS["agent_cost_units"])
        used = ledger.agents.get(role)
        agent_spent = used.cost_units(weights) if used else 0.0
        if agent_spent >= agent_ceiling:
            return Verdict(
                "block",
                "budget-agent-ceiling",
                gate_message(
                    "budget-agent-ceiling",
                    role=role,
                    spent=f"{agent_spent:,.0f}",
                    limit=f"{agent_ceiling:,.0f}",
                ),
                agent_spent,
                agent_ceiling,
            )
        call_cap = _num(limits.get("agent_calls"), DEFAULTS["agent_calls"])
        calls = ledger.agent_calls.get(role, 0)
        if calls >= call_cap:
            return Verdict(
                "block",
                "budget-agent-calls",
                gate_message("budget-agent-calls", role=role, spent=calls, limit=call_cap),
                calls,
                call_cap,
            )

    warn_at = _num(limits.get("warn_cost_units"), DEFAULTS["warn_cost_units"])
    if warn_at < ceiling and spent >= warn_at:
        return Verdict("warn", "budget-warn", warn_text(ledger, spent, ceiling), spent, ceiling)
    return Verdict("allow", spent=spent, limit=ceiling)


def warn_text(ledger: Ledger, spent: float, ceiling: float) -> str:
    pct = (spent / ceiling * 100) if ceiling else 0.0
    lines = [
        f"[asgard budget] Session spend {spent:,.0f} / {ceiling:,.0f} cost units ({pct:.0f}%).",
        "Finish the core deliverable first; drop optional exploration. "
        "Do not start work you cannot finish inside the remaining budget — "
        "say what you are dropping instead of silently truncating it.",
    ]
    if ledger.agent_calls:
        busiest = sorted(ledger.agent_calls.items(), key=lambda kv: -kv[1])[:3]
        lines.append("Subagent dispatches so far: " + ", ".join(f"{r}×{n}" for r, n in busiest) + ".")
    return "\n".join(lines)


# ── 설정 ────────────────────────────────────────────────────────────────────────
def load_limits(root: str) -> dict:
    """env > 프로젝트 > 글로벌 > 기본값. settings.py의 스코프 규칙과 동일 유지 (단일 출처 원칙)."""
    limits = dict(DEFAULTS)
    home = os.environ.get("HOME") or os.path.expanduser("~")
    for path in (
        os.path.join(home, ".asgard", "asgard-setting-global.json"),
        os.path.join(root, ".asgard", "asgard-setting-project.json"),
    ):
        try:
            with open(path, encoding="utf-8") as handle:
                config = json.load(handle)
        except Exception:
            continue
        section = config.get("budget") if isinstance(config, dict) else None
        if isinstance(section, dict):
            limits.update(section)
    override = os.environ.get("ASGARD_BUDGET")
    if override:
        mode = override.strip().lower()
        if mode in {"off", "warn", "block"}:
            limits["enforce"] = mode
    return limits


# ── 훅 배선 ─────────────────────────────────────────────────────────────────────
def action() -> str:
    raw = str(sys.argv[2] if len(sys.argv) > 2 else "prompt").lower()
    return raw if raw in ACTIONS else "prompt"


def emit(current_client: str, text: str, event: str, current_action: str = "prompt") -> None:
    """주입 스키마는 클라이언트마다 다르다 — unattended-context·map-activate와 동일 유지 (단일 규약).

    Cursor의 beforeSubmitPrompt는 컨텍스트 주입 통로가 없다 (출력이 continue/user_message 뿐,
    cursor.com/docs/hooks 26-07-27 확인). 남은 continue=False 는 프롬프트를 지우는 그 동작이라
    상한 안내에도 쓸 수 없다 — Cursor 메인 레인은 경고도 상한도 내보내지 않고, 사람 표면은
    `asgard budget` 하나다. 틀린 스키마를 내면 훅 전체가 파싱 실패로 죽어 스폰 거부까지 사라진다."""
    if current_client == "cursor":
        if current_action == "prompt":
            return
        cursor_context(text)
    elif current_client == "codex":
        host_context(event, text)
    else:
        sys.stdout.write(text)


def deny(current_client: str, message: str) -> None:
    """스폰 거부 — Claude Code/Codex는 exit 2 + stderr (git-guard와 동일 규약).

    메인 레인에는 호출자가 없다: UserPromptSubmit 의 거부는 프롬프트를 지우기 때문이다(모듈 주석).
    남은 지점이 PreToolUse 하나라서 Cursor 도 스키마가 permission JSON 하나로 좁아진다."""
    if current_client == "cursor":
        payload = {"permission": "deny", "user_message": message, "agent_message": message}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.exit(0)
    print(message, file=sys.stderr)
    sys.exit(2)


def spawn_role(data: dict) -> str:
    """PreToolUse(Task) 페이로드에서 스폰 대상 역할 — memory_activate의 추출 순서와 동일 유지."""
    raw_input = data.get("tool_input")
    tool_input: dict = raw_input if isinstance(raw_input, dict) else {}
    for value in (
        data.get("agent_type"),
        data.get("subagent_type"),
        tool_input.get("agent_type"),
        tool_input.get("subagent_type"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def main() -> None:
    current_client = client()
    current_action = action()
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if not isinstance(data, dict):
        sys.exit(0)

    root = str(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    limits = load_limits(root)
    enforce = str(limits.get("enforce") or "block").lower()
    if enforce == "off":
        sys.exit(0)

    ledger = read_ledger(str(data.get("transcript_path") or ""))
    role = spawn_role(data) if current_action == "task" else ""
    result = verdict(ledger, limits, role)

    if result.action == "block":
        # 거부는 스폰 레인에만 있다 — 메인 레인의 거부는 프롬프트를 지우고, 지워진 프롬프트는
        # 지출을 되돌리지 못한다(모듈 주석). 상한에서도 메인 레인은 지시를 넣고 턴을 연다.
        if enforce == "block" and current_action == "task":
            deny(current_client, "Asgard budget-guard — " + result.message)
        emit(current_client, "[asgard budget] " + result.message, _EVENT[current_action], current_action)
        sys.exit(0)
    if result.action == "warn":
        emit(current_client, result.message, _EVENT[current_action], current_action)
        sys.exit(0)
    if current_client == "cursor" and current_action == "task":
        # Cursor는 침묵을 허용으로 안 본다 — 명시적 allow가 프로토콜 요구사항 (secret-guard와 동일).
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    sys.exit(0)


_EVENT = {"prompt": "UserPromptSubmit", "task": "PreToolUse"}


if __name__ == "__main__":
    main()
