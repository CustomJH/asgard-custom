# Asgard — this project's run commands. https://github.com/casey/just
#
# `just --list` shows every command this repository has. Recipes between the asgard markers are
# rewritten by `asgard just sync` from the checked-in manifests; everything outside them is yours
# and never rewritten. When a name collides, the recipe out here is kept and the managed one is dropped.

set shell := ["bash", "-uc"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show every command in this repository
default:
    @just --list

# >>> asgard managed recipes >>>

# Run the tests
test:
    uv run python -m pytest

# Lint the code
lint:
    uv run ruff check .

# Check formatting without writing
fmt-check:
    uv run ruff format --check .

# Check types
typecheck:
    uv run ty check

# Everything the gates run
check: fmt-check lint typecheck test

# <<< asgard managed recipes <<<

# `quality` gates the `release` job, so a red gate means the tag ships no wheel — that is how
# v0.10.15 and v0.10.16 became tags with no release. tests/test_release_gate.py keeps this recipe
# equal to .github/workflows/release.yml, so the two cannot drift apart again.

# Everything the release workflow checks before it builds — run this before you tag
gate:
    uv sync --group dev
    uv run ruff check
    uv run ruff format --check
    uv run ty check
    uv run asgard health --gate
    uv run pytest -q -n auto
