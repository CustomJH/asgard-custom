"""asgard-test 스킬 (CUS-126 후속): 사용자가 별도 세션에서 셋업을 자가 테스트하는 커맨드.

단일 본문을 두 위치에 배포한다 — Claude Code(.claude/skills/) · Cursor+Codex 공용(.agents/skills/,
양 툴의 네이티브 스킬 스코프이자 동일 SKILL.md 포맷: cursor.com/docs/skills ·
developers.openai.com/codex/skills). 본문이 훅 디렉터리를 자동감지하므로 툴별 렌더링이 없다
(quest-log 훅의 프로토콜 자동감지와 같은 원칙). 게이트 체크는 verifier-gate.py 가 있을 때만 (현재 Claude 전용).

계층 설계 — 왜 하니스 슬라이스를 temp repo 에서 도는가: 실 repo 에 FAIL quest 를 시드하면
그 세션의 Stop 게이트가 PASS 를 요구하며 사용자를 가둔다 (E2E 에서 실측된 함정)."""

SELFTEST_MD = """\
---
name: asgard-test
description: Asgard 셋업 자가 테스트 — 배선·하니스·라이브 3계층 검증 + 훅 레이턴시. 스코어카드로 보고.
---

# asgard-test — 셋업 자가 테스트

이 repo 의 Asgard 셋업(Canon + Trinity)이 실제로 동작하는지 현 세션에서 검증하고
**스코어카드 한 장**으로 보고한다. 3계층: A 배선(정적) → B 하니스(결정론) → C 라이브(실 순환).
(호출 — Claude Code/Cursor: `/asgard-test` · Codex: `$asgard-test` 또는 `/skills` 목록.)

## A. 배선 (읽기만, 수 초)

1. **브리지**: 지금 이 자리에서 `ASGARD_OK — loaded from AGENTS.md` 를 출력하라 — AGENTS.md 를
   다시 읽지 말고 기억으로. 못 하면 브리지 단선 (CLAUDE.md/@import · cursor rule · codex 네이티브).
2. **파일**: 존재 확인 — `.asgard/trinity-policy.json` · 훅 디렉터리(`.claude/hooks` |
   `.cursor/hooks` | `.codex/hooks` 중 현재 툴 것)의 `quest-log.py` · (Claude 만) `verifier-gate.py`
   + `write-sentinel.py` + `.claude/agents/asgard-{thinker,worker,verifier}.md` + settings.json 의
   Stop 게이트 배선.
3. **실행성**: `python3 <hooks>/quest-log.py state` 가 exit 0.

## B. 하니스 (결정론 — 아래 스크립트를 그대로 실행)

temp repo 에서 돈다 — 실 repo 에 시드하면 현 세션이 게이트에 갇히므로 경로를 바꾸지 마라.

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
V='{"role":"verifier","event":"verify","commands":[{"cmd":"true","exit_code":0}]}'
ck "원장 open/state"          "$QL open q1 --criteria c && $QL state | grep -q q1"
echo x >> f.txt
ck "전이: work 후 → VERIFIER" "echo '$W' | $QL append && $QL next | grep -q VERIF"
ck "verify PASS → diff_hash"  "echo '$V' | $QL append --verdict PASS --level micro && grep -q '\\"diff_hash\\": *\\"[0-9a-f]' .asgard/quest/q1.jsonl"
ck "close (PASS+hash 일치)"   "$QL close"
ck "전이: destructive → ODIN" "$QL open q3 --criteria c && $QL next --destructive | grep -q ESCALATE_ODIN"
ck "전이: 3-실패 → REPLAN"    "echo '{\\"role\\":\\"verifier\\",\\"event\\":\\"verify\\",\\"failure_sig\\":\\"s\\",\\"failure_count\\":3,\\"commands\\":[{\\"cmd\\":\\"true\\",\\"exit_code\\":1}]}' | $QL append --verdict FAIL && $QL next | grep -q THINKER_REPLAN"
if [ -n "$GATE" ]; then
  $QL open q2 --criteria c >/dev/null; echo y >> f.txt
  echo "$V" | $QL append --verdict PASS --level micro >/dev/null
  echo z >> f.txt   # PASS 후 변조
  ck "게이트: 변조 → stale block" "echo '{\\"session_id\\":\\"st\\"}' | CLAUDE_PROJECT_DIR=\\"$T\\" python3 vg.py | grep -q block"
  echo "$V" | $QL append --verdict ESCALATE --level full >/dev/null
  ck "게이트: ESCALATE → allow"   "test -z \\"\\$(echo '{\\"session_id\\":\\"st\\"}' | CLAUDE_PROJECT_DIR=\\"$T\\" python3 vg.py)\\""
fi
echo "-- harness: $((n-f))/$n ok"
cd "$SRC" && rm -rf "$T"
```

전부 `ok` 면 통과 — `FAIL` 줄은 스코어카드에 그대로 옮긴다.

## C. 라이브 (현 세션, 실 프로토콜 1순환 — write 몇 턴)

실 repo 에서 마이크로 과업으로 Trinity 순환을 실제로 돈다 (AGENTS.md 트리니티 루프 그대로):

1. `python3 <hooks>/quest-log.py open selftest-live --criteria "python3 selftest_probe.py 가 exit 0"`
2. **[Worker]** `selftest_probe.py` 생성 (`print("probe ok")` 한 줄) → work 이벤트 append.
3. **[Verifier]** Worker 해설 무시, 검증 명령 직접 실행 → verify PASS append (diff_hash 자동 계산).
4. `close` 성공 확인 → **그 다음** `selftest_probe.py` 삭제 (역순이면 stale PASS 로 게이트에 걸린다 —
   그것도 정상 동작 증거지만 순환이 지저분해진다).
5. Claude Code 는 서브에이전트 디스패치(모드 B)가 기본 경로지만 이 테스트는 phase 전환(모드 A)으로
   충분하다 — 크로스툴 동일 경로 검증이 목적.

## 레이턴시 (선택)

`time python3 <hooks>/quest-log.py state` 3회 — median 을 보고. (Claude) Stop 게이트 allow 도 동일.
기준치(M5 Max): state ~97ms · gate allow ~87ms · 비-quest 세션 gate ~24ms.

## 스코어카드 (보고 형식)

| 계층 | 체크 | 결과 |
|---|---|---|
| A 배선 | 브리지 / 파일 / 실행성 | ✅·❌ 각각 |
| B 하니스 | N/N ok (FAIL 항목 명시) | |
| C 라이브 | open→work→verify PASS→close + 정리 | |
| 레이턴시 | state / gate (측정 시) | |

캐비앗을 정직하게: 이 테스트는 **배선·강제화·프로토콜 준수** 검증이다 — 토큰/비용/아웃풋 품질
계측은 세션 안에서 불가하다. 풀 E2E(게이트 유/무 A/B, 비용 실측)는 asgard repo 의
`test/e2e_trinity.sh`. 결함 발견 시 스코어카드에 재현 명령을 첨부하라.
"""
