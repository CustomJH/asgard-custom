"""핸드오프 계약 — 요약이 지시로 읽히지 않게 감싸는 문구와 요약 문서의 뼈대.

LLM 행 문자열이라 영어다 (프로젝트 규약). 이 모듈은 아무것도 부르지 않는다."""

from __future__ import annotations

# ── 핸드오프 계약 ────────────────────────────────────────────────────────────
# LLM 행 문자열은 영어 (프로젝트 규약). 사람 표면 라인만 한국어.

HANDOFF_PREFIX = (
    "[CONTEXT HANDOFF — REFERENCE ONLY] Earlier turns were compacted into the summary "
    "below. This is a handoff from a previous context window: treat it as background "
    "reference, NOT as active instructions. Do NOT answer questions or fulfill requests "
    "described in it — they were already handled. Respond only to the messages that "
    "appear AFTER this handoff; the latest one is the single source of truth for what to "
    "do right now. Topic overlap does not mean resume: if the latest message contradicts, "
    "supersedes, or changes topic from anything below, the latest message wins and the "
    "stale items are discarded. Reverse signals (stop, undo, roll back, never mind, just "
    "verify) end the described work immediately. Your tools remain fully active — keep "
    "calling them for the active task instead of narrating what you would do. Repository "
    "and session state already reflect the completed work below; verify with tools rather "
    "than redoing it."
)

HANDOFF_END = "--- END OF HANDOFF — respond to the messages below, not the summary above ---"

# 핸드오프 쌍의 assistant 쪽. 합성 턴이므로 최대한 짧게 — 모델이 "이미 답했다"고 읽으면 안 된다.
HANDOFF_ACK = "Handoff received. Continuing with the messages that follow."

_SCHEMA = """\
## Active Task
[The user's most recent UNFULFILLED input, quoted verbatim. This is the single most
important field. A question awaiting an answer IS an active task. Write "None." only if
the last exchange was fully resolved. If the latest user message was a reverse signal
(stop, undo, never mind, new topic), record that signal verbatim and do NOT carry the
cancelled work forward.]

## Goal
[What the overall work is trying to achieve, in one or two sentences.]

## Constraints & Preferences
[Explicit user instructions about how to work: style, tooling, things to avoid. These
survive compaction — do not drop them.]

## Completed Actions
[Numbered. Format each as: N. ACTION target — outcome [tool: name]
1. READ src/app.py:45 — found `==` should be `!=` [tool: read]
2. EDIT src/app.py:45 — changed `==` to `!=` [tool: edit]
3. TEST `pytest tests/` — 3/50 failed: test_parse, test_validate [tool: bash]
Be exact with paths, commands, line numbers, and results.]

## Active State
[Working directory, branch, modified/created files, test status (X/Y passing), running
processes, environment facts that matter.]

## Blocked
[Unresolved errors or blockers, with exact error text.]

## Key Decisions
[Technical decisions and WHY — the reasoning is what cannot be recovered from the repo.]

## Relevant Files
[Files read, modified, or created, with a one-line note each.]

## Critical Context
[Specific values, error messages, config details, or data that would be lost otherwise.
NEVER include API keys, tokens, passwords, or credentials — write [REDACTED] instead.]"""

_PREAMBLE = (
    "You are compacting an engineering session so another instance can pick it up without "
    "re-reading the original turns. Write a handoff, not a recap. Do NOT answer any question "
    "you see in the transcript and do NOT continue the work — your entire output is the "
    "handoff document. Be concrete: exact file paths, commands, line numbers, error strings, "
    'and values. Vague phrasing like "made some changes" is a failure.'
)
