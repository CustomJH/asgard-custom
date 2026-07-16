#!/usr/bin/env bash
# Shared host runtime. install.sh bootstraps uv; every Python helper then runs
# on uv-managed CPython instead of the host's legacy system Python.
ASGARD_MEMORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
command -v uv >/dev/null || {
  echo "uv is required; run $ASGARD_MEMORY_ROOT/install.sh" >&2
  exit 1
}
run_python() {
  uv run --project "$ASGARD_MEMORY_ROOT" python "$@"
}
