#!/usr/bin/env bash
# Asgard DEV sandbox — persistent, batteries-included (node24 + bun + git + build tools + sudo).
# Install & test Asgard alongside Claude Code / Codex inside it (you install those yourself).
#   docker/devbox.sh up       # build + start (repo mounted at ~/asgard)
#   docker/devbox.sh shell    # open a shell inside
#   docker/devbox.sh down     # stop + remove
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMG="asgard-devbox:latest"
NAME="asgard-devbox"

case "${1:-up}" in
  up)
    docker build -f "$REPO/docker/devbox.Dockerfile" -t "$IMG" "$REPO/docker"
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -dit --name "$NAME" -v "$REPO":/home/dev/asgard "$IMG" >/dev/null
    echo "devbox up: $NAME  (repo mounted at ~/asgard)"
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
