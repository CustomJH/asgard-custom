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

    def _post(self, path: str, payload: Mapping[str, object]) -> dict:
        project_path = urllib.parse.quote(self.project_id, safe="")
        url = f"{self.endpoint}/v1/default/banks/{project_path}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(dict(payload)).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
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

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            semantic_search=True,
            metadata_filtering=True,
            metadata_roundtrip=True,
            namespace_isolation=True,
            stable_replace=True,
            ownership_binding=True,
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
        output = self._post("/memories/recall", {"query": query})
        rows = output.get("results")
        results = rows if isinstance(rows, list) else []
        hits: list[ProjectMemoryHit] = []
        for raw in results[: max(1, min(int(max_results), 50))]:
            if not isinstance(raw, Mapping):
                continue
            metadata = raw.get("metadata")
            score = raw.get("score")
            hits.append(
                ProjectMemoryHit(
                    text=str(raw.get("text") or ""),
                    metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
                    document_id=str(raw.get("document_id") or raw.get("id") or ""),
                    score=float(score) if isinstance(score, (int, float)) else None,
                )
            )
        return hits

    def retain(self, records: Sequence[ProjectMemoryRecord]) -> BackendWriteResult:
        items = [
            {
                "content": record.text,
                "context": record.context,
                "document_id": record.record_id,
                "update_mode": "replace",
                "tags": list(record.tags),
                "metadata": dict(record.metadata),
            }
            for record in records
        ]
        output = self._post("/memories", {"items": items, "async": False})
        success = output.get("success") is True
        accepted = tuple(record.record_id for record in records) if success else ()
        error = str(output.get("error") or "")
        return BackendWriteResult(
            success=success,
            accepted_ids=accepted,
            rejected={} if success else {record.record_id: error or "backend rejected record" for record in records},
            error=error,
            details=output,
        )

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
    if not 1 <= timeout <= 300:
        raise ValueError("project memory timeout must be between 1 and 300 seconds")
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
