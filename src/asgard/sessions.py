"""세션 정본 — 이 세션이 어느 에이전트인가를 키가 정한다.

지금까지 "이 세션은 누구인가"의 답은 프로세스 주변 상태에 있었다: `ASGARD_PROFILE` 환경변수와
`~/.asgard/active_profile` 파일. 둘 다 프로세스 전체를 덮으므로 한 기계에서 세션 둘이 서로 다른
에이전트로 못 돌고, 값이 나중에 바뀌면 이미 열린 세션의 정체까지 같이 바뀐다.

그래서 에이전트를 **키 안에** 넣는다.

    agent:<agent_id>:<scope>[:<suffix>]

키가 에이전트를 포함하므로 요청 주변의 값으로 덮이지 않는다. 같은 scope 라도 에이전트가 다르면
키가 다르고, 두 세션의 기록이 같은 칸에 겹치지 않는다 (`session_key`·`parse_key`).

해석 사다리는 셋이고 순서가 계약이다 (`resolve_agent`):

    1. explicit   이 세션이 고른 것 — 게이트웨이의 `?agent=` 가 이 인자로 들어온다
    2. binding    프로젝트 배치 (`.asgard` 의 [agents] — swarm)
    3. sticky     끈끈한 활성 (`asgard agent use` 와 env bootstrap — profiles.active)

env 는 1번이 아니라 3번 안쪽이다. 환경변수는 아무것도 안 고른 세션의 출발값이지 정체의 근거가
아니다 — explicit 이 주어지면 `ASGARD_PROFILE` 이 무엇이든 explicit 이 우선한다.

`describe` 가 source 를 같이 돌려주는 이유는 사람이 "왜 이 에이전트인가"를 물었을 때 답할 근거가
있어야 하기 때문이다. 표시 표면(스튜디오 스냅샷·상태줄)이 그 값을 그대로 보여준다.

fail-open: 배치 해석이 실패해도 예외를 안 던지고 다음 칸으로 내려간다. 정체 해석의 결함이 세션
시동을 막으면 안 된다 (profiles·swarm 과 같은 계약).
"""

from __future__ import annotations

import re

from .profiles import DEFAULT, ID_RE, active, exists, normalize
from .swarm import binding

PREFIX = "agent"  # 키의 첫 칸 — 이 값이 아니면 세션 키가 아니다
SEP = ":"
MAIN = "main"  # scope 미지정 세션의 기본 칸

# 키 한 칸에 허용하는 문자. ID_RE(에이전트 id)와 같은 알파벳이라 scope·suffix 가 에이전트 id와
# 같은 규약을 진다.
_TOKEN_BAD = re.compile(r"[^a-z0-9_-]+")


def _token(value: object, fallback: str = "") -> str:
    """키 한 칸으로 쓸 문자열 — 허용 밖 문자는 `-` 로 바꾸고, 비면 fallback.

    구분자 `:` 가 칸 안에 남으면 `parse_key` 가 칸 경계를 잘못 잡아 왕복이 깨진다. 그래서
    치환은 선택이 아니라 왕복의 전제다."""
    text = _TOKEN_BAD.sub("-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _agent_id(name: object) -> str:
    """에이전트 이름 → 키에 쓸 id. 형식이 안 맞으면 DEFAULT.

    키는 지어낸 이름을 담으면 안 된다 — 그 순간 그 이름으로 기록이 쌓이고, 되짚을 홈이 없다."""
    canon = normalize(str(name or ""))
    return canon if canon == DEFAULT or ID_RE.match(canon) else DEFAULT


def session_key(agent: str, scope: str = MAIN, suffix: str = "") -> str:
    """세션 키 — `agent:<agent_id>:<scope>`, suffix 가 있으면 `:<suffix>` 를 덧붙인다.

    에이전트가 키의 일부라 주변 상태로 덮이지 않는다. 이 함수의 요점이 그 한 줄이다."""
    parts = [PREFIX, _agent_id(agent), _token(scope, MAIN)]
    tail = _token(suffix)
    if tail:
        parts.append(tail)
    return SEP.join(parts)


def parse_key(key: str) -> dict:
    """키 → {agent, scope, suffix}. 형식이 안 맞으면 빈 딕셔너리 — 못 읽은 것을 지어내지 않는다."""
    parts = str(key or "").split(SEP, 3)
    if len(parts) < 3 or parts[0] != PREFIX:
        return {}
    agent, scope = parts[1], parts[2]
    if not scope or not (agent == DEFAULT or ID_RE.match(agent)):
        return {}
    return {"agent": agent, "scope": scope, "suffix": parts[3] if len(parts) > 3 else ""}


def _installed(name: object) -> str:
    """이 기계에 있는 에이전트 이름으로 정규화 — 미선언·형식 불량·미설치는 빈 문자열.

    빈 입력을 `normalize` 에 그냥 넘기면 안 된다: 거기서는 빈 값이 DEFAULT 로 접혀 "안 골랐다"와
    "기본 에이전트를 골랐다"가 구분되지 않는다 (swarm._name 과 같은 판정)."""
    text = str(name or "").strip()
    if not text:
        return ""
    canon = normalize(text)
    if canon != DEFAULT and not ID_RE.match(canon):
        return ""
    try:
        return canon if exists(canon) else ""
    except Exception:
        return ""


def _placed(root: str, mode: str = "", role: str = "") -> str:
    """프로젝트 배치가 지정한 에이전트 — 좁은 선언이 넓은 선언보다 우선한다 (역할 > 모드 > 대표).

    `swarm.resolve` 를 그대로 부르지 않는 이유는 사다리의 칸을 갈라야 하기 때문이다. 그쪽은
    배치가 없으면 끈끈한 활성까지 내려가므로 반환값만으로는 배치가 정한 것인지 활성이 정한
    것인지 구분되지 않고, 그러면 `describe` 가 source 를 말할 수 없다."""
    try:
        declared = binding(root)
        # 빈 role/mode 로는 조회하지 않는다 — 빈 이름의 선언이 설정에 있으면 그것이 "안 골랐다"를
        # 가로챈다 (swarm.resolve 와 같은 판정).
        candidates = (
            declared["roles"].get(role) if role else None,
            declared["modes"].get(mode) if mode else None,
            declared["default"],
        )
    except Exception:  # 배치 해석 실패는 다음 칸으로 (fail-open — 세션 시동을 막지 않는다)
        return ""
    for name in candidates:
        picked = _installed(name)
        if picked:
            return picked
    return ""


def _sticky() -> str:
    """끈끈한 활성 — `profiles.active` 그대로. 이름 없는 홈(custom)은 DEFAULT 로 접는다.

    접는 이유는 키 때문이다: `custom` 은 이름이 아니라 "지금 이 프로세스의 홈"을 뜻하는 표지라
    (profiles.CUSTOM) 키에 적히면 다른 기계에서 되짚을 자리가 없다."""
    try:
        now = active()
    except Exception:
        return DEFAULT
    return now if now and now != "custom" else DEFAULT


def describe(root: str, explicit: str | None = None, mode: str = "", role: str = "") -> dict:
    """이 자리의 에이전트와 그 근거 — {agent, source, key}.

    source 는 "explicit" | "binding" | "sticky" 이고 사다리의 어느 칸이 정했는지를 뜻한다.
    explicit 에 이 기계에 없는 이름이 오면 그 칸은 탈락하고 아래 칸이 정한다 — 부른 쪽은
    source 가 "explicit" 이 아닌 것으로 그 사실을 판정한다 (없는 이름으로 세션을 여는 것보다
    낫다: 그 이름에는 홈도 기억도 없다).

    key 의 scope 는 좁은 선언이 우선한다 (역할 > 모드 > main) — 사다리와 같은 순서다."""
    picked, source = _installed(explicit), "explicit"
    if not picked:
        picked, source = _placed(root, mode, role), "binding"
    if not picked:
        picked, source = _sticky(), "sticky"
    return {"agent": picked, "source": source, "key": session_key(picked, scope=role or mode or MAIN)}


def resolve_agent(root: str, explicit: str | None = None, mode: str = "", role: str = "") -> str:
    """이 자리에서 일할 에이전트 id — explicit > 프로젝트 배치 > 끈끈한 활성.

    항상 이름 하나를 돌려준다 (최악이 DEFAULT). 왜 그 이름인지가 필요하면 `describe`."""
    return describe(root, explicit, mode, role)["agent"]
