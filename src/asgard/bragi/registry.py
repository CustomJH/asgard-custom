"""언어 등록부 — 코어를 안 고치고 언어를 늘리는 접점.

`register(latin=True)` 는 `LATIN_LANGS` 를 다시 묶는다. 그래서 판정기(`judge`)는 이 이름을
자기 모듈로 가져가지 않고 `registry.LATIN_LANGS` 로 매번 읽는다 — 가져가면 등록 뒤에 옛 값이
남는다.
"""

from __future__ import annotations

from .corpora import _ES, _FR, _JA, _RU, _VI, _ZH
from .english import _EN
from .korean import _KO
from .tell import Tell

# ── 지원 언어. "generic"은 미등록 언어의 폴백 신원 — 언어 무관 패턴만 돈다.
LANGS = ("en", "ko", "ja", "zh", "vi", "es", "fr", "ru", "generic")
# 라틴 문자권 — 엠대시·타이틀 케이스처럼 라틴 조판에서만 성립하는 규칙의 적용 대상.
# 한국어·일본어·중국어 조판에서 줄표는 AI 신호가 아니다 (KatFishNet의 한국어 신호는 쉼표다).
LATIN_LANGS = frozenset({"en", "es", "fr", "vi"})

_REGISTRY: dict[str, list[Tell]] = {
    "en": _EN,
    "ko": _KO,
    "ja": _JA,
    "zh": _ZH,
    "vi": _VI,
    "es": _ES,
    "fr": _FR,
    "ru": _RU,
    "generic": [],
}


def register(lang: str, tells_: list[Tell], *, latin: bool = False) -> None:
    """새 언어 코퍼스 등록 — 코어 수정 없이 언어를 늘리는 유일한 접점.

    같은 언어를 두 번 등록하면 뒤가 앞을 덮는다 (프로젝트 커스텀이 기본값을 우선한다)."""
    global LATIN_LANGS
    _REGISTRY[lang] = list(tells_)
    if latin:
        LATIN_LANGS = LATIN_LANGS | {lang}


def registered_langs() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))
