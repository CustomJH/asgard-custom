#!/usr/bin/env bash
# Regenerate static-parser.mjs — the detector's static-HTML parsing stack.
#
# The engine imports htmlparser2 / css-select / css-tree / domutils by bare
# specifier and, when none resolves, falls back to this bundle. Asgard ships the
# engine as Python package data with no node_modules beside it, so without the
# bundle the static path never runs and the detector silently degrades to
# regex-only. tests/test_freyja2_static_parser.py holds that line.
#
# Pin the versions to whatever the upstream engine declares (ref/impeccable
# package.json) so the vendored copy tracks the engine it was cut from.
#
# Usage: ./rebuild.sh [work-dir]   (needs bun; work-dir defaults to a temp dir)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="${1:-$(mktemp -d)}"
mkdir -p "$work"
cd "$work"

# css-tree's ESM build reads its data through createRequire(import.meta.url),
# which no bundler can follow; its CJS build requires the JSON statically, so
# bundling that entry inlines mdn-data instead of leaving a runtime lookup.
cat > package.json <<'JSON'
{
  "name": "freyja2-static-parser-bundle",
  "private": true,
  "dependencies": {
    "css-select": "^7.0.0",
    "css-tree": "^3.2.1",
    "domutils": "^4.0.2",
    "htmlparser2": "^12.0.0"
  }
}
JSON

cat > entry.mjs <<'JS'
export * as htmlparser2 from 'htmlparser2';
export * as cssSelect from 'css-select';
export * as domutils from 'domutils';
export { default as csstree } from './node_modules/css-tree/cjs/index.cjs';
JS

cat > banner.txt <<'TXT'
/**
 * Vendored static-HTML parser bundle for Freyja 2's detector.
 *
 * Bundles htmlparser2, css-select, css-tree and domutils — the four packages
 * `engines/static-html/detect-html.mjs` needs to build a real DOM and resolve
 * the CSS cascade. Upstream gets them as dependencies of its npm package;
 * Asgard ships this engine as Python package data with no node_modules beside
 * it, so every bare import threw and the detector fell back to regex-only,
 * losing the contrast, spacing and type-size rule sets with no warning.
 *
 * Generated — do not edit. Regenerate with ./rebuild.sh.
 * Upstream licenses are recorded in LICENSES.md beside this file.
 */
TXT

bun install --no-save >/dev/null
bun build entry.mjs --target=node --format=esm --banner "$(cat banner.txt)" \
  --outfile="$here/static-parser.mjs"

node -e "import('$here/static-parser.mjs').then(m => {
  const missing = ['htmlparser2','cssSelect','csstree','domutils'].filter(k => !m[k]);
  if (missing.length) { console.error('bundle is missing exports:', missing.join(', ')); process.exit(1); }
  if (typeof m.csstree.parse !== 'function') { console.error('css-tree data did not inline'); process.exit(1); }
  console.log('bundle ok');
})"

echo "Refresh LICENSES.md from $work/node_modules when a version changes."
