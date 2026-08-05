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
