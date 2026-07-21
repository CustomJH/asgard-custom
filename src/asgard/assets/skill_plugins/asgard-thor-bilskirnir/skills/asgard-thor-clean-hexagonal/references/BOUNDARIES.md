# Clean·Hexagonal 경계 정본

## 같은 중심, 다른 어휘

- Clean Architecture의 dependency rule: source dependency는 바깥의 mechanism에서 안쪽의 policy로만 향한다.
- Hexagonal Architecture의 ports/adapters: application 내부가 port를 정의하고, 바깥 adapter가 프로토콜·DB·SDK를 그 port에 맞춘다.
- 둘을 함께 쓸 때 domain/application이 안쪽이고 adapter/framework가 바깥이다. 둘을 별도 계층 세트로 중복 구현하지 않는다.

## 최소 경계표

| 영역 | 소유 | 허용 | 금지 |
|---|---|---|---|
| domain | entity, value object, 업무 불변식 | 표준 라이브러리·domain 타입 | web/ORM/SDK import |
| application | use case, input/output, outbound port | domain·자기 port | concrete DB/API client |
| inbound adapter | HTTP/CLI/queue 변환 | application input port 호출 | 업무 규칙·직접 DB |
| outbound adapter | repository/gateway 구현과 매핑 | application port 구현 | domain 정책 결정 |
| composition root | 생성·설정·결선 | 모든 concrete adapter | 업무 규칙 |

port는 경계마다 자동 생성하지 않는다. 교체·격리해야 하는 I/O 또는 같은 능력의 구현이 둘 이상일 때만 둔다. 순수 함수 호출을 interface로 감싸는 것은 경계가 아니라 간접층이다.

## 흐름과 의존 방향

```text
request/event -> inbound adapter -> use case -> domain
                                      |
                                      v
                                 outbound port <- outbound adapter -> DB/API/queue

composition root: adapter를 생성해 port에 결선
source dependency: adapter -> application -> domain
```

제어 흐름이 바깥으로 나가도 source dependency는 안쪽 port를 향한다. application이 adapter 클래스 이름을 import하면 역전이 실패한 것이다.

## 구조 예시

프로젝트의 기존 package/module 관례를 우선한다. 새 구조가 필요할 때만 feature 단위로 최소 배치한다.

```text
orders/
  domain/              # Order, 정책
  application/         # CreateOrder, OrderRepository port
  adapters/inbound/    # HTTP/queue 변환
  adapters/outbound/   # DB/payment 구현
  composition.py       # 또는 framework-native config
```

전역 `domain/`, `application/`, `adapters/`가 기능 변경을 여러 최상위 폴더로 흩뜨리면 feature-first가 낫다. 기존 모듈식 레이어드 구조가 응집돼 있으면 폴더를 옮기지 않고 import 방향만 봉인한다.

## 수직 슬라이스 마이그레이션

1. 기존 동작을 characterization test로 고정한다.
2. handler/controller의 업무 분기를 plain input/output use case로 옮긴다.
3. use case가 직접 쓰는 DB/SDK 호출 한 개를 capability port로 추출한다.
4. 기존 구현을 outbound adapter로 연결한다.
5. composition root에서만 concrete 구현을 생성한다.
6. domain/use case 단위 테스트와 adapter integration test를 실행한다.
7. 한 슬라이스가 안정된 뒤 다음 슬라이스로 반복한다.

기존 API·DB 계약은 이 과정에서 바꾸지 않는다. 구조 변경과 동작 변경을 한 diff에 섞지 않는다.
