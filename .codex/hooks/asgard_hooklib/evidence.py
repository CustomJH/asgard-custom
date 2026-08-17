"""증거의 품질 — 실행된 명령이 무엇을 보였는가.

`trivial_evidence` 는 26-08-06 까지 세 훅에 세 판본으로 살아 있었고 subagent-gate 의 것은
`true`·`echo` 만 아는 두 줄짜리였다. 그래서 같은 `ls` 한 줄이 Stop 게이트에서는 증거가 아니고
SubagentStop 게이트에서는 증거였다. 판정 술어를 한 자리에 두는 이유가 그것이다.
"""

from __future__ import annotations

import json
import os
import shlex


def trivial_evidence(cmd) -> bool:
    """verifier_gate.py의 trivial_evidence와 동일 유지 (단일 출처 원칙) — `true` 한 방이 PASS
    증거로 성립하던 Goodhart 구멍 봉합: 무조건 exit 0 이거나 관찰만 하는 명령은 검증 증거가 아니다."""
    try:
        tokens = shlex.split(str(cmd), posix=True)
    except ValueError:
        return True
    if not tokens:
        return True
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"|", "||", "&&", ";"}:
            segments.append([])
        else:
            segments[-1].append(token)
    observational = {
        ":",
        "awk",
        "cat",
        "date",
        "echo",
        "file",
        "find",
        "head",
        "ls",
        "od",
        "printf",
        "pwd",
        "sed",
        "sleep",
        "stat",
        "tail",
        "tree",
        "true",
        "type",
        "wc",
        "which",
        "whoami",
        "xxd",
    }
    for segment in segments:
        while segment and ("=" in segment[0] and not segment[0].startswith(("=", "-"))):
            segment = segment[1:]
        if not segment:
            continue
        head = os.path.basename(segment[0])
        if head in {"sh", "bash", "zsh"} and any(flag in segment for flag in ("-c", "-lc")):
            index = next(i for i, token in enumerate(segment) if token in ("-c", "-lc"))
            if index + 1 < len(segment) and not trivial_evidence(segment[index + 1]):
                return False
            continue
        if head == "git":
            sub = next((token for token in segment[1:] if not token.startswith("-")), "")
            if sub == "diff" and any(flag in segment for flag in ("--check", "--quiet", "--exit-code")):
                return False
            if sub in {"grep", "rev-parse"}:
                return False
            continue
        if head not in observational and not (head == "exit" and segment[1:] == ["0"]):
            return False
    return True


_GIT_INSPECT_SUBS = {"status", "diff", "log", "show", "ls-files"}


def inspection_evidence(cmd) -> bool:
    """워킹트리 상태를 직접 관측하는 read-only git 명령 — 무변경(diff 0) 퀘스트 한정 PASS 증거.

    trivial 필터는 '아무 exit 0 명령'이 증거로 성립하는 Goodhart를 막는 축이고, 이 판정은
    별개 축이다: '변경 없음' 주장의 올바른 검증은 트리 관측(git status/diff) 그 자체인데,
    관측 명령이 전부 trivial로 걸러지면 무변경 퀘스트는 영원히 PASS가 불가능한 교착이 된다
    (26-07-21 "안녕" 실측 — Verifier PASS 5연속 무효화 후 예산 소진)."""
    try:
        tokens = shlex.split(str(cmd), posix=True)
    except ValueError:
        return False
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"|", "||", "&&", ";"}:
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        while segment and ("=" in segment[0] and not segment[0].startswith(("=", "-"))):
            segment = segment[1:]
        if not segment or os.path.basename(segment[0]) != "git":
            continue
        sub, rest, index = "", segment[1:], 0
        while index < len(rest):
            token = rest[index]
            if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
                index += 2  # 옵션 인자 스킵 — `git -C <path> status`의 <path> 를 sub로 오인 금지
                continue
            if token.startswith("-"):
                index += 1
                continue
            sub = token
            break
        if sub in _GIT_INSPECT_SUBS:
            return True
    return False


def pass_evidence(rec: dict, *, no_change: bool = False) -> bool:
    """PASS 레코드의 성공 명령 증거 — trivial 명령 제외 (verifier_gate.py와 동일 유지).
    하네스가 직접 돌린 베이스라인 green·전 계약 성공(criteria_checks)은 그 자체가 물리 증거 —
    trivial 필터는 모델이 고른 명령에만 적용한다 (둘 다 하네스 소유 기록, 모델 위조 불가).
    no_change=True (하네스 관측 diff가 EMPTY) 면 트리 관측 명령(git status/diff)도 증거다 —
    무변경 주장에는 관측이 곧 검증이며, 아니면 no-op 퀘스트가 영구 FAIL로 교착한다."""
    if (rec.get("baseline") or {}).get("state") == "green":
        return True
    checks = [c for c in (rec.get("criteria_checks") or []) if isinstance(c, dict)]
    if checks and all(c.get("exit_code") == 0 for c in checks):
        return True  # 계약 명령 전부 성공 — 하네스가 직접 실행한 기록
    if no_change and any(
        isinstance(c, dict) and c.get("exit_code") == 0 and inspection_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    ):
        return True
    return any(
        isinstance(c, dict) and c.get("exit_code") == 0 and not trivial_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    )


def evidence_items(rec: dict) -> dict[str, list[str]]:
    """PASS 를 떠받치는 성공 증거를 출처별로 모은다 — baseline / contract / adhoc.

    출처를 나누는 이유는 셋의 위조 난이도가 다르기 때문이다. `baseline` 은 하네스가 프로젝트
    소유 체크를 직접 돌린 기록, `contract` 는 criteria 에 선언해 하네스가 다시 돌린 명령,
    `adhoc` 은 Verifier 가 그 자리에서 고른 명령이다. 앞의 둘은 모델이 결과를 못 바꾼다.

    같은 명령 문자열은 한 번만 센다 — 되풀이 실행은 새 증거가 아니다."""
    items: dict[str, list[str]] = {"baseline": [], "contract": [], "adhoc": []}
    if (rec.get("baseline") or {}).get("state") == "green":
        items["baseline"].append("baseline green")
    for check in rec.get("criteria_checks") or []:
        if isinstance(check, dict) and check.get("exit_code") == 0:
            items["contract"].append(str(check.get("cmd", "")))
    for command in rec.get("commands") or []:
        if isinstance(command, dict) and command.get("exit_code") == 0 and not trivial_evidence(command.get("cmd", "")):
            items["adhoc"].append(str(command.get("cmd", "")))
    return {kind: sorted(set(cmds)) for kind, cmds in items.items()}


def evidence_breadth(rec: dict) -> int:
    """서로 다른 성공 증거의 수. `pass_evidence` 가 '있는가'면 이건 '몇 개인가'다.

    있는가만 물으면 계약 명령 하나로 어떤 크기의 변경도 닫힌다 — 26-08-06 실측에서 5파일
    리팩터가 `python3 test_basic.py` exit 0 하나로 PASS 했다. 계약을 한 줄로 쓰는 건 어려운
    과업일수록 쉬우므로, 있는가만 보는 문턱은 난이도가 올라갈수록 낮아진다."""
    return sum(len(cmds) for cmds in evidence_items(rec).values())


# 읽을 수 없는 영수증 두 종 — 파일이 안 열리거나(OSError) JSON 이 아니거나(JSONDecodeError 는
# ValueError). 이름을 붙여 두는 이유는 `paths.UNREADABLE_RECEIPT` 와 같다: `except Exception` 은
# 진짜 결함까지 삼키고, 이 함수는 거짓이 정상 답이라 삼킨 자리가 겉으로 안 드러난다. 사본인 것은
# 두 모듈이 같은 등급이라 서로 임포트하지 않기 때문이다 (배포 계약 — tests/architecture/packages.py 의 등급표).
# 괄호를 벗기지 않는 이유도 있다: 괄호 없는 형태는 Python 3.14 문법이고, 훅은 사용자 환경의
# 인터프리터로 도는 자립 파일이다.
_UNREADABLE = (OSError, ValueError)


def harness_verdict(rec: dict) -> bool:
    """이 판정을 하네스가 적었는가 — `verify-baseline` 이 남기는 `role: harness`.

    하네스 판정에는 판정자 자리가 없다. 명령을 고른 것도 돌린 것도 실행 결과를 읽은 것도 전부
    코드라, 누가 그것을 적었는지 물을 대상이 없다."""
    return str(rec.get("role") or "").lower() == "harness"


def verifier_dispatched(root: str, qid: str) -> bool:
    """이 퀘스트에서 판정자 자리가 실제로 따로 섰는가 — 디스패치 영수증이 유일한 증거다.

    로그의 `role` 필드는 이것을 답하지 못한다. 그 값은 이벤트를 적는 쪽이 자기 손으로 채우므로,
    워커가 `{"role":"VERIFIER"}` 를 적으면 로그상으로는 판정자가 돈 것과 한 글자도 다르지 않다.
    26-08-13 helios-asgard 실측이 정확히 그 모양이었다 — 전이 함수가 VERIFIER 를 12회 배정했고,
    12회 다 같은 세션이 자기 diff 에 PASS 를 적었으며, 서브에이전트 배차는 0건이었다.

    영수증(`subagent_gate.record_agent_start`)은 호스트가 서브에이전트를 띄울 때 훅이 적는다.
    모델이 만질 수 없는 기록이라 이 물음의 답이 된다. 없으면 거짓이다 — 서브에이전트가 없는
    모드에서도 거짓이고, 그쪽은 `verifier_independence` 정책이 면제한다."""
    directory = os.path.join(root, ".asgard", "quest", "receipts", qid)
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    for name in names:
        if not name.startswith("agent-"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                record = json.load(handle)
        except _UNREADABLE:
            continue  # 못 읽는 영수증은 없는 것으로 — 판정을 막을 근거가 못 된다
        if str(record.get("agent_type") or "").lower().replace("_", "-").endswith("verifier"):
            return True
    return False
