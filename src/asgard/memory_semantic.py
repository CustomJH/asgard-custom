"""개인 메모리 시맨틱 스트림 (기본 켜짐) — Tier0 검색을 lexical → hybrid로.

배경 (26-07-18): agentmemory 실사 결론 — 1차 메모리로 그대로 채택은 부적합(iii 상주
데몬·KV 필터 격리·기본 벡터 OFF)하나, 검색 파이프라인(3-스트림 RRF + 로컬 임베딩)은
이식 가치가 있다. 여기가 그 이식이다 — 저장·오케스트레이션은 Asgard 정본 계약을 지키고
알고리즘만 취한다.

계약 (memory.py 정본 원칙 상속):
  · **정본 불변** — 벡터는 state.db의 파생물이다. 지워도(또는 손상돼도) reindex로 복원되고,
    파일 md가 여전히 지식의 정본이다. 벡터는 pages/ 를 절대 대체하지 않는다.
  · **fail-open** — 임베더 미설치 또는 설정 off 면 embedder()=None → query()가 기존 2경로
    (FTS5 BM25 + 정본 스캔)로 완전히 동일하게 동작한다. 어떤 예외도 검색을 막지 않는다.
  · **stdlib 수학** — 벡터 수학(pack/cosine)은 stdlib(array·math)만 쓴다. 임베딩 모델
    라이브러리(model2vec)는 26-07-27부터 기본 의존성이지만, 없거나 못 불러도 2경로가 돈다.
  · **정직한 상태** — agentmemory는 "로컬 임베딩 기본"이라 광고하고 실제론 OFF 였다. 우리는
    active()로 활성/비활성을 대시보드·doctor에 그대로 노출한다 (숨기지 않는다).

설정:  [memory].semantic = "local" | "off"  (**기본 "local"** — 26-07-27 오딘 결정)
      env  ASGARD_MEMORY_SEMANTIC로 세션 오버라이드 (off|local).

모델 바꾸기 — 기본값은 아래 실측으로 고른 potion-multilingual-128M 이고, **언제든 갈 수 있다**:
      [memory].semantic_model = "<hf 모델 이름>"     설정 파일 (영구)
      ASGARD_MEMORY_SEMANTIC_MODEL=<hf 모델 이름>    환경 변수 (세션)
  model2vec 정적 모델을 먼저 시도하고, 못 읽으면 sentence-transformers로 넘어간다.
  그래서 두 계열 모델 이름을 다 쓸 수 있다.

  ⚠ 바꾼 뒤에는 **asgard memory reindex**를 돌려야 한다. 저장된 벡터는 옛 모델의 차원이고,
  cosine은 길이가 다르면 0을 돌려주므로(차원 오염 방지) 재색인 전까지 의미 검색은 조용히
  아무것도 못 찾는다. 대시보드 '의미 검색 준비' 칸이 벡터가 섞였음을 표시한다.

기본을 켜기로 한 근거 (실측 26-07-27, 40페이지·80질의 벤치):
  hit@1 0.750 → 0.850, 놓친 질의 11 → 2건, **회귀 0건**. 한국어는 0.787 → 0.894.
  대가는 프로세스당 모델 로드 ~1.4초(첫 실행은 모델 내려받느라 ~35초·약 1GB)다.
  오딘 판단: 지연을 감수하고 회수 품질을 택한다. 끄려면 semantic="off" 한 줄이면 되고,
  그때는 lexical 2경로로 **완전히 동일하게** 돌아간다 (fail-open 계약 불변).

모델 선택이 한국어에 걸려 있다 (같은 날 실측, 관련 문장 − 무관 문장 코사인 차):
  potion-base-8M        한국어 -0.011 · 영어 +0.270   ← 한국어를 아예 구분 못 한다
  potion-retrieval-32M  한국어 -0.023 · 영어 +0.133   ← 마찬가지
  potion-multilingual   한국어 +0.261 · 영어 +0.147   ← 유일하게 성립
  작은 모델은 로드가 3배 빠르지만(345ms vs 962ms) 한국어에서 **음수 판별력**이다 —
  무관한 문장을 관련 문장보다 가깝다고 본다. 속도로 바꿀 수 있는 품질이 아니라서 큰 쪽을 쓴다.

ollama 임베딩 경로를 붙이지 않은 이유 (같은 벤치에서 실측):
  nomic-embed-text(768d)는 hit@1 0.812로 model2vec potion-multilingual-128M(0.850)보다
  낮았고, 한국어는 0.766 vs 0.894로 크게 뒤졌으며, 질의 지연은 19.4ms vs 3.8ms로 5배였다.
  HTTP 왕복을 검색 경로에 넣을 값이 없다. 로컬 정적 임베더가 이 과업에서 더 낫다.
"""

from __future__ import annotations

import array
import contextlib
import math
import os
from collections.abc import Callable
from typing import Any

# 테스트·운영 주입 시임 — 실제 무거운 모델 없이 3-스트림 융합 로직을 검증한다.
# None이 아니면 embedder()가 이 콜러블을 그대로 반환한다 (모드·로드 우회).
_OVERRIDE: Callable[[str], list[float]] | None = None
_CACHE: dict[str, Any] = {"loaded": False, "fn": None, "dim": 0, "model": ""}

# 기본 모델 — 26-07-27 벤치가 고르고 26-07-29 오딘이 재확인했다. 한국어 판별력이 유일하게
# 성립한 모델이라 바꿀 때는 한국어부터 확인할 것 (독스트링의 코사인 차 표 참조).
# 내려받기가 길다는 점은 고려했으나, 어차피 설치 시점에 한 번 치르는 값이라 기준이 아니다
# (install.sh가 `asgard memory semantic warmup`으로 미리 받는다).
# 바꾸는 길은 두 개다 — [memory].semantic_model 또는 ASGARD_MEMORY_SEMANTIC_MODEL.
DEFAULT_MODEL = "minishlab/potion-multilingual-128M"
# 구 이름 — 한때 "정적 폴백 전용 모델"이었다. 지금은 그게 곧 기본값이라 같은 값을 가리킨다.
DEFAULT_STATIC_MODEL = DEFAULT_MODEL
DEFAULT_MODE = "local"  # 26-07-27 오딘 결정 — 회수 품질을 위해 지연을 감수한다 (모듈 독스트링 근거)
_ENV = "ASGARD_MEMORY_SEMANTIC"


def _settings() -> dict:
    """[memory] 설정 — memory 모듈의 단일 로더 재사용 (순환 import 회피 위해 지연)."""
    try:
        from . import memory

        return memory._memory_settings()
    except Exception:
        return {}


def mode() -> str:
    """시맨틱 모드 — env 우선, 설정 폴백, 기본 'local'. 'off' 이외는 로컬 임베딩 시도.

    기본이 'local' 이어도 임베더가 없으면 _load_local이 None을 돌려 2경로로 폴백한다 —
    켜져 있다는 것과 도는 것은 다르고, 그 차이는 doctor가 말한다."""
    env = (os.environ.get(_ENV) or "").strip().lower()
    if env:
        return env
    try:
        return str(_settings().get("semantic", DEFAULT_MODE)).strip().lower() or DEFAULT_MODE
    except Exception:
        return DEFAULT_MODE


def _model_name() -> str:
    env = (os.environ.get(_ENV + "_MODEL") or "").strip()
    if env:
        return env
    try:
        return str(_settings().get("semantic_model") or DEFAULT_MODEL)
    except Exception:
        return DEFAULT_MODEL


def set_embedder(fn: Callable[[str], list[float]] | None) -> None:
    """주입 시임 (테스트·커스텀 임베더) — 캐시를 무효화한다."""
    global _OVERRIDE
    _OVERRIDE = fn
    reset()


def reset() -> None:
    """로드 캐시 초기화 — 설정/모드 변경 후 재평가용.

    첫 내려받기 실패 래치도 같이 지운다 (`_download_latched`). 뜻이 "처음부터 다시 판정하라"
    인 손잡이가 판정을 막는 상태 하나를 남겨 두면, 사람은 왜 안 켜지는지 알 길이 없다.
    `warmup()`이 이 함수로 시작하는 것이 곧 래치의 복구 경로다."""
    _CACHE.update({"loaded": False, "fn": None, "dim": 0, "model": ""})
    _clear_download_latch()


@contextlib.contextmanager
def _quiet_hub(quiet: bool = True, offline: bool | None = None):
    """모델 허브의 진행 막대를 잠재운다.

    기본으로 켜진 뒤로는 `memory query` 한 번마다 남의 라이브러리 진행 막대가 stderr로
    새어 나온다 — 사용자 표면은 우리 것이어야 한다. 막대를 보여 주는 자리는 **처음 받을 때**
    하나뿐이다 (거기서는 1GB를 받는 중이라는 사실이 곧 필요한 정보다)."""
    import logging

    keys = ["HF_HUB_DISABLE_PROGRESS_BARS", "HF_HUB_DISABLE_TELEMETRY"]
    # 조용함과 오프라인은 다른 축이다. 평시 로드는 둘 다 원하지만(이미 받아 둔 모델은 갱신
    # 확인 왕복이 낭비다), 워밍업은 조용하되 네트워크는 열어야 한다 — 깨진 캐시를 고치는
    # 경로가 바로 거기이기 때문이다. 묶어 두면 복구가 불가능해진다.
    if offline is None:
        offline = quiet and model_cached()
    if offline:
        keys.append("HF_HUB_OFFLINE")
    previous = {key: os.environ.get(key) for key in keys}
    logger = logging.getLogger("huggingface_hub")
    level = logger.level
    if quiet:
        for key in keys:
            os.environ[key] = "1"
        logger.setLevel(logging.ERROR)
    elif offline:  # 조용하지 않아도 오프라인 지정은 존중한다
        os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        yield
    finally:
        logger.setLevel(level)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_local(model_name: str) -> tuple[Callable[[str], list[float]], int, str] | None:
    """로컬 임베더 로드 — **model2vec(정적) 우선**, sentence-transformers 폴백.
    미설치면 None (fail-open). 반환 = (embed_fn, dim, 실제 모델명).

    순서가 반대였다. sentence-transformers를 먼저 시도하면, 그게 설치된 환경에서는 기본
    모델 이름이 ST 쪽으로 해석돼 **한국어 검증을 받은 적 없는 모델이 조용히 이겼다** —
    벤치가 고른 값이 실제로 쓰이지 않으면 그건 기본값이 아니다. 고른 모델을 먼저 연다.

    ST 경로는 남겨 둔다: 사용자가 semantic_model로 ST 계열 이름을 지정하면 model2vec이
    그 이름을 못 읽고, 그때 여기로 넘어온다. 즉 두 계열을 다 쓸 수 있다.

    어떤 import·로드 실패도 삼켜 None — 검색은 계속돼야 한다."""
    with contextlib.suppress(Exception):  # torch 무의존 정적 임베더 (기본 경로)
        from model2vec import StaticModel

        model = StaticModel.from_pretrained(model_name)

        def _embed_static(text: str) -> list[float]:
            vec = model.encode(text)
            return _normalize([float(x) for x in vec])

        probe = _embed_static("dimension probe")
        return _embed_static, len(probe), model_name
    with contextlib.suppress(Exception):  # 사용자가 ST 계열 모델을 지정한 경우
        from sentence_transformers import SentenceTransformer  # type: ignore

        st_model = SentenceTransformer(model_name)
        dim = int(st_model.get_sentence_embedding_dimension())

        def _embed_st(text: str) -> list[float]:
            vec = st_model.encode([text], normalize_embeddings=True)[0]
            return [float(x) for x in vec]

        return _embed_st, dim, model_name
    return None


_DEADLINE_ENV = "ASGARD_MEMORY_NO_DOWNLOAD"


def deadline_bound() -> bool:
    """이 프로세스가 남의 시간 상한 안에서 도는가 — 훅이 자식에게 켜 준다.

    켜져 있으면 임베더를 **차게 세우지 않는다**. 내려받기뿐 아니라 로드도 그렇다: 26-08-04
    실측에서 `asgard memory recall` 1,370ms 중 1,050ms 가 이미 캐시에 있는 정적 모델을
    프로세스마다 다시 올리는 값이었다 (`tokenizers.Tokenizer.from_file` 490ms +
    StaticModel.__init__ 423ms + get_vocab 134ms — 어휘 50만 항목 재구축). 훅은 프롬프트마다
    새 프로세스라 그 값을 매번 문다. 같은 저장소에서 어휘 2경로만 도는 회수는 140~222ms 다.

    질의 자체는 싸다 (벤치 hybrid-search: 시맨틱 켠 query() p50 9.47ms). 그러니 이 판정이
    아끼는 것은 검색이 아니라 프로세스 경계다. 이미 선 임베더는 이 판정에 안 걸린다 —
    `embedder()` 가 `_CACHE["loaded"]` 에서 먼저 돌려주기 때문에, 오래 사는 네이티브 루프와
    사람이 기다리는 `asgard memory query` 는 한 번 올린 뒤 상한과 무관하게 3경로를 쓴다.
    값을 무는 것은 프롬프트마다 새로 뜨는 훅 프로세스뿐이다.

    시맨틱만 빠지고 어휘·그래프 스트림은 그대로 도므로 회수는 나빠질 뿐 멈추지 않는다."""
    return bool((os.environ.get(_DEADLINE_ENV) or "").strip())


def detached_env(env: dict[str, str]) -> dict[str, str]:
    """분리 스폰용 환경 — 부모의 시간 상한 표식을 뗀다 (같은 dict 를 돌려준다).

    상한은 **부모의 시계**를 뜻하는데 `start_new_session=True` 로 떼어낸 자식은 그 시계 밖이다.
    물려주면 그 자식이 위키를 쓰면서 벡터를 안 만들고 (`memory/index.py` 의 `_vec_upsert` 가
    `active()` 로 잠근다), 페이지는 늘고 벡터는 안 늘어 vec_coverage 가 조용히 썩는다."""
    env.pop(_DEADLINE_ENV, None)
    return env


# ── 첫 내려받기 실패 래치 ─────────────────────────────────────────────────────
#
# 위 보호는 켜 주는 자리가 외부 클라이언트 훅 하나뿐이다. 네이티브 루프와 모든 `asgard
# memory *` 호출은 그 밖이라, 모델이 캐시에 없고 네트워크가 막힌 기계에서는 **프로세스마다**
# 같은 허브 왕복을 다시 시도하고 그 시간만큼 조용히 멈춘다 (`_CACHE`는 프로세스 수명이라
# 다음 호출이 처음부터 다시 한다). 크래시는 안 나고 어휘 경로로 fail-open 하므로 저하 자체는
# 우아하다 — 문제는 그 저하가 **매번 값을 낸다**는 것이다. 그래서 실패 하나를 짧게 기억한다.
#
# 무엇을 기억하는가 — "**첫 내려받기**가 실패했다"뿐이다. 판정은 예외 종류가 아니라 로드
# 직전의 캐시 유무로 한다: `_load_local`이 모든 예외를 삼켜 None을 주므로 여기서 원인을 물을
# 수는 없지만, 캐시에 없던 모델을 못 얻었다는 것은 그 로드가 내려받기를 해야 했고 못 했다는
# 뜻이다. 캐시가 있는데 실패한 것은 깨진 파일이거나 라이브러리 문제라 다음 실행에서 다시 시도할
# 값어치가 있고, 그래서 안 적는다.
#
# 자리는 기계 전역이다 (`~/.asgard`, trust store와 같은 자리). 실패의 원인이 모델 캐시 부재와
# 네트워크라 프로젝트 속성이 아니다 — 저장소마다 따로 두면 같은 실패를 저장소 수만큼 겪는다.
#
# 왜 10분인가. 아끼는 것은 프로세스당 왕복 한 번이고, 그 왕복을 무는 것은 CLI 한 세션이 짧은
# 프로세스를 연달아 띄우는 몇 분이다. 반대로 래치가 길면 사람이 네트워크를 고친 뒤에도 그
# 시간만큼 시맨틱이 꺼진 채로 돈다. 10분은 한 세션의 연쇄는 덮고 사람의 수리는 안 덮는 폭이다.
# 그리고 복구는 어느 쪽이든 즉시다 — `reset()`(그러므로 `warmup()`)이 래치를 지운다.
_LATCH_TTL = 600.0
_LATCH_NAME = "memory-embed-latch"


def _latch_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard", _LATCH_NAME)


def _download_latched() -> bool:
    """최근에 이 모델의 첫 내려받기가 실패했는가.

    읽기 한 번으로 끝나고, 못 읽으면 False다 — 래치 파일 하나가 회수를 막으면 그게 더 나쁘다.
    모델 이름을 같이 적어 두는 이유: 사람이 `semantic_model`을 바꾼 것은 새로운 시도이고,
    옛 모델의 실패가 그것을 막으면 안 된다."""
    try:
        import time

        with open(_latch_path(), encoding="utf-8") as handle:
            stamp, _, model = handle.read().strip().partition(" ")
        return model == _model_name() and time.time() - float(stamp) < _LATCH_TTL
    except Exception:
        return False


def _latch_download_failure() -> None:
    """첫 내려받기 실패를 적는다 — 실패해도 조용하다 (래치는 최적화이지 계약이 아니다)."""
    with contextlib.suppress(Exception):
        import time

        path = _latch_path()
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"{time.time():.0f} {_model_name()}\n")
        os.chmod(path, 0o600)


def _clear_download_latch() -> None:
    with contextlib.suppress(OSError):
        os.remove(_latch_path())


def embedder() -> Callable[[str], list[float]] | None:
    """활성 임베더 콜러블 또는 None. 결과를 캐시한다 (무거운 모델 재로드 방지)."""
    if _OVERRIDE is not None:
        return _OVERRIDE
    if mode() == "off":
        return None
    if _CACHE["loaded"]:
        return _CACHE["fn"]
    if deadline_bound():
        # 시간 상한 안에서는 콜드 로드를 안 연다 — 캐시에 없으면 35초짜리 첫 내려받기고,
        # 캐시에 있어도 1,050ms 짜리 재구축이다 (deadline_bound 의 실측). 위 `_CACHE["loaded"]`
        # 갈래가 먼저라 이미 선 임베더는 여기까지 안 온다.
        _CACHE["loaded"], _CACHE["fn"], _CACHE["dim"] = True, None, 0
        return None
    cached = model_cached()
    if not cached and _download_latched():
        # 최근에 같은 첫 내려받기가 실패했다 — 프로세스마다 같은 값을 다시 치르지 않는다.
        _CACHE["loaded"], _CACHE["fn"], _CACHE["dim"] = True, None, 0
        return None
    _CACHE["loaded"] = True
    # 처음 한 번은 모델을 받느라 수십 초가 걸린다. 그 침묵이 "멈춘 것"으로 보이므로 한 줄 알린다 —
    # 프로세스당 한 번, stderr 로만 (산출을 파이프로 받는 소비자를 오염시키지 않는다).
    warming = bool(_CACHE.get("warmup"))
    if not warming and not cached:
        with contextlib.suppress(Exception):
            import sys

            print(
                "⠶ 메모리 시맨틱 검색을 준비하고 있어요 — 임베딩 모델을 처음 받는 중이에요 (한 번만)", file=sys.stderr
            )
    with _quiet_hub(quiet=not warming or cached, offline=False if warming else None):
        loaded = _load_local(_model_name())
    if loaded is None:
        if not cached:
            _latch_download_failure()  # 캐시에 없던 모델을 못 얻었다 = 첫 내려받기 실패
        _CACHE["fn"], _CACHE["dim"] = None, 0
        return None
    _clear_download_latch()  # 성공은 래치를 즉시 무른다
    _CACHE["fn"], _CACHE["dim"], _CACHE["model"] = loaded
    return _CACHE["fn"]


def active() -> bool:
    """임베더가 이번 세션에서 서는가.

    **주의 — 이것은 "회수에 기여하는가"가 아니다.** 임베더가 서 있어도 파생 벡터가 정본을
    안 덮으면 시맨틱 스트림은 빈 리스트를 낸다 (실측 26-07-29: 페이지 2장·vec 0행에서
    active()는 True). 사람에게 보여 줄 상태는 이 값 하나가 아니라
    `memory.vec_coverage()`와 **같이** 읽어야 한다."""
    return embedder() is not None


def loaded_model() -> str:
    """이미 로드된 임베더의 모델명 — **로드를 유발하지 않는다** (없으면 빈 문자열).

    파생 인덱스에 "어떤 임베더로 만든 벡터인가"를 적기 위한 접근자다. `status()`는
    embedder()를 부르므로 이 자리에 쓸 수 없다 — 색인 경로가 상태 조회 때문에 35초짜리
    첫 내려받기를 여는 일은 없어야 한다.

    주입 임베더(테스트·커스텀)는 `injected`로 보고한다. 빈 문자열로 두면 주입 임베더로 만든
    벡터와 진짜 모델로 만든 벡터가 파생 인덱스에서 구분되지 않아, 둘을 오가면 낡은 공간의
    벡터가 조용히 살아남는다."""
    if _OVERRIDE is not None:
        return "injected"
    return str(_CACHE.get("model") or "")


def status() -> dict:
    """상태 스냅샷 — 정직한 노출용. 로드를 강제하지 않으려면 active()를 먼저 부른 뒤 읽는다."""
    fn = embedder()
    if _OVERRIDE is not None:
        return {"mode": mode(), "active": True, "model": "injected", "dim": len(_OVERRIDE("x"))}
    return {"mode": mode(), "active": fn is not None, "model": _CACHE.get("model", ""), "dim": _CACHE.get("dim", 0)}


def model_cached() -> bool:
    """설정된 모델이 이미 디스크에 있는가 — 첫 실행의 긴 내려받기를 예고하기 위한 판정.

    HuggingFace 캐시 규약(models--<org>--<name>)만 본다. 라이브러리를 부르지 않으므로
    이 함수는 모델을 로드하지 않는다 (판정 때문에 35초를 쓰면 판정의 의미가 없다).

    예전에는 기본 이름(ST)과 실제 로드 모델(potion)이 달라 여기서 이름을 갈아 끼웠다.
    이제 기본값이 곧 로드되는 모델이라 그 매핑이 없다 — 묻는 이름과 보는 캐시가 같다."""
    target = _model_name()
    if "/" not in target:
        return False
    slug = "models--" + target.replace("/", "--")
    roots = [
        os.path.join(
            os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "hub"
        ),
        os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"),
    ]
    return any(os.path.isdir(os.path.join(root, slug)) for root in roots)


def warmup() -> dict:
    """모델을 미리 내려받아 로드한다 — 첫 검색이 조용히 35초 멈추는 일을 없앤다.

    평시 경로와 달리 여기서는 네트워크를 막지 않는다 — 워밍업은 **복구 경로**이기도 하다.
    캐시가 깨진 상태에서 오프라인으로 열면 고칠 방법이 없어지고, 그때 사용자가 부르는 명령이
    바로 이것이다. 진행 막대도 그대로 보여 준다 (1GB를 받는 중이라는 사실이 곧 필요한 정보다).

    반환 = {"active", "model", "dim", "downloaded", "seconds"}. 실패해도 예외를 올리지 않는다:
    워밍업 실패는 검색을 막지 않고, 그저 시맨틱 없이 도는 것뿐이다 (fail-open 계약)."""
    import time

    had_cache = model_cached()
    start = time.perf_counter()
    reset()
    # 캐시가 있으면 조용히, 없으면 진행을 보여 준다. 네트워크는 어느 쪽이든 연다 (복구 경로).
    _CACHE["warmup"] = True
    fn = embedder()
    _CACHE.pop("warmup", None)
    elapsed = time.perf_counter() - start
    if fn is not None:
        with contextlib.suppress(Exception):
            fn("warmup probe")
    return {
        "active": fn is not None,
        "model": _CACHE.get("model", ""),
        "dim": _CACHE.get("dim", 0),
        "downloaded": not had_cache,
        "seconds": round(elapsed, 1),
    }


def embed(text: str) -> list[float] | None:
    """텍스트 → 정규화 벡터. 임베더 없거나 실패 시 None (fail-open)."""
    fn = embedder()
    if fn is None:
        return None
    try:
        vec = fn(text or "")
        return _normalize([float(x) for x in vec]) if vec else None
    except Exception:
        return None


# ── 벡터 수학 (stdlib only) ──────────────────────────────────────────────────


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def pack(vec: list[float]) -> bytes:
    """float32 직렬화 — state.db BLOB 저장용 (파생물, reindex로 복원 가능)."""
    return array.array("f", vec).tobytes()


def unpack(data: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(data)
    return a.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    """코사인 유사도 — 정규화 벡터 전제이므로 내적이지만, 안전하게 분모를 둔다.
    길이 불일치(모델 교체)는 0 반환 — 차원 오염이 조용히 매칭되지 않게."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return max(-1.0, min(1.0, dot))
