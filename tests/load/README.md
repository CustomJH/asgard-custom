# Project memory load harness (k6, Docker)

프로젝트 메모리 backend 는 팀이 공유하는 원격 서비스다. 한 사람의 지연은 doctor 가 보지만,
**여러 사람이 동시에 회수할 때 무슨 일이 나는지**는 재 보지 않으면 알 수 없다. 그 자리를 여기서 잰다.

회수 경로만 잰다. 등록은 사람이 승인할 때 한 번이고, 회수는 대화마다 돈다.

## 실행

```bash
docker run --rm -i --add-host=host.docker.internal:host-gateway \
  -e HS_BASE=http://host.docker.internal:18890 -e HS_BANK=<bank> \
  -v "$PWD/tests/load:/scripts" grafana/k6:latest run /scripts/saturate.js
```

`recall.js` 는 1→50 VU 램프(임계값 판정), `saturate.js` 는 1·2·5·10·20 VU 계단(포화점 탐색).
빈 뱅크에 걸면 의미가 없다 — `asgard memory project-sync --all --inventory` 로 채운 뱅크를 쓴다.

## 실측 (Hindsight 0.8.3 · Docker · M-series · 2026-07-28)

| 동시 VU | p95 | 평균 |
|---|---|---|
| 1 | 0.51s | 0.48s |
| 2 | 0.76s | 0.71s |
| 5 | 1.80s | 1.45s |
| 10 | 3.47s | 2.82s |
| 20 | 6.22s | 5.52s |
| 50 | 14.98s | 6.82s |

처리량은 VU 와 무관하게 **~2.9 req/s 로 평평하다** — 지연 증가는 전부 큐 대기다.
요청 모양은 원인이 아니다: budget(low/mid)·include(chunks/entities)·max_tokens 를 바꿔도
단일 요청은 0.47~0.58s 로 같았다.

읽는 법: 기본 timeout 15s 기준으로 **인스턴스 하나가 동시 회수 ~20건까지** 여유가 있다.
그 위로는 타임아웃이 난다 — 팀이 더 크면 인스턴스를 늘리거나 `asgard memory connect --timeout` 을 올린다.
