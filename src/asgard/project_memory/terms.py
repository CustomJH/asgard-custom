"""2차 레인의 한국어 질의 토큰화 — 기준은 여기 하나이고, 그 기준은 1차에서 가져온다.

왜 이 모듈이 생겼는가 (26-08-01, `benchmarks/project-memory/REPORT.md`).

문서 레인의 hit@1 이 한국어 0.444 대 영어 0.875 였다. 원인은 랭킹이 아니라 토큰화였다:
`documents.search` 가 질의를 공백으로만 쪼개서 `금요일에`·`배포해도` 같은 형태가 정본의
`금요일`·`배포를` 과 맞지 않았다 ("금요일에 배포해도 되나" 가 빈손 0건). 같은 저장소의
1차 회수(`memory/recall.py:query`)와 주입면(`memory_context._query_terms`)은 그때 이미
조사 목록을 갖고 있었다 — 없는 기준을 만들 일이 아니라 있는 기준을 안 쓰고 있던 것이다.

그래서 여기에는 조사 목록을 **적지 않는다**. 적는 순간 한국어를 재는 기준이 하나 더 늘고,
조사 하나를 더 알아야 할 날에 어느 쪽을 고쳐야 하는지 아무도 못 말하게 된다.

**어미까지 쓰지 않는 이유** (26-08-01 갱신). 이 모듈이 생길 때는 1차에서 가장 넓은 처리가
`memory/recall.py:query` 안에 인라인이라 import 가 안 됐고, 그래서 그다음으로 넓은
`memory_context._query_terms`(조사 18개, 어미 없음)를 불렀다. 그 제약은 같은 날 사라졌다 —
근거 대조를 길이에서 형태로 바꾸면서 `_KO_PARTICLES`·`_KO_ENDINGS`·`_KO_STEM_SUFFIXES` 가
모듈 수준으로 나왔다. 그런데 **옮길 근거가 없다.** 이 레인에 남은 한국어 오답 2건은
토큰화가 아니라 0-LLM 레인의 어휘 겹침 상한이고(`benchmarks/project-memory/REPORT.md`),
어미를 더 떼면 후보만 넓어져 정밀도가 떨어진다.

그러니 이것은 "못 해서 안 한 것"이 아니라 **재 보고 안 하기로 한 것**이다. 옮기려는 사람은
먼저 그 벤치를 돌려 ko 가 오르고 en 이 안 내려가는 것을 보여야 한다 (지금 ko 0.778 · en 1.000).
"""

from __future__ import annotations


def query_terms(text: str) -> list[str]:
    """1차와 같은 기준으로 자른 질의어 — 원형과 조사를 뗀 어간 후보가 함께 온다.

    호출측은 이것을 **기존 토큰에 더해 쓴다, 갈아 끼우지 않는다**. 이 처리는 도메인을 안
    가르는 낱말을 버리는데(`what`·`the`·`관련`), 조사가 안 붙는 영어 질의에서는 그 낱말들이
    지금 실제로 후보를 만들고 있다 — 갈아 끼우면 한국어를 살리면서 영어를 깎는다.

    불러오지 못하면 빈 목록이다. 2차 레인은 서버도 모델도 없이 도는 자리이고, 형태 처리가
    빠지는 것은 고치기 전 상태로 돌아간다는 뜻이지 회수가 멈출 이유는 아니다."""
    try:
        from ..memory_context import _query_terms

        return [term for term in _query_terms(text) if len(term) >= 2]
    except Exception:
        return []


def expand(base: list[str], text: str) -> list[str]:
    """`base` 뒤에 어간 후보를 덧대고 중복만 지운다 — 순서는 `base` 가 정한다.

    순서를 지키는 이유: 발췌 자리 잡기(`documents._excerpt`)가 앞에서부터 처음 걸리는 낱말을
    바늘로 쓴다. 어간을 앞에 두면 사람이 적은 말 대신 깎인 말 자리에서 발췌가 시작된다."""
    return list(dict.fromkeys(base + query_terms(text)))


__all__ = ["expand", "query_terms"]
