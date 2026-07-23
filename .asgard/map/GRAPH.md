<!-- asgard:map-graph schema=1 -->
# Relation Graph

> Asgard managed relation catalog. Regenerate with `asgard map scan`; do not hand-edit.
> `?` marks candidate evidence — verify at the cited source before asserting.

- Evidence summary: commands 55 · models 2 · db 1 · calls 14 · uses 3

## Relations by file

- `src/asgard/cli.py` — commands: add, approve, archive, assign, bench, check, completions, connect, context, dashboard, dashboard, desktop, disable, doctor, enable, export-okf, generate, ingest, init, install, lint, list, list, list, list, list, login, logout, map, mcp, merge, model, nudge, obsidian, path, polish, project-approve, project-rehydrate, project-scan, project-sync, query, recall, reindex, reject, remove, resolve, restore, run, run, run, scan, scan, show, show, show, snapshot, start, status, sync, sync-turn, trace, unassign, uninstall, update, update, view
- `src/asgard/memory/index.py` — db: conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?, conn.execute?
- `src/asgard/openai_codex.py` — calls: httpx.get?, httpx.post? · uses: openai
- `src/asgard/agent/session.py` — uses: anthropic, openai
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/app/builder/page.tsx` — calls: /api/references/${id}?, /api/references?
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/scripts/convert_hwp.py` — models: InfoResult, PageDef
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/cip/generate.py` — uses: google-cloud
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/icon/generate.py` — uses: google-cloud
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/logo/generate.py` — uses: google-cloud
- `benchmarks/shortcut-recall/harness.py` — db: conn.execute?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/scripts/analytics/prune-ga4-keyevents.mjs` — calls: ${BASE}${path}?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/scripts/analytics/setup-ga4.mjs` — calls: ${BASE}${path}?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/scripts/build-embeddings.mjs` — calls: https://openrouter.ai/api/v1/embeddings
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/app/api/font-playground/match/route.ts` — uses: anthropic
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/app/api/github-stars/route.ts` — calls: https://api.github.com/repos/${REPO}
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/app/playground/playground-view.tsx` — calls: /api/references/${refId}?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/components/analytics-consent.tsx` — calls: /api/geo?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/components/font-playground/match-results.tsx` — calls: /api/font-playground/match?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/components/reference-selector.tsx` — calls: /api/geo?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/lib/active.ts` — calls: /api/active?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/lib/gtag.ts` — calls: /api/track?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/lib/hot-refs.ts` — calls: /api/leaderboard?event=${event}&limit=${limit}?
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/src/lib/use-github-stars.ts` — calls: /api/github-stars?

## Navigation contract

- Trace edges with `asgard map trace --from <node-id>` (`--kinds touches,calls` filters edge kinds).
