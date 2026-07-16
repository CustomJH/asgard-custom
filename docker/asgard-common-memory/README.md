# asgard-common-memory — 중앙 공유 Hindsight 서버

팀 공용 프로젝트 메모리 서버. **DB 하나에 여러 사용자가 bank(=프로젝트) 단위로 조회·기록**한다.
Asgard 메모리 v3의 2차 계층 인프라 (1차 개인 위키는 각자 로컬 `~/.asgard/memory/`).

```
사용자들 ──REST/MCP──▶ hindsight (:8888 API · :9999 UI)
                          │ retain = 기본 chunks-only (LLM 선택) · recall = TEMPR, LLM 0
                          ▼
                      postgres (pgvector, 컨테이너 내부 전용)
```

## 기동

```bash
cd docker/asgard-common-memory
cp .env.example .env        # DB 비밀번호 필수; LLM 설정은 사실 추출을 켤 때만
docker compose up -d
docker compose logs -f hindsight   # 첫 기동은 임베딩 모델 다운로드로 수 분
```

`HINDSIGHT_DB_PASSWORD`는 PostgreSQL 접속 URL에도 들어가므로 URL-safe 문자(영문·숫자와
`-._~`)만 사용한다. 다른 문자가 필요하면 percent-encoding한 값을 별도 DB URL로 구성해야 한다.

- API `http://<host>:8888` · UI `http://<host>:9999`
- macOS 로컬 시험 시 8888이 OrbStack 등과 충돌하면 `.env`의 `HINDSIGHT_PORT` 변경

## 클라이언트 (팀원)

```python
# pip install hindsight-client
from hindsight_client import Hindsight
c = Hindsight(base_url="http://<host>:8888")
c.retain(bank_id="<project-id>", content="…")          # 쓰기 (기본 chunks-only)
c.recall(bank_id="<project-id>", query="…")            # 조회 (LLM 0, ~0.3s)
```

MCP(Claude Code 등): `claude mcp add --transport http hindsight http://<host>:8888/mcp --header "X-Bank-Id: <project-id>"`

**bank 규약**: bank = 안정적인 project-id 하나 (repo remote URL에서 파생하지 말 것 — 이사하면 기억이 갈라진다).
asgard CLI 통합(`asgard memory` 프로젝트 스코프)이 이 서버를 소비한다.

## 설계 결정

| 결정 | 이유 |
|---|---|
| 외부 postgres (임베디드 pg0 아님) | 중앙 서버는 독립 백업(pg_dump)·재시작 안전·표준 운영이 우선 |
| 임베딩 = onnx multilingual-e5-small **고정** | 기본 bge-small-en은 한국어 취약. **벡터 차원이 스키마에 고정** — 나중에 바꾸면 전체 재임베딩이라 첫 기동 전에 확정 |
| 리랭커 = `BAAI/bge-reranker-v2-m3` | Hindsight 기본 `ms-marco-MiniLM-L-6-v2`는 영어 전용이다. 실측에서 올바른 한국어 semantic 1위를 4위로 뒤집어 공식 multilingual 권장 모델로 고정 |
| LLM = 기본 `none` | 원문 chunk 검색만 먼저 검증한다. 이 모드에서는 사실·엔티티 추출, observation, consolidation, reflect가 비활성이다. 이 기능이 필요할 때 API 키 또는 내부 Ollama를 명시적으로 켠다 |
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
