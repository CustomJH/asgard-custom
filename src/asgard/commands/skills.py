"""CLI surfaces for the Asgard-owned skill and plugin catalog."""

import json
import os
import sys

from ..skill_registry import (
    assign_skill,
    install_plugin,
    plugins,
    resolve_skills,
    run_skill,
    set_skill_enabled,
    show_skill,
    show_skill_resource,
    skills,
)


def run_skills_list(json_out: bool = False) -> int:
    rows = skills(os.getcwd())
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['name']}\t{row['plugin']}\t{row['origin']}\t{row['invocation']}\t{row['description']}")
    return 0


def run_skills_show(name: str, body_only: bool = True, resource: str | None = None) -> int:
    try:
        text = show_skill_resource(os.getcwd(), name, resource) if resource else show_skill(os.getcwd(), name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if text is None:
        print(f"skill not found: {name}", file=sys.stderr)
        return 2
    if resource is None and body_only and text.startswith("---"):
        text = text.split("---", 2)[2].lstrip()
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def run_skills_resolve(agent: str, task: str | None, json_out: bool = False) -> int:
    if agent not in ("worker", "freyja", "freyja-lead", "thor", "thor-lead", "eitri", "mimir", "verifier", "loki"):
        print("invalid agent", file=sys.stderr)
        return 2
    task = task if task is not None else sys.stdin.read()
    if not task.strip():
        print("task is required", file=sys.stderr)
        return 2
    rows = resolve_skills(os.getcwd(), task, agent)
    if json_out:
        print(json.dumps([{"name": name, "body": body} for name, body in rows], ensure_ascii=False, indent=2))
    elif rows:
        print("\n\n".join(f"# Skill: {name}\n\n{body.rstrip()}" for name, body in rows))
    return 0


def run_plugins_list(json_out: bool = False) -> int:
    rows = plugins()
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(
                f"{row['name']}\t{row['version']}\t{row['origin']}\t{len(row['skills'])} skills\t{row['description']}"
            )
    return 0


def run_plugins_install(source: str) -> int:
    try:
        manifest = install_plugin(source)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"installed {manifest['name']} {manifest['version']} ({len(manifest['skills'])} skills)")
    return 0


def run_skills_run(name: str, args: list[str]) -> int:
    try:
        return run_skill(os.getcwd(), name, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def run_skills_assign(name: str, agent: str, *, assigned: bool) -> int:
    try:
        assign_skill(os.getcwd(), name, agent, assigned=assigned)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"{'assigned' if assigned else 'unassigned'} {name} {'to' if assigned else 'from'} {agent}")
    return 0


def run_skills_enable(name: str, *, enabled: bool) -> int:
    try:
        set_skill_enabled(os.getcwd(), name, enabled=enabled)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"{'enabled' if enabled else 'disabled'} {name}")
    return 0
