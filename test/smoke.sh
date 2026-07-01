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

asgard --help | grep -q "asgard — make anything, your way" || { echo "FAIL: --help missing banner"; exit 1; }
asgard --help | grep -q "doctor" || { echo "FAIL: --help missing command list"; exit 1; }
asgard version | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "FAIL: 'version' subcommand"; exit 1; }
asgard run | grep -qi "planned" || { echo "FAIL: planned command not announced"; exit 1; }
asgard run >/dev/null || { echo "FAIL: planned command should exit 0"; exit 1; }
asgard completions bash | grep -q "complete -F _asgard asgard" || { echo "FAIL: bash completions"; exit 1; }
asgard completions zsh | grep -q "#compdef asgard" || { echo "FAIL: zsh completions"; exit 1; }
asgard completions fish | grep -q "complete -c asgard" || { echo "FAIL: fish completions"; exit 1; }
if asgard completions badshell >/dev/null 2>&1; then echo "FAIL: bad shell should exit nonzero"; exit 1; fi

asgard doctor >/dev/null || { echo "FAIL: doctor exit nonzero (asgard should be on PATH)"; exit 1; }
asgard doctor --json | grep -q '"ok": true' || { echo "FAIL: doctor --json ok"; exit 1; }

if asgard bogus >/dev/null 2>&1; then echo "FAIL: unknown command should exit nonzero"; exit 1; fi

# setup (universal AGENTS.md) — codex/claude-code/cursor 공용
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --dry-run | grep -q "AGENTS.md" ) || { echo "FAIL: setup --dry-run"; exit 1; }
[ ! -e "$PROJ/AGENTS.md" ] || { echo "FAIL: dry-run must not create"; exit 1; }
( cd "$PROJ" && asgard setup >/dev/null ) || { echo "FAIL: setup"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] || { echo "FAIL: AGENTS.md missing"; exit 1; }
[ -f "$PROJ/.claude/CLAUDE.md" ] || { echo "FAIL: .claude/CLAUDE.md missing"; exit 1; }
[ ! -e "$PROJ/CLAUDE.md" ] || { echo "FAIL: CLAUDE.md must be inside .claude, not root"; exit 1; }
grep -q "@../AGENTS.md" "$PROJ/.claude/CLAUDE.md" || { echo "FAIL: .claude/CLAUDE.md must import ../AGENTS.md"; exit 1; }
rm -rf "$PROJ"

# setup --cc (claude-code) == init — .claude/
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --cc >/dev/null ) || { echo "FAIL: setup --cc"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.claude/CLAUDE.md" ] || { echo "FAIL: --cc files"; exit 1; }
[ ! -e "$PROJ/AGENTS.md" ] || { echo "FAIL: --cc must not create AGENTS.md"; exit 1; }
if ( cd "$PROJ" && asgard init >/dev/null 2>&1 ); then echo "FAIL: init must refuse existing .claude"; exit 1; fi
( cd "$PROJ" && asgard init --force >/dev/null ) || { echo "FAIL: init --force"; exit 1; }
rm -rf "$PROJ"

# setup --cursor — .cursor/rules/
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --cursor >/dev/null ) || { echo "FAIL: setup --cursor"; exit 1; }
[ -f "$PROJ/.cursor/rules/asgard.mdc" ] || { echo "FAIL: cursor rule missing"; exit 1; }
rm -rf "$PROJ"

# setup --codex — AGENTS.md (no CLAUDE.md bridge)
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --codex >/dev/null ) || { echo "FAIL: setup --codex"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] && [ ! -e "$PROJ/CLAUDE.md" ] || { echo "FAIL: codex files"; exit 1; }
rm -rf "$PROJ"

# combined — --cc --cursor installs both
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --cc --cursor >/dev/null ) || { echo "FAIL: setup --cc --cursor"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.cursor/rules/asgard.mdc" ] || { echo "FAIL: combined files"; exit 1; }
rm -rf "$PROJ"

# upgrade — dry-run only (no network in smoke)
asgard upgrade --dry-run | grep -q "would download" || { echo "FAIL: upgrade --dry-run"; exit 1; }

# uninstall LAST (destructive) — preview is a no-op, then --yes cleanly removes
asgard uninstall | grep -qi "would remove" || { echo "FAIL: uninstall preview"; exit 1; }
[ -e "$BIN_DIR/asgard" ] || { echo "FAIL: preview must not remove"; exit 1; }
asgard uninstall --yes >/dev/null || { echo "FAIL: uninstall --yes"; exit 1; }
[ ! -e "$BIN_DIR/asgard" ] || { echo "FAIL: symlink remains after uninstall"; exit 1; }
[ ! -d "$ASGARD_HOME" ] || { echo "FAIL: ASGARD_HOME remains after uninstall"; exit 1; }

echo "PASS: build+install + version($ver) + help + doctor + completions + init + upgrade + uninstall"
