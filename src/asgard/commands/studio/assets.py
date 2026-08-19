"""`/asset/...` — 패키지 안 자산을 창에 내주는 한 곳.

여태 창은 자립형 단일 파일이었다. 토큰도 컴포넌트도 페이지 안에 인라인으로 들어 있었고,
그래서 세 화면이 같은 색을 세 번 적었다. 한 곳으로 모으려면 그것이 파일이어야 하고, 파일이면
누군가 내줘야 한다. 여기가 그 자리다.

**경로 검사가 이 모듈의 본체다.** `src/asgard/assets/` 는 패키지 **안에** 있다. 그래서 요청받은
이름을 그대로 이어 붙이면 `../commands/loopback.py` 가 그대로 나간다. 루프백 전용 표면이라도
브라우저에서 열리는 주소이므로, 어떤 페이지가 무엇을 요청하든 자산 밖으로는 나가지 않아야 한다.

검사는 둘을 다 건다. 글자 검사(`_safe_name`)는 뜻이 분명한 것을 먼저 끊고, 실경로 검사
(`realpath` 봉쇄)는 심볼릭 링크처럼 글자만 봐서는 알 수 없는 것을 끊는다. 하나로는 모자란다 —
글자 검사만 두면 링크가 뚫고, 실경로 검사만 두면 `..` 이 자산 안을 훑는 것을 허용하게 된다.
"""

from __future__ import annotations

import os
from importlib.resources import files

# 창이 실제로 읽는 갈래만 연다. 새 갈래가 필요하면 여기 한 줄을 더하는 것이 유일한 문이다.
_PREFIXES = ("ui/", "js/", "vendor/")

# 확장자 허용 목록 — 내용 종류를 우리가 정한다. `.py`·`.json`·`.md` 가 없는 것이 요점이다.
_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
}


def _root() -> str:
    return os.path.realpath(str(files("asgard") / "assets"))


def _safe_name(rel: str) -> bool:
    """글자만 보고 끊는 것들 — 절대경로·상위 참조·역슬래시·빈 마디·숨김 파일."""
    if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return False
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return False
    return rel.startswith(_PREFIXES) and os.path.splitext(rel)[1] in _TYPES


def serve(rel: str) -> tuple[int, str, bytes]:
    """`(status, content-type, bytes)`. 없거나 규칙 밖이면 404 — 이유는 나누지 않는다.

    "규칙 위반"과 "없는 파일"을 다른 응답으로 내면 그 차이가 곧 자산 밖 파일의 존재를 알려 주는
    신호가 된다. 밖에서 보면 둘 다 똑같이 없는 것이어야 한다."""
    if not _safe_name(rel):
        return 404, "text/plain; charset=utf-8", b"not found"
    base = _root()
    path = os.path.realpath(os.path.join(base, rel))
    # 봉쇄 — 실경로가 자산 뿌리 **아래**여야 한다. `startswith(base)` 만으로는
    # `/…/assets-evil/` 이 통과하므로 구분자까지 붙여 비교한다.
    if path != base and not path.startswith(base + os.sep):
        return 404, "text/plain; charset=utf-8", b"not found"
    try:
        with open(path, "rb") as handle:
            body = handle.read()
    except OSError, ValueError:
        return 404, "text/plain; charset=utf-8", b"not found"
    return 200, _TYPES[os.path.splitext(rel)[1]], body
