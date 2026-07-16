#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")"

for cmd in docker curl; do
  command -v "$cmd" >/dev/null || { echo "missing command: $cmd" >&2; exit 1; }
done
docker compose version >/dev/null

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null; then
  uv_installer=$(mktemp)
  trap 'rm -f "$uv_installer"' EXIT
  curl -LsSf --max-time 60 https://astral.sh/uv/install.sh -o "$uv_installer"
  UV_INSTALL_DIR="$HOME/.local/bin" sh "$uv_installer"
  rm -f "$uv_installer"
  trap - EXIT
fi
uv python install 3.14
uv sync --project .
# shellcheck disable=SC1091
source ./runtime.sh

if [[ ! -f .env ]]; then
  cp .env.example .env
  run_python - <<'PY'
from pathlib import Path
import secrets
p = Path('.env')
text = p.read_text()
text = text.replace('COGNEE_DEFAULT_USER_PASSWORD=GENERATE_ON_INSTALL', f'COGNEE_DEFAULT_USER_PASSWORD={secrets.token_urlsafe(32)}')
text = text.replace('COGNEE_VERIFICATION_SECRET=GENERATE_ON_INSTALL', f'COGNEE_VERIFICATION_SECRET={secrets.token_urlsafe(48)}')
text = text.replace('COGNEE_RESET_SECRET=GENERATE_ON_INSTALL', f'COGNEE_RESET_SECRET={secrets.token_urlsafe(48)}')
p.write_text(text)
PY
  chmod 600 .env
  echo "generated .env with private Cognee credentials (values not printed)"
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

mkdir -p data models backups
chmod 700 data models backups

if [[ "${COGNEE_LLM_PROVIDER:-ollama}" == "ollama" ]]; then
  ollama_url="http://127.0.0.1:${COGNEE_OLLAMA_PORT:-11434}/api/tags"
  if curl -fsS --max-time 10 "$ollama_url" | run_python -c 'import json,os,sys; names={m.get("name") for m in json.load(sys.stdin).get("models",[])}; wanted=os.environ["COGNEE_OLLAMA_MODEL"]; raise SystemExit(0 if wanted in names else 1)'; then
    echo "optional LLM preflight: host Ollama model is available"
  elif [[ "${COGNEE_LLM_REQUIRED:-false}" == "true" ]]; then
    echo "required host Ollama model is unavailable: ${COGNEE_OLLAMA_MODEL}" >&2
    exit 1
  else
    echo "warning: optional host Ollama model is unavailable; starting Cognee in degraded retrieval-only readiness" >&2
  fi
fi

docker compose config >/dev/null
docker compose build --pull
docker compose up -d

base_url="http://127.0.0.1:${COGNEE_PORT:-8000}"
for _ in $(seq 1 120); do
  if curl -fsS --max-time 5 "$base_url/health" >/dev/null 2>&1; then
    echo "Cognee ready: $base_url"
    ./doctor.sh
    exit 0
  fi
  sleep 5
done

echo "Cognee failed readiness deadline" >&2
docker compose ps >&2
docker compose logs --tail=200 cognee >&2
exit 1
