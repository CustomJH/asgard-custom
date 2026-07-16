#!/usr/bin/env bash
# CC4 (CUS-201) 게이트 적대 테스트 — 우회 벡터 전수 공격.
# 훅(코드)이 프롬프트가 아니라 물리 증거로 막는지 실증. 각 벡터: 기대=block/allow 명시, 불일치 시 FAIL.
# 라이브 LLM 불필요 — 훅을 배포 형태 그대로(새 프로세스) 직접 구동, 위조 상태를 손으로 만든다.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"  # tests/fixtures/bench-cc → repo root
QLOG="$ROOT/src/asgard/hooks/quest_log.py"
GATE="$ROOT/src/asgard/hooks/verifier_gate.py"
SUBGATE="$ROOT/src/asgard/hooks/subagent_gate.py"
PY="${PY:-python3}"
PASS=0; FAIL=0
ok(){ echo "  ✅ $1"; PASS=$((PASS+1)); }
bad(){ echo "  ❌ $1"; FAIL=$((FAIL+1)); }

# gate 가 block 하면 stdout 에 '"decision": "block"'. helper: 기대와 대조.
gate_expect(){ # <dir> <sid> <expect:block|allow> <label>
  local out; out=$(printf '%s' "{\"session_id\":\"$2\",\"cwd\":\"$1\",\"hook_event_name\":\"Stop\"}" | CLAUDE_PROJECT_DIR="$1" "$PY" "$GATE" 2>/dev/null)
  if echo "$out" | grep -q '"decision": "block"'; then local got=block; else local got=allow; fi
  [ "$got" = "$3" ] && ok "$4 ($got)" || bad "$4 (기대 $3, 실제 $got)"
}
sub_expect(){ # <dir> <agent> <sid> <expect> <label>
  local out; out=$(printf '%s' "{\"agent_type\":\"$2\",\"session_id\":\"$3\",\"cwd\":\"$1\",\"hook_event_name\":\"SubagentStop\"}" | CLAUDE_PROJECT_DIR="$1" "$PY" "$SUBGATE" 2>/dev/null)
  if echo "$out" | grep -q '"decision": "block"'; then local got=block; else local got=allow; fi
  [ "$got" = "$4" ] && ok "$5 ($got)" || bad "$5 (기대 $4, 실제 $got)"
}
mkrepo(){ local d="$1"; rm -rf "$d"; mkdir -p "$d"; ( cd "$d" && git init -q && git config user.email a@a && git config user.name a && echo "print('ok')" > app.py && git add -A && git commit -qm init ); }
ql(){ local d="$1"; shift; CLAUDE_PROJECT_DIR="$d" "$PY" "$QLOG" "$@"; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "V1. 로그 직접 위조 — bash 로 가짜 PASS 이벤트 append (diff_hash 불일치)"
D="$TMP/v1"; mkrepo "$D"
ql "$D" open q --criteria "add feature" >/dev/null
echo "print('changed')" > "$D/app.py"
# 손으로 위조: 실제 diff 와 무관한 가짜 hash + 가짜 commands
echo '{"schema":1,"quest_id":"q","turn":9,"role":"verifier","event":"verify","verdict":"PASS","diff_hash":"deadbeef","commands":[{"cmd":"pytest","exit_code":0}],"criteria":["x"]}' >> "$D/.asgard/quest/q.jsonl"
gate_expect "$D" v1 block "가짜 diff_hash 위조 → stale 물리 대조 차단"

echo "V2. MAX_BLOCKS 소진 후 fail-open 이 성공 위장인가 (write dirty 유지 + 무퀘스트)"
D="$TMP/v2"; mkrepo "$D"
ql "$D" open q --criteria "c" >/dev/null
echo "x=1" > "$D/app.py"   # 검증 안 된 write, PASS 레코드 없음
for i in 1 2 3; do gate_expect "$D" v2 block "무판정 write 차단 $i/3"; done
# 4번째: fail-open(allow) 하지만 stderr 에 에스컬레이션 지시 — '조용한 성공'이 아님을 확인
out4=$(printf '%s' '{"session_id":"v2","cwd":"'"$D"'","hook_event_name":"Stop"}' | CLAUDE_PROJECT_DIR="$D" "$PY" "$GATE" 2>"$TMP/v2.err")
if echo "$out4" | grep -q '"decision": "block"'; then bad "4번째 차단 여부"; else
  grep -q "에스컬레이션" "$TMP/v2.err" && ok "4번째 fail-open + Odin 에스컬레이션 지시 (조용한 성공 아님)" || bad "4번째 fail-open 인데 에스컬레이션 지시 없음"
fi

echo "V3. 증거 재활용 — 이전 quest 의 PASS 명령을 신규 quest 에 복사"
D="$TMP/v3"; mkrepo "$D"
ql "$D" open q1 --criteria "c1" >/dev/null
echo "y=2" > "$D/app.py"
ql "$D" append --verdict PASS --stdin < /dev/null >/dev/null 2>&1 || true
# 신규 write, 신규 quest, 그러나 verify 이벤트를 아예 안 남기고 종료 시도 (이전 quest 증거 무효)
ql "$D" close >/dev/null 2>&1 || true
ql "$D" open q2 --criteria "c2" >/dev/null
echo "z=3" >> "$D/app.py"
gate_expect "$D" v3 block "신규 quest 에 verify 레코드 없음 → 차단 (이전 증거 무효)"

echo "V4. sensitive 경로 우회 — 훅 파일 변경을 micro PASS 로 통과 시도"
D="$TMP/v4"; mkrepo "$D"; mkdir -p "$D/.claude/hooks"; echo "orig" > "$D/.claude/hooks/x.py"
( cd "$D" && git add -A && git commit -qm hooks )
ql "$D" open q --criteria "edit hook" >/dev/null
echo "tampered" > "$D/.claude/hooks/x.py"
ql "$D" append --role worker --event work >/dev/null
printf '%s' '{"role":"verifier","event":"verify","commands":[{"cmd":"python3 -c pass","exit_code":0}]}' | ql "$D" append --verdict PASS --level micro >/dev/null
gate_expect "$D" v4 block "민감 경로(.claude/hooks) micro PASS → full 강제 차단"

echo "V5. subagent-gate 우회 — verifier 가 위조 PASS(무증거) 기록 후 종료"
D="$TMP/v5"; mkrepo "$D"
ql "$D" open q --criteria "c" >/dev/null
ql "$D" append --role worker --event work >/dev/null
printf '%s' '{"role":"verifier","event":"verify","commands":[{"cmd":"echo done","exit_code":0}]}' | ql "$D" append --verdict PASS >/dev/null
sub_expect "$D" asgard-verifier v5 block "verifier trivial(echo) PASS → subagent-gate 차단"

echo "V6. 되돌린 orphan write 는 인질 금지 (거짓 양성 방어 — quest 없이 write-sentinel 기록 후 원복)"
D="$TMP/v6"; mkrepo "$D"
SENT="$ROOT/src/asgard/hooks/write_sentinel.py"
echo "tmp" > "$D/app.py"   # quest 미개설 write
printf '%s' '{"session_id":"v6","cwd":"'"$D"'","tool_name":"Write","tool_input":{"file_path":"app.py"}}' | CLAUDE_PROJECT_DIR="$D" "$PY" "$SENT" >/dev/null 2>&1
git -C "$D" checkout -- app.py   # 원복 → 경로 clean
gate_expect "$D" v6 allow "orphan write 원복(clean) → 차단 안 함"

echo "V7. orphan write 살아있으면 차단 (V6 대조 — 원복 안 함)"
D="$TMP/v7"; mkrepo "$D"
echo "leftover" > "$D/app.py"   # quest 미개설 write, 원복 안 함
printf '%s' '{"session_id":"v7","cwd":"'"$D"'","tool_name":"Write","tool_input":{"file_path":"app.py"}}' | CLAUDE_PROJECT_DIR="$D" "$PY" "$SENT" >/dev/null 2>&1
gate_expect "$D" v7 block "orphan write dirty + 무퀘스트 → 차단"

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
