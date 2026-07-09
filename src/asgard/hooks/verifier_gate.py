#!/usr/bin/env python3
# Asgard verifier-gate — Canon 10(완료 증명)의 훅 강제 (CUS-122). Claude Code Stop 시점에 실행.
#
# 핵심은 로그 위조 방지가 아니라 **로그 밖 물리 증거 대조**다 (Goodhart 방어, CUS-117 코멘트 B):
# 모델이 로그에 가짜 PASS 를 append 해도 working-tree 상태는 위조할 수 없다. Stop 시점에 diff hash 를
# 재계산해 PASS 레코드의 diff_hash 와 대조한다 — 불일치 = stale PASS(PASS 후 추가 변경)도 잡힌다.
#
# 차단 알고리즘 (deterministic violation 만 block, 그 외 전부 warn+allow — fail-open 유지):
#   활성 quest 없음 / 비-git / 파싱 실패          → allow
#   write 전무 + mutation 명령 전무 (trivial 면제) → allow
#   Verifier PASS 레코드 없음                      → block
#   PASS.diff_hash != 현재 hash (stale PASS)       → block
#   criteria 없음 / 성공 명령 증거 없음            → block
#   full-verify 필요(민감 경로·큰 diff)한데 micro   → block
#
# 왜 블록 3회 상한인가: Stop block → 모델 재시도 → 또 block 의 무한 루프는 Canon 9(3-실패 법칙)
# 위반이다. 같은 세션에서 3회 차단하면 4번째는 경고와 함께 통과시키고 Odin 에스컬레이션을 지시한다.
# 게이트는 자기기만 방어지 인질극 장치가 아니다.
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any

EMPTY = hashlib.sha256(b"").hexdigest()
# quest_log.py 의 DEFAULT_POLICY 와 동일 유지 — 정책 파일이 없어도 두 스크립트가 같은 기준으로 판단.
# dict[str, Any]: 사용자 trinity-policy.json 이 update() 로 섞이므로 값 타입은 런타임에 열려 있다.
DEFAULT_POLICY: dict[str, Any] = {
    "small_write": {"max_files": 2, "max_lines": 80},
    "sensitive_paths": [
        "hooks",
        "policy",
        "templates",
        "install",
        "security",
        "auth",
        "secret",
        "db",
        "migration",
        "ci",
        ".github",
        ".claude",
        ".cursor",
        ".codex",
    ],
    "readonly_commands": [
        "git status",
        "git diff",
        "git log",
        "git show",
        "git ls-files",
        "git rev-parse",
        "rg",
        "grep",
        "ls",
        "cat",
        "head",
        "tail",
        "find",
        "wc",
        "pwd",
        "which",
    ],
}
MAX_BLOCKS = 3  # Canon 9 정합 — 동일 세션 4번째 차단 대신 에스컬레이션


def git(root, *args, binary=False):
    try:
        p = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=60)
        return p.returncode, (p.stdout if binary else p.stdout.decode("utf-8", "replace"))
    except Exception:
        return 1, b"" if binary else ""


# ── quest_log.py 의 diff_state 와 알고리즘 동일 유지 (단일 출처 원칙 — 어긋나면 위양성 차단) ──
# 검증 실행 아티팩트 — quest_log.py 의 _junk 와 동일해야 한다 (양쪽 hash 불일치 = 영구 stale).
# ponytail: 고정 목록 — 정책 파일로 빼면 exclude 확대가 게이트 우회 벡터가 되므로 하드코딩 유지.
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv"}


def _junk(p):
    return p.endswith((".pyc", ".pyo")) or any(seg in _JUNK_DIRS for seg in p.split("/"))


def diff_state(root, base_ref):
    if not base_ref or base_ref == "NONE":
        return EMPTY, [], 0
    spec = [base_ref, "--", ".", ":(exclude).asgard"]
    rc, diff = git(root, "diff", "--binary", *spec, binary=True)
    if rc != 0:
        return EMPTY, [], 0
    _, names = git(root, "diff", "--name-only", *spec)
    _, unt = git(root, "ls-files", "--others", "--exclude-standard", "--", ".", ":(exclude).asgard")
    _, num = git(root, "diff", "--numstat", *spec)
    lines = 0
    for row in num.splitlines():
        parts = row.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            lines += int(parts[0]) + int(parts[1])
    untracked = sorted(p for p in unt.splitlines() if p.strip() and not _junk(p))
    h = hashlib.sha256(diff)
    for p in untracked:
        try:
            body = open(os.path.join(root, p), "rb").read()
            lines += body.count(b"\n") + 1
            h.update(p.encode() + b"\0" + hashlib.sha256(body).digest())
        except Exception:
            h.update(p.encode() + b"\0missing")
    changed = sorted(set(n for n in names.splitlines() if n.strip()) | set(untracked))
    return (h.hexdigest() if changed else EMPTY), changed, lines


def readonly(cmd, allow):
    c = str(cmd).strip()
    return any(c == a or c.startswith(a + " ") for a in allow)


def block(root, sid, reason):
    """차단 — 단 세션당 MAX_BLOCKS 회까지. 초과 시 warn+allow + Odin 에스컬레이션 지시 (Canon 9)."""
    path = os.path.join(root, ".asgard", "gate-blocks-" + sid + ".json")
    n = 0
    try:
        n = int(json.load(open(path)).get("n", 0))
    except Exception:
        pass
    n += 1
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump({"n": n}, open(path, "w"))
    except Exception:
        pass
    if n > MAX_BLOCKS:
        sys.stderr.write(
            "asgard verifier-gate: %d회 차단 초과 — 통과시키되 Odin 에스컬레이션 필요 (Canon 9)\n" % MAX_BLOCKS
        )
        sys.exit(0)
    sys.stdout.write(
        json.dumps(
            {
                "decision": "block",
                "reason": "Asgard verifier-gate (Canon 10 — 완료 증명): "
                + reason
                + " Verifier 판정을 로그에 기록하세요: echo '{...}' | python3 <hooks>/quest-log.py "
                "append --verdict PASS|FAIL (verify 이벤트가 diff_hash 를 자동 계산). "
                "3회 이상 막히면 중단하고 Odin 에게 보고하세요 (Canon 9).",
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)


def orphan_writes(root, sid):
    """quest 로그 없이 끝나려는 세션의 write 흔적 검사 (write-sentinel 기록 대조).
    기록된 경로가 지금도 HEAD 와 다르면 = 검증 안 된 write 가 남아 있다 → 차단.
    되돌린 write(경로 clean)·사용자 기존 dirt(기록에 없음)는 차단하지 않는다.
    예외: 직전 close 된 quest(LAST)의 PASS 가 현재 워킹트리 hash 와 일치하면 이미 검증된 상태 —
    close 직후 Stop 이 방금 검증한 write 를 오차단하지 않게 한다."""
    try:
        writes = json.load(open(os.path.join(root, ".asgard", "writes-" + sid + ".json")))
    except Exception:
        return  # 이 세션의 write 기록 없음 → 게이트 대상 아님
    dirty = []
    for rel in writes[:500]:
        rc, out = git(root, "status", "--porcelain", "--", str(rel))
        if rc == 0 and out.strip():
            dirty.append(str(rel))
    if not dirty:
        return
    try:  # LAST quest 의 PASS 가 현 상태를 물리 증명하면 allow
        qid = open(os.path.join(root, ".asgard", "quest", "LAST")).read().strip()
        events = []
        for line in open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8"):
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
        verdicts = [e for e in events if e.get("event") == "verify" and e.get("verdict") in ("PASS", "ESCALATE")]
        if verdicts and verdicts[-1].get("verdict") == "ESCALATE":
            return  # Canon 9 정규 종료 — close 후에도 인질 금지 (active 경로와 동일 규칙, s1 라이브 실측)
        if base_ref and verdicts and git(root, "rev-parse", "--verify", base_ref)[0] == 0:
            if verdicts[-1].get("diff_hash") == diff_state(root, base_ref)[0]:
                return
    except Exception:
        pass
    block(
        root,
        sid,
        "이 세션이 파일을 썼는데(%s%s) 퀘스트 로그가 없습니다. write 과업은 Trinity "
        "순환이 필수입니다: python3 <hooks>/quest-log.py open <quest-id> --criteria "
        '"..." 로 로그를 열고 Verifier 검증을 기록하세요.'
        % (", ".join(dirty[:3]), " 외 %d" % (len(dirty) - 3) if len(dirty) > 3 else ""),
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
        try:
            qid = open(os.path.join(root, ".asgard", "quest", "ACTIVE")).read().strip()
        except Exception:
            orphan_writes(root, sid)  # quest 미개설 우회 봉합 — write 흔적이 dirty 면 여기서 block
            sys.exit(0)  # write 흔적 없음 → 게이트 대상 아님
        events = []
        try:
            for line in open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8"):
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            sys.exit(0)  # 로그 읽기 실패 → warn+allow (fail-open)
        if not events:
            sys.exit(0)
        base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
        if not base_ref or base_ref == "NONE" or git(root, "rev-parse", "--verify", base_ref)[0] != 0:
            sys.stderr.write("asgard verifier-gate: base_ref 확인 불가 — allow (fail-open)\n")
            sys.exit(0)
        policy = dict(DEFAULT_POLICY)
        try:
            policy.update(json.load(open(os.path.join(root, ".asgard", "trinity-policy.json"))))
        except Exception:
            pass

        current, changed, lines = diff_state(root, base_ref)
        cmds = [c for e in events for c in (e.get("commands") or []) if isinstance(c, dict)]
        mutating = [c for c in cmds if not readonly(c.get("cmd", ""), policy["readonly_commands"])]
        risk_write = any((e.get("risk") or {}).get("has_write") for e in events)
        if current == EMPTY and not risk_write and not mutating:
            sys.exit(0)  # trivial 면제 — write·mutation 전무 + read-only 명령만 (CUS-117 코멘트 D)

        # 판정 레코드 = verify 이벤트의 PASS 또는 ESCALATE. ESCALATE 는 Canon 9 의 정규 종료
        # (close 도 인정) — 오딘 보고 세션을 게이트가 인질로 잡으면 정직한 에스컬레이션이
        # 3회 헛차단 + fail-open 상한에 기대게 된다 (CUS-126 E2E S4 에서 실측된 마찰).
        verdicts = [e for e in events if e.get("event") == "verify" and e.get("verdict") in ("PASS", "ESCALATE")]
        if not verdicts:
            block(root, sid, "write 과업인데 Verifier 판정(PASS/ESCALATE) 레코드가 없습니다.")
        p = verdicts[-1]
        if p.get("verdict") == "ESCALATE":
            try:
                os.remove(os.path.join(root, ".asgard", "gate-blocks-" + sid + ".json"))
            except Exception:
                pass
            sys.exit(0)  # 종료 허용 — 단 완료가 아니라 오딘 결정 대기 상태 (원장에 ESCALATE 가 남는다)
        if p.get("diff_hash") != current:
            block(root, sid, "stale PASS — PASS 기록 이후 워킹트리가 변경되었습니다 (물리 대조 불일치). 재검증 필요.")
        if not any(e.get("criteria") for e in events):
            block(root, sid, "성공 기준(criteria)이 로그에 없습니다. 검증은 기준 없이는 성립하지 않습니다.")
        if not any(c.get("exit_code") == 0 for c in (p.get("commands") or []) if isinstance(c, dict)):
            block(
                root,
                sid,
                "PASS 에 성공한 검증 명령 증거(commands[{cmd,exit_code==0}])가 없습니다. "
                "Verifier 는 검증 명령을 직접 실행해야 합니다.",
            )
        small = policy["small_write"]
        sensitive = [f for f in changed if any(s in f.lower() for s in policy["sensitive_paths"])]
        full_required = bool(sensitive) or len(changed) > small["max_files"] or lines > small["max_lines"]
        if full_required and p.get("level") != "full":
            block(
                root,
                sid,
                "full-verify 필요(민감 경로 %s / diff %d files·%d lines)한데 micro PASS 입니다. "
                "--level full 로 재검증하세요." % (sensitive[:3], len(changed), lines),
            )
        try:  # 통과 → 차단 카운터 리셋 (다음 위반은 새로 3회부터)
            os.remove(os.path.join(root, ".asgard", "gate-blocks-" + sid + ".json"))
        except Exception:
            pass
    except Exception:
        sys.exit(0)  # 훅 자체 오류 = allow — 게이트가 죽어도 세션을 인질로 잡지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
