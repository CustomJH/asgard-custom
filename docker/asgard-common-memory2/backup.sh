#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./runtime.sh
[[ -f .env ]] || { echo "missing .env" >&2; exit 1; }
mkdir -p backups
chmod 700 backups
out="backups/cognee-$(date +%Y%m%d-%H%M%S).tar.gz"

# SQLite, LanceDB, and Ladybug/Kuzu are a coordinated binary projection. Stop
# the writer to take a consistent filesystem snapshot.
docker compose stop cognee
restart_needed=true
trap 'if [[ "${restart_needed:-false}" == true ]]; then docker compose start cognee >/dev/null; fi' EXIT

tar -czf "$out" data
chmod 600 "$out"
docker compose start cognee >/dev/null
restart_needed=false

run_python - "$out" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
print(f"backup: {p} ({p.stat().st_size} bytes)")
PY

run_python - <<'PY'
from pathlib import Path
files=sorted(Path('backups').glob('cognee-*.tar.gz'), key=lambda p:p.stat().st_mtime, reverse=True)
for p in files[14:]: p.unlink()
PY
