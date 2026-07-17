<!-- asgard:project-map schema=1 -->
# Project Map — asgard

> Asgard managed orientation map. Regenerate with `asgard setup map`; do not hand-edit this file.
> It is a navigation hint, not completion evidence: re-read every path used by a plan.

## Orientation

- Project root: `./`
- Languages by observed source files: Python (152)
- Evidence scan: 247 files; 20 landmarks

## Landmarks

- `README.md` — project overview and operating guide
- `docker/` — container and deployment area
- `docker/asgard-common-memory/` — project boundary (docker-compose.yml)
- `docker/asgard-common-memory2/` — project boundary (docker-compose.yml)
- `pyproject.toml` — Python project manifest
- `src/` — primary source area
- `src/asgard/` — Python package root
- `src/asgard/agent/` — Python package root
- `src/asgard/agent/heimdall/` — Python package root
- `src/asgard/cli.py` — CLI entrypoint `asgard`
- `src/asgard/commands/` — Python package root
- `src/asgard/commands/memory_dashboard/` — Python package root
- `src/asgard/hooks/` — Python package root
- `src/asgard/memory/` — Python package root
- `src/asgard/memory_bridge/` — Python package root
- `src/asgard/project_memory/` — Python package root
- `src/asgard/project_memory_backends/` — Python package root
- `src/asgard/templates/` — Python package root
- `src/asgard/templates/roles/` — Python package root
- `tests/` — test area

## Navigation contract

- Read `PROJECT.md` first, then the matching human-authored area map if present.
- Verify target definitions and usages from source before planning or editing.
- Structural changes refresh this managed map before Verifier hashing; use `--check` in CI to detect drift.
