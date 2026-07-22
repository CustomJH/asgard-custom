# Attribution — tving Reference Capture

Captured: **2026-05-15** via `vanadis:add-reference` (CREATE mode) + `browser-harness` CDP :9222

## Sources

| File | Source URL | Captured | Notes |
|---|---|---|---|
| `tokens.json` | https://www.tving.com (→ /onboarding) | 2026-05-15 | Computed styles via browser-harness CDP, factual analysis |
| `structure.json` | https://www.tving.com (→ /onboarding) | 2026-05-15 | Observable composition facts (CSS vars, layout geometry, category taxonomy) |
| `fonts.json` | https://www.tving.com | 2026-05-15 | Computed `font-family` first-token + known-font registry match |
| `.live-inspect-proof.json` | https://www.tving.com | 2026-05-15 | 13 raw_samples (≥5 floor), 114 CSS custom properties captured |
| `screenshots/hero-desktop.png` | https://www.tving.com (1280×713) | 2026-05-15 | Reference for design alignment — onboarding surface (unauth) |

## Skipped (URL recorded for manual review)

- Authenticated browse / VOD detail / live player surfaces — gated behind login, not inspected in this pass. Flagged for UPDATE.
- Content thumbnail / poster art — copyrighted by respective rights holders (studios, distributors). NOT downloaded.
- Marketing video assets — skipped per skill policy.

## Tier-1 Official Design System

**Result: negative (documented).**

Probed (all DNS no-resolve or 404 as of 2026-05-15):
- `design.tving.com` → DNS 000
- `brand.tving.com` → DNS 000
- `tech.tving.com` → DNS 000
- `tving.com/design` → 404
- GitHub `tving` org → 1 repo only (`tving.github.io`, no DS content)
- CJ ENM corporate channels — no public TVING-branded DS portal

The production CSS `:root` token set (114 custom properties, captured via CDP) is the closest authoritative public artifact and was extracted directly.

## Tier-2 Indexes

- `getdesign.md/q/tving` → 404
- `styles.refero.design/?q=tving` → 200 but no result cards

Consistent with the systemic Korean-coverage gap.

## Rights

These materials are owned by **CJ ENM** (TVING Inc.) and its respective
rights holders. Captured under fair-use principles for the purpose of
design analysis and development reference. See `LICENSE-NOTE.md` for
usage boundaries.

## Refresh

Rerun `vanadis:add-reference tving` to recapture. Tokens reflect the live
site at capture time and may drift as the brand evolves.
