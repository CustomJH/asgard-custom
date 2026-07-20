---
name: 21st-cli-use
description: Search, inspect, and install React, shadcn, Tailwind components, themes, templates, and SVG logos from 21st.dev with its official CLI. Use for 21st.dev requests, UI component searches, installing a selected community component, or generating a UI draft only after catalog search finds no suitable component.
---

# Use 21st.dev components

Reuse the official 21st.dev catalog before hand-writing a common UI component. Keep Freyja's design system, accessibility, restraint, and visual-verification contracts authoritative after adoption.

Run the pinned official CLI through Asgard:

```bash
asgard skills run 21st-cli-use <command> [args...]
```

## Workflow

1. Inspect the project's framework, `components.json`, existing UI components, tokens, and installed dependencies.
2. Search with a specific visual and behavioral query. Prefer `--json` when comparing results.
3. Inspect the chosen result and its dependencies. Do not assume community code fits the project's license, accessibility, or style requirements.
4. Print the install command first. Install only when it will not overwrite an existing component or add a redundant motion/UI engine.
5. Adapt the copied source to project tokens and conventions, then test keyboard use, reduced motion, responsive states, and representative screenshots.

## Commands

```bash
# Metadata search is the default first step.
asgard skills run 21st-cli-use search "animated pricing table" --limit 8 --json
asgard skills run 21st-cli-use search "dashboard chart" --type c --free --json

# Free logo and theme lookup.
asgard skills run 21st-cli-use logo "linear" --limit 5 --json
asgard skills run 21st-cli-use search "neutral dark" --type theme --json
asgard skills run 21st-cli-use theme <theme-id> --json

# Inspect or install a selected component.
asgard skills run 21st-cli-use get <component-id> --json
asgard skills run 21st-cli-use add <author>/<slug> --print
asgard skills run 21st-cli-use add <author>/<slug>

# Generate only when catalog search has no close fit; generation can consume quota.
asgard skills run 21st-cli-use usage
asgard skills run 21st-cli-use generate "<clear UI brief>" --json
```

The official CLI reads `API_KEY_21ST`/`TWENTYFIRST_TOKEN` or its mode-0600 credential at `~/.config/21st/auth.json`. Never print, commit, place in a URL, or copy that value into generated component code.

## Boundaries

- Search and inspect before `add`; do not use overwrite flags implicitly.
- Treat `get`, `add`, and AI generation as metered operations and avoid repeated speculative calls.
- Do not publish, edit, delete, or change visibility on 21st.dev without an explicit user request.
- Prefer the project's current CSS or Motion dependency. A catalog component is source material, not permission to mix animation engines.
