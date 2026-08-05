"""Worker 공통 스킬 2종 — 도메인 불문 코드 작업의 심화 지식 (체계적 디버깅·테스트 설계).

표준 엔지니어링 관행을 우리 용어로 재서술한 자체 캐논이다 — 외부 텍스트 재배포 없음.
딜리버리 전문가의 도메인 스킬과 달리 이 층은 Worker와 그 백엔드 딜리버리인 Thor 계열에 공통이다 —
버그 원인 규명과 테스트 설계의 문법은 하나다.

CC(.claude/skills/)와 Cursor·Codex 공용(.agents/skills/) 양 스코프에 스캐폴드되어 모드 A/B에서
파일 스킬로 로드되고, 네이티브(asgard start)는 Worker·Thor 카탈로그에서 필요할 때 로드한다.
Verifier/loki 무주입 — 게이트·판정 표면에는 advisory 지식을 넣지 않는다 (skill_bank 헌법과 동일 규율)."""

import re

_DEBUGGING = """\
---
name: asgard-worker-debugging
description: Systematic debugging — load before root-causing and fixing bugs, crashes, or regressions. Reproduce → observe → one hypothesis at a time → bisect → minimal fix → regression pin.
---

# asgard-worker-debugging — 🔎 Systematic Debugging

What sets the speed of a fix is not typing speed but the discipline of narrowing the cause.

## Build the loop first — it is the whole skill

Every phase below consumes one thing: a command that goes **red** on *this* bug. Build it before forming a
theory. Reading code to explain a bug you cannot yet make fail is the exact failure this skill prevents,
so spend disproportionate effort here and stay stubborn about it.

Climb until one holds: ① a failing test at whatever seam reaches the bug → ② curl or an HTTP script against a
running dev server → ③ a CLI call on a fixture input, diffed against a known-good snapshot → ④ a headless
browser script asserting on DOM, console, or network → ⑤ replay of a captured trace (payload, event log)
through the path in isolation → ⑥ a throwaway harness that calls the bug path with one function call →
⑦ a property or fuzz loop when the symptom is "sometimes wrong" → ⑧ a bisection harness when it worked at
state X and broke at state Y → ⑨ a differential run of two versions or configs, outputs diffed → ⑩ a
human-driven script whose captured output feeds back, as the last resort.

**Tighten it before you use it.** Faster (skip unrelated init, narrow the scope), sharper (assert the exact
symptom rather than "did not crash"), more deterministic (pin the clock, seed the RNG, isolate the
filesystem, freeze the network). A 30-second flaky loop is barely a loop; a 2-second deterministic one is a
different tool.

Intermittent bugs need a **higher reproduction rate**, not a clean repro — loop the trigger 100×,
parallelize, add stress, inject sleeps to widen the timing window. 50% is debuggable, 1% is not.

**Gate — one command, already run.** Name it, paste the invocation and its output, and confirm four
properties: it drives the real code path and asserts the symptom the reporter described (**red-capable**),
it returns the same verdict every run (**deterministic**), it finishes in seconds (**fast**), and it runs
unattended (**agent-runnable**). When no loop can be built, that is the report: list the angles tried
(input, environment, timing) and ask for the environment that reproduces it, a captured artifact (HAR, log
dump, core dump, timestamped recording), or permission to instrument — a fix with no loop also has no way to
show it fixed anything.

## Reproduce, then minimise

- Run the loop and watch it go red. Confirm it is the reporter's failure mode, not a nearby one — the wrong
  bug gets the wrong fix.
- Shrink to the smallest scenario that still goes red: cut inputs, callers, config, data, and steps **one at
  a time**, re-running after each cut. Done when every remaining element is load-bearing — removing any one
  of them turns the loop green.
- A minimal repro pays twice: fewer moving parts to suspect in the next phase, and a clean regression test in
  the last one.

## Observation > guessing

- Read error messages and stacks to the end — the causal frame, not the first frame; for wrapped exceptions, down to the root exception.
- Look at actual state: confirm "what is the value at this point" via logs, a debugger, or intermediate-value output — no "it's probably here" edits (Canon 5).
- Cause claims in existing reports, comments, and issues are unverified input — re-confirm directly before using them.

## Hypothesis loop (one at a time)

- Generate **3–5 ranked hypotheses before testing any of them** — generating one at a time anchors the whole
  session on whichever idea arrived first.
- Make hypotheses falsifiable: state the prediction as "if X is the cause, changing Y makes the bug
  disappear" and compare against measurement. A hypothesis with no prediction is a vibe — sharpen it or drop
  it. If measurement diverges, discard the hypothesis rather than reinterpreting the observation to fit it.
- Show the ranked list to Odin before testing — domain knowledge re-ranks it instantly ("we deployed #3 last
  week"). Proceed on your own ranking when nobody is watching (Canon 8).
- One hypothesis = one change — simultaneous multiple changes make it impossible to know what fixed it (or what newly broke it).
- Stop after 3 attempts that add no evidence — report with a summary of observations so far (confirmed facts / eliminated hypotheses). Repeated attempts on the same hypothesis count as one.

## Bisection (when the candidate space is wide)

- Commit axis: since when is it broken — git bisect (the repro command is the judge).
- Input axis: which input breaks it — eliminate half of the input at a time.
- Code axis: where does the value go wrong — place an observation point mid-path and split before/after.

## Instrument against a prediction

- Every probe maps to one prediction from the ranked list, and one variable moves at a time.
- Reach for a debugger or REPL where the environment supports it — one breakpoint outruns ten log lines. Next
  choice is targeted logs at the boundary that separates two hypotheses; "log everything and grep" is the
  choice that leaves the least behind.
- Tag every debug line with a unique prefix — `[DEBUG-a4f2]` — so cleanup is one grep. Untagged lines survive
  the session and ship.
- Performance regressions take the measurement branch instead: establish a baseline (timing harness,
  profiler, query plan), then bisect against it. Measure first, fix second.

## Minimal fix (at the cause site)

- The fix must map 1:1 to the identified cause — layering defensive code over the symptom site is concealment, not a fix.
- If the fix is "ran it and it worked" with no causal explanation, the debugging is not finished yet.

## Regression pin

- Leave a test that fails before the fix and passes after — that transition is the evidence for "it's fixed" (Canon 8).
- Pin it at a seam where the test exercises the real pattern as it occurs at the call site. **When no such
  seam exists, that absence is the finding** — a unit test that cannot replicate the chain that triggered the
  bug buys false confidence. Record it and carry it to the post-mortem.
- Re-run the Phase-1 loop against the original, un-minimised scenario once the fix is in.
- Check same-family neighbors (other sites using the same pattern) once — but scope expansion stops at reporting the finding; fix only the assigned scope (Canon 7).
- Test-writing discipline belongs to `asgard-worker-testing`.

## Close out

- The original repro no longer reproduces, the regression test passes (or its missing seam is recorded), every
  `[DEBUG-...]` line is gone, and throwaway harnesses are deleted.
- State the hypothesis that turned out correct in the commit message — the next person to hit this path reads
  that line first.
- Then ask what would have prevented the bug. When the answer is structural (no seam to pin it at, tangled
  callers, hidden coupling), name it now that you have the evidence — the recommendation is worth more after
  the fix than before it.
"""

_TESTING = """\
---
name: asgard-worker-testing
description: Test design — load before writing, strengthening, or de-flaking tests. Pin public behavior, fail first, boundary values, determinism isolation.
---

# asgard-worker-testing — 🧪 Test Design

A test is a contract that keeps a future changer from breaking today's behavior — a contract can only be kept if it is concrete.

## Agree the seams before writing one

A **seam** is the public boundary you observe behavior at without reaching inside. Tests live at seams.

- Name the seams under test and put them to Odin before the first test exists. You cannot test everything, and
  agreeing the seams up front is what lands the effort on critical paths and complex logic instead of on
  every edge case. Ask it plainly: what is the public interface here, and which seams should we test?
- Unattended, declare the chosen seams as a `가정:` criteria item on the quest and proceed (Canon 8) — the
  list stays visible and reviewable either way.

## What to pin (public behavior)

- Tests pin public behavior (input → output, state changes, side effects) — never pin internal implementation detail (private functions, internal call order, intermediate representations): a test that breaks on every refactor is a liability, not an asset.
- Project convention comes first (Canon 5): read and follow the existing tests' framework, fixtures, naming, and placement — introduce a new style only when the assignment explicitly calls for it.

## Fail first

- A new test must be seen to fail once — a test that has only ever been seen passing may not be exercising the target, or may be a tautological assertion.
- A test accompanying a bug fix must actually measure the failure before the fix — that transition is the proof the test exists (Canon 8).
- **Red before green**: write the failing test, then only enough code to pass it. Anticipating the next test
  or adding speculative shape puts implementation into the suite before anyone has observed it.
- **Vertical slice**: one failing test for one public seam → the minimal implementation that passes only that test → move to the next seam in order. Each cycle is a **tracer bullet** — it responds to what the previous one taught you. Horizontal splitting — writing a pile of layer-by-layer tests up front — pins an implementation nobody has seen yet and goes insensitive to real changes.
- Refactoring belongs to the review stage, not to this loop. Keep the red → green cycle to one seam, one test,
  one minimal implementation, and reshape afterwards.

## Assertions that can disagree with the code

An assertion that recomputes the expected value the way the code does — `expect(add(a, b)).toBe(a + b)`, a
snapshot derived by hand along the same steps, a constant asserted equal to itself — passes by construction
and can never catch a defect. Expected values come from an independent source: a known-good literal, a worked
example, the spec.

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

# Worker·Thor task → 공통 스킬 매칭 (네이티브 카탈로그 task-match 통로 — 모드 A/B는 파일 스킬이 담당).
# Worker는 모든 과업이 지나는 표면이라 과주입이 곧 노이즈다 — 트리거는 보수적으로 유지한다.
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
# 짧은 ASCII 용어는 단어 경계 필수 — 부분 일치면 latest→test, majestic→jest, debugger는 잡되
# ladybug는 제외하는 식의 통제가 불가능하다.
_WORD_RE: dict[str, tuple[str, ...]] = {
    "asgard-worker-debugging": (r"\bdebug", r"\bbugs?\b", r"\bcrash", r"\bbisect\b"),
    "asgard-worker-testing": (r"\btests?\b", r"\btesting\b", r"\btdd\b", r"\bjest\b", r"\bmock"),
}


def resolve_worker_skills(task: str) -> list[tuple[str, str]]:
    """Worker·Thor task → 매칭된 공통 스킬 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    일치 없음 = 빈 리스트 (fail-open — role 계약 기준으로 진행). 복수 매칭은 전부 주입 —
    "회귀 버그 수정 + 회귀 테스트 고정"처럼 두 표면이 한 과업인 경우가 실재한다.
    호출측은 Worker·Thor 계열 한정 — Verifier/loki는 부르지 않는다 (게이트 무결성)."""
    t = task.lower()

    def hit(name: str) -> bool:
        return any(k in t for k in _SUBSTR.get(name, ())) or any(re.search(p, t) for p in _WORD_RE.get(name, ()))

    return [(name, body.split("---", 2)[2].lstrip()) for name, body in WORKER_SKILLS if hit(name)]
