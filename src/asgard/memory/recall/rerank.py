"""구절 리랭크(2단계) — 긴 페이지에서 통짜 임베딩이 놓친 순위를 되찾고, QPP 게이트로 발언권을 정한다."""

from __future__ import annotations

import contextlib
import hashlib
import math
import os

from ..index import _db
from ..policy import _memory_settings

RERANK_CANDIDATES = 20  # 리랭크 대상 — RRF 상위 이만큼만 다시 본다 (전량 재계산은 비싸다)
RERANK_PASSAGE_CHARS = 600
RERANK_MAX_PASSAGES = 40  # 페이지 하나에서 볼 구절 상한 (~24,000자까지 덮는다)
# 이만큼 구절이 안 나오는 페이지는 리랭크 대상이 아니다 — 희석이 없으면 되돌릴 것도 없다.
RERANK_MIN_PASSAGES = 3
RERANK_TOP_PASSAGES = 3  # 평균에 쓸 상위 구절 수
RERANK_MAX_WEIGHT = 0.5  # max와 상위평균의 배합 — 1.0 이면 순수 max (선호 유형에서 −13pp)
# 융합에서 기존 4스트림 순위에 주는 가중 (리랭크는 항상 1.0). 1.0 = 대등.
# 리랭크가 우선하는 자리와 지는 자리가 갈리기 때문에 둔 손잡이다: 사실 질문은 리랭크가 맞고,
# 간접 질문("내가 좋아할 만한 걸 추천해줘")은 어휘가 맞다. 어느 쪽도 항상 옳지 않다.
RERANK_BASE_WEIGHT = 1.0
# 2단계를 끄는 세션 오버라이드 — 시맨틱 스트림의 ASGARD_MEMORY_SEMANTIC과 같은 모양이다.
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
# 여기 옮기면 정확히 V2의 실패 모양이다: 모든 구절이 비슷해 보이면 순위를 바꿀 근거가 없다.
#
# NQC는 코퍼스 점수로 정규화하지만 우리에겐 그 상수가 없다. 코사인은 척도가 고정
# ([-1,1]) 이고 후보 집합이 작으므로 **변동계수**(σ/μ)를 쓴다 — 척도 무관이고 stdlib로 끝난다.
RERANK_DISPERSION_ENV = "ASGARD_MEMORY_RERANK_DISPERSION"
# 게이트의 **모양** — 기권(hard)인가 감쇠(soft)인가.
#
# 처음 낸 것은 hard 였다: 분산이 문턱 미만이면 리랭크 표를 아예 안 던진다. held-out 계측이
# 그 대가를 정확히 보여 줬다 (26-07-29):
#   V2(새 도메인) 퇴행 9건 → 2건  ← 얻은 것
#   M(건초더미 9배) R@5 동일하나 NDCG −0.9pp · MRR −1.4pp  ← 치른 것
# M에서 리랭크는 순증(27:14)이었으므로, 낮은 분산 질의에서도 **순위를 다듬는 몫**이 있었는데
# 기권이 그걸 통째로 버린 것이다. 신호가 약하다는 것과 신호가 없다는 것은 다른 말이다.
#
# soft는 그 사이를 열어 본 시도다: 분산을 **확신도**로 읽어 융합 가중을 낮춘다.
#   w(σ/μ) = min(1, 분산 / 문턱)
# 문턱 이상이면 1.0이라 S의 이득은 정의상 보존되고, 문턱 미만에서만 비례해 줄어든다.
#
# **재 봤고, 안 됐다 (26-07-29 3벌 실측).** 감쇠가 너무 완만하다 — V2에서 해를 끼치던 질의의
# 분산이 문턱 **바로 아래**(0.82~0.95 × 문턱)에 몰려 있어서 가중이 0.8 이상으로 거의 안 깎인다.
#
#   V2 R@5:  OFF 0.800 · 게이트없음 0.750(4:9) · **hard 0.780(0:2)** · soft 0.760(4:8)
#   S  R@5:  게이트없음 0.956 · **hard 0.960** · soft 0.956 (게이트없음과 동률)
#
# 즉 soft는 게이트 없음과 거의 같다 — 지키려던 것을 못 지킨다. 그래서 기본은 **hard** 다.
# soft를 남겨 두는 이유는 이 판정이 취향이 아니라 계측이었음을 남이 재현할 수 있어야 하기
# 때문이다 (`--gate soft`). hard가 M에서 치르는 MRR −1.4pp는 여전히 열린 값이고, 그걸
# 되찾으려면 지금 신호가 못 주는 구분이 필요하다 — 다음 라운드의 held-out 몫이다.
RERANK_GATE_ENV = "ASGARD_MEMORY_RERANK_GATE"
RERANK_GATE_MODE = "hard"
# 문턱은 **개발 집합(S)에서만** 뽑았다. held-out(M·V2)을 보고 고르면 그 절의 증거값이
# 그 자리에서 사라진다 — 보고서가 스스로 경계한 그 행동이다.
#
# 보정 규칙(`benchmarks/longmemeval/calibrate_dispersion.py`, 산출물 calibration-dispersion.json):
#   floor = 0.99 × min{ 분산(q) : q ∈ S, 리랭크가 그 질의를 0→1로 이긴 경우 }
# 즉 "리랭크가 실제로 값을 한 질의는 하나도 안 막는다"를 **구성으로** 보장하는 가장 큰 문턱이다.
# S 점수를 최대화하는 값을 찾지 않는다 — 그건 30문항 위 2문항을 좇는 과적합이다.
#
# S 500문항 실측 (26-07-29): 리랭크 발동 500 · 이김 13 · 짐 4 · 무변화 483.
#   이긴 질의의 분산 [0.1518 … 0.3548]  ·  진 질의의 분산 [0.1237, 0.1275, 0.1548, 0.3643]
#   → floor 0.1503에서 **이긴 13건 전부 통과, 진 4건 중 2건 차단**, 전체 기권률 6.2%.
# 진 사례가 분포 하단에 몰린 것이 NQC의 주장(낮은 분산 = query drift)과 방향이 같다.
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
    남이 그 수치를 검증한다 — `ASGARD_MEMORY_RERANK`와 같은 모양의 손잡이다."""
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
    """게이트 모양 — env > 설정 > 기본 `hard`(기권). `soft`(감쇠)는 보고서 재현용으로만 남아 있다.

    기본값은 위 `RERANK_GATE_MODE` 절의 실측이 고른 것이다 — 두 이름의 뜻이 여기서 갈리면
    설정을 읽는 사람이 반대쪽을 켠다."""
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

    문턱이 0(게이트 없음)이면 항상 1.0이라 도입 전과 바이트 동일하게 돈다."""
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


class _PassageVectors:
    """구절 벡터 공급 — `state.db` 의 `vec_passage` 파생 칸을 앞세우고, 없을 때만 임베딩한다.

    페이지 벡터에는 "본문 sha 가 같으면 재임베딩하지 않는다"가 명시적 계약인데
    (`index._vec_upsert`) 구절 벡터에는 그 계약이 없었다. 그래서 **글자 그대로 같은 질의**를
    두 번 쳐도 같은 계산을 그대로 다시 했다 (실측 26-08-02: 1회차 636 호출 · 2회차 636 호출).
    리랭크가 값을 하는 자리는 정의상 긴 페이지라, 그 조건이 성립하는 순간 비용이 매 턴 반복된다.

    임베더가 바뀌면 저장된 벡터는 **다른 공간의 것**이라 통째로 버린다. 이름을 적는 칸은
    페이지 벡터와 따로 쓴다 (`index.passage_model` 참조).

    `d` 가 없으면(단위 시험처럼 디렉터리 없이 부르는 자리) 질의 수명 메모만 쓴다 — 그때도
    같은 구절을 두 번 임베딩하지는 않는다."""

    __slots__ = ("_conn", "_d", "_memo", "_pending", "_ready")

    def __init__(self, d: str | None) -> None:
        self._d = d
        self._conn = None
        self._ready = False
        self._memo: dict[tuple[str, str], list[list[float]]] = {}
        # 쓰기는 모아서 한 번에 넘긴다 — 후보 스무 장이면 커밋도 스무 번이 되고, 커밋 비용은
        # 디스크마다 다르다. 회수 경로에서 사람을 기다리게 할 이유가 없는 자리다.
        self._pending: list[tuple[str, str, list[bytes]]] = []

    def _db_conn(self):
        """DB 연결 (지연) — 임베더 이름이 다르면 접어 둔 구절을 먼저 버린다. 실패는 None."""
        if self._ready:
            return self._conn
        self._ready = True
        if not self._d:
            return None
        from ... import memory_semantic as sem
        from ..index import passage_model, passage_reset

        with contextlib.suppress(Exception):
            conn = _db(self._d)
            model = sem.loaded_model()
            if not model:  # 이름을 모르면 접어 두지 않는다 — 어느 자로 잰 값인지 못 적는다
                conn.close()
                return None
            if passage_model(conn) != model:
                passage_reset(conn, model)
            self._conn = conn
        return self._conn

    def of(self, slug: str, body: str, chunks: list[str]) -> list[list[float]]:
        """구절 벡터 목록 — 임베딩에 실패한 구절은 빠진다 (캐시 없을 때의 거동과 같다)."""
        from ... import memory_semantic as sem

        sha = hashlib.sha1(body.encode()).hexdigest()
        hit = self._memo.get((slug, sha))
        if hit is not None:
            return hit
        conn = self._db_conn()
        if conn is not None:
            from ..index import passage_vectors

            blobs = passage_vectors(conn, slug, sha)
            if blobs:
                vectors = [sem.unpack(blob) for blob in blobs]
                self._memo[(slug, sha)] = vectors
                return vectors
        vectors = [vec for passage in chunks if (vec := sem.embed(passage))]
        self._memo[(slug, sha)] = vectors
        if conn is not None and vectors:
            self._pending.append((slug, sha, [sem.pack(vec) for vec in vectors]))
        return vectors

    def close(self) -> None:
        """모아 둔 구절 벡터를 한 번에 접어 두고 연결을 닫는다. 실패는 무해 — 다음 질의에 다시 잰다."""
        if self._conn is None:
            return
        if self._pending:
            from ..index import passage_remember

            passage_remember(self._conn, self._pending)
            self._pending.clear()
        with contextlib.suppress(Exception):
            self._conn.close()
        self._conn = None


def _rerank_order(
    text: str,
    cand: dict,
    ranked: list[str],
    d: str | None = None,
    query_vec: list[float] | None = None,
) -> tuple[list[tuple[str, float]], float]:
    """구절 최대 유사도 순위 — 페이지가 길수록 통짜 임베딩이 못 보는 것을 되찾는다.

    페이지 벡터 하나는 문서 전체의 평균이라, 긴 페이지에서는 정작 답이 든 한 문장이 나머지
    수천 자에 희석된다 (LongMemEval-S 실측: 세션 중앙값 1만 자). 구절로 쪼개 최댓값을 쓰면
    같은 임베더로도 순위가 날카로워진다 — 새 모델도, torch도 필요 없다.

    **다섯 번째 스트림일 뿐 대체가 아니다.** 실측(500문항)에서 이 점수로 순위를 통째로
    갈아치우면 어휘·그래프 신호를 버려 이득이 반으로 줄었다. RRF에 한 표로 넣는 게 낫다.

    **비용은 이득이 있는 곳에서만 낸다.** 짧은 페이지는 아래 길이 게이트에서 통째로 빠지므로
    정상적인 개인 메모리(사실 한 건 = 수백 자)에서는 이 함수가 사실상 아무 일도 안 한다.
    긴 페이지가 실제로 쌓인 위키에서만 구절 임베딩 비용을 내고 그만큼 순위를 되찾는다.
    후보를 잘라 예산을 아끼는 방식은 실측에서 역효과였다 — 앞 구절만 보면 답이 뒤에 있을 때
    놓치고(−0.8pp), 후보를 앞쪽 몇 개로 줄이면 재정렬할 범위 자체가 사라져 이득이 0이 된다.

    반환 = (순위, 융합 가중). 가중은 QPP 게이트가 정한다 — 1.0 이면 기존과 대등, 0.0 이면
    표를 안 던진다. 실패는 조용히 빈 순위 — 시맨틱이 꺼져 있으면 기존 4스트림 그대로 돈다."""
    from ... import memory_semantic as sem

    if not sem.active() or not ranked:
        return [], 0.0
    # 질의 벡터는 호출자(시맨틱 스트림)가 이미 만들었으면 그것을 쓴다 — 같은 문자열을 한 턴에
    # 두 번 임베딩할 이유가 없다.
    query_vec = query_vec if query_vec is not None else sem.embed(text)
    if query_vec is None:
        return [], 0.0
    passages = _PassageVectors(d)
    try:
        scored = _passage_scores(query_vec, cand, ranked, passages)
    finally:
        passages.close()
    # 대상이 둘 미만이면 순위라 부를 것이 없다 — 아무것도 안 한다 (기존 4스트림 그대로).
    if len(scored) < 2:
        return [], 0.0
    # QPP 게이트 — 후보들이 안 갈리면 리랭크의 발언권을 줄인다 (위 RERANK_GATE_ENV 참조).
    # 회수 범위도 기존 순위도 안 건드린다: 가중 0은 "4스트림 결과 그대로"라는 뜻이다.
    #
    # 분산은 문턱과 **무관하게** 항상 계산한다. 실수 스무 개의 평균과 제곱합이라 비용이 없고,
    # 단락 평가로 건너뛰면 게이트를 끈 상태에서 이 값을 관측할 수 없다 — 보정(문턱을 뽑는 일)은
    # 정의상 게이트가 꺼진 실행에서 해야 하므로, 그때 계기가 죽으면 보정 자체가 불가능해진다.
    weight = _gate_weight(_dispersion([score for _slug, score in scored]), _dispersion_floor())
    if weight <= 0.0:
        return [], 0.0
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return [pair for pair in scored if pair[1] > 0.0], weight


def _passage_scores(
    query_vec: list[float],
    cand: dict,
    ranked: list[str],
    passages: _PassageVectors,
) -> list[tuple[str, float]]:
    """후보별 구절 점수 — max 와 상위평균의 배합. 구절이 모자란 페이지는 빠진다."""
    from ... import memory_semantic as sem

    scored: list[tuple[str, float]] = []
    for slug in ranked:
        entry = cand.get(slug)
        if not entry:
            continue
        chunks = _passages(entry[1])
        # 짧은 페이지는 건너뛴다. 리랭크는 **희석을 되돌리는** 연산인데, 페이지 전체가 한 구절이면
        # 되돌릴 희석이 없다 — 그런데도 순위에 한 표를 더 주면 같은 시맨틱 신호를 두 번 세는 셈이라
        # 어휘 신호가 묻힌다. 실측(100페이지 실코퍼스)에서 직접질의 hit@1이 1.00 → 0.60으로 무너졌다.
        # 개인 메모리의 정상 페이지는 사실 한 건이라 여기서 대부분 걸러지고, 대화 로그처럼
        # 길게 자란 페이지만 리랭크를 받는다.
        if len(chunks) < RERANK_MIN_PASSAGES:
            continue
        sims = [sem.cosine(query_vec, vec) for vec in passages.of(slug, entry[1], chunks)]
        if not sims:
            continue
        # 최댓값만 쓰면 너무 뾰족하다. 사실 질문은 한 문장이 답이라 max가 맞지만, 간접 질문
        # ("내가 좋아할 만한 걸 추천해줘")은 문서 전체의 주제 일치가 답이라 max가 엉뚱한 한 줄을
        # 집는다 — 실측에서 선호 유형만 −13pp 였다. 상위 몇 구절의 평균을 섞어 둘 다 살린다.
        top_sims = sorted(sims, reverse=True)[:RERANK_TOP_PASSAGES]
        scored.append(
            (slug, RERANK_MAX_WEIGHT * top_sims[0] + (1 - RERANK_MAX_WEIGHT) * (sum(top_sims) / len(top_sims)))
        )
    return scored
