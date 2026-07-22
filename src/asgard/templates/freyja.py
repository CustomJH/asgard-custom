"""Minimal Freyja role contract.

Specialist skills are intentionally rebuilt and assigned one at a time.
"""

from .roles import role_core_skill

FREYJA_SKILLS: list[tuple[str, str]] = []


def resolve_freyja_skills(_task: str) -> list[tuple[str, str]]:
    return []


def freyja_core_skill() -> str:
    return role_core_skill(
        "asgard-freyja.md",
        "Freyja UI/UX delivery using the default Freyja Design engine.",
    )
