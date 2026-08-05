#!/usr/bin/env bash
# Conductor 대조 배치 — 3아암 × 3과업 × N반복, 동시 3세션.
# usage: batch.sh [reps]   (기본 2)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
export RUNS="${RUNS:-$ROOT/workspace/bench-conductor/runs}"
export RESULTS="${RESULTS:-$ROOT/workspace/bench-conductor/results}"
REPS="${1:-2}"
JOBS="${JOBS:-3}"

mkdir -p "$RUNS" "$RESULTS"
manifest="$RUNS/../manifest.txt"
: > "$manifest"
for rep in $(seq 1 "$REPS"); do
  for task in t6-pagination t5-dates t3-config; do
    for arm in plain reflect asgard; do
      echo "$task $arm $rep" >> "$manifest"
    done
  done
done

echo "[batch] $(wc -l < "$manifest") sessions, jobs=$JOBS"
xargs -P "$JOBS" -L 1 uv run --project "$ROOT" python "$HERE/live_run.py" < "$manifest"
echo "[batch] done"
