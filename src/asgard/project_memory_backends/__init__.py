"""선택형 프로젝트 메모리 backend 계약과 registry."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.metadata
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol, runtime_checkable

MAX_HTTP_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_BACKEND_TIMEOUT = 1800  # 초 — 서버측 LLM 타임아웃(600s)과 청킹 여유를 덮는다
_BASE_RETAIN_FIELDS = frozenset({"content", "context", "document_id", "update_mode", "tags", "metadata"})
BACKEND_API_VERSION = 2
BINDING_DOCUMENT_ID = "asgard:project-binding:v1"
BINDING_SCHEMA = 1


@dataclasses.dataclass(frozen=True)
class BackendSettings:
    engine: str
    project_id: str
    endpoint: str = ""
    timeout: int = 15
    project_uid: str = ""
    binding_id: str = ""
    options: Mapping[str, object] = dataclasses.field(default_factory=dict)
    raw: Mapping[str, object] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class ProjectMemoryHit:
    text: str
    metadata: Mapping[str, object] = dataclasses.field(default_factory=dict)
    document_id: str = ""
    score: float | None = None


@dataclasses.dataclass(frozen=True)
class ProjectMemoryRecord:
    """Backend-neutral stable project-memory record."""

    record_id: str
    text: str
    metadata: Mapping[str, object] = dataclasses.field(default_factory=dict)
    tags: tuple[str, ...] = ()
    context: str = ""
    # 이 사실에 발생 시각이 없는가 — 코드·규격은 시점이 아니라 리비전으로 산다.
    timeless: bool = False
    # 확정 엔티티 (이름, 타입) — 서버의 자동 추출과 합쳐진다. chunks 모드에서는 유일 출처다.
    entities: tuple[tuple[str, str], ...] = ()
    # 선택 backend가 지원할 때만 전달되는 retain 힌트. Hindsight는 item별 strategy와
    # observation scope를 받아 같은 프로젝트 안에서도 정적 문서와 관계형 기록을 다르게 다룬다.
    strategy: str = ""
    observation_scopes: str | tuple[tuple[str, ...], ...] | None = None


@dataclasses.dataclass(frozen=True)
class BackendWriteResult:
    success: bool
    accepted_ids: tuple[str, ...] = ()
    rejected: Mapping[str, str] = dataclasses.field(default_factory=dict)
    error: str = ""
    details: Mapping[str, object] = dataclasses.field(default_factory=dict)

    @property
    def items_count(self) -> int:
        return len(self.accepted_ids)


# 서버 응답이 **수용을 이름으로** 말하는 자리들. 실서버 0.8.3은 `{"success": true, "items_count": N}`
# 만 돌려주고 항목별 id를 대지 않는다 — 지금 이 키들은 하나도 오지 않는다.
#
# 그래도 두는 이유와, 그 이상 넓히지 않는 이유가 같다. 여기 적힌 셋은 "받아들인 것"말고 다른
# 뜻으로 읽힐 수 없다. `items`·`results` 같은 이름은 **요청을 되비친 것**일 수 있고, 그것을
# 수용 목록으로 읽으면 보낸 목록으로 만들던 옛 코드와 정확히 같아진다 — 고치려던 자리로 돌아간다.
_ACCEPTED_ID_KEYS = ("accepted_ids", "accepted", "document_ids")


def _named_ids(output: Mapping[str, object]) -> tuple[str, ...] | None:
    """응답이 항목별로 이름 댄 id — 없으면 None (빈 목록과 다르다)."""
    for key in _ACCEPTED_ID_KEYS:
        rows = output.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        found: list[str] = []
        for row in rows:
            if isinstance(row, str) and row:
                found.append(row)
            elif isinstance(row, Mapping):
                value = row.get("document_id") or row.get("id") or row.get("record_id")
                if isinstance(value, str) and value:
                    found.append(value)
        if found:
            return tuple(found)
    return None


def _accepted_ids(output: Mapping[str, object], records: Sequence[ProjectMemoryRecord]) -> tuple[str, ...]:
    """서버가 실제로 받아들인 id — **우리가 보낸 목록이 아니라 응답**에서 만든다.

    보낸 목록으로 만들면 상위의 정합성 검사(memory_bridge.client)가 자기 입력을 자기와 대조하는
    셈이라 구조적으로 절대 발화하지 못한다. 그러면 서버가 3건 중 2건만 삼킨 응답도 성공으로
    지나가고, 빠진 하나는 아무도 다시 보내지 않는다 — 조용히 사라지는 기록이 가장 나쁘다.

    증거의 세기 순서로 읽는다:
      ① 항목별 id를 이름 댄 응답  → 그대로 쓴다 (가장 강하다)
      ② 셈만 있는 응답            → 셈이 보낸 수와 같을 때만 전부 수용으로 읽는다. 모자라면
                                    **어느 것이 빠졌는지 알 수 없으므로** 하나도 대지 않는다:
                                    빈 목록이 정합성 검사를 깨워 재전송으로 보낸다. 여기서
                                    아무 id나 채우는 것은 추측이고, 추측은 누락을 지운다.
      ③ 셈도 없는 응답            → 요청 단위 승인이 가진 증거의 전부다. 이때만 보낸 목록으로
                                    읽고, 그 사실을 여기 적어 둔다."""
    if (named := _named_ids(output)) is not None:
        return named
    count = output.get("items_count")
    if isinstance(count, bool) or not isinstance(count, int):
        return tuple(record.record_id for record in records)
    if count == len(records):
        return tuple(record.record_id for record in records)
    return ()


@dataclasses.dataclass(frozen=True)
class ProjectMemoryBinding:
    """A deterministic project-to-namespace ownership assertion.

    The identifiers are not secrets.  They prevent accidental namespace
    crossover; backend ACLs remain responsible for hostile writers.
    """

    project_uid: str
    binding_id: str
    project_id: str
    schema: int = BINDING_SCHEMA

    def __post_init__(self) -> None:
        for name, value in (("project_uid", self.project_uid), ("binding_id", self.binding_id)):
            try:
                parsed = uuid.UUID(value)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"project memory {name} must be a UUID") from exc
            if str(parsed) != value.lower():
                raise ValueError(f"project memory {name} must be a canonical UUID")
        if self.schema != BINDING_SCHEMA or not self.project_id.strip():
            raise ValueError("invalid project memory binding schema or project_id")

    def to_json(self) -> str:
        return json.dumps(
            {
                "binding_id": self.binding_id,
                "project_id": self.project_id,
                "project_uid": self.project_uid,
                "schema": self.schema,
                "type": "asgard-project-memory-binding",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> "ProjectMemoryBinding":
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("type") != "asgard-project-memory-binding":
                raise ValueError
            return cls(
                project_uid=str(payload.get("project_uid") or ""),
                binding_id=str(payload.get("binding_id") or ""),
                project_id=str(payload.get("project_id") or ""),
                schema=int(payload.get("schema") or 0),
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid project memory binding document") from exc


@dataclasses.dataclass(frozen=True)
class BackendCapabilities:
    semantic_search: bool = False
    lexical_search: bool = False
    hybrid_search: bool = False
    metadata_filtering: bool = False
    metadata_roundtrip: bool = False
    namespace_isolation: bool = False
    stable_replace: bool = False
    delete: bool = False
    background_extraction: bool = False
    transactional_commit: bool = False
    ownership_binding: bool = False
    atomic_binding_create: bool = False
    file_upload: bool = False
    document_text_stored: bool = False


@dataclasses.dataclass(frozen=True)
class BackendReadiness:
    status: Literal["ready", "degraded", "unavailable"]
    engine: str
    project_id: str
    detail: str = ""


@runtime_checkable
class ProjectMemoryBackend(Protocol):
    engine: str
    api_version: int
    project_id: str

    def capabilities(self) -> BackendCapabilities: ...

    def readiness(self) -> BackendReadiness: ...

    def recall(self, query: str, max_results: int = 8) -> list[ProjectMemoryHit]: ...

    def retain(self, records: Sequence[ProjectMemoryRecord]) -> BackendWriteResult: ...

    def read_binding(self) -> ProjectMemoryBinding | None: ...

    def write_binding(self, binding: ProjectMemoryBinding) -> BackendWriteResult: ...

    def namespace_document_count(self) -> int: ...

    def close(self) -> None: ...


class HindsightBackend:
    engine = "hindsight"
    api_version = BACKEND_API_VERSION

    def __init__(self, settings: BackendSettings):
        if not settings.endpoint:
            raise ValueError("hindsight project memory endpoint is required")
        parsed = urllib.parse.urlsplit(settings.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("hindsight endpoint must be an http(s) URL without embedded credentials")
        self.settings = settings
        self.project_id = settings.project_id
        self.endpoint = settings.endpoint
        self.timeout = settings.timeout
        self._retain_fields: frozenset[str] | None = None
        self._features: dict | None = None

    def _post(self, path: str, payload: Mapping[str, object]) -> dict:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: Mapping[str, object]) -> dict:
        project_path = urllib.parse.quote(self.project_id, safe="")
        url = f"{self.endpoint}/v1/default/banks/{project_path}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(dict(payload)).encode(),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            decoded = json.loads(self._read_bounded(response).decode() or "{}")
        return decoded if isinstance(decoded, dict) else {}

    def _get(self, path: str, *, missing_ok: bool = False) -> dict | None:
        project_path = urllib.parse.quote(self.project_id, safe="")
        url = f"{self.endpoint}/v1/default/banks/{project_path}{path}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                decoded = json.loads(self._read_bounded(response).decode() or "{}")
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise
        if not isinstance(decoded, dict):
            raise ValueError("project memory backend returned a malformed object")
        return decoded

    @staticmethod
    def _read_bounded(response: Any) -> bytes:
        payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        if len(payload) > MAX_HTTP_RESPONSE_BYTES:
            raise ValueError(f"project memory backend response exceeds {MAX_HTTP_RESPONSE_BYTES} bytes")
        return payload

    def server_features(self) -> dict:
        """서버가 스스로 신고하는 기능 플래그 — `GET /version` (0.8.3 실측).

        openapi 스키마 파싱보다 싸고 정확하다. 스키마는 "필드가 있는가"만 말하지만 플래그는
        "이 배포에서 켜져 있는가"를 말한다 (file_upload_api·store_document_text 등)."""
        if self._features is not None:
            return self._features
        features: dict = {}
        with contextlib.suppress(Exception):
            request = urllib.request.Request(f"{self.endpoint}/version", method="GET")
            with urllib.request.urlopen(request, timeout=min(self.timeout, 10)) as response:
                payload = json.loads(self._read_bounded(response).decode() or "{}")
            if isinstance(payload, dict):
                raw = payload.get("features")
                features = {
                    "api_version": str(payload.get("api_version") or ""),
                    **({str(k): bool(v) for k, v in raw.items()} if isinstance(raw, Mapping) else {}),
                }
        self._features = features
        return features

    def supports(self, feature: str) -> bool:
        """서버가 이 기능을 켰다고 신고했는가. 모르면 False (없는 기능을 부르지 않는다)."""
        return bool(self.server_features().get(feature))

    def retain_fields(self) -> frozenset[str]:
        """서버가 실제로 받는 retain 항목 필드 — /openapi.json에서 읽는다 (버전 추측 금지).

        26-07-28 조사: Hindsight 문서끼리 어긋난다 (SDK 문서는 entities·observation_scopes를
        적고 HTTP 레퍼런스는 없다고 한다). raw HTTP를 쓰는 우리에게 정본은 **서버 스키마**다 —
        문서 대신 스키마를 읽고, 모르는 필드는 보내지 않는다. 실서버 0.8.3에서 entities·
        observation_scopes·strategy·timestamp 4 개가 이 경로로 자동 발견됐다."""
        if self._retain_fields is not None:
            return self._retain_fields
        fields = _BASE_RETAIN_FIELDS
        with contextlib.suppress(Exception):
            request = urllib.request.Request(f"{self.endpoint}/openapi.json", method="GET")
            with urllib.request.urlopen(request, timeout=min(self.timeout, 10)) as response:
                spec = json.loads(self._read_bounded(response).decode() or "{}")
            discovered = _retain_item_properties(spec)
            if discovered:
                fields = frozenset(discovered)
        self._retain_fields = fields
        return fields

    def bank_config(self) -> dict:
        """뱅크 설정 읽기. 응답은 {"bank_id":…, "config":{…}}로 중첩돼 있다 — 26-07-28 실측:
        최상위에서 찾으면 언제나 None이라 "설정이 안 걸렸다"고 오판한다."""
        payload = self._get("/config", missing_ok=True) or {}
        nested = payload.get("config")
        return dict(nested) if isinstance(nested, Mapping) else {}

    def update_bank_config(self, updates: Mapping[str, object]) -> dict:
        """뱅크 설정 갱신. 서버 스키마가 {"updates": {...}}로 감싸기를 요구한다."""
        payload = self._request("PATCH", "/config", {"updates": dict(updates)})
        nested = payload.get("config")
        return dict(nested) if isinstance(nested, Mapping) else {}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            semantic_search=True,
            lexical_search=True,
            hybrid_search=True,
            metadata_filtering=True,
            metadata_roundtrip=True,
            namespace_isolation=True,
            stable_replace=True,
            ownership_binding=True,
            # 배포마다 켜짐이 다르다 — 서버 신고를 그대로 옮긴다
            file_upload=self.supports("file_upload_api"),
            document_text_stored=self.supports("store_document_text"),
        )

    def readiness(self) -> BackendReadiness:
        if not self.endpoint or not self.project_id:
            return BackendReadiness("unavailable", self.engine, self.project_id, "endpoint and project_id are required")
        request = urllib.request.Request(f"{self.endpoint}/openapi.json", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 5)) as response:
                self._read_bounded(response)
        except Exception as exc:
            return BackendReadiness("unavailable", self.engine, self.project_id, type(exc).__name__)
        return BackendReadiness("ready", self.engine, self.project_id)

    def recall(self, query: str, max_results: int = 8) -> list[ProjectMemoryHit]:
        # Hindsight ranks extracted facts, but Asgard's project-memory trust gate
        # intentionally accepts only the exact Git-canonical document text. Ask
        # for each fact's source chunk and return that verbatim while preserving
        # the ranked fact's ownership/provenance metadata.
        output = self._post(
            "/memories/recall",
            {
                "query": query,
                "types": ["world", "experience"],
                "budget": "mid",
                "max_tokens": 2048,
                "include": {"entities": None, "chunks": {"max_tokens": 4096}},
            },
        )
        rows = output.get("results")
        results = rows if isinstance(rows, list) else []
        raw_chunks = output.get("chunks")
        chunks = raw_chunks if isinstance(raw_chunks, Mapping) else {}
        hits: list[ProjectMemoryHit] = []
        seen_documents: set[str] = set()
        limit = max(1, min(int(max_results), 50))
        for raw in results:
            if not isinstance(raw, Mapping):
                continue
            metadata = raw.get("metadata")
            score = raw.get("score")
            document_id = str(raw.get("document_id") or raw.get("id") or "")
            if document_id and document_id in seen_documents:
                continue
            chunk = chunks.get(str(raw.get("chunk_id") or ""))
            chunk_text = (
                chunk.get("text") if isinstance(chunk, Mapping) and chunk.get("truncated") is not True else None
            )
            hits.append(
                ProjectMemoryHit(
                    text=str(chunk_text or raw.get("text") or ""),
                    metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
                    document_id=document_id,
                    score=float(score) if isinstance(score, (int, float)) else None,
                )
            )
            if document_id:
                seen_documents.add(document_id)
            if len(hits) >= limit:
                break
        return hits

    def retain(self, records: Sequence[ProjectMemoryRecord]) -> BackendWriteResult:
        allowed = self.retain_fields()
        items = []
        for record in records:
            item: dict = {
                "content": record.text,
                "context": record.context,
                "document_id": record.record_id,
                "update_mode": "replace",
                "tags": list(record.tags),
                "metadata": dict(record.metadata),
            }
            # 서버가 받는다고 말한 선택 필드만 덧붙인다. 코드·규격에는 발생 시각이 없다 —
            # timestamp를 지금으로 두면 서버의 상대시간 해석이 파일 나이를 오늘로 착각한다.
            if "timestamp" in allowed and record.timeless:
                item["timestamp"] = "unset"
            if "entities" in allowed and record.entities:
                item["entities"] = [{"text": name, "type": kind} for name, kind in record.entities]
            if "strategy" in allowed and record.strategy:
                item["strategy"] = record.strategy
            if "observation_scopes" in allowed and record.observation_scopes is not None:
                scopes = record.observation_scopes
                item["observation_scopes"] = [list(scope) for scope in scopes] if isinstance(scopes, tuple) else scopes
            items.append(item)
        output = self._post("/memories", {"items": items, "async": False})
        success = output.get("success") is True
        accepted = _accepted_ids(output, records) if success else ()
        error = str(output.get("error") or "")
        return BackendWriteResult(
            success=success,
            accepted_ids=accepted,
            rejected={} if success else {record.record_id: error or "backend rejected record" for record in records},
            error=error,
            details=output,
        )

    def reflect(self, query: str, budget: str = "low", max_tokens: int = 2048) -> dict:
        """Reflect — bank 전체를 근거로 LLM 합성 답변. 반환 = {"text", "based_on"?}.

        읽기 전용 자문 표면이다: 산출은 backend LLM의 종합이지 Git 정본이 아니므로
        자동 컨텍스트 주입 자격이 없다 (게이트·trust 필터 계약과 무관한 별도 소비면)."""
        if budget not in {"low", "mid", "high"}:
            raise ValueError("reflect budget must be low|mid|high")
        output = self._post(
            "/reflect",
            {
                "query": query,
                "budget": budget,
                "max_tokens": max(256, min(int(max_tokens), 8192)),
                "include": {"facts": {}},  # {} = 근거 facts 동봉 활성 (Hindsight 0.8 스키마)
            },
        )
        text = output.get("text")
        if not isinstance(text, str):
            raise ValueError("project memory backend returned a malformed reflect response")
        return output

    def consolidate(self, tag_scopes: Sequence[Sequence[str]]) -> dict:
        """선택 태그의 미통합 fact만 observation으로 올리는 비동기 작업을 예약한다."""
        scopes = [[str(tag) for tag in scope] for scope in tag_scopes if scope]
        if not scopes:
            raise ValueError("project memory consolidation requires at least one non-empty tag scope")
        output = self._post("/consolidate", {"observation_scopes": scopes})
        if not isinstance(output.get("operation_id"), str):
            raise ValueError("project memory backend returned a malformed consolidation result")
        return output

    def list_mental_models(self) -> list[dict]:
        output = self._get("/mental-models?detail=full") or {}
        items = output.get("items")
        if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
            raise ValueError("project memory backend returned malformed mental models")
        return [dict(item) for item in items]

    def create_mental_model(self, spec: Mapping[str, object]) -> dict:
        output = self._post("/mental-models", spec)
        if not isinstance(output.get("operation_id"), str):
            raise ValueError("project memory backend returned a malformed mental-model result")
        return output

    def update_mental_model(self, model_id: str, spec: Mapping[str, object]) -> dict:
        path = "/mental-models/" + urllib.parse.quote(model_id, safe="")
        output = self._request("PATCH", path, spec)
        if str(output.get("id") or "") != model_id:
            raise ValueError("project memory backend returned a malformed mental-model update")
        return output

    def refresh_mental_model(self, model_id: str) -> dict:
        path = "/mental-models/" + urllib.parse.quote(model_id, safe="") + "/refresh"
        output = self._post(path, {})
        if not isinstance(output.get("operation_id"), str):
            raise ValueError("project memory backend returned a malformed mental-model refresh result")
        return output

    def read_binding(self) -> ProjectMemoryBinding | None:
        document = self._get(
            "/documents/" + urllib.parse.quote(BINDING_DOCUMENT_ID, safe=""),
            missing_ok=True,
        )
        if document is None:
            return None
        original = document.get("original_text")
        if not isinstance(original, str):
            raise ValueError("invalid project memory binding document")
        binding = ProjectMemoryBinding.from_json(original)
        if binding.project_id != self.project_id:
            raise ValueError("project memory binding project_id mismatch")
        return binding

    def write_binding(self, binding: ProjectMemoryBinding) -> BackendWriteResult:
        if binding.project_id != self.project_id:
            raise ValueError("project memory binding project_id mismatch")
        return self.retain(
            [
                ProjectMemoryRecord(
                    record_id=BINDING_DOCUMENT_ID,
                    text=binding.to_json(),
                    context="asgard project memory ownership binding",
                    tags=("asgard:control", "kind:binding"),
                    metadata={
                        "scope": "control",
                        "kind": "binding",
                        "project_uid": binding.project_uid,
                        "binding_id": binding.binding_id,
                        "schema": str(binding.schema),
                    },
                )
            ]
        )

    def namespace_document_count(self) -> int:
        stats = self._get("/stats")
        count = stats.get("total_documents") if isinstance(stats, dict) else None
        if not isinstance(count, int) or count < 0:
            raise ValueError("project memory backend returned invalid namespace statistics")
        return count

    def close(self) -> None:
        """urllib transport owns no persistent client resources."""
        return None


def _retain_item_properties(spec: Mapping[str, object]) -> set[str]:
    """OpenAPI 문서에서 retain item의 속성 이름을 뽑는다. 못 찾으면 빈 집합.

    스키마 **이름**은 배포마다 달라질 수 있으므로 **모양**으로 찾는다 — `content`를 가진
    오브젝트 스키마 중 기본 필드를 가장 많이 겹치는 것이 retain item 이다."""
    schemas = spec.get("components")
    schemas = schemas.get("schemas") if isinstance(schemas, Mapping) else None
    if not isinstance(schemas, Mapping):
        return set()
    best: set[str] = set()
    for definition in schemas.values():
        if not isinstance(definition, Mapping) or definition.get("type") != "object":
            continue
        properties = definition.get("properties")
        if not isinstance(properties, Mapping) or "content" not in properties:
            continue
        names = {str(key) for key in properties}
        if len(names & _BASE_RETAIN_FIELDS) >= 3 and len(names) > len(best):
            best = names
    return best


BackendFactory = Callable[[BackendSettings], Any]
_FACTORIES: dict[str, BackendFactory] = {"hindsight": HindsightBackend}
ENTRY_POINT_GROUP = "asgard.project_memory_backends"


def register_backend(name: str, factory: BackendFactory, *, replace: bool = False) -> None:
    key = name.strip().lower()
    if not key:
        raise ValueError("project memory backend name is required")
    if key in _FACTORIES and not replace:
        raise ValueError(f"project memory backend already registered: {key}")
    _FACTORIES[key] = factory


def _load_entry_point_factory(engine: str) -> BackendFactory | None:
    matches = [
        entry for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP) if entry.name.lower() == engine
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"multiple project memory backend plugins registered: {engine}")
    trusted = {
        name.strip().lower() for name in os.environ.get("ASGARD_PROJECT_MEMORY_PLUGINS", "").split(",") if name.strip()
    }
    if engine not in trusted:
        raise ValueError(
            f"project memory backend plugin {engine} is installed but not trusted; "
            "allow it in ASGARD_PROJECT_MEMORY_PLUGINS"
        )
    try:
        factory = matches[0].load()
    except Exception as exc:
        raise ValueError(f"failed to load project memory backend plugin {engine}: {type(exc).__name__}") from exc
    if not callable(factory):
        raise ValueError(f"project memory backend plugin is not callable: {engine}")
    return factory


def parse_settings(config: Mapping[str, object]) -> BackendSettings:
    canonical_project = str(config.get("project_id") or "").strip()
    legacy_project = str(config.get("bank") or "").strip()
    canonical_endpoint = str(config.get("endpoint") or "").rstrip("/")
    legacy_endpoint = str(config.get("server") or "").rstrip("/")
    if canonical_project and legacy_project and canonical_project != legacy_project:
        raise ValueError("conflicting project memory project_id and legacy bank")
    if canonical_endpoint and legacy_endpoint and canonical_endpoint != legacy_endpoint:
        raise ValueError("conflicting project memory endpoint and legacy server")
    engine = str(config.get("engine") or "hindsight").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", engine):
        raise ValueError("project memory engine must match [a-z0-9][a-z0-9_-]{0,63}")
    project_id = canonical_project or legacy_project
    if not project_id:
        raise ValueError("project memory project_id is required")
    endpoint = canonical_endpoint or legacy_endpoint
    timeout_value = config.get("timeout")
    options_value = config.get("options")
    timeout = 15 if timeout_value is None else int(str(timeout_value))
    # 상한 300s는 서버가 그보다 오래 걸릴 수 있다는 사실보다 먼저 정해진 값이었다. 26-07-28 실측:
    # 로컬 12B 추출이 문서 하나에 57s, 서버 LLM 타임아웃도 600s로 올렸다. 클라이언트가 서버보다
    # 먼저 포기하면 등록은 서버에서 성공하고 우리만 실패로 기록한다 — 그 어긋남이 manifest를 속인다.
    if not 1 <= timeout <= MAX_BACKEND_TIMEOUT:
        raise ValueError(f"project memory timeout must be between 1 and {MAX_BACKEND_TIMEOUT} seconds")
    if options_value is not None and not isinstance(options_value, Mapping):
        raise ValueError("project memory options must be an object")
    options = {str(key): value for key, value in options_value.items()} if isinstance(options_value, Mapping) else {}
    return BackendSettings(
        engine=engine,
        project_id=project_id,
        endpoint=endpoint,
        timeout=timeout,
        project_uid=str(config.get("project_uid") or "").strip(),
        binding_id=str(config.get("binding_id") or "").strip(),
        options=options,
        raw=dict(config),
    )


def get_backend(config: Mapping[str, object]) -> ProjectMemoryBackend:
    settings = parse_settings(config)
    engine = settings.engine
    factory = _FACTORIES.get(engine) or _load_entry_point_factory(engine)
    if factory is None:
        raise ValueError(f"unknown project memory engine: {engine}")
    backend = factory(settings)
    if not isinstance(backend, ProjectMemoryBackend):
        close = getattr(backend, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()
        raise TypeError(f"backend {engine} does not implement ProjectMemoryBackend")
    try:
        if backend.engine.strip().lower() != engine:
            raise ValueError(f"project memory backend engine mismatch: configured={engine}, adapter={backend.engine}")
        if backend.project_id != settings.project_id:
            raise ValueError(
                f"project memory backend project_id mismatch: configured={settings.project_id}, adapter={backend.project_id}"
            )
        if backend.api_version != BACKEND_API_VERSION:
            raise ValueError(
                f"project memory backend API version mismatch: core={BACKEND_API_VERSION}, adapter={backend.api_version}"
            )
        capabilities = backend.capabilities()
        if not isinstance(capabilities, BackendCapabilities):
            raise TypeError(f"project memory backend {engine} capabilities() must return BackendCapabilities")
        required = ("metadata_roundtrip", "namespace_isolation", "stable_replace", "ownership_binding")
        missing = [name for name in required if not getattr(capabilities, name)]
        if missing:
            raise ValueError(
                f"project memory backend {engine} lacks required safety capabilities: {', '.join(missing)}"
            )
    except Exception:
        with contextlib.suppress(Exception):
            backend.close()
        raise
    return backend


__all__ = [
    "BackendCapabilities",
    "BACKEND_API_VERSION",
    "BackendReadiness",
    "BackendSettings",
    "BackendWriteResult",
    "HindsightBackend",
    "ProjectMemoryBackend",
    "ProjectMemoryBinding",
    "ProjectMemoryHit",
    "ProjectMemoryRecord",
    "get_backend",
    "parse_settings",
    "register_backend",
]
