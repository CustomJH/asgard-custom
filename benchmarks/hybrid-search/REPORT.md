# 하이브리드 검색 벤치 — 2경로 vs 3경로

- 페이지: **100** · 모델: `minishlab/potion-multilingual-128M` (256d, torch 무의존)
- off = lexical 2경로(FTS5 BM25 + 정본 스캔) · on = +시맨틱 3경로 RRF

## 검색 품질 (hit@k · MRR)

| 계층 | 모드 | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| direct | off | 1.00 | 1.00 | 1.00 | 1.000 |
| direct | on | 1.00 | 1.00 | 1.00 | 1.000 |
| paraphrase | off | 0.50 | 0.50 | 0.50 | 0.500 |
| paraphrase | on | 0.50 | 0.50 | 0.50 | 0.500 |
| crosslingual | off | 0.00 | 0.00 | 0.00 | 0.000 |
| crosslingual | on | 0.80 | 0.80 | 0.80 | 0.800 |

- **direct** = 두 모드 동일해야 정상(무회귀 대조군)
- **paraphrase / crosslingual** = off 는 원리상 회수 불가, on 의 이득 구간

## 지연 (query() 벽시계)

| 모드 | p50 | p95 | max |
|---|---|---|---|
| off | 5.59ms | 8.38ms | 13.16ms |
| on | 6.71ms | 7.37ms | 10.73ms |

