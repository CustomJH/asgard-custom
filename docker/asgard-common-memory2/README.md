# asgard-common-memory2 — Cognee 프로젝트 지식 엔진

Asgard 프로젝트 정본(Markdown/JSONL/OWL)을 문서·코드·ontology knowledge graph로 투영하는 Cognee 서버다. Hindsight 프로젝트 경험/시간 엔진과 독립적으로 켜고 끌 수 있으며, **Cognee DB를 정본으로 취급하지 않는다.**

## 확정 구성

| 항목 | 값 | 근거 |
|---|---|---|
| Cognee | `1.3.0` | 검증 버전 고정 |
| Embedding | FastEmbed `0.8.0` | CPU in-process, 서버/API key/GPU 불필요 |
| Model | `intfloat/multilingual-e5-large`, 1024 dim | FastEmbed 0.8.0 built-in 다국어 모델; e5-small은 custom registry adapter 필요 |
| LLM | optional provider mapping; 기본 host Ollama `llama3.2:latest` | 실제 JSON probe에서 가장 빠르고 유효한 구조화 출력을 낸 설치 모델 |
| Relational | SQLite | 초기 단일 서버 projection |
| Vector | LanceDB | Cognee 기본 local backend |
| Graph | Ladybug/Kuzu compatibility backend | Cognee 기본 local graph |
| Auth | Cognee bearer auth + backend access control | LAN bind라도 무인증 금지 |
| Data | `./data`, model cache `./models` | host bind로 재시작 보존 |

## 배포

```bash
cd /data/asgard-project-memory2
./install.sh
./e2e.sh --auto
```

`install.sh`는 먼저 공식 Astral installer로 user-local `uv`를 준비하고, uv-managed CPython 3.14와 lockfile runtime을 만든다. 이후 최초 실행에만 `.env`를 만들고 app password와 FastAPI token secrets를 무작위 생성한다. 값은 출력하지 않으며 `.env` permission을 `0600`으로 설정한다. 이미 `.env`가 있으면 수정하지 않는다. 운영 스크립트의 Python 코드는 시스템 Python이 아니라 모두 `uv run`으로 실행한다.

접속:

- API: `http://<host>:8000`
- Health: `http://<host>:8000/health`
- OpenAPI: `http://<host>:8000/docs`
- 애플리케이션 로그인 ID는 원격 `.env`의 `COGNEE_DEFAULT_USER_EMAIL` 참조
- password도 원격 `.env`에만 있으며 저장소·로그에 기록하지 않는다.

> 서버의 SSH 계정과 Cognee 애플리케이션 계정은 별개다. SSH password를 Cognee에 재사용하지 않는다.

## 명령

```bash
./doctor.sh             # health, container→LLM readiness, safe runtime config
./e2e.sh --auto         # LLM 가능 시 full, 불가능 시 health/auth + DEGRADED
./e2e.sh --base-only    # LLM과 무관하게 health/auth만 검증
./e2e.sh --full         # LLM이 반드시 가능한 조건으로 전체 graph E2E
uv run ./llm-benchmark.py  # 설치된 Ollama 모델 JSON 출력·처리량 probe
./backup.sh             # writer 정지 후 SQLite/LanceDB/graph 일관 snapshot
./restore.sh backups/cognee-YYYYmmdd-HHMMSS.tar.gz

docker compose logs -f cognee
docker compose restart cognee
docker compose down     # data/models bind directory는 보존
docker compose down -v  # named volume은 없지만 관례상 파괴 명령 취급
```

## E2E가 검증하는 것

1. 인증이 실제로 요구되고 default app user가 로그인 가능
2. 한국어/영어 혼합 Markdown ingest
3. 프로젝트 OWL ontology upload
4. 설정된 LLM이 가용할 때만 직렬 cognify
5. FastEmbed multilingual E5를 통한 CHUNKS semantic recall
6. GRAPH_COMPLETION이 canonical/projection 관계를 답함
7. graph가 비어 있지 않고 ontology-grounded node가 존재

E2E fixture dataset은 provenance를 남기기 위해 실행 시각이 붙은 dataset으로 보존한다. 반복 운영 전에는 테스트 dataset 정리 API를 별도 운영 명령으로 추가한다.

### LLM 가용성 상태

Cognee의 API/auth/storage health와 graph extraction readiness는 별도 상태다.

| 상태 | health/auth | add | cognify/graph | 판정 |
|---|---:|---:|---:|---|
| LLM available | 가능 | 가능 | 가능 | full |
| LLM unavailable | 가능 | 가능 | 불가능/미검증 | degraded |

`COGNEE_LLM_REQUIRED=false`가 기본이라 Ollama가 없거나 잠시 내려가도 install과 API health는 유지한다. `doctor.sh`와 `e2e.sh --auto`는 **컨테이너 내부에서** 설정 endpoint/model을 probe한다. 모델이 없으면 graph 단계를 성공으로 위장하지 않고 명시적으로 `DEGRADED`를 출력한다. 모델이 다시 가용해지면 설정 변경 없이 `./e2e.sh --full` 또는 canonical rehydrate를 실행할 수 있다.

다른 provider를 쓰려면 `.env`에서 `COGNEE_LLM_PROVIDER`, `COGNEE_LLM_MODEL`, `COGNEE_LLM_ENDPOINT`, `COGNEE_LLM_API_KEY`를 모두 명시한다. 외부 API로의 묵시적 fallback은 없다.

### LiteLLM proxy provider

`litellm.env.example`은 기존 또는 별도 운영되는 LiteLLM proxy를 위한 안전한 snippet이다. 실제 key는 private `.env`에만 넣는다.

```dotenv
COGNEE_LLM_REQUIRED=false
COGNEE_LLM_PROVIDER=custom
COGNEE_LLM_MODEL=openai/<litellm-model-alias>
COGNEE_LLM_ENDPOINT=http://<litellm-host>:4000/v1
COGNEE_LLM_API_KEY=<private-key>
```

Cognee `custom` provider는 내부 `GenericAPIAdapter`와 LiteLLM client를 사용한다. `provider-readiness.py`는 컨테이너에서 `/v1/models`를 bearer 인증으로 조회해 alias 존재를 검사한다. endpoint와 alias가 확인되지 않으면 `DEGRADED`이며, 다른 provider로 자동 전환하지 않는다.

### 서버 설치 모델 실측

동일한 짧은 JSON schema 요청 결과:

| 모델 | wall | output tok/s | JSON 유효 | 판정 |
|---|---:|---:|---:|---|
| `llama3.2:latest` | 7.49s | 3.09 | yes | 기본값 |
| `phi4-mini:latest` | 43.61s | 2.54 | yes | 느린 fallback 후보 |
| `doomgrave/qwen3:8B-Q3_KS` | 51.95s | 2.44 | no | Cognee 기본에서 제외 |

마지막 모델은 2 token만 내고 JSON schema를 만족하지 못했다. 따라서 모델 이름만 존재하는 것을 readiness로 간주하지 않고, 배포 후 full cognify E2E를 별도로 통과시켜야 한다.

## Hindsight와의 관계

```text
Project Canonical Ledger (repo Markdown/JSONL/OWL)
            ├─▶ Cognee: 문서·코드·ontology·multi-hop projection
            └─▶ Hindsight: 대화·경험·timeline·current-state projection
```

금지:

- Cognee 결과를 Hindsight 정본으로 retain
- Hindsight observation을 Cognee 정본으로 자동 기록
- 두 엔진 plugin이 Asgard를 우회해 prompt에 직접 자동 주입

허용:

- 같은 canonical revision에서 두 projection을 독립 재수화
- dual-shadow query 평가
- Asgard gateway가 provenance/security/budget 검사 후 결과 병합

## 보안

- `.env`, `data/`, `models/`, `backups/`는 gitignore 대상이다.
- API는 기본 `0.0.0.0:8000`에 bind하지만 bearer auth를 강제한다. 공인망 노출은 금지하고 LAN/VPN 또는 인증 reverse proxy를 사용한다.
- default user password와 token secrets는 install 시 무작위 생성한다.
- REST 결과는 여전히 untrusted memory다. body/title/entity/edge/source를 Asgard threat scanner와 role gate에 통과시켜야 한다.
- Verifier/Loki는 Cognee/Hindsight 기억을 완료 증거로 사용하지 않는다.
- 모델·DB 장애는 작업 실패가 아니라 기억 힌트 부재로 fail-open 해야 한다.

## 운영 주의

- 첫 build는 base image와 FastEmbed dependency, 첫 startup/query는 2.24GB E5 model 다운로드로 오래 걸릴 수 있다. `FASTEMBED_CACHE_PATH=/root/.cache/fastembed`는 host `./models`에 영속화된다.
- e5-large는 품질은 좋지만 FastEmbed 단독 실측 추가 RSS가 약 1.7GB였다. Cognee graph/vector/LLM까지 포함한 container limit은 기본 12GB다.
- 기본 host Ollama mapping은 `host.docker.internal`을 사용한다. Linux gateway mapping은 Compose에 포함됐지만 Ollama가 loopback에만 bind되면 컨테이너에서는 접근할 수 없으며 이 경우 정상적인 `DEGRADED` 상태다.
- `DATASET_QUEUE_MAX_CONCURRENT=1`, cognify E2E의 `chunks_per_batch=1`, `data_per_batch=1`은 단일 Ollama 모델 스래싱을 방지한다.
- embedding model/dimension 변경 시 기존 LanceDB를 그대로 사용하지 말고 canonical에서 새 projection을 구축한다.
- backup은 binary stores의 일관성을 위해 짧은 Cognee downtime을 발생시킨다.

## 다음 통합 단계

이 배포는 독립 엔진 E2E까지만 담당한다. Asgard product integration에는 별도 `ProjectMemoryEngine` adapter가 필요하다.

```text
health
rehydrate
upsert
remove
query
trace
reset
manifest
```

초기에는 `dual-shadow`로 Cognee/Hindsight를 모두 조회하되 기준 엔진만 모델 context에 넣고, 실제 project gold query로 graph/temporal 품질과 latency를 비교한 후 `cognee`, `hindsight`, `hybrid` 중 결정한다.
