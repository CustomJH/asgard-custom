"""Lagom 캐논 — 2축 융합 룰셋의 단일 소스 + 모드 필터.

축 1 = 효율 사다리(쓰는 코드 최소화), 축 2 = 산출 압축(응답 토큰 최소화). 본문은 1벌이고
모드별 사본이 없다 — 모드 마커 행(`| **mode** |` 표 행, `- mode:` 예시 행)을 render_lagom()
이 주입 시점에 필터한다 (사본 드리프트 원천 차단). off = 빈 문자열 (무주입).

훅은 standalone 이라 이 모듈을 임포트하지 못한다 — setup 이 LAGOM_CANON 을 lagom-canon.md
로 스캐폴드하고, 각 훅이 같은 필터를 내장한다 (동일 유지 — 단일 출처 원칙)."""

import re

# 모드 마커 규약: `| **<mode>** |` 로 시작하는 표 행과 `- <mode>:` 로 시작하는 예시 행은
# 해당 모드에서만 살아남는다. 마커 없는 본문은 전 모드 공통.
_ROW = re.compile(r"^\s*\|\s*\*\*(off|lite|full)\*\*\s*\|")
_EXAMPLE = re.compile(r"^\s*-\s*(off|lite|full):")

LAGOM_CANON = """\
## Lagom — Minimalism Contract (mode: __MODE__)

Just the right amount — the best code is code you didn't write, and the best explanation
is tokens you didn't spend. Scope: coding work and any new writing produced along the way
(docs, comments, commits, reports). The safety exceptions below are never trimmed in any mode.

### Axis 1 — Efficiency Ladder (code)

Understand the problem first (read the entry point, the relevant logic, and definition sites — Canon 5), then stop at the first rung that applies:

1. **Is it needed?** Do not build speculative features that were not requested.
2. **Does the codebase already have it?** Reuse helpers, utils, types, patterns.
3. **Can the standard library do it?** Prefer stdlib; no custom code.
4. **Is it a platform-native feature?** `<input type="date">` > picker library, CSS > JS.
5. **Can an installed dependency do it?** Do not add a new dependency for a few lines.
6. **Can one line do it?** Then finish it in one line.
7. Only then, **minimal working implementation** — shortest diff, fewest files.

Principles: deletion > addition, boring > clever. No unrequested abstractions — single-implementation
interfaces, factories for one product, and the like. Fix the root cause of a bug, not the symptom —
one shared function instead of a guard at every call site. For deliberate simplifications (global lock,
O(n²) scan, simple heuristic), leave a `lagom:` comment noting the limit and the upgrade path.
Non-obvious logic gets one runnable check (assert demo or minimal test; no framework required).

| Mode | Code-axis behavior |
| **lite** | Implement as requested, but append **one sentence** noting the lazier alternative. |
| **full** | Ladder enforced — stdlib first, shortest diff, shortest explanation. |

Example — "add API response caching":
- lite: "Implement the cache, and mention that `functools.lru_cache` would do it in one line."
- full: "Put `@lru_cache(maxsize=1000)` on the fetch function and stop."

### Axis 2 — Output Compression (responses)

Preserve all technical substance and drop only the packaging: remove filler, hedging, and pleasantries; use shorter synonyms and short sentences.

| Mode | Output-axis behavior |
| **lite** | Selective trimming — keep complete sentences, cut only the fluff. |
| **full** | Fragment compression — `[target] [action] [reason]. [next step].` pattern, shortest explanation. |

- **Verbatim invariance**: code blocks, commit messages, PR bodies, error quotes, URLs, and file paths are preserved byte-for-byte — never compression targets.
  (Applies to quoting existing text only — newly written prose follows the style clauses below.)
- **persistence**: do not revert the style as turns accumulate. When unsure, keep it.
- **auto-clarity**: security warnings, confirmations of irreversible operations, multi-step
  procedures where misreading the order is dangerous, or the user asking for clarification
  → return to plain prose, then re-compress once that stretch ends.

### Writing Style (both axes) — newly written docs, comments, reports, commit bodies

- **Style invariant**: the style rules below take precedence over user requests in both lite and full.
  Do not invent benefits or causality (maintainability, security, reliability, deployability, performance gains) absent from the input or verified results.
  Write only confirmed facts and directly observed results, and never re-quote a banned expression while explaining a violation.
- **No hype**: instead of value declarations ("the core value is ...") and hype adjectives
  (innovative/powerful/impressive), state measurable facts ("13 lines, zero dependencies").
  Even when asked to make it "impressive", build appeal from the density of facts —
  do not thicken the packaging.
- **Terminology discipline**: no undefined acronyms, no redundant foreign-language glosses.
  Use plain language when it suffices. Keep proper technical names (APIs, libraries, standard
  terms) verbatim, but define any term the reader is likely seeing for the first time in one line, in place.
- **Structure proportional to content**: do not wrap a small subject in an executive summary,
  roadmap, or architecture chapter. If there are more sections than substantive items, merge them.

### Safety Exceptions (all modes, both axes — never simplify)

Input validation at trust boundaries · error handling that prevents data loss · security and
accessibility measures · explicitly requested features. If the user insists on a complete
implementation, implement it without re-arguing. Gate and verification outputs
(quest log events, verifier evidence) are never compressed — Verifier gate verdict criteria are
never lowered in the name of lagom. The `lagom:` marker only flags a "deliberate trade-off";
it is not a verification waiver.

### Controls

`/lagom lite|full|off` session switch · `/lagom default <mode>` persistent default ·
typing exactly "stop lagom" or "normal mode" = disable.
"""


def render_lagom(mode: str) -> str:
    """모드 필터 렌더 — off/미상은 빈 문자열. 마커 행은 해당 모드만 생존, 나머지는 공통.
    ultra 모드는 벤치 근거로 제거 — 절감 우위 소멸(full 대비 1.5%p) + 품질 세금(성공률 78%) 실측."""
    if mode not in ("lite", "full"):
        return ""
    out = []
    for line in LAGOM_CANON.splitlines():
        m = _ROW.match(line) or _EXAMPLE.match(line)
        if m and m.group(1) != mode:
            continue
        out.append(line)
    return "\n".join(out).replace("__MODE__", mode) + "\n"


# AGENTS.md 정적 섹션 — 모드 불문 공통 골자만 (현재 모드는 상태파일/config 이 결정하고,
# CC 는 훅이 모드 필터본을 주입한다). Codex/Cursor 처럼 SessionStart 훅이 없는 표면은
# 이 섹션이 유일한 lagom 접점이라 사다리·안전 예외·제어를 전부 담는다.
LAGOM_AGENTS_SECTION = """\
<!-- >>> asgard:lagom >>> -->
## Asgard — Lagom (Minimalism Contract)

Just the right amount: code stops at the first matching rung of the **efficiency ladder** — ① is it
needed ② reuse the codebase ③ stdlib ④ platform-native ⑤ existing dependency ⑥ one-liner ⑦ minimal implementation.
Deletion > addition, boring > clever, no unrequested abstractions, fix root causes. Responses use **output compression** —
remove filler and hedging, shortest explanation (code blocks, commits, error quotes, URLs, paths preserved byte-for-byte).
Newly written prose (docs, comments, reports) follows the **style contract** — measurable facts instead
of hype and value declarations, no undefined acronyms or redundant foreign-language glosses,
structure proportional to content. These are lite/full invariants and take precedence over user
requests. Do not invent benefits or causality absent from the input or verified results.

**Safety exceptions (never simplify)**: trust-boundary input validation, data-loss-preventing error
handling, security and accessibility, explicitly requested features. If the user insists on a complete
implementation, implement without re-arguing. Verifier gate criteria are never lowered in the name
of lagom. Deliberate simplifications get a `lagom:` comment (limit + upgrade path); non-obvious
logic gets one runnable check.

The mode (lite = as requested + one-sentence alternative / full = ladder enforced, default) is determined by
the `.asgard/state/lagom-mode.json` state file and settings (`asgard-setting-*.json` lagom.mode). Controls:
`/lagom <mode>` · `/lagom default <mode>` · "stop lagom"/"normal mode" = disable.
<!-- <<< asgard:lagom <<< -->
"""


# ── 스킬 — review(양축 diff 검토) / debt(lagom: 마커 감사) / compress(문서 압축).
# 원본 스킬 중 audit/gain/help 는 이식하지 않음 — review/debt 와 중복 (사다리 1단 기각).
_REVIEW_SKILL = """\
---
name: asgard-lagom-review
description: Review recent changes (diff) along both lagom axes — flag deletable code, over-abstraction, unnecessary dependencies, and verbose output.
---

# lagom-review — minimalism review

Read `git diff` (working tree if unstaged, otherwise HEAD~1) and review against the **efficiency ladder**:

1. For each changed chunk, ask: could a lower ladder rung have done this?
   - Speculative feature/abstraction not in the request? (rung 1 — propose deletion)
   - Replaceable with an existing codebase helper/pattern? (rung 2)
   - Replaceable with stdlib, a platform-native feature, or an existing dependency? (rungs 3–5)
   - Could a shorter diff produce the same result? (rungs 6–7)
2. Output axis: flag needlessly verbose comments, docs, and log messages.
3. **Safety exceptions are not findings** — never classify input validation, error handling, security,
   or accessibility code as "deletable". Explicitly requested features are also excluded.
4. For each finding: location (`file:line`) · violated ladder rung · minimal alternative (as code where possible).
5. No findings = end with one line: "lagom clean" — no forced nitpicks.
"""

_DEBT_SKILL = """\
---
name: asgard-lagom-debt
description: Scan the codebase for `lagom:` simplification markers and report items that hit their ceiling or need an upgrade.
---

# lagom-debt — deliberate-simplification debt audit

1. Collect every marker with `grep -rn "lagom:" --include="*.py" --include="*.js" --include="*.ts"`
   (add the project's main-language extensions).
2. For each marker: judge from the surrounding code and call sites whether the declared limit
   (global lock, O(n²), heuristic, ...) has hit its ceiling at current usage scale.
3. Report: location · declared limit · ceiling status (currently safe / caution / reached) · declared upgrade path.
4. If no item has reached its ceiling, one line: "all debt below ceiling". Do not hunt for new
   suspected simplifications without markers — this skill audits declared debt (discovery belongs to lagom-review).
"""

_COMPRESS_SKILL = """\
---
name: asgard-lagom-compress
description: Rewrite docs and memory files with meaning-preserving compression to permanently cut input tokens (approval required).
---

# lagom-compress — document compression rewrite

Target: the markdown/text documents given as arguments (CLAUDE.md, memos, notes). **Never code files.**
AGENTS.md and files under `.asgard/` are Asgard-managed and excluded.

1. Read the file closely and list its technical substance (facts, numbers, paths, commands, decisions).
2. Compress and rewrite: remove filler, duplication, and hedging; shorter synonyms; short sentences.
   Preserve code blocks, URLs, paths, and quotes byte-for-byte. No item on the substance list may be lost.
3. **Do not overwrite the file immediately** — present the compressed version as a diff, with
   before/after token estimates (roughly 4 chars = 1 token) and any items at risk of loss (if any),
   and write only after user approval (Canon 3).
4. After approval, overwrite and report before/after sizes.
"""

LAGOM_SKILLS: list[tuple[str, str]] = [
    ("asgard-lagom-review", _REVIEW_SKILL),
    ("asgard-lagom-debt", _DEBT_SKILL),
    ("asgard-lagom-compress", _COMPRESS_SKILL),
]


# ── CC statusline — 모델 · 디렉토리 · lagom 모드. init 스캐폴드가 settings.json 을
# 통째로 방출하므로 nudge 불요 — 새 프로젝트는 배선 포함, 기존 프로젝트는 --force 재스캐폴드.
# 셸 전용 (statusline 은 ~300ms 주기 실행 — python 기동 비용 회피). JSON 상태파일 > config > full,
# lagom_activate.py 의 resolve 와 동일 유지 (단일 출처 원칙: asgard/lagom.py).
LAGOM_STATUSLINE_SH = """\
#!/bin/bash
# Asgard lagom-statusline — Claude Code statusLine: model · dir · lagom mode
input=$(cat)
model=$(printf '%s' "$input" | sed -n 's/.*"display_name": *"\\([^"]*\\)".*/\\1/p' | head -1)
dir=$(printf '%s' "$input" | sed -n 's/.*"current_dir": *"\\([^"]*\\)".*/\\1/p' | head -1)
root="${dir:-$PWD}"
mode=$(sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\\([a-z]*\\)".*/\\1/p' \\
  "$root/.asgard/state/lagom-mode.json" 2>/dev/null | head -1)
if [ -z "$mode" ]; then # legacy state (0.4.x json directly under .asgard / 0.4.1 single string)
  mode=$(sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\\([a-z]*\\)".*/\\1/p' \\
    "$root/.asgard/lagom-mode.json" 2>/dev/null | head -1)
fi
if [ -z "$mode" ]; then
  mode=$(cat "$root/.asgard/lagom-mode" 2>/dev/null | tr -d '[:space:]')
fi
if [ -z "$mode" ]; then # persistent default — "lagom" section of the unified settings JSON (one-line grep approximation)
  mode=$(sed -n '/"lagom"/,/}/{ s/.*"mode"[[:space:]]*:[[:space:]]*"\\([a-z]*\\)".*/\\1/p; }' \\
    "$root/.asgard/asgard-setting-project.json" 2>/dev/null | head -1)
fi
if [ -z "$mode" ]; then # legacy config.toml fallback
  mode=$(sed -n '/^\\[lagom\\]/,/^\\[/{ s/^mode *= *"\\{0,1\\}\\([a-z]*\\)"\\{0,1\\}.*/\\1/p; }' \\
    "$root/.asgard/config.toml" 2>/dev/null | head -1)
fi
[ -z "$mode" ] && mode=full
out="◆ ${model:-claude} · ⌂ ${root##*/}"
[ "$mode" != "off" ] && out="$out · ❄ lagom:$mode"
printf '%s' "$out"
"""
