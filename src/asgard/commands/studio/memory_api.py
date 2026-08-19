"""메모리 창구 — 개인 기억의 다섯 자료를 스튜디오 주소로 낸다.

메모리도 자기 서버로 뜨는 창이었다가 이 창의 화면이 됐다. 자료를 만드는 쪽
(`memory_dashboard.data`)은 그대로 두고, 여기서는 주소와 매개변수만 스튜디오 계약에 맞춘다 —
옛 주소 `/api/snapshot` 이 여기서는 `/api/memory/snapshot` 이고 그 아래는 같은 함수다.

**보는 자리가 프로젝트 뿌리가 아니다.** 다른 창구는 `root` 가 자료를 고르지만 1차 기억은
에이전트의 것이라 서고를 `memory.memory_dir()` 이 정한다(ASGARD_MEMORY_DIR · 설정 · 프로파일 홈
순). 그래서 창이 어느 프로젝트를 보고 있든 같은 서고가 나오고, `root` 는 500 을 기록할 자리를
가리키는 데만 쓴다.

수치 매개변수의 범위는 자료 쪽이 이미 건다 — `search_data` 가 k 를 1..25 로, `log_query` 가
limit 을 1..500 으로, offset 을 0 이상으로 자른다. 여기서 다시 자르면 상한이 두 곳에 살게 되고
언젠가 갈라지므로, 이 문은 형식만 본다(숫자가 아니면 기본값).

`memory_dashboard` 를 부르는 임포트가 전부 함수 안에 있는 이유는 등급표다 — `studio` 와
`memory_dashboard` 는 `commands` 안에서 같은 등급("명령 소비")이라 모듈 레벨로 부르면
`tests/architecture/test_package_internals.py` 가 같은 등급 결합으로 잡는다. 형제 명령 패키지를
쓰는 다른 자리도 같은 모양이다 (`routes.py` 의 `plan_api`·`ticket_api`·`studio_store`).
"""

from __future__ import annotations

import re

from ... import memory
from .. import loopback

# 연대기 날짜 필터 — 연·월·일 접두. 형식 밖은 무시한다(fail-open), 옛 서버와 같은 규율.
_DAY = re.compile(r"\d{4}(-\d{2}){0,2}")


def _one(params: dict[str, list[str]], name: str, default: str = "") -> str:
    return (params.get(name) or [default])[0]


def _int(params: dict[str, list[str]], name: str, default: int) -> int:
    """숫자로 못 읽는 값은 기본값. 자릿수가 파이썬 변환 상한을 넘는 문자열도 여기서 걸린다."""
    try:
        return int(_one(params, name, str(default)))
    except ValueError:
        return default


def _page(params: dict[str, list[str]]) -> tuple[int, str, bytes]:
    """페이지 상세 — 경로 안전은 `memory.valid_slug` 와 `memory._page_path` 가 이미 든다
    (슬러그 문자셋에 `/` 도 `.` 도 없고, 읽기 직전에 realpath 가 pages/ 안인지 본다).
    그래서 여기서는 막지 않고, 자료가 낸 거절 사유를 코드가 붙은 오류로 옮기기만 한다."""
    from ..memory_dashboard.data import page_data

    slug = _one(params, "slug").strip()
    data = page_data(slug)
    reason = data.get("error")
    if not reason:
        return loopback.json_body(200, data)
    if reason == "invalid slug":
        return loopback.api_error(
            400,
            "memory_slug_invalid",
            "슬러그 형식이 아니에요",
            remedy="목록이나 그래프에서 페이지를 골라 주세요 — 경로가 아니라 슬러그예요",
            detail={"slug": slug[:80]},
        )
    return loopback.api_error(
        404,
        "memory_page_not_found",
        "그 슬러그의 페이지가 없어요",
        remedy="서고를 옮겼거나 지웠는지 `asgard memory list` 로 확인해 보세요",
        detail={"slug": slug[:80]},
    )


def _log(params: dict[str, list[str]]) -> tuple[int, str, bytes]:
    from ..memory_dashboard.data import log_query

    day = _one(params, "day").strip() or None
    if day and not _DAY.fullmatch(day):
        day = None
    return loopback.json_body(
        200,
        log_query(
            memory.memory_dir(),
            _int(params, "offset", 0),
            _int(params, "limit", 60),
            _one(params, "op").strip() or None,
            day,
        ),
    )


def dispatch(
    method: str, path: str, params: dict[str, list[str]] | None = None, root: str | None = None
) -> tuple[int, str, bytes]:
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    params = params or {}
    try:
        if path == "/api/memory/snapshot":
            from ..memory_dashboard.data import snapshot_data

            return loopback.json_body(200, snapshot_data())
        if path == "/api/memory/injection":
            # 주입면은 스냅샷 블록 원문을 통째로 넣는다 — 탭이 열릴 때만 부르는 무거운 자리다.
            from ..memory_dashboard.data import injection_data

            return loopback.json_body(200, injection_data())
        if path == "/api/memory/search":
            from ..memory_dashboard.data import search_data

            return loopback.json_body(200, search_data(_one(params, "q"), _int(params, "k", 5)))
        if path == "/api/memory/page":
            return _page(params)
        if path == "/api/memory/log":
            return _log(params)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        # 서고가 없거나 깨져도 창이 통째로 죽지는 않는다. 표면 이름을 여기서 붙이는 이유는
        # 서버의 포괄 처리로 흘러가면 기록이 "studio" 로만 남아 어느 화면이었는지 사라지기 때문이다.
        return loopback.error_result(exc, surface="memory", root=root or "", where=path)
    return 404, "text/plain; charset=utf-8", b"not found"
