#!/usr/bin/env bash
# Smoke test — the money path: install the Python CLI as a uv tool into a temp prefix, put it on PATH,
# then the basic commands work; and every scaffold/guard assertion. Fails loud. No framework.
# CUS-108 Path B: no compile — `uv tool install <repo>` + `uv run --project <repo> asgard` for speed.
# No `pipefail`: `cmd | grep -q` closes the pipe early → the Python producer gets SIGPIPE (exit 141),
# which pipefail would propagate as a false failure. `set -eu` is enough here.
set -eu

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ── money path: install as a uv tool into an isolated prefix, verify it lands on PATH ──
export UV_TOOL_DIR="$TMP/uvtools" UV_TOOL_BIN_DIR="$TMP/uvbin"
uv tool install --python 3.14 --refresh-package asgard "$REPO" >/dev/null 2>&1 || { echo "FAIL: uv tool install"; exit 1; }
export PATH="$UV_TOOL_BIN_DIR:$PATH"
command -v asgard >/dev/null || { echo "FAIL: asgard not on PATH after uv tool install"; exit 1; }

# Assertions run the actual installed CLI on PATH.
ASG=(asgard)

ver="$(asgard --version)"
echo "$ver" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "FAIL: --version => '$ver'"; exit 1; }
[ "$ver" != "0.0.0" ] || { echo "FAIL: version reported as 0.0.0"; exit 1; }

"${ASG[@]}" --help | grep -q "asgard — make anything, your way" || { echo "FAIL: --help missing tagline"; exit 1; }
"${ASG[@]}" --help | grep -q "doctor" || { echo "FAIL: --help missing command list"; exit 1; }
"${ASG[@]}" version | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "FAIL: 'version' subcommand"; exit 1; }
"${ASG[@]}" run | grep -qi "planned" || { echo "FAIL: planned command not announced"; exit 1; }
"${ASG[@]}" run >/dev/null || { echo "FAIL: planned command should exit 0"; exit 1; }
"${ASG[@]}" completions bash | grep -q "complete -F _asgard asgard" || { echo "FAIL: bash completions"; exit 1; }
"${ASG[@]}" completions zsh | grep -q "#compdef asgard" || { echo "FAIL: zsh completions"; exit 1; }
"${ASG[@]}" completions fish | grep -q "complete -c asgard" || { echo "FAIL: fish completions"; exit 1; }
if "${ASG[@]}" completions badshell >/dev/null 2>&1; then echo "FAIL: bad shell should exit nonzero"; exit 1; fi

asgard doctor >/dev/null || { echo "FAIL: doctor exit nonzero (asgard on PATH)"; exit 1; }
asgard doctor --json | grep -q '"ok": true' || { echo "FAIL: doctor --json ok"; exit 1; }
if "${ASG[@]}" bogus >/dev/null 2>&1; then echo "FAIL: unknown command should exit nonzero"; exit 1; fi

# ── init --profile universal — codex/claude-code/cursor 공용 ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --profile universal --dry-run | grep -q "AGENTS.md" ) || { echo "FAIL: init universal --dry-run"; exit 1; }
[ ! -e "$PROJ/AGENTS.md" ] || { echo "FAIL: dry-run must not create"; exit 1; }
( cd "$PROJ" && "${ASG[@]}" init --profile universal >/dev/null ) || { echo "FAIL: init universal"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] || { echo "FAIL: AGENTS.md missing"; exit 1; }
[ -f "$PROJ/.claude/CLAUDE.md" ] || { echo "FAIL: .claude/CLAUDE.md missing"; exit 1; }
[ ! -e "$PROJ/CLAUDE.md" ] || { echo "FAIL: CLAUDE.md must be inside .claude, not root"; exit 1; }
grep -q "@../AGENTS.md" "$PROJ/.claude/CLAUDE.md" || { echo "FAIL: .claude/CLAUDE.md must import ../AGENTS.md"; exit 1; }
grep -q "ASGARD_OK" "$PROJ/AGENTS.md" || { echo "FAIL: AGENTS.md missing wiring-check marker"; exit 1; }
grep -q "asgard:identity" "$PROJ/AGENTS.md" && grep -q "Heimdall" "$PROJ/AGENTS.md" || { echo "FAIL: AGENTS.md missing asgard:identity block"; exit 1; }
grep -q "asgard:law" "$PROJ/AGENTS.md" && grep -q "3회 실패 법칙" "$PROJ/AGENTS.md" || { echo "FAIL: AGENTS.md missing asgard:law block"; exit 1; }
[ -f "$PROJ/.cursor/rules/000-agents.mdc" ] || { echo "FAIL: .cursor/rules/000-agents.mdc missing"; exit 1; }
grep -q "alwaysApply: true" "$PROJ/.cursor/rules/000-agents.mdc" || { echo "FAIL: cursor rule must alwaysApply"; exit 1; }
# universal must ENFORCE, not just bridge prose — every tool's hooks/config present
[ -f "$PROJ/.claude/settings.json" ] || { echo "FAIL: universal missing .claude/settings.json (no hook wiring)"; exit 1; }
grep -q '"PostToolUse"' "$PROJ/.claude/settings.json" || { echo "FAIL: universal .claude missing PostToolUse wiring"; exit 1; }
[ -f "$PROJ/.claude/hooks/git-guard.py" ] && [ -f "$PROJ/.claude/hooks/failure-tracker.py" ] || { echo "FAIL: universal missing .claude guards"; exit 1; }
[ -f "$PROJ/.cursor/hooks.json" ] && [ -f "$PROJ/.cursor/hooks/git-guard.py" ] || { echo "FAIL: universal missing .cursor guard"; exit 1; }
[ -f "$PROJ/.codex/config.toml" ] && [ -f "$PROJ/.codex/rules/canon.rules" ] || { echo "FAIL: universal missing .codex config/rules"; exit 1; }
# cross-tool continuity — failure-tracker (Law 9) wired in ALL three, sharing root .asgard/ state
[ -f "$PROJ/.codex/hooks/failure-tracker.py" ] && [ -f "$PROJ/.cursor/hooks/failure-tracker.py" ] || { echo "FAIL: universal missing codex/cursor failure-tracker"; exit 1; }
grep -q "PostToolUse" "$PROJ/.codex/config.toml" || { echo "FAIL: codex config missing PostToolUse tracker"; exit 1; }
grep -q "postToolUseFailure" "$PROJ/.cursor/hooks.json" || { echo "FAIL: cursor hooks missing postToolUseFailure"; exit 1; }
python3 -m py_compile "$PROJ/.codex/hooks/failure-tracker.py" "$PROJ/.cursor/hooks/failure-tracker.py" || { echo "FAIL: cross-tool trackers invalid Python"; exit 1; }
rm -rf "$PROJ"

# ── init --cc — AGENTS.md + full .claude/ (bridge + config + Python guards) ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --cc >/dev/null ) || { echo "FAIL: init --cc"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] || { echo "FAIL: --cc must create AGENTS.md"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.claude/CLAUDE.md" ] || { echo "FAIL: --cc files"; exit 1; }
python3 -c "import json,sys; d=json.load(open('$PROJ/.claude/settings.json')); sys.exit(0 if d.get('permissions',{}).get('deny') else 1)" || { echo "FAIL: --cc settings.json permissions"; exit 1; }
[ -f "$PROJ/.claude/.gitignore" ] && grep -q "settings.local.json" "$PROJ/.claude/.gitignore" || { echo "FAIL: --cc .gitignore"; exit 1; }
for _d in commands agents skills hooks rules output-styles; do
  [ -f "$PROJ/.claude/$_d/README.md" ] || { echo "FAIL: --cc missing .claude/$_d/README.md"; exit 1; }
done
[ ! -e "$PROJ/.cursor" ] || { echo "FAIL: --cc must NOT create .cursor"; exit 1; }
# Canon guards (Python) — block danger, allow safe, fail-open on garbage
grep -q '"PreToolUse"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing hooks"; exit 1; }
[ -f "$PROJ/.claude/hooks/git-guard.py" ] && [ -f "$PROJ/.claude/hooks/secret-guard.py" ] || { echo "FAIL: --cc missing Python guards"; exit 1; }
python3 -m py_compile "$PROJ/.claude/hooks/git-guard.py" "$PROJ/.claude/hooks/secret-guard.py" || { echo "FAIL: guards invalid Python"; exit 1; }
printf '%s' '{"tool_input":{"command":"git push --force"}}' | python3 "$PROJ/.claude/hooks/git-guard.py" 2>/dev/null && { echo "FAIL: git-guard must block force-push"; exit 1; } || true
printf '%s' '{"tool_input":{"command":"git status"}}'      | python3 "$PROJ/.claude/hooks/git-guard.py" 2>/dev/null || { echo "FAIL: git-guard must allow git status"; exit 1; }
printf '%s' 'not-json'                                      | python3 "$PROJ/.claude/hooks/git-guard.py" 2>/dev/null || { echo "FAIL: git-guard must fail-open"; exit 1; }
printf '%s' '{"tool_input":{"file_path":"x/.env","content":"A=1"}}' | python3 "$PROJ/.claude/hooks/secret-guard.py" 2>/dev/null && { echo "FAIL: secret-guard must block .env"; exit 1; } || true
# Canon Law 9 failure-tracker (PostToolUse) — soft 3-strike warn, normalized signature, fail-open
grep -q '"PostToolUse"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing PostToolUse"; exit 1; }
[ -f "$PROJ/.claude/hooks/failure-tracker.py" ] || { echo "FAIL: --cc missing failure-tracker.py"; exit 1; }
python3 -m py_compile "$PROJ/.claude/hooks/failure-tracker.py" || { echo "FAIL: failure-tracker invalid Python"; exit 1; }
_FT="$PROJ/.claude/hooks/failure-tracker.py"
_FAIL='{"tool_name":"Bash","session_id":"smoke","tool_response":{"is_error":true,"error":"cannot open /p/a1: e1"}}'
for _i in 1 2; do printf '%s' "$_FAIL" | CLAUDE_PROJECT_DIR="$PROJ" python3 "$_FT" | grep -q 'asgard-failure-warning' && { echo "FAIL: failure-tracker warned too early"; exit 1; } || true; done
printf '%s' "$_FAIL" | CLAUDE_PROJECT_DIR="$PROJ" python3 "$_FT" | grep -q 'asgard-failure-warning' || { echo "FAIL: failure-tracker must warn on 3rd"; exit 1; }
printf '%s' 'not-json' | python3 "$_FT" >/dev/null 2>&1 || { echo "FAIL: failure-tracker must fail-open"; exit 1; }
# shared state at ROOT .asgard/ (tool-neutral, cross-tool continuity), self-ignored via '*'
[ -f "$PROJ/.asgard/failures-smoke.json" ] || { echo "FAIL: shared state must live in root .asgard/"; exit 1; }
grep -q '^\*' "$PROJ/.asgard/.gitignore" || { echo "FAIL: .asgard/ must self-ignore with '*'"; exit 1; }
rm -rf "$PROJ/.asgard"
if ( cd "$PROJ" && "${ASG[@]}" init >/dev/null 2>&1 ); then echo "FAIL: init must refuse existing"; exit 1; fi
( cd "$PROJ" && "${ASG[@]}" init --force >/dev/null ) || { echo "FAIL: init --force"; exit 1; }
rm -rf "$PROJ"

# ── init --cursor — .cursor/ skeleton + beforeShellExecution guard ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --cursor >/dev/null ) || { echo "FAIL: init --cursor"; exit 1; }
[ -f "$PROJ/.cursor/rules/000-agents.mdc" ] || { echo "FAIL: --cursor rules bridge"; exit 1; }
for _d in skills hooks; do [ -f "$PROJ/.cursor/$_d/README.md" ] || { echo "FAIL: --cursor .cursor/$_d/README.md"; exit 1; }; done
[ ! -e "$PROJ/.claude" ] || { echo "FAIL: --cursor must NOT create .claude"; exit 1; }
grep -q "beforeShellExecution" "$PROJ/.cursor/hooks.json" || { echo "FAIL: --cursor hooks.json"; exit 1; }
[ -f "$PROJ/.cursor/hooks/git-guard.py" ] || { echo "FAIL: --cursor guard missing"; exit 1; }
python3 -m py_compile "$PROJ/.cursor/hooks/git-guard.py" || { echo "FAIL: cursor guard invalid"; exit 1; }
printf '%s' '{"command":"git push --force"}' | python3 "$PROJ/.cursor/hooks/git-guard.py" | grep -q '"permission":"deny"' || { echo "FAIL: cursor guard deny"; exit 1; }
printf '%s' '{"command":"git status"}'      | python3 "$PROJ/.cursor/hooks/git-guard.py" | grep -q '"permission":"allow"' || { echo "FAIL: cursor guard allow"; exit 1; }
rm -rf "$PROJ"

# ── init --codex — config.toml + git-guard + rules ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --codex >/dev/null ) || { echo "FAIL: init --codex"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] && [ -f "$PROJ/.codex/config.toml" ] || { echo "FAIL: --codex files"; exit 1; }
[ ! -e "$PROJ/.claude" ] && [ ! -e "$PROJ/.cursor" ] || { echo "FAIL: --codex scoped"; exit 1; }
grep -q '\[\[hooks.PreToolUse\]\]' "$PROJ/.codex/config.toml" || { echo "FAIL: --codex PreToolUse hook"; exit 1; }
[ -f "$PROJ/.codex/hooks/git-guard.py" ] || { echo "FAIL: --codex guard"; exit 1; }
[ -f "$PROJ/.codex/rules/canon.rules" ] && grep -q "prefix_rule" "$PROJ/.codex/rules/canon.rules" || { echo "FAIL: --codex rules"; exit 1; }
python3 -m py_compile "$PROJ/.codex/hooks/git-guard.py" || { echo "FAIL: codex guard invalid"; exit 1; }
rm -rf "$PROJ"

# ── combined --cc --cursor --codex ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --cc --cursor --codex >/dev/null ) || { echo "FAIL: init combined"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.cursor/hooks.json" ] && [ -f "$PROJ/.codex/config.toml" ] || { echo "FAIL: combined"; exit 1; }
rm -rf "$PROJ"

# ── upgrade — dry-run only (no network) ──
"${ASG[@]}" upgrade --dry-run | grep -q "would install" || { echo "FAIL: upgrade --dry-run"; exit 1; }

# ── uninstall — removes the uv tool we installed at the top ──
asgard uninstall --yes >/dev/null || { echo "FAIL: uninstall"; exit 1; }
[ ! -e "$UV_TOOL_BIN_DIR/asgard" ] || { echo "FAIL: asgard shim still present after uninstall"; exit 1; }

echo "PASS: uv-install + version($ver) + help + doctor + completions + init(universal/cc/cursor/codex) + guards(py) + failure-tracker(law9) + upgrade + uninstall"
