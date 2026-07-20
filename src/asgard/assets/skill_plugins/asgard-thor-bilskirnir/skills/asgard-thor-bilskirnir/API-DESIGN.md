# REST API 설계 정책

## URL·메서드

베이스: `/api/v{version}/{resource}` (예: `/api/v1/users`)

```
GET    /api/v1/users           # 목록
GET    /api/v1/users/{id}      # 단건
POST   /api/v1/users           # 생성
PUT    /api/v1/users/{id}      # 수정
DELETE /api/v1/users/{id}      # 삭제
```

쿼리 파라미터 표준: `page`, `size`, `sort`(예: `sort=name,asc`), `filter`, `search`/`q`, `include`.

## 응답 봉투 (전 엔드포인트 단일 형태)

```json
// 성공 (단건)
{ "resultCode": 200, "resultMsg": "OK", "when": "2024-01-15T10:30:00", "payload": { "id": 1 } }

// 성공 (목록 + 페이지네이션)
{ "resultCode": 200, "resultMsg": "OK", "when": "…",
  "payload": { "content": [], "page": { "number": 0, "size": 20, "totalElements": 100, "totalPages": 5 } } }

// 결과 없음
{ "resultCode": 201, "resultMsg": "No Data", "when": "…", "payload": null }

// 검증 실패
{ "resultCode": 420, "resultMsg": "Mandatory Param Error", "when": "…",
  "payload": { "field": "email", "message": "must be valid" } }

// 서버 오류
{ "resultCode": 500, "resultMsg": "Internal Server Error", "when": "…", "payload": null }
```

## 이중 층위 — HTTP 상태(프로토콜) ≠ resultCode(비즈니스)

HTTP 상태는 전송 층위(200/201/204/400/401/403/404/422/500), resultCode 는 비즈니스 판정이다. 역할이 다르므로 하나로 뭉개지 않는다.

### ResultCode 카탈로그

| Enum | Code | Message (EN) | Message (KO) | 용도 |
|---|---|---|---|---|
| RC200 | 200 | OK | 성공 | 성공 |
| RC201 | 201 | No Data | 검색 결과 없음 | 빈 결과 |
| RC400 | 400 | Bad Request | 요청 실패 | 잘못된 요청 |
| RC401 | 401 | Login Failed | 로그인 실패 | 인증 실패 |
| RC401_1 | 401 | Not Valid Token | 유효하지 않은 토큰 | 만료·위조 토큰 |
| RC403 | 403 | Forbidden | 접근 권한 없음 | 인가 거부 |
| RC404 | 404 | Not Found | 존재하지 않는 엔티티 | 리소스 없음 |
| RC405 | 405 | Method Not Allowed | 잘못된 Http Method | 메서드 오류 |
| RC408 | 408 | Request Timeout | 요청 응답 없음 | 타임아웃 |
| RC409 | 409 | Conflict | 상태 동일하여 변경 불가 | 상태 충돌 |
| RC420 | 420 | Mandatory Param Error | 필수 파라미터 오류 | 필수 값 누락 |
| RC421 | 421 | Invalid Param Error | 지원하지 않는 파라미터 | 미지원 파라미터 |
| RC422 | 400 | Mandatory Header Error | 필수 헤더 미입력 | 헤더 누락 |
| RC430 | 430 | Query Failed | 조회 실패 | 조회 실패 |
| RC431 | 431 | Registration Failed | 등록 실패 | 등록 실패 |
| RC432 | 432 | Generation Failed | 생성 실패 | 생성 실패 |
| RC433 | 433 | Modification Failed | 수정 실패 | 수정 실패 |
| RC434 | 434 | Removal Failed | 삭제 실패 | 삭제 실패 |
| RC500 | 500 | Internal Server Error | 서버 내부 오류 | 서버 오류 |

## 컨트롤러 반환 패턴

컨트롤러는 반드시 `ResponseEntity<ApiResponse<T>>` 를 반환한다. 맨 `ApiResponse<T>` 나 `Map<String, Object>` 반환 금지. 예외: 전역 예외 핸들러만 `ResponseEntity` 를 직접 조작해 에러 HTTP 상태를 매핑한다.

| 메서드 | 반환 | HTTP |
|---|---|---|
| GET | `ResponseEntity.ok(ApiResponse.success(data))` | 200 |
| POST (생성) | `ResponseEntity.status(CREATED).body(ApiResponse.success(data))` | 201 |
| POST (액션) | `ResponseEntity.ok(ApiResponse.success(data))` | 200 |
| PUT/PATCH | `ResponseEntity.ok(ApiResponse.success(data))` | 200 |
| DELETE | `ResponseEntity.ok(ApiResponse.success(null))` | 200 |

## API 문서 주석 — 이중 언어 (혼재 언어 팀 정책)

문서화 어노테이션(`@Tag`, `@Operation` 류)은 **"English / 한국어"** 병기.

| 항목 | 규칙 | 예 |
|---|---|---|
| 태그 이름 | 영어 단어 | `"Auth"` |
| 태그 설명 | `"영어 / 한국어"` | `"Authentication / 인증"` |
| 동작 요약 | `"영어 동작 / 한국어 동작"` | `"Login / 로그인"` |

한국어만·영어만 단독 사용 금지 — API 문서는 국문·영문 혼재 팀이 열람한다.

## 인증·부가 헤더

- 인증: `Authorization: Bearer <token>`, 갱신 엔드포인트 별도 (`POST /api/v1/auth/refresh`).
- 레이트리밋 노출: `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`.
