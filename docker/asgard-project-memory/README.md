# asgard-project-memory — 2차 메모리(프로젝트 메모리) Hindsight 서버

프로젝트 단위 공유 메모리 서버. **DB 하나에 여러 사용자가 bank(=프로젝트) 단위로 조회·기록**한다.
Asgard 메모리의 2차 계층 인프라 (1차 개인 위키는 각자 로컬 `~/.asgard/memory/`).
구 `docker/asgard-common-memory`(Hindsight)와 `asgard-common-memory2`(Cognee 실험)를
이 폴더 하나로 통합했다 (2026-07-23 — 이전 구성은 git 이력에 있음).

```
사용자들 ──REST/MCP──▶ hindsight (:8888 API · :9999 UI)
                          │ retain = LLM 추출(기본 ollama) · recall = TEMPR, LLM 0
                          │ 관찰 통합(백그라운드) · Reflect(질의 시)
                          ▼
                      postgres (pgvector, 컨테이너 내부 전용)
```

## 기본 구성 (2026-07-23 확정)

| 항목 | 기본값 | 근거 |
|---|---|---|
| MCP 도구 | **활성** — single-bank `/mcp/{bank_id}/` (0.8.3 실측 29 tools) | retain·recall·reflect·mental model·directive·document 를 복합적으로 쓰는 것이 2차 메모리의 존재 이유 |
| bank 생성/열람(create_bank·list_banks·get_bank_stats) | **MCP 미노출** = 관리자 전용 | 이 3종은 multi-bank `/mcp/` 마운트에만 있다. 클라이언트를 single-bank 로만 붙이면 구조적으로 차단 — 별도 설정 불필요·불변경 |
| 관찰(observation) | **활성** | LLM 연결(기본 = 내부망 OpenAI 호환 게이트웨이, `.env` 설정)이면 retain 후 백그라운드 관찰 통합이 자동 동작 |
| Reflect | **활성** | 동일 — LLM 연결로 활성. `none` 이면 HTTP 400 |
| mission 3종 (retain / observations / reflect) | **전부 빈칸** | Asgard 어댑터가 이미 증류된 record 를 쓰기 때문에 서버측 조향은 추출 왜곡 위험만 추가. 소형 모델(qwen3:8b)에 프롬프트 복잡도를 더하지 않는다. 필요해지면 retain 은 `.env` 의 `HINDSIGHT_RETAIN_MISSION`, observations/reflect 는 bank 설정(`update_bank`·UI)으로 |
| disposition (skepticism·literalism·empathy) | Hindsight 기본값 유지 | 조정 근거 없음 — 빈 손대지 않음 |
| 산출 언어 (`HINDSIGHT_API_LLM_OUTPUT_LANGUAGE`) | **빈칸** | 이 값은 "산출 언어 선택"이 아니라 **"모든 원문을 이 언어로 번역하라"** 를 프롬프트에 붙이는 스위치다. 26-07-28 실측: Korean 고정이면 영어 규격서가 한국어로 번역돼 앉고, English 고정이면 한국어 지식이 `박베타 → Park Beta` 로 앉는다(같은 사실이 두 언어로 중복 unit 이 되기까지 했다). 프로젝트 문서가 두 언어로 섞여 들어오는 한 어느 쪽으로 고정해도 절반이 번역본이 된다 — 비워서 원문을 지킨다. 사람이 읽는 표면의 언어는 Asgard 가 따로 만든다 |

> 이 표의 "산출 언어" 행은 원래 `Korean` 이었다. 26-07-28 실측으로 뒤집혔고,
> compose 는 그때 이미 빈칸으로 고쳤는데 **이 표만 12일 동안 옛 값을 말하고 있었다**.
> 설정 파일과 문서가 갈리면, 사람은 문서를 믿는다.

## 백엔드 제약 — 이 구성의 모든 상한이 여기서 나온다

LLM 은 내부망 LiteLLM 게이트웨이의 `wams-summary` 다 (26-07-29 실측):

| | 값 |
|---|---|
| 실모델 | `Qwen/Qwen3.5-35B-A3B-GPTQ-Int4` |
| **컨텍스트** | **`--max-model-len 16384`** |
| 게이트웨이 | `request_timeout 180s` · `num_retries 2` · `max_parallel_requests 7` · `rpm 60` |
| thinking | 게이트웨이가 `chat_template_kwargs.enable_thinking=false` 를 이미 붙인다 |

**16384 가 지배 제약이다.** Hindsight 의 토큰 상한 기본값은 전부 이보다 크게 잡혀 있어서,
그냥 두면 세 군데가 순서대로 터진다 — retain(기본 64000), consolidation(기본 **무제한**),
reflect 입력(기본 **100000**, 여섯 배). compose 는 각각 8192 / 4096 / 10000 으로 맞춰 둔다.
게이트웨이 모델을 더 긴 컨텍스트로 교체하면 **셋을 같이** 올려야 한다.

`reasoning_effort` 는 신경 쓰지 않아도 된다: Hindsight 는 모델명이 reasoning 계열로
판정될 때만 그 값을 보내고, `wams-summary` 는 해당하지 않는다. 다만 그 판정이 참이 되면
`max_completion_tokens` 가 **강제로 16000 이상**으로 올라가 16384 모델을 그대로 넘긴다 —
모델 별칭을 지을 때 reasoning 계열로 읽힐 이름은 피할 것.

## 기동

```bash
cd docker/asgard-project-memory
cp .env.example .env        # DB 비밀번호 필수. LLM 은 기본 게이트웨이(wams-summary) — 켜진 채로 출발
docker compose up -d
docker compose logs -f hindsight   # 첫 기동은 임베딩·리랭커 모델 다운로드로 수 분
```

`HINDSIGHT_DB_PASSWORD`는 PostgreSQL 접속 URL에도 들어가므로 URL-safe 문자(영문·숫자와
`-._~`)만 사용한다. 게이트웨이가 닿지 않는 환경이면 `.env` 의 폴백 블록으로 호스트
ollama(`ollama pull qwen3:8b`)를 쓰거나 `none`(chunk 저장 모드)으로 내려간다.

### 리랭커 실측 — 이 한 줄이 한국어 회수를 결정한다 (26-07-29)

실운영 뱅크(`asgard-custom-project`, 48 fact + 83 observation)를 그대로 복제해 같은 질의
20개(한국어 14·영어 6)를 던졌다. **매 실험에서 바뀐 변수는 리랭커 하나뿐**이다.

| 리랭커 | 전체 hit@1 | **한국어 hit@1** | 한국어 MRR | p50 지연 |
|---|---|---|---|---|
| `ms-marco-MiniLM-L-6-v2` — 영어 전용, 업스트림 기본 | 0.100 | **0.000** | 0.053 | 1.97s |
| `BAAI/bge-reranker-base` — 278M 다국어, CPU | 0.600 | 0.500 | 0.644 | 8.18s |
| `BAAI/bge-reranker-v2-m3` — 568M 다국어, CPU | 0.800 | **0.857** | 0.893 | 57.05s |
| **`BAAI/bge-reranker-v2-m3` — 같은 모델, GPU(litellm)** | **0.800** | **0.857** | **0.893** | **0.535s** |

읽을 것이 세 가지다.

**첫째, 영어 리랭커는 한국어에서 정답을 한 번도 1위로 올리지 못했다 (0/14).** 성능 저하가
아니라 기능 부재다. 실서버가 12일 동안 이 상태로 서비스됐고, 기동 로그의
`Reranker: provider=local` 은 그동안 초록불이었다.

**둘째, 작은 다국어 모델은 타협이 아니라 손해였다.** 7배 빨라지는 대신 한국어 hit@1 이
0.857 → 0.500 으로 떨어진다. 크기를 줄여 얻은 속도가 정확도를 그만큼 가져갔다.

**셋째, GPU 로 옮기는 것은 타협이 전혀 아니다.** 같은 모델이라 품질이 **소수점까지 동일**
하고(hit@1·MRR·미회수 건수 전부 일치) 지연만 57.05s → 0.535s, **107배**다. 품질과 속도가
맞바꿈이 아니었던 유일한 축이고, 그래서 이것이 답이다.

후보 수(`RERANKER_MAX_CANDIDATES`)는 **잘 듣지 않는 손잡이**다. 80→20 으로 줄여도 지연은
57s→24s 로 절반밖에 안 줄고(개당으로는 오히려 비싸진다 — 남는 20개가 가장 긴 코드 청크라서)
한국어 hit@1 은 0.857→0.643 으로 떨어진다. **비용을 지배하는 것은 후보 개수가 아니라
후보 길이다.**

#### GPU 리랭커 붙이기

뒷단은 게이트웨이 호스트의 `vllm-rerank`(같은 `BAAI/bge-reranker-v2-m3`, `--runner pooling`,
GPU util 0.06 ≈ 2.8GB)이고 litellm 에 `wams-rerank` 로 이미 라우팅돼 있다. `.env` 는 네 줄이다:

```bash
HINDSIGHT_RERANKER_PROVIDER=litellm
HINDSIGHT_RERANKER_LITELLM_API_BASE=http://172.16.10.174:4001/v1   # 끝에 /v1 — 코드가 여기에 /rerank 를 붙인다
HINDSIGHT_RERANKER_LITELLM_API_KEY=sk-wams-local
HINDSIGHT_RERANKER_LITELLM_MODEL=wams-rerank
```

폴백 사다리: **GPU litellm → CPU `bge-reranker-v2-m3`(느리지만 정확) → CPU `bge-reranker-base`
(빠르지만 한국어 절반)**. 영어 전용 기본값으로는 내려가지 않는다 — 그건 폴백이 아니라 고장이다.

### 기동 직후 반드시 확인할 두 줄

```bash
docker compose logs hindsight | grep -E "Reranker: initializing|Embeddings: ONNX provider initialized"
```

기대값은 `BAAI/bge-reranker-v2-m3` 와 `dim: 384` 다.

`Reranker: provider=local` 만 보고 넘어가면 안 된다 — **provider 는 맞는데 모델이 기본값**
(`cross-encoder/ms-marco-MiniLM-L-6-v2`, 영어 전용)인 상태가 실제로 있었다. 26-07-29 대조에서
실서버가 정확히 그 상태로 12일 동안 한국어 뱅크를 서비스하고 있었다. provider 는 옳고 모델만
틀린 고장은 로그 한 줄 위에서 조용하다.

LLM 이 정말 붙었는지는 별도 문으로 묻는다 (compose 기본 켬):

```bash
curl -sX POST http://<host>:8888/v1/default/banks/<bank>/health/llm -H 'content-type: application/json' -d '{}'
```

- API `http://<host>:8888` · UI `http://<host>:9999` (UI = bank 관리, 관리자 표면)
- macOS 로컬에서 8888 이 충돌하면 `.env` 의 `HINDSIGHT_PORT` 변경

### 구 asgard-common-memory 볼륨에서 데이터 이관

compose 프로젝트 이름이 바뀌어 볼륨 이름도 바뀐다 (`asgard-common-memory_pgdata` →
`asgard-project-memory_pgdata`). 기존 데이터가 있으면 첫 `up` 전에 복제:

```bash
docker volume create asgard-project-memory_pgdata
docker run --rm -v asgard-common-memory_pgdata:/from -v asgard-project-memory_pgdata:/to \
  alpine sh -c "cd /from && cp -a . /to"
# 모델 캐시(재다운로드 가능이라 생략해도 무방)
docker volume create asgard-project-memory_models
docker run --rm -v asgard-common-memory_models:/from -v asgard-project-memory_models:/to \
  alpine sh -c "cd /from && cp -a . /to"
```

## 뱅크 단위 설정 — compose 가 못 닿는 층

지금까지 이 문서는 **서버 전역 설정(compose·`.env`)만** 다뤘다. 그런데 Hindsight 설정은 두 층이고,
운영에서 실제로 거동을 가르는 값 몇 개는 아래층에만 있다:

```bash
curl -s http://<host>:8888/v1/default/banks/<bank>/config | python3 -m json.tool
curl -sX PATCH http://<host>:8888/v1/default/banks/<bank>/config \
  -H 'content-type: application/json' -d '{"updates": {"retain_extraction_mode": "chunks"}}'
```

⚠ 본문은 반드시 `{"updates": {...}}` 로 감싼다. 평평하게 보내면 422 다.

| 뱅크 설정 | 값 | 왜 여기에 있나 |
|---|---|---|
| `retain_extraction_mode` | **`chunks`** | 서버 기본은 `concise`(LLM 이 사실을 추출). `chunks` 는 **LLM 을 아예 건너뛰고 청크를 그대로 저장한다**(`fact_extraction.py`: "chunks mode: skip LLM entirely"). Asgard 어댑터는 이미 증류된 record 를 보내므로, `concise` 로 두면 증류를 두 번 한다. 실서버 `asgard-custom-project` 도 `chunks` 다 — 우연이 아니라 이 구조에 맞는 선택이다 |
| `observations_mission` / `reflect_mission` | 설정함 (실서버와 동일) | "mission 3종 전부 빈칸" 결정은 **retain** 을 두고 한 말이다 — 우리 record 는 이미 증류돼 있으니 추출을 더 조향하지 말자는 것. observation·reflect 는 다르다: 거기서는 **서버가 직접 글을 쓴다**. 그래서 retain mission 만 빈칸으로 두고 이 둘은 채운다. 언어 고정도 여기서 한다 — 전역 `LLM_OUTPUT_LANGUAGE` 와 달리 **뱅크 단위라 다른 뱅크를 번역해 버리지 않는다** |
| `mcp_enabled_tools` | **비움(allowlist 없음)** | 실서버 뱅크에는 31종 allowlist 가 박혀 있다. 그런데 0.8.4 single-bank 마운트의 실제 표면은 **29종**이고, 나머지 2개(`list_banks`·`get_bank_stats`)는 multi-bank 전용이라 애초에 없다 = 지금은 아무것도 안 막는 목록이다. 대신 **업그레이드 때 신규 도구를 조용히 차단**한다. 막을 것이 있으면 Asgard 브리지 쪽에서 막는다(브리지는 recall + 2단계 retain 만 노출) |

`retain_extraction_mode` 는 **`llm_provider=none` 일 때 서버가 강제로 `chunks` 로 내린다**
(`memory_engine.py`, `enable_observations` 도 같이 끈다). 그래서 "LLM 이 붙어 있는데 사실이 안
늘어난다"와 "LLM 이 안 붙어서 chunks 로 강등됐다"가 겉으로 똑같이 보인다 — 구분은
`health/llm` 로 한다.

## 클라이언트

### MCP — 기본 (도구 전체 표면, 부팅 시 1회 등록)

```bash
claude mcp add --transport http hindsight-memory "http://<host>:8888/mcp/<project-id>/"
```

single-bank 마운트라 도구 전 표면(0.8.3 실측 29종 — retain·sync_retain·recall·reflect·
mental model·directive·document·operation·tag·bank 조회/설정)이 열리고,
**create_bank/list_banks/get_bank_stats 는 노출되지 않는다**.

⚠ 단 `delete_bank`·`clear_memories` 는 single-bank 에도 노출된다(destructiveHint 표기).
에이전트 표면에서 이것까지 막으려면 bank 별 `update_bank` 의 `mcp_enabled_tools`
allowlist 를 쓴다 (기본 = 제한 없음 — "도구 기본 활성화" 결정에 따름. allowlist 는
버전 업그레이드 시 신규 도구를 침묵 차단하는 부작용이 있어 기본값으로 쓰지 않는다).

### Asgard 브리지 — 게이트 경유 쓰기 경로

`asgard memory connect http://<host>:8888` 후 `claude mcp add --scope user asgard-memory -- asgard memory mcp`.
브리지는 recall + 2단계 retain(승인 게이트)만 노출한다 — 정본 기록은 이 경로로,
탐색·reflect·mental model 은 네이티브 MCP 로. 두 경로는 같은 bank 를 본다.

### REST/SDK

```python
# pip install hindsight-client
from hindsight_client import Hindsight
c = Hindsight(base_url="http://<host>:8888")
c.retain(bank_id="<project-id>", content="…")
c.recall(bank_id="<project-id>", query="…")
```

**bank 규약**: bank = 안정적인 project-id 하나 (repo remote URL에서 파생하지 말 것 — 이사하면
기억이 갈라진다). `asgard memory connect` 가 `{디렉터리명}-{uuid8}` 로 만들어 준다.

## 설계 결정

| 결정 | 이유 |
|---|---|
| 외부 postgres (임베디드 pg0 아님) | 공유 서버는 독립 백업(pg_dump)·재시작 안전·표준 운영이 우선 |
| 임베딩 = onnx multilingual-e5-small **고정** | **벡터 차원이 스키마에 고정** — 나중에 바꾸면 전체 재임베딩이라 첫 기동 전에 확정. (0.8.4 부터는 업스트림 기본도 같은 모델이다. 예전 기본 `bge-small-en` 이 한국어에 취약해서 고른 값인데, 지금은 "기본과 같아서 안 써도 된다"가 아니라 **차원을 고정하는 줄이라 명시한다**가 이유다) |
| 리랭커 = `BAAI/bge-reranker-v2-m3` | Hindsight 기본 `ms-marco-MiniLM-L-6-v2`는 영어 전용. 실측에서 한국어 semantic 1위를 4위로 뒤집어 공식 multilingual 권장 모델로 고정 |
| 리랭크 후보 수 = 80 (`RERANKER_MAX_CANDIDATES`) | 업스트림 기본 300 은 GPU 리랭커 전제. 여기는 CPU 12코어 + 568M 다국어 모델이고, 회수 지연은 사실상 전부 이 단계다(26-07-28 로그: graph 0.003s vs rerank 20.675s). 비용은 후보 수 × 후보 길이 — 후보 수가 우리가 쥔 유일한 손잡이 |
| 임베딩은 로컬 ONNX 유지 (게이트웨이 `wams-embed` 미채택) | 게이트웨이에 `wams-embed`(Qwen3-Embedding-4B, 2560차원)가 살아 있고 실제로 응답한다(26-07-29 확인). 그래도 안 붙인다 — ① 차원이 스키마에 박혀 되돌리려면 전체 재임베딩 ② **retain 과 recall 매 호출마다 네트워크 왕복이 생긴다**(로컬 ONNX 는 실측 1건 0.015s) ③ 게이트웨이가 죽으면 회수까지 같이 죽는다. 지금은 게이트웨이가 내려가도 회수는 산다 |
| LLM = 내부망 OpenAI 호환 게이트웨이 **연결** (엔드포인트·모델명·키는 `.env` 에만) | 관찰·Reflect 기본 활성 결정(2026-07-23) + 같은 날 로컬 ollama qwen3:8b → 게이트웨이의 대형 MoE 모델로 승격(한국어 종합 품질, 0원·내부망 유지). 폴백 사다리: 게이트웨이 불가 → ollama qwen3:8b(.env 주석 블록) → `none`(chunk 모드) |
| retain 출력 상한 = 8192 (`HINDSIGHT_RETAIN_MAX_COMPLETION_TOKENS`) | 업스트림 기본 64000 이 게이트웨이 모델의 짧은 컨텍스트 상한 초과로 400 — 실증 후 고정 |
| keyword 검색 = native(english) 유지 | 한국어 keyword arm 은 약함(CJK 토큰화 없음) — semantic+리랭커가 다국어라 실측 hit@1 은 확보. pgroonga/pg_search 도입은 별도 과제 |
| postgres 포트 비노출 | 접근은 hindsight API 경유만. 백업은 `docker compose exec` |
| 모델 캐시 볼륨 | 재기동 시 임베딩/리랭커 재다운로드 방지 |

## 26-07-29 실서버 검증에서 나온 것

실운영 뱅크를 복제한 새 스택(`asgard-project-memory-v2`, :8890)에 실제 부하를 걸어
확인한 것들. **전부 기본값이 조용히 틀린 자리**다 — 로그는 초록불이고 API 는 200 을 준다.

| 발견 | 증상 | 대응 |
|---|---|---|
| 리랭커 모델이 기본값(영어 전용) | `provider=local` 은 맞아서 정상으로 보인다. 한국어 top-1 정답 0/14 | 모델을 명시 + GPU 경로 (위 §리랭커) |
| `REFLECT_MAX_CONTEXT_TOKENS` 기본 100000 | 16384 모델의 여섯 배. 뱅크가 작을 때만 우연히 산다 | 10000 |
| `CONSOLIDATION_MAX_COMPLETION_TOKENS` 기본 무제한 | retain 만 막으면 관찰 통합이 같은 벽에 부딪힌다 | 3072 (+ 아래) |
| **출력만 잡고 입력을 안 잡음** | 4096 으로 잡았더니 `12289 + 4096 = 16385`, **1 토큰 초과**. consolidation 이 배치를 **건너뛰고 계속 간다**("skipping batch") — API 는 성공, 관찰만 조용히 빈다 | 출력 3072 + source 3072 + **배치 8→4** 를 한 세트로 |
| `ENABLE_BANK_LLM_HEALTH` 기본 false | "LLM 이 죽었나 뱅크가 빈 건가"를 물어볼 문이 없다 | true — `POST .../health/llm` |
| `WORKER_ID` 미설정 | 컨테이너 재생성 때 신원이 갈려 진행 중 작업을 아무도 회수하지 않는다 | 고정 이름 |
| bank `mcp_enabled_tools` 에 31종 고정 | 실제 표면은 29종(2개는 multi-bank 전용 유령). 지금은 아무것도 안 막고, **업그레이드 때 신규 도구를 조용히 막는다** | allowlist 비움 |
| bank `retain_extraction_mode` | `chunks` 는 **LLM 을 통째로 건너뛴다**. LLM 없는 배포용 폴백이지, GPU 가 있는 곳의 기본이 아니다 | GPU 있으면 `concise` |

`chunks` 와 `concise` 의 차이는 숫자로 보면 분명하다 — 같은 성격의 저장소에서
**chunks: 17 문서 → 48 fact** 대 **concise: 11 문서 → 469 fact**. 2차 메모리가 있는 곳에서
`chunks` 로 두면 Hindsight 를 청크 저장소로만 쓰는 셈이다.

### 검증된 것

`document-transfer` 로 실운영 뱅크 복제(17 문서·48 fact·83 observation, 누락 0) → 새 뱅크에서
retain(게이트웨이 LLM 추출 6.2s, `thoughts_tokens=0` 으로 thinking 꺼짐 확인) → 자동
consolidation → reflect(4.4s, 컨텍스트 초과 없음) → Asgard 브리지 2단계 승인 retain →
**회수·주입까지 한국어로 왕복**.

⚠ 복제할 때 하나 조심할 것: `document-transfer` 는 Asgard 의 바인딩 제어 문서
(`asgard:project-binding:v1`)까지 같이 복사한다. 사본 뱅크는 **원본 프로젝트에 묶인 채로**
태어나서 `asgard memory connect` 가 `binding project_id mismatch` 로 거절한다 — 가드가
제대로 동작한 것이다. 사본을 쓰려면 그 문서를 먼저 지우고 `connect --claim` 한다.

## 보안 — 반드시 읽기

- **Hindsight REST/MCP는 기본 무인증** — 이 구성은 **내부망/VPN 전제**다. 공인망 노출 금지.
  외부 노출이 필요하면 reverse proxy(인증) 뒤에 두거나 API-key tenant extension을 구성하고, `HINDSIGHT_MCP_ENABLED=false` 검토.
- 메모리는 **힌트**다 — Asgard 게이트는 메모리를 완료 증거로 절대 신뢰하지 않는다. 서버 다운 = 힌트 부재 = fail-open (클라이언트가 지켜야 할 계약).
- 개인 어휘 유입 금지(용어 방화벽) — 개인 위키 내용을 재서술 없이 retain하지 말 것.

## 운영

```bash
./backup.sh                          # pg_dump → backups/ (최근 14개 보존) — cron 권장
docker compose pull && docker compose up -d   # 업그레이드 (핀 태그면 .env 수정 후)
docker compose exec postgres psql -U hindsight   # DB 직접 점검
```

**복구**: `gunzip -c backups/<파일>.sql.gz | docker compose exec -T postgres psql -U hindsight hindsight` (빈 DB 기준 — 필요 시 볼륨 재생성 후).

**업그레이드 주의**: Hindsight는 pre-1.0 (주 단위 릴리스) — 운영 안정화 후 `.env`의 `HINDSIGHT_TAG`를 특정 버전으로 핀하고, 업그레이드 전 백업.
