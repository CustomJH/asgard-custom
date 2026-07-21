# 경계 검증 도구 선택

도구는 저장소에 이미 설치·설정된 것을 먼저 쓴다. 아래 이름이 manifest/config/CI에 없으면 새 의존성을 넣지 말고 현재 테스트와 표준 도구로 봉인한다.

## 공통 탐색

```sh
rg -n "^(from|import) |require\(|from ['\"]" src
rg -n "Controller|Handler|UseCase|Repository|Gateway|Adapter|Port" src tests
rg -n "ArchitectureTest|import-linter|pytestarch|ArchUnit|Deptrac|NetArchTest|madge" .
```

문자열 검색은 후보 탐색이다. 최종 판정은 언어 parser/compiler 또는 기존 architecture test로 한다.

## 기존 도구가 있을 때

| 생태계 | 발견 신호 | 좁은 실행 예 |
|---|---|---|
| Python | `.importlinter`, `import-linter` | `uv run lint-imports` 또는 프로젝트 러너 |
| Python | `pytestarch`·architecture test | 해당 `pytest` 파일만 실행 |
| JVM | `ArchUnit`, `*ArchitectureTest` | Gradle/Maven의 해당 테스트만 실행 |
| .NET | `NetArchTest`, architecture test project | `dotnet test --filter Architecture` |
| PHP | `deptrac.yaml` | `vendor/bin/deptrac analyse` |
| JS/TS | `madge` dependency/config | 프로젝트 script 또는 `npx madge --circular src` |
| Go | compiler package graph | `go test ./...`; 필요 시 `go list -deps ./...` |
| Rust | Cargo package graph | `cargo test`; 필요 시 `cargo tree` |

정확한 명령은 package script, Makefile, CI workflow에서 복원한다. 기억으로 새 명령을 발명하지 않는다.

## 최소 봉인

도구가 없으면 기존 테스트 프레임워크에 경계 1개만 봉인한다.

- domain/application package가 framework·ORM·adapter package를 import하지 않는다.
- composition root 이외의 application 코드가 concrete adapter를 생성하지 않는다.
- use case 테스트가 web server·DB 없이 실행된다.

정적 import 테스트가 언어의 동적 import를 못 보면 미검증 영역으로 명기한다. PASS로 뭉개지 않는다.
