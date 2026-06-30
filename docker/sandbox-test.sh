#!/usr/bin/env bash
# Runs INSIDE the bare sandbox container. Installs asgard from the prebuilt binary
# (no node/bun/git present) and verifies the CLI — proving the install is self-contained.
set -euo pipefail

echo "── runtime present? (expect all absent on bare base) ──"
for t in node bun git; do
  if command -v "$t" >/dev/null 2>&1; then echo "  ✘ $t PRESENT — not a clean room"; exit 1; else echo "  ✓ $t absent"; fi
done

echo "── install (download path, file:// the prebuilt binary) ──"
export ASGARD_DOWNLOAD_URL="file:///home/asgard/prebuilt/asgard"
bash install.sh

echo "── verify CLI ──"
command -v asgard >/dev/null || { echo "FAIL: asgard not on PATH"; exit 1; }
ver="$(asgard --version)"; echo "$ver" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "FAIL: --version => '$ver'"; exit 1; }
[ "$ver" != "0.0.0" ] || { echo "FAIL: version 0.0.0 (not embedded)"; exit 1; }
asgard --help | grep -q "asgard — make anything, your way" || { echo "FAIL: --help"; exit 1; }
asgard --help | grep -q "doctor" || { echo "FAIL: --help command list"; exit 1; }
asgard setup | grep -qi "planned" || { echo "FAIL: planned command"; exit 1; }
asgard doctor
asgard doctor --json | grep -q '"ok": true' || { echo "FAIL: doctor --json ok"; exit 1; }
if asgard bogus >/dev/null 2>&1; then echo "FAIL: unknown cmd should be nonzero"; exit 1; fi

echo "SANDBOX PASS — self-contained install verified on bare base (v$ver)"
