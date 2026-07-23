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
| 산출 언어 | Korean (`HINDSIGHT_API_LLM_OUTPUT_LANGUAGE`) | 프로젝트 메모리 정본이 한국어 |

## 기동

```bash
cd docker/asgard-project-memory
cp .env.example .env        # DB 비밀번호 필수. LLM 은 기본 ollama(qwen3:8b) — 켜진 채로 출발
docker compose up -d
docker compose logs -f hindsight   # 첫 기동은 임베딩 모델 다운로드로 수 분
```

`HINDSIGHT_DB_PASSWORD`는 PostgreSQL 접속 URL에도 들어가므로 URL-safe 문자(영문·숫자와
`-._~`)만 사용한다. 관찰·Reflect 를 실제로 쓰려면 호스트에서 `ollama pull qwen3:8b` 후
ollama 가 떠 있어야 한다 (없어도 서버는 뜨고 retain 은 실패 시 해당 기능만 저하).

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
| 임베딩 = onnx multilingual-e5-small **고정** | 기본 bge-small-en은 한국어 취약. **벡터 차원이 스키마에 고정** — 나중에 바꾸면 전체 재임베딩이라 첫 기동 전에 확정 |
| 리랭커 = `BAAI/bge-reranker-v2-m3` | Hindsight 기본 `ms-marco-MiniLM-L-6-v2`는 영어 전용. 실측에서 한국어 semantic 1위를 4위로 뒤집어 공식 multilingual 권장 모델로 고정 |
| LLM = 내부망 OpenAI 호환 게이트웨이 **연결** (엔드포인트·모델명·키는 `.env` 에만) | 관찰·Reflect 기본 활성 결정(2026-07-23) + 같은 날 로컬 ollama qwen3:8b → 게이트웨이의 대형 MoE 모델로 승격(한국어 종합 품질, 0원·내부망 유지). 폴백 사다리: 게이트웨이 불가 → ollama qwen3:8b(.env 주석 블록) → `none`(chunk 모드) |
| retain 출력 상한 = 8192 (`HINDSIGHT_RETAIN_MAX_COMPLETION_TOKENS`) | 업스트림 기본 64000 이 게이트웨이 모델의 짧은 컨텍스트 상한 초과로 400 — 실증 후 고정 |
| keyword 검색 = native(english) 유지 | 한국어 keyword arm 은 약함(CJK 토큰화 없음) — semantic+리랭커가 다국어라 실측 hit@1 은 확보. pgroonga/pg_search 도입은 별도 과제 |
| postgres 포트 비노출 | 접근은 hindsight API 경유만. 백업은 `docker compose exec` |
| 모델 캐시 볼륨 | 재기동 시 임베딩/리랭커 재다운로드 방지 |

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
