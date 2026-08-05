"""아키텍처 계층 규칙 — 계층형(도메인 패키지 변형) 의존 방향을 코드로 강제한다.

실행: uv run pytest tests/test_architecture.py

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

from __future__ import annotations

import ast
import os
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "asgard")
# 훅과 같은 폴더에 함께 깔리는 공용 라이브러리의 이름. 이름이 곧 임포트 경로라서 상수로 둔다 —
# 여기와 `hooks/__init__.py` 의 `LIBRARY` 가 어긋나면 배포본이 임포트에서 죽는다.
HOOK_LIBRARY = "asgard_hooklib"

LAYERS: list[tuple[str, frozenset[str]]] = [
    (
        "foundation",
        frozenset(
            {
                "settings",
                "platform",
                "theme",
                "ui",
                "i18n",
                "io_journal",
                # activity — 도는 동안의 활동을 한 줄짜리 JSON으로 흘리는 자리. io_journal 과
                # 같은 성격(무의존 append-only 기록)이라 같은 층에 둔다. 위로 못 올리는 이유가
                # 있다: 세션·오케스트레이터·명령 계층이 전부 이걸 부르므로, 조금이라도 위에
                # 있으면 아래 계층이 자기 활동을 못 적는다.
                "activity",
                "io_files",
                # io_sqlite — sqlite3 접속 계약(WAL·busy_timeout) 한 자리. io_journal·io_files 와
                # 같은 성격이고 실제로 무의존이다(os·sqlite3 만 본다). 이걸 부르는 쪽이
                # memory.index·agent.episodes·studio.db·orchestration.store 처럼 여러 계층에
                # 흩어져 있으므로, 조금이라도 위에 있으면 아래 계층이 DB를 못 연다.
                "io_sqlite",
                "registry",
                # profiles — 에인헤랴르 홈 해석. settings가 이걸 부르므로 settings보다 아래여야
                # 하고, 실제로 무의존이다 (내장 명부만 templates를 lazy로 본다).
                "profiles",
                # runs — asgard 내부 모듈을 임포트하지 않는 기계 단위 실행 등록부라 foundation 기반 등급이다.
                "runs",
                "sandbox",
                "failures",
                # errors — 예외의 정본(코드·처방·상태). failures 와 같은 자리에 둔다: 둘 다
                # 어휘층이고 무의존이다(ui 는 render_cli 안에서만 늦게 본다). 모든 계층이
                # 예외를 던지므로 이보다 위에 두면 아래 계층이 자기 오류를 못 만든다.
                "errors",
                "picker",
                "winterm",
            }
        ),
    ),
    ("providers", frozenset({"providers", "openai_codex", "model_tiers"})),
    (
        "domain",
        frozenset(
            {
                "memory",
                "memory_context",
                "memory_semantic",
                "memory_bridge",
                "project_memory",
                "project_memory_backends",
                "skill_bank",
                "skill_registry",
                "skill_scope",
                "surface",
                "lagom",
                "bragi",
                "charter",
                "manual",  # 커스텀 매뉴얼 — charter와 같은 자리(설정 해석 + 프롬프트 렌더)
                "code_map",
                "health",
                # loop — 컨트롤러. health(센서)·craft_rules(단위) 위에 서고, 고르기만 한다.
                # 센서와 같은 층인 이유는 둘 다 판단을 내리지 않기 때문이다 — 적용은 위층 몫.
                "loop",
                "craft",
                "craft_rules",
                "craft_lex",
                "craft_c",
                # craft_note — 주석 문체 판정. craft_rules(코드 형상)와 같은 층이고 같은 계약을
                # 진다: 순수 함수, 파일 시스템 안 만짐, 래칫은 craft가 건다.
                "craft_note",
                # craft_fix — 판정을 되돌리는 수리 레인. craft_note 옆이다: 규칙을 스스로 갖지
                # 않고 판정기의 사전을 읽어 고칠 수 있는 것만 고친다. 파일을 쓰는 것은 apply()
                # 하나뿐이고 repair()는 순수하다.
                "craft_fix",
                "thor_gate",
                # freyja_gate — 시각 표면의 래칫. craft(형상)·thor_gate(정확성)와 같은 층이고
                # 같은 계약을 진다. 규칙을 스스로 갖지 않고 각 엔진이 배송한 판정기를 부른다.
                "freyja_gate",
                "thor_trail",
                "thor_survey",
                "thor_rules",
                "thor_lex",
                "tutor",
                # review_agent — 튜터 사실을 입력으로 삼되, 오딘 승인 뒤에만 제안을 저장하는
                # 선택형 리뷰 층. 모델 호출은 함수 안 lazy라 domain 경계를 올리지 않는다.
                "review_agent",
                "tutor_probes",
                "tutor_growth",
                # tutor_debt — 인지적 항복의 신호를 세는 계량기. tutor_growth(기록)만 읽고
                # 판정은 tutor 가 소비한다. 여기 있는 이유는 tutor_probes 와 같다: 재기만 하고
                # 무엇을 할지는 안 정한다.
                "tutor_debt",
                # tutor_teach — 이번 변경을 사람에게 **설명하는** 재료(읽는 순서·용어·확인 명령).
                # tutor 는 물음을 만들고 이쪽은 설명을 만든다 — 같은 축의 반대쪽이라 계층이 같다.
                # 판정 등급인 이유는 부등호다: 계측(tutor_probes)을 읽고 적용(tutor)이 이걸 읽는다.
                "tutor_teach",
                "map_context",
                "map_graph",
                # map_lex — 질의 어휘 사전. craft_lex·thor_lex와 같은 자리다: 순수 표이고, 그것을
                # 쓰는 판정(map_context 랭킹)은 위가 아니라 옆에 있다.
                "map_lex",
                # map_notes — 근거 주석 레인. map_graph(관계)와 같은 층의 다른 레인이다:
                # 소스에서 증거를 뽑고, 그것을 어디에 쓸지는 위층이 정한다.
                "map_notes",
                "k6",
                # k6_live·k6_gate·k6_selftest — 다 k6(러너·요약·판정) 하나만 보고 도메인의 다른
                # 이름을 모른다. 레인을 넷으로 가른 이유는 크기가 아니라 묻는 것이다: k6 는 끝난
                # 한 판을 판정하고, k6_live 는 끝나기 전을 적고, k6_gate 는 지난번과 견주고,
                # k6_selftest 는 판정기 자신이 참을 말하는지 표적에 걸어 본다.
                "k6_live",
                "k6_gate",
                "k6_selftest",
                "evolution",
                "evolution_bench",
                "skill_curator",
                "templates",
                # swarm — 프로젝트가 루트의 에이전트를 배치하는 규칙. 설정 해석 + 배치 판정이라
                # charter/manual과 같은 자리이고, agent(application)·commands가 이걸 쓴다.
                "swarm",
                # sessions — profiles(foundation)·swarm(domain 자립)을 읽는 세션 정체성 해석이라 domain 표 등급이다.
                "sessions",
                # automations — io_files(foundation)만 읽는 프로젝트 자동화 규칙과 저장소라 domain 자립 등급이다.
                "automations",
                # studio — 일감(티켓)의 어휘와 규칙, 그리고 그것을 담는 프로젝트 로컬 저장소.
                # memory 군과 같은 자리다: 자기 저장소를 소유하고 규칙만 진다(표면 없음). 위층
                # 셋이 이걸 쓴다 — 창(commands.studio)·CLI(commands.ticket)·툴(agent.tools).
                "studio",
                # plan — 기획 문서 셋(PRD·기능 명세서·유저 플로우)의 형상·검사·저장소. studio와
                # 같은 자리다. 모델 호출(agent.oneshot)은 상향이라 함수 안 lazy 로만 부른다.
                "plan",
                # orchestration — 배차 장부(Run·Task·Dispatch·우편·게이트). studio와 같은 자리다:
                # 자기 SQLite 를 소유하고 규칙만 진다. 실행은 위층(agent.heimdall)이 하고, 이
                # 계층은 무엇이 배차됐고 무엇이 답을 기다리는지만 안다.
                "orchestration",
                # engines — 이 자리에 설정된 엔진이 **지금 실제로 닿는가**. providers(해석)만 보고
                # 도메인 형제를 안 본다. 자동 배치가 이걸 근거로 삼는다: 닿지 않는 엔진에 역할을
                # 앉히면 그건 배치가 아니라 지연된 실패다.
                "engines",
                "hooks",
            }
        ),
    ),
    ("application", frozenset({"agent"})),
    ("interface", frozenset({"cli", "commands", "__main__"})),
]
_RANK = {name: i for i, (layer, names) in enumerate(LAYERS) for name in names}

# 계층 안쪽의 등급 — 같은 계층에 이름이 여럿이면 그 사이에도 방향이 있어야 한다.
#
# 순서는 실제 임포트 방향에서 뽑았다: 등급 n 은 등급 n-1 이하만 부른다. 지금 있는 모듈 레벨
# 엣지 전부가 이 순서로 내려가고, 거스르는 것은 하나도 없다(그래서 이 표는 현행 코드의 서술이지
# 소망이 아니다). 등급 이름은 그 자리에 있는 것들의 다수를 가리킬 뿐이고, **계약은 이름이
# 아니라 순서**다 — 필요하면 이름과 안 맞아도 등급을 올리되 왜 올렸는지를 그 줄에 적는다.
SUBTIERS: dict[str, list[tuple[str, frozenset[str]]]] = {
    "foundation": [
        # 아래로 아무것도 안 본다 — 경로·기록·접속·표·프로필.
        (
            "기반",
            frozenset(
                {
                    "platform",
                    "io_journal",
                    "activity",
                    "io_files",
                    "io_sqlite",
                    "registry",
                    "failures",
                    "profiles",
                    "runs",
                    "winterm",
                }
            ),
        ),
        # 기반을 읽어 "지금 이 기계는 어떤 상태인가"를 만든다. settings→profiles, theme→winterm.
        ("해석", frozenset({"settings", "theme"})),
        # 해석 결과를 사람이 읽는 형태로 만든다. ui→theme·winterm, i18n→settings.
        ("표현", frozenset({"i18n", "ui"})),
        # 표현을 소비한다. picker→ui·theme·i18n, errors→ui(render_cli 안에서 늦게).
        ("표현 소비", frozenset({"errors", "picker"})),
        # sandbox — 격리 판정. picker 로 사람에게 묻는 자리가 있어 표현 소비보다 위다.
        ("격리", frozenset({"sandbox"})),
    ],
    "providers": [
        ("표", frozenset({"model_tiers"})),
        # 벤더 하나의 어댑터. providers 의 공용 헬퍼를 함수 안 lazy 로 되부르는 자리가 있고,
        # 그 상향은 계층 규칙과 같은 관용으로 허용된다.
        ("어댑터", frozenset({"openai_codex"})),
        # 파사드 — 어떤 어댑터를 쓸지 고른다. 그래서 어댑터보다 위다.
        ("파사드", frozenset({"providers"})),
    ],
    "domain": [
        # domain 안에서 아무것도 안 부른다 — 자기 저장소·감지기·사전·설정 해석·배포 산출물.
        # studio·plan·orchestration 이 여기 있는 이유는 크기가 아니라 방향이다: 셋 다 자기
        # SQLite/파일만 알고 domain 의 다른 이름을 모른다.
        (
            "자립",
            frozenset(
                {
                    "health",
                    "hooks",
                    "surface",
                    "memory",
                    "project_memory_backends",
                    "skill_bank",
                    "map_lex",
                    "tutor_growth",
                    "memory_semantic",
                    "skill_scope",
                    "lagom",
                    "bragi",
                    "charter",
                    "manual",
                    "k6",
                    "evolution_bench",
                    "swarm",
                    "thor_trail",
                    "thor_survey",
                    "studio",
                    "plan",
                    "orchestration",
                    "engines",
                    "automations",
                }
            ),
        ),
        # 자립층 하나를 얹는다 — 판정 표(craft_rules→health), 색인(skill_registry→skill_bank),
        # 렌더(templates→hooks), 저장 어댑터 다리(memory_bridge→project_memory_backends).
        # evolution·skill_curator 도 skill_bank 하나만 보므로 같은 자리다.
        # k6_live·k6_gate·k6_selftest 가 여기 있는 것은 이름 때문이 아니라 순서 때문이다 —
        # 자립층의 k6 하나를 얹는다(러너 조립·요약 파싱·판정을 되쓴다). 계약은 이름이 아니라
        # 부등호다.
        (
            "표",
            frozenset(
                {
                    "templates",
                    "craft_rules",
                    "memory_bridge",
                    "skill_registry",
                    "skill_curator",
                    "evolution",
                    "k6_live",
                    "k6_gate",
                    "k6_selftest",
                    "sessions",
                }
            ),
        ),
        # 표를 읽어 한 대상의 뜻을 만든다 — craft_lex·craft_note·thor_rules(규칙 해석),
        # code_map(templates 로 색인), project_memory·memory_context(다리 위 저장소), loop(고르기).
        (
            "해석",
            frozenset(
                {"code_map", "craft_lex", "craft_note", "thor_rules", "loop", "project_memory", "memory_context"}
            ),
        ),
        # 여러 해석을 합쳐 실제 소스를 잰다 — 언어별 어댑터(craft_c)·어휘(thor_lex)·프로브
        # (tutor_probes)·지도 레인(map_graph·map_context·map_notes).
        (
            "계측",
            frozenset({"craft_c", "thor_lex", "tutor_probes", "tutor_debt", "map_graph", "map_context", "map_notes"}),
        ),
        # 계측을 합쳐 결론을 낸다. tutor_teach 가 craft 옆인 이유는 방향이다 — 탐침(tutor_probes)과
        # 기록(tutor_growth)을 읽어 "무엇을 어떤 순서로 읽어야 하는가"를 만들고, 그 결론을
        # 적용 등급의 tutor 가 화면에 넣는다. craft 를 부르지 않는 것이 이 자리의 조건이다.
        ("판정", frozenset({"craft", "tutor_teach"})),
        # 결론을 소비한다 — 막고(thor_gate·freyja_gate) 고치고(craft_fix) 되짚는다(tutor).
        ("적용", frozenset({"craft_fix", "freyja_gate", "thor_gate", "tutor"})),
        # 적용 결과와 튜터의 결정론적 사실을 읽어 승인형 제안 기록으로 만든다. 자동 적용은 없다.
        ("승인형 제안", frozenset({"review_agent"})),
    ],
    "application": [("실행", frozenset({"agent"}))],
    "interface": [
        # 명령 구현. cli 가 이걸 골라 부른다(전부 함수 안 lazy — 시작 시간 때문).
        ("명령", frozenset({"commands"})),
        ("진입", frozenset({"cli"})),
        ("실행 진입", frozenset({"__main__"})),
    ],
}
_SUBRANK = {name: index for tiers in SUBTIERS.values() for index, (title, names) in enumerate(tiers) for name in names}
_SUBTIER_NAME = {name: title for tiers in SUBTIERS.values() for title, names in tiers for name in names}

# 패키지 안쪽의 등급 — 계층·SUBTIERS 와 같은 기계를 한 단 더 안으로 넣는다.
#
# 계층 규칙과 SUBTIERS 는 최상위 이름끼리만 비교한다. 그래서 `asgard.memory` 안의 모듈이
# `asgard.memory` 안의 다른 모듈을 부르면 출발과 도착의 최상위 이름이 같아 그냥 통과했다.
# 실측(모듈 레벨 임포트 527건 기준) 285건(54.1%)이 그 자리였고, 이 저장소에서 가장 큰 덩어리가
# 전부 패키지다 — memory 18모듈·commands 35자식·agent 16·hooks 21·templates 23. 즉 안 재는
# 쪽이 코드의 대부분이었다.
#
# 표의 단위는 **직속 자식**이다: 모듈, 서브패키지 하나, 그리고 파사드(`__init__`). 깊은 자리는
# 그 자리의 층에서 잰다 — `commands/studio/server.py` → `commands/studio/state.py` 는 `commands`
# 가 아니라 `commands.studio` 의 문제이고, 그쪽은 STUDIO_CHAIN 이 본다.
#
# 순서는 실제 임포트 방향의 위상 정렬에서 뽑았다(등급 n = 자기가 부르는 것들의 최고 등급 + 1).
# 그래서 지금 있는 엣지 전부가 이 표를 엄격히 내려가고, 서로 안 부르는 것끼리는 같은 등급에
# 남는다 — 그 사이에 새 결합이 생기면 표를 고쳐야 하고, 그 편집이 결정의 흔적이다.
#
# 파사드(`__init__`)는 언제나 맨 위다. 계산된 깊이가 아니라 위를 고정한 이유가 있다: 안쪽 모듈이
# 자기 패키지 파사드를 부르면 그건 순환이고, 파사드를 위에 두면 그 방향이 항상 위반이 된다.
# 대신 파사드가 무엇을 재수출하든 통과한다 — 파사드는 이 패키지의 가장 바깥 소비자다.
PACKAGE_TIERS: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {
    "memory": (
        # 아무것도 안 부른다 — 설정·게이트(policy), 순수 판정(fence·temporal).
        ("바닥", frozenset({"policy", "fence", "temporal"})),
        ("저장", frozenset({"store", "manager"})),
        # 저장 위의 파생 — 색인·계기·vault·외부 포맷 어댑터. 지워도 정본에서 다시 만든다.
        # graph — 페이지의 링크를 인접 리스트로 펴는 자리. 같은 성격이다: 정본에서 매번
        # 다시 만들고, 지워도 답이 안 바뀐다.
        ("파생", frozenset({"index", "usage", "vault", "okf", "graph"})),
        ("회수", frozenset({"recall"})),
        ("조립", frozenset({"assemble", "pages"})),
        ("쓰기", frozenset({"propose", "contradiction"})),
        ("손질", frozenset({"norn"})),
        # 정본을 통째로 옮기거나(backup) 대화에서 새로 올린다(pattern) — 둘 다 norn 위다.
        ("이식", frozenset({"backup", "pattern"})),
        ("연동", frozenset({"sync"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "agent": (
        (
            "바닥",
            frozenset(
                {
                    "tools",
                    "turn_store",
                    "claude_native",
                    "oneshot",
                    "huginn",
                    "onboard",
                    "prompt_cache",
                    "rate_limit",
                    "compact_lessons",
                    "unit_workspace",
                    # 퀘스트 로그·게이트를 부르는 자리. agent 안의 어느 모듈도 안 부르고 hooks 만
                    # 부르므로 바닥이다 — 루프(heimdall)와 표면(repl)이 여기로 내려온다.
                    "quest_bridge",
                }
            ),
        ),
        ("계약", frozenset({"tool_kernel", "episodes"})),
        ("세션", frozenset({"session", "evicted"})),
        ("루프", frozenset({"heimdall", "repl"})),
        # 표면이 Heimdall을 직접 조립하지 않도록 턴·이벤트 계약을 한곳에 둔다.
        ("실행", frozenset({"runtime"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 도구는 선언(모델이 읽는 스키마)과 구현이 갈라져 있고, 실행 도구는 판정을 먼저 지난다.
    # `guards` 가 `shell`·`patch` 아래인 것이 계약이다 — 실행이 판정을 우회할 방향이 없다.
    "agent.tools": (
        ("바닥", frozenset({"_core", "schemas"})),
        ("판정", frozenset({"guards"})),
        ("실행", frozenset({"shell", "patch", "web", "knowledge", "tickets"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 터미널 — 그리는 것(chrome)과 차례표(catalog)가 바닥이고, 그 위에 입력 재료, 상주 독,
    # 슬래시 명령이 차례로 선다. 파사드에 남은 것은 그것들을 엮는 루프 하나다.
    "agent.repl": (
        ("바닥", frozenset({"chrome", "catalog"})),
        ("재료", frozenset({"editline", "render"})),
        ("상주", frozenset({"dock"})),
        ("명령", frozenset({"commands"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "agent.heimdall": (
        # LLM·IO 없이 판정하거나 상태만 적는 자리.
        ("순수", frozenset({"classify", "journal", "planning", "roles", "todo", "patch_merge", "ticket_lease"})),
        ("선언", frozenset({"toolspec", "bifrost"})),
        ("레인", frozenset({"trinity", "waves", "delivery"})),
        ("코어", frozenset({"core"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # TrinityRun 은 실행 상태 하나를 믹스인 셋이 나눠 진다. 믹스인끼리는 서로를 안 부르므로
    # 같은 등급이고, 그 아래 `_shared` 는 상태를 안 드는 상수·순수 판정만 든다.
    "agent.heimdall.trinity": (
        ("순수", frozenset({"_shared"})),
        ("턴", frozenset({"turns", "verdict", "notes"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # Heimdall 도 같은 형상이다 — 조정자 상태 하나를 면 넷이 나눠 진다.
    "agent.heimdall.core": (
        ("순수", frozenset({"_shared"})),
        ("면", frozenset({"sessions", "recall", "routing", "closing"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 명령 표면 — `_app` 이 루트 Typer 앱과 전역 플래그를 들고, 그룹 모듈은 거기에 자기 명령을
    # 매단다. 그룹끼리는 서로를 안 부른다. `__main__`(python -m asgard.cli)은 파사드와 같은
    # 등급이다 — 둘 다 이 패키지의 가장 바깥이고, 파사드보다 위인 등급은 규칙이 허락하지 않는다.
    "cli": (
        ("바닥", frozenset({"_app"})),
        (
            "그룹",
            frozenset(
                {
                    "root",
                    "review",
                    "agent",
                    "map",
                    "role",
                    "siege",
                    "skills",
                    "memory",
                    "ticket",
                    "evolve",
                    "office",
                    "k6",
                }
            ),
        ),
        ("파사드", frozenset({"__init__", "__main__"})),
    ),
    "commands": (
        # 명령 구현 대부분이 여기다 — 서로를 안 부른다. 같은 등급이라 새로 부르면 빨개진다.
        (
            "명령",
            frozenset(
                {
                    "auth",
                    "budget",
                    "completions",
                    "doctor",
                    "evolve",
                    "health",
                    "humanize",
                    "k6",
                    "loopback",
                    "map",
                    "memory",
                    "mode",
                    "office",
                    "role",
                    "setup",
                    "skills",
                    "start",
                    "studio_store",
                    "ticket_api",
                    "tools",
                    "uninstall",
                }
            ),
        ),
        # 위 셋 중 하나에 기댄다 — health(진단 표면)·loopback(창 경계)·setup(설치)·completions.
        (
            "명령 소비",
            frozenset(
                {
                    "agent",
                    "craft",
                    "init_tui",
                    "manual",
                    "memory_dashboard",
                    # automations — commands.health의 프로젝트 경계 해석을 읽으므로 명령 소비 등급이다.
                    "automations",
                    # orchestrate — 정책·엔진 준비 상태의 표면. tutor 와 같은 자리인 이유도 같다:
                    # 자기는 설정만 읽고 쓰지만 저장소 뿌리를 health 에서 받아 온다.
                    "orchestrate",
                    "plan_api",
                    # review — health의 프로젝트 경계와 review_agent 도메인을 조립하는 승인 표면.
                    "review",
                    # siege(장부 읽기)·siege_act(장부 몰기) — 형제를 안 부른다. 둘 다 저장소 뿌리를
                    # health 에서 직접 받으므로 같은 등급이고, 그래서 서로를 부르면 빨개진다.
                    "siege",
                    "siege_act",
                    "studio",
                    "surface",
                    "sync",
                    "thor",
                    "ticket",
                    "tutor",
                    "update",
                }
            ),
        ),
        # 지금 이 파사드는 형제를 하나도 안 부른다 (cli 가 명령을 함수 안 lazy 로 고르므로).
        ("파사드", frozenset({"__init__"})),
    ),
    # 검사군은 서로를 안 부른다 — 파사드만 전부를 모아 한 화면으로 그린다. 같은 등급이라
    # 검사 하나가 옆 검사를 부르기 시작하면 여기서 빨개진다 (그건 조립기가 할 일이다).
    "commands.doctor": (
        ("검사", frozenset({"memory", "codemap", "gate", "wiring", "engines"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # `_core` 는 승인 계획의 보관·선점과 모든 run_* 가 쓰는 오류 봉투다. `personal` 이 한 단
    # 위인 이유는 하나뿐이다 — 재색인 안내 문구를 `backends` 의 플래그에서 읽는다.
    "commands.memory": (
        ("바닥", frozenset({"_core"})),
        ("표면", frozenset({"autosave", "backends", "evolution", "graph", "hygiene", "project"})),
        ("개인", frozenset({"personal"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "commands.memory_dashboard": (
        ("데이터", frozenset({"data"})),
        ("표면", frozenset({"server"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "commands.plan_api": (
        ("표면", frozenset({"server"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "hooks": (
        # 훅끼리는 여전히 서로를 안 부른다 — 그게 배포 계약이다. 훅은 `.claude/hooks/`로 복사되므로
        # 형제를 이름으로 부르면 복사본에서 죽는다. 같은 등급끼리 금지라 임포트 하나만 생겨도 이
        # 표가 잡는다 (상대 임포트는 test_hooks_are_self_contained 가, 절대 임포트는 여기가 본다).
        #
        # 아래 한 등급이 그 계약의 예외가 아니라 그 계약을 지키는 방법이다: `asgard_hooklib` 은
        # 훅과 **같은 폴더에** 함께 깔리므로 배포본에서도 임포트가 선다. 다만 훅은 그것을 배포
        # 이름(`import asgard_hooklib.…`)으로 부르지 `asgard.hooks.asgard_hooklib` 으로 부르지
        # 않으므로 이 표의 엣지 추출기에는 그 방향이 안 보인다. 보이지 않는 방향은 표가 아니라
        # test_hook_library_only_leans_downward 가 지킨다.
        ("라이브러리", frozenset({"asgard_hooklib"})),
        (
            "훅",
            frozenset(
                {
                    "agent_activate",
                    "budget_guard",
                    "charter_activate",
                    "craft_gate",
                    "failure_tracker",
                    "git_guard",
                    "lagom_activate",
                    "lagom_subagent",
                    "lagom_tracker",
                    "manual_activate",
                    "map_activate",
                    "memory_activate",
                    "quest_log",
                    "readonly_guard",
                    "release_guard",
                    "secret_guard",
                    "subagent_gate",
                    "tutor_note",
                    "unattended_context",
                    "verifier_gate",
                    "write_sentinel",
                }
            ),
        ),
        ("파사드", frozenset({"__init__"})),
    ),
    # 훅이 함께 지고 다니는 공용 라이브러리. 여기 등급은 실측 임포트 방향의 위상 정렬 그대로다
    # (26-08-06: 엣지 26건, 순환 0). 이 패키지가 생긴 이유가 곧 이 표가 필요한 이유다 — 같은
    # 코드가 훅 셋에 사본으로 살던 동안 49개 중 9개가 의미까지 갈라졌고, 사본에는 방향이 없었다.
    "hooks.asgard_hooklib": (
        # 아무것도 안 부른다 — 파일·git 원시 연산, 해시, 증거 술어, 정책 표.
        # siege — 배차 장부에 한 줄 적으라고 CLI 프로세스를 띄우는 문. asgard 를 임포트하지
        # 않는 것이 요점이라(배포 인터프리터에는 없다) 여기 바닥에 선다.
        ("바닥", frozenset({"evidence", "inject", "integrity", "paths", "policy", "siege", "workspace"})),
        # 바닥 하나씩만 얹는다. 서로는 안 부른다.
        ("한 단", frozenset({"ledger", "runners", "scope", "session", "shell", "transition"})),
        ("두 단", frozenset({"contracts", "readonly", "tickets", "tree"})),
        # 실행과 관측 — `summary` 가 아래를 거의 다 부르는 유일한 자리다 (관측을 한 함수로 모은다).
        ("조립", frozenset({"baseline", "summary"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "map_graph": (
        # 증거 모델과 그것만 읽는 조회기들.
        ("증거", frozenset({"evidence", "bridge", "resolve_jvm", "view_legacy"})),
        ("추출", frozenset({"extract_java", "extract_python", "extract_tsjs", "spring_props"})),
        ("그래프", frozenset({"graph"})),
        ("뷰", frozenset({"view"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "memory_bridge": (
        ("소비", frozenset({"client"})),
        ("신뢰", frozenset({"trust"})),
        ("설정", frozenset({"config"})),
        ("표면", frozenset({"server"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "orchestration": (
        # 어휘·순수 판정(model)·SQLite 정본(store)·형상 선택(strategy) — 서로를 안 부른다.
        ("정본", frozenset({"model", "store", "strategy"})),
        # policy — 사용자가 고른 오케스트레이션 정책(auto 포함)을 형상·배치로 옮기는 자리.
        # strategy(형상 선택) 바로 위다: strategy 는 "이 요청이 어떤 모양인가"만 보고, 여기는
        # 거기에 "지금 무엇으로 돌릴 수 있는가"(닿는 엔진)와 사용자 뜻을 얹는다.
        ("정책", frozenset({"policy"})),
        ("장부", frozenset({"board", "mail"})),
        ("배차", frozenset({"dispatch"})),
        # roster — 호출된 에이전트 하나를 Run·Task·Dispatch 로 엮는 조합. 배차 위인 이유는
        # 아래 셋을 순서대로 부르기만 하기 때문이다 — 어느 계약도 바꾸지 않는다.
        ("명부", frozenset({"roster"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "plan": (
        # intake — 온보딩의 축·단계 표와 커버리지 판정. store 아래인 이유는 store 가 이 표로
        # 문서를 검사하기 때문이다: 표가 위에 있으면 정본이 자기 형상을 못 검사한다.
        ("온보딩", frozenset({"intake"})),
        ("정본", frozenset({"store"})),
        # review — PRD 심사. 모델을 안 부르고 문서만 읽는 순수 판정이라 planner 와 나란하지
        # 않고 정본 바로 위다. planner 가 이 판정을 읽는 것은 없고, export 만 읽는다.
        ("판정", frozenset({"review"})),
        # folders — 폴더에 갇혀 있던 기획을 워크스페이스로 들여오는 레인. 정본 위에 서고
        # 지능과 나란하다: 저장소를 읽고 쓰지만 모델을 안 부른다.
        ("지능", frozenset({"planner", "edits", "folders"})),
        ("앉히기", frozenset({"build"})),
        # export — 문서와 심사를 마크다운 한 장으로. 담는 쪽이 아니라 꺼내는 쪽이라 build 와
        # 같은 등급이 아니다.
        ("내보내기", frozenset({"export"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "project_memory": (
        # backend IO 를 모르는 절반 — 정책·토큰화·합성.
        ("순수", frozenset({"records", "terms", "reflect"})),
        ("정본", frozenset({"canonical", "scan", "ingest", "documents"})),
        ("파생", frozenset({"projection", "retain", "evolve", "learning", "automation"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "studio": (
        # mentions — `@이름`을 읽어 에인헤랴르 명부에 맞춰 보는 어휘. 저장소를 안 보고
        # profiles 만 본다(foundation) — vocab 과 같은 자리인 이유가 그것이다.
        ("정본", frozenset({"db", "vocab", "mentions"})),
        # teams — 번호의 주인. projects·tickets 가 팀을 가로지르므로 그 아래다.
        ("팀", frozenset({"teams"})),
        ("축", frozenset({"projects", "tickets", "legacy"})),
        # documents — 티켓과 나란한 글. 프로젝트·팀에 매달릴 수 있어 그 둘 위에 선다.
        ("글", frozenset({"documents"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 티켓 — `_core` 가 "어디까지 보이는가"와 "이 값을 받는가"를 혼자 진다. 읽는 면이 쓰는 면
    # 아래인 것이 방향이다: 쓰고 나서 무엇이 됐는지를 읽지, 읽으면서 쓰지 않는다.
    "studio.tickets": (
        ("바닥", frozenset({"_core"})),
        ("조각", frozenset({"labels", "cycles", "evidence"})),
        ("읽기", frozenset({"views"})),
        ("쓰기", frozenset({"crud"})),
        ("분류", frozenset({"triage"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "templates": (
        # 순수 방출기 — 캐논 본문과 스킬 본문. 서로를 안 부른다.
        (
            "본문",
            frozenset(
                {
                    "agent_models",
                    "bragi",
                    "bridge",
                    "canon",
                    "claude",
                    "comments",
                    "eitri",
                    "lagom",
                    "manual",
                    "map",
                    "memory",
                    "mimir",
                    "seal",
                    "selftest",
                    "siege",
                    "skill_router",
                    "thor",
                    "trinity",
                    "worker",
                }
            ),
        ),
        # 본문을 모아 한 문서로 만든다 — AGENTS.md(agents), 역할 명부(roles).
        ("조합", frozenset({"agents", "roles"})),
        # 역할 명부를 클라이언트 형식으로 옮긴다.
        ("어댑터", frozenset({"codex", "cursor", "freyja"})),
        ("파사드", frozenset({"__init__"})),
    ),
}

# 등급표 대신 다른 규칙이 보는 패키지 — 값은 그 규칙의 이름이다.
PACKAGES_GOVERNED_ELSEWHERE: dict[str, str] = {
    # commands.studio 는 STUDIO_CHAIN 이 전순서로 본다. 등급표를 겹쳐 놓지 않는 이유는 둘이
    # 막는 것이 다르기 때문이다: 사슬은 `snapshot → artifacts` 처럼 손으로 정한 방향까지
    # 막고, 등급은 같은 등급끼리를 막는다. 한 패키지에 규칙 둘을 두면 어느 쪽이 계약인지
    # 아무도 못 말한다 — 그래서 먼저 있던 쪽을 남긴다.
    "commands.studio": "STUDIO_CHAIN",
}

# 등급을 못 세운 패키지 — 값은 이유다. 조용히 빠뜨리는 자리를 없애려고 비어 있어도 남긴다.
#
# 이 표를 둔 이유는 순환이었다: 안쪽에 순환이 있으면 위상 정렬이 안 되고 등급을 못 만든다.
# 실측 결과 순환은 **한 패키지에도 없었다** (직속 자식 단위 Tarjan, 파사드 포함, 17패키지
# 전수). 그래서 지금은 비어 있다. 순환이 생기면 여기 이름과 순환 고리를 적고, 그때 규칙 밖에
# 두는 것은 순환을 고칠 때까지의 임시 상태다.
PACKAGES_WITHOUT_TIERS: dict[str, str] = {}

_PACKAGE_TIER_RANK = {
    pkg: {name: index for index, (_title, names) in enumerate(tiers) for name in names}
    for pkg, tiers in PACKAGE_TIERS.items()
}
_PACKAGE_TIER_TITLE = {
    pkg: {name: title for title, names in tiers for name in names} for pkg, tiers in PACKAGE_TIERS.items()
}

_FACADE = "__init__"


def _module_dotted(path: str) -> list[str]:
    """src/asgard 기준 상대 경로 → 패키지 경로 성분 (파일명 제외 규칙: __init__은 패키지 자신)."""
    rel = os.path.relpath(path, SRC)
    parts = rel.replace(os.sep, "/").removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def _iter_py_files():
    for dirpath, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _resolved_targets(node: ast.stmt, parts: list[str]) -> set[tuple[str, ...]]:
    """import 문 → 임포트 대상의 절대 경로 성분 (`asgard` 접두는 뗀다, 외부 라이브러리는 무시).

    상대(`from .server import X`)와 절대(`from asgard.commands.studio.server import X`)를 한
    자리에서 푼다. 대상 해석기가 하나여야 문법을 바꿔 규칙을 비껴가는 자리가 안 생긴다.
    `from pkg import name` 은 name 이 모듈일 수도 있어 `pkg` 와 `pkg.name` 을 둘 다 낸다 —
    쓰는 쪽이 필요한 깊이만 잘라 본다.
    """
    out: set[tuple[str, ...]] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            bits = alias.name.split(".")
            if bits[0] == "asgard" and len(bits) > 1:
                out.add(tuple(bits[1:]))
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0:
            bits = (node.module or "").split(".")
            if bits and bits[0] == "asgard" and len(bits) > 1:
                base = tuple(bits[1:])
                out.add(base)
                out.update(base + (alias.name,) for alias in node.names)
        else:
            # 상대 임포트 해석 — parts는 파일의 패키지 경로 성분 (파일이 모듈이면 모듈명 포함)
            pkg = parts[:-1] if parts else []  # 담는 패키지 (모듈 파일 기준)
            if node.level - 1 > len(pkg):
                return out
            base = tuple(pkg[: len(pkg) - (node.level - 1)])
            if node.module:
                base = base + tuple(node.module.split("."))
                if base:
                    out.add(base)
            out.update(base + (alias.name,) for alias in node.names)
    return out


def _top_targets(node: ast.stmt, parts: list[str]) -> set[str]:
    """import 문 → asgard 내부 top-level 대상 집합 (외부 라이브러리는 무시)."""
    out = {target[0] for target in _resolved_targets(node, parts) if target}
    return {t for t in out if t in _RANK or t == "assets"}


_FUNCTION_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _is_type_checking_guard(node: ast.AST) -> bool:
    """`if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` 인가 — 본문이 런타임에 안 도는 자리."""
    test = getattr(node, "test", None)
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _module_level_imports(tree: ast.Module) -> list[ast.stmt]:
    """모듈을 임포트할 때 **실제로 도는** import 문. 판정 대상은 이것이고, 들여쓰기가 아니다.

    `tree.body` 직접 자식만 보면 `try: ... except ImportError:` 아래가 규칙 밖으로 빠진다.
    그 자리는 상향 결합이 조용히 들어오는 통로다 — 임포트는 도는데 실패해도 fail-open 이라
    아무 소리가 안 난다. 훅 시험은 이미 try 를 재귀로 훑으므로 같은 파일 안에서 엄밀도가
    갈리지 않게 여기도 맞춘다. `if`/`try`/`with` 와 클래스 본문은 임포트 시점에 도니까 전부
    포함한다.

    빼는 것은 둘뿐이고 둘 다 이유가 같다 — 안 돈다. 함수 안 lazy 임포트(의도된 탈출구)와
    `if TYPE_CHECKING:` 본문이다. 후자는 이 저장소가 순환을 피하려고 고른 형식이고
    (`agent/heimdall/waves.py:25` 가 그 이유를 적어 뒀다), 그 자리를 막으면 남는 선택지는
    타입을 지우는 것뿐이다. `else` 는 실제로 도므로 계속 본다.
    """
    found: list[ast.stmt] = []
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, _FUNCTION_SCOPES):
            continue
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            stack.extend(node.orelse)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
            continue
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found, key=lambda node: (node.lineno, node.col_offset))


def _toplevel_edges():
    """계층 등재 모듈 사이의 모듈 레벨 임포트 전수 → (파일, 행, 출발 최상위, 도착 최상위)."""
    for path in _iter_py_files():
        parts = _module_dotted(path)
        if not parts:  # asgard/__init__.py — 루트 파사드는 규칙 밖 (버전 표면)
            continue
        src_top = parts[0]
        if src_top not in _RANK:
            continue
        rel = os.path.relpath(path, SRC)
        # __init__.py는 패키지 자신이 담는 패키지 — 상대 해석용 성분에 sentinel 추가
        file_parts = (parts + ["__init__"]) if rel.endswith("__init__.py") else parts
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in _module_level_imports(tree):
            for target in _top_targets(node, file_parts):
                if target == "assets" or target == src_top:
                    continue
                yield rel, node.lineno, src_top, target


def _iter_packages() -> list[tuple[str, ...]]:
    """src/asgard 아래 패키지 전수 → dotted 성분. `.py`를 담은 디렉터리면 전부 센다.

    `__init__.py` 존재를 조건으로 걸지 않는다: 그러면 규칙이 재는 범위가 파일 하나의 유무로
    움직이고, 그 파일을 지우는 것만으로 패키지를 규칙 밖으로 뺄 수 있다. assets 는 코드가
    아니라 배포 자료라서 제외한다 (계층 규칙도 같은 이유로 assets 를 통과시킨다).
    """
    out: list[tuple[str, ...]] = []
    for dirpath, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(dirpath, SRC).replace(os.sep, "/")
        if rel == ".":
            continue
        parts = tuple(rel.split("/"))
        if parts[0] == "assets" or not any(f.endswith(".py") for f in files):
            continue
        out.append(parts)
    return sorted(out)


def _package_children(pkg: tuple[str, ...]) -> set[str]:
    """패키지의 직속 자식 — 모듈·서브패키지 + 파사드(`__init__`). 등급표가 덮어야 하는 이름이다."""
    base = os.path.join(SRC, *pkg)
    out = {_FACADE}
    for entry in sorted(os.listdir(base)):
        if entry in ("__pycache__", "__init__.py"):
            continue
        full = os.path.join(base, entry)
        if entry.endswith(".py"):
            out.add(entry.removesuffix(".py"))
        elif os.path.isdir(full) and any(f.endswith(".py") for f in os.listdir(full)):
            out.add(entry)
    return out


def _package_edges(pkg: tuple[str, ...]):
    """패키지 안쪽 모듈 레벨 임포트 전수 → (파일, 행, 출발 자식, 도착 자식).

    깊은 자리는 직속 자식 하나로 접는다: `commands/studio/server.py` 가 `commands/loopback.py`
    를 부르면 `commands` 층에서는 studio → loopback 한 건이고, 같은 자식 안쪽
    (`studio/server.py` → `studio/state.py`)은 `commands.studio` 층에서 잰다. 그래서 한 임포트가
    두 층에서 두 번 세지지 않는다.

    안에서 패키지 자신을 절대 경로로 부른 자리(`from asgard.memory import Foo` in memory/*)는
    파사드로 되돌아오는 엣지로 잡는다 — 형제 모듈 이름이 안 나온 경우만이다. 형제가 나오면
    그건 서브모듈 임포트이고, 그쪽으로 세는 것이 실제 결합을 가리킨다.
    """
    depth = len(pkg)
    children = _package_children(pkg)
    for path in _iter_py_files():
        parts = _module_dotted(path)
        if tuple(parts[:depth]) != pkg:
            continue
        src = _FACADE if len(parts) == depth else parts[depth]
        rel = os.path.relpath(path, SRC)
        file_parts = (parts + [_FACADE]) if os.path.basename(path) == "__init__.py" else parts
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in _module_level_imports(tree):
            targets = _resolved_targets(node, file_parts)
            hits = {
                target[depth]
                for target in targets
                if len(target) > depth and tuple(target[:depth]) == pkg and target[depth] in children
            }
            if not hits and any(tuple(target) == pkg for target in targets):
                hits = {_FACADE}
            for dst in sorted(hits):
                if dst != src:
                    yield rel, node.lineno, src, dst


class TestLayeredArchitecture(unittest.TestCase):
    def test_every_top_module_is_assigned_to_a_layer(self):
        """새 top-level 모듈은 계층 지정 없이 못 들어온다 — 미분류 = 아키텍처 결정 누락."""
        tops = set()
        for entry in os.listdir(SRC):
            if entry in ("__pycache__", "__init__.py", "assets"):
                continue
            if entry.endswith(".py"):
                tops.add(entry.removesuffix(".py"))
            elif os.path.isdir(os.path.join(SRC, entry)):
                tops.add(entry)
        unassigned = tops - set(_RANK)
        self.assertFalse(unassigned, f"계층 미지정 top-level 모듈: {sorted(unassigned)} — LAYERS 에 배치하라")

    def test_every_layer_member_has_a_subtier(self):
        """계층에 이름만 넣고 등급을 안 정하면 그 이름 주변이 다시 무규칙이 된다.

        계층 표에 한 줄 더 적는 것은 싸고, 그래서 domain 이 46개까지 불었다. 등급을 같이
        요구하면 "이게 무엇 위에 서는가"를 넣는 사람이 답하게 된다."""
        problems: list[str] = []
        for layer, names in LAYERS:
            tiers = SUBTIERS.get(layer)
            if tiers is None:
                problems.append(f"{layer} — 등급표(SUBTIERS) 자체가 없다")
                continue
            placed = [name for _, members in tiers for name in members]
            missing = sorted(set(names) - set(placed))
            stray = sorted(set(placed) - set(names))
            twice = sorted({name for name in placed if placed.count(name) > 1})
            if missing:
                problems.append(f"{layer} — 등급 미지정: {missing}")
            if stray:
                problems.append(f"{layer} — 계층에 없는 이름이 등급표에: {stray}")
            if twice:
                problems.append(f"{layer} — 등급이 둘: {twice}")
        unknown = sorted(set(SUBTIERS) - {layer for layer, _ in LAYERS})
        if unknown:
            problems.append(f"계층에 없는 등급표: {unknown}")
        self.assertFalse(problems, "등급표가 계층 표와 어긋난다:\n" + "\n".join(problems))

    def test_no_upward_toplevel_imports(self):
        """상위 계층 방향의 모듈 레벨 임포트 금지 — lazy(함수 내부) 임포트만 예외."""
        violations = [
            f"{rel}:{lineno} — {src_top}({_layer(src_top)}) → {target}({_layer(target)})"
            for rel, lineno, src_top, target in _toplevel_edges()
            if _RANK[target] > _RANK[src_top]
        ]
        self.assertFalse(violations, "상향 계층 임포트 발견:\n" + "\n".join(violations))

    def test_same_layer_imports_go_down_a_subtier(self):
        """같은 계층 안에서도 방향이 있다 — 아래 등급만 부른다, 같은 등급끼리도 안 된다.

        계층 비교만 쓰면 domain 46개 사이의 결합은 전부 통과한다. 그 몫이 이 저장소에서 가장
        빨리 자라는 곳이고, "위반 0"이 구조 건강으로 오독되던 자리다. 같은 등급도 막는 이유는
        새 결합이 표를 안 고치고 생길 수 있으면 표가 기록으로 전락하기 때문이다 — 필요한
        결합이면 등급을 올리고 그 줄에 이유를 적으면 된다. 그 편집이 곧 결정의 흔적이다."""
        violations: list[str] = []
        for rel, lineno, src_top, target in _toplevel_edges():
            if _RANK[target] != _RANK[src_top]:
                continue
            src_tier, dst_tier = _SUBRANK.get(src_top), _SUBRANK.get(target)
            if src_tier is None or dst_tier is None:
                continue  # 등급 미지정은 test_every_layer_member_has_a_subtier 가 이름을 대며 잡는다
            if dst_tier < src_tier:
                continue
            why = "같은 등급" if dst_tier == src_tier else "등급을 거슬러 오른다"
            violations.append(
                f"{rel}:{lineno} — {src_top}[{_SUBTIER_NAME[src_top]}] → {target}[{_SUBTIER_NAME[target]}] ({why})"
            )
        self.assertFalse(
            violations,
            "같은 계층 등급 위반 — SUBTIERS 를 고치고 왜 올렸는지 그 줄에 적어라:\n" + "\n".join(violations),
        )

    def test_hooks_are_self_contained(self):
        """훅 배포 계약 — hooks/*.py는 `.claude/hooks/`에 복사 배포된다 (asgard 설치와 무관하게 돈다).

        따라서 asgard 임포트는 ① 상대 임포트 금지(복사본에서 즉사) ② 절대 `asgard.*` 임포트는
        try 블록 안 lazy만 허용(미설치 환경에서 fail-open 되는 선택적 강화 — 예: code_map 갱신,
        quest 요약). 무방비 임포트가 하나라도 생기면 복사 배포본이 죽는다.

        `asgard_hooklib` 은 이 금지의 예외가 아니다 — asgard 패키지가 아니라 훅과 **같은 폴더에**
        함께 깔리는 사본이라서 배포본에서도 그대로 선다. 다만 저장소 안에서 임포트될 때를 위한
        sys.path 부트스트랩이 그 파일에 함께 있어야 하고, 그 짝을 여기서 본다: 임포트만 있고
        부트스트랩이 없으면 라이브러리 면(`asgard.hooks.<훅>`)이 ImportError 로 죽는다."""
        violations: list[str] = []
        hooks_dir = os.path.join(SRC, "hooks")

        def is_asgard_import(node: ast.AST) -> bool:
            if isinstance(node, ast.ImportFrom):
                return node.level > 0 or (node.module or "").split(".")[0] == "asgard"
            if isinstance(node, ast.Import):
                return any(a.name.split(".")[0] == "asgard" for a in node.names)
            return False

        def scan(node: ast.AST, fname: str, guarded: bool) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ImportFrom) and child.level > 0:
                    violations.append(f"hooks/{fname}:{child.lineno} — 상대 임포트 (복사 배포 즉사)")
                elif isinstance(child, (ast.Import, ast.ImportFrom)) and is_asgard_import(child) and not guarded:
                    violations.append(f"hooks/{fname}:{child.lineno} — try 밖 asgard 임포트 (fail-open 아님)")
                scan(child, fname, guarded or isinstance(child, ast.Try))

        for f in sorted(os.listdir(hooks_dir)):
            if not f.endswith(".py") or f == "__init__.py":
                continue
            src = open(os.path.join(hooks_dir, f), encoding="utf-8").read()
            scan(ast.parse(src), f, guarded=False)
            if HOOK_LIBRARY in src and "sys.path.append(_HOOK_DIR)" not in src:
                violations.append(f"hooks/{f} — {HOOK_LIBRARY} 를 부르는데 sys.path 부트스트랩이 없다")
        self.assertFalse(violations, "훅 자립 계약 위반:\n" + "\n".join(violations))

    def test_hook_library_only_leans_downward(self):
        """공용 라이브러리는 아래만 본다 — 훅을 부르지 않고 asgard 도 부르지 않는다.

        이 방향은 PACKAGE_TIERS 가 못 본다: 훅은 라이브러리를 **배포 이름**(`asgard_hooklib.…`)
        으로 부르므로 엣지 추출기가 `asgard.*` 로 인식하지 않는다. 그 사각을 여기서 막는다.
        거꾸로 라이브러리가 훅 하나를 부르는 순간 배포본은 그 훅이 같이 깔릴 때만 살아나고,
        훅 계약이 fail-open 이라 그 죽음은 조용하다. `asgard.*` 는 훅과 같은 조건으로만 허용한다:
        try 안 lazy — 미설치 환경에서 조용히 꺼지는 선택적 강화(자가발전 채굴·배차 장부)."""
        library_dir = os.path.join(SRC, "hooks", HOOK_LIBRARY)
        hook_modules = {
            f[:-3] for f in os.listdir(os.path.join(SRC, "hooks")) if f.endswith(".py") and f != "__init__.py"
        }
        violations: list[str] = []

        def scan(node: ast.AST, fname: str, guarded: bool) -> None:
            for child in ast.iter_child_nodes(node):
                targets: list[str] = []
                if isinstance(child, ast.ImportFrom) and child.level == 0:
                    targets = [(child.module or "").split(".")[0]]
                elif isinstance(child, ast.Import):
                    targets = [a.name.split(".")[0] for a in child.names]
                for target in targets:
                    if target == "asgard" and not guarded:
                        violations.append(f"{HOOK_LIBRARY}/{fname}:{child.lineno} — try 밖 asgard 임포트")
                    elif target in hook_modules:
                        violations.append(f"{HOOK_LIBRARY}/{fname}:{child.lineno} — 훅({target})을 부른다 (방향 역전)")
                scan(child, fname, guarded or isinstance(child, ast.Try))

        for f in sorted(os.listdir(library_dir)):
            if f.endswith(".py"):
                scan(ast.parse(open(os.path.join(library_dir, f), encoding="utf-8").read()), f, guarded=False)
        self.assertFalse(violations, "공용 라이브러리 방향 위반:\n" + "\n".join(violations))

    def test_hooks_parse_on_old_python(self):
        """훅 문법 바닥 — hooks/*.py는 asgard의 venv가 아니라 그 기계가 내주는 파이썬으로 돈다.

        `platform.hook_python()`의 정본은 이제 `uv run --no-project python`이다 — 설치가 uv
        관리 CPython 위에 서므로 보통은 충분히 새 인터프리터가 온다. 그래도 asgard 자신의
        `requires-python`은 여전히 훅에 대한 보장이 못 된다: uv 가 없는 기계에서는 PATH 의
        python3/py 로 내려가고(패키지 매니저 설치·사내 이미지), 그 파이썬은 낡을 수 있다.
        훅이 최신 문법을 쓰면 거기서 임포트 시점 SyntaxError가 되고, 훅 계약은 fail-open이라
        그 죽음이 **조용하다**: 사용자는 계층이 켜진 줄 알고 아무 일도 안 일어난다.

        실제로 그 자리가 있었다: 괄호 없는 다중 except (PEP 758, 3.14+)가 세 군데 있었고,
        3.13 기계에서는 매뉴얼 계층과 퀘스트 로그가 통째로 증발하는 상태였다.

        바닥은 3.9 그대로 둔다. uv 정본이 인터프리터를 새것으로 끌어올리긴 하지만 그건
        **정본 경로의 성질**이지 폴백 경로의 보장이 아니다 — 바닥을 올리면 그 보장을 uv 부재
        기계에 소급 적용하는 셈이고, 어긋나는 순간의 실패가 조용하다는 성질은 그대로다.
        비용이 없는 벨트라 남긴다. 문법만 본다(`ast`는 실행하지 않는다). 새 문법이 정말
        필요하면 이 상수를 올리되, 그건 훅이 도는 기계의 최소 사양을 올리겠다는 **명시적
        결정**이어야 한다."""
        floor = (3, 9)
        hooks_dir = os.path.join(SRC, "hooks")
        broken: list[str] = []
        # 라이브러리도 같은 바닥을 진다 — 훅이 임포트 첫 줄에서 그것을 부르므로, 여기 문법 하나가
        # 낡은 인터프리터에서 걸리면 그 훅은 통째로 안 돈다 (같은 침묵).
        listing = [(hooks_dir, f) for f in sorted(os.listdir(hooks_dir)) if f.endswith(".py")]
        library_dir = os.path.join(hooks_dir, HOOK_LIBRARY)
        listing += [(library_dir, f) for f in sorted(os.listdir(library_dir)) if f.endswith(".py")]
        for directory, f in listing:
            rel = os.path.relpath(os.path.join(directory, f), os.path.join(SRC, "hooks")).replace(os.sep, "/")
            src = open(os.path.join(directory, f), encoding="utf-8").read()
            try:
                ast.parse(src, filename=f, feature_version=floor)
            except SyntaxError as exc:
                broken.append(f"hooks/{rel}:{exc.lineno} — {exc.msg}")
        self.assertFalse(
            broken,
            f"훅이 python {floor[0]}.{floor[1]} 에서 파싱되지 않는다 (조용히 죽는다):\n" + "\n".join(broken),
        )


class TestRoleContract(unittest.TestCase):
    """역할 문서는 산문이라 통째로 다시 쓰이는데, 그때 사라지는 것은 문장이 아니라 계약이다."""

    def test_role_documents_keep_their_contract_phrases(self):
        """다시 쓰기가 계약 문구를 떨어뜨리면 그 역할과 사유를 대며 죽는다.

        26-08-04 실측: 판정자 문서가 41줄에서 105줄로 다시 쓰이면서 `not a verification waiver`
        와 `read-only guard` 가 같이 사라졌다. 그때도 빨개지긴 했지만, 두 시험 다 **우연히** 그
        문구를 쓰고 있었을 뿐이라(하나는 doctor 드리프트 카나리아의 치환 대상, 하나는 lagom
        계약 검사) 무엇이 왜 깨졌는지는 어디에도 안 적혀 있었다. 게다가 둘 다 스캐폴딩을 도는
        느린 시험이라, 자기가 만진 파일만 돌린 사람은 초록을 보고 끝낸다.

        이 시험은 표(`ROLE_CONTRACT_INVARIANTS`) 하나만 읽는다 — 파일 I/O도 스캐폴딩도 없다."""
        from asgard.templates.roles import ROLE_AGENTS, ROLE_CONTRACT_INVARIANTS, missing_role_invariants

        bodies = dict(ROLE_AGENTS)
        for fname in ROLE_CONTRACT_INVARIANTS:
            self.assertIn(fname, bodies, f"{fname} — 표가 없는 역할 문서를 가리킨다")
        missing = missing_role_invariants()
        self.assertFalse(missing, "역할 문서가 자기 계약 문구를 잃었다:\n" + "\n".join(missing))


class TestPackageInternals(unittest.TestCase):
    """최상위 이름 안쪽 — 패키지가 커져도 그 안의 방향이 규칙으로 남는지."""

    def test_every_package_with_internal_edges_has_a_tier_table(self):
        """안쪽 결합이 있는 패키지는 등급표를 갖는다 — 빠뜨리려면 이유를 적어야 한다.

        문턱을 엣지 1건으로 잡는다. 크기가 아니라 결합의 유무가 기준인 이유는, 지금 자식끼리
        아무것도 안 부르는 패키지는 잴 것이 없고 첫 결합이 생기는 순간 이 시험이 그 이름을
        대며 표를 요구하기 때문이다. 그래서 새 패키지가 규칙 없이 자라는 경로가 없다."""
        problems: list[str] = []
        packages = {".".join(pkg): pkg for pkg in _iter_packages()}
        for dotted, pkg in sorted(packages.items()):
            if dotted in PACKAGE_TIERS or dotted in PACKAGES_GOVERNED_ELSEWHERE:
                continue
            edges = list(_package_edges(pkg))
            if not edges:
                continue
            if dotted in PACKAGES_WITHOUT_TIERS:
                continue  # 이유가 비었는지는 아래에서 따로 본다
            sample = ", ".join(f"{src}→{dst}" for _rel, _lineno, src, dst in edges[:4])
            problems.append(f"{dotted} — 안쪽 엣지 {len(edges)}건({sample}) 인데 등급표가 없다")
        for dotted in sorted(set(PACKAGE_TIERS) | set(PACKAGES_GOVERNED_ELSEWHERE) | set(PACKAGES_WITHOUT_TIERS)):
            if dotted not in packages:
                problems.append(f"{dotted} — 없는 패키지를 가리키는 표가 남아 있다")
        for dotted, reason in sorted(PACKAGES_WITHOUT_TIERS.items()):
            if not reason.strip():
                problems.append(f"{dotted} — 규칙 밖에 두는 이유가 비어 있다")
        self.assertFalse(
            problems,
            "패키지 안쪽이 규칙 밖에 있다 — PACKAGE_TIERS 에 등급을 세우거나 "
            "PACKAGES_WITHOUT_TIERS 에 이유를 적어라:\n" + "\n".join(problems),
        )

    def test_tier_tables_match_the_package_directory(self):
        """표와 디렉터리가 어긋나면 안 된다 — 새 모듈은 자리를 얻고 들어온다.

        미배치는 '이게 무엇 위에 서는가'를 아무도 안 정했다는 뜻이고, 남은 이름은 표가 옛
        디렉터리를 서술한다는 뜻이다. 둘 다 표를 기록으로 전락시킨다."""
        problems: list[str] = []
        for dotted, tiers in sorted(PACKAGE_TIERS.items()):
            pkg = tuple(dotted.split("."))
            if not os.path.isdir(os.path.join(SRC, *pkg)):
                continue  # 사라진 패키지를 가리키는 표는 위 시험이 이름을 대며 잡는다
            actual = _package_children(pkg)
            placed = [name for _title, names in tiers for name in names]
            missing = sorted(actual - set(placed))
            stray = sorted(set(placed) - actual)
            twice = sorted({name for name in placed if placed.count(name) > 1})
            if missing:
                problems.append(f"{dotted} — 등급 미지정: {missing}")
            if stray:
                problems.append(f"{dotted} — 패키지에 없는 이름이 등급표에: {stray}")
            if twice:
                problems.append(f"{dotted} — 등급이 둘: {twice}")
            if _PACKAGE_TIER_RANK[dotted].get(_FACADE) != len(tiers) - 1:
                problems.append(f"{dotted} — 파사드({_FACADE})는 맨 위 등급이어야 한다")
        self.assertFalse(problems, "등급표가 패키지 디렉터리와 어긋난다:\n" + "\n".join(problems))

    def test_package_internals_go_down_a_tier(self):
        """패키지 안에서도 아래 등급만 부른다 — 같은 등급끼리도 안 된다.

        계층·SUBTIERS 와 같은 부등호다. 같은 등급을 막는 이유도 같다: 새 결합이 표를 안 고치고
        생길 수 있으면 표는 계약이 아니라 기록이 된다. 필요한 결합이면 등급을 올리고 왜
        올렸는지를 그 줄에 적으면 된다."""
        violations: list[str] = []
        for dotted in sorted(PACKAGE_TIERS):
            pkg = tuple(dotted.split("."))
            if not os.path.isdir(os.path.join(SRC, *pkg)):
                continue  # 사라진 패키지는 test_every_package_with_internal_edges_has_a_tier_table 몫
            rank, title = _PACKAGE_TIER_RANK[dotted], _PACKAGE_TIER_TITLE[dotted]
            for rel, lineno, src, dst in _package_edges(pkg):
                src_tier, dst_tier = rank.get(src), rank.get(dst)
                if src_tier is None or dst_tier is None:
                    continue  # 등급 미지정은 test_tier_tables_match_the_package_directory 가 잡는다
                if dst_tier < src_tier:
                    continue
                why = "같은 등급" if dst_tier == src_tier else "등급을 거슬러 오른다"
                violations.append(f"{rel}:{lineno} — {src}[{title[src]}] → {dst}[{title[dst]}] ({why})")
        self.assertFalse(
            violations,
            "패키지 안쪽 등급 위반 — PACKAGE_TIERS 를 고치고 왜 올렸는지 그 줄에 적어라:\n" + "\n".join(violations),
        )


# Studio 안쪽의 사슬 — `commands.studio` 패키지는 아래로만 기댄다. 이 순서가 곧 계약이다:
# 왼쪽이 오른쪽을 부를 수 없다. 하나라도 뒤집히면 순환이 생기고, 순환이 생기면 "이 모듈만
# 읽으면 된다"가 다시 거짓이 된다 (1,586줄 한 파일로 돌아가는 첫걸음이 그것이었다).
#
# 파사드(`__init__`)가 맨 끝에 있다. 예전에는 사슬이 `__init__.py`를 아예 안 봤고, 그래서 밖에
# 내보내는 이름을 고정하는 그 파일에서 형제를 부르는 임포트 18건이 규칙 밖이었다. 파사드는
# 이 패키지의 가장 바깥 소비자라 맨 위가 맞고, 위에 두면 안쪽 모듈이 파사드를 부르는 방향
# (그건 순환이다)이 항상 위반이 된다.
STUDIO_CHAIN = (
    "state",
    "dialog",
    "boundary",
    "tasks",
    "snapshot",
    "workspaces",
    "artifacts",
    "config",
    # tutor — 되짚기 창의 재료. routes 아래인 이유는 방향이다: 자기는 엔진(asgard.tutor·
    # tutor_debt)만 읽고, 그것을 어느 주소에 걸지는 routes 가 정한다.
    "tutor",
    # orchestration — 오케스트레이션 정책·엔진 준비 상태의 창 재료. tutor 와 같은 자리다:
    # 엔진(asgard.engines·orchestration.policy)만 읽고 주소는 routes 가 건다.
    "orchestration",
    # load — 부하 시험 창의 재료와 실행. tutor·orchestration 과 같은 자리다: 엔진(asgard.k6·
    # k6_live)만 읽고 어느 주소에 걸지는 routes 가 정한다. 자기 실행 장부를 따로 드는 것은
    # 부하가 창보다 오래 살기 때문이다 — 창을 닫아도 도는 판은 끝까지 가야 기록이 남는다.
    "load",
    # agents — 에인헤랴르(에이전트 프로파일) 창의 재료. tutor·orchestration 과 같은 자리다:
    # 엔진(asgard.profiles·settings·swarm)만 읽고 어느 주소에 걸지는 routes 가 정한다.
    "agents",
    "routes",
    "server",
    "__init__",
)


def _chain_targets(node: ast.stmt, parts: list[str]) -> set[str]:
    """import 문 → STUDIO_CHAIN 에 등재된 형제 모듈 이름. 계층 규칙과 같은 해석기를 쓴다."""
    return {
        target[2]
        for target in _resolved_targets(node, parts)
        if len(target) >= 3 and target[:2] == ("commands", "studio")
    }


class TestStudioPackage(unittest.TestCase):
    """스튜디오 창의 안쪽 — 한 파일이던 것을 책임별로 가른 뒤의 불변식."""

    def _studio_modules(self) -> dict[str, ast.Module]:
        """패키지 안의 모든 `.py` — 파사드(`__init__`)까지. 키는 STUDIO_CHAIN 의 성분과 같다.

        `__init__` 의 상대 임포트를 풀 때 그 키가 그대로 경로 성분으로 쓰인다
        (`["commands", "studio", "__init__"]`) — 계층 규칙이 `__init__.py` 를 다루는 방식과 같다.
        """
        base = os.path.join(SRC, "commands", "studio")
        out = {}
        for entry in sorted(os.listdir(base)):
            if entry.endswith(".py"):
                with open(os.path.join(base, entry), encoding="utf-8") as handle:
                    out[entry.removesuffix(".py")] = ast.parse(handle.read())
        return out

    def test_every_module_is_placed_on_the_chain(self):
        """새 모듈은 자리를 얻고 들어온다 — 미배치는 '어디에 기대는지 아무도 안 정했다'는 뜻."""
        unplaced = set(self._studio_modules()) - set(STUDIO_CHAIN)
        self.assertFalse(unplaced, f"사슬에 자리 없는 모듈: {sorted(unplaced)} — STUDIO_CHAIN 에 배치하라")

    def test_the_package_leans_only_downward(self):
        """위 모듈은 아래를 부르고, 아래는 위를 모른다.

        상대(`from .server import X`)와 절대(`from asgard.commands.studio.server import X`)를
        똑같이 본다. 예전에는 상대 임포트만 봤는데, 그러면 임포트를 절대 형식으로 적는 것만으로
        STUDIO_CHAIN 을 통째로 비껴갈 수 있었다 — 문법 한 글자로 우회되는 계약은 계약이 아니다.
        함수 안 lazy 임포트는 계층 규칙과 같은 관용으로 남긴다."""
        rank = {name: index for index, name in enumerate(STUDIO_CHAIN)}
        violations: list[str] = []
        for name, tree in sorted(self._studio_modules().items()):
            parts = ["commands", "studio", name]
            for node in _module_level_imports(tree):
                for target in _chain_targets(node, parts):
                    if target in rank and rank[target] >= rank[name]:
                        violations.append(f"{name}:{node.lineno} → {target} (사슬을 거슬러 오른다)")
        self.assertFalse(violations, "스튜디오 패키지에 순환 위험:\n" + "\n".join(violations))

    def test_the_loopback_guard_is_written_once(self):
        """로컬 창 셋이 같은 것을 막는다 — 세 벌로 적으면 셋이 갈린다.

        실측(합치기 전): `Referrer-Policy`는 두 창에만,
        `frame-src`·`base-uri`·`form-action`은 한 창에만 걸려 있었다. 보안 경계가 갈렸다는 사실 자체가 아무도 안 보고 있었다는
        증거라, 다시 갈라지지 않게 여기서 잡는다."""
        owner = os.path.join(SRC, "commands", "loopback.py")
        offenders: list[str] = []
        for path in _iter_py_files():
            if os.path.abspath(path) == os.path.abspath(owner):
                continue
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            rel = os.path.relpath(path, SRC)
            if "def host_allowed(" in source:
                offenders.append(f"{rel} — host_allowed 를 다시 적었다")
            if 'frozenset({"127.0.0.1"' in source:
                offenders.append(f"{rel} — 루프백 명부를 다시 적었다")
            if "Content-Security-Policy" in source:
                offenders.append(f"{rel} — CSP 를 다시 적었다")
        self.assertFalse(offenders, "루프백 경계는 commands/loopback.py 한 벌이다:\n" + "\n".join(offenders))


def _layer(top: str) -> str:
    return LAYERS[_RANK[top]][0]


if __name__ == "__main__":
    unittest.main()
