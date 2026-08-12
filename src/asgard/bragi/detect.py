"""언어 판정 — 문자 체계 우선, 라틴권은 진단 글자·기능어로 가른다."""

from __future__ import annotations

import re

# ── 언어 판정 — 문자 체계 우선, 라틴권은 진단 글자·기능어로 가른다.
_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN_CH = re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]")
# 베트남어 진단 글자 — 다른 라틴 표기 언어에 거의 나오지 않는 조합.
_VI_CH = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯ]|[ạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")
_ES_CH = re.compile(r"[ñ¿¡]|\b(?:que|para|con|los|las|del|una|este|más)\b", re.I)
_FR_CH = re.compile(r"[œçÇ]|\b(?:les|des|une|dans|pour|est|avec|cette|plus)\b", re.I)


def detect_lang(text: str) -> str:
    """지배 문자 체계로 언어를 고른다. 미상은 "generic" — 침묵하지 않고 무관 패턴만 돈다.

    코드·URL이 섞인 한국어 보고문처럼 라틴 문자가 함께 나오는 경우가 정상이므로,
    표의·음절 문자가 하나라도 우세하면 그쪽을 택한다 (라틴 다수결이 아니다)."""
    if not text or not text.strip():
        return "generic"
    hangul, kana, han = len(_HANGUL.findall(text)), len(_KANA.findall(text)), len(_HAN.findall(text))
    cyr, latin = len(_CYRILLIC.findall(text)), len(_LATIN_CH.findall(text))
    cjk = hangul + kana + han
    if cjk and cjk * 4 >= latin:  # 라틴이 4배를 넘게 압도할 때만 라틴으로 본다
        if hangul >= max(kana, han):
            return "ko"
        if kana:  # 가나가 하나라도 있으면 일본어 — 한자 단독이 중국어
            return "ja"
        return "zh"
    if cyr and cyr * 2 >= latin:
        return "ru"
    if not latin:
        return "generic"
    if len(_VI_CH.findall(text)) >= 2:
        return "vi"
    es, fr = len(_ES_CH.findall(text)), len(_FR_CH.findall(text))
    if max(es, fr) >= 3 and max(es, fr) > 2 * min(es, fr):
        return "es" if es > fr else "fr"
    return "en"
