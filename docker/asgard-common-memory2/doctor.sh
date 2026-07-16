#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./runtime.sh
[[ -f .env ]] || { echo "missing .env; run ./install.sh" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source .env
set +a

base_url="http://127.0.0.1:${COGNEE_PORT:-8000}"
health_file=$(mktemp)
trap 'rm -f "$health_file"' EXIT
curl -fsS --max-time 10 "$base_url/health" > "$health_file"
run_python - "$health_file" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
print('health:', p)
PY

docker compose ps
container=$(docker compose ps -q cognee)
[[ -n "$container" ]] || { echo "Cognee container not found" >&2; exit 1; }
docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}' | run_python -c 'import sys; allowed=("LLM_PROVIDER=","LLM_MODEL=","LLM_ENDPOINT=","EMBEDDING_PROVIDER=","EMBEDDING_MODEL=","EMBEDDING_DIMENSIONS=","GRAPH_DATABASE_PROVIDER=","VECTOR_DB_PROVIDER=","ENABLE_BACKEND_ACCESS_CONTROL=","REQUIRE_AUTHENTICATION="); print("".join(line for line in sys.stdin if line.startswith(allowed)),end="")'

if docker compose exec -T cognee python /opt/asgard/provider-readiness.py; then
  echo "llm_readiness: available"
else
  echo "llm_readiness: unavailable or unverified (API remains usable; cognify/graph is degraded)"
  [[ "${COGNEE_LLM_REQUIRED:-false}" == "true" ]] && exit 1
fi
