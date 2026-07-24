"""Spring 설정 해석기 — `${placeholder}` 를 체크인된 base 설정값으로만 해석한다.

계약: 해석은 이름 승격이지 추측이 아니다. base `application.{yml,yaml,properties}` 가
유일하게 증명하는 스칼라 값만 쓴다. 프로파일 파일(`application-*.yml`)은 환경 의존이라
제외하고, 같은 스코프에서 키가 서로 다른 값으로 중복 정의되면 해석을 포기한다 —
모호성은 미해결 증거로 보존한다.

대상: 이벤트 토픽(전체-문자열 `${...}`)과 라우트·api_call 이름(임베디드 `${...}` 치환,
예: `GET /${api.prefix}orders` → `GET /api/v2/orders`). 라우트 해석은 API↔라우트
브리지의 완전 일치 근거가 된다.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .evidence import Evidence, safe_url

_BASE_NAMES = {"application.yml", "application.yaml", "application.properties"}
_PLACEHOLDER = re.compile(r"^\$\{([^:{}]+)(?::([^{}]*))?\}$")
_EMBEDDED = re.compile(r"\$\{([^:{}]+)(?::([^{}]*))?\}")
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

    def _resolve_embedded(self, text: str, scope: str) -> tuple[str, list[str]] | None:
        """텍스트에 박힌 `${key[:default]}` 전부를 설정값으로 치환한다. 하나라도 못 풀면 None.

        라우트 클래스 프리픽스(`${api.prefix}orders`)나 Feign url 처럼 플레이스홀더가
        리터럴과 섞인 이름을 실제 경로로 복원한다 — 부분 해석은 정체가 아니라서 안 한다.
        """
        trails: list[str] = []
        failed = False

        def substitute(match: re.Match[str]) -> str:
            nonlocal failed
            key, inline_default = match.group(1).strip(), match.group(2)
            hit = self._lookup(key, scope)
            if hit is None and inline_default is not None:
                literal = _literal(match.group(0))
                hit = (literal, "annotation default") if literal is not None else None
            if hit is None:
                failed = True
                return match.group(0)
            value, source = hit
            trails.append(f"${{{key}}} → {value} ({source})")
            return value

        resolved = _EMBEDDED.sub(substitute, text)
        return None if failed or not trails else (resolved, trails)

    def promote(self, collected: list[Evidence]) -> list[Evidence]:
        """설정이 증명하는 이름 승격 — 이벤트는 전체-문자열, 라우트/api_call 은 임베디드 치환.

        해석 실패는 원문 보존(candidate 유지·브리지의 접두 벗김 폴백이 이어받는다).
        """
        promoted: list[Evidence] = []
        for item in collected:
            if item.kind == "event":
                matched = _PLACEHOLDER.fullmatch(item.name.strip())
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
                continue
            if item.kind in {"route", "api_call"} and "${" in item.name:
                resolved = self._resolve_embedded(item.name, self._scope(item.file))
                if resolved is None:
                    promoted.append(item)
                    continue
                name, trails = resolved
                confidence = item.confidence
                if item.kind == "route":
                    # 프리픽스 값의 앞뒤 `/` 로 생긴 중복 슬래시를 경로 표기로 정돈한다
                    method, _, raw = name.partition(" ")
                    name = f"{method} " + re.sub(r"/{2,}", "/", raw)
                else:
                    name = safe_url(name)
                    if name.startswith(("http://", "https://")):
                        # URL 정체가 설정으로 증명됐다 — 추출기의 리터럴 URL 기준과 동일 승격
                        confidence = "confirmed"
                trail = " · ".join(trails)
                detail = f"{item.detail} · {trail}" if item.detail else trail
                promoted.append(replace(item, name=name, confidence=confidence, detail=detail))
                continue
            promoted.append(item)
        return promoted
