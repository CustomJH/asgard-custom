"""Hindsight 프로젝트 학습층 — 승인 record만 observation과 mental model로 올린다."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from .ingest import BANK_DEFAULTS, STRATEGIES

# 종합층 로컬 사본. 파생물이라 정본(records/)과 달리 저장소에 커밋되지 않는다
# (.asgard/.gitignore의 `memory/*`가 이미 덮는다).
SYNTHESIS_FILENAME = os.path.join(".asgard", "memory", "synthesis.json")
SYNTHESIS_MAX_CHARS = 8000  # 모델 하나가 뱅크 전체를 실어 나르는 것을 막는다

MODEL_SPECS: tuple[dict, ...] = (
    {
        "id": "asgard-architecture",
        "name": "Project Architecture and Invariants",
        "source_query": (
            "이 프로젝트의 현재 아키텍처, 핵심 구성요소의 책임, 소유권 경계, 반드시 지켜야 할 "
            "불변조건은 무엇인가? 활성 상태의 검증된 프로젝트 기록만 사용하고 폐기된 결정은 구분하라."
        ),
        "tags": ["record"],
        "max_tokens": 2048,
        "trigger": {
            "mode": "delta",
            "refresh_after_consolidation": True,
            "fact_types": ["world", "experience", "observation"],
            "tags_match": "all_strict",
            "exclude_mental_models": True,
            "include_chunks": True,
            "recall_max_tokens": 8192,
        },
    },
    {
        "id": "asgard-decisions",
        "name": "Project Decisions, Risks, and Corrections",
        "source_query": (
            "이 프로젝트에서 채택하거나 기각한 주요 결정, 그 근거와 트레이드오프, 아직 열린 위험과 "
            "후속 조치는 무엇인가? 사건, 교정, 실험의 최신 증거를 우선하라."
        ),
        "tags": ["record"],
        "max_tokens": 2048,
        "trigger": {
            "mode": "delta",
            "refresh_after_consolidation": True,
            "fact_types": ["world", "experience", "observation"],
            "tags_match": "all_strict",
            "exclude_mental_models": True,
            "include_chunks": True,
            "recall_max_tokens": 8192,
        },
    },
    {
        "id": "asgard-delivery",
        "name": "Project Delivery and Operations",
        "source_query": (
            "이 프로젝트의 구현, 검증, 릴리스, 운영 절차와 실패 시 복구 규칙은 무엇인가? "
            "현재 적용되는 계약과 runbook만 정리하라."
        ),
        "tags": ["record"],
        "max_tokens": 2048,
        "trigger": {
            "mode": "delta",
            "refresh_after_consolidation": True,
            "fact_types": ["world", "experience", "observation"],
            "tags_match": "all_strict",
            "exclude_mental_models": True,
            "include_chunks": True,
            "recall_max_tokens": 8192,
        },
    },
)


def model_ready(model: Mapping[str, object]) -> bool:
    content = str(model.get("content") or "").strip()
    return content.casefold().rstrip(".") not in {"", "generating content", "i don't have information"}


def _methods(backend) -> tuple:
    names = (
        "bank_config",
        "update_bank_config",
        "consolidate",
        "list_mental_models",
        "create_mental_model",
        "update_mental_model",
        "refresh_mental_model",
    )
    methods = tuple(getattr(backend, name, None) for name in names)
    if not all(callable(method) for method in methods):
        raise ValueError("selected project-memory backend does not expose the Hindsight learning surface")
    return methods


def _desired_config(current: Mapping[str, object]) -> dict:
    strategies = current.get("retain_strategies")
    merged = {**(dict(strategies) if isinstance(strategies, Mapping) else {}), **STRATEGIES}
    return {"retain_strategies": merged, **BANK_DEFAULTS}


def _model_drift(current: Mapping[str, object], desired: Mapping[str, object]) -> bool:
    for key in ("name", "source_query", "tags", "max_tokens"):
        if current.get(key) != desired.get(key):
            return True
    trigger = current.get("trigger")
    expected = desired.get("trigger")
    if not isinstance(trigger, Mapping) or not isinstance(expected, Mapping):
        return trigger != expected
    return any(trigger.get(key) != value for key, value in expected.items())


def plan(backend) -> dict:
    read_config, _write_config, _consolidate, list_models, *_ = _methods(backend)
    current = read_config()
    desired = _desired_config(current)
    models = list_models()
    by_id = {str(model.get("id") or ""): model for model in models}
    missing = [spec["id"] for spec in MODEL_SPECS if spec["id"] not in by_id]
    drifted = [spec["id"] for spec in MODEL_SPECS if spec["id"] in by_id and _model_drift(by_id[spec["id"]], spec)]
    configured = all(current.get(key) == value for key, value in desired.items())
    return {
        "configured": configured,
        "desired_config": desired,
        "missing_models": missing,
        "drifted_models": drifted,
        "models": [
            {
                "id": str(model.get("id") or ""),
                "name": str(model.get("name") or ""),
                "ready": model_ready(model),
                "stale": bool(model.get("is_stale")),
                "last_refreshed_at": str(model.get("last_refreshed_at") or ""),
            }
            for model in models
            if str(model.get("id") or "").startswith("asgard-")
        ],
    }


def apply(backend) -> dict:
    read_config, write_config, consolidate, list_models, create_model, update_model, refresh_model = _methods(backend)
    current = read_config()
    desired_config = _desired_config(current)
    config_changed = any(current.get(key) != value for key, value in desired_config.items())
    if config_changed:
        write_config(desired_config)

    by_id = {str(model.get("id") or ""): model for model in list_models()}
    model_operations: list[dict] = []
    for spec in MODEL_SPECS:
        model_id = str(spec["id"])
        existing = by_id.get(model_id)
        if existing is None:
            result = create_model(spec)
            model_operations.append({"id": model_id, "action": "created", "operation_id": str(result["operation_id"])})
        elif _model_drift(existing, spec):
            update_model(model_id, {key: value for key, value in spec.items() if key != "id"})
            result = refresh_model(model_id)
            model_operations.append({"id": model_id, "action": "updated", "operation_id": str(result["operation_id"])})
        elif not model_ready(existing) or bool(existing.get("is_stale")):
            result = refresh_model(model_id)
            model_operations.append(
                {"id": model_id, "action": "refreshed", "operation_id": str(result["operation_id"])}
            )

    consolidation = consolidate([["record"]])
    return {
        "config_changed": config_changed,
        "models": model_operations,
        "consolidation_operation_id": str(consolidation["operation_id"]),
        "consolidation_deduplicated": bool(consolidation.get("deduplicated")),
    }


def snapshot(backend, root: str, *, project_uid: str = "", binding_id: str = "") -> int:
    """준비된 mental model을 로컬 사본으로 내린다 — 반환 = 저장한 모델 수.

    왜 파일로 내리는가: 종합층은 이미 만들고 있었는데 아무도 안 읽었다 (`doctor`가 개수만
    셌다). 회수 때마다 원격으로 목록을 다시 부르면 턴 시작에 두 번째 왕복이 붙고, 서버가
    죽으면 종합층이 통째로 사라진다. 큰 문서 레인(documents)과 같은 결로 간다 — 원본은
    backend에 있고, 소비는 로컬에서 한다.

    소유권 필드를 같이 적는다: 다른 binding으로 옮겨 간 저장소에서 남은 사본이 되살아나
    남의 프로젝트 종합을 주입하는 경로를 닫는다."""
    models = [
        {
            "id": str(model.get("id") or ""),
            "name": str(model.get("name") or ""),
            "content": str(model.get("content") or "").strip()[:SYNTHESIS_MAX_CHARS],
            "refreshed_at": str(model.get("last_refreshed_at") or ""),
        }
        for model in backend.list_mental_models()
        if str(model.get("id") or "").startswith("asgard-") and model_ready(model) and not model.get("is_stale")
    ]
    path = os.path.join(root, SYNTHESIS_FILENAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "schema": "asgard-project-synthesis-v1",
        "project_uid": project_uid,
        "binding_id": binding_id,
        "models": models,
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return len(models)


def load_synthesis(root: str, *, project_uid: str = "", binding_id: str = "") -> list[dict]:
    """로컬 종합층 사본 — 소유권이 어긋나거나 없으면 빈 리스트 (fail-open).

    빈 소유권은 **불일치로 친다**. 안 그러면 `"" != ""`가 거짓이라 대조가 저절로 통과한다:
    소유권 필드를 비운 사본을 심고 설정에서 binding을 빼면 게이트가 있는 채로 무력해진다.
    소유권을 못 대는 사본은 주인을 모르는 사본이고, 주인을 모르면 안 싣는다."""
    try:
        with open(os.path.join(root, SYNTHESIS_FILENAME), encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError, ValueError:
        return []
    if not isinstance(payload, dict) or payload.get("schema") != "asgard-project-synthesis-v1":
        return []
    if not project_uid or not binding_id:
        return []
    if payload.get("project_uid") != project_uid or payload.get("binding_id") != binding_id:
        return []
    models = payload.get("models")
    if not isinstance(models, list):
        return []
    return [model for model in models if isinstance(model, dict) and str(model.get("content") or "").strip()]


__all__ = [
    "BANK_DEFAULTS",
    "MODEL_SPECS",
    "SYNTHESIS_FILENAME",
    "apply",
    "load_synthesis",
    "model_ready",
    "plan",
    "snapshot",
]
