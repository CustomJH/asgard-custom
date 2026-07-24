# Fjadrhamr source recipes — fetch and capture, per source

Load this file only when actually acquiring an example (`asgard skills show asgard-freyja-fjadrhamr --resource SOURCES.md`). The umbrella SKILL.md carries the workflow and rules; this file carries the exact commands.

## Catalog files (bundled, offline)

- `catalog-magicui.json` — name, title, description (77)
- `catalog-reactbits.json` — name, title, description; each has JS/TS × CSS/Tailwind variants (139)
- `catalog-animata.json` — name, category, path; 23 categories: background, text, card, button, hero, widget, … (214)
- `catalog-aceternity.json` — name; descriptive slugs like `background-beams`, `sparkles`, `spotlight` (109)
- `catalog-motionprimitives.json` — name, path; core primitives: glow-effect, border-trail, infinite-slider, magnetic, dock, … (33)
- `catalog-21st.json` — author, name (5,592 entries, ~300KB: do NOT read whole — `grep -i '<keyword>'`; slugs are descriptive, e.g. `hero-section-5`, `shader-dither`, `text-loop`)
- `catalog-originkit.json` — name, category, description, tags, plus ready `poster`/`video` capture URLs (100; 48 with rich descriptions from the official index)
- `catalog-uiverse.json` — author, name, category, path (3,802 entries, ~490KB: do NOT read whole — grep by category; slugs are random pet-names, so match by category first, then fetch a few and judge)

To refresh a catalog, re-fetch the registry (`https://magicui.design/r/registry.json`, `https://reactbits.dev/r/registry.json`, `https://ui.aceternity.com/registry/index.json`) or the GitHub repo tree (codse/animata, ibelick/motion-primitives, uiverse-io/galaxy).

## Fetch recipes (free sources, unlimited)

**Magic UI** — source is inline in the registry item:
```bash
curl -s "https://magicui.design/r/marquee.json" | python3 -c "import json,sys; d=json.load(sys.stdin); [print('===',f['path'],'==='+chr(10)+f['content']) for f in d['files']]"
```

**ReactBits** — pick the variant (`TS-TW` = TypeScript + Tailwind is the usual default):
```bash
curl -s "https://reactbits.dev/r/ClickSpark-TS-TW.json" | python3 -c "import json,sys; d=json.load(sys.stdin); [print('===',f['path'],'==='+chr(10)+f['content']) for f in d['files']]"
```

**Animata** — use the `path` from the catalog against GitHub raw:
```bash
curl -s "https://raw.githubusercontent.com/codse/animata/main/animata/background/blurry-blob.tsx"
```

**Aceternity UI** — shadcn registry (registered in the official shadcn directory as `@aceternity`); source inline:
```bash
curl -s "https://ui.aceternity.com/registry/background-beams.json" | python3 -c "import json,sys; d=json.load(sys.stdin); [print('===',f['path'],'==='+chr(10)+f['content']) for f in d['files']]"
```
A 401/HTML response means that item is pro-gated — skip it and pick another candidate; do not attempt to bypass.

**Motion Primitives** — use the `path` from the catalog against GitHub raw (free library only):
```bash
curl -s "https://raw.githubusercontent.com/ibelick/motion-primitives/main/components/core/glow-effect.tsx"
```
Do not target `pro.motion-primitives.com` — it is a paid, gated product with no public registry.

**Uiverse** — use the `path` from the catalog against GitHub raw; the first line is a comment with author + search tags:
```bash
curl -s "https://raw.githubusercontent.com/uiverse-io/galaxy/main/loaders/0xnihilism_brown-puma-30.html"
```
Curation rule (UGC quality varies widely): never adopt the first hit. Fetch 3+ candidates from the matching category, compare, and pass the pick through Freyja's restraint/slop gates before adapting. Attribution is appreciated (not required): credit the author from the file's first-line comment. Do not crawl uiverse.io itself (Cloudflare-guarded and unnecessary).

## Key-gated sources

**21st.dev** — only fetch when `TWENTYFIRST_API_KEY` is set:
```bash
curl -s "https://21st.dev/r/{author}/{name}" -H "x-api-key: $TWENTYFIRST_API_KEY"
```
Without a key the server returns `403 {"error":"Authentication required"}`. Never bypass the gate and never scrape pages for source (none is embedded).

**Originkit** — official MCP fetch when `ORIGINKIT_API_KEY` is set (free key at originkit.dev → Settings → API Integration; **10 fetches/day**, so spend the budget only on a confirmed match):
```bash
curl -s -X POST "https://mcp.originkit.dev/vellumai" \
  -H "Authorization: Bearer $ORIGINKIT_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_component","arguments":{"name":"<component-name>","stack":"react","styling":"tailwind","typescript":true}}}'
```

## No key → capture protocol (visual reference, original reimplementation)

Capturing what a public preview *looks like* is fair reference use; taking gated code is not.

1. **21st.dev** — the public browse page HTML embeds CDN media per component (static `preview.*.png` + motion demo `video.*.mp4` on `cdn.21st.dev`):
   ```bash
   curl -sL "https://21st.dev/@{author}/components/{name}" | grep -oE 'https://cdn\.21st\.dev/[^"\\ ]+\.(png|mp4|webm)' | sort -u
   ```
   **Originkit** — the catalog already carries direct `poster`/`video` URLs (`https://cdn.originkit.dev/components/{name}-gallery-poster.jpg`, `{name}-gallery-720.mp4`).
2. Download the media locally. Read the PNG directly; step through the MP4 in a browser tab (or `ffmpeg -vf fps=2` when available). If media is missing, render the public browse page in a browser tool and screenshot rest/mid-animation/hover states.
3. Write a motion log: layers, what moves, direction, rough period/easing, blend/occlusion behavior, palette sampled from the capture.
4. Reimplement FROM THE CAPTURE ONLY — original vanilla JS/canvas/CSS that reproduces the observed feel. Never attempt to recover, decompile, or transcribe gated source; never embed the downloaded media in deliverables (local reference only); never copy page text/branding.
5. Credit as: `Visually inspired by {source} "{name}" (public preview media; independently reimplemented — no source code accessed)`.
6. If the preview cannot be captured, fall back to the free sources.

## Adaptation notes

Note each registry item's `dependencies` / `registryDependencies` and local imports (e.g. `@/lib/utils` `cn`) so the adaptation plan accounts for them.
