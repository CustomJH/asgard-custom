# Design hook manifests

These two files are **reference templates, not something Asgard installs.**

Upstream shipped them with the paths of an npm-installed skill, which do not
exist here: the engine travels inside the Asgard wheel, not under the project's
`.claude/skills/`. Both now name the engine through `${FREYJA2_ENGINE}` instead
of a path that resolves to nothing.

- `plugin-hooks.json` — a Claude Code *plugin* hooks block.
- `claude-settings.json` — the same two hooks as a `settings.json` fragment,
  guarded so a machine without the engine is a no-op instead of an error.

## Wiring one by hand

Resolve the engine directory, then export it where the agent will run:

```sh
asgard doctor --json | python3 -c \
  "import json,sys;print(json.load(sys.stdin)['freyja2_engine'])"
```

```sh
export FREYJA2_ENGINE=/…/asgard/assets/skill_plugins/freyja2/skills/asgard-freyja2/engine
```

Then merge the fragment you want into the host's hook configuration. The path
changes when Asgard updates, so re-export it after `asgard update` rather than
hardcoding a version-specific path.

## Not wiring one

That is the supported default, and the engine already accounts for it: with no
hook dispatching, `context.mjs` emits one `MANUAL_DETECTOR_REQUIRED` directive at
boot asking for a single detector run over the changed files before finishing.
The rules are identical either way — the hook only changes *when* they run.
