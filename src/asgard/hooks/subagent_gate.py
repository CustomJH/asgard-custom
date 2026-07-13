#!/usr/bin/env python3
# Asgard subagent-gate — Trinity 역할 서브에이전트의 로그 규율 강제 (Claude Code SubagentStop).
#
# 모드 B 의 유일한 프롬프트-의존 축은 "역할이 자기 이벤트를 quest 로그에 기록한다"는 계약이다
# (CUS-189: 프롬프트 준수는 가정이 아니라 측정 대상). 이 훅은 그 계약을 코드로 바꾼다 —
# asgard-thinker/worker/verifier 서브에이전트가 활성 quest 에 자기 역할 이벤트를 기록하지 않고
# 종료하면 1회 차단하고 정확한 append 명령을 지시한다 (lazycodex 증거-영수증 게이트 이식).
#
# 차단 알고리즘 (deterministic 만 block, 그 외 전부 allow — fail-open 유지):
#   활성 quest 없음 / 파싱 실패 / 미지의 agent_type → allow (DIRECT·비-Trinity 디스패치 존중)
#   thinker  종료: 마지막 verify 이후 plan 이벤트 없음   → block (재계획 포함)
#   worker   종료: 마지막 verify 이후 work 이벤트 없음   → block
#   verifier 종료: 마지막 work 이후 verify 이벤트 없음   → block
#   verifier PASS 인데 성공 명령 증거 없음               → block (조기 피드백 — Stop 게이트 전에)
#
# 왜 역할당 2회 상한인가: SubagentStop block 루프는 서브에이전트를 인질로 잡는다. 같은 세션에서
# 같은 역할을 2회 차단하면 3번째는 경고와 함께 통과 — 최종 담보는 어차피 Stop 의 verifier-gate
# (diff-hash 물리 대조)다. 이 훅은 조기 교정 장치지 최후 방벽이 아니다.
import json
import os
import re
import sys

MAX_BLOCKS = 2  # 역할당 — 3번째는 통과 (최후 방벽은 verifier-gate)
ROLE_EVENT = {"asgard-thinker": "plan", "asgard-worker": "work", "asgard-verifier": "verify"}
# 역할 이벤트의 "신선도" 기준점 — 이 이벤트 뒤에 자기 이벤트가 있어야 이번 턴 기록으로 인정.
ANCHOR = {"plan": "verify", "work": "verify", "verify": "work"}


def trivial_evidence(cmd):
    """quest_log.py 의 trivial_evidence 와 동일 유지 (단일 출처 원칙)."""
    c = " ".join(str(cmd).split())
    return c in ("true", ":", "exit 0", "echo") or c.startswith("echo ")


def pass_evidence(rec):
    """verifier_gate.py 의 pass_evidence 와 동일 유지 (단일 출처 원칙)."""
    if (rec.get("baseline") or {}).get("state") == "green":
        return True
    return any(
        isinstance(c, dict) and c.get("exit_code") == 0 and not trivial_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    )


def block(root, sid, agent, reason):
    """차단 — 단 세션·역할당 MAX_BLOCKS 회. 초과 시 warn+allow (인질극 방지)."""
    path = os.path.join(root, ".asgard", "subgate-" + sid + ".json")
    counts = {}
    try:
        counts = json.load(open(path))
        counts = counts if isinstance(counts, dict) else {}
    except Exception:
        pass
    n = int(counts.get(agent, 0)) + 1
    counts[agent] = n
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())  # temp+rename — 크래시 절단이 카운터를 리셋하지 않게
        json.dump(counts, open(tmp, "w"))
        os.replace(tmp, path)
    except Exception:
        pass
    if n > MAX_BLOCKS:
        sys.stderr.write(
            "asgard subagent-gate: %s %d회 차단 초과 — 통과 (최종 담보는 verifier-gate)\n" % (agent, MAX_BLOCKS)
        )
        sys.exit(0)
    sys.stdout.write(json.dumps({"decision": "block", "reason": "Asgard subagent-gate: " + reason}, ensure_ascii=False))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        agent = str(data.get("agent_type") or "")
        want = ROLE_EVENT.get(agent)
        if not want:
            sys.exit(0)  # Trinity 역할 아님 (딜리버리 전문가 포함) → 대상 아님
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
        try:
            qid = open(os.path.join(root, ".asgard", "quest", "ACTIVE")).read().strip()
        except Exception:
            sys.exit(0)  # 활성 quest 없음 → DIRECT·탐사 디스패치 존중 (fail-open)
        events = []
        try:
            for line in open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8"):
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            sys.exit(0)  # 로그 읽기 실패 → allow (fail-open)

        anchor = ANCHOR[want]
        last_anchor = max((i for i, e in enumerate(events) if e.get("event") == anchor), default=-1)
        fresh = [e for i, e in enumerate(events) if i > last_anchor and e.get("event") == want]
        hooks_dir = ".claude/hooks"  # SubagentStop 은 Claude Code 전용 이벤트
        if not fresh:
            block(
                root,
                sid,
                agent,
                "%s 가 활성 quest(%s)에 %s 이벤트를 기록하지 않고 종료하려 합니다. 역할 수행은 로그 기록으로만 "
                '성립합니다 — 기록 후 종료하세요: echo \'{"role":"%s","event":"%s",...}\' | '
                'python3 "$CLAUDE_PROJECT_DIR/%s/quest-log.py" append%s'
                % (
                    agent,
                    qid,
                    want,
                    want if want != "verify" else "verifier",
                    want,
                    hooks_dir,
                    " --verdict PASS|FAIL --level micro|full (검증 명령 직접 실행 + commands 기록 필수)"
                    if want == "verify"
                    else "",
                ),
            )
        if want == "verify":
            last = fresh[-1]
            if last.get("verdict") == "PASS" and not pass_evidence(last):
                block(
                    root,
                    sid,
                    agent,
                    "PASS 에 성공한 검증 명령 증거(commands[{cmd,exit_code==0}])가 없습니다. 검증 명령을 직접 "
                    "실행하고 결과를 append 로 재기록하세요 (true/echo 류 무조건-성공 명령은 증거가 아닙니다).",
                )
        # 통과 → 이 역할의 차단 카운터 리셋 (다음 위반은 새로 계수)
        try:
            path = os.path.join(root, ".asgard", "subgate-" + sid + ".json")
            counts = json.load(open(path))
            if isinstance(counts, dict) and agent in counts:
                counts.pop(agent)
                tmp = "%s.%d.tmp" % (path, os.getpid())
                json.dump(counts, open(tmp, "w"))
                os.replace(tmp, path)
        except Exception:
            pass
    except Exception:
        sys.exit(0)  # 훅 자체 오류 = allow — 게이트가 죽어도 서브에이전트를 인질로 잡지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
