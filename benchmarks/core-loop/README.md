# Asgard core loop A/B

This benchmark compares one direct-agent command with `asgard run` on fresh copies of the same
three Git fixtures:

- a one-function correction;
- a contract change with an existing hidden caller;
- a security boundary requiring constant-time comparison.

The harness owns the tests, rejects deleted/edited test files, records wall time and tokens when
the command emits them, and reads Asgard's Quest events to report retries, replans, and verified
close rate. Results append after every run to survive interruption.

```bash
uv run python benchmarks/core-loop/harness.py --self-check

uv run python benchmarks/core-loop/harness.py \
  --control 'claude -p --model sonnet {prompt}' \
  --candidate '/absolute/path/to/asgard run --json --provider claude-native --model sonnet {prompt}' \
  --runs 3
```

Use the same underlying model and permission policy in both commands. A run count below three is a
pilot, not a product-quality claim. Passing these small fixtures measures loop overhead and repeated
failure containment; it does not establish broad coding superiority.

## What this harness cannot measure: system-prompt size

Do not use it to price a change to the injected prompt surface. Measured 2026-08-02, 18 sessions
(3 fixtures x 2 arms x 3 runs, sonnet), where the arms differed only by `ASGARD_PROMPT_LEAN` — one
carried the full identity, the other a version gated down by 4,394 tokens per turn:

- Quality was flat and clean: 9/9 versus 9/9, zero replans in either arm.
- Token and wall-clock differences flipped sign by fixture (-10.8%, +1.0%, +38.0% median tokens).
- Spread *within* one arm ran 11-120% of its own median, while the gap *between* arms ran 1-38%.

A session here spends 300-700k tokens, dominated by tool output and cache reads, so a few thousand
tokens of system prompt sits well inside the noise. Three runs cannot resolve it, and more runs buy
resolution slowly at roughly $4 per session.

Price a prompt-surface change by measuring the assembled string directly (`heimdall.roles`
`direct_identity` / `delivery_identity` plus the lagom and bragi notes) — that number is exact and
costs nothing. Then run this harness for the question it does answer: did the change break anything.
