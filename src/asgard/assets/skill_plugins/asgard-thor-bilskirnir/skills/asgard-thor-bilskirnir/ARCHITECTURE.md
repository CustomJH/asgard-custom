# 백엔드 아키텍처 정책 — 4계층

## 계층과 의존 방향

```
boot (진입) → service (REST·로직·설정) → store (데이터 접근) → domain (엔티티·DTO·계약)
```

**의존 규칙**: `boot → service → store → domain` 단방향. domain 은 외부 의존이 없다 (프레임워크 포함 최소화).

## 모듈 구조

```
{project}-be/
├── {project}-be-boot/      # 애플리케이션 진입점
├── {project}-be-service/   # REST 컨트롤러, 비즈니스 로직, 설정
├── {project}-be-store/     # 매퍼·리포지토리, DB 설정
└── {project}-be-domain/    # 엔티티, DTO, 예외, 인터페이스
```

서비스 명명: `{project}-{service}` (소문자·하이픈). 예: `{project}-be`(API), `{project}-batch`(스케줄러·배치), `{project}-fe`(웹 클라이언트).

## 패키지 배치표

베이스 패키지: `com.{company}.{project}`

| 모듈 | 패키지 | 내용 |
|---|---|---|
| boot | `…` | `Main.java` |
| service | `….rest` | REST 컨트롤러 |
| service | `….logic` | 비즈니스 로직 (spec 구현) |
| service | `….config` | 설정 클래스 |
| service | `….utils` | 유틸리티 (토큰·API 헬퍼) |
| service | `….interceptor` | HTTP 인터셉터 |
| store | `….mapper` | 매퍼 구현 |
| store | `….config` | DB 설정 |
| domain | `….entity` | 엔티티 |
| domain | `….dto` | DTO |
| domain | `….response` | API 응답 래퍼 |
| domain | `….spec` | 서비스 인터페이스 |
| domain | `….store` | 스토어 인터페이스 |
| domain | `….type` | Enum (ResultCode 등) |
| domain | `….exception` | 커스텀 예외 |

## 계층 책임

| 계층 | 한다 | 하지 않는다 |
|---|---|---|
| boot | 진입·컴포넌트 스캔 | 비즈니스 로직, 설정 |
| service | REST 엔드포인트, 로직, 검증, 설정 | SQL, 직접 DB 조작 |
| store | 데이터 접근, 쿼리 | 비즈니스 로직 |
| domain | 자료 구조, 인터페이스, 예외 | 로직, 외부 의존 |

## 인터페이스 패턴 (계약은 domain, 구현은 바깥)

```
domain/spec/    → 서비스 인터페이스 (예: UserService)
domain/store/   → 스토어 인터페이스 (예: UserStore)
service/logic/  → 서비스 구현 (예: UserLogic)
store/mapper/   → 스토어 구현 (예: UserMapper)
```

## 설정 프로파일

형식: `{env}-{db}` (예: `local-h2`, `dev-postgres`, `prod-postgres`). 프로파일 그룹으로 관리하고 쉼표 나열 프로파일은 금지한다. 기본은 로컬·개발 안전값, 운영 값은 명시 주입만.

## 부트 리소스 규약 (boot 모듈 `resources/`)

| 파일 | 용도 | 필수 |
|---|---|---|
| `application.yml` | 공통 설정, 프로파일 그룹 | ✅ |
| `application-{profile}.yml` | 환경·DB별 설정 | ✅ |
| `messages_{lang}.properties` | i18n 메시지 | ✅ |
| `banner.txt` | 기동 배너 (프레임워크 네이티브 플레이스홀더 사용) | 신규 서비스 필수 |
| `logback-spring.xml` | 로깅 설정 | 신규 서비스 필수 |

**로깅 표준 3-appender**: CONSOLE + FILE(롤링: 크기·시간 병용, 보존 상한 명시) + ERROR_FILE(WARN 이상 필터). 로깅 설정 없이 기동하면 로그 디렉토리가 생기지 않아 운영에서 로그 유실 위험 — 신규 서비스 스캐폴딩 시 배너·로깅부터 배치한다. 필수 로거: 서비스 베이스 패키지, 데이터 접근 계층, 프레임워크 코어 (INFO).
