"""휠에 코드로 들어 있는 기본 플러그인과 그 해석기 — 본문은 templates 에서 늦게 부른다."""

from __future__ import annotations


def _builtin_plugins() -> dict[str, dict]:
    """Built-ins are imported lazily; several skill bodies are intentionally large."""
    from ..templates import BRIDGE_SKILL_MD, SEAL_SKILL_MD, SELFTEST_MD
    from ..templates.bragi import BRAGI_SKILLS
    from ..templates.eitri import EITRI_SKILLS
    from ..templates.freyja import FREYJA_SKILLS, freyja_core_skill
    from ..templates.just import JUST_SKILLS
    from ..templates.lagom import LAGOM_SKILLS
    from ..templates.memory import MEMORY_SKILL_MD
    from ..templates.mimir import MIMIR_SKILLS, mimir_core_skill
    from ..templates.siege import SIEGE_SKILLS
    from ..templates.thor import THOR_SKILLS, eitri_core_skill, thor_core_skill
    from ..templates.worker import WORKER_SKILLS

    return {
        "asgard-core": {
            "description": "Asgard bridge, self-test, seal, and memory contracts",
            "skills": [
                ("asgard-provider", BRIDGE_SKILL_MD),
                ("asgard-test", SELFTEST_MD),
                ("asgard-seal", SEAL_SKILL_MD),
                ("asgard-memory", MEMORY_SKILL_MD),
            ],
        },
        "worker": {
            "description": "Common delivery debugging and testing policy",
            "skills": WORKER_SKILLS,
            "agents": ("worker", "thor", "thor-lead"),
            "resolver": "worker",
        },
        "freyja": {
            "description": "Freyja UI/UX and frontend delivery contract",
            "skills": [("asgard-freyja", freyja_core_skill()), *FREYJA_SKILLS],
            "agents": ("freyja",),
            "resolver": "freyja",
        },
        "thor": {
            "description": "Backend, data, API, and runtime policy",
            "skills": [("asgard-thor", thor_core_skill()), *THOR_SKILLS],
            "agents": ("thor", "thor-lead"),
            "resolver": "thor",
        },
        "eitri": {
            "description": "Build, CI, packaging, and release automation",
            "skills": [("asgard-eitri", eitri_core_skill()), *EITRI_SKILLS],
            "agents": ("eitri",),
            "resolver": "eitri",
        },
        "mimir": {
            "description": "Code walkthrough and onboarding policy",
            "skills": [("asgard-mimir", mimir_core_skill()), *MIMIR_SKILLS],
            "agents": ("mimir",),
            "resolver": "mimir",
        },
        # siege — 배차 장부를 모는 계약. 딜리버리 전문가와 달리 표면이 아니라 조율을 진다:
        # Worker 와 Thor 편대장이 배차를 여는 쪽이라 그 둘에만 붙인다.
        "siege": {
            "description": "Dispatch ledger — task graphs, attempts, coordinator mail, and decision gates",
            "skills": SIEGE_SKILLS,
            "agents": ("worker", "thor-lead"),
            "resolver": "siege",
        },
        # just — 실행 표면. 명령을 실제로 부르는 역할 전부에 붙는다: 표면이 갈라지는 것은
        # 한 역할이 raw 명령으로 돌아가는 순간이고, 그 순간은 어느 역할에서든 온다.
        "just": {
            "description": "The project's run surface — one Justfile, written from the manifests and extended by hand",
            "skills": JUST_SKILLS,
            "agents": ("worker", "thor", "thor-lead", "eitri", "freyja"),
            "resolver": "just",
        },
        "lagom": {"description": "Lagom review, debt, and compression modes", "skills": LAGOM_SKILLS},
        "bragi": {"description": "Human-voice audit and rewrite for reports, any language", "skills": BRAGI_SKILLS},
    }


def _builtin_resolver(name: str):
    if name == "worker":
        from ..templates.worker import resolve_worker_skills

        return resolve_worker_skills
    if name == "freyja":
        from ..templates.freyja import resolve_freyja_skills

        return resolve_freyja_skills
    if name == "thor":
        from ..templates.thor import resolve_thor_skills

        return resolve_thor_skills
    if name == "eitri":
        from ..templates.eitri import resolve_eitri_skills

        return resolve_eitri_skills
    if name == "mimir":
        from ..templates.mimir import resolve_mimir_skills

        return resolve_mimir_skills
    if name == "siege":
        from ..templates.siege import resolve_siege_skills

        return resolve_siege_skills
    if name == "just":
        from ..templates.just import resolve_just_skills

        return resolve_just_skills
    return None
