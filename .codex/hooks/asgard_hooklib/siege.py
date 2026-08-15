"""배차 장부에 한 줄 적으라고 CLI 에 던지는 문 — 훅 둘이 나눠 쓴다.

**왜 임포트가 아니라 프로세스인가.** 훅은 배포본에서 `uv run --no-project python
<hooks>/<hook>.py` 로 돈다. 그 인터프리터에는 `asgard` 가 없다 (26-08-06 실측: 갓 세팅한
프로젝트에서 `find_spec('asgard')` → None). 그런데 장부를 적는 두 자리
(`subagent_gate.siege_open/close`, `tickets._siege_mirror`)는 둘 다 `from asgard import
orchestration` 으로 시작했고, 둘 다 fail-open 이라 실패가 조용했다. 그래서 호스트
세 모드에서 `asgard siege` 는 **한 번도** 장부를 채운 적이 없다 — 코드는 다 있는데
임포트 한 줄이 늘 실패하고 있었다.

**왜 답을 안 기다리는가.** 장부는 퀘스트 로그에서 파생된 기록이고, 부르는 쪽은 사람이
기다리는 자리다 (서브에이전트 디스패치·티켓 전이). 답을 기다리면 CLI 기동 시간이 그대로
얹힌다. 적히는 시점이 조금 늦는 것은 장부에 아무 해가 없다 — `siege show` 는 언제나 지금
적힌 것을 보여 준다.

`asgard` 가 PATH 에 없으면 아무 일도 안 한다. 장부를 얻으려다 정본의 전이를 잃지 않는다.
"""

from __future__ import annotations

import json
import shutil
import subprocess


def ledger_call(root: str, argv: list[str]) -> bool:
    """`asgard siege <argv>` 를 띄우고 곧바로 돌아온다. 띄웠으면 True.

    반환값은 시험용이다 — 부르는 쪽은 성공도 실패도 똑같이 넘어간다.
    """
    try:
        binary = shutil.which("asgard")
        if not binary:
            return False
        subprocess.Popen(  # noqa: S603 — 인자는 전부 부르는 쪽이 만든 값이고 셸을 안 거친다
            [binary, "siege", *argv, "--json"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return False
    return True


def ledger_read(root: str, argv: list[str], timeout: float = 8.0) -> dict | list | None:
    """`asgard siege <argv> --json` 의 답을 기다려 파싱해 돌려준다. 못 얻으면 None.

    `ledger_call` 과 갈리는 이유는 자리가 다르기 때문이다. 저쪽은 장부에 한 줄 적고 마는
    파생 기록이라 답이 필요 없다. 이쪽은 우편함에서 **무엇을 받았는지**가 곧 결과이고,
    그것을 못 읽으면 훅이 주입할 내용 자체가 없다. 그래서 CLI 기동 시간을 그대로 부담한다 —
    부르는 쪽이 먼저 sqlite 조회로 받을 것이 있는지 확인한 뒤에만 이 문을 쓰는 이유다.

    CLI 기동이 `timeout` 을 넘기면 죽이고 None 을 준다. 훅은 사람이 기다리는 자리라
    무한정 붙잡고 있을 수 없다.
    """
    try:
        binary = shutil.which("asgard")
        if not binary:
            return None
        done = subprocess.run(  # noqa: S603 — 인자는 부르는 쪽이 만든 값이고 셸을 안 거친다
            [binary, "siege", *argv, "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
        if done.returncode != 0:
            return None
        return json.loads(done.stdout or "null")
    except Exception:
        return None
