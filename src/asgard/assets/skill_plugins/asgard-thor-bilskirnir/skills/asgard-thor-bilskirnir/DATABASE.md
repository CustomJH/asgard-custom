# 데이터베이스 설계 정책

## 표준 컬럼 (전 테이블 공통)

```sql
id              BIGINT AUTO_INCREMENT PRIMARY KEY,
created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
created_by      BIGINT,
updated_by      BIGINT
```

## 타입 표

| 타입 | 용도 |
|---|---|
| BIGINT | ID |
| VARCHAR(255) | 짧은 문자열 |
| TEXT | 긴 텍스트 |
| TIMESTAMP | 일시 (UTC 저장) |
| BOOLEAN | `is_` 접두 |
| DECIMAL(10,2) | 금액 (FLOAT 절대 금지) |

## DB 명명

| 대상 | 규칙 | 예 |
|---|---|---|
| 테이블 | 소문자 snake_case 복수형 | `users`, `user_roles` |
| 컬럼 | 소문자 snake_case | `user_id`, `created_at` |
| PK | `id` | `id BIGINT` |
| FK | `{table}_id` | `user_id` |
| 인덱스 | `idx_{table}_{col}` | `idx_users_email` |
| 유니크 | `uk_{table}_{col}` | `uk_users_email` |

## 외래키

```sql
CONSTRAINT fk_task_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
```

| 액션 | 용도 |
|---|---|
| CASCADE | 부모 삭제 시 자식 동반 삭제 |
| SET NULL | 삭제 시 NULL 처리 |
| RESTRICT | 자식 존재 시 삭제 차단 |

## 인덱스 지침

대상: PK(자동), FK, WHERE 컬럼, ORDER BY, JOIN 조건. 근거 없는 선제 인덱스 금지 — 실측 쿼리 계획이 근거다 (데이터 안전 오버레이 참조).

## 매퍼 패턴 (SQL 매퍼 스택 정본)

```java
@Mapper
public interface UserMapper {
    Optional<User> findById(Long id);
    List<User> findAll(UserSearchCriteria criteria);
    void insert(User user);
    void update(User user);
}
```

```xml
<select id="findAll" resultMap="userResultMap">
    SELECT * FROM users
    <where>
        <if test="email != null">AND email LIKE CONCAT('%', #{email}, '%')</if>
    </where>
    ORDER BY created_at DESC LIMIT #{size} OFFSET #{offset}
</select>
```

바인딩은 항상 `#{name}` — `${name}` 문자열 보간은 SQL 인젝션이다 (동적 컬럼명 등 불가피하면 allowlist 검증 후).

## 마이그레이션 룰

- 기존 마이그레이션 파일은 절대 수정하지 않는다 — 새 파일로.
- 변경 1건 = 마이그레이션 1개.
- 롤백을 테스트한다. 롤백 계획 없는 마이그레이션은 미완성이다.
- 명명: `V1.0__create_users_table.sql`.
- 스키마 변경 실행 절차(expand-contract·백필·락 추정)는 데이터 안전 오버레이(`asgard-thor-jarngreipr`)를 합성 로드해 따른다.

## 다중 DB 대응

동일 스키마를 복수 DB 벤더로 서빙하면 매퍼 XML 을 벤더별 디렉토리로 분리한다 (`mapper/h2/`, `mapper/postgres/` …). 개발용 인메모리 DB 는 운영 벤더 호환 모드로 기동한다.
