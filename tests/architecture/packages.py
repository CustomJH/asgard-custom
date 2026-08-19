"""패키지 안쪽 등급표(PACKAGE_TIERS)와 규칙 밖에 두는 자리 — 근거는 패키지 docstring 에 있다."""

from __future__ import annotations

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
    # 회수 — 위 `memory` 표의 ("회수", {"recall"}) 행이 이 패키지를 부모 층에서 잰 자리이고,
    # 여기는 그 안쪽이다. 순수 계산과 행 읽기가 바닥, 그것들을 합치는 두 회수기가 그 위, 턴에
    # 실을 것을 고르는 blocks 가 맨 위다.
    "memory.recall": (
        # 패키지 안의 어느 모듈도 안 부른다 — 유사도·어간·전파·리랭크 같은 순수 계산(grams·
        # stems·ppr·rerank·clean), 행 읽기(rows), 응답에서 실존 경로만 추리는 넛지(nudge).
        ("바닥", frozenset({"grams", "stems", "rows", "clean", "ppr", "rerank", "nudge"})),
        # 바닥만 부른다. search 는 네 스트림을 합치고 snapshot 은 세션 카탈로그를 동결하는데,
        # 서로를 안 부르므로 같은 등급이다.
        ("회수", frozenset({"search", "snapshot"})),
        # search 의 결과와 rows 를 읽어 턴마다 붙일 블록을 고른다 — 회수 위인 이유가 그것이다.
        ("주입", frozenset({"blocks"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 손질 — 위 `memory` 표의 ("손질", {"norn"}) 행이 이 패키지를 부모 층에서 잰 자리이고,
    # 여기는 그 안쪽이다. 쓰기가 검증 위인 것이 이 패키지의 계약이다: 검증을 통과한 op 만
    # apply 까지 온다.
    "memory.norn": (
        # 패키지 안의 어느 모듈도 안 부른다 — 근거 대조·극성 판정(insight), 트리거와 latch 를
        # 담는 상태 파일 한 자리(state).
        ("바닥", frozenset({"insight", "state"})),
        # LLM 이 낸 op 목록에서 기계가 확인한 것만 남긴다. insight 만 부른다.
        ("검증", frozenset({"validate"})),
        # 손질 패스 둘 — 증거를 모아 델타를 제안하고 검증까지 돌리는 쪽(plan), 검증을 지난 op 를
        # 백업 뒤 커밋하는 쪽(apply). 서로를 안 부르므로 같은 등급이다.
        ("패스", frozenset({"plan", "apply"})),
        # 언제 손질할지와 무엇까지 스스로 할지를 정해 plan·apply 를 부른다. 그 둘이 아래라 여기다.
        ("자율", frozenset({"auto"})),
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
    # 세션 — 한 턴의 tool use 루프. 위 `agent` 표의 ("세션", {"session"}) 행이 부모 층에서 잰
    # 자리이고, 여기는 그 안쪽이다. 형상은 heimdall.trinity·heimdall.core 와 같다: 상태 하나를
    # 믹스인 넷이 나눠 지고, 그 상태 선언(`_shared`)은 아무 믹스인도 안 부른다.
    "agent.session": (
        # 패키지 안의 어느 모듈도 안 부른다 — 턴 결과·예외·툴콜 형상(types), provider 별 SDK
        # 클라이언트 한 자리(client), 정본 스키마와 provider 형식 사이의 변환(wire).
        ("바닥", frozenset({"types", "client", "wire"})),
        # 믹스인 넷이 공유하는 세션 상태의 선언. types 만 부르고, 값은 `AgentSession.__init__` 이
        # 채운다 — 믹스인을 부르면 상태가 자기를 드는 쪽을 알게 되므로 그 방향이 여기서 막힌다.
        ("상태", frozenset({"_shared"})),
        # 트랜스포트 루프 셋(chat·messages·responses)과 압축 믹스인(compress). 넷 다 `_shared` 의
        # 상태만 읽고 서로를 안 부르므로 같은 등급이다.
        ("믹스인", frozenset({"chat", "messages", "responses", "compress"})),
        # AgentSession — 믹스인 넷을 한 턴의 생애로 엮는다. 넷이 전부 아래라 여기다.
        ("세션", frozenset({"core"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 후긴 — 컨텍스트 압축 엔진. 압축은 사다리(T0 위생 → T1 프룬 → 요약 → T3 서버측)라서 표도
    # 그 순서 그대로다: 단계 하나가 옆 단계를 안 부르고, engine 만 전부를 순서대로 부른다.
    "agent.huginn": (
        # 패키지 안의 어느 모듈도 안 부른다 — 핸드오프 문구 뼈대(contract), [compress] 설정
        # 해석(policy), 토큰 근사(tokens), 세션 트랜스포트로 요약 1회를 부르는 함수(caller).
        ("바닥", frozenset({"contract", "policy", "tokens", "caller"})),
        # 메시지를 실제로 손대는 단계들 — 직렬화(text), 결정론 압축(prune), 고아 툴콜 제거
        # (pairs), 서버측 압축 요청·판별(server). 서로를 안 부른다.
        ("가공", frozenset({"text", "prune", "pairs", "server"})),
        # 트랜스크립트에서 핸드오프 쌍을 판별해 떼어낸다. contract·text·tokens 를 부르므로 가공 위다.
        ("핸드오프", frozenset({"handoff"})),
        # 요약이 자를 구간의 앞뒤를 역할 교대가 맞는 자리로 옮긴다 — 그 경계를 handoff 의 판별에서
        # 받으므로 핸드오프 위다.
        ("경계", frozenset({"align"})),
        # 세션 1개의 압축 상태와 사다리 실행. 위 네 등급을 전부 부르는 유일한 자리다.
        ("엔진", frozenset({"engine"})),
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
    # Trinity 를 배차 장부에 비추는 어댑터. 위 `agent.heimdall` 표의 ("선언", {"bifrost"}) 행이
    # 부모 층에서 잰 자리이고, 여기는 그 안쪽이다.
    "agent.heimdall.bifrost": (
        # 오케스트레이션 형상 판정 — 신호와 사용자 정책만 읽고 패키지 안의 어느 모듈도 안 부른다.
        ("형상", frozenset({"shape"})),
        # 한 퀘스트의 배차 장부. shape 의 판정으로 형상을 정하므로 그 위다.
        ("장부", frozenset({"ledger"})),
        # 장부를 드는 쪽 — 준비된 일감을 배차하고 워커 질문에 답하는 감독 고리(coordinator),
        # 장부가 안 선 경로가 쓰는 비활성 장부와 형상 판정을 먼저 두는 진입점(null).
        # coordinator 의 런타임 임포트는 orchestration 뿐이지만(장부는 인자로 받는다) 여기 두는
        # 이유는 방향이다: 아래에 두면 ledger→coordinator 가 통과하고, 그러면 장부가 자기를
        # 모는 쪽을 알게 된다.
        ("감독", frozenset({"coordinator", "null"})),
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
                    "roots",
                    "review",
                    "agent",
                    "map",
                    "just",
                    "style",
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
        # swarm — 명령 표면이 아니라 명령이 쓰는 재료다. start 가 --cc/--codex 갈래에서 이것을
        # 부르고, 이것은 형제 명령을 하나도 안 부른다 (agent.runtime 과 orchestration 만 쓴다).
        # 같은 등급에 두면 start→swarm 이 그대로 등급 위반이라 여기가 아래다.
        ("명령 재료", frozenset({"swarm"})),
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
                    "workroots",
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
                    # just — 실행 표면을 세우고 재는 손. craft·manual 과 같은 자리다:
                    # 저장소 뿌리를 health 에서 받고, 판정 자체는 도메인(justfile)이 한다.
                    "just",
                    "manual",
                    "memory_dashboard",
                    # style — 저장소가 선언한 스타일 규격의 표면. craft·just 와 같은 자리다:
                    # 저장소 뿌리를 health 에서 받고, 판정 자체는 도메인(code_style)이 한다.
                    "style",
                    # automations — commands.health의 프로젝트 경계 해석을 읽으므로 명령 소비 등급이다.
                    "automations",
                    # orchestrate — 정책·엔진 준비 상태의 표면. tutor 와 같은 자리인 이유도 같다:
                    # 자기는 설정만 읽고 쓰지만 저장소 뿌리를 health 에서 받아 온다.
                    "orchestrate",
                    "plan_api",
                    # review — health의 프로젝트 경계와 review_agent 도메인을 조립하는 승인 표면.
                    "review",
                    # siege(장부 읽기)·siege_act(장부 몰기)·siege_serve(우편함을 모델에게 잇기) —
                    # 형제를 안 부른다. 셋 다 저장소 뿌리를 health 에서 직접 받으므로 같은 등급이고,
                    # 그래서 서로를 부르면 빨개진다.
                    "siege",
                    "siege_act",
                    "siege_serve",
                    # roundtable — 좌석을 앉히고 전사를 찍는 표면. siege 삼형제와 같은 자리다:
                    # 저장소 뿌리를 health 에서 직접 받고, 토론 자체는 도메인(roundtable)이 한다.
                    "roundtable",
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
    # 되짚기 자료의 사람 표면. 도메인 계산은 전부 `tutor` 에 있고 여기는 그것을 화면·JSON·
    # 보고서로 옮기는 자리라, 표의 방향도 재료 → 표현 → 갈래 → 진입 하나뿐이다.
    "commands.tutor": (
        # 패키지 안의 어느 모듈도 안 부른다 — 보고서에 손으로 적은 답을 걷는 자리(answers),
        # 되짚기 엔진에 늦게 닿고 없으면 침묵하는 자리(engines), 세 표면이 같이 쓰는 이름표(labels).
        ("바닥", frozenset({"answers", "engines", "labels"})),
        # 같은 사실을 세 형식으로 낸다 — 터미널(screen), 훅·스튜디오가 읽는 JSON(payload),
        # 절이 하나 더 있는 보고서(report). 셋 다 engines·labels 만 부르고 서로를 안 부른다.
        ("표현", frozenset({"screen", "payload", "report"})),
        # 기본 갈래를 뺀 나머지 명령 갈래. screen 으로 그리므로 표현 위다.
        ("갈래", frozenset({"lanes"})),
        # 플래그 하나를 갈래 하나에 맞추고 기본 갈래는 직접 돈다 — 아래 셋을 전부 부른다.
        ("진입", frozenset({"entry"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 다국어 휴먼체 판정. 언어를 늘리는 접점이 registry 하나이므로 표도 그 접점을 기준으로
    # 갈린다: 언어 코퍼스는 registry 를 모르고, judge 는 개별 언어를 모른다.
    "bragi": (
        # 패키지 안의 어느 모듈도 안 부른다 — 흔적 하나의 자료형과 심각도 눈금(tell), 언어
        # 판정(detect), 원문 보존 대상을 지운 검사 사본(clean), on/off 상태(mode).
        ("바닥", frozenset({"tell", "detect", "clean", "mode"})),
        # 패턴을 tell 로 적는 자리 — 언어 무관(universal), 언어별 코퍼스(english·korean·corpora),
        # 구 목록으로 못 잡는 분포 자질(stats). 서로를 안 부른다.
        ("흔적", frozenset({"universal", "english", "korean", "corpora", "stats"})),
        # 언어 코드를 코퍼스에 맞춘다. 코퍼스 셋을 부르므로 그 위이고, 판정을 안 부르는 것이
        # 이 자리의 조건이다 — 언어를 늘릴 때 고치는 파일이 여기 하나로 남는다.
        ("등록", frozenset({"registry"})),
        # 흔적 목록 → 등급 → 게이트가 소비하는 문자열. registry 로 언어를 고르고 clean 의 사본을
        # 읽으므로 등록 위다.
        ("판정", frozenset({"judge"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 자가발전 인박스 — 디스크 자리와 두 채굴원이 바닥이고, 그 위로 채굴(inbox) → 처분
    # (decisions) → 자율 손잡이(autonomy) → 턴 끝 한 줄(nudge) 순으로 올라간다. 방향이 뒤집히면
    # 인박스가 화면을 알게 되고, 그러면 화면 없이 채굴만 돌리는 경로가 사라진다.
    "evolution": (
        # 패키지 안의 어느 모듈도 안 부른다 — 경로·seen latch·넛지 지문 파일(store), 퀘스트 로그
        # 읽기(quests), 신호에서 SKILL.md 초안 본문을 쓰는 자리(drafts).
        ("바닥", frozenset({"store", "quests", "drafts"})),
        # 정정 발화를 탐지해 store 가 정한 자리에 적는다. 채굴원이라 inbox 아래다 — quests 와
        # 같은 자리인데, store 를 부르는 만큼만 한 등급 위다.
        ("정정", frozenset({"corrections"})),
        # 두 채굴원(quests·corrections)의 신호를 drafts 의 초안으로 세워 pending 에 올린다.
        ("채굴", frozenset({"inbox"})),
        # 인박스가 올린 것에 손을 댄다 — 초안을 LLM 으로 다시 쓰거나(distill) 설치된 learned
        # 스킬을 파일·latch 짝으로 보관·복원한다(skills). 둘은 서로를 안 부른다.
        ("가공", frozenset({"distill", "skills"})),
        # 초안의 처분 — inbox 의 pending 목록을 읽고 store 의 latch 를 고치며, 승인 뒤에는
        # skills 의 배차 명단 재렌더를 부른다. 그 셋이 전부 아래라 여기다.
        ("처분", frozenset({"decisions"})),
        # 스스로 캘지(autoscan)·스스로 설치할지(autonomy_mode)를 정해 decisions 의 승인을
        # 대신 누른다. 관문을 없애지 않고 누르는 손만 정책이 드는 자리라 처분 위다.
        ("자율", frozenset({"autonomy"})),
        # 턴 끝에 나가는 한 줄 — 채굴과 자동 설치를 돌린 뒤 무엇이 늘었는지 말한다. 이 패키지에서
        # 유일하게 화면을 아는 자리이고, 아무도 이것을 안 부른다.
        ("표면", frozenset({"nudge"})),
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
                    "style_gate",
                    "dispatch_context",
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
                    "scope_activate",
                    "secret_guard",
                    "siege_inbox",
                    "subagent_gate",
                    "tutor_note",
                    "unattended_context",
                    "verifier_context",
                    "verifier_gate",
                    "write_sentinel",
                }
            ),
        ),
        # 훅을 **부르는** 훅 하나. 한 이벤트의 주입 훅들을 프로세스 하나에서 돌리므로 위 등급
        # 위에 선다. 형제를 이름으로 임포트하지는 않는다 — 배선이 준 파일 경로로 올리므로 배포
        # 계약(형제 임포트 금지)은 그대로고, 그래서 이 방향은 엣지 추출기에 안 보인다.
        # 표가 적어 두는 이유가 그것이다.
        ("묶음 실행", frozenset({"hook_dispatch"})),
        ("파사드", frozenset({"__init__"})),
    ),
    # 훅이 함께 지고 다니는 공용 라이브러리. 여기 등급은 실측 임포트 방향의 위상 정렬 그대로다
    # (26-08-06: 엣지 26건, 순환 0). 이 패키지가 생긴 이유가 곧 이 표가 필요한 이유다 — 같은
    # 코드가 훅 셋에 사본으로 살던 동안 49개 중 9개가 의미까지 갈라졌고, 사본에는 방향이 없었다.
    "hooks.asgard_hooklib": (
        # 아무것도 안 부른다 — 파일·git 원시 연산, 해시, 증거 술어, 정책 표.
        # siege — 배차 장부에 한 줄 적으라고 CLI 프로세스를 띄우는 문. asgard 를 임포트하지
        # 않는 것이 요점이라(배포 인터프리터에는 없다) 여기 바닥에 선다.
        # transcript — 세션 기록 JSONL 을 읽어 도구 호출을 짝짓는다. stdlib 만 쓰고 아무도 안 부른다.
        # seen — 훅이 도는 프로젝트의 뿌리를 `~/.asgard/seen/` 에 남긴다. `asgard sync` 가 이
        # 기계에서 고칠 프로젝트를 찾는 데 쓰고, 등록 판단은 하지 않는다 (그 판단은 registry 몫).
        (
            "바닥",
            frozenset(
                {"evidence", "inject", "integrity", "paths", "policy", "seen", "siege", "transcript", "workspace"}
            ),
        ),
        # 바닥 하나씩만 얹는다. 서로는 안 부른다.
        ("한 단", frozenset({"firing", "ledger", "runners", "scope", "session", "shell", "transition"})),
        # destructive — 되돌리기 어려운 명령을 가려내는 판정기. `shell`(한 단)만 얹는다.
        ("두 단", frozenset({"contracts", "destructive", "readonly", "tickets", "tree"})),
        # 실행과 관측 — `summary` 가 아래를 거의 다 부르는 유일한 자리다 (관측을 한 함수로 모은다).
        ("조립", frozenset({"baseline", "summary"})),
        ("파사드", frozenset({"__init__"})),
    ),
    "map_graph": (
        # 증거 모델과 그것만 읽는 조회기들.
        ("증거", frozenset({"evidence", "bridge", "resolve_jvm", "view_legacy"})),
        ("추출", frozenset({"extract_java", "extract_python", "extract_tsjs", "spring_props"})),
        # projection — 완성된 상태만 받아 팀 공유 Markdown을 만드는 결정론 뷰. 그래프 조립은
        # 이 렌더러를 부르지만 렌더러는 수집·해석을 모르므로 그래프 바로 아래에 둔다.
        ("프로젝션", frozenset({"projection"})),
        ("그래프", frozenset({"graph"})),
        # impact — fresh graph와 memory overlay를 읽어 revision-bound dossier로 조립한다.
        # 추출·그래프를 바꾸지 않고 소비만 하므로 graph 위, 공개 파사드 아래다.
        ("영향", frozenset({"impact"})),
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
    # 스킬·플러그인 등록부 — 파일 읽기와 휠 내장 선언이 바닥이고, 신뢰 경계(manifest)를 지나야
    # 디스크 배치(anchor·bundles)가 있고, 그 배치를 읽는 소비자들이 그 위에 선다. manifest 가
    # 아래인 것이 계약이다 — 복사·실행이 검증을 우회할 방향이 없다.
    "skill_registry": (
        # 패키지 안의 어느 모듈도 안 부른다 — SKILL.md 프론트매터·본문 읽기(frontmatter),
        # 휠에 코드로 들어 있는 기본 플러그인 선언(builtin).
        ("바닥", frozenset({"frontmatter", "builtin"})),
        # plugin.json 과 자원 트리를 검사하는 신뢰 경계. frontmatter 만 부른다.
        ("검증", frozenset({"manifest"})),
        # 검증을 지난 것을 디스크에 놓는다 — 앵커 스킬 트리를 프로젝트 옆에 푸는 자리(anchor),
        # 동봉·제3자 묶음의 출처와 설치(bundles). 둘은 서로를 안 부른다.
        ("설치", frozenset({"anchor", "bundles"})),
        # 놓인 묶음을 읽는 두 소비자 — 어느 스킬이 어느 역할에게 열려 있는지 판정하고(policy),
        # 선언된 진입점을 셸 없이 돌린다(runner). 둘은 서로를 안 부른다.
        ("정책·실행", frozenset({"policy", "runner"})),
        # 목록·본문·자원을 policy 의 판정으로 걸러 내보낸다. 그 필터가 아래라서 여기다.
        ("차례표", frozenset({"catalog"})),
        # catalog 를 읽어 어느 스킬인지 정한다 — 요청 문장마다 고르거나(resolve) 프로젝트 설정에
        # 결속·해제를 남긴다(assignment). 둘은 서로를 안 부른다.
        ("선정", frozenset({"assignment", "resolve"})),
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
                    "env",
                    "just",
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
    # 이번 변경을 사용자가 되짚게 만드는 층. 화면은 `commands.tutor` 가 지고 여기는 사실만
    # 만든다 — 그래서 표의 위쪽도 화면이 아니라 "턴 끝에 실을 카드"(native)다.
    "tutor": (
        # 패키지 안의 어느 모듈도 안 부른다 — 공개 시그니처 대조(contracts), git 에서 읽는
        # 재료(diffs), 물음 종류의 화면 이름(labels), 사실을 사람에 맞춰 줄이는 조절(pacing).
        ("바닥", frozenset({"contracts", "diffs", "labels", "pacing"})),
        # 재료를 읽어 판정을 만든다 — 파일 하나의 인벤토리와 물음(points), 세션·하루·한 주의
        # 서사와 도중 팁(narrative). 서로를 안 부른다.
        ("판정", frozenset({"points", "narrative"})),
        # 파일별 판정과 표면 대조를 `Lesson` 하나로 묶는다. points 를 부르므로 판정 위다.
        ("조립", frozenset({"lesson"})),
        # 네이티브 루프에 닿는 경로 — lesson 을 카드 한 장과 모드로 옮긴다.
        ("도달", frozenset({"native"})),
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
