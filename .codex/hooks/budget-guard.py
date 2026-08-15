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
# ── 매 호출 전량 재스캔을 안 하는 이유 (26-08-14) ────────────────────────────────────
# 이 훅은 UserPromptSubmit 과 PreToolUse 두 자리에 걸려 있어 도구 호출마다 돈다. 계측원인 트랜스
# 크립트는 세션 내내 자라기만 하고(이 저장소 실측 1.38MB), 매번 통째로 훑으면 훅 한 번의 값이
# 세션 길이에 비례해 붙는다. 그래서 마지막으로 센 바이트 오프셋과 그때까지의 누계를 세션별 상태
# 파일(`.asgard/state/budget-<세션>.json`)에 적고, 다음 호출은 그 뒤에 붙은 바이트만 읽는다.
#
# 꼬리 N줄만 읽는 방법은 여기서 오답이다 — 앞부분을 놓치면 누계가 실제보다 작아지고 상한 판정이
# **막아야 할 때 안 막는 쪽**으로 틀린다. 체크포인트는 앞부분을 버리는 게 아니라 접어 두는 것이라
# 집계값이 전량 스캔과 같다. 값을 못 믿는 자리는 전부 전량 재스캔으로 되돌아간다: 파일이 줄었다
# (회전·교체), 앞 4096바이트 지문이 다르다, 상태 파일이 깨졌거나 없다. `read_ledger` 참조.
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
# 차단 54,000,000 은 p99 의 2.2배다 — 임의의 숫자를 박으면 게이트가 오탐으로 죽고, 걸리는 것은
# 실측 분포의 꼬리뿐이어야 한다. 종전 30,000,000(p99 바로 위)에서 80% 올린 값이고, 올린 이유는
# 분포가 아니라 이 게이트가 무엇을 끊느냐다: p99 근처의 상한이 잡는 것은 폭주가 아니라 판정
# 왕복이 붙은 긴 정상 세션이었다. 저장소가 자기 폭을 좁히는 것은 설정으로 언제든 할 수 있고
# (`asgard budget --set session_cost_units=<n>`), 내장 기본값은 그 반대쪽 — 정상 작업이 기본값
# 때문에 끊기지 않는 자리 — 에 둔다.
#
# 경고는 그 상한의 80%다. 종전처럼 6,000,000(p90 아래) 같은 절대값에 박으면 상한의 11% 지점부터
# "핵심만 끝내고 탐색은 버려라"가 매 턴 붙어, 세션은 남은 89%를 그 지시와 함께 쓴다. 몫으로
# 두면 경고가 상한을 따라가고, 경고와 차단 사이에는 10,800,000 이 남는다 (정상 세션 여럿에
# 맞먹는 예고 구간).
#
# 오류는 전부 allow (fail-open). 예산 가드가 죽어서 세션이 멈추는 것은 예산 초과보다 나쁘다.
from __future__ import annotations

import json
import os
import sys
import zlib
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

from asgard_hooklib.firing import run  # noqa: E402
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

# 경고 문턱은 상한의 몫으로 잡는다. 절대값으로 박으면 상한을 올린 저장소에서 경고가 세션
# 앞머리에 머물고, 그 뒤의 모든 턴이 "마무리하라"는 지시를 달고 돈다. 설정에 warn_cost_units
# 를 적으면 그 절대값이 우선한다 — 몫은 기본값일 뿐이다.
WARN_RATIO = 0.8

DEFAULTS = {
    "enforce": "block",  # block | warn | off
    # p99(24.5M)의 2.2배. 15M 은 p95(13.7M)와 p99 사이였는데, 그 값이 잡는 것은 폭주가 아니라
    # **긴 정상 세션**이었다 — 26-08-11 에 판정 왕복이 있는 한 세션이 상한에 닿아 남은 일이 독립
    # 판정 하나뿐인 자리에서 배차가 막혔고, 그 턴이 판정 없이 끝났다. 상한의 값은 폭주를 끊는
    # 것인데 판정을 끊으면 게이트가 지키려던 것을 게이트가 깎는다. 30M 도 p99 바로 위라 같은
    # 자리에 있었고, 26-08-12 에 80% 올려 54M 으로 뒀다.
    "session_cost_units": 54_000_000,
    # warn_cost_units 는 기본값이 없다 — 없으면 warn_threshold() 가 상한의 WARN_RATIO 배로 센다.
    # 역할 상한은 세션 상한의 10% — 세션이 넓어지면 한 역할의 몫도 같은 비율로 넓어진다.
    "agent_cost_units": 5_400_000,  # 한 역할이 세션 내내 쓸 수 있는 누적 상한
    # 호출 횟수는 지출이 아니라 같은 역할을 되풀이해 부르는 모양(Canon 9)의 탐지라 상한과 함께
    # 올리지 않는다 — 24회를 채우는 것은 예산을 다 쓴 것이 아니라 루프에 들어간 것이다.
    "agent_calls": 24,
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
    broken: int = 0  # 못 읽은 줄 수 — read_error 문구의 출처이자 체크포인트에 이어지는 값

    def total(self) -> Usage:
        out = Usage()
        out.add(self.main)
        for usage in self.agents.values():
            out.add(usage)
        return out

    def cost_units(self, weights: dict | None = None) -> float:
        return self.total().cost_units(weights)

    def merge(self, other: "Ledger") -> None:
        """다른 집계를 이 집계에 더한다 — 체크포인트에 접어 둔 몫과 이번에 읽은 몫을 잇는 자리."""
        self.main.add(other.main)
        for role, usage in other.agents.items():
            self.agents.setdefault(role, Usage()).add(usage)
        for role, calls in other.agent_calls.items():
            self.agent_calls[role] = self.agent_calls.get(role, 0) + calls
        for model, calls in other.models.items():
            self.models[model] = self.models.get(model, 0) + calls
        self.broken += other.broken


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


def _ingest(ledger: Ledger, row: dict) -> None:
    """트랜스크립트 한 행을 두 레인에 반영한다 — 메인은 message.usage, 에이전트는 toolUseResult."""
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


def _scan(handle) -> tuple[Ledger, int, Ledger]:
    """열린 파일의 현재 위치부터 끝까지 센다 — `(확정 집계, 확정한 바이트 수, 꼬리 집계)`.

    개행으로 끝나지 않은 마지막 줄은 호스트가 지금 쓰는 중일 수 있다. 그 줄은 이번 판정에는
    넣되(빼면 과소 집계고, 과소 집계는 안 막는 쪽으로 틀린다) 확정 몫에서는 뺀다 — 확정하면
    다음 호출이 그 줄의 나머지를 새 줄로 읽어 반쪽만 세거나 같은 usage 를 두 번 센다.

    이진 모드로 읽는 이유는 두 가지다: 바이트 오프셋이 그대로 나와야 체크포인트를 적을 수 있고,
    `"usage"` 선별을 디코딩 전에 해서 걸러지는 줄의 디코딩 값을 안 낸다."""
    committed, tail, consumed = Ledger(), Ledger(), 0
    for raw in handle:
        target = committed if raw.endswith(b"\n") else tail
        if target is committed:
            consumed += len(raw)
        if b'"usage"' not in raw and b'"toolUseResult"' not in raw:
            continue
        try:
            row = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            target.broken += 1
            continue
        if isinstance(row, dict):
            _ingest(target, row)
    return committed, consumed, tail


# 체크포인트 — 마지막으로 센 자리와 그때까지의 누계. 파일 형식이 바뀌면 version 을 올린다:
# 못 알아보는 판은 버려지고 그 세션은 한 번 전량 재스캔한다 (틀린 누계를 이어받는 것보다 낫다).
_CHECKPOINT_VERSION = 1
_HEAD_BYTES = 4096  # 파일 동일성 지문을 뜨는 앞부분 — 세션 기록은 줄마다 sessionId 를 적는다
_COMPONENTS = ("input", "output", "cache_write", "cache_read")


def _checkpoint_path(root: str, transcript: str) -> str:
    """이 트랜스크립트의 체크포인트 파일 — 쓸 자리가 없으면 빈 문자열.

    이름짓기는 craft-gate 의 `writes-<세션>.json`·`craftgate-<세션>.json` 과 같은 규약이고, 세션
    이름은 트랜스크립트 파일 이름이다 (Claude Code 는 `<session-id>.jsonl`, Codex 는
    `rollout-<시각>-<uuid>.jsonl`). `.asgard` 가 없는 트리에는 안 적는다 — 아스가르드를 안 쓰는
    저장소에 상태 폴더를 만드는 것은 이 훅의 일이 아니다."""
    if not root or not transcript or not os.path.isdir(os.path.join(root, ".asgard")):
        return ""
    name = os.path.basename(transcript)
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")]
    safe = "".join(char if (char.isalnum() or char in "._-") else "-" for char in name)
    return os.path.join(root, ".asgard", "state", "budget-" + safe + ".json") if safe else ""


def _head_mark(handle) -> str:
    """파일 앞부분의 지문 — 같은 이름에 다른 파일이 앉았는지(회전·교체) 가리는 값.

    hashlib 이 아니라 zlib 인 이유는 값이다: 이 훅은 도구 호출마다 새 프로세스로 뜨고 `import
    hashlib` 하나가 실측 0.9~1.2ms 인데 `import zlib` 은 0.03ms 다. 32비트 검사합이라 서로 다른
    앞부분이 같은 값을 낼 확률이 남지만, 그 자리는 파일이 같은 이름·같은 이상의 크기로 교체되고
    앞 4096바이트의 검사합까지 같은 경우다. 어긋나면 전량 재스캔이므로 틀리는 방향은 느린 쪽이다."""
    handle.seek(0)
    return format(zlib.crc32(handle.read(_HEAD_BYTES)), "08x")


def _read_checkpoint(path: str, head: str, size: int) -> tuple[int, Ledger] | None:
    """`(오프셋, 그때까지의 누계)` — 이어 붙일 수 없으면 None (호출자는 전량 재스캔한다).

    되돌아가는 조건: 파일이 없다·JSON 이 깨졌다·판이 다르다·앞부분 지문이 다르다(교체)·오프셋이
    파일 크기를 넘는다(잘렸다)·성분에 정수가 아닌 값이 있다. 의심스러운 판은 고쳐 쓰지 않고
    통째로 버린다 — 틀린 누계를 이어받으면 상한이 조용히 어긋난다."""
    try:
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
    except Exception:
        return None
    if not isinstance(saved, dict) or saved.get("version") != _CHECKPOINT_VERSION:
        return None
    if saved.get("head") != head:
        return None
    offset = saved.get("offset")
    broken = saved.get("broken", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= size:
        return None
    if isinstance(broken, bool) or not isinstance(broken, int) or broken < 0:
        return None
    ledger = Ledger(broken=broken)
    main = _usage_from_state(saved.get("main"))
    if main is None:
        return None
    ledger.main = main
    agents = saved.get("agents")
    if not isinstance(agents, dict):
        return None
    for role, raw in agents.items():
        usage = _usage_from_state(raw)
        if usage is None:
            return None
        ledger.agents[str(role)] = usage
    for source, target in ((saved.get("calls"), ledger.agent_calls), (saved.get("models"), ledger.models)):
        if not isinstance(source, dict):
            return None
        for key, count in source.items():
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                return None
            target[str(key)] = count
    return offset, ledger


def _usage_from_state(raw) -> Usage | None:
    """체크포인트에 적힌 성분 넷 → Usage. 하나라도 음수·비정수면 None (판 전체를 버린다)."""
    if not isinstance(raw, dict):
        return None
    usage = Usage()
    for name in _COMPONENTS:
        value = raw.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        setattr(usage, name, value)
    return usage


def _write_checkpoint(path: str, offset: int, head: str, ledger: Ledger) -> None:
    """확정한 자리까지의 누계를 적는다 — 실패는 삼킨다 (다음 호출이 전량 재스캔하면 그만이다).

    temp+rename 은 craft-gate 의 카운터와 같은 이유다: 중간에 끊긴 파일이 남으면 다음 호출이
    그것을 읽고 누계를 잃는다."""
    payload = {
        "version": _CHECKPOINT_VERSION,
        "offset": offset,
        "head": head,
        "broken": ledger.broken,
        "main": {name: getattr(ledger.main, name) for name in _COMPONENTS},
        "agents": {role: {name: getattr(usage, name) for name in _COMPONENTS} for role, usage in ledger.agents.items()},
        "calls": dict(ledger.agent_calls),
        "models": dict(ledger.models),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except Exception:
        pass  # 못 적으면 다음 호출이 전량 재스캔한다 — 집계는 안 틀리고 그 한 번이 느려질 뿐이다


def read_ledger(path: str, root: str = "") -> Ledger:
    """트랜스크립트 JSONL을 두 레인으로 집계한다. 못 읽으면 빈 집계 + read_error.

    메인 레인은 assistant 행의 message.usage, 에이전트 레인은 Task 결과의 toolUseResult 다.
    한 행이 깨져도 나머지는 센다 — 부분 관측이 무관측보다 낫고, 부분이라는 사실은 read_error가 진다.

    `root` 를 주면 세션별 체크포인트에 확정 오프셋과 누계를 적고 다음 호출은 그 뒤만 읽는다.
    안 주면 매번 전량 스캔이다 — 어느 쪽이든 같은 파일에 대한 집계값은 같다."""
    ledger = Ledger()
    if not path:
        ledger.read_error = "no transcript path"
        return ledger
    try:
        handle = open(path, "rb")
    except Exception as exc:
        ledger.read_error = f"open failed: {type(exc).__name__}"
        return ledger
    with handle:
        state = _checkpoint_path(root, path)
        head = _head_mark(handle) if state else ""
        resumed = _read_checkpoint(state, head, os.fstat(handle.fileno()).st_size) if state else None
        start, ledger = resumed if resumed else (0, Ledger())
        handle.seek(start)
        committed, consumed, tail = _scan(handle)
        ledger.merge(committed)
        if state and (consumed or not resumed):
            _write_checkpoint(state, start + consumed, head, ledger)
        ledger.merge(tail)
    if ledger.broken:
        ledger.read_error = f"{ledger.broken} unparsable line(s)"
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


def warn_threshold(limits: dict) -> float:
    """경고가 울리는 값 — 설정에 절대값이 없으면 상한의 WARN_RATIO 배.

    판정(`verdict`)과 사람 표면(`asgard budget`)이 이 함수 하나를 본다. 두 자리에서 따로
    계산하면 화면이 적어 놓은 문턱과 게이트가 울리는 문턱이 갈라진다."""
    ceiling = float(_num(limits.get("session_cost_units"), DEFAULTS["session_cost_units"]))
    return float(_num(limits.get("warn_cost_units"), ceiling * WARN_RATIO))


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

    warn_at = warn_threshold(limits)
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

    # root 를 같이 넘기는 것이 증분 스캔의 스위치다 — 이 훅은 도구 호출마다 도는 자리라
    # 트랜스크립트를 매번 통째로 훑으면 값이 세션 길이에 비례해 붙는다 (모듈 주석).
    ledger = read_ledger(str(data.get("transcript_path") or ""), root)
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
    run("budget-guard", main)
