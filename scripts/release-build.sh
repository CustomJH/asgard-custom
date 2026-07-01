#!/usr/bin/env bash
# Cross-compile per-OS asgard binaries into an output dir (default: dist/).
# Bun cross-compiles all targets from any single host — run locally or in CI.
#   scripts/release-build.sh [outdir]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
OUT="${1:-dist}"
mkdir -p "$OUT"

# bun --compile target → release asset name (must match install.sh detect_asset)
targets=(
  "bun-linux-x64:asgard-linux-x64"
  "bun-linux-arm64:asgard-linux-arm64"
  "bun-darwin-x64:asgard-darwin-x64"
  "bun-darwin-arm64:asgard-darwin-arm64"
  "bun-windows-x64:asgard-windows-x64.exe"
)

for entry in "${targets[@]}"; do
  target="${entry%%:*}"
  asset="${entry##*:}"
  echo "→ $target → $OUT/$asset"
  bun build src/cli.ts --compile --target="$target" --outfile "$OUT/$asset"
done

# SHA256SUMS — install.sh verifies the downloaded binary against this (fail-closed on mismatch).
( cd "$OUT" && { command -v sha256sum >/dev/null 2>&1 && sha256sum asgard-* || shasum -a 256 asgard-*; } > SHA256SUMS )
echo "wrote $OUT/SHA256SUMS"

echo
echo "built into $OUT/:"
ls -lh "$OUT" | awk 'NR>1 {print "  " $5 "  " $9}'
