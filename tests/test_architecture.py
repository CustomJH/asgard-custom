"""아키텍처 계층 규칙 — 계층형(도메인 패키지 변형) 의존 방향을 코드로 강제한다.

실행: uv run pytest tests/test_architecture.py

계층 (아래가 하위 — 상위는 하위만 임포트할 수 있다):
  foundation   settings·platform·theme·ui·i18n·io_journal·io_files·registry — 무의존 기반
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
판정 대상이 되고, 판정 커버리지는 242/527(45.9%)이 된다. 남은 285건은 같은 최상위 이름
안쪽(패키지 내부)이고, 그 층의 규칙은 STUDIO_CHAIN 이 한 패키지에 대해 먼저 세워 둔 형태다.
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
                "registry",
                # profiles — 에인헤랴르 홈 해석. settings가 이걸 부르므로 settings보다 아래여야
                # 하고, 실제로 무의존이다 (내장 명부만 templates를 lazy로 본다).
                "profiles",
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
                "tutor_probes",
                "tutor_growth",
                "map_context",
                "map_graph",
                # map_lex — 질의 어휘 사전. craft_lex·thor_lex와 같은 자리다: 순수 표이고, 그것을
                # 쓰는 판정(map_context 랭킹)은 위가 아니라 옆에 있다.
                "map_lex",
                # map_notes — 근거 주석 레인. map_graph(관계)와 같은 층의 다른 레인이다:
                # 소스에서 증거를 뽑고, 그것을 어디에 쓸지는 위층이 정한다.
                "map_notes",
                "k6",
                "evolution",
                "evolution_bench",
                "skill_curator",
                "templates",
                # swarm — 프로젝트가 루트의 에이전트를 배치하는 규칙. 설정 해석 + 배치 판정이라
                # charter/manual과 같은 자리이고, agent(application)·commands가 이걸 쓴다.
                "swarm",
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
        # 아래로 아무것도 안 본다 — 경로·기록·표·프로필.
        (
            "기반",
            frozenset(
                {"platform", "io_journal", "activity", "io_files", "registry", "failures", "profiles", "winterm"}
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
                }
            ),
        ),
        # 자립층 하나를 얹는다 — 판정 표(craft_rules→health), 색인(skill_registry→skill_bank),
        # 렌더(templates→hooks), 저장 어댑터 다리(memory_bridge→project_memory_backends).
        # evolution·skill_curator 도 skill_bank 하나만 보므로 같은 자리다.
        (
            "표",
            frozenset({"templates", "craft_rules", "memory_bridge", "skill_registry", "skill_curator", "evolution"}),
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
        ("계측", frozenset({"craft_c", "thor_lex", "tutor_probes", "map_graph", "map_context", "map_notes"})),
        # 계측을 합쳐 결론을 낸다.
        ("판정", frozenset({"craft"})),
        # 결론을 소비한다 — 막고(thor_gate·freyja_gate) 고치고(craft_fix) 되짚는다(tutor).
        ("적용", frozenset({"craft_fix", "freyja_gate", "thor_gate", "tutor"})),
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
        """훅 배포 계약 — hooks/*.py는 단일 파일로 `.claude/hooks/`에 복사 배포된다.

        따라서 asgard 임포트는 ① 상대 임포트 금지(복사본에서 즉사) ② 절대 `asgard.*` 임포트는
        try 블록 안 lazy만 허용(미설치 환경에서 fail-open 되는 선택적 강화 — 예: code_map 갱신,
        quest 요약). 무방비 임포트가 하나라도 생기면 복사 배포본이 죽는다."""
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
            tree = ast.parse(open(os.path.join(hooks_dir, f), encoding="utf-8").read())
            scan(tree, f, guarded=False)
        self.assertFalse(violations, "훅 자립 계약 위반:\n" + "\n".join(violations))

    def test_hooks_parse_on_old_python(self):
        """훅 문법 바닥 — hooks/*.py는 사용자 PATH의 `python3`로 돈다, asgard의 venv가 아니라.

        `platform.hook_python()`은 `shutil.which("python3")`이 찾은 것을 그대로 쓴다. 그래서
        asgard 자신의 `requires-python`은 훅에 대한 보장이 못 된다 — 훅이 최신 문법을 쓰면
        조금 낡은 기계에서 임포트 시점 SyntaxError가 되고, 훅 계약은 fail-open이라 그 죽음이
        **조용하다**: 사용자는 계층이 켜진 줄 알고 아무 일도 안 일어난다.

        실제로 그 자리가 있었다: 괄호 없는 다중 except (PEP 758, 3.14+)가 세 군데 있었고,
        3.13 기계에서는 매뉴얼 계층과 퀘스트 로그가 통째로 증발하는 상태였다.

        바닥을 3.9로 잡는다 — "python3라고 불리는 것"의 현실적 하한이다. 문법만 본다
        (`ast`는 실행하지 않는다). 새 문법이 정말 필요하면 이 상수를 올리되, 그건 훅이 도는
        기계의 최소 사양을 올리겠다는 **명시적 결정**이어야 한다."""
        floor = (3, 9)
        hooks_dir = os.path.join(SRC, "hooks")
        broken: list[str] = []
        for f in sorted(os.listdir(hooks_dir)):
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(hooks_dir, f), encoding="utf-8").read()
            try:
                ast.parse(src, filename=f, feature_version=floor)
            except SyntaxError as exc:
                broken.append(f"hooks/{f}:{exc.lineno} — {exc.msg}")
        self.assertFalse(
            broken,
            f"훅이 python {floor[0]}.{floor[1]} 에서 파싱되지 않는다 (조용히 죽는다):\n" + "\n".join(broken),
        )


# Studio 안쪽의 사슬 — `commands.studio` 패키지는 아래로만 기댄다. 이 순서가 곧 계약이다:
# 왼쪽이 오른쪽을 부를 수 없다. 하나라도 뒤집히면 순환이 생기고, 순환이 생기면 "이 모듈만
# 읽으면 된다"가 다시 거짓이 된다 (1,586줄 한 파일로 돌아가는 첫걸음이 그것이었다).
STUDIO_CHAIN = (
    "state",
    "dialog",
    "boundary",
    "tasks",
    "snapshot",
    "workspaces",
    "artifacts",
    "config",
    "routes",
    "server",
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
        base = os.path.join(SRC, "commands", "studio")
        out = {}
        for entry in sorted(os.listdir(base)):
            if entry.endswith(".py") and entry != "__init__.py":
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
