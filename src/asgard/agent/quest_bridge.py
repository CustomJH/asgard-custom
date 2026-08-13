#!/usr/bin/env python3
"""퀘스트 로그·게이트를 부르는 자리 — 훅 하나를 한 번 부르는 데 드는 값이 여기서 정해진다.

`session.py` 에서 갈라져 나왔다. 옮긴 이유는 크기가 아니라 축이다: 이 파일이 답하는 질문은
"훅을 프로세스로 부를 것인가, 이 인터프리터 안에서 부를 것인가" 하나뿐이고, 그것은 대화 루프가
답하는 질문과 겹치지 않는다.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import threading


def _ql_timeout(root: str) -> int:
    """append(PASS) 하나가 이 프로세스 안에서 얼마나 오래 걸릴 수 있는가.

    그 호출은 하네스 베이스라인과 계약 명령을 직접 실행한다 (체크당 `baseline_timeout`, 최대
    `MAX_CHECKS` 개). 상한을 상수로 적어 두면 정책이 커질 때 조용히 어긋나고, 그때 죽는 것은
    **이미 끝난 Verifier 턴 전체**다 — 판정을 처음부터 다시 사야 하므로 이 시스템에서 가장 비싼
    실패다. 그래서 정책에서 계산하고, 상한은 실제로 도는 자리(`asgard_hooklib.baseline`)에서
    빌린다. 마지막 120초는 지도 갱신·트리 해시 두 번 같은 나머지 몫이다."""
    from ..hooks.quest_log import DEFAULT_POLICY, MAX_CHECKS, detect_checks, load_policy

    try:
        policy = load_policy(root)
        per_check = int(policy.get("baseline_timeout") or 120)
        checks = min(len(detect_checks(root, policy)), MAX_CHECKS) or 1
    except Exception:  # 정책을 못 읽어도 append 는 돌아야 한다 — 내장 기본값으로 계산
        per_check, checks = int(DEFAULT_POLICY["baseline_timeout"]), 1
    return per_check * (checks + 1) + 120


# 인프로세스 갈래는 `sys.stdout`/`sys.stdin` 을 잠깐 바꿔 끼운다 — 그 둘은 프로세스 전역이라
# wave 병렬 스레드가 동시에 들어오면 서로의 출력을 삼킨다. 락 구간은 가벼운 명령만 지난다
# (무거운 갈래는 프로세스로 빠지므로 이 락 밖에서 돈다).
_QL_LOCK = threading.Lock()


def _ql_heavy(args: tuple[str, ...]) -> bool:
    """이 호출이 하네스 명령을 실제로 실행하는가 — 그렇다면 프로세스 경계와 timeout 이 필요하다.

    `verify-baseline` 과 판정이 붙은 `append` 둘뿐이다. 그 둘은 베이스라인과 criteria 계약 명령을
    직접 돌리므로 벽시계가 분 단위로 열려 있고, 인프로세스에는 그것을 끊을 손이 없다. `--request-stdin`
    은 다른 이유로 뺀다 — 그 갈래는 `sys.stdin.buffer` 를 읽는데 바꿔 끼운 스트림에는 그 면이 없다."""
    return "verify-baseline" in args or "--request-stdin" in args or ("append" in args and "--verdict" in args)


def _ql_inproc(root: str, argv: list[str], stdin: str) -> subprocess.CompletedProcess:
    from ..hooks import quest_log

    out, err = io.StringIO(), io.StringIO()
    with _QL_LOCK:
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = quest_log.main(argv, root=root)
        except SystemExit as exit_:  # argparse 의 사용법 오류 — 프로세스였다면 종료 코드였을 것
            code = int(exit_.code or 0)
        except Exception as exc:  # 훅의 크래시가 부모를 끌고 내려가지 않는다 (프로세스 갈래와 같은 계약)
            err.write(f"{type(exc).__name__}: {exc}")
            code = 1
        finally:
            sys.stdin = saved_stdin
    return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())


def ql(root: str, *args: str, stdin: str = "", session: str = "native") -> subprocess.CompletedProcess:
    """퀘스트 로그 한 번. 무거운 갈래만 프로세스로 나가고 나머지는 이 인터프리터 안에서 돈다.

    26-08-06 실측이 그 갈림을 만들었다: 역할 턴 하나가 이 함수를 29번 부르는데 호출당 210ms 가
    거의 전부 `fork`+`import`+`select.poll` 대기였고, 훅이 하는 일 자체는 파일 몇 개와 git 몇 번이다.
    부르는 쪽은 이미 `asgard.hooks.quest_log` 를 임포트한 같은 인터프리터라 그 왕복은 살 이유가 없다."""
    argv = [*args, "--session", session]
    if not _ql_heavy(args):
        return _ql_inproc(root, argv, stdin)
    return subprocess.run(
        [sys.executable, "-m", "asgard.hooks.quest_log", *argv],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=root,
        timeout=_ql_timeout(root),
    )


def gate(root: str, session: str = "native") -> tuple[bool, str]:
    import json as _json

    p = subprocess.run(
        [sys.executable, "-m", "asgard.hooks.verifier_gate"],
        # `native: true` 는 판정자 독립성 검사 하나를 끈다. 그 검사는 "모델이 정말 판정자를
        # 띄웠는가"를 디스패치 영수증으로 묻는 장치인데, 네이티브 루프에는 그 물음이 없다 —
        # 판정자 세션을 코드가 직접 만들고 읽기 전용 도구로 강제해서(trinity/verdict.py 의
        # `mk_verifier`), 워커가 그 자리를 대신 앉을 수 있는 경로 자체가 없다. 나머지 게이트는
        # 전부 그대로 돈다. 모델이 이 값을 못 넣는 것이 요점이다: 이 페이로드는 루프가 쓴다.
        input=_json.dumps({"session_id": session, "cwd": root, "native": True}),
        capture_output=True,
        text=True,
        cwd=root,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    if '"block"' in (p.stdout or ""):
        try:
            return True, _json.loads(p.stdout)["reason"]
        except Exception:
            return True, p.stdout[:300]
    return False, ""
