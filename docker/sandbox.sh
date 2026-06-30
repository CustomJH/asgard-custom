#!/usr/bin/env bash
# Asgard test sandbox — host runner. Build the image, then run the test in a fresh,
# ephemeral container (--rm: created then destroyed each run). Repeat freely.
#   docker/sandbox.sh            # build + run the clean-room test
#   docker/sandbox.sh shell      # drop into an interactive bare container
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMG="asgard-sandbox:latest"

docker build -f "$REPO/docker/Dockerfile" -t "$IMG" "$REPO"

if [ "${1:-}" = "shell" ]; then
  exec docker run --rm -it "$IMG" bash
fi
exec docker run --rm "$IMG"
