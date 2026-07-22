"""Spring 설정 해석기 — `${placeholder}` 를 체크인된 base 설정값으로만 해석한다.

계약: 해석은 이름 승격이지 추측이 아니다. base `application.{yml,yaml,properties}` 가
유일하게 증명하는 스칼라 값만 쓴다. 프로파일 파일(`application-*.yml`)은 환경 의존이라
제외하고, 같은 스코프에서 키가 서로 다른 값으로 중복 정의되면 해석을 포기한다 —
모호성은 미해결 증거로 보존한다.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .evidence import Evidence

_BASE_NAMES = {"application.yml", "application.yaml", "application.properties"}
_PLACEHOLDER = re.compile(r"^\$\{([^:{}]+)(?::([^{}]*))?\}$")
_AMBIGUOUS = ("", "")  # 충돌 마커 — 값이 아니라 "해석 금지" 신호


def _literal(value: object) -> str | None:
    """설정 값 → 증명 가능한 리터럴. `${ENV:default}` 는 default, 미해결 잔여 `${` 는 포기."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    matched = _PLACEHOLDER.fullmatch(text)
    if matched:
        text = (matched.group(2) or "").strip()
    if not text or "${" in text:
        return None
    return text


def _flatten(node: object, prefix: str, into: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, (str, int)):
                _flatten(value, f"{prefix}{key}.", into)
        return
    literal = _literal(node)
    if literal is not None and prefix:
        into[prefix.rstrip(".")] = literal


class SpringProps:
    """스코프(모노레포 최상위 디렉터리) 단위 base 설정 테이블."""

    def __init__(self) -> None:
        # scope → key → (value, source) — 충돌 시 _AMBIGUOUS 로 강등되어 해석이 막힌다.
        self._scoped: dict[str, dict[str, tuple[str, str]]] = {}

    @staticmethod
    def is_config(name: str) -> bool:
        return name in _BASE_NAMES

    @staticmethod
    def _scope(rel_posix: str) -> str:
        parts = rel_posix.split("/")
        return parts[0] if len(parts) > 1 else ""

    def ingest(self, rel_posix: str, source: str) -> None:
        flat: dict[str, str] = {}
        if rel_posix.endswith(".properties"):
            for line in source.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", "!")) or "=" not in stripped:
                    continue
                key, _, raw = stripped.partition("=")
                literal = _literal(raw)
                if key.strip() and literal is not None:
                    flat[key.strip()] = literal
        else:
            try:
                import yaml

                documents = list(yaml.safe_load_all(source))
            except Exception:
                return
            for document in documents:
                _flatten(document, "", flat)
        table = self._scoped.setdefault(self._scope(rel_posix), {})
        for key, value in flat.items():
            existing = table.get(key)
            if existing is not None and existing != _AMBIGUOUS and existing[0] != value:
                table[key] = _AMBIGUOUS
            elif existing is None:
                table[key] = (value, rel_posix)

    def _lookup(self, key: str, scope: str) -> tuple[str, str] | None:
        for table in (self._scoped.get(scope), self._scoped.get("")):
            if table and key in table:
                hit = table[key]
                return None if hit == _AMBIGUOUS else hit
        # 리포 전체에서 정확히 한 스코프만 키를 정의하면 그 정의가 유일한 증명이다.
        owners = [table[key] for table in self._scoped.values() if key in table]
        if len(owners) == 1 and owners[0] != _AMBIGUOUS:
            return owners[0]
        return None

    def promote(self, collected: list[Evidence]) -> list[Evidence]:
        """`${key}` 전체-문자열 이름의 이벤트 증거만 리터럴로 승격한다 (해석 실패는 원문 보존)."""
        promoted: list[Evidence] = []
        for item in collected:
            matched = _PLACEHOLDER.fullmatch(item.name.strip()) if item.kind == "event" else None
            if matched is None:
                promoted.append(item)
                continue
            key, inline_default = matched.group(1).strip(), matched.group(2)
            hit = self._lookup(key, self._scope(item.file))
            if hit is None and inline_default is not None:
                literal = _literal(item.name.strip())
                hit = (literal, "annotation default") if literal is not None else None
            if hit is None:
                promoted.append(item)
                continue
            value, source = hit
            trail = f"{item.name} → {source}"
            detail = f"{item.detail} · {trail}" if item.detail else trail
            promoted.append(replace(item, name=value, confidence="confirmed", detail=detail))
        return promoted
