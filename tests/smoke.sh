#!/usr/bin/env bash
# Smoke test — the money path: install the Python CLI as a uv tool into a temp prefix, put it on PATH,
# then the basic commands work; and every scaffold/guard assertion. Fails loud. No framework.
# No compile step — `uv tool install <repo>` + `uv run --project <repo> asgard` for speed.
# No `pipefail`: `cmd | grep -q` closes the pipe early → the Python producer gets SIGPIPE (exit 141),
# which pipefail would propagate as a false failure. `set -eu` is enough here.
set -eu

# 훅 구동 인터프리터 — 하드코딩 python3 는 Windows(git-bash)·python3 없는 러너에서 스위트를
# 통째로 무력화한다. python3 → python 순 폴백, PY 환경변수로 재정의 가능.
PY="${PY:-$(command -v python3 || command -v python)}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# HOME 격리 — asgard 는 ~/.asgard 에 상태를 쓴다 (projects.json 레지스트리·completions).
# 격리 없이는 smoke 가 돌 때마다 mktemp 프로젝트들이 실레지스트리에 등록돼 `asgard sync` 를
# 오염시킨다 (라이브 실측: temp 항목 18건 누적). uv 캐시·managed python 은 실경로를 물려줘
# 재다운로드 없이 돈다 — HOME 을 바꾸기 전에 실경로를 고정해야 한다.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$(uv cache dir)}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$HOME/.local/share/uv/python}"
export HOME="$TMP/home"
mkdir -p "$HOME"

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
# version 은 --version 옵션 단일 (위에서 검증) — 중복 서브커맨드 제거됨.
"${ASG[@]}" --help | grep -q "planned" && { echo "FAIL: --help must not list planned stubs"; exit 1; } || true
# run 은 실 커맨드 (PROMPT 필수) — 인자 없으면 usage 오류(2), --help 는 0.
# (구 hidden-stub exit-0 계약은 폐기 — 이 하네스가 CI 밖이라 조용히 썩었던 지점)
rc=0; "${ASG[@]}" run >/dev/null 2>&1 || rc=$?  # set -e 안전 캡처
[ "$rc" -eq 2 ] || { echo "FAIL: 'run' without PROMPT should exit 2 (usage), got $rc"; exit 1; }
"${ASG[@]}" run --help >/dev/null || { echo "FAIL: 'run --help' should exit 0"; exit 1; }
"${ASG[@]}" completions bash | grep -q "complete -F _asgard asgard" || { echo "FAIL: bash completions"; exit 1; }
"${ASG[@]}" completions zsh | grep -q "#compdef asgard" || { echo "FAIL: zsh completions"; exit 1; }
"${ASG[@]}" completions fish | grep -q "complete -c asgard" || { echo "FAIL: fish completions"; exit 1; }
if "${ASG[@]}" completions badshell >/dev/null 2>&1; then echo "FAIL: bad shell should exit nonzero"; exit 1; fi
# 서브커맨드 인지(뒷단 자동완성) — role 서브커맨드·역할 인자까지 세 셸 모두에 존재해야 한다
"${ASG[@]}" completions bash | grep -q "thinker worker verifier" || { echo "FAIL: bash completions missing role args"; exit 1; }
"${ASG[@]}" completions zsh | grep -q "thinker worker verifier" || { echo "FAIL: zsh completions missing role args"; exit 1; }
"${ASG[@]}" completions fish | grep -q "thinker worker verifier" || { echo "FAIL: fish completions missing role args"; exit 1; }

# doctor 는 cwd 의 .asgard 상태(공유 메모리 백엔드 등)를 읽는다 — 개발자 로컬 repo 에서 돌리면
# 호스트 백엔드 접속 상태가 smoke 를 물들인다. HOME 격리와 같은 이유로 중립 cwd 에서 판정.
( cd "$HOME" && asgard doctor >/dev/null ) || { echo "FAIL: doctor exit nonzero (asgard on PATH)"; exit 1; }
( cd "$HOME" && asgard doctor --json | grep -q '"ok": true' ) || { echo "FAIL: doctor --json ok"; exit 1; }
# Canonical Tool Kernel catalog — installed CLI reports both runtime surfaces.
asgard tools list --role worker --json | grep -q '"str_replace_based_edit_tool"' || { echo "FAIL: native tool catalog"; exit 1; }
asgard tools list --role worker --json | grep -q '"NotebookEdit"' || { echo "FAIL: Claude Code tool catalog"; exit 1; }
if asgard tools list --role odin --json >/dev/null 2>&1; then echo "FAIL: unknown tool role should exit nonzero"; exit 1; fi
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
"$PY" -m py_compile "$PROJ/.codex/hooks/failure-tracker.py" "$PROJ/.cursor/hooks/failure-tracker.py" || { echo "FAIL: cross-tool trackers invalid Python"; exit 1; }
# cross-tool memory lifecycle — shared skill + client-native snapshot/recall/sync hooks.
[ -f "$PROJ/.agents/skills/asgard-memory/SKILL.md" ] \
  && [ -f "$PROJ/.codex/hooks/memory-activate.py" ] && [ -f "$PROJ/.cursor/hooks/memory-activate.py" ] \
  || { echo "FAIL: universal missing codex/cursor memory lifecycle"; exit 1; }
grep -q "UserPromptSubmit" "$PROJ/.codex/config.toml" \
  && grep -q "beforeSubmitPrompt" "$PROJ/.cursor/hooks.json" \
  || { echo "FAIL: universal memory recall not wired cross-tool"; exit 1; }
# asgard-test 자가 테스트 커맨드 — 3툴 전부 (skills/commands/prompts), 하니스 스크립트 실동작.
# 스캐폴드 파일은 발견용 어댑터라 하니스 본문은 중앙 정본(asgard skills show)에서 추출한다.
[ -f "$PROJ/.claude/skills/asgard-test/SKILL.md" ] && [ -f "$PROJ/.agents/skills/asgard-test/SKILL.md" ] \
  || { echo "FAIL: universal missing asgard-test (.claude + .agents)"; exit 1; }
grep -q "asgard skills show asgard-test" "$PROJ/.claude/skills/asgard-test/SKILL.md" \
  || { echo "FAIL: asgard-test adapter must point at the canonical body"; exit 1; }
( cd "$PROJ" && git init -q && git -c user.email=t@t -c user.name=t commit -qm init --allow-empty \
  && "${ASG[@]}" skills show asgard-test > selftest.md \
  && "$PY" -c "
import re
md = open('selftest.md').read()
open('selftest-b.sh','w').write(re.search(r'\`\`\`bash\n(.*?)\`\`\`', md, re.S).group(1))" \
  && bash selftest-b.sh | grep -q -- '-- harness: 8/8 ok' ) || { echo "FAIL: asgard-test harness slice not 8/8"; exit 1; }
rm -rf "$PROJ"

# ── init --cc — AGENTS.md + full .claude/ (bridge + config + Python guards) ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --cc >/dev/null ) || { echo "FAIL: init --cc"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] || { echo "FAIL: --cc must create AGENTS.md"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.claude/CLAUDE.md" ] || { echo "FAIL: --cc files"; exit 1; }
"$PY" -c "import json,sys; d=json.load(open('$PROJ/.claude/settings.json')); sys.exit(0 if d.get('permissions',{}).get('deny') else 1)" || { echo "FAIL: --cc settings.json permissions"; exit 1; }
[ -f "$PROJ/.claude/.gitignore" ] && grep -q "settings.local.json" "$PROJ/.claude/.gitignore" || { echo "FAIL: --cc .gitignore"; exit 1; }
# Role tool surfaces are explicit least-privilege allowlists, not host defaults.
grep -q '^tools: Read, Grep, Glob, Bash, Write, Edit, NotebookEdit, Agent$' "$PROJ/.claude/agents/asgard-worker.md" || { echo "FAIL: worker tool allowlist"; exit 1; }
grep -q '^tools: Read, Grep, Glob, Bash, Agent$' "$PROJ/.claude/agents/asgard-verifier.md" || { echo "FAIL: verifier tool allowlist"; exit 1; }
grep -q '^tools: Read, Grep, Glob, Bash, Write, Edit, NotebookEdit$' "$PROJ/.claude/agents/asgard-thor.md" || { echo "FAIL: delivery tool allowlist"; exit 1; }
for _d in commands agents skills hooks rules output-styles; do
  [ -f "$PROJ/.claude/$_d/README.md" ] || { echo "FAIL: --cc missing .claude/$_d/README.md"; exit 1; }
done
[ ! -e "$PROJ/.cursor" ] || { echo "FAIL: --cc must NOT create .cursor"; exit 1; }
# Canon guards (Python) — block danger, allow safe, fail-open on garbage
grep -q '"PreToolUse"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing hooks"; exit 1; }
[ -f "$PROJ/.claude/hooks/git-guard.py" ] && [ -f "$PROJ/.claude/hooks/readonly-guard.py" ] && [ -f "$PROJ/.claude/hooks/secret-guard.py" ] || { echo "FAIL: --cc missing Python guards"; exit 1; }
"$PY" -m py_compile "$PROJ/.claude/hooks/git-guard.py" "$PROJ/.claude/hooks/readonly-guard.py" "$PROJ/.claude/hooks/secret-guard.py" || { echo "FAIL: guards invalid Python"; exit 1; }
printf '%s' '{"tool_input":{"command":"git push --force"}}' | "$PY" "$PROJ/.claude/hooks/git-guard.py" 2>/dev/null && { echo "FAIL: git-guard must block force-push"; exit 1; } || true
printf '%s' '{"tool_input":{"command":"git checkout HEAD -- ."}}' | "$PY" "$PROJ/.claude/hooks/git-guard.py" 2>/dev/null && { echo "FAIL: git-guard must block worktree discard"; exit 1; } || true
printf '%s' '{"tool_input":{"command":"git status"}}'      | "$PY" "$PROJ/.claude/hooks/git-guard.py" 2>/dev/null || { echo "FAIL: git-guard must allow git status"; exit 1; }
printf '%s' 'not-json'                                      | "$PY" "$PROJ/.claude/hooks/git-guard.py" 2>/dev/null || { echo "FAIL: git-guard must fail-open"; exit 1; }
[ -f "$PROJ/.claude/hooks/release-guard.py" ] || { echo "FAIL: --cc missing release-guard"; exit 1; }
printf '%s' '{"tool_input":{"command":"npm publish"}}'      | "$PY" "$PROJ/.claude/hooks/release-guard.py" 2>/dev/null && { echo "FAIL: release-guard must block npm publish"; exit 1; } || true
printf '%s' '{"tool_input":{"command":"docker push repo/img"}}' | "$PY" "$PROJ/.claude/hooks/release-guard.py" 2>/dev/null && { echo "FAIL: release-guard must block docker push"; exit 1; } || true
printf '%s' '{"tool_input":{"command":"npm run build"}}'    | "$PY" "$PROJ/.claude/hooks/release-guard.py" 2>/dev/null || { echo "FAIL: release-guard must allow npm run build"; exit 1; }
printf '%s' 'not-json'                                      | "$PY" "$PROJ/.claude/hooks/release-guard.py" 2>/dev/null || { echo "FAIL: release-guard must fail-open"; exit 1; }
printf '%s' '{"agent_type":"asgard-verifier","tool_input":{"command":"printf hacked > calc.py"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null && { echo "FAIL: readonly-guard must block shell writes"; exit 1; } || true
printf '%s' '{"tool_input":{"command":"printf hacked > calc.py"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null && { echo "FAIL: readonly-guard must block coordinator shell writes"; exit 1; } || true
printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"calc.py","content":"hacked"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null && { echo "FAIL: readonly-guard must block coordinator Write"; exit 1; } || true
printf '%s' '{"agent_type":"asgard-worker","tool_name":"Write","tool_input":{"file_path":"calc.py","content":"ok"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null || { echo "FAIL: readonly-guard must allow worker Write"; exit 1; }
printf '%s' '{"agent_type":"asgard-worker","tool_name":"Write","tool_input":{"file_path":".claude/hooks/readonly-guard.py","content":"pass"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null && { echo "FAIL: worker must not overwrite control hooks"; exit 1; } || true
printf '%s' '{"agent_type":"asgard-worker","tool_name":"Bash","tool_input":{"command":"printf pass > .claude/hooks/readonly-guard.py"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null && { echo "FAIL: worker Bash must not overwrite control hooks"; exit 1; } || true
printf '%s' '{"agent_type":"asgard-verifier","tool_input":{"command":"git diff"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null || { echo "FAIL: readonly-guard must allow inspection"; exit 1; }
printf '%s' '{"agent_type":"asgard-worker","tool_input":{"command":"printf ok > calc.py"}}' | "$PY" "$PROJ/.claude/hooks/readonly-guard.py" 2>/dev/null || { echo "FAIL: readonly-guard must allow worker"; exit 1; }
printf '%s' '{"tool_input":{"file_path":"x/.env","content":"A=1"}}' | "$PY" "$PROJ/.claude/hooks/secret-guard.py" 2>/dev/null && { echo "FAIL: secret-guard must block .env"; exit 1; } || true
# Canon Law 9 failure-tracker (PostToolUse) — soft 3-strike warn, normalized signature, fail-open
grep -q '"PostToolUse"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing PostToolUse"; exit 1; }
[ -f "$PROJ/.claude/hooks/failure-tracker.py" ] || { echo "FAIL: --cc missing failure-tracker.py"; exit 1; }
"$PY" -m py_compile "$PROJ/.claude/hooks/failure-tracker.py" || { echo "FAIL: failure-tracker invalid Python"; exit 1; }
_FT="$PROJ/.claude/hooks/failure-tracker.py"
_FAIL='{"tool_name":"Bash","session_id":"smoke","tool_response":{"is_error":true,"error":"cannot open /p/a1: e1"}}'
for _i in 1 2; do printf '%s' "$_FAIL" | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$_FT" | grep -q 'asgard-failure-warning' && { echo "FAIL: failure-tracker warned too early"; exit 1; } || true; done
printf '%s' "$_FAIL" | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$_FT" | grep -q 'asgard-failure-warning' || { echo "FAIL: failure-tracker must warn on 3rd"; exit 1; }
printf '%s' 'not-json' | "$PY" "$_FT" >/dev/null 2>&1 || { echo "FAIL: failure-tracker must fail-open"; exit 1; }
# Trinity subagent-gate (SubagentStop) — 역할 로그 규율: 미기록 종료 block, quest 없으면 allow, fail-open
grep -q '"SubagentStop"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing SubagentStop"; exit 1; }
_SG="$PROJ/.claude/hooks/subagent-gate.py"
[ -f "$_SG" ] || { echo "FAIL: --cc missing subagent-gate.py"; exit 1; }
"$PY" -m py_compile "$_SG" || { echo "FAIL: subagent-gate invalid Python"; exit 1; }
printf '%s' 'not-json' | "$PY" "$_SG" >/dev/null 2>&1 || { echo "FAIL: subagent-gate must fail-open"; exit 1; }
printf '%s' '{"agent_type":"asgard-verifier","session_id":"smoke"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$_SG" | grep -q 'block' && { echo "FAIL: subagent-gate must allow without active quest"; exit 1; } || true
mkdir -p "$PROJ/.asgard/quest" && printf 'sg1' > "$PROJ/.asgard/quest/ACTIVE" && printf '{"event":"work","role":"worker"}\n' > "$PROJ/.asgard/quest/sg1.jsonl"
printf '%s' '{"agent_type":"asgard-verifier","session_id":"smoke"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$_SG" | grep -q '"decision": "block"' || { echo "FAIL: subagent-gate must block verifier without verify event"; exit 1; }
printf '{"event":"verify","role":"verifier","verdict":"PASS","commands":[{"cmd":"pytest -q","exit_code":0}]}\n' >> "$PROJ/.asgard/quest/sg1.jsonl"
printf '%s' '{"agent_type":"asgard-verifier","session_id":"smoke"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$_SG" | grep -q 'block' && { echo "FAIL: subagent-gate must allow verifier with evidence PASS"; exit 1; } || true
rm -f "$PROJ/.asgard/quest/ACTIVE" "$PROJ/.asgard/quest/sg1.jsonl"
# Lagom — 훅 3종+캐논 스캐폴드, SessionStart 주입, /lagom 전환, off 무주입, fail-open
grep -q '"SessionStart"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing SessionStart (lagom)"; exit 1; }
grep -q '"SubagentStart"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing SubagentStart (lagom)"; exit 1; }
for _f in lagom-activate.py lagom-tracker.py lagom-subagent.py lagom-canon.md lagom-statusline.sh; do
  [ -f "$PROJ/.claude/hooks/$_f" ] || { echo "FAIL: --cc missing $_f"; exit 1; }
done
grep -q '"statusLine"' "$PROJ/.claude/settings.json" || { echo "FAIL: --cc settings.json missing statusLine (lagom)"; exit 1; }
printf '%s' '{"model":{"display_name":"Opus"},"workspace":{"current_dir":"'"$PROJ"'"}}' | bash "$PROJ/.claude/hooks/lagom-statusline.sh" | grep -q 'lagom:full' || { echo "FAIL: lagom-statusline must show default full"; exit 1; }
"$PY" -m py_compile "$PROJ/.claude/hooks/lagom-activate.py" "$PROJ/.claude/hooks/lagom-tracker.py" "$PROJ/.claude/hooks/lagom-subagent.py" || { echo "FAIL: lagom hooks invalid Python"; exit 1; }
printf '%s' '{"source":"startup"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$PROJ/.claude/hooks/lagom-activate.py" | grep -q 'mode=full' || { echo "FAIL: lagom-activate must inject default full"; exit 1; }
"$PY" -c 'import json, sys; assert json.load(open(sys.argv[1])) == {"mode": "full"}' "$PROJ/.asgard/state/lagom-mode.json" || { echo "FAIL: lagom JSON state file not written"; exit 1; }
printf '%s' '{"prompt":"/lagom lite"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$PROJ/.claude/hooks/lagom-tracker.py" | grep -q 'lite' || { echo "FAIL: lagom-tracker must switch mode"; exit 1; }
"$PY" -c 'import json, sys; assert json.load(open(sys.argv[1])) == {"mode": "lite"}' "$PROJ/.asgard/state/lagom-mode.json" || { echo "FAIL: lagom switch not persisted to JSON state"; exit 1; }
printf '%s' '{"agent_type":"asgard-verifier"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$PROJ/.claude/hooks/lagom-subagent.py" | grep -q 'additionalContext' && { echo "FAIL: lagom-subagent must not inject verifier"; exit 1; } || true
printf '%s' '{"agent_type":"asgard-worker"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$PROJ/.claude/hooks/lagom-subagent.py" | grep -q 'additionalContext' || { echo "FAIL: lagom-subagent must inject worker"; exit 1; }
printf '%s' '{"prompt":"stop lagom"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$PROJ/.claude/hooks/lagom-tracker.py" | grep -q '\[lagom\] off' || { echo "FAIL: lagom deactivation phrase"; exit 1; }
printf '%s' '{"source":"compact"}' | CLAUDE_PROJECT_DIR="$PROJ" "$PY" "$PROJ/.claude/hooks/lagom-activate.py" | grep -q '.' && { echo "FAIL: lagom off must inject nothing"; exit 1; } || true
printf '%s' 'not-json' | "$PY" "$PROJ/.claude/hooks/lagom-tracker.py" >/dev/null 2>&1 || { echo "FAIL: lagom-tracker must fail-open"; exit 1; }
rm -f "$PROJ/.asgard/state/lagom-mode.json" "$PROJ/.asgard/lagom-mode"
grep -q 'asgard:lagom' "$PROJ/AGENTS.md" || { echo "FAIL: AGENTS.md missing lagom section"; exit 1; }
[ -f "$PROJ/.claude/skills/asgard-lagom-review/SKILL.md" ] || { echo "FAIL: --cc missing lagom-review skill"; exit 1; }
[ -f "$PROJ/.claude/skills/asgard-seal/SKILL.md" ] || { echo "FAIL: --cc missing asgard-seal skill"; exit 1; }
grep -q "Co-Authored-By" "$PROJ/.claude/skills/asgard-seal/SKILL.md" || { echo "FAIL: asgard-seal missing no-footer hard rule"; exit 1; }
# shared state at ROOT .asgard/ (tool-neutral, cross-tool continuity), self-ignored via '*'
[ -f "$PROJ/.asgard/failures-smoke.json" ] || { echo "FAIL: shared state must live in root .asgard/"; exit 1; }
grep -q '^\*' "$PROJ/.asgard/.gitignore" || { echo "FAIL: .asgard/ must self-ignore with '*'"; exit 1; }
grep -q '^!map/$' "$PROJ/.asgard/.gitignore" || { echo "FAIL: .asgard/.gitignore must un-ignore map/ (team-shared)"; exit 1; }
grep -q '^!memory/records/$' "$PROJ/.asgard/.gitignore" || { echo "FAIL: .asgard/.gitignore must un-ignore memory/records/"; exit 1; }
# 코드베이스 지도 — 시드 존재 + git 실추적 검증 (루트 블록·자가 무시 둘 다 map 을 허용해야 추적됨)
[ -f "$PROJ/.asgard/map/INDEX.md" ] || { echo "FAIL: --cc must seed .asgard/map/INDEX.md"; exit 1; }
[ -f "$PROJ/.asgard/map/GRAPH.md" ] && [ -f "$PROJ/.asgard/state/map-graph.json" ] \
  || { echo "FAIL: --cc must perform the initial relation-map scan"; exit 1; }
[ -f "$PROJ/.claude/hooks/map-activate.py" ] && grep -q 'map-activate.py' "$PROJ/.claude/settings.json" \
  || { echo "FAIL: --cc periodic map maintenance missing"; exit 1; }
grep -q 'asgard:map' "$PROJ/AGENTS.md" || { echo "FAIL: AGENTS.md missing map section"; exit 1; }
# 루트 .gitignore — 런타임 상태 필터. 생성됨 + asgard 블록 + .asgard/* 무시 + map 재포함
[ -f "$PROJ/.gitignore" ] || { echo "FAIL: --cc must create root .gitignore"; exit 1; }
grep -q '^\.asgard/\*$' "$PROJ/.gitignore" || { echo "FAIL: root .gitignore must ignore .asgard/* (not dir pattern)"; exit 1; }
grep -q '^!\.asgard/map/$' "$PROJ/.gitignore" || { echo "FAIL: root .gitignore must un-ignore .asgard/map/"; exit 1; }
grep -q '^!\.asgard/memory/records/$' "$PROJ/.gitignore" || { echo "FAIL: root .gitignore must un-ignore .asgard/memory/records/"; exit 1; }
grep -q '>>> asgard >>>' "$PROJ/.gitignore" || { echo "FAIL: root .gitignore missing asgard marker block"; exit 1; }
if command -v git >/dev/null; then
  ( cd "$PROJ" && git init -q . && git add -A >/dev/null 2>&1
    git status --porcelain | grep -q 'A  .asgard/map/INDEX.md' || { echo "FAIL: .asgard/map must be git-tracked"; exit 1; }
    mkdir -p .asgard/memory/records && printf '%s\n' test > .asgard/memory/records/test.md && git add -A >/dev/null 2>&1
    git status --porcelain | grep -q 'A  .asgard/memory/records/test.md' || { echo "FAIL: .asgard/memory/records must be git-tracked"; exit 1; }
    git status --porcelain | grep -q 'failures-smoke' && { echo "FAIL: .asgard runtime state must stay ignored"; exit 1; } || true
    rm -rf .git ) || exit 1
fi
# 병합 — 기존 사용자 규칙 보존 + idempotent (블록 1개)
printf '# user rule\nmydir/\n' > "$PROJ/.gitignore"
( cd "$PROJ" && "${ASG[@]}" init --cc --force >/dev/null 2>&1 )
grep -q '^mydir/$' "$PROJ/.gitignore" || { echo "FAIL: .gitignore merge must preserve user rules"; exit 1; }
[ "$(grep -c '>>> asgard >>>' "$PROJ/.gitignore")" = "1" ] || { echo "FAIL: .gitignore asgard block must be idempotent (1)"; exit 1; }
rm -rf "$PROJ/.asgard"
if ( cd "$PROJ" && "${ASG[@]}" init >/dev/null 2>&1 ); then echo "FAIL: init must refuse existing"; exit 1; fi
( cd "$PROJ" && "${ASG[@]}" init --force >/dev/null ) || { echo "FAIL: init --force"; exit 1; }
rm -rf "$PROJ"

# ── init --cursor — .cursor/ skeleton + beforeShellExecution guard ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --cursor >/dev/null ) || { echo "FAIL: init --cursor"; exit 1; }
[ -f "$PROJ/.cursor/rules/000-agents.mdc" ] || { echo "FAIL: --cursor rules bridge"; exit 1; }
for _d in skills hooks; do [ -f "$PROJ/.cursor/$_d/README.md" ] || { echo "FAIL: --cursor .cursor/$_d/README.md"; exit 1; }; done
[ -f "$PROJ/.agents/skills/asgard-test/SKILL.md" ] || { echo "FAIL: --cursor missing .agents/skills asgard-test"; exit 1; }
[ -f "$PROJ/.agents/skills/asgard-seal/SKILL.md" ] || { echo "FAIL: --cursor missing .agents/skills asgard-seal"; exit 1; }
[ -f "$PROJ/.agents/skills/asgard-memory/SKILL.md" ] || { echo "FAIL: --cursor missing asgard-memory skill"; exit 1; }
[ ! -e "$PROJ/.claude" ] || { echo "FAIL: --cursor must NOT create .claude"; exit 1; }
grep -q "beforeShellExecution" "$PROJ/.cursor/hooks.json" || { echo "FAIL: --cursor hooks.json"; exit 1; }
[ -f "$PROJ/.cursor/hooks/git-guard.py" ] || { echo "FAIL: --cursor guard missing"; exit 1; }
[ -f "$PROJ/.cursor/hooks/memory-activate.py" ] && grep -q '"beforeSubmitPrompt"' "$PROJ/.cursor/hooks.json" \
  || { echo "FAIL: --cursor memory lifecycle missing"; exit 1; }
[ -f "$PROJ/.asgard/map/GRAPH.md" ] && [ -f "$PROJ/.asgard/state/map-graph.json" ] \
  && [ -f "$PROJ/.cursor/hooks/map-activate.py" ] && grep -q 'map-activate.py' "$PROJ/.cursor/hooks.json" \
  || { echo "FAIL: --cursor map lifecycle missing"; exit 1; }
[ -f "$PROJ/.cursor/agents/asgard-worker.md" ] && [ -f "$PROJ/.cursor/agents/asgard-verifier.md" ] || { echo "FAIL: --cursor Trinity agents missing"; exit 1; }
grep -q '"subagentStart"' "$PROJ/.cursor/hooks.json" && grep -q '"stop"' "$PROJ/.cursor/hooks.json" || { echo "FAIL: --cursor Trinity hooks missing"; exit 1; }
grep -q '^readonly: false$' "$PROJ/.cursor/agents/asgard-worker.md" || { echo "FAIL: --cursor worker must be writable"; exit 1; }
grep -q '^readonly: true$' "$PROJ/.cursor/agents/asgard-verifier.md" || { echo "FAIL: --cursor verifier must be read-only"; exit 1; }
"$PY" -m py_compile "$PROJ/.cursor/hooks/git-guard.py" || { echo "FAIL: cursor guard invalid"; exit 1; }
printf '%s' '{"command":"git push --force"}' | "$PY" "$PROJ/.cursor/hooks/git-guard.py" | grep -q '"permission":"deny"' || { echo "FAIL: cursor guard deny"; exit 1; }
printf '%s' '{"command":"git status"}'      | "$PY" "$PROJ/.cursor/hooks/git-guard.py" | grep -q '"permission":"allow"' || { echo "FAIL: cursor guard allow"; exit 1; }
rm -rf "$PROJ"

# ── init --codex — config.toml + git-guard + rules ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --codex >/dev/null ) || { echo "FAIL: init --codex"; exit 1; }
[ -f "$PROJ/AGENTS.md" ] && [ -f "$PROJ/.codex/config.toml" ] || { echo "FAIL: --codex files"; exit 1; }
[ ! -e "$PROJ/.claude" ] && [ ! -e "$PROJ/.cursor" ] || { echo "FAIL: --codex scoped"; exit 1; }
grep -q '\[\[hooks.PreToolUse\]\]' "$PROJ/.codex/config.toml" || { echo "FAIL: --codex PreToolUse hook"; exit 1; }
[ -f "$PROJ/.codex/hooks/git-guard.py" ] || { echo "FAIL: --codex guard"; exit 1; }
[ -f "$PROJ/.codex/hooks/memory-activate.py" ] && grep -q '\[\[hooks.UserPromptSubmit\]\]' "$PROJ/.codex/config.toml" \
  || { echo "FAIL: --codex memory lifecycle missing"; exit 1; }
[ -f "$PROJ/.asgard/map/GRAPH.md" ] && [ -f "$PROJ/.asgard/state/map-graph.json" ] \
  && [ -f "$PROJ/.codex/hooks/map-activate.py" ] && grep -q 'map-activate.py' "$PROJ/.codex/config.toml" \
  || { echo "FAIL: --codex map lifecycle missing"; exit 1; }
[ -f "$PROJ/.codex/agents/asgard-worker.toml" ] && [ -f "$PROJ/.codex/agents/asgard-verifier.toml" ] || { echo "FAIL: --codex Trinity agents missing"; exit 1; }
grep -q '\[\[hooks.SubagentStart\]\]' "$PROJ/.codex/config.toml" && grep -q '\[\[hooks.Stop\]\]' "$PROJ/.codex/config.toml" || { echo "FAIL: --codex Trinity hooks missing"; exit 1; }
grep -q '^sandbox_mode = "read-only"$' "$PROJ/.codex/agents/asgard-verifier.toml" || { echo "FAIL: --codex verifier must be read-only"; exit 1; }
[ -f "$PROJ/.codex/rules/canon.rules" ] && grep -q "prefix_rule" "$PROJ/.codex/rules/canon.rules" || { echo "FAIL: --codex rules"; exit 1; }
[ -f "$PROJ/.agents/skills/asgard-test/SKILL.md" ] || { echo "FAIL: --codex missing .agents/skills asgard-test"; exit 1; }
[ -f "$PROJ/.agents/skills/asgard-memory/SKILL.md" ] || { echo "FAIL: --codex missing asgard-memory skill"; exit 1; }
"$PY" -m py_compile "$PROJ/.codex/hooks/git-guard.py" || { echo "FAIL: codex guard invalid"; exit 1; }
rm -rf "$PROJ"

# ── combined --cc --cursor --codex ──
PROJ="$(mktemp -d)"
( cd "$PROJ" && "${ASG[@]}" init --cc --cursor --codex >/dev/null ) || { echo "FAIL: init combined"; exit 1; }
[ -f "$PROJ/.claude/settings.json" ] && [ -f "$PROJ/.cursor/hooks.json" ] && [ -f "$PROJ/.codex/config.toml" ] || { echo "FAIL: combined"; exit 1; }
rm -rf "$PROJ"

# ── update — dry-run only (no network) ──
"${ASG[@]}" update --dry-run | grep -q "would install" || { echo "FAIL: update --dry-run"; exit 1; }
"${ASG[@]}" upgrade --dry-run | grep -q "would install" || { echo "FAIL: upgrade alias --dry-run"; exit 1; }

# ── uninstall — removes the uv tool we installed at the top ──
asgard uninstall --yes >/dev/null || { echo "FAIL: uninstall"; exit 1; }
[ ! -e "$UV_TOOL_BIN_DIR/asgard" ] || { echo "FAIL: asgard shim still present after uninstall"; exit 1; }

echo "PASS: uv-install + version($ver) + help + doctor + completions + init(universal/cc/cursor/codex) + guards(py) + failure-tracker(law9) + upgrade + uninstall"
