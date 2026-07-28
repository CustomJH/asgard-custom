# Vendored upstream — text-to-cad

Source: `https://github.com/earthtojake/text-to-cad`
Revision: `fdbb4b4fb62d95ae298cfe9a46fdc7092bdaf423` (2026-07-10, "Publish 0.3.9 from develop to main")
License: MIT — see `LICENSE` here and `../../../../NOTICE` at the plugin root.

This tree is a **vendored snapshot, not a fork**. Freyja's own doctrine lives in
`engine/reference/`; this directory holds the upstream runtime it calls. Keep the
two separated so a future re-sync is a directory replace plus a re-application of
the deviation list below.

## What was kept

All eleven upstream skills, plus the four shared runtime packages:

| Path | What it is |
|---|---|
| `packages/cadpy/` | STEP generation, selector refs, topology, assembly helper, measure/align/frame/diff, GLB/STL/3MF export |
| `packages/cadpy_metadata/` | generator contract shared by the URDF/SRDF/SDF skills |
| `packages/cadjs/` | render/viewer runtime (three.js) |
| `packages/implicitjs/` | implicit-CAD (GLSL SDF) runtime, mesher, exporters |
| `skills/cad/` | `step` · `inspect` · `snapshot` CLIs and the CAD reference set |
| `skills/cad-viewer/` | local review server (`backend/server.mjs` is a self-contained bundle) + prebuilt `dist/` |
| `skills/dxf/` · `skills/gcode/` · `skills/sendcutsend/` · `skills/bambu-labs/` | 2D drawings, slicing, fabrication preflight, print jobs |
| `skills/step-parts/` | purchasable-component catalog client |
| `skills/implicit-cad/` | browser-native SDF modelling |
| `skills/urdf/` · `skills/srdf/` · `skills/sdf/` | robot description and simulation model generation |

## Deviations from upstream

Every deviation is mechanical and listed here. Nothing else was edited.

### 1. Deduplicated runtime packages

Upstream ships a byte-identical copy of `cadpy` inside `skills/cad`, `skills/dxf`,
and `skills/cad-viewer` (and of `cadpy_metadata` inside the three robot skills, and
of `implicitjs` inside `skills/implicit-cad`). Verified identical by checksum, so
the per-skill copies were dropped and the single `packages/` copy is shared.

Consequence: five copies of `cadpy` collapse to one, and the tree drops from
roughly 20 MB to 9.5 MB.

The Python CLIs were unaffected — they resolve `cadpy` as an installed package and
their `sys.path` hints for the removed directory are inert. `cad-viewer`'s
`server.mjs` already walks parent directories looking for `packages/cadpy/src`, so
it finds the shared copy on its own.

Four files did need repointing, because they hard-coded the per-skill path:

- `skills/implicit-cad/scripts/export.mjs` — resolves the shared `packages/implicitjs`
- `skills/implicit-cad/scripts/snapshot.mjs` — same
- `skills/implicit-cad/scripts/lib/implicit-cad.mjs` — schema import
- `skills/implicit-cad/SKILL.md` — the sentence naming the schema's location

Each carries an `Asgard vendoring:` comment at the edit site.

### 2. Repointed `requirements.txt`

Six files pointed at the now-removed per-skill package directories and were
rewritten to the shared `packages/` copy: `cad`, `dxf`, `cad-viewer`,
`cad-viewer/scripts/viewer`, `urdf`, `srdf`, `sdf`.

In practice Asgard does not use these files — the documented invocation is
`uv run --with <pkg path>`, which needs no editable install. They are corrected so
the upstream instructions are not left pointing at nothing.

### 3. Dropped JavaScript source maps

All `*.map` files were excluded (about 12 MB, nearly all of it `cad-viewer/dist`).
They are debugging aids for upstream development and are not read at runtime.
Re-sync from upstream if you need to debug the bundled viewer.

## Known upstream gaps — do not report these as Asgard regressions

- **`cad-viewer` has no `agent:start`, and its documented flags do not exist.**
  Its `SKILL.md` documents `npm --prefix scripts/viewer run agent:start -- --dir <root>`,
  but the packaged bundle ships neither that npm script nor
  `scripts/start-agent-viewer.mjs` — the launcher lives only in the upstream
  development tree, and it was the launcher that owned `--dir` and port selection.
  Passing `--dir` to the packaged `backend/server.mjs` is silently ignored (the
  server roots itself at the skill directory); `--root-dir` exits with
  `--root-dir has been removed; pass ?dir= in the Viewer URL.`

  Measured working invocation:

  ```bash
  node backend/server.mjs --host 127.0.0.1 --port 4178
  # then address artifacts by absolute directory in the query string:
  #   http://127.0.0.1:4178/?dir=<absolute model dir>&file=<path relative to dir>
  ```

  `engine/reference/lane-viewer.md` carries this. The gap is upstream's, present
  before vendoring.

## Re-syncing

1. Clone upstream at the new revision with `GIT_LFS_SKIP_SMUDGE=1`.
2. `rsync` `packages/` and `skills/` in, excluding `scripts/packages/`,
   `scripts/viewer/packages/`, `*.map`, `__pycache__`, `node_modules`.
3. Re-apply deviations 1 and 2 — they are four path edits and six one-line files.
4. Re-run `tests/test_freyja_cad.py`, which checksums the shared packages against
   the per-skill copies' absence and asserts the repointed paths resolve.
5. Update the revision at the top of this file.
