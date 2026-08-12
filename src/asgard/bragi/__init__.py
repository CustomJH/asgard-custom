"""Bragi — 다국어 휴먼체 엔진. 보고문이 사람이 쓴 글로 읽히는지 결정론으로 판정한다.

브라기는 시가(詩歌)와 언변의 신 — 아스가르드가 결과를 보고할 때 쓰는 문장을 맡는다.
Lagom이 "얼마나 적게 쓰는가"(압축·근거)를 보는 축이라면, 브라기는 "사람처럼 읽히는가"를 본다.
두 축은 겹치지 않는다: Lagom은 근거 없는 효용 주장을 잡고, 브라기는 LLM 특유의 문장 습관을 잡는다.

계층: domain (settings만 lazy 임포트). 프롬프트 계약은 templates/bragi.py.

판정 구조
  탐지기(tells)   언어별 패턴 + 언어 무관 패턴을 원문의 검사 사본에 적용
  심각도          S1 = 1회로 결정적 · S2 = 3회 이상이거나 다른 흔적과 동반될 때 · S3 = 군집일 때만
  등급(grade)     A/B/C/D — 상류 korean-skills의 자연도 등급 경계를 그대로 계승

임계는 취향이 아니라 실측으로 정했다. benchmarks/bragi-humanvoice/ 가 상류 라벨 코퍼스(Part A),
이 저장소가 쌓아 온 사람 글 677건(Part B), 로컬 모델 A/B(Part C)로 채점한다. 쉼표 밀도 0.70,
굵은 머리말 S3 강등, 어미 단조 한·일 한정은 전부 Part B 오탐을 보고 되돌린 결정이다.

근거 (패턴마다 verified 필드로 표기)
  ✅ KatFishNet (ACL 2025, arXiv 2503.00032) — 한국어 쉼표 94.88 · 품사 82.99 · 띄어쓰기 79.51 AUC
  ✅ Kobak et al., Science Advances 2025 (arXiv 2406.07016) — 영어 초과 어휘 (2024 초록 13.5% LLM 처리)
  ✅ Juzek & Ward, COLING 2025 — ChatGPT 초점어 21종 (delve/intricate/pivotal …)
  ✅ Wikipedia:Signs of AI writing (WikiProject AI Cleanup) — blader/humanizer 31k★ 의 근거 문서
  📊 언어별 커뮤니티 코퍼스 — vi(longhang2004) · ja(gonta223) · zh(op7418) · ko(DaleSeo)

언어 확장은 register() 한 줄이면 된다 — 코어를 건드리지 않는다. 등록되지 않은 언어도
언어 무관 패턴만으로 동작한다 (탐지력은 낮지만 침묵하지 않는다).

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.bragi` 하나만 보면
되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).

**이름을 갈아 끼우려면 정의한 모듈에 꽂아라.** 파사드의 이름을 바꿔도 정의한 모듈 안의
호출자는 자기 모듈에서 찾으므로 바뀐 것을 못 본다 (`mock.patch.object(bragi.judge, …)`).
`register(latin=True)` 가 다시 묶는 `LATIN_LANGS` 도 같은 이유로 `registry` 쪽이 정본이고,
여기 재수출된 값은 등록 시점의 사본이다 — 판정기는 `registry.LATIN_LANGS` 를 매번 읽는다.
"""

from __future__ import annotations

# 분해 전 `bragi` 가 들고 있던 이름 — 이 파사드 안에서는 안 쓰지만 부르는 쪽이 이 이름으로
# 닿을 수 있어 그대로 남긴다 (표준 라이브러리 모듈까지).
import os  # noqa: F401
import re  # noqa: F401
from typing import NamedTuple  # noqa: F401

from .clean import _DATA_LINE, _PATH, _SPAN_SENSITIVE, lintable, lintable_spans  # noqa: F401
from .corpora import _ES, _FR, _JA, _RU, _VI, _ZH  # noqa: F401
from .detect import (  # noqa: F401
    _CYRILLIC,
    _ES_CH,
    _FR_CH,
    _HAN,
    _HANGUL,
    _KANA,
    _LATIN_CH,
    _VI_CH,
    detect_lang,
)
from .english import _EN  # noqa: F401
from .judge import grade, tells, violations  # noqa: F401
from .korean import _KO, KO_METAPHOR  # noqa: F401
from .mode import DEFAULT_MODE, MODES, current_mode, enabled, normalize, note  # noqa: F401
from .registry import _REGISTRY, LANGS, LATIN_LANGS, register, registered_langs  # noqa: F401
from .stats import (  # noqa: F401
    _SENT_SPLIT,
    _comma_density,
    _ending_monotony,
    _length_uniformity,
    _sentences,
    _statistical,
)
from .tell import _GRADES, _S2_MIN_HITS, SEVERITIES, Finding, Tell, _t  # noqa: F401
from .universal import _UNIVERSAL  # noqa: F401
