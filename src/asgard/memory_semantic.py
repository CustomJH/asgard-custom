"""개인 메모리 시맨틱 스트림 (옵트인) — Tier0 검색을 lexical → hybrid 로.

배경 (26-07-18): agentmemory 실사 결론 — 1차 메모리로 그대로 채택은 부적합(iii 상주
데몬·KV 필터 격리·기본 벡터 OFF)하나, 검색 파이프라인(3-스트림 RRF + 로컬 임베딩)은
이식 가치가 있다. 여기가 그 이식이다 — 저장·오케스트레이션은 Asgard 정본 계약을 지키고
알고리즘만 취한다.

계약 (memory.py 정본 원칙 상속):
  · **정본 불변** — 벡터는 state.db 의 파생물이다. 지워도(또는 손상돼도) reindex 로 복원되고,
    파일 md 가 여전히 지식의 정본이다. 벡터는 pages/ 를 절대 대체하지 않는다.
  · **fail-open** — 임베더 미설치 또는 설정 off 면 embedder()=None → query() 가 기존 2경로
    (FTS5 BM25 + 정본 스캔) 로 완전히 동일하게 동작한다. 어떤 예외도 검색을 막지 않는다.
  · **의존성 제로 기본** — 벡터 수학(pack/cosine)은 stdlib(array·math)만 쓴다. 임베딩 모델
    라이브러리만 옵트인 로드다. 설치 안 하면 아무 것도 안 깔린 채로 2경로가 돈다.
  · **정직한 상태** — agentmemory 는 "로컬 임베딩 기본"이라 광고하고 실제론 OFF 였다. 우리는
    active() 로 활성/비활성을 대시보드·doctor 에 그대로 노출한다 (숨기지 않는다).

옵트인 방법:  설정 [memory].semantic = "local"  (기본 "off")
             모델 [memory].semantic_model = "sentence-transformers/all-MiniLM-L6-v2" (선택)
             env  ASGARD_MEMORY_SEMANTIC 로 세션 오버라이드 (off|local).
"""

from __future__ import annotations

import array
import contextlib
import math
import os
from collections.abc import Callable
from typing import Any

# 테스트·운영 주입 시임 — 실제 무거운 모델 없이 3-스트림 융합 로직을 검증한다.
# None 이 아니면 embedder() 가 이 콜러블을 그대로 반환한다 (모드·로드 우회).
_OVERRIDE: Callable[[str], list[float]] | None = None
_CACHE: dict[str, Any] = {"loaded": False, "fn": None, "dim": 0, "model": ""}

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_STATIC_MODEL = "minishlab/potion-multilingual-128M"
_ENV = "ASGARD_MEMORY_SEMANTIC"


def _settings() -> dict:
    """[memory] 설정 — memory 모듈의 단일 로더 재사용 (순환 import 회피 위해 지연)."""
    try:
        from . import memory

        return memory._memory_settings()
    except Exception:
        return {}


def mode() -> str:
    """시맨틱 모드 — env 우선, 설정 폴백, 기본 'off'. 'off' 이외는 로컬 임베딩 시도."""
    env = (os.environ.get(_ENV) or "").strip().lower()
    if env:
        return env
    try:
        return str(_settings().get("semantic", "off")).strip().lower() or "off"
    except Exception:
        return "off"


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
    """로드 캐시 초기화 — 설정/모드 변경 후 재평가용."""
    _CACHE.update({"loaded": False, "fn": None, "dim": 0, "model": ""})


def _load_local(model_name: str) -> tuple[Callable[[str], list[float]], int, str] | None:
    """로컬 임베더 로드 — sentence-transformers 우선, model2vec 폴백. 미설치면 None (fail-open).

    반환 = (embed_fn, dim, 실제 모델명). 어떤 import·로드 실패도 삼켜 None — 검색은 계속돼야 한다.
    """
    with contextlib.suppress(Exception):
        from sentence_transformers import SentenceTransformer  # type: ignore

        model = SentenceTransformer(model_name)
        dim = int(model.get_sentence_embedding_dimension())

        def _embed(text: str) -> list[float]:
            vec = model.encode([text], normalize_embeddings=True)[0]
            return [float(x) for x in vec]

        return _embed, dim, model_name
    with contextlib.suppress(Exception):  # 경량 폴백 — torch 없는 정적 임베딩
        from model2vec import StaticModel

        static_model_name = DEFAULT_STATIC_MODEL if model_name == DEFAULT_MODEL else model_name
        model = StaticModel.from_pretrained(static_model_name)

        def _embed2(text: str) -> list[float]:
            vec = model.encode(text)
            return _normalize([float(x) for x in vec])

        probe = _embed2("dimension probe")
        return _embed2, len(probe), static_model_name
    return None


def embedder() -> Callable[[str], list[float]] | None:
    """활성 임베더 콜러블 또는 None. 결과를 캐시한다 (무거운 모델 재로드 방지)."""
    if _OVERRIDE is not None:
        return _OVERRIDE
    if mode() == "off":
        return None
    if _CACHE["loaded"]:
        return _CACHE["fn"]
    _CACHE["loaded"] = True
    loaded = _load_local(_model_name())
    if loaded is None:
        _CACHE["fn"], _CACHE["dim"] = None, 0
        return None
    _CACHE["fn"], _CACHE["dim"], _CACHE["model"] = loaded
    return _CACHE["fn"]


def active() -> bool:
    """시맨틱 스트림이 이번 세션에서 실제로 동작하는가 (대시보드·doctor 표시용)."""
    return embedder() is not None


def status() -> dict:
    """상태 스냅샷 — 정직한 노출용. 로드를 강제하지 않으려면 active() 를 먼저 부른 뒤 읽는다."""
    fn = embedder()
    if _OVERRIDE is not None:
        return {"mode": mode(), "active": True, "model": "injected", "dim": len(_OVERRIDE("x"))}
    return {"mode": mode(), "active": fn is not None, "model": _CACHE.get("model", ""), "dim": _CACHE.get("dim", 0)}


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
    """float32 직렬화 — state.db BLOB 저장용 (파생물, reindex 로 복원 가능)."""
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
