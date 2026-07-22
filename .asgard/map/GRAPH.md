<!-- asgard:map-graph schema=1 -->
# Relation Graph

> Asgard managed relation catalog. Regenerate with `asgard map scan`; do not hand-edit.
> `?` marks candidate evidence — verify at the cited source before asserting.

- Evidence summary: commands 34 · models 2 · db 1 · calls 2 · uses 3

## Relations by file

- `src/asgard/cli.py` — commands: add, assign, check, completions, context, disable (+34)
- `src/asgard/memory/index.py` — db: conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute? (+5)
- `src/asgard/openai_codex.py` — calls: httpx.get?, httpx.post? · uses: openai
- `src/asgard/agent/session.py` — uses: anthropic, openai
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/scripts/convert_hwp.py` — models: InfoResult, PageDef
- `src/asgard/assets/skill_plugins/ui-ux-pro-max/skills/design/scripts/cip/generate.py` — uses: google-cloud
- `src/asgard/assets/skill_plugins/ui-ux-pro-max/skills/design/scripts/icon/generate.py` — uses: google-cloud
- `src/asgard/assets/skill_plugins/ui-ux-pro-max/skills/design/scripts/logo/generate.py` — uses: google-cloud

## Navigation contract

- Trace edges with `asgard map trace --from <node-id>`.
