#!/usr/bin/env bash
# Asgard DEV box — persistent, batteries-included (Python 3.14 via uv + node + vim/ll/rg/fzf/git + sudo).
# Install & test Asgard alongside Claude Code / Codex / cursor-agent inside it.
#   docker/devbox.sh up       # build + start (repo mounted at ~/asgard)
#   docker/devbox.sh shell    # open a shell inside  →  then: asgard-install
#   docker/devbox.sh down     # stop + remove
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMG="asgard-devbox:latest"
NAME="asgard-devbox"

case "${1:-up}" in
  up)
    docker build -f "$REPO/docker/devbox.Dockerfile" -t "$IMG" "$REPO/docker"
    mkdir -p "$REPO/workspace"
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -dit --name "$NAME" \
      -v "$REPO":/home/dev/asgard \
      -v "$REPO/workspace":/home/dev/work \
      "$IMG" >/dev/null
    echo "devbox up: $NAME"
    echo "  repo       → ~/asgard"
    echo "  workspace  → ~/work   (host: ./workspace — shared both ways, gitignored)"
    echo "  enter:  docker/devbox.sh shell"
    ;;
  shell)
    exec docker exec -it "$NAME" bash
    ;;
  down)
    docker rm -f "$NAME" >/dev/null && echo "devbox down: $NAME removed"
    ;;
  *)
    echo "usage: devbox.sh {up|shell|down}" >&2; exit 2
    ;;
esac
