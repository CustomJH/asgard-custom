"""체크 실행 — 하네스가 직접 돌려서 증거를 만든다.

모델이 "돌렸다"고 적은 것과 하네스가 돌린 것을 구분하려고 실행을 이쪽으로 가져왔다. 상한
시간을 넘긴 체크는 실패가 아니라 `timed_out` 으로 구분해 적는다 — 둘을 뭉치면 느린 스위트가
빨간 판정으로 보인다.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from .contracts import contract_criteria, criteria_contracts
from .paths import quest_dir, read_text
from .policy import load_policy
from .runners import detect_checks
from .session import active_quest

# 한 판정에서 하네스가 실제로 돌리는 체크의 상한. 판정자 주입면이 같은 수를 세어야 한다
# (`verifier_context.commitments`) — 한쪽만 늘리면 판정자가 한 번도 못 본 명령이 PASS 채점에
# 남는다. 상수를 여기 두는 이유가 그것이다: 두 자리에 숫자를 적으면 둘이 갈라진다.
MAX_CHECKS = 10


def fail_lines(stdout: bytes | None, stderr: bytes | None, limit: int = 5) -> list[str]:
    """실패한 체크 출력에서 정형 실패 줄만 추출 — 이유 없는 red를 만들지 않는다 (바운디드 증거).
    pytest 요약 줄(FAILED/ERROR ...) 우선, 없으면 출력 꼬리 3줄. 줄당 200자·최대 limit 줄 —
    수리 턴이 '무엇이 왜 깨졌는지'를 exit code 만으로 추측하지 않게 한다."""
    text = b"\n".join(s for s in (stdout, stderr) if s).decode("utf-8", "replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hits = [ln for ln in lines if ln.startswith(("FAILED ", "ERROR ")) or "AssertionError" in ln]
    return [ln[:200] for ln in (hits or lines[-3:])[:limit]]


def _timed_out_before(events: list[dict], cmd: str) -> bool:
    """이 퀘스트에서 이미 시간을 다 쓰고 끊긴 체크인가.

    timeout 은 red 도 green 도 아니라 증거 없음이다 (run_baseline 의 skip 규약). 그래서 다시
    돌려도 판정은 한 글자도 안 바뀌고, append 마다 baseline_timeout 만큼 더 기다리기만 한다.
    26-08-04 실측: 이 저장소의 `uv run pytest -x -q` 는 615s 인데 baseline_timeout 은 120s 라
    verify append 가 매번 120s 를 태우고 아무 증거도 못 얻었다."""
    return any(_timed_out_row((event.get("baseline") or {}).get("results"), cmd, 120) for event in events)


def _timed_out_row(rows, cmd: str, width: int | None = None) -> bool:
    """기록된 실행 행 중 이 명령이 timeout 으로 끊긴 것이 있는가.

    `width` 는 그 표면이 cmd 를 자르는 길이다. 계약 표면은 안 자르므로 (`run_criteria_checks` 의
    행은 로그가 아니라 결속 키다) None 이고, 베이스라인 표면만 120자를 넘긴다."""
    target = cmd if width is None else cmd[:width]
    return any(isinstance(r, dict) and r.get("timed_out") and r.get("cmd") == target for r in rows or [])


def _contract_timed_out_before(events: list[dict], cmd: str, budget: int, diff_hash: str) -> bool:
    """이 퀘스트에서 이미 timeout 으로 끊긴 계약 명령인가 — **같은 상한, 같은 트리에서만** 그렇다.

    이 메모에는 무효화 축이 없었다. 한 번 timeout 이 적히면 그 뒤로는 명령을 아예 안 돌리고
    같은 행을 다시 적었고, 상한을 올려도 코드를 고쳐도 다시 재지 않았다 — 26-08-12 에 경합으로
    한 번 늦은 계약이 그렇게 세 턴 연속 미충족으로 굳었다 (단독 실행 44.4초, 상한 120초).
    그래서 축을 둘 준다: 그때의 상한과 그때의 트리. 둘 중 하나라도 다르면 다시 잰다.

    상한을 안 적은 옛 행은 메모로 안 친다. 축이 없는 기록으로는 "같은 조건" 을 말할 수 없고,
    한 번 더 재는 값이 영영 안 닫히는 퀘스트보다 싸다.
    """
    for event in events:
        for row in event.get("criteria_checks") or []:
            if not (isinstance(row, dict) and row.get("timed_out") and row.get("cmd") == cmd):
                continue
            if row.get("budget") != budget:
                continue
            recorded = event.get("diff_hash")
            if diff_hash and recorded and recorded != diff_hash:
                continue
            return True
    return False


# `pytest` 바로 앞에 설 수 있는 것들 — 러너 두 개와 셸 경계. 이 중 하나가 앞에 있거나 명령의 첫
# 토큰일 때만 pytest 호출로 친다 (`_in_program_slot`).
_RUNNER_LEADS = {"run", "-m", "&&", "||", ";", "|", "("}


def _in_program_slot(tokens: list[str], at: int) -> bool:
    """`tokens[at]` 이 실행되는 프로그램 자리인가 — 인자나 문자열에 스친 한 마디가 아니라.

    러너와 프로그램 사이의 긴 옵션은 건너뛴다: `uv run --no-project pytest` 도 `uv run pytest` 와
    같은 호출이고, AGENTS.md 가 계약 명령에 쓰는 형태가 그것이다. 짧은 옵션은 안 건너뛴다 —
    `-m` 자체가 러너 표식이고, 값을 따로 받는 짧은 옵션(`-p no:xdist`)은 뒤 토큰이 프로그램 자리로
    보이면 안 된다."""
    while at > 0 and tokens[at - 1].startswith("--"):
        at -= 1
    return at == 0 or tokens[at - 1] in _RUNNER_LEADS


def _parallel_pytest(cmd: str) -> str | None:
    """이 명령을 xdist 로 돌린 형태 — pytest 호출이 아니거나 이미 병렬 인자가 있으면 None.

    바꾸는 것은 스케줄뿐이고 무엇을 도는지는 그대로다. `-n auto` 는 `pytest` 토큰 바로 뒤에
    끼운다 — 끝에 붙이면 `&&` 나 파이프 뒤의 다른 명령에 붙는다.
    이 저장소 실측(26-08-05): `tests/test_trinity.py` 직렬 352초 → `-n 8` 68.6초(238건 전량 통과),
    전체 스위트 836초 → `-n auto` 282초(4,941건 전량 통과)."""
    tokens = cmd.split()
    # `no:xdist` 는 토큰이 아니라 글자로 찾는다 — `-p no:xdist` 와 `-pno:xdist` 가 같은 뜻인데
    # 토큰만 보면 붙여 쓴 쪽이 유일한 탈출구를 그냥 지나친다.
    if "no:xdist" in cmd or any(t.startswith(("-n", "--numprocesses")) for t in tokens):
        return None
    # `pytest` 가 **프로그램 자리**에 있을 때만이다 — 판정은 `_in_program_slot`. 토큰만 찾으면
    # `echo pytest` 나 경로에 스친 한 마디까지 잡아 인자를 엉뚱한 명령에 붙인다.
    at = next((i for i, t in enumerate(tokens) if t == "pytest" and _in_program_slot(tokens, i)), None)
    if at is None:
        return None
    return " ".join(tokens[: at + 1] + ["-n", "auto"] + tokens[at + 1 :])


def _run_check(cmd: str, root: str, timeout: int, parallel_ok: bool = True):
    """(exit_code, CompletedProcess, 선언과 다르게 실행했다면 그 명령 — 같으면 None).

    pytest 는 xdist 로 먼저 돌리되 **초록만 병렬이 결정한다.** 초록이 아니면 무엇이 나왔든 선언
    원문으로 다시 돌려 그 종료 코드를 판정에 쓴다.

    코드별로 예외를 두지 않는 이유: xdist 는 종료 코드를 자기 방식으로 다시 매긴다. 같은 트리
    같은 명령이 직렬 대 병렬로 사용법 오류 4 대 5, `-x` 중단 1 대 2, `-k` 무매치 4 대 3 을 낸다
    (26-08-05 실측). `run_baseline` 의 분류는 2·3·4·5 를 skip 으로 접으므로, 재사상 하나를 놓칠
    때마다 빨간 게이트가 사유 한 줄 없이 꺼진다 — 목록을 넓히는 수리를 두 번 했고 두 번 다 남은
    코드가 있었다. 열거를 그만두고 규칙을 뒤집는다.

    덤으로 병렬 안전하지 않은 스위트의 거짓 red 도 여기서 걸린다: 병렬에서 깨져도 직렬이 초록이면
    기록되는 것은 직렬의 0 이다. `parallel_ok=False` (`trinity_policy.baseline_parallel: false`) 는
    그 재실행 값마저 아까운 저장소를 위한 손잡이다.

    값은 빨간 경우에만 든다 — 초록은 병렬 한 번으로 끝난다. 빨간 판정에는 어차피 사람이 손으로
    재현할 직렬 명령과 `fails` 줄이 필요하다.
    timeout 은 여기서 안 잡는다: 병렬이 상한을 넘었다면 직렬은 더 오래 걸려 재시도가 손해고,
    호출부가 `TimeoutExpired` 를 그대로 기록한다."""
    parallel = _parallel_pytest(cmd) if parallel_ok else None
    if parallel:
        p = subprocess.run(parallel, shell=True, cwd=root, capture_output=True, timeout=timeout)
        if p.returncode == 0:
            return 0, p, parallel
    p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, timeout=timeout)
    return p.returncode, p, None


def run_baseline(root: str, policy: dict, events: list[dict], diff_hash: str) -> dict | None:
    """체크 전부 실행 → {"state": green|red|none, "results": [...]}. 체크 없음 → None (요건 면제).
    같은 diff_hash의 기존 verify 기록은 재사용 — 동일 트리에 pytest를 두 번 돌리지 않는다.
    skip(127 미설치·pytest 5 수집 없음·timeout)은 red 아님 — 게이트는 자기기만 방어지 인질극 장치가
    아니다 (verifier_gate.py 서두와 같은 원칙). lagom: timeout=skip은 보호 약화 — 느린 스위트는
    baseline_timeout 상향으로 대응."""
    checks = detect_checks(root, policy)
    if not checks:
        return None
    for e in reversed(events):
        bl = e.get("baseline")
        if bl and e.get("event") == "verify" and e.get("diff_hash") == diff_hash:
            return {**bl, "cached": True}
    timeout = int(policy.get("baseline_timeout") or 120)
    auto = not policy.get("baseline_checks")  # 자동 감지 모드 — red 판정을 보수적으로 (아래)
    results: list[dict] = []
    state = "none"
    for cmd in checks[:MAX_CHECKS]:
        if _timed_out_before(events, cmd):
            results.append({"cmd": cmd[:120], "exit_code": None, "secs": 0.0, "timed_out": True, "memo": True})
            continue
        t0 = time.time()
        code: int | None
        p = None
        timed_out = False
        run_cmd = None
        try:
            code, p, run_cmd = _run_check(cmd, root, timeout, policy.get("baseline_parallel", True))
        except subprocess.TimeoutExpired:
            code, timed_out = None, True  # skip 취급 (fail-open) — 다음 append 는 memo 로 건너뛴다
        except Exception:
            code = None  # 그 밖의 실행 실패도 skip
        row: dict = {"cmd": cmd[:120], "exit_code": code, "secs": round(time.time() - t0, 1)}
        if run_cmd:
            # 자르지 않는다 — 잘린 명령은 온전해 보이면서 파일을 빠뜨리고, 붙여 넣으면 다른 답을 낸다
            # (이 저장소 베이스라인은 선언 221자·병렬 229자라 200에서 경로 한가운데가 끊겼다).
            row["run_cmd"] = run_cmd
        if timed_out:
            row["timed_out"] = True
        results.append(row)
        # skip = 체크가 "돌 수 없었다": 127 미설치 · pytest 5 수집 없음 · timeout. 자동 감지 pytest는
        # 2/3/4(수집·사용법 오류 — venv 밖 pytest가 흔한 원인)도 skip — 환경 문제를 코드 red로
        # 오판해 게이트가 인질 잡는 것 방지. 명시 설정 체크는 사용자가 커맨드를 보증하므로 엄격 판정.
        if code is None or code == 127 or ("pytest" in cmd.split() and (code == 5 or (auto and code in (2, 3, 4)))):
            continue
        if code != 0:
            if p is not None:
                fails = fail_lines(p.stdout, p.stderr)
                if fails:
                    row["fails"] = fails  # 정형 실패 줄 — 게이트 사유·수리 턴 컨텍스트로 흐른다
            state = "red"
            break  # 첫 red에서 중단 — 나머지는 수리 후 어차피 재실행
        state = "green"
    return {"state": state, "results": results}


def baseline_ran(root: str, policy: dict, baseline: dict | None) -> dict[str, dict]:
    """이번 판정에서 baseline 이 이미 돌린 명령 → 그 실행 행 (정규화된 명령이 키다).

    두 판정 경로(append·verify-baseline)가 각자 이 짝을 세우면 한쪽만 고쳐진다 — 실제로 그랬다.
    baseline 은 detect_checks 순서대로 돌고 첫 red 에서 멈추므로 zip 이 실행된 만큼만 짝짓는다."""
    return {
        " ".join(cmd.split()): row
        for cmd, row in zip(detect_checks(root, policy), (baseline or {}).get("results") or [])
        if isinstance(row, dict)
    }


def run_criteria_checks(
    root: str, policy: dict, criteria, events: list[dict], diff_hash: str, ran: dict[str, dict] | None = None
) -> list[dict] | None:
    """계약 명령을 하네스가 직접 실행해 기록 — stdin 위조는 normalize가 버리고 이 코드만이
    기록 경로 (baseline과 동일). 같은 diff_hash의 기존 기록은 재사용. 계약 없음 → None (요건 면제).

    `ran`은 이번 append 에서 baseline 이 이미 돌린 명령의 결과다(정규화 명령 → 실행 행). 계약이
    baseline 체크와 같은 명령이면 — `verify: uv run pytest -q` 처럼 흔하다 — 같은 트리에서 같은
    스위트를 한 번 더 돌릴 이유가 없다. 물리적으로 같은 실행이고 둘 다 하네스 소유 기록이라
    판정은 그대로고 append 시간만 절반이 된다."""
    contracts = [c for c in criteria_contracts(criteria) if c["verify_cmd"]]
    if not contracts:
        return None
    # 재사용 조건은 트리가 같은 것만으로는 부족하다 — **선언된 명령을 전부 담은** 기록이어야 한다.
    # 기준 수정(`quest-log.py amend-criteria`)은 트리를 안 바꾸므로 diff_hash 만 보면 옛 명령의
    # 결과가 새 계약의 답으로 돌아온다. 그러면 `unmet_contracts` 는 새 명령을 기록에서 못 찾아
    # 영영 미충족이고, close 는 닫히지 않는다 — 계약만 잘못 적혔고 코드는 다 선 경우가 그 동사의
    # 주 용례라 정작 필요한 자리에서 못 쓰인다.
    wanted = {" ".join(str(c["verify_cmd"]).split()) for c in contracts}
    for e in reversed(events):
        cc = e.get("criteria_checks")
        if cc and e.get("event") == "verify" and e.get("diff_hash") == diff_hash:
            have = {" ".join(str(r.get("cmd", "")).split()) for r in cc if isinstance(r, dict)}
            if not wanted <= have:
                break  # 기록이 안 담은 명령이 있다 — 이 트리에서 직접 돌린다
            return [{**c, "cached": True} for c in cc if isinstance(c, dict)]
    timeout = int(policy.get("baseline_timeout") or 120)
    results: list[dict] = []
    for c in contracts:
        cmd = c["verify_cmd"]
        shared = (ran or {}).get(" ".join(cmd.split()))
        if shared and shared.get("exit_code") is not None:
            # `cmd` 는 자르지 않는다 — 이 행은 로그가 아니라 **결속 키**다. `unmet_contracts` 가
            # 선언된 명령 원문으로 이 표를 찾으므로, 잘라 두면 그보다 긴 계약은 exit 0 을 받고도
            # 영영 미충족으로 남는다 (26-08-05 실측: 207자 계약 하나가 판정을 무한 재판정으로).
            results.append({**shared, "cmd": cmd, "shared": True})
            continue
        if _contract_timed_out_before(events, cmd, timeout, diff_hash):
            # 계약 명령이 timeout 보다 느리면 그 계약은 **이 상한과 이 트리에서는** 충족될 수 없다.
            # 미충족은 그대로 두되(기준 유지) 같은 대기를 append 마다 다시 사지는 않는다 — 판정은
            # 안 바뀌고 재검증 턴마다 timeout 만큼만 늘어나던 자리다. 상한이나 트리가 바뀌면
            # `_contract_timed_out_before` 가 이 갈래를 안 태우고 다시 잰다.
            results.append(
                {"cmd": cmd, "exit_code": None, "secs": 0.0, "timed_out": True, "memo": True, "budget": timeout}
            )
            continue
        t0 = time.time()
        code: int | None
        timed_out = False
        run_cmd = None
        try:
            code, _, run_cmd = _run_check(cmd, root, timeout, policy.get("baseline_parallel", True))
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
        except Exception:
            code = None  # 미충족 취급 (계약은 명시 선언이라 skip 면제 없음)
        # 결속 키는 선언 원문(`cmd`)이다 — 병렬로 돌렸다면 그 사실만 따로 적는다. 계약이 무엇을
        # 검사했는지는 안 바뀌고, Odin 이 읽는 계약 문자열도 선언한 그대로 남는다.
        row: dict = {"cmd": cmd, "exit_code": code, "secs": round(time.time() - t0, 1)}
        if run_cmd:
            row["run_cmd"] = run_cmd
        if timed_out:
            # 상한을 함께 적는다 — 이것이 메모의 무효화 키다. 안 적으면 다음 턴이 "무슨 조건에서
            # 늦었는지" 를 모른 채 같은 결론을 물려받는다.
            row["timed_out"] = True
            row["budget"] = timeout
        results.append(row)
    return results


def _declared_verify_commands(root: str) -> list[str]:
    """활성 퀘스트가 **개봉 기록과 기준 수정 기록에** 선언한 verify 계약 명령.

    개봉 기록과 `amend` 이벤트 둘만 본다. 그 밖의 이벤트에 실린 criteria 까지 세면 읽기전용 역할이
    진행 중인 퀘스트에 자기 허용을 덧붙일 수 있다 — 그 역할은
    `quest-log.py append --criteria "... | verify: <명령>"` 을 부를 수 있고(읽기전용 레인이 기장
    쓰기를 허용한다), 그러면 아래 함수가 그 문자열을 하네스 소유로 읽는다. `amend` 는 raw append
    로 못 적는다 (`ledger.APPEND_EVENTS`).

    이것이 막는 것은 거기까지다. `open` 도 같은 레인에서 허용되므로, 읽기전용 역할이 계약을 실은
    퀘스트를 새로 열면 그 계약이 다시 개봉 기록이 된다. 그래도 실행 능력은 안 늘어난다 — 하네스가
    `run_criteria_checks` 에서 그 문자열을 `shell=True` 로 어차피 돌린다. 문이 옮겨질 뿐이다.

    수정 기록을 여기서도 읽는 이유는 두 소비처가 갈리면 안 되기 때문이다. 하네스는 수정된 계약을
    돌리는데(`effective_criteria`) 이 함수가 개봉 계약만 알면, 판정자는 자기가 채점받는 명령을
    받아 놓고 그것을 못 돌린다 — 26-08-14 판정이 그 자리에서 계약 명령 대신 하네스 모듈을 임포트해
    같은 수를 재는 우회로 섰고, 그 우회는 검증 독립성의 근거를 판정자 손에서 뺀다."""
    qid = active_quest(root)
    if not qid:
        return []
    criteria: list = []
    opening_read = False
    for line in read_text(os.path.join(quest_dir(root), qid + ".jsonl")).splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            return []  # 기록 한 줄을 못 읽으면 무엇이 선언됐는지도 말할 수 없다
        # 개봉 기록은 첫 줄 **하나**다. "아직 계약을 못 찾았으면 계속 본다"로 적으면 기준 없이
        # 열린 퀘스트에서 둘째 줄이 개봉 기록 자리를 차지해, 이 함수가 막으려던 그 문이 열린다.
        if not opening_read:
            opening_read = True
            criteria = contract_criteria(event.get("criteria"))
        elif event.get("event") == "amend" and event.get("criteria"):
            criteria = contract_criteria(event.get("criteria"))
    contracts = criteria_contracts(criteria)
    return [c["verify_cmd"] for c in contracts if c.get("verify_cmd")]


def harness_owned_command(root: str, command: str) -> bool:
    """하네스가 PASS 를 적을 때 자기 손으로 돌리는 명령인가 — 읽기전용 레인의 유일한 예외.

    판정자 주입면은 이 판정이 무엇으로 채점되는지를 판정자에게 알려 준다: 선언된 verify 계약과
    프로젝트 베이스라인 (`verifier_context.commitments`). 알려 주고 실행은 막으면 판정자는 채점
    기준을 알고도 그것을 못 돌린다. 26-08-14 판정이 그 자리에 걸려, 계약 명령 대신 하네스 모듈을
    임포트해 같은 수를 재는 우회로 판정을 세웠다 — 그 우회는 "판정자가 검증 명령을 직접 돌린다"는
    검증 독립성의 근거를 판정자 손에서 뺀다.

    넓히는 것은 허용 목록이 아니라 **출처**다. 여기를 통과하는 문자열은 하네스가 어차피 돌리는
    바로 그것이므로 이 완화가 새로 여는 실행 능력은 없다 — 판정자가 안 돌려도 하네스가 돌린다.
    그래서 정확히 일치할 때만 통과한다: 인자 하나가 달라지면 그것은 하네스가 돌리는 명령이 아니라
    판정자가 고른 임의 실행이다. 공백만 접어서 비교하는 이유는 계약 원문과 정책에 적힌 형태가
    들여쓰기로 갈릴 수 있어서다.

    베이스라인은 `MAX_CHECKS` 까지만 센다. 하네스가 상한 밖 명령을 안 돌리므로, 그 뒤를 열면
    "하네스가 어차피 돌린다"는 이 함수의 근거가 그 명령에는 성립하지 않는다."""
    target = " ".join(command.split())
    if not target:
        return False
    try:
        owned = list(detect_checks(root, load_policy(root))[:MAX_CHECKS])
        owned += _declared_verify_commands(root)
    except Exception:
        return False  # 출처를 못 읽으면 완화하지 않는다 — 이 레인의 기본은 막는 쪽이다
    return any(target == " ".join(str(cmd).split()) for cmd in owned)
