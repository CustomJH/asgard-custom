#!/usr/bin/env bash
# asgard-common-memory 백업 — pg_dump 전체 덤프를 backups/ 에 남긴다 (git 밖).
# 기억은 힌트지만 팀 자산이다 — cron 등으로 주기 실행 권장. 복구는 README §복구.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backups
out="backups/hindsight-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T postgres pg_dump -U hindsight hindsight | gzip > "$out"
echo "backup → $out ($(du -h "$out" | cut -f1))"
# 보존 정책: 최근 14개만 유지
ls -t backups/hindsight-*.sql.gz 2>/dev/null | tail -n +15 | xargs rm -f 2>/dev/null || true
