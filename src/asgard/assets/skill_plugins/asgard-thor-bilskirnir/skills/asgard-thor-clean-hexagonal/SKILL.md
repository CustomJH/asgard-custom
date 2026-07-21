---
name: asgard-thor-clean-hexagonal
description: 토르의 선택형 Clean Architecture·Hexagonal(Ports and Adapters) 적용 스킬. 사용자가 Clean Architecture, Hexagonal 또는 Ports and Adapters를 명시적으로 요구했을 때만 로드해 use case·port·adapter·composition root 경계를 설계·리팩터링한다. 명시가 없으면 이 스킬을 쓰지 않고 빌스키르니르의 기본 4레이어를 유지한다.
---

# Thor Clean + Hexagonal

이 스킬은 **명시적 opt-in**이다. 기본 백엔드 아키텍처는 `asgard-thor-bilskirnir`의 4레이어다. 사용자가 Clean Architecture·Hexagonal·Ports and Adapters를 직접 지정하지 않았으면 여기서 멈추고 기본 4레이어를 적용한다.

## 선택 게이트

1. 요청에 **Hexagonal/헥사고날/Ports and Adapters/포트와 어댑터**가 명시되면 Hexagonal을 적용한다.
2. 요청에 **Clean Architecture/클린 아키텍처**가 명시되면 Clean의 dependency rule을 따르고 Hexagonal의 port/adapter로 경계를 구현한다.
3. 둘 다 없으면 `asgard-thor-bilskirnir`의 4레이어를 적용하고 이 스킬을 로드하지 않는다.
4. opt-in이어도 진입점 → 업무 규칙 → DB·외부 API의 실제 호출 경로와 import 방향을 먼저 추적하고, 한 수직 슬라이스만 바꾼다. 전체 재작성 금지.

세부 경계와 최소 디렉터리 예시는 `references/BOUNDARIES.md`, 생태계별 검증 도구 선택은 `references/TOOLING.md`, 조사 근거는 `references/SOURCES.md`를 필요한 경우에만 연다.

## 구현 절차

1. **한 수직 슬라이스를 고른다.** 자주 바뀌지만 파급이 작은 endpoint/job 한 개가 기본이다.
2. **경계를 선언한다.** domain=업무 불변식, application=use case+port, inbound adapter=프로토콜 변환, outbound adapter=DB/SDK/queue 변환, composition root=구체 구현 결선.
3. **port는 소비자가 소유한다.** 기술 이름(`PostgresRepository`)이 아니라 필요한 능력(`OrderRepository`)으로 정의한다. 모든 클래스에 interface를 만들지 않는다.
4. **경계 데이터는 단순하게 둔다.** HTTP request, ORM row, SDK response를 domain/application 안으로 넘기지 않고 adapter에서 매핑한다.
5. **기존 adapter를 보존하며 잘라 옮긴다.** characterization test → use case 추출 → outbound port → adapter 위임 순서로 한 슬라이스씩 이동한다. big-bang 재작성 금지.
6. **결선은 한 곳에 둔다.** composition root 밖에서 concrete adapter를 즉흥 생성하거나 service locator/global singleton으로 숨기지 않는다.

## 검증과 스킬 합성

- domain/use case는 프레임워크·DB 없이 테스트하고, outbound adapter는 실제 인프라 계약 테스트, inbound adapter는 프로토콜 매핑 테스트를 둔다.
- 의존 방향·경계 우회 검증은 `asgard-hlidskjalf`와 필요한 `LAYERING.md`/`BOUNDARIES.md`만 합성한다.
- 기존 하우스 정책은 `asgard-thor-bilskirnir`, 트랜잭션·메시징은 `asgard-thor-mjollnir`, API·외부 호출은 `asgard-thor-lightning`, 스키마 변경은 `asgard-thor-jarngreipr`, 결함 진단은 `asgard-thor-gridarvol`을 겹쳐 적용한다.
- 저장소에 이미 설정된 architecture test/linter가 있으면 실행한다. 없으면 `rg` 호출 경로 추적과 기존 테스트로 검증하며, 이 작업만을 위해 새 의존성을 추가하지 않는다.

## 완료 계약

`아키텍처: Hexagonal | Clean+Hexagonal — 경계: <한 줄>`과 `Specialist trace: skills=<로드한 이름>; resources=<파일 또는 없음>; tools=<실행 명령>; decision=<명시적 요청>`을 남긴다. 경계 테스트 없이 “적용 완료”라고 보고하지 않는다.
