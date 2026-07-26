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
