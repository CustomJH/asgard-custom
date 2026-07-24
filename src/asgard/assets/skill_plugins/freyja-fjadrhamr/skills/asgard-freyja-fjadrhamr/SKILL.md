---
name: asgard-freyja-fjadrhamr
description: "Freyja Fjadrhamr — the falcon cloak. Source working animated-component and micro-UI examples from 8 libraries (Magic UI, ReactBits, Animata, Aceternity UI, Motion Primitives, 21st.dev, Originkit, Uiverse; 10,066 components): browse the bundled catalogs, match the design need, fetch open source directly or capture-reimplement key-gated previews, and adapt everything under Freyja's design system and restraint gate."
---

# Fjadrhamr — Freyja's falcon cloak (motion-example hunting)

Eight catalogs — six with free unlimited source access (Magic UI 77 · ReactBits 139 · Animata 214 · Aceternity 109 · Motion Primitives 33 · Uiverse 3,802), two key-gated with a capture fallback (21st.dev 5,592 · Originkit 100). Use these as **example sources**: find a component matching the design need, obtain its real source (fetch) or its real look (capture protocol: public preview media → motion log → original reimplementation), and adapt it under Freyja's own tokens, accessibility, and restraint gate.

## Ground rules

- Examples are references, not deliverables. Adapt every fetched file to the project's stack, design tokens, and a11y gates — never ship verbatim. Keep a top-of-file attribution comment, e.g. `// Adapted from Magic UI "Marquee" (MIT) — magicui.design`.
- Licenses: most sources are MIT. **ReactBits carries a Commons Clause** — in-product use is fine, mass-mirroring/redistributing the library is not. Aceternity free items are site-served (pro items 401 → pick another). Never bypass a key gate; captured preview media stays local and is never embedded in deliverables.
- Uiverse is UGC — quality varies widely: never adopt the first hit; fetch 3+ candidates, compare, and pass the pick through the restraint/slop gates.

## Workflow

1. **Browse** — eight `catalog-*.json` files sit next to this skill. Small ones can be read whole; `catalog-21st.json` (~300KB) and `catalog-uiverse.json` (~490KB) must be searched with `grep`, never read whole. Shortlist 1–3 candidates and state which source, which component, and why each fits before acquiring anything.
2. **Acquire** — load the exact fetch/capture commands on demand:

       asgard skills show asgard-freyja-fjadrhamr --resource SOURCES.md

   Free sources fetch real code from public registries/GitHub raw. Key-gated sources fetch with `TWENTYFIRST_API_KEY` / `ORIGINKIT_API_KEY`, or fall back to the capture protocol in SOURCES.md.
3. **Report** — Match (source, component, why) / Acquisition (code or the exact blocker with raw error text, plus dependencies) / Adaptation plan (stack fit, token substitution, a11y, restraint gate; for ReactBits confirm in-product use).

Fjadrhamr is Freyja's falcon cloak: fly out, observe, bring the example home — and reforge it as your own.
