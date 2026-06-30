#!/usr/bin/env bash
# Smoke test — the money path: build+install the self-contained binary into a temp prefix,
# put it on PATH, then the basic commands work. Fails loud if anything breaks. No framework.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export ASGARD_HOME="$TMP/.asgard"
export BIN_DIR="$TMP/bin"
unset ASGARD_DOWNLOAD_URL   # force local bun build from this checkout

bash "$REPO/install.sh" >/dev/null
export PATH="$BIN_DIR:$PATH"   # mirror what a user adds to their shell rc

command -v asgard >/dev/null || { echo "FAIL: asgard not on PATH after install"; exit 1; }

ver="$(asgard --version)"
echo "$ver" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "FAIL: --version => '$ver'"; exit 1; }
[ "$ver" != "0.0.0" ] || { echo "FAIL: version embedded as 0.0.0 (package.json not bundled)"; exit 1; }

asgard --help | grep -q "asgard — Claude Code harness" || { echo "FAIL: --help missing banner"; exit 1; }
asgard --help | grep -q "doctor" || { echo "FAIL: --help missing command list"; exit 1; }
asgard version | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "FAIL: 'version' subcommand"; exit 1; }
asgard setup | grep -qi "planned" || { echo "FAIL: planned command not announced"; exit 1; }
asgard setup >/dev/null || { echo "FAIL: planned command should exit 0"; exit 1; }
asgard completions bash | grep -q "complete -F _asgard asgard" || { echo "FAIL: bash completions"; exit 1; }
asgard completions zsh | grep -q "#compdef asgard" || { echo "FAIL: zsh completions"; exit 1; }
asgard completions fish | grep -q "complete -c asgard" || { echo "FAIL: fish completions"; exit 1; }
if asgard completions badshell >/dev/null 2>&1; then echo "FAIL: bad shell should exit nonzero"; exit 1; fi

asgard doctor >/dev/null || { echo "FAIL: doctor exit nonzero (asgard should be on PATH)"; exit 1; }
asgard doctor --json | grep -q '"ok": true' || { echo "FAIL: doctor --json ok"; exit 1; }

if asgard bogus >/dev/null 2>&1; then echo "FAIL: unknown command should exit nonzero"; exit 1; fi

echo "PASS: build+install + version($ver) + help + doctor + unknown-cmd"
