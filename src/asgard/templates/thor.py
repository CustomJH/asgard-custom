"""토르 전용 스킬 4종 + 코어 계약 스킬 — 백엔드(연산·API·런타임·데이터 안전) 심화 지식.

내용 방침: ref/ 참조 조사(asgard-helios 뵐룬드·프레이르, hermes-agent 내구성 계약, 26-07-16)에서
검증한 패턴과 표준 엔지니어링 관행을 우리 용어로 재서술한다 — 외부 텍스트 재배포 없음. 스킬들은
CC(.claude/skills/)와 Cursor·Codex 공용(.agents/skills/) 양 스코프에 스캐폴드되어 모드 A/B/네이티브
전부에서 로드 가능하다. 코어 스킬은 role 파일이 단일 소스(roles.role_core_skill).

리졸버는 프레이야식 순수 부분 일치가 아니라 단어 경계 + 동반어 조건을 쓴다 — 26-07-16 Codex
교차검증에서 오발 반례(RESTORE→rest, capital→api, alternative→alter, healthcare→health,
drag-and-drop→drop) 가 실증됐다. 짧은 ASCII 용어는 \\b, 중의어(index·cache·schema·drop)는
도메인 동반어가 있을 때만 발화한다."""

import re

_MJOLLNIR = """\
---
name: asgard-thor-mjollnir
description: 토르의 망치 묠니르 — 핵심 연산·트랜잭션·배치·메시징 신뢰성 심화. 비즈니스 로직·대용량 처리·백그라운드 잡·큐 소비자 작업 전 로드.
---

# asgard-thor-mjollnir — 🔨 핵심 연산·트랜잭션·배치

던지면 맞아야 하고(정확), 반드시 돌아와야 한다(복구 가능) — 정확성이 성능보다 먼저다.

## 트랜잭션 캐논

- 경계는 유스케이스 단위 — 한 트랜잭션 = 한 일관성 단위. 진입 표면(핸들러)이나 저장 계층이 아니라 도메인 작업이 소유한다.
- 트랜잭션 안에서 외부 I/O(HTTP 호출·메일·큐 발행) 금지 — 커밋 전 부수효과는 롤백이 못 지운다. 발행이 필요하면 outbox.
- 롱 트랜잭션 금지: 사용자 대기·외부 응답을 트랜잭션 안에서 기다리지 않는다.
- 락 순서 일관성: 복수 자원 갱신은 전역 고정 순서로 — 교차 순서가 데드락 제조기다.
- 원자성 경계 밖 정합성은 명시적 전략으로: outbox(이벤트 발행) / 보상 트랜잭션(분산) / upsert+유니크 제약(중복 흡수).
- 격리 수준은 기본값을 확인하고 필요한 지점만 올린다 — 전역 상향은 해법이 아니라 처리량 사고다.

## 멱등성·재시도

- 재시도 가능 경로(큐 소비·웹훅 수신·배치 재실행)는 멱등이 기본값 — 멱등 키·처리 표식·유니크 제약 중 하나로 중복을 흡수한다.
- at-least-once 전달을 전제한다 — "정확히 한 번"은 전달이 아니라 처리(멱등 소비자)로 달성한다.

## 배치 내구성 계약 (이것 없이는 배치가 아니다)

- **체크포인트**: 어디까지 처리했는지를 재시작이 읽을 수 있는 위치에 기록한다.
- **재진입점**: 중단 후 재실행이 이어서인지 처음부터인지 선언하고, 이어서라면 경계 중복 구간을 멱등 처리한다.
- **부분 실패**: 실패 항목의 격리 방침(스킵+기록 vs 전체 중단)을 기준과 함께 선언한다. 실패가 조용히 사라지는 구조 금지 — 실패 테이블이든 DLQ 든 남긴다.
- **진행 관측**: 처리율·잔여 추정이 로그로 보인다 — 무소식 장시간 배치는 죽은 것과 구분이 안 된다.

## 대용량 처리

- 전량 메모리 적재 금지 — 스트리밍·커서·청킹. 청크 크기는 실측으로 정한다.
- N+1 탐지: 루프 안 쿼리는 배치 조회·조인으로. 수정 전후 쿼리 수를 실측해 보고한다.
- 처리량 주장은 실측만 — "빨라졌다"는 전/후 수치(건수/시간) 없이 보고하지 않는다 (Canon 8).

## 메시징 신뢰성

- 발행: DB 커밋과 발행의 원자성은 outbox 로 — 커밋 후 발행 실패, 발행 후 롤백 둘 다 사고다.
- 소비: 멱등 소비자 + 명시적 ack. poison 메시지는 재시도 상한 후 DLQ — 무한 재큐잉이 파이프라인을 멈춘다.
- backpressure: 소비 < 발행이 지속되면 버퍼 확대가 아니라 설계 문제 — 큐 깊이를 관측하고 상한을 둔다.

## 동시성

- 공유 가변 상태 최소화가 첫수. race 의심은 추측 수정 금지 — 재현(반복 실행·강제 인터리빙)이 먼저다 (role 사전 진단 게이트).

> 출처(패턴 번안): ref/asgard-helios 뵐룬드 트랜잭션 규약 + ref/hermes-agent 내구성 계약 조사(26-07-16), outbox·DLQ·멱등 소비자 표준 관행 자체 재서술.
"""

_LIGHTNING = """\
---
name: asgard-thor-lightning
description: 토르의 번개 — API·실시간·서버 보안·외부 연동 심화. 엔드포인트 설계·스트리밍·지연 예산·인증 경계·서드파티 호출 작업 전 로드.
---

# asgard-thor-lightning — ⚡ API·실시간·보안·외부 연동

요청이 오면 번개처럼 — 빠르게, 그러나 계약대로.

## API 계약 우선

- 에러 모델 일관: 같은 실패는 같은 형태(코드·구조)로. 내부 예외 문자열·스택을 응답에 노출하지 않는다.
- 버저닝: 깨는 변경(필드 제거·의미 변경)은 새 버전으로 — 기존 소비자 무경고 파괴 금지.
- 페이지네이션 기본: 무한 목록 응답 금지. 커서 우선(오프셋은 얕은 페이지만), 페이지 상한 명시.
- 입력 검증은 서버가 최종이다 — 클라이언트 검증은 UX 이지 방어가 아니다.

## 지연 수치 캐논

- 타임아웃 계층화: 바깥이 안쪽보다 길게 (클라이언트 > 게이트웨이 > 서비스 > DB·외부 호출). 역전되면 안쪽은 살아 있는데 바깥이 끊는 유령 실패가 된다.
- 재시도: 멱등 요청만, 지수 백오프 + 지터, 상한 명시 — 비멱등 재시도는 중복 실행 사고다.
- 서킷 브레이커: 연속 실패 임계 후 차단 + 반개방 프로브 — 죽은 의존성에 전 요청이 타임아웃까지 매달리게 두지 않는다.
- 수치 예산은 핫 패스만 의무 (role 성능 표면 분리) — 예산은 실측으로 검증해 보고한다.

## 실시간 사다리 (낮은 단이 충족하면 멈춘다)

① 폴링(간격 조회 — 대부분 충분) → ② SSE/롱폴링(서버→클라이언트 단방향 push) → ③ WebSocket(양방향·상태 유지 — 재연결·팬아웃·백프레셔 비용을 감당할 때만). 근거 없는 상위 단계 채택 금지. WebSocket 이면 재연결 전략과 미전달 메시지 처리를 함께 설계한다.

## 캐싱

- 무효화 전략을 먼저 쓰지 못하면 캐시 도입 금지 — "일단 TTL" 은 전략이 아니라 미뤄 둔 버그다.
- 캐시 키에 파라미터·인증 스코프를 전부 반영한다 — 타인 데이터 응답이 최악의 캐시 버그.
- 스탬피드: 동시 만료 재계산은 잠금·조기 갱신으로 막는다.

## 서버 보안 경계

- 인증(누구인가)과 인가(무엇을 할 수 있나)를 구분해 명시한다 — 리소스 접근마다 객체 소유권 검사(IDOR 방어).
- 비밀정보 하드코딩 금지 — 환경·시크릿 스토어로. 로그에 토큰·개인정보를 남기지 않는다.
- 사용자 입력 URL 로 서버가 fetch 하면 SSRF — 내부망 차단·allowlist 검증 필수. 세션 쿠키 기반이면 CSRF 토큰/SameSite.

## 외부 연동 (타임아웃·부분 실패·보상 없이는 외부 호출이 아니다)

- 모든 외부 호출에 타임아웃 명시 — 라이브러리 기본 무한대기가 흔한 함정.
- 실패 시 전략을 선언한다: 재시도(멱등 한정)? 폴백? 실패 전파? — "될 거라 가정"은 전략이 아니다.
- 외부 응답은 미검증 입력이다 — 스키마 검증 후 사용 (Canon 5 와 같은 원리).

> 출처: 타임아웃 계층화·서킷 브레이커·OWASP 상위 카테고리 표준 관행 자체 재서술 + ref/ 참조 조사(26-07-16) 번안.
"""

_MEGINGJORD = """\
---
name: asgard-thor-megingjord
description: 토르의 힘의 허리띠 메긴기요르드 — 런타임 인프라·스케일링·관측성 심화. 배포 후 거동(probe·리소스·오토스케일·로그·메트릭) 작업 전 로드. 이미지 빌드·CI 는 eitri 소관.
---

# asgard-thor-megingjord — 🜃 런타임 인프라·스케일링·관측성

허리띠는 힘을 두 배로 — 트래픽이 몰려도 시스템이 버티게. 스코프는 배포된 것의 런타임 거동·정책 값이다. 빌드 그래프·CI·패키징은 asgard-eitri 소관 — 혼합 파일(k8s manifest 의 이미지 태그, Dockerfile 의 HEALTHCHECK)은 주 표면 담당이 편집하되 런타임 값은 이 캐논을 기준으로 쓴다.

## 무상태 우선 (스케일아웃의 전제)

- 프로세스 로컬 세션·업로드 파일·정합성이 걸린 인메모리 캐시가 있으면 수평 확장 불가 — 외부화(스토어·오브젝트 스토리지)가 스케일링보다 먼저다.
- 리트머스: 인스턴스 2개로 굴려도 죽지 않는가.

## 헬스체크

- liveness(살았나 — 실패 시 재시작) ≠ readiness(받을 수 있나 — 실패 시 트래픽 제외)를 구분한다.
- 의존성 캐스케이드 금지: DB 다운을 liveness 실패로 전파하면 전체 재시작 폭풍 — 의존성 상태는 readiness 까지만.
- 체크는 가볍게 — 헬스체크 자체가 부하 원인이 되지 않게.

## graceful shutdown

- 종료 시그널 수신 → 신규 수신 중단(readiness 내리기) → 인플라이트 완료 대기(상한부) → 자원 정리 → 종료. 인플라이트를 끊으면 재시도 없는 클라이언트에겐 데이터 손실이다.
- 종료 대기 상한은 인프라의 강제 종료 유예보다 짧게 잡는다.

## 스케일링

- 수평 우선 — 수직(더 큰 머신)은 실측 근거(단일 프로세스 CPU/메모리 병목) 가 필요하다.
- 오토스케일 신호는 실제 병목 지표로(큐 깊이·p99·동시 처리 수) — CPU 만으론 I/O 바운드를 놓친다.
- 스케일 정책엔 상한·하한·쿨다운 명시 — 무상한 오토스케일은 비용 사고이자 연쇄 장애 증폭기다.

## 설정 외부화

- 환경별 분기 코드 금지 — 설정 값 주입으로. 코드는 모든 환경에서 동일 아티팩트다.
- 기본값은 안전한 쪽(로컬·개발) — 운영 값은 명시 주입만.

## 관측성 최소 계약

- 구조화 로그(검색 가능한 필드) + 요청 상관 ID 전파.
- 핵심 메트릭 4종: 트래픽·에러율·지연(p50/p99)·포화도. SLO 는 핫 패스만 (role 성능 표면 분리).
- 리트머스: "이 코드가 새벽에 죽으면 로그만으로 원인 후보를 좁힐 수 있는가."

> 출처: probe 분리·graceful shutdown·핵심 메트릭 표준 관행 자체 재서술.
"""

_JARNGREIPR = """\
---
name: asgard-thor-jarngreipr
description: 토르의 철장갑 야른그레이프르 — 데이터·스키마 안전 오버레이. 스키마 변경·마이그레이션·인덱스·비가역 데이터 조작이 끼는 작업에서 다른 스킬 위에 겹쳐 로드한다.
---

# asgard-thor-jarngreipr — 🧤 데이터·스키마 안전 (오버레이)

달군 묠니르를 맨손으로 쥐지 않는다. 이 스킬은 단독이 아니라 **오버레이** — 데이터 위험이 끼면 묠니르·번개 위에 겹쳐 적용한다. RDB 만이 아니라 검색 인덱스·파일 데이터·캐시 스토어 등 상태 있는 저장소 전부가 대상이다.

## 안전 등급 매트릭스 (환경 × 부작용 — role 승인 모델의 데이터 구체화)

| 등급 | 대상 | 행동 |
|---|---|---|
| 🟢 | 읽기 전부 / 로컬·ephemeral 환경 전부 | 즉시 실행 |
| 🟡 | 공유 환경 데이터 변경(DML) | 영향 범위·건수 추정 + 되돌리기 방법을 산출물로 보고 — 실행은 배정에 명시됐을 때만 |
| 🔴 | 스키마 변경·마이그레이션 | expand-contract + 롤백 계획 필수, 계획을 보고에 동반 |
| ⚫ | 운영 환경 직접 실행 / 백업 없는 파괴 조작(drop·truncate·비가역 갱신) | 직접 실행 금지 — 계획 반환, 승인은 Odin 몫 |

## 마이그레이션 (expand-contract)

- 전방·후방 호환: 구 코드와 신 코드가 공존하는 배포 구간을 견뎌야 한다 — ① 확장(새 컬럼·테이블, 널 허용/기본값) ② 이행(이중 쓰기 또는 백필) ③ 수축(구 경로 제거)은 별 단계·별 배포로 나눈다.
- 파괴 변경(컬럼 제거·타입 축소·NOT NULL 추가)은 수축 단계에서만 — 사용처 0 을 확인한 뒤.
- 백필은 배치 내구성 계약(묠니르)을 따른다 — 한 방 대량 UPDATE 금지(락·복제 지연), 청크+스로틀.
- 롤백 계획 없는 마이그레이션은 미완성이다 — "롤포워드로 고친다"도 계획이면 명시한다.

## 인덱스

- 근거는 실측 쿼리 계획 — "느릴 것 같아서" 인덱스 금지. 전/후 계획·실행 시간을 보고에 첨부한다.
- 쓰기 비용 명시: 인덱스는 공짜가 아니다 — 쓰기 빈도 높은 테이블은 트레이드오프를 서술한다.
- 대형 테이블 인덱스 생성은 온라인 방식(지원 시) — 락 유지 시간 추정 없이 실행 금지.

## 정합성·비가역

- 비가역 조작 전 리트머스: "직후 후회하면 되돌릴 수단이 있는가" — 없으면 ⚫ 등급이다.
- 유니크·외래키 제약은 애플리케이션 검증의 대체가 아니라 최후 방어선 — 경합 창은 제약만 잡는다.
- 검색 인덱스·캐시 등 파생 데이터는 재구축 절차가 확인될 때만 파괴 가능하다.

> 출처(패턴 번안): ref/asgard-helios 프레이르 안전 등급 조사(26-07-16) + expand-contract 표준 관행 자체 재서술.
"""

THOR_SKILLS: list[tuple[str, str]] = [
    ("asgard-thor-mjollnir", _MJOLLNIR),
    ("asgard-thor-lightning", _LIGHTNING),
    ("asgard-thor-megingjord", _MEGINGJORD),
    ("asgard-thor-jarngreipr", _JARNGREIPR),
]

# 네이티브 디스패치 task → 전용 스킬 매칭 (파일 스킬 로더가 없는 asgard start 세션용 통로 —
# 모드 A/B 는 파일 스킬이 담당). 부분 일치 키워드 + 단어 경계 정규식 + 동반어 조건 3층.
_SUBSTR: dict[str, tuple[str, ...]] = {
    "asgard-thor-mjollnir": (
        "배치",
        "트랜잭션",
        "transaction",
        "집계",
        "aggregat",
        "대용량",
        "동시성",
        "concurren",
        "멱등",
        "idempoten",
        "메시징",
        "outbox",
        "dlq",
        "backpressure",
        "kafka",
        "rabbitmq",
        "비즈니스 로직",
        "business logic",
        "데드락",
        "deadlock",
        "레이스 컨디션",
        "race condition",
        "백그라운드 잡",
        "background job",
        "백필",
        "backfill",
    ),
    "asgard-thor-lightning": (
        "endpoint",
        "엔드포인트",
        "graphql",
        "grpc",
        "websocket",
        "웹소켓",
        "실시간",
        "realtime",
        "real-time",
        "스트리밍",
        "streaming",
        "지연",
        "latency",
        "rate limit",
        "레이트리밋",
        "폴링",
        "polling",
        "restful",
        "인증",
        "인가",
        "authent",
        "authoriz",
        "oauth",
        "웹훅",
        "webhook",
        "타임아웃",
        "timeout",
        "서킷",
        "circuit breaker",
        "외부 연동",
        "서드파티",
        "third-party",
    ),
    "asgard-thor-megingjord": (
        "스케일링",
        "오토스케일",
        "autoscal",
        "스케일 아웃",
        "scale-out",
        "로드밸런",
        "load balanc",
        "k8s",
        "kubernetes",
        "쿠버네티스",
        "오케스트레이션",
        "orchestrat",
        "무중단",
        "healthcheck",
        "health check",
        "헬스체크",
        "liveness",
        "readiness",
        "graceful",
        "드레이닝",
        "관측성",
        "observab",
        "메트릭",
        "metric",
        "트레이싱",
        "tracing",
        "무상태",
        "stateless",
    ),
    "asgard-thor-jarngreipr": (
        "마이그레이션",
        "migrat",
        "truncate",
        "정합성",
        "expand-contract",
        "롤백",
        "rollback",
        "백업",
        # ddl/dml/스키마/인덱스/drop 은 아래 정규식·동반어 조건이 담당 (오발 방지)
    ),
}
# 단어 경계 필수 — 부분 일치면 capital→api, batches 는 잡되 debatch 는 제외하는 식의 통제 불가.
_WORD_RE: dict[str, tuple[str, ...]] = {
    "asgard-thor-mjollnir": (r"\bbatch", r"\bqueue", r"\brace\b"),
    "asgard-thor-lightning": (r"\bapi\b", r"\bsse\b", r"\bauth\b", r"\bp99\b"),
    "asgard-thor-megingjord": (r"\bscal(e|es|ed|ing)\b", r"\bhpa\b", r"\bslo\b", r"\bdrain"),
    "asgard-thor-jarngreipr": (r"\bddl\b", r"\bdml\b"),
}


def _any(t: str, *patterns: str) -> bool:
    return any(re.search(p, t) for p in patterns)


_DB_CONTEXT = (
    r"\bsql\b|쿼리|query|테이블|\btable\b|\bdb\b|database|스키마|\bschema\b|postgres|mysql|mariadb|sqlite|mssql|oracle"
)


def _cache_hit(t: str) -> bool:
    """캐시 → lightning — 서버 응답 캐시 문맥만 (CI 캐시·docker layer·브라우저 캐시 제외)."""
    if not _any(t, r"캐시|\bcach"):
        return False
    if _any(t, r"\bci\b", r"docker", r"\blayer\b", r"브라우저", r"browser", r"빌드 캐시", r"build cache"):
        return False
    return _any(
        t,
        r"server",
        r"서버",
        r"응답",
        r"response",
        r"redis",
        r"memcach",
        r"\bcdn\b",
        r"\bapi\b",
        r"엔드포인트",
        r"endpoint",
        r"무효화",
        r"invalidat",
    )


def _index_hit(t: str) -> bool:
    """인덱스 → jarngreipr — DB 문맥 동반 시만 (index.ts·목차 오발 방지)."""
    return _any(t, r"인덱스", r"\bindex") and _any(t, _DB_CONTEXT)


def _schema_hit(t: str) -> bool:
    """스키마 → jarngreipr — 단 GraphQL 스키마는 API 계약(lightning 트리거가 별도 담당)."""
    return _any(t, r"스키마", r"\bschema\b") and not _any(t, r"graphql")


def _drop_hit(t: str) -> bool:
    """drop/alter → jarngreipr — DB 문맥 동반 시만 (drag-and-drop·alternative 오발 방지)."""
    return _any(t, r"\bdrop\b", r"\balter\b") and _any(t, _DB_CONTEXT, r"컬럼", r"\bcolumn\b")


_COMPANION: dict[str, tuple] = {
    "asgard-thor-lightning": (_cache_hit,),
    "asgard-thor-jarngreipr": (_index_hit, _schema_hit, _drop_hit),
}


def resolve_thor_skills(task: str) -> list[tuple[str, str]]:
    """디스패치 task → 매칭된 전용 스킬 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    네이티브 토르 자식 세션의 system 에 직접 주입할 본문을 고른다 (파일 스킬 로더 부재 보완).
    무매칭 = 빈 리스트 (fail-open — role 본문 기준으로 진행, role 이 이미 그 폴백을 선언한다).
    복수 매칭은 전부 주입 — role 합성 규칙(야른그레이프르 = 오버레이)이 그것을 전제한다."""
    t = task.lower()

    def hit(name: str) -> bool:
        return (
            any(k in t for k in _SUBSTR.get(name, ()))
            or _any(t, *_WORD_RE.get(name, ()))
            or any(cond(t) for cond in _COMPANION.get(name, ()))
        )

    return [(name, body.split("---", 2)[2].lstrip()) for name, body in THOR_SKILLS if hit(name)]


def thor_core_skill() -> str:
    """모드 A용 토르 코어 계약 스킬 — role 파일 단일 소스 (roles.role_core_skill 파생)."""
    from .roles import role_core_skill

    return role_core_skill(
        "asgard-thor.md",
        "토르 코어 계약 — 백엔드(서비스 코드·데이터·API·런타임 정책) 작업의 인라인 수행 기준. "
        "서브에이전트가 없는 툴에서 백엔드 하위작업 시 Worker phase 가 로드한다.",
    )


def eitri_core_skill() -> str:
    """모드 A용 에이트리 코어 계약 스킬 — role 파일 단일 소스 (roles.role_core_skill 파생)."""
    from .roles import role_core_skill

    return role_core_skill(
        "asgard-eitri.md",
        "에이트리 코어 계약 — 빌드·CI·패키징·릴리스 작업의 인라인 수행 기준. "
        "서브에이전트가 없는 툴에서 빌드·CI 하위작업 시 Worker phase 가 로드한다.",
    )
