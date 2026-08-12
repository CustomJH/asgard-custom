"""SKILL.md 프론트매터와 파일 읽기 — 이 패키지의 다른 모듈을 부르지 않는다."""

from __future__ import annotations

import re


def _read_text(path: str) -> str:
    """읽고 반드시 닫는다. 실패는 그대로 올린다 — 여기서 삼키면 호출부의 판정이 조용히 바뀐다."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _description(text: str) -> str:
    match = re.search(r"^description:\s*(.+)$", text.split("---", 2)[1], re.M)
    return match.group(1).strip() if match else ""


def _implicit(text: str) -> bool:
    """Whether a skill may enter model discovery context (Agent Skills convention)."""
    if not text.startswith("---"):
        return True
    match = re.search(r"^disable-model-invocation:\s*(.+)$", text.split("---", 2)[1], re.M)
    return not match or match.group(1).strip().lower() not in ("true", "yes", "1", "on")


def _lane(text: str) -> str:
    """Declared execution lane of a skill, or "" when it takes the ordinary delivery route.

    The native loop classifies a turn from the request text, and a user-invoked skill hands it
    the whole SKILL.md body instead — a contract that says what the procedure *may* do, not what
    the user asked for. `asgard-seal`'s old body alone carried twelve write verbs, so the write-verb
    veto in `Heimdall._classify` promoted every `/asgard-seal` to a Trinity quest (plan → worker
    waves → baseline suite → verifier) for a run that only calls git. A skill whose procedure is
    already bounded declares its lane here and the router reads the declaration instead of
    guessing from prose.
    """
    if not text.startswith("---"):
        return ""
    match = re.search(r"^lane:\s*(.+)$", text.split("---", 2)[1], re.M)
    return match.group(1).strip().lower() if match else ""


def _file_skill(text: str) -> tuple[dict[str, str], str] | None:
    """Parse standard SKILL.md metadata; routing may live in plugin.json."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return (meta, parts[2].lstrip()) if meta.get("name") else None


def _items(value) -> list[str]:
    raw = value if isinstance(value, list) else str(value or "").split(",")
    return [str(item).strip() for item in raw if str(item).strip()]
