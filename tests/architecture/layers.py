"""계층 표(LAYERS)와 계층 안쪽 등급(SUBTIERS) — 규칙이 읽는 정본. 근거는 패키지 docstring 에 있다."""

from __future__ import annotations

import os

SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src", "asgard")
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
                # justfile — 실행 표면. code_map 과 같은 층이고 그 감지기를 부른다: 저장소가
                # 무엇을 돌릴 수 있는지 읽어 파일 하나로 낸다. 명령을 도는 것은 just 자신이다.
                "justfile",
                # code_style — 저장소가 선언한 스타일 도구를 부르고 그 출력을 판정으로 바꾼다.
                # justfile 과 같은 자리인 이유는 방향이 같아서다: 규칙을 스스로 갖지 않고,
                # 저장소가 이미 정해 둔 것(Justfile·checkstyle.xml)을 읽어 하나의 산출물을 낸다.
                # code_style_catalog 는 그 도구를 저장소에서 찾아내는 목록이고, Tool 하나만 보므로
                # code_style 보다 위 등급이다.
                "code_style",
                "code_style_catalog",
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
                # tutor_model — tutor_growth의 안정적인 물음 ID를 품은 Tutor 값 객체.
                # 조립과 표면은 모르고, tutor가 기존 공개 이름으로 재노출한다.
                "tutor_model",
                # review_agent — 튜터 사실을 입력으로 삼되, 오딘 승인 뒤에만 제안을 저장하는
                # 선택형 리뷰 층. 모델 호출은 함수 안 lazy라 domain 경계를 올리지 않는다.
                "review_agent",
                "tutor_probes",
                "tutor_growth",
                # tutor_debt — 인지적 항복의 신호를 세는 계량기. tutor_growth(기록)만 읽고
                # 판정은 tutor 가 소비한다. 여기 있는 이유는 tutor_probes 와 같다: 재기만 하고
                # 무엇을 할지는 안 정한다.
                "tutor_debt",
                # tutor_rationale — 이 변경을 만든 퀘스트의 기록(요청·기준·가정·검증 명령)을 읽는
                # 자. tutor_probes·tutor_debt 와 같은 자리다: 재기만 하고 무엇을 할지는 안 정하며,
                # 아스가르드 모듈을 하나도 안 부른다 (퀘스트 로그 파일이 유일한 입력).
                "tutor_rationale",
                # tutor_teach — 이번 변경을 사람에게 **설명하는** 재료(읽는 순서·용어·확인 명령).
                # tutor 는 물음을 만들고 이쪽은 설명을 만든다 — 같은 축의 반대쪽이라 계층이 같다.
                # 판정 등급인 이유는 부등호다: 계측(tutor_probes)을 읽고 적용(tutor)이 이걸 읽는다.
                "tutor_teach",
                # tutor_brief — 일을 시작하기 **전에** 그 자리에 남은 물음을 꺼내는 화면.
                # tutor_teach 와 같은 자리다: 기록(tutor_growth)과 공용 표(tutor_model)만 읽고,
                # 적용 등급의 tutor 가 그 이름을 재수출해 표면에 넣는다. tutor 를 부르지 않는
                # 것이 이 자리의 조건이라 `_normalise` 도 여기서 따로 갖는다.
                "tutor_brief",
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
                # roundtable — 좌석 여럿을 한 안건에 앉히고 회차를 돌리는 규칙. orchestration
                # 옆이다: 전사를 그 장부에 적고, 그 위의 무엇도 안 본다. 모델 호출(providers·
                # agent.oneshot)은 상향이라 plan 과 같은 규율으로 함수 안 lazy 로만 부른다.
                "roundtable",
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
                    "tutor_model",
                    # roundtable — 자립층의 orchestration 하나를 얹는다(전사를 그 장부에 적는다).
                    # k6_live 와 같은 이유로 여기다: 이름이 표여서가 아니라 부등호가 그렇다.
                    "roundtable",
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
            frozenset(
                {
                    "craft_c",
                    # justfile — 해석 등급의 code_map 감지기를 읽어 실행 표면 하나를 낸다.
                    # 지도 레인과 같은 자리인 이유도 같다: 같은 감지를 읽고 다른 산출물을 낸다.
                    "justfile",
                    "thor_lex",
                    "tutor_probes",
                    "tutor_debt",
                    "tutor_rationale",
                    "map_graph",
                    "map_context",
                    "map_notes",
                }
            ),
        ),
        # 계측을 합쳐 결론을 낸다. tutor_teach 가 craft 옆인 이유는 방향이다 — 탐침(tutor_probes)과
        # 기록(tutor_growth)을 읽어 "무엇을 어떤 순서로 읽어야 하는가"를 만들고, 그 결론을
        # 적용 등급의 tutor 가 화면에 넣는다. craft 를 부르지 않는 것이 이 자리의 조건이다.
        # code_style 이 craft 옆인 이유는 산출물이 같아서다 — 막는 판정 목록 하나. 규칙의
        # 출처만 다르다(craft 는 이 저장소가, code_style 은 사용자가 선언한 도구가 갖는다).
        ("판정", frozenset({"craft", "code_style", "tutor_teach", "tutor_brief"})),
        # code_style_catalog — 판정 등급의 Tool 하나를 얹는다. 언어가 늘어도 판정은 안 바뀐다.
        ("규격 목록", frozenset({"code_style_catalog"})),
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
