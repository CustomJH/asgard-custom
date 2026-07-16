#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[[ $# -eq 1 ]] || { echo "usage: $0 backups/cognee-YYYYmmdd-HHMMSS.tar.gz" >&2; exit 2; }
archive=$1
[[ -f "$archive" ]] || { echo "backup not found: $archive" >&2; exit 1; }
case "$archive" in backups/cognee-*.tar.gz) ;; *) echo "refusing archive outside backups/ naming policy" >&2; exit 1;; esac

stamp=$(date +%Y%m%d-%H%M%S)
docker compose stop cognee
if [[ -d data ]]; then mv data "data.pre-restore-$stamp"; fi
mkdir -p data
if ! tar -xzf "$archive"; then
  rm -rf data
  if [[ -d "data.pre-restore-$stamp" ]]; then mv "data.pre-restore-$stamp" data; fi
  docker compose start cognee
  exit 1
fi
docker compose start cognee

echo "restored $archive; previous data retained at data.pre-restore-$stamp"
