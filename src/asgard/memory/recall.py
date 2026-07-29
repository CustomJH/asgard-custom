"""검색·주입면 — RRF 3-스트림 query, usage 추적, 동결 스냅샷·회수 블록·증류 넛지."""

from __future__ import annotations

import datetime as _dt
import math
import os
import re

from .index import _db
from .policy import (
    _INVISIBLE,
    _memory_settings,
    index_budget,
    inject_enabled,
    kind_budgets,
    memory_dir,
    scan_threats,
)
from .store import (
    PAGES,
    _desc,
    _kind,
    _pages,
    _read,
    _today,
    poisoned,
    slot_query_aliases,
    slugify,
)
from .temporal import event_date

_SNAPSHOT_WARN = "- … (index over budget — asgard memory lint)"

# 칸 이름 — 사람이 읽는 표면이라 세계관 어휘를 쓴다. 순서가 곧 주입 순서다:
# 값비싼 칸을 앞에 둬서 총량 상한이 걸릴 때 뒤(싼 칸)부터 잘리게 한다.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("user", "오딘은 누구인가"),
    ("feedback", "일하는 방식"),
    ("decision", "확정된 판정"),
    ("insight", "벼려낸 통찰"),
    ("reference", "참조 사실"),
    ("note", "메모"),
)

# ── 검색 (query) — LLM 0. trigram FTS, 실패 시 파일 스캔 fail-open ─────────────────


def _grams(text: str, n: int = 3) -> set[str]:
    t = re.sub(r"\s+", " ", text.lower())
    return {t[i : i + n] for i in range(max(len(t) - n + 1, 1))}


def _jaccard(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / (len(ga | gb) or 1)


def _containment(a: str, b: str) -> float:
    """포함 계수 |A∩B|/min(|A|,|B|) — 한쪽이 다른 쪽을 품는 패러프레이즈에 강건."""
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / (min(len(ga), len(gb)) or 1)


# ── 근거 접지 원시함수 — 패턴(관측)과 노른(통찰)이 같은 자를 쓴다 ─────────────────


def _content_words(text: str) -> set[str]:
    """접지 비교용 내용어 — 2자 이상 토큰. 조사·기호는 분리자로 흘려보낸다."""
    return {word.lower() for word in re.split(r"[^\w가-힣]+", text) if len(word) >= 2}


def _stem_hit(word: str, haystack: str) -> bool:
    """낱말이 건초더미에 어간으로 남아 있는가.

    집합 교집합으로는 한국어 접지를 못 잰다 — 조사·어미가 낱말 **뒤**에 붙어서 "금요일"과
    "금요일에는"이 서로 남남이 된다. 그래서 앞에서부터 잘라 보며 어간을 찾는다 (영어의
    굴절 deploy/deploying 도 같은 자로 걸린다). 절반 미만으로는 안 자른다: 두 글자만
    남기고 맞히기 시작하면 우연 일치가 접지로 둔갑한다."""
    floor = max(2, (len(word) + 1) // 2)
    return any(word[:cut] in haystack for cut in range(len(word), floor - 1, -1))


# 접지 판정에서 빼는 주어·기능어 — 누구에 대한 기록인지는 접지의 증거가 아니다.
_GROUNDING_STOP = frozenset("오딘 사용자 유저 user odin the is are was were and or for with that this it its".split())


def _stopword(word: str) -> bool:
    """주어·기능어인가 — 조사·어미가 붙어도 같은 낱말이다 ("오딘은" = 오딘).

    꼬리 길이를 제한하는 이유: 앞을 우연히 공유하는 남의 낱말까지 삼키면 안 된다
    ("withdraw" 는 "with" 가 아니다)."""
    return any(word.startswith(stop) and len(word) - len(stop) <= 3 for stop in _GROUNDING_STOP)


RRF_K = 60  # rank-fusion 표준 상수 — 상위 랭크 간 격차를 완만히 눌러 단일 경로 독주를 막는다
SEM_FLOOR = 0.20  # 시맨틱 후보 진입 문턱 — 이 미만 코사인은 후보로도 안 넣는다(약연관 잡음 차단).
TEMPORAL_KINDS = frozenset({"reference"})
TEMPORAL_DAYS = 365
TEMPORAL_ALPHA = 0.20  # 최신성은 관련도를 대체하지 않고 최대 약 ±10%만 보정한다.
PPR_DAMPING = 0.85
PPR_STEPS = 20
# 0.20 은 경량 정적 임베더(model2vec) 기준 실측 튜닝(26-07-18): 교차언어 정답이 랭크1이어도
# 절대 코사인이 0.18–0.29 로 낮아 0.30 은 이득을 죽였다. 강한 torch 모델(all-MiniLM 등)은
# 0.5–0.7 로 분리가 뚜렷해 이 문턱이 넉넉하다. config [memory].semantic_floor 로 조정 가능.


def _sem_floor() -> float:
    """시맨틱 후보 진입 문턱 — 설정 오버라이드 > SEM_FLOOR 기본. 모델 tier 에 맞춰 조정."""
    try:
        v = _memory_settings().get("semantic_floor")
        return float(v) if v is not None else SEM_FLOOR
    except Exception:
        return SEM_FLOOR


def _temporal_multiplier(meta: dict, today: _dt.date | None = None) -> float:
    """빠르게 낡는 reference만 보수적으로 보정한다. 날짜 불명·다른 kind는 중립."""
    if _kind(meta) not in TEMPORAL_KINDS:
        return 1.0
    try:
        # 사건 시각 우선 — "작년에 정한 규칙"을 오늘 적었다고 최신 사실이 되진 않는다
        updated = _dt.date.fromisoformat(event_date(meta))
    except ValueError:
        return 1.0
    days = max(0, ((today or _dt.date.today()) - updated).days)
    recency = max(0.1, min(1.0, 1.0 - days / TEMPORAL_DAYS))
    return 1.0 + TEMPORAL_ALPHA * (recency - 0.5)


RERANK_CANDIDATES = 20  # 리랭크 대상 — RRF 상위 이만큼만 다시 본다 (전량 재계산은 비싸다)
RERANK_PASSAGE_CHARS = 600
RERANK_MAX_PASSAGES = 40  # 페이지 하나에서 볼 구절 상한 (~24,000자까지 덮는다)
# 이만큼 구절이 안 나오는 페이지는 리랭크 대상이 아니다 — 희석이 없으면 되돌릴 것도 없다.
RERANK_MIN_PASSAGES = 3
RERANK_TOP_PASSAGES = 3  # 평균에 쓸 상위 구절 수
RERANK_MAX_WEIGHT = 0.5  # max 와 상위평균의 배합 — 1.0 이면 순수 max (선호 유형에서 −13pp)
# 융합에서 기존 4스트림 순위에 주는 가중 (리랭크는 항상 1.0). 1.0 = 대등.
# 리랭크가 이기는 자리와 지는 자리가 갈리기 때문에 둔 손잡이다: 사실 질문은 리랭크가 맞고,
# 간접 질문("내가 좋아할 만한 걸 추천해줘")은 어휘가 맞다. 어느 쪽도 항상 옳지 않다.
RERANK_BASE_WEIGHT = 1.0
# 2단계를 끄는 세션 오버라이드 — 시맨틱 스트림의 ASGARD_MEMORY_SEMANTIC 과 같은 모양이다.
# 어블레이션(리랭크 ON/OFF A/B)을 몽키패치 없이 재현할 수 있어야 남이 그 수치를 검증한다.
# held-out 실측(26-07-28)에서 이 단계가 대화형 코퍼스 밖에서는 이득을 못 낸다는 반례가
# 나왔으므로, 끄는 길은 벤치 전용 장치가 아니라 정식 스위치여야 한다.
_RERANK_ENV = "ASGARD_MEMORY_RERANK"

# ── 리랭크 적용 게이트 — 길이가 아니라 **점수 분산**으로 (26-07-29) ────────────────────
#
# 왜 바꾸는가. held-out 실측(V2, 웹/기업 에이전트 궤적)에서 구절 리랭크는 −5.0pp 였고
# 피해가 `static-environment` 유형에 몰렸다(0:5). 보고서의 가설은 "같은 환경의 궤적은 UI
# 어휘를 공유해서, 구절로 쪼개 보면 질의 낱말을 되울리는 구절이 어디에나 있다" 였다. 즉
# **구별이 안 되는 코퍼스**에서 리랭크가 잡음을 신호로 착각한다.
#
# 그런데 기존 게이트(`RERANK_MIN_PASSAGES`)는 **길이만** 본다. 길이는 그 실패를 예측하지
# 못한다 — V2 궤적은 충분히 길다. 필요한 것은 "이 질의에 대해 후보들이 갈리는가"를 재는 자다.
#
# 그 자는 정보검색에 이미 있다: **Query Performance Prediction (QPP)**. 그중 NQC
# (Normalized Query Commitment, Shtok et al.)는 상위 문서 점수의 **표준편차**를 쓰고,
# 낮은 분산을 query drift — 질의와 무관한 문서가 상위를 점령한 상태 — 의 증거로 읽는다.
# 여기 옮기면 정확히 V2 의 실패 모양이다: 모든 구절이 비슷해 보이면 순위를 바꿀 근거가 없다.
#
# NQC 는 코퍼스 점수로 정규화하지만 우리에겐 그 상수가 없다. 코사인은 척도가 고정
# ([-1,1]) 이고 후보 집합이 작으므로 **변동계수**(σ/μ)를 쓴다 — 척도 무관이고 stdlib 로 끝난다.
RERANK_DISPERSION_ENV = "ASGARD_MEMORY_RERANK_DISPERSION"
# 게이트의 **모양** — 기권(hard)인가 감쇠(soft)인가.
#
# 처음 낸 것은 hard 였다: 분산이 문턱 미만이면 리랭크 표를 아예 안 던진다. held-out 계측이
# 그 대가를 정확히 보여 줬다 (26-07-29):
#   V2(새 도메인) 퇴행 9건 → 2건  ← 얻은 것
#   M(건초더미 9배) R@5 동일하나 NDCG −0.9pp · MRR −1.4pp  ← 치른 것
# M 에서 리랭크는 순증(27:14)이었으므로, 낮은 분산 질의에서도 **순위를 다듬는 몫**이 있었는데
# 기권이 그걸 통째로 버린 것이다. 신호가 약하다는 것과 신호가 없다는 것은 다른 말이다.
#
# soft 는 그 사이를 열어 본 시도다: 분산을 **확신도**로 읽어 융합 가중을 낮춘다.
#   w(σ/μ) = min(1, 분산 / 문턱)
# 문턱 이상이면 1.0 이라 S 의 이득은 정의상 보존되고, 문턱 미만에서만 비례해 줄어든다.
#
# **재 봤고, 안 됐다 (26-07-29 3벌 실측).** 감쇠가 너무 완만하다 — V2 에서 해를 끼치던 질의의
# 분산이 문턱 **바로 아래**(0.82~0.95 × 문턱)에 몰려 있어서 가중이 0.8 이상으로 거의 안 깎인다.
#
#   V2 R@5:  OFF 0.800 · 게이트없음 0.750(4:9) · **hard 0.780(0:2)** · soft 0.760(4:8)
#   S  R@5:  게이트없음 0.956 · **hard 0.960** · soft 0.956 (게이트없음과 동률)
#
# 즉 soft 는 게이트 없음과 거의 같다 — 지키려던 것을 못 지킨다. 그래서 기본은 **hard** 다.
# soft 를 남겨 두는 이유는 이 판정이 취향이 아니라 계측이었음을 남이 재현할 수 있어야 하기
# 때문이다 (`--gate soft`). hard 가 M 에서 치르는 MRR −1.4pp 는 여전히 열린 값이고, 그걸
# 되찾으려면 지금 신호가 못 주는 구분이 필요하다 — 다음 라운드의 held-out 몫이다.
RERANK_GATE_ENV = "ASGARD_MEMORY_RERANK_GATE"
RERANK_GATE_MODE = "hard"
# 문턱은 **개발 집합(S)에서만** 뽑았다. held-out(M·V2)을 보고 고르면 그 절의 증거값이
# 그 자리에서 사라진다 — 보고서가 스스로 경계한 그 행동이다.
#
# 보정 규칙(`benchmarks/longmemeval/calibrate_dispersion.py`, 산출물 calibration-dispersion.json):
#   floor = 0.99 × min{ 분산(q) : q ∈ S, 리랭크가 그 질의를 0→1 로 이긴 경우 }
# 즉 "리랭크가 실제로 값을 한 질의는 하나도 안 막는다"를 **구성으로** 보장하는 가장 큰 문턱이다.
# S 점수를 최대화하는 값을 찾지 않는다 — 그건 30문항 위 2문항을 좇는 과적합이다.
#
# S 500문항 실측 (26-07-29): 리랭크 발동 500 · 이김 13 · 짐 4 · 무변화 483.
#   이긴 질의의 분산 [0.1518 … 0.3548]  ·  진 질의의 분산 [0.1237, 0.1275, 0.1548, 0.3643]
#   → floor 0.1503 에서 **이긴 13건 전부 통과, 진 4건 중 2건 차단**, 전체 기권률 6.2%.
# 진 사례가 분포 하단에 몰린 것이 NQC 의 주장(낮은 분산 = query drift)과 방향이 같다.
RERANK_DISPERSION_FLOOR = 0.1503


def rerank_enabled() -> bool:
    """구절 리랭크를 이번 세션에서 쓰는가 — env 우선, 설정 폴백, 기본 ON."""
    env = (os.environ.get(_RERANK_ENV) or "").strip().lower()
    if env:
        return env not in ("off", "0", "false", "no")
    try:
        return str(_memory_settings().get("rerank", "on")).strip().lower() not in ("off", "0", "false", "no")
    except Exception:
        return True


def _dispersion_floor() -> float:
    """리랭크 표를 던지기 위해 필요한 최소 변동계수 — env > 설정 > 기본.

    0 이면 게이트 없음(도입 전 거동과 바이트 동일). 어블레이션이 몽키패치 없이 되어야
    남이 그 수치를 검증한다 — `ASGARD_MEMORY_RERANK` 와 같은 모양의 손잡이다."""
    env = (os.environ.get(RERANK_DISPERSION_ENV) or "").strip()
    if env:
        try:
            return max(0.0, float(env))
        except ValueError:
            return RERANK_DISPERSION_FLOOR
    try:
        value = _memory_settings().get("rerank_dispersion")
        return max(0.0, float(value)) if value is not None else RERANK_DISPERSION_FLOOR
    except Exception:
        return RERANK_DISPERSION_FLOOR


def _gate_mode() -> str:
    """게이트 모양 — env > 설정 > 기본 soft. `hard` 는 기권(도입 당시 거동, 보고서 재현용)."""
    env = (os.environ.get(RERANK_GATE_ENV) or "").strip().lower()
    if env in ("hard", "soft"):
        return env
    try:
        mode = str(_memory_settings().get("rerank_gate", RERANK_GATE_MODE)).strip().lower()
        return mode if mode in ("hard", "soft") else RERANK_GATE_MODE
    except Exception:
        return RERANK_GATE_MODE


def _gate_weight(dispersion: float, floor: float) -> float:
    """리랭크 스트림에 줄 융합 가중 — 1.0 이면 기존과 동일, 0.0 이면 표를 안 던진다.

    문턱이 0(게이트 없음)이면 항상 1.0 이라 도입 전과 바이트 동일하게 돈다."""
    if floor <= 0.0:
        return 1.0
    if dispersion >= floor:
        return 1.0
    if _gate_mode() == "hard":
        return 0.0
    return max(0.0, dispersion / floor)


def _dispersion(scores: list[float]) -> float:
    """후보 점수의 변동계수 σ/μ — 후보들이 갈리는 정도. 못 재면 0.0.

    평균이 0 이하면 정의되지 않는다(코사인이 전부 0 근처인 경우) — 그때는 갈리지 않는다고
    본다. 두 개 미만도 마찬가지다: 순위라 부를 것이 없으면 분산도 없다."""
    if len(scores) < 2:
        return 0.0
    mean = sum(scores) / len(scores)
    if mean <= 0.0:
        return 0.0
    variance = sum((score - mean) ** 2 for score in scores) / len(scores)
    return math.sqrt(variance) / mean


def _passages(body: str) -> list[str]:
    """구절 분할 — 줄(=대화 턴·문단) 경계로 쪼개고, 긴 줄은 다시 자른다.

    한 구절이 길면 희석 문제가 그대로 되돌아오므로 상한을 건다."""
    out: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if len(line) < 12:
            continue
        for start in range(0, len(line), RERANK_PASSAGE_CHARS):
            out.append(line[start : start + RERANK_PASSAGE_CHARS])
            if len(out) >= RERANK_MAX_PASSAGES:
                return out
    return out


def _rerank_order(text: str, cand: dict, ranked: list[str]) -> tuple[list[tuple[str, float]], float]:
    """구절 최대 유사도 순위 — 페이지가 길수록 통짜 임베딩이 못 보는 것을 되찾는다.

    페이지 벡터 하나는 문서 전체의 평균이라, 긴 페이지에서는 정작 답이 든 한 문장이 나머지
    수천 자에 희석된다 (LongMemEval-S 실측: 세션 중앙값 1만 자). 구절로 쪼개 최댓값을 쓰면
    같은 임베더로도 순위가 날카로워진다 — 새 모델도, torch 도 필요 없다.

    **다섯 번째 스트림일 뿐 대체가 아니다.** 실측(500문항)에서 이 점수로 순위를 통째로
    갈아치우면 어휘·그래프 신호를 버려 이득이 반으로 줄었다. RRF 에 한 표로 넣는 게 낫다.

    **비용은 이득이 있는 곳에서만 낸다.** 짧은 페이지는 아래 길이 게이트에서 통째로 빠지므로
    정상적인 개인 메모리(사실 한 건 = 수백 자)에서는 이 함수가 사실상 아무 일도 안 한다.
    긴 페이지가 실제로 쌓인 위키에서만 구절 임베딩 비용을 내고 그만큼 순위를 되찾는다.
    후보를 잘라 예산을 아끼는 방식은 실측에서 역효과였다 — 앞 구절만 보면 답이 뒤에 있을 때
    놓치고(−0.8pp), 후보를 앞쪽 몇 개로 줄이면 재정렬할 범위 자체가 사라져 이득이 0이 된다.

    반환 = (순위, 융합 가중). 가중은 QPP 게이트가 정한다 — 1.0 이면 기존과 대등, 0.0 이면
    표를 안 던진다. 실패는 조용히 빈 순위 — 시맨틱이 꺼져 있으면 기존 4스트림 그대로 돈다."""
    from .. import memory_semantic as sem

    if not sem.active() or not ranked:
        return [], 0.0
    query_vec = sem.embed(text)
    if query_vec is None:
        return [], 0.0
    scored: list[tuple[str, float]] = []
    for slug in ranked:
        entry = cand.get(slug)
        if not entry:
            continue
        chunks = _passages(entry[1])
        # 짧은 페이지는 건너뛴다. 리랭크는 **희석을 되돌리는** 연산인데, 페이지 전체가 한 구절이면
        # 되돌릴 희석이 없다 — 그런데도 순위에 한 표를 더 주면 같은 시맨틱 신호를 두 번 세는 셈이라
        # 어휘 신호가 묻힌다. 실측(100페이지 실코퍼스)에서 직접질의 hit@1 이 1.00 → 0.60 으로 무너졌다.
        # 개인 메모리의 정상 페이지는 사실 한 건이라 여기서 대부분 걸러지고, 대화 로그처럼
        # 길게 자란 페이지만 리랭크를 받는다.
        if len(chunks) < RERANK_MIN_PASSAGES:
            continue
        sims = [sem.cosine(query_vec, vec) for passage in chunks if (vec := sem.embed(passage))]
        if not sims:
            continue
        # 최댓값만 쓰면 너무 뾰족하다. 사실 질문은 한 문장이 답이라 max 가 맞지만, 간접 질문
        # ("내가 좋아할 만한 걸 추천해줘")은 문서 전체의 주제 일치가 답이라 max 가 엉뚱한 한 줄을
        # 집는다 — 실측에서 선호 유형만 −13pp 였다. 상위 몇 구절의 평균을 섞어 둘 다 살린다.
        top_sims = sorted(sims, reverse=True)[:RERANK_TOP_PASSAGES]
        scored.append(
            (slug, RERANK_MAX_WEIGHT * top_sims[0] + (1 - RERANK_MAX_WEIGHT) * (sum(top_sims) / len(top_sims)))
        )
    # 대상이 둘 미만이면 순위라 부를 것이 없다 — 아무것도 안 한다 (기존 4스트림 그대로).
    if len(scored) < 2:
        return [], 0.0
    # QPP 게이트 — 후보들이 안 갈리면 리랭크의 발언권을 줄인다 (위 RERANK_GATE_ENV 참조).
    # 회수 범위도 기존 순위도 안 건드린다: 가중 0 은 "4스트림 결과 그대로"라는 뜻이다.
    #
    # 분산은 문턱과 **무관하게** 항상 계산한다. 실수 스무 개의 평균과 제곱합이라 비용이 없고,
    # 단락 평가로 건너뛰면 게이트를 끈 상태에서 이 값을 관측할 수 없다 — 보정(문턱을 뽑는 일)은
    # 정의상 게이트가 꺼진 실행에서 해야 하므로, 그때 계기가 죽으면 보정 자체가 불가능해진다.
    weight = _gate_weight(_dispersion([score for _slug, score in scored]), _dispersion_floor())
    if weight <= 0.0:
        return [], 0.0
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return [pair for pair in scored if pair[1] > 0.0], weight


def _graph_order(pages: dict[str, tuple[dict, str]], seeds: dict[str, float]) -> list[tuple[str, float]]:
    """명시적 wiki-link 위에서만 personalized PageRank. LLM 추론 엣지는 만들지 않는다."""
    links = {slug: set() for slug in pages}
    for source, (meta, body) in pages.items():
        refs = re.findall(r"\[\[([^\]\n]+)\]\]", body)
        refs += [ref.strip() for ref in str(meta.get("links") or "").split(",") if ref.strip()]
        for ref in refs:
            raw = ref.split("|", 1)[0].split("#", 1)[0].strip()
            target = raw if raw in pages else slugify(raw)
            if target in pages and target != source:
                links[source].add(target)
                links[target].add(source)
    if not any(links.values()):
        return []
    personal = {slug: max(0.0, seeds.get(slug, 0.0)) if links[slug] else 0.0 for slug in pages}
    total = sum(personal.values())
    if not total:
        return []
    personal = {slug: score / total for slug, score in personal.items()}
    scores = personal.copy()
    for _ in range(PPR_STEPS):
        nxt = {slug: (1.0 - PPR_DAMPING) * personal[slug] for slug in pages}
        dangling = sum(scores[slug] for slug, neighbors in links.items() if not neighbors)
        for slug in pages:
            nxt[slug] += PPR_DAMPING * dangling * personal[slug]
        for source, neighbors in links.items():
            if not neighbors:
                continue
            share = PPR_DAMPING * scores[source] / len(neighbors)
            for target in neighbors:
                nxt[target] += share
        scores = nxt
    return sorted(((slug, score) for slug, score in scores.items() if score > 0), key=lambda p: (-p[1], p[0]))


def query(
    text: str,
    k: int = 5,
    d: str | None = None,
    track: bool = True,
    explain: bool = False,
    expand_links: bool = True,
) -> list[dict]:
    """FTS5 trigram 검색 (한국어 substring 대응). hit 는 usage 를 남긴다 — lint 부패 판정 원료.

    랭킹 = RRF(rank fusion). BM25 값과 스캔 매칭 카운트는 척도가 달라 점수 혼합이 무의미하므로
    각 경로의 '순위'만 합산한다 (동점 = 동순위). RRF 동률은 reference 최신성 → usage 회수
    빈도 → slug 순으로 가른다 — 보조 신호는 관련도 순위를 넘지 못한다.
    오염 페이지는 결과에서 제외한다 (2차 리뷰 ② — query 출력은 에이전트 컨텍스트로 흘러간다).
    제외 수는 결과에 실리지 않고 lint 가 threat 로 보고한다.

    명시적 links/[[wiki-link]]가 있으면 lexical·semantic seed에서 PPR로 연관 페이지를 확장해
    네 번째 RRF 스트림으로 합친다. expand_links=False는 A/B 평가용 기존 3-스트림 경로다.

    explain=True 면 각 hit 에 `streams`(fts/scan/semantic/graph 경로별 적중 여부)를 덧붙인다 —
    랭킹·반환 순서는 불변, 대시보드의 스트림 출처 표시(읽기 전용)용 파생 정보일 뿐이다."""
    d = d or memory_dir()
    k = max(1, min(int(k), 1000))  # 음수·0·과대 방지 (P2)
    if not os.path.isdir(os.path.join(d, PAGES)):
        return []

    clean_cache: dict[str, tuple[dict, str] | None] = {}

    def _clean(slug: str) -> tuple[dict, str] | None:
        if slug not in clean_cache:
            pg = _read(d, slug)
            clean_cache[slug] = pg if pg and not poisoned(*pg) else None
        return clean_cache[slug]

    phrase = text.strip().lower()
    raw_words = [w.lower() for w in re.split(r"[^\w가-힣%-]+", text) if len(w) >= 2]
    scan_words: list[str] = []
    particles = (
        "으로",
        "에서",
        "에게",
        "한테",
        "처럼",
        "까지",
        "부터",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "에",
        "의",
        "로",
        "과",
        "와",
        "도",
        "만",
    )
    # 조사는 물론 흔한 용언 활용도 어간 후보를 하나만 더 만든다. 한국어 FTS trigram은
    # `선호하는` 질의와 정본의 `선호한다`처럼 의미가 같아도 표면형이 달라지면 놓치므로,
    # 형태소 분석기 의존성 없이 길고 명확한 어미만 보수적으로 제거한다.
    endings = ("하는", "한다", "했다", "된다", "되는", "되며", "하며", "해서", "하기", "하게")
    for word in raw_words:
        scan_words.append(word)
        suffix = next((p for p in particles if word.endswith(p) and len(word) > len(p) + 1), None)
        if suffix:
            scan_words.append(word[: -len(suffix)])
        ending = next((e for e in endings if word.endswith(e) and len(word) > len(e) + 1), None)
        if ending:
            scan_words.append(word[: -len(ending)])
    # 정체성 슬롯 동의어 — "내 이름이 뭐야"가 "사용자의 호칭은 …" 페이지를 찾게 한다.
    # 승계(ingest)가 정본 어휘를 슬롯 안에서 갈아끼우므로 질의도 슬롯 단위로 넓힌다.
    scan_words.extend(slot_query_aliases(text))
    scan_words = list(dict.fromkeys(scan_words))

    def _scan_score(meta: dict, body: str) -> tuple[list[str], int]:
        hay = (meta.get("title", "") + "\n" + body).lower()
        matched = [w for w in scan_words if w in hay]
        return matched, len(matched) + (3 if phrase and phrase in hay else 0)

    # 후보 수집: slug → (meta, body, matched, scan_score). FTS 순위는 별도 리스트로 보존.
    cand: dict[str, tuple[dict, str, list[str], int]] = {}
    fts_order: list[tuple[str, float]] = []  # (slug, bm25) — bm25 는 작을수록 좋음
    try:
        conn = _db(d)
        words = [w for w in re.split(r"\s+", text.strip()) if len(w) >= 3]
        if words:
            match = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
            rows = conn.execute(
                "SELECT slug, bm25(fts) FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
                (match, k),
            ).fetchall()
            for slug, bm in rows:
                pg = _clean(slug)
                if pg is None:  # 오염·소실 — FTS 행이 낡았어도 정본 기준으로 거른다
                    continue
                meta, body = pg
                matched, s = _scan_score(meta, body)
                if not s:
                    continue  # stale FTS 행 — 현재 정본이 더는 질의와 맞지 않음
                cand[slug] = (meta, body, matched, s)
                fts_order.append((slug, bm))
        conn.close()
    except Exception:
        pass  # FTS 불능 → 아래 파일 스캔만으로 fail-open

    # 정본 스캔으로 FTS 일부 누락·stale 행을 보완한다. 메모리는 예산상 작아 완전성 우선.
    clean_pages = {slug: pg for slug in _pages(d) if (pg := _clean(slug)) is not None}
    for slug, pg in clean_pages.items():
        if slug in cand:
            continue
        meta, body = pg
        matched, s = _scan_score(meta, body)
        if s:
            cand[slug] = (meta, body, matched, s)

    # 시맨틱 스트림 (옵트인 3번째 경로) — 활성 시에만. lexical 이 놓친 패러프레이즈/동의어를
    # 회수한다. 벡터는 state.db 파생물이고, 비활성이면 이 블록 전체가 건너뛰어져 기존 2경로와
    # 완전히 동일하게 동작한다 (무회귀 계약). 문턱 미만 코사인은 후보로도 넣지 않는다.
    sem_order: list[tuple[str, float]] = []
    from .. import memory_semantic as sem

    if sem.active():
        qv = sem.embed(text)
        if qv:
            floor = _sem_floor()
            scored: list[tuple[str, float]] = []
            try:
                conn = _db(d)
                rows = conn.execute("SELECT slug, data FROM vec").fetchall()
                conn.close()
            except Exception:
                rows = []
            for slug, data in rows:
                try:
                    cos = sem.cosine(qv, sem.unpack(data))
                except Exception:
                    continue
                if cos >= floor:
                    scored.append((slug, cos))
            scored.sort(key=lambda p: -p[1])
            for slug, cos in scored[: max(k, 10)]:
                if slug not in cand:
                    pg = _clean(slug)  # 시맨틱 전용 후보도 오염 제외
                    if not pg:
                        continue
                    meta, body = pg
                    matched, _s = _scan_score(meta, body)
                    cand[slug] = (meta, body, matched, _s)  # _s 0 가능 — 순수 시맨틱 진입
                sem_order.append((slug, cos))

    if not cand:
        return []

    scan_order = sorted(((slug, float(c[3])) for slug, c in cand.items() if c[3] > 0), key=lambda p: -p[1])

    # 기존 검색 결과를 personalization seed로 삼고, 정본의 명시 링크만 PPR로 전파한다.
    # LLM 추출 그래프/별도 DB 없이 기존 Zettelkasten 링크를 실제 검색 신호로 재사용한다.
    seed_scores = dict.fromkeys(cand, 0.0)

    def _add_ranks(scores: dict[str, float], ordered: list[tuple[str, float]], weight: float = 1.0) -> None:
        rank, prev = 0, None
        for i, (slug, s) in enumerate(ordered):
            if s != prev:
                rank, prev = i + 1, s
            scores[slug] += weight / (RRF_K + rank)

    for ordered in (fts_order, scan_order, sem_order):
        _add_ranks(seed_scores, ordered)
    graph_order = _graph_order(clean_pages, seed_scores) if expand_links else []
    graph_order = graph_order[: max(k, 10)]
    for slug, _score in graph_order:
        if slug not in cand:
            meta, body = clean_pages[slug]
            matched, s = _scan_score(meta, body)
            cand[slug] = (meta, body, matched, s)

    # RRF: 경로별 순위 기여 1/(RRF_K+rank) 합산. 동점은 동순위 — 진짜 동등만 동률로 남는다.
    rrf = dict.fromkeys(cand, 0.0)

    _add_ranks(rrf, fts_order)
    # 스캔 스트림엔 실제 lexical 매칭(s>0)만 — 순수 시맨틱 후보(s=0)가 스캔 순위를 훔치지 않게
    _add_ranks(rrf, scan_order)
    _add_ranks(rrf, sem_order)  # 비활성이면 빈 리스트 → 무영향
    _add_ranks(rrf, graph_order)  # 링크가 없거나 A/B off면 빈 리스트 → 무영향

    # 2단계 — 4스트림이 정한 상위권만 구절 단위로 다시 보고, 그 순위와 **1:1 로** 융합한다.
    # 회수 범위는 안 넓히고 순위만 고친다. 왜 다섯 번째 스트림이 아니라 2단계인가:
    # 스트림 하나로 넣으면 가중이 1/5 로 희석돼 실측 이득이 +2.4pp → +0.4pp 로 죽었다
    # (LongMemEval-S 500문항). 이 신호는 그만큼 강하다 — 대등하게 세워야 값을 한다.
    base_order = sorted(cand, key=lambda slug: (-rrf[slug], slug))
    if rerank_enabled():
        rerank_order, rerank_weight = _rerank_order(text, cand, base_order[:RERANK_CANDIDATES])
        if rerank_order and rerank_weight > 0.0:
            fused = dict.fromkeys(cand, 0.0)
            _add_ranks(fused, [(slug, rrf[slug]) for slug in base_order], RERANK_BASE_WEIGHT)
            # 가중은 QPP 게이트가 정한다: 후보가 갈리면 1.0(대등), 안 갈리면 그만큼 작게.
            _add_ranks(fused, rerank_order, rerank_weight)
            rrf = fused

    # 빠르게 낡는 reference만 시간 multiplier를 계산하되 RRF 동률 안에서만 쓴다.
    # k=60 RRF의 인접 순위 차가 작아 전역 곱셈은 약한 최신성만으로 강한 관련도를 뒤집는다.
    # user/decision/insight는 강등하지 않고, last_used도 자기강화 편향 때문에 쓰지 않는다.
    temporal_scores = {slug: rrf[slug] * _temporal_multiplier(cand[slug][0]) for slug in cand}

    # usage 는 RRF·시간 보정 동률 타이브레이크 전용 prior (힌트, 증거 아님)
    uses: dict[str, int] = {}
    try:
        conn = _db(d)
        uses = dict(conn.execute("SELECT slug, uses FROM usage").fetchall())
        conn.close()
    except Exception:
        pass

    # 경로별 적중 집합 (explain 전용 파생 — 랭킹엔 미개입). fts=BM25 경로, scan=lexical(s>0),
    # semantic=벡터 코사인 경로. RRF 합산에 쓴 그 순서 리스트와 동일 출처라 표시가 실사와 일치한다.
    fts_slugs = {s for s, _ in fts_order}
    scan_slugs = {s for s, c in cand.items() if c[3] > 0}
    sem_slugs = {s for s, _ in sem_order}
    graph_slugs = {s for s, _ in graph_order}

    hits: list[dict] = []
    for slug in sorted(cand, key=lambda s: (-rrf[s], -temporal_scores[s], -uses.get(s, 0), s))[:k]:
        meta, body, matched, _s = cand[slug]
        lb = body.lower()
        needle = phrase if phrase in lb else next((w for w in matched if w in lb), "")
        i = lb.find(needle) if needle else 0
        hit = {
            "slug": slug,
            "title": meta.get("title", slug),
            "kind": _kind(meta),
            "snippet": body[max(i - 40, 0) : i + 80].strip(),
            "score": round(rrf[slug], 4),
        }
        if explain:
            hit["streams"] = {
                "fts": slug in fts_slugs,
                "scan": slug in scan_slugs,
                "semantic": slug in sem_slugs,
                "graph": slug in graph_slugs,
            }
        hits.append(hit)
    return _track(d, hits) if track else hits


def _track(d: str, hits: list[dict]) -> list[dict]:
    """hit 의 사용 흔적 기록 — lint 부패 판정 원료. 경로(FTS/스캔) 무관 공통, 실패는 무해."""
    try:
        conn = _db(d)
        ts = _today()
        with conn:
            for h in hits:
                conn.execute(
                    "INSERT INTO usage(slug, uses, last_used) VALUES(?,1,?) "
                    "ON CONFLICT(slug) DO UPDATE SET uses = uses + 1, last_used = ?",
                    (h["slug"], ts, ts),
                )
        conn.close()
    except Exception:
        pass
    return hits


# ── 동결 스냅샷 주입 — Heimdall 세션 생성 시 1회 ─────────────


def _neutralize(s: str) -> str:
    """주입면 경계 무력화 (P0) — 각괄호를 유사문자로 치환해 태그/펜스 탈출 차단.

    비가시 문자는 여기서도 벗긴다. poisoned() 가 이미 막지만 그건 '페이지째 제외'라
    저장 이전에 심어진 것·판정을 비껴간 것이 남는다. 주입면에서 한 번 더 벗기는 값이
    제외보다 크다 — 마지막 관문은 조용히 무해하게 만드는 쪽이 낫다."""
    stripped = "".join(c for c in s if c not in _INVISIBLE and not 0xE0000 <= ord(c) <= 0xE007F)
    return stripped.replace("<", "‹").replace(">", "›")


def _row(title: str, desc: str) -> str:
    """카탈로그 행 — 제목과 설명이 같은 말이면 한 번만 적는다.

    한 문장짜리 페이지에서는 title 이 곧 본문 첫 줄이고 _desc 도 본문 첫 줄이라, 그대로 두면
    주입면의 절반이 같은 문장의 반복이 된다. 자르는 길이가 달라(제목 80·설명 90) 한쪽이 다른
    쪽의 접두사가 되므로 긴 쪽을 남긴다 — 잘림이 덜한 쪽이다."""
    if desc.startswith(title) or title.startswith(desc):
        return f"- {max(title, desc, key=len)}"
    return f"- {title} — {desc}"


def _snapshot_rows(d: str) -> list[tuple[str, str]]:
    """주입용 카탈로그 행 — (kind, row). 페이지 재검증(오염 제외) + 경계 무력화 + kind 화이트리스트.
    index.md 와 별도(주입 안전용)이다.

    행에 kind 를 적지 않는다 — 칸 머리글이 이미 말하므로 행마다 반복하면 그만큼 예산만 먹는다.
    정렬은 칸 안에서 updated 내림차순: 예산이 모자랄 때 알파벳순으로 자르면 무엇이 살아남는지가
    임의가 된다(슬러그 첫 글자가 운을 가른다). 최신이 먼저 살아야 잘림이 뜻을 갖는다."""
    rows: list[tuple[str, str, str]] = []
    for slug in _pages(d):
        pg = _read(d, slug)
        if not pg:
            continue
        meta, body = pg
        if poisoned(meta, body):
            continue  # 오염 페이지는 주입 제외 (lint 전이라도)
        title = _neutralize(meta.get("title", slug))
        rows.append((_kind(meta), str(meta.get("updated", "")), _row(title, _neutralize(_desc(meta, body)))))
    rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
    return [(kind, row) for kind, _updated, row in rows]


def _section(kind: str, label: str, rows: list[str], budget: int) -> str:
    """칸 하나 렌더 — 머리글에 사용률을 적는다. 빈 칸·예산 0 은 빈 문자열.

    사용률을 100% 로 깎지 않는다: 저장은 무제한이라 칸은 실제로 넘칠 수 있고, `143%` 라고
    적혀 있어야 모델이 그 칸을 통합하자고 먼저 말한다. 계기가 거짓말하면 계기가 아니다.
    예산은 행에만 건다 — 머리글은 계기판이라 예산 밖이다."""
    if budget <= 0 or not rows:
        return ""
    full = sum(len(r) + 1 for r in rows)
    kept: list[str] = []
    used = 0
    for row in rows:
        if used + len(row) + 1 > budget:
            break
        kept.append(row)
        used += len(row) + 1
    if len(kept) < len(rows):  # 잘림 — 경고 한 줄도 예산 안에서 (자리 없으면 행을 물린다)
        while kept and used + len(_SNAPSHOT_WARN) + 1 > budget:
            used -= len(kept.pop()) + 1
        if not kept:
            return ""
        kept.append(_SNAPSHOT_WARN)
    if not kept:
        return ""
    pct = round(100 * full / budget)
    return f"## {label} `{kind}` [{pct}% — {full:,}/{budget:,} chars]\n" + "\n".join(kept)


def section_usage(d: str | None = None) -> list[tuple[str, int, int]]:
    """칸별 (kind, 실제 주입 문자수, 예산). 페이지가 없는 칸은 빼고 _SECTIONS 순서로.

    lint·대시보드가 "어느 칸이 꽉 찼나"를 묻는 유일한 통로다. 세는 대상은 주입 행이라
    잘림 여부와 무관하게 '원래 얼마인지'를 돌려준다 — 넘친 양을 알아야 통합 판단이 선다."""
    d = d or memory_dir()
    rows = _snapshot_rows(d)
    budgets = kind_budgets()
    usage: list[tuple[str, int, int]] = []
    for kind, _label in _SECTIONS:
        used = sum(len(r) + 1 for k, r in rows if k == kind)
        if used:
            usage.append((kind, used, budgets.get(kind, 0)))
    return usage


def _fit_total(prefix: str, body: str, suffix: str, budget: int) -> str:
    """총량 상한 — 조립된 블록을 뒤에서부터 잘라 예산 안에 넣는다 (구 index_budget_chars).

    뒤가 먼저 죽는 건 의도다: _SECTIONS 가 값비싼 칸을 앞에 세워 뒀다."""
    lines = body.split("\n")
    truncated = False
    while lines:
        while lines and lines[-1].startswith("## "):  # 행 없는 머리글은 계기가 아니라 껍데기
            lines.pop()
            truncated = True
        if not lines:
            break
        candidate = [*lines, _SNAPSHOT_WARN] if truncated else lines
        text = prefix + "\n".join(candidate) + suffix
        if len(text) <= budget:
            return text
        lines.pop()
        truncated = True
    warned = prefix + _SNAPSHOT_WARN + suffix
    return warned if len(warned) <= budget else ""


def snapshot_note(d: str | None = None) -> str:
    """세션 프롬프트 주입분 — 카탈로그를 부분(kind)별 예산 안에서 동결. 페이지 없으면 빈 문자열.

    칸을 나누는 이유는 예산이 아니라 굶주림이다. 총량 하나면 수가 많은 칸(reference)이
    값비싼 칸(user·feedback)을 밀어내는데, 사람이 같은 말을 반복하지 않게 만드는 건 뒤쪽이다.
    칸마다 상한을 주면 어느 칸도 굶지 않는다.

    "동결" 계약 = Heimdall 인스턴스 수명. self.identity 에 1회 결합 후 세션 중 불변
    (KV 캐시 보존). /lagom 등 Heimdall 재생성 경로에서만 재렌더된다."""
    try:
        if not inject_enabled():  # 킬스위치 (2차 리뷰 ⑦) — off 면 어느 provider 로도 전송 없음
            return ""
        d = d or memory_dir()
        rows = _snapshot_rows(d)
        if not rows:
            return ""
        budgets = kind_budgets()
        prefix = (
            '\n\n<memory-context scope="personal">\n'
            "개인 메모리 카탈로그 (힌트 — 완료 증거 아님). 상세는 asgard memory query.\n"
        )
        suffix = "\n</memory-context>"
        sections = [
            block
            for kind, label in _SECTIONS
            if (block := _section(kind, label, [r for k, r in rows if k == kind], budgets.get(kind, 0)))
        ]
        if not sections:
            return ""
        body = "\n".join(sections)
        total = index_budget()
        if total is not None:
            return _fit_total(prefix, body, suffix, total)
        return prefix + body + suffix
    except Exception:
        return ""  # fail-open — 메모리 불능이 세션을 막지 않는다


RECALL_BUDGET = 900  # chars — 회수 블록 상한 (턴마다 붙으므로 카탈로그보다 훨씬 작게)


def _diversify(hits: list[dict], k: int) -> list[dict]:
    """한 종류가 회수 블록을 독식하지 못하게 자른다 — 순위는 건드리지 않는다.

    같은 공간에 섞여 있는 서로 다른 성격의 기억은 서로를 대체할 수 있는 근거처럼 회수된다
    (MemGuard, arXiv 2605.28009 — "heterogeneous memory contamination"). asgard 는 kind 로
    성격을 이미 구분해 두었는데 회수는 그걸 안 봤다: reference 세 장이 상위를 차지하면
    바로 아래의 feedback("이렇게 하지 말라던 그것")이 블록에 못 들어온다. 값이 다른 게 아니라
    종류가 다른 것이라 순위로만 자르면 안 되는 자리다.

    한 종류 상한은 과반(k=3 이면 2). 다른 종류에 후보가 없으면 상한을 안 걸고 그대로 채운다 —
    다양성을 위해 빈 줄을 남기지는 않는다."""
    cap = max(1, (k + 1) // 2)
    if len({h.get("kind") for h in hits}) < 2:
        return hits[:k]
    picked: list[dict] = []
    seen: dict[str, int] = {}
    for hit in hits:  # 1차 — 상한을 지키며 순위대로
        kind = str(hit.get("kind") or "")
        if seen.get(kind, 0) >= cap:
            continue
        picked.append(hit)
        seen[kind] = seen.get(kind, 0) + 1
        if len(picked) == k:
            return picked
    for hit in hits:  # 2차 — 자리가 남으면 상한을 풀고 순위대로 채운다
        if hit not in picked:
            picked.append(hit)
            if len(picked) == k:
                break
    return picked


RECALL_PREFIX = '\n\n<memory-recall scope="personal">\n요청 관련 개인 메모리 (힌트 — 완료 증거 아님):\n'
RECALL_SUFFIX = "\n</memory-recall>"


def recall_rows(text: str, k: int = 3, d: str | None = None) -> list[str]:
    """회수 본문 목록 — **렌더도 예산도 여기서 안 한다**.

    레인을 후보 생산자로 갈라 둔 이유는 조립기(`memory.assemble`)가 여섯 레인을 하나의
    예산 위에서 겨루게 하고 레인 간 중복을 걷어내야 하기 때문이다. 각 레인이 자기 예산을
    자기가 자르던 시절에는 같은 사실이 다섯 레인으로 다섯 번 실릴 수 있었다."""
    if not inject_enabled():
        return []
    # 넉넉히 뽑아 종류를 섞은 뒤 k 개로 줄인다 — 왜인지는 _diversify 참조.
    hits = query(text, k=max(k, k * 2), d=d)  # track=True — 회수 흔적이 lint 부패 판정 원료
    if not hits:
        return []
    return [_hit_row(h) for h in _diversify(hits, k)]


def _hit_row(hit: dict) -> str:
    """회수 한 줄 — 제목과 발췌가 같은 말이면 한 번만 적는다.

    스냅샷 쪽은 이미 이 규율을 갖고 있었는데(`_row`) 회수 쪽에는 없었다. 한 문장짜리 페이지는
    title 이 곧 본문이고 snippet 도 그 본문에서 잘라 오므로, 그대로 두면 **같은 문장이 한 줄에
    두 번** 실린다 (실측 26-07-29: 182자 중 절반이 반복). 레인 간 중복을 걷어내면서 한 줄
    안의 중복을 남겨 두는 것은 앞뒤가 안 맞는다."""
    title = _neutralize(str(hit["title"]))[:120]
    snippet = _neutralize(str(hit["snippet"]))[:160]
    head = f"{title} `{hit['kind']}`"
    if not snippet:
        return head
    # 한쪽이 다른 쪽을 품으면 긴 쪽만 남긴다 — 자르는 길이가 달라(120/160) 접두사 관계가 흔하다.
    if snippet in title or title in snippet:
        return f"{max(title, snippet, key=len)} `{hit['kind']}`"
    return f"{head} — {snippet}"


def recall_note(text: str, k: int = 3, d: str | None = None) -> str:
    """요청 기반 zero-LLM 회수 블록 — DIRECT/Thinker 턴 시작 시 결정론 주입 (감사 권고:
    "모델이 자발적으로 CLI 를 부르는" 순응 의존을 없앤다). query 가 오염 페이지를 이미
    제외하므로 여기선 경계 무력화 + 예산만. 무적중·킬스위치 off = 빈 문자열 (무변화).

    이 레인 **혼자** 쓰는 표면(`asgard memory recall`·개인 메모리만 보는 호출)용이다. 여섯
    레인을 같이 싣는 자리는 `memory_context.recall_note` 가 조립기로 간다."""
    try:
        rows = recall_rows(text, k=k, d=d)
        if not rows:
            return ""
        from .assemble import Candidate, Lane, assemble

        lane = Lane("personal", RECALL_PREFIX, RECALL_SUFFIX, RECALL_BUDGET)
        return assemble(
            [Candidate("personal", body, rank=index) for index, body in enumerate(rows)],
            (lane,),
            budget=RECALL_BUDGET,
        )
    except Exception:
        return ""  # fail-open


DISTILL_MAX_PATHS = 3  # 넛지당 경로 상한 — 위치 지식의 최소 형태만, 목록 폭주 방지


def distill_nudge(request: str, response: str, root: str) -> str:
    """탐색 발견 저장 넛지 (0-LLM) — 응답에 인용된 '실존 파일 경로'만 증류해 기존 ingest
    승인 게이트로 안내한다. 저장은 ask-before-save 그대로 — 여기는 안내문뿐이다.

    응답 유래 자유 텍스트는 명령에 싣지 않는다: 디스크 실존 + root 격리 검증을 통과한
    경로 토큰만 후보가 된다 (모델 응답을 명령 제안으로 렌더링하는 표면의 인젝션 차단).
    숏컷 벤치(26-07-16) 근거 — 위치 지식이 recall 이득(토큰 -67%)의 최대 원천."""
    try:
        # 킬스위치는 여기서 라이브로 본다 — 호출측 플래그는 세션 생성 시점 캐시라
        # 세션 도중 ASGARD_MEMORY_INJECT=off 를 반영하지 못한다.
        if not inject_enabled():
            return ""
        req = re.sub(r"\s+", " ", (request or "")).strip().replace('"', "'")
        if not req or not response or scan_threats(req):
            return ""
        real_root = os.path.realpath(root)
        paths: list[str] = []
        for tok in re.findall(r"[\w][\w./\-]*\.[A-Za-z0-9_]+", response):
            p = tok.strip(".")
            if "/" not in p or os.path.isabs(p) or p.startswith((".asgard/", ".git/")):
                continue
            full = os.path.realpath(os.path.join(real_root, p))
            if os.path.commonpath([real_root, full]) != real_root:
                continue  # 경로 순회 시도 — 후보 자격 없음
            if p not in paths and os.path.isfile(full):
                paths.append(p)
            if len(paths) >= DISTILL_MAX_PATHS:
                break
        if not paths:
            return ""
        fact = f"{req[:80]} → {', '.join(paths)}"
        return f'⠶ 탐색 발견 저장 후보 (승인 전엔 저장되지 않음):\n  asgard memory ingest "{fact}" --kind reference'
    except Exception:
        return ""  # fail-open — 넛지는 실행을 인질로 잡지 않는다
