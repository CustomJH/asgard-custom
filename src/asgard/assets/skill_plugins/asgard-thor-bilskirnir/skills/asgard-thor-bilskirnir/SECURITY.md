# 백엔드 보안 정책

## 인증

- **토큰**: 서명 시크릿은 환경 주입(`${JWT_SECRET}`), 최소 256비트. 액세스 단기(시간 단위) + 리프레시 장기(일 단위) 분리.
- **패스워드**: 최소 8자, 대·소문자+숫자+특수문자, 적응형 해시(BCrypt strength 12 급). 평문·가역 암호화 금지.
- **역할 위계**: `ADMIN > MANAGER > USER > GUEST` 형태로 명시적 위계 선언.

## 인가 (인증과 구분한다)

```java
@PreAuthorize("hasRole('ADMIN')")
@PreAuthorize("hasRole('MANAGER') or #userId == authentication.principal.id")
@PreAuthorize("@permissionService.canAccess(#projectId)")
```

리소스 접근마다 객체 소유권 검사 — 역할 검사만으로는 IDOR 를 막지 못한다.

## 입력 검증 (서버가 최종)

```java
public record UserCreateRequest(
    @NotBlank @Email String email,
    @NotBlank @Size(min = 8, max = 100)
    @Pattern(regexp = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d).*$") String password
) {}
```

## SQL 인젝션

| DO | DON'T |
|---|---|
| `WHERE email = #{email}` (바인딩) | `WHERE email = '${email}'` (보간) |

## 보안 헤더·CORS

- 헤더: content-type options, frame deny, CSP(`default-src 'self'` 기점).
- CORS: 오리진 allowlist 명시(와일드카드 금지), 허용 메서드 열거, credentials 사용 시 특히 엄격히.

## 민감 데이터

- **로그 금지**: 패스워드, API 키, 토큰, 개인정보. 필요 시 마스킹(`j***@example.com`).
- **환경 주입**: `${DB_PASSWORD}`, `${JWT_SECRET}` — 환경변수 명명은 `{CATEGORY}_{NAME}` (`DB_HOST`, `JWT_SECRET`, `API_BASE_URL`).

## 시크릿 배치표

| 위치 | 허용 | 금지 |
|---|---|---|
| `application-{profile}.yml` | `${ENV_VAR}` 참조 | 하드코딩 값 |
| `.env` / `.env.example` | 키 이름 정의 (실값은 gitignore) | git 커밋 |
| `{project}-fe/**` (프론트엔드) | **없음** | 모든 키·시크릿·토큰 |
| `{project}-be-service/config/` | 타입 세이프 설정 바인딩 | 인라인 크리덴셜 |

**CRITICAL**: 프론트엔드 코드는 브라우저로 배포된다. 외부 서비스 크리덴셜은 ① 환경변수로 저장 ② 백엔드만 읽고 ③ 설정 파일에서 `${ENV_VAR}` 참조 — 전체 경계는 `INTEGRATION.md`.

## 보안 체크리스트

- [ ] 토큰 시크릿 256비트+, 환경 주입
- [ ] 패스워드 적응형 해시
- [ ] SQL 바인딩만 사용 (보간 0건)
- [ ] CORS 오리진 allowlist
- [ ] 보안 헤더 설정
- [ ] 민감 데이터 로그 0건
- [ ] 레이트리밋 적용
- [ ] 서버측 입력 검증
- [ ] 의존성 최신화
- [ ] 시크릿은 환경변수·백엔드 설정만 (프론트엔드 0건)
- [ ] 외부 서비스 호출은 백엔드 경유만
