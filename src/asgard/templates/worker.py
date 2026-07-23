"""Worker 공통 스킬 2종 — 도메인 불문 코드 작업의 심화 지식 (체계적 디버깅·테스트 설계).

표준 엔지니어링 관행을 우리 용어로 재서술한 자체 캐논이다 — 외부 텍스트 재배포 없음.
딜리버리 전문가(프레이야·토르·에이트리)의 도메인 스킬과 달리 이 층은 Worker 표면 공통이다 —
백엔드든 프론트든 버그 원인 규명과 테스트 설계의 문법은 하나다.

CC(.claude/skills/)와 Cursor·Codex 공용(.agents/skills/) 양 스코프에 스캐폴드되어 모드 A/B 에서
파일 스킬로 로드되고, 네이티브(asgard start)는 heimdall 이 Worker system 에 직접 주입한다.
Verifier/loki 무주입 — 게이트·판정 표면에는 advisory 지식을 넣지 않는다 (skill_bank 헌법과 동일 규율)."""

import re

_DEBUGGING = """\
---
name: asgard-worker-debugging
description: Systematic debugging — load before root-causing and fixing bugs, crashes, or regressions. Reproduce → observe → one hypothesis at a time → bisect → minimal fix → regression pin.
---

# asgard-worker-debugging — 🔎 Systematic Debugging

What sets the speed of a fix is not typing speed but the discipline of narrowing the cause.

## Reproduce first (no reproduction, no fix)

- Build a minimal reproduction — shrink inputs, environment, and path to the smallest condition where the failure holds, and measure it. Record the repro command and the observed result (exit code, error output).
- If it cannot be reproduced, report that fact instead of guess-fixing — along with the angles tried (input, environment, timing). A fix without a reproduction also has no way to verify "it's fixed."

## Observation > guessing

- Read error messages and stacks to the end — the causal frame, not the first frame; for wrapped exceptions, down to the root exception.
- Look at actual state: confirm "what is the value at this point" via logs, a debugger, or intermediate-value output — no "it's probably here" edits (Canon 5).
- Cause claims in existing reports, comments, and issues are unverified input — re-confirm directly before using them.

## Hypothesis loop (one at a time)

- One hypothesis = one change — simultaneous multiple changes make it impossible to know what fixed it (or what newly broke it).
- Make hypotheses falsifiable: write "if X, then Y will be observed" first and compare against measurement. If it diverges, discard the hypothesis — never reinterpret observations to fit it.
- Stop after 3 attempts that add no evidence — report with a summary of observations so far (confirmed facts / eliminated hypotheses). Repeated attempts on the same hypothesis count as one.

## Bisection (when the candidate space is wide)

- Commit axis: since when is it broken — git bisect (the repro command is the judge).
- Input axis: which input breaks it — eliminate half of the input at a time.
- Code axis: where does the value go wrong — place an observation point mid-path and split before/after.

## Minimal fix (at the cause site)

- The fix must map 1:1 to the identified cause — layering defensive code over the symptom site is concealment, not a fix.
- If the fix is "ran it and it worked" with no causal explanation, the debugging is not finished yet.

## Regression pin

- Leave a test that fails before the fix and passes after — that transition is the evidence for "it's fixed" (Canon 8).
- Check same-family neighbors (other sites using the same pattern) once — but scope expansion stops at reporting the finding; fix only the assigned scope (Canon 7).
- Test-writing discipline belongs to `asgard-worker-testing`.
"""

_TESTING = """\
---
name: asgard-worker-testing
description: Test design — load before writing, strengthening, or de-flaking tests. Pin public behavior, fail first, boundary values, determinism isolation.
---

# asgard-worker-testing — 🧪 Test Design

A test is a contract that keeps a future changer from breaking today's behavior — a contract can only be kept if it is concrete.

## What to pin (public behavior)

- Tests pin public behavior (input → output, state changes, side effects) — never pin internal implementation detail (private functions, internal call order, intermediate representations): a test that breaks on every refactor is a liability, not an asset.
- Project convention comes first (Canon 5): read and follow the existing tests' framework, fixtures, naming, and placement — introduce a new style only when the assignment explicitly calls for it.

## Fail first

- A new test must be seen to fail once — a test that has only ever been seen passing may not be exercising the target, or may be a tautological assertion.
- A test accompanying a bug fix must actually measure the failure before the fix — that transition is the proof the test exists (Canon 8).
- **Vertical slice**: one failing test for one public seam → the minimal implementation that passes only that test → move to the next seam in order. Horizontal splitting — writing a pile of layer-by-layer tests up front — is forbidden because it pins an implementation not yet observed.

## Case skeleton

- Minimum skeleton: one happy path + boundaries (empty value, 0, 1, max, just before/after a boundary, unicode) + shape verification of failure paths (exceptions, rejection, timeout).
- Systematic counterexample search is loki's surface — Worker fills in the skeleton, and the verdict belongs to Verifier (Canon 10).

## Determinism (cut off flakiness at the source)

- Time: no real wall clock — a fixed clock or injectable time.
- Random: a fixed seed, or injected.
- Network: no real remote calls — isolate with fakes/fixtures (exception only when declared an integration test).
- Filesystem: use a temp directory — never pollute the repo or home directory.
- Order: tests are independent of each other — no dependence on execution order or shared state; each test builds its own state.
- On finding a flaky test, do not paper over it with retries — classify the cause along the five axes above and fix it (CI-layer handling belongs to `asgard-eitri-draupnir`).

## Assertion quality

- Assert on concrete values — weak assertions like "not null" or "no error" make a pass uninformative.
- Let the failure message state the cause — choose an assertion form that surfaces expected vs. actual.
- Coverage is a metric, not a goal — no assertion-free tests written just to pad the number.

## Layer placement

- Unit is the default (fast and narrow, the majority), integration covers boundary seams (between modules/processes), E2E covers only the core flows at a minimum — an inverted pyramid that is all E2E is slow and can't pinpoint causes.
"""

WORKER_SKILLS: list[tuple[str, str]] = [
    ("asgard-worker-debugging", _DEBUGGING),
    ("asgard-worker-testing", _TESTING),
]

# Worker task → 공통 스킬 매칭 (네이티브 Worker system 주입용 통로 — 모드 A/B 는 파일 스킬이 담당).
# Worker 는 모든 과업이 지나는 표면이라 과주입이 곧 노이즈다 — 트리거는 보수적으로 유지한다.
_SUBSTR: dict[str, tuple[str, ...]] = {
    "asgard-worker-debugging": (
        "디버깅",
        "디버그",
        "버그",
        "크래시",
        "스택트레이스",
        "stack trace",
        "traceback",
        "재현",
        "reproduc",
        "root cause",
        "원인 규명",
        "원인 분석",
        "회귀",
        "regression",
    ),
    "asgard-worker-testing": (
        "테스트",
        "커버리지",
        "coverage",
        "픽스처",
        "fixture",
        "flaky",
        "단언",
        "assertion",
        "모킹",
        "pytest",
        "vitest",
        "회귀",
        "regression",
    ),
}
# 짧은 ASCII 용어는 단어 경계 필수 — 부분 일치면 latest→test, majestic→jest, debugger 는 잡되
# ladybug 는 제외하는 식의 통제가 불가능하다.
_WORD_RE: dict[str, tuple[str, ...]] = {
    "asgard-worker-debugging": (r"\bdebug", r"\bbugs?\b", r"\bcrash", r"\bbisect\b"),
    "asgard-worker-testing": (r"\btests?\b", r"\btesting\b", r"\btdd\b", r"\bjest\b", r"\bmock"),
}


def resolve_worker_skills(task: str) -> list[tuple[str, str]]:
    """Worker task → 매칭된 공통 스킬 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    무매칭 = 빈 리스트 (fail-open — role 계약 기준으로 진행). 복수 매칭은 전부 주입 —
    "회귀 버그 수정 + 회귀 테스트 고정" 처럼 두 표면이 한 과업인 경우가 실재한다.
    호출측은 Worker 한정 — Verifier/loki 는 부르지 않는다 (게이트 무결성)."""
    t = task.lower()

    def hit(name: str) -> bool:
        return any(k in t for k in _SUBSTR.get(name, ())) or any(re.search(p, t) for p in _WORD_RE.get(name, ()))

    return [(name, body.split("---", 2)[2].lstrip()) for name, body in WORKER_SKILLS if hit(name)]
