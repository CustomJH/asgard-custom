"""asgard-test 스킬: 사용자가 별도 세션에서 셋업을 자가 테스트하는 커맨드.

단일 본문을 두 위치에 배포한다 — Claude Code(.claude/skills/) · Cursor+Codex 공용(.agents/skills/,
양 툴의 네이티브 스킬 스코프이자 동일 SKILL.md 포맷: cursor.com/docs/skills ·
developers.openai.com/codex/skills). 본문이 훅 디렉터리를 자동감지하므로 툴별 렌더링이 없다
(quest-log 훅의 프로토콜 자동감지와 같은 원칙). 게이트 체크는 verifier-gate.py 가 있을 때만 (현재 Claude 전용).

계층 설계 — 왜 하니스 슬라이스를 temp repo 에서 도는가: 실 repo 에 FAIL quest 를 시드하면
그 세션의 Stop 게이트가 PASS 를 요구하며 사용자를 가둔다 (E2E 에서 실측된 함정)."""

SELFTEST_MD = """\
---
name: asgard-test
description: Asgard setup self-test — three-layer verification (wiring, harness, live) plus hook latency. Reports as a scorecard.
---

# asgard-test — setup self-test

Verify in the current session that this repo's Asgard setup (Canon + Trinity) actually works, and
report it as **a single scorecard**. Three layers: A wiring (static) → B harness (deterministic) → C live (real cycle).
(Invocation — Claude Code/Cursor: `/asgard-test` · Codex: `$asgard-test` or the `/skills` list.)

## A. Wiring (read-only, a few seconds)

1. **Bridge**: right here, print `ASGARD_OK — loaded from AGENTS.md` — from memory, without
   re-reading AGENTS.md. If you cannot, the bridge is broken (CLAUDE.md/@import · cursor rule · codex native).
2. **Files**: check existence — `.asgard/asgard-setting-project.json` · `quest-log.py` in the hook
   directory (whichever of `.claude/hooks` | `.cursor/hooks` | `.codex/hooks` matches the current
   tool) · (Claude only) `verifier-gate.py` + `write-sentinel.py` +
   `.claude/agents/asgard-{thinker,worker,verifier}.md` + the Stop gate wiring in settings.json.
3. **Executability**: `python3 <hooks>/quest-log.py state` exits 0.

## B. Harness (deterministic — run the script below verbatim)

Runs in a temp repo — seeding the real repo would trap this session behind its own gate, so do not change the paths.

```bash
set -u
SRC="$(pwd)"; H="$(ls -d .claude/hooks .cursor/hooks .codex/hooks 2>/dev/null | head -1)"
T="$(mktemp -d)"; cp "$H/quest-log.py" "$T/ql.py"
GATE=""; [ -f "$SRC/.claude/hooks/verifier-gate.py" ] && { cp "$SRC/.claude/hooks/verifier-gate.py" "$T/vg.py"; GATE=1; }
cd "$T" || exit 1
git init -q && git config user.email t@t && git config user.name t
echo base > f.txt && git add -A && git commit -qm init
QL="python3 ql.py"; n=0; f=0
ck(){ n=$((n+1)); if eval "$2" >/dev/null 2>&1; then echo "ok   $1"; else echo "FAIL $1"; f=$((f+1)); fi; }
W='{"role":"worker","event":"work","changed_files":["f.txt"],"commands":[{"cmd":"true","exit_code":0}]}'
V='{"role":"verifier","event":"verify","commands":[{"cmd":"test -s f.txt","exit_code":0}]}'
ck "quest log open/state"          "$QL open q1 --criteria c && $QL state | grep -q q1"
echo x >> f.txt
ck "transition: after work → VERIFIER" "echo '$W' | $QL append && $QL next | grep -q VERIF"
ck "verify PASS → diff_hash"  "echo '$V' | $QL append --verdict PASS --level micro && grep -q '\\"diff_hash\\": *\\"[0-9a-f]' .asgard/quest/q1.jsonl"
ck "close (PASS + hash match)"   "$QL close"
ck "transition: destructive → ODIN" "$QL open q3 --criteria c && $QL next --destructive | grep -q ESCALATE_ODIN"
ck "transition: 3 failures → REPLAN"    "echo '{\\"role\\":\\"verifier\\",\\"event\\":\\"verify\\",\\"failure_sig\\":\\"s\\",\\"failure_count\\":3,\\"commands\\":[{\\"cmd\\":\\"true\\",\\"exit_code\\":1}]}' | $QL append --verdict FAIL && $QL next | grep -q THINKER_REPLAN"
if [ -n "$GATE" ]; then
  $QL open q2 --criteria c >/dev/null; echo y >> f.txt
  echo "$V" | $QL append --verdict PASS --level micro >/dev/null
  echo z >> f.txt   # tamper after PASS
  ck "gate: tamper → stale block" "echo '{\\"session_id\\":\\"st\\"}' | CLAUDE_PROJECT_DIR=\\"$T\\" python3 vg.py | grep -q block"
  echo "$V" | $QL append --verdict ESCALATE --level full >/dev/null
  ck "gate: ESCALATE → allow"   "test -z \\"\\$(echo '{\\"session_id\\":\\"st\\"}' | CLAUDE_PROJECT_DIR=\\"$T\\" python3 vg.py)\\""
fi
echo "-- harness: $((n-f))/$n ok"
cd "$SRC" && rm -rf "$T"
```

All `ok` = pass — copy any `FAIL` lines into the scorecard verbatim.

## C. Live (current session, one real protocol cycle — a few write turns)

Run one real Trinity cycle in the real repo as a micro quest (following the AGENTS.md trinity loop exactly):

1. `python3 <hooks>/quest-log.py open selftest-live --criteria "python3 selftest_probe.py exits 0"`
2. **[Worker]** create `selftest_probe.py` (one line: `print("probe ok")`) → append a work event.
3. **[Verifier]** ignore the Worker's narrative, run the verification command directly → append verify PASS (diff_hash auto-computed).
4. Confirm `close` succeeds → **only then** delete `selftest_probe.py` (in the reverse order the gate
   blocks on a stale PASS — itself evidence of correct behavior, but it makes the cycle messy).
5. On Claude Code, subagent dispatch (mode B) is the default path, but phase switching (mode A) is
   enough for this test — the goal is verifying the identical cross-tool path.

## Latency (optional)

Run `time python3 <hooks>/quest-log.py state` 3 times — report the median. (Claude) Same for Stop gate allow.
Reference (M5 Max): state ~97ms · gate allow ~87ms · non-quest-session gate ~24ms.

## Scorecard (report format)

| Layer | Check | Result |
|---|---|---|
| A wiring | bridge / files / executability | ✅·❌ each |
| B harness | N/N ok (list FAIL items) | |
| C live | open→work→verify PASS→close + cleanup | |
| Latency | state / gate (if measured) | |

Be honest about caveats: this test verifies **wiring, enforcement, and protocol compliance** —
token/cost/output-quality measurement is impossible inside a session. Full E2E (gate on/off A/B,
real cost) lives in the asgard repo's `tests/e2e_trinity.sh`. If you find a defect, attach a
reproduction command to the scorecard.
"""
