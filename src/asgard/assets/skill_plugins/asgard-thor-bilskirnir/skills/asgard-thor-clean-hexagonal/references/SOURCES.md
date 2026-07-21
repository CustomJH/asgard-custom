# 조사 근거 — 2026-07-21 스냅샷

## 1차 출처

- Alistair Cockburn, *Hexagonal Architecture* (2005): https://alistair.cockburn.us/hexagonal-architecture — inside/outside 비대칭을 port와 adapter로 격리하고 application을 UI·DB 없이 구동·테스트하는 원형.
- Robert C. Martin, *The Clean Architecture* (2012): https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html — dependency rule, entity/use case/adapter/framework 경계, 안쪽에 편한 단순 데이터만 통과시키는 규칙.

## 조사한 에이전트 스킬

- `affaan-m/everything-claude-code@hexagonal-architecture` — 4.4K installs, MIT, revision `5deee34c93395045b985e3baf91550e5f1ab7204`. 다중 언어 port/adapter, composition root, 수직 슬라이스 migration과 boundary별 테스트가 강점.
- `wondelai/skills@clean-architecture` — 4K installs, MIT, revision `ed2930cf8496336641441eef513ad2ad857b65a1`. dependency rule, component/boundary 진단과 infrastructure 누수 탐지가 강점.
- `wondelai/skills@domain-driven-design` — 4.1K installs, 같은 revision. bounded context, aggregate, ubiquitous language를 architecture 경계 선택에 보강.
- `affaan-m/everything-claude-code@architecture-decision-records` — 4.9K installs, 같은 ECC revision. 중요한 구조 선택 기록에 유용하지만 Asgard의 프로젝트 기록/승인 흐름과 겹치므로 런타임 스킬로 복제하지 않는다.

외부 본문은 번들하지 않았다. 중복 스킬 네 개를 매번 노출하는 대신 원저자 불변식과 검증 절차를 이 자체 스킬에 재서술하고, Asgard 기존 `bilskirnir`·`hlidskjalf`·Thor 실천 스킬과 합성한다.
