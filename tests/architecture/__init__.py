"""아키텍처 계층 규칙 — 계층형(도메인 패키지 변형) 의존 방향을 코드로 강제한다.

실행: uv run pytest tests/architecture

계층 (아래가 하위 — 상위는 하위만 임포트할 수 있다):
  foundation   settings·platform·theme·ui·i18n·io_journal·io_files·io_sqlite·registry — 무의존 기반
  providers    providers·openai_codex — 외부 LLM/자격 인프라
  domain       memory군·skill_bank·lagom·charter·manual·code_map·health·surface·craft·thor_gate·tutor·evolution·templates·hooks — 비즈니스 규칙
  application  agent — 오케스트레이션 (Heimdall/Trinity/세션)
  interface    cli·commands — 진입점·표면

계층 하나로는 부족하다. domain 에만 최상위 이름이 46개라, 계층 비교만으로는 그 사이 결합이
전부 무규칙으로 통과한다. 실측(모듈 레벨 내부 임포트 527건 기준): 계층 규칙이 판정하던 것은
171건(32.4%)뿐이고, 285건(54.1%)은 같은 최상위 이름이라 건너뛰고, 71건(13.5%)은 같은 계층이라
부등호를 그냥 통과했다. 그 71건 중 65건이 domain 안이다 — 결합이 나빠져도 규칙이 안 빨개지는
자리가 거기였다.

그래서 계층마다 **등급(SUBTIERS)** 을 둔다. 같은 계층 안에서도 아래 등급만 부를 수 있고,
**같은 등급끼리도 못 부른다**. 새 결합을 만들려면 등급표를 고치고 왜 올렸는지를 그 자리에
적어야 한다 — 그 편집이 없으면 새 결합은 못 생긴다. 이 강제로 같은 계층 엣지 71건이 전부
판정 대상이 되고, 커버리지는 242/527(45.9%)이 됐다.

남은 285건(54.1%)은 같은 최상위 이름 안쪽, 즉 패키지 내부였다. 규칙이 최상위 이름만 보고
같으면 건너뛰었으므로 패키지 안에서는 무엇이 무엇을 불러도 통과했고, 이 저장소에서 가장 큰
덩어리가 전부 패키지라(memory 18모듈·commands 35자식·templates 23·hooks 21·agent 16) 안 재는
쪽이 코드의 대부분이었다. 그래서 같은 기계를 한 단 더 안으로 넣는다 — **PACKAGE_TIERS**.
단위는 직속 자식(모듈·서브패키지·파사드)이고, 부등호는 위와 같이 엄격하다. 깊은 자리는 그
자리의 층에서 재므로 한 임포트가 두 번 세지지 않는다. 이제 285건이 전부 판정 대상이 되고,
커버리지는 45.9% → **100%(미판정 0건)** 이다.

100% 는 "모든 상시 임포트가 어떤 규칙의 부등호를 지난다"는 뜻이다. 규칙 밖에 남는 것은
설계로 남긴 둘뿐이고 이유가 같다 — 함수 안 lazy 임포트와 `if TYPE_CHECKING:` 본문은 안 돈다.
숫자는 실측 시점의 스냅샷이지 불변식이 아니다 — 비율이 어디서 오는지를 읽으라고 적는다.

규칙은 **임포트할 때 실제로 도는 임포트**에만 적용한다 — 함수 내부 lazy import는 의도된
탈출구다(예: repl → commands.update의 /update 실행, evolution → agent.session의 LLM 클라이언트).
`tree.body` 직접 자식만이 아니라 `try:`·`if`·클래스 본문 아래까지 전부 본다: 들여쓰기 한 칸으로
비껴갈 수 있으면 규칙이 아니다. `if TYPE_CHECKING:` 본문만 예외인데, 이유가 다른 예외와 같다 —
안 돈다. 새 상시 결합이 상향으로 생기면 이 테스트가 막는다.

hooks/ 는 별도 불변식: `.claude/hooks/`로 단일 파일 복사 배포되는 계약이므로 상대 임포트는
금지, asgard 절대 임포트는 try 안 lazy(미설치 시 fail-open 되는 선택적 강화)만 허용된다.
"""
