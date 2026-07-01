#!/usr/bin/env bash
# Runs INSIDE the bare sandbox (CUS-108 Path B). The base has no node/bun/python/uv; install.sh
# bootstraps uv + a standalone CPython 3.14 and installs asgard as a uv tool — proving zero-runtime.
set -eu

echo "── runtime present? (node/bun should be absent on the bare base) ──"
for t in node bun; do
  if command -v "$t" >/dev/null 2>&1; then echo "  ✘ $t PRESENT — not a clean room"; exit 1; else echo "  ✓ $t absent"; fi
done

echo "── install (uv bootstrap + uv tool install from the local checkout) ──"
cd /home/asgard/src && bash install.sh
export PATH="/home/asgard/.local/bin:$PATH"

echo "── verify CLI ──"
command -v asgard >/dev/null || { echo "FAIL: asgard not on PATH"; exit 1; }
ver="$(asgard --version)"
echo "$ver" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "FAIL: --version => '$ver'"; exit 1; }
[ "$ver" != "0.0.0" ] || { echo "FAIL: version 0.0.0 (not embedded)"; exit 1; }
asgard --help | grep -q "make anything, your way" || { echo "FAIL: --help"; exit 1; }
asgard --help | grep -q "doctor" || { echo "FAIL: --help command list"; exit 1; }
asgard run | grep -qi "planned" || { echo "FAIL: planned command"; exit 1; }
asgard doctor --json | grep -q '"ok": true' || { echo "FAIL: doctor --json ok"; exit 1; }
if asgard bogus >/dev/null 2>&1; then echo "FAIL: unknown cmd should be nonzero"; exit 1; fi

echo "SANDBOX PASS — uv self-contained install verified on bare base (v$ver)"
