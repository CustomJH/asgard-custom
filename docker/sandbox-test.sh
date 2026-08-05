#!/usr/bin/env bash
# Runs INSIDE the bare sandbox. The base has no node/bun/python/uv; install.sh
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
# `ok` 는 이제 **모든** 항목이 초록일 때만 참이다 (0=전부 초록 · 1=못 쓴다 · 2=손볼 것 있음).
# 맨 베이스 컨테이너에는 프로젝트 배선도 설계 엔진 런타임도 없어 그 항목들이 늘 빨갛다 —
# 여기서 묻는 것은 "설치가 섰는가"이므로 `blocking_ok` 를 본다.
asgard doctor --json | grep -q '"blocking_ok": true' || { echo "FAIL: doctor --json blocking_ok"; exit 1; }
if asgard bogus >/dev/null 2>&1; then echo "FAIL: unknown cmd should be nonzero"; exit 1; fi

echo "SANDBOX PASS — uv self-contained install verified on bare base (v$ver)"
