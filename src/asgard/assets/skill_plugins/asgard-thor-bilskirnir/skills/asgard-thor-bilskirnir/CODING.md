# 백엔드 코딩 컨벤션 (JVM 정본)

## 스타일

들여쓰기 4, 최대 줄 120, 중괄호 같은 줄. import 순서: `java` → `jakarta` → 프레임워크 → `com.{company}` → static (와일드카드 금지 수준의 높은 임계).

## 명명

| 대상 | 규칙 | 예 |
|---|---|---|
| 클래스·인터페이스 | PascalCase | `UserService` |
| 메서드·변수 | camelCase | `findByEmail()` |
| 상수 | UPPER_SNAKE | `MAX_RETRY_COUNT` |
| 패키지 | 소문자 | `com.{company}.{project}.logic` |

클래스 내부 순서: static 필드 → final 필드 → 기타 필드 → 생성자 → public 메서드 → private 메서드.

## 금지 패턴표 (NEVER / ALWAYS)

| 범주 | 금지 | 대신 |
|---|---|---|
| 모듈 의존 | domain → store/service/boot | boot → service → store → domain 단방향 |
| DI | 필드·세터 주입 | 생성자 주입 (`private final` + 생성자 자동 생성) |
| 응답 | 맨 `ApiResponse<T>`, `Map<String, Object>` | `ResponseEntity<ApiResponse<T>>` |
| 트랜잭션 | 컨트롤러·private 메서드에 선언 | 서비스 로직 계층, 조회는 읽기 전용 명시 |
| 보안 | 하드코딩 시크릿, 문자열 보간 쿼리 | 설정 주입(`@Value`/환경), 파라미터 바인딩 |
| 메시지 | 하드코딩 문자열 | i18n 메시지 키 |
| 로깅 | `System.out`, `e.printStackTrace()` | 로거 (`log.info()` 등) |
| 엔티티 | 무차별 `@Data`(민감 필드 노출) | 민감 필드 `@ToString.Exclude` |

## DTO — record 우선

```java
// 요청: 검증 어노테이션 동반
public record UserCreateRequest(
    @NotBlank @Email String email,
    @NotBlank @Size(min = 8) String password
) {}

// 응답: 엔티티→DTO 정적 팩토리
public record UserResponse(Long id, String email, LocalDateTime createdAt) {
    public static UserResponse from(User user) {
        return new UserResponse(user.getId(), user.getEmail(), user.getCreatedAt());
    }
}
```

## 예외

도메인 예외는 공통 베이스(`BusinessException` + `ErrorCode`)를 상속하고 문맥을 담는다.

```java
public class UserNotFoundException extends BusinessException {
    public UserNotFoundException(Long id) {
        super(ErrorCode.USER_NOT_FOUND, "User not found: " + id);
    }
}
```

## 로깅 레벨

| 레벨 | 용도 |
|---|---|
| ERROR | 복구 불가 오류 |
| WARN | 복구 가능 이상 |
| INFO | 비즈니스 이벤트 |
| DEBUG | 개발 진단 |

## Null 처리

조회 결과는 `Optional`, 계약은 `@NotNull`/`@Nullable` 명시, 생성자 필수 인자는 `Objects.requireNonNull()`.

## 주석 — 이중 언어 (혼재 언어 팀 정책)

신규·수정 주석은 **`English / 한국어`** 한 줄 병기. 한국어 단독 금지, 두 줄 분리 금지.

| 형태 | 예 |
|---|---|
| 한 줄 | `// Validate token / 토큰 검증` |
| 줄 끝 | `int retry = 3;  // Max retries / 최대 재시도` |
| 블록 첫 줄 | `/** Authenticate user / 사용자 인증 */` |
| TODO | `// TODO: Add cache / 캐시 추가 (#42)` |

- 코드로 의도가 명확하면 주석 자체를 생략한다.
- 비활성화 마커: `// Disabled 2026-05-07 / 2026-05-07 비활성화` — 원본 주석은 보존.
- 기존 한국어-only 주석은 해당 블록을 만질 때만 양식 변환 (일괄 sweep 금지).
