#!/usr/bin/env bash
# Smoke test — the money path: build+install the self-contained binary into a temp prefix,
# put it on PATH, then the basic commands work. Fails loud if anything breaks. No framework.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export ASGARD_HOME="$TMP/.asgard"
export BIN_DIR="$TMP/bin"
export ASGARD_NO_RC=1        # don't touch the real ~/.zshrc during the main test (rc round-trip tested separately)
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
grep -q "ASGARD_OK" "$PROJ/AGENTS.md" || { echo "FAIL: AGENTS.md missing wiring-check marker"; exit 1; }
# cursor bridge — always-apply rule pointing at AGENTS.md
[ -f "$PROJ/.cursor/rules/000-agents.mdc" ] || { echo "FAIL: .cursor/rules/000-agents.mdc missing"; exit 1; }
grep -q "alwaysApply: true" "$PROJ/.cursor/rules/000-agents.mdc" || { echo "FAIL: cursor rule must alwaysApply"; exit 1; }
grep -q "AGENTS.md" "$PROJ/.cursor/rules/000-agents.mdc" || { echo "FAIL: cursor rule must reference AGENTS.md"; exit 1; }
rm -rf "$PROJ"

# setup --cc (claude-code) == init — AGENTS.md (canonical) + .claude/ (bridge + real config)
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --cc >/dev/null ) || { echo "FAIL: setup --cc"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] || { echo "FAIL: --cc must create AGENTS.md"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.claude/CLAUDE.md" ] || { echo "FAIL: --cc files"; exit 1; }
grep -q "@../AGENTS.md" "$PROJ/.claude/CLAUDE.md" || { echo "FAIL: --cc .claude/CLAUDE.md must import ../AGENTS.md"; exit 1; }
grep -q "ASGARD_OK" "$PROJ/AGENTS.md" || { echo "FAIL: --cc AGENTS.md missing wiring-check marker"; exit 1; }
# settings.json is real (not empty {}) — valid JSON with a permissions floor
python3 -c "import json,sys; d=json.load(open('$PROJ/.claude/settings.json')); sys.exit(0 if d.get('permissions',{}).get('deny') else 1)" || { echo "FAIL: --cc settings.json must have permissions"; exit 1; }
[ -f "$PROJ/.claude/.gitignore" ] && grep -q "settings.local.json" "$PROJ/.claude/.gitignore" || { echo "FAIL: --cc .claude/.gitignore must ignore settings.local.json"; exit 1; }
# foundational .claude/ folder skeleton (README in each so git tracks it)
for _d in commands agents skills hooks rules output-styles; do
  [ -f "$PROJ/.claude/$_d/README.md" ] || { echo "FAIL: --cc missing .claude/$_d/README.md"; exit 1; }
done
if ( cd "$PROJ" && asgard init >/dev/null 2>&1 ); then echo "FAIL: init must refuse existing .claude"; exit 1; fi
( cd "$PROJ" && asgard init --force >/dev/null ) || { echo "FAIL: init --force"; exit 1; }
rm -rf "$PROJ"

# setup --cursor — .cursor/ skeleton (rules bridge base + skills/ + hooks/)
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --cursor >/dev/null ) || { echo "FAIL: setup --cursor"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] || { echo "FAIL: --cursor must create AGENTS.md"; exit 1; }
[ -f "$PROJ/.cursor/rules/000-agents.mdc" ] || { echo "FAIL: --cursor rules bridge missing"; exit 1; }
for _d in skills hooks; do
  [ -f "$PROJ/.cursor/$_d/README.md" ] || { echo "FAIL: --cursor missing .cursor/$_d/README.md"; exit 1; }
done
rm -rf "$PROJ"

# setup --codex — .codex/config.toml (root AGENTS.md native; only per-project config surface)
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --codex >/dev/null ) || { echo "FAIL: setup --codex"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] || { echo "FAIL: --codex must create AGENTS.md"; exit 1; }
[ -f "$PROJ/.codex/config.toml" ] || { echo "FAIL: --codex missing .codex/config.toml"; exit 1; }
grep -q "config-reference" "$PROJ/.codex/config.toml" || { echo "FAIL: --codex config.toml missing docs pointer"; exit 1; }
rm -rf "$PROJ"

# combined --cc --cursor --codex — all skeletons in one project
PROJ="$(mktemp -d)"
( cd "$PROJ" && asgard setup --cc --cursor --codex >/dev/null ) || { echo "FAIL: setup combined"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.cursor/skills/README.md" ] && [ -f "$PROJ/.codex/config.toml" ] || { echo "FAIL: combined skeletons"; exit 1; }
rm -rf "$PROJ"

# upgrade — dry-run only (no network in smoke)
asgard upgrade --dry-run | grep -q "would download" || { echo "FAIL: upgrade --dry-run"; exit 1; }

# rc round-trip — install adds a guarded PATH block to the shell rc; uninstall removes it
RCH="$(mktemp -d)"; touch "$RCH/.zshrc"
HOME="$RCH" SHELL=/bin/zsh ASGARD_HOME="$RCH/.asgard" BIN_DIR="$RCH/bin" ASGARD_NO_RC=0 bash "$REPO/install.sh" >/dev/null
grep -q ">>> asgard >>>" "$RCH/.zshrc" || { echo "FAIL: install did not add PATH block to rc"; exit 1; }
HOME="$RCH" ASGARD_HOME="$RCH/.asgard" BIN_DIR="$RCH/bin" "$RCH/bin/asgard" uninstall --yes >/dev/null
grep -q ">>> asgard >>>" "$RCH/.zshrc" && { echo "FAIL: uninstall did not clean rc"; exit 1; }
rm -rf "$RCH"

# uninstall LAST (destructive) — preview is a no-op, then --yes cleanly removes
asgard uninstall | grep -qi "would remove" || { echo "FAIL: uninstall preview"; exit 1; }
[ -e "$BIN_DIR/asgard" ] || { echo "FAIL: preview must not remove"; exit 1; }
asgard uninstall --yes >/dev/null || { echo "FAIL: uninstall --yes"; exit 1; }
[ ! -e "$BIN_DIR/asgard" ] || { echo "FAIL: symlink remains after uninstall"; exit 1; }
[ ! -d "$ASGARD_HOME" ] || { echo "FAIL: ASGARD_HOME remains after uninstall"; exit 1; }

echo "PASS: build+install + version($ver) + help + doctor + completions + init + upgrade + uninstall"
