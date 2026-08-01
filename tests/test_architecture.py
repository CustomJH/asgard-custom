"""아키텍처 계층 규칙 — 계층형(도메인 패키지 변형) 의존 방향을 코드로 강제한다.

실행: uv run pytest tests/test_architecture.py

계층 (아래가 하위 — 상위는 하위만 임포트할 수 있다):
  foundation   settings·platform·theme·ui·i18n·io_journal·io_files·registry — 무의존 기반
  providers    providers·openai_codex — 외부 LLM/자격 인프라
  domain       memory군·skill_bank·lagom·charter·manual·code_map·health·surface·craft·thor_gate·tutor·evolution·templates·hooks — 비즈니스 규칙
  application  agent — 오케스트레이션 (Heimdall/Trinity/세션)
  interface    cli·commands — 진입점·표면

규칙은 **모듈 top-level 임포트**에만 적용한다 — 함수 내부 lazy import는 의도된 탈출구다
(예: repl → commands.update의 /update 실행, evolution → agent.session의 LLM 클라이언트).
새 상시 결합이 상향으로 생기면 이 테스트가 막는다.

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
                "hooks",
            }
        ),
    ),
    ("application", frozenset({"agent"})),
    ("interface", frozenset({"cli", "commands", "__main__"})),
]
_RANK = {name: i for i, (layer, names) in enumerate(LAYERS) for name in names}


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


def _top_targets(node: ast.stmt, parts: list[str]) -> set[str]:
    """import 문 → asgard 내부 top-level 대상 집합 (외부 라이브러리는 무시)."""
    out: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            bits = alias.name.split(".")
            if bits[0] == "asgard" and len(bits) > 1:
                out.add(bits[1])
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0:
            bits = (node.module or "").split(".")
            if bits and bits[0] == "asgard" and len(bits) > 1:
                out.add(bits[1])
        else:
            # 상대 임포트 해석 — parts는 파일의 패키지 경로 성분 (파일이 모듈이면 모듈명 포함)
            pkg = parts[:-1] if parts else []  # 담는 패키지 (모듈 파일 기준)
            base = pkg[: len(pkg) - (node.level - 1)] if node.level - 1 <= len(pkg) else []
            if node.module:
                target = base + node.module.split(".")
                if target:
                    out.add(target[0])
            else:
                for alias in node.names:
                    target = base + [alias.name]
                    out.add(target[0])
    return {t for t in out if t in _RANK or t == "assets"}


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

    def test_no_upward_toplevel_imports(self):
        """상위 계층 방향의 top-level 임포트 금지 — lazy(함수 내부) 임포트만 예외."""
        violations: list[str] = []
        for path in _iter_py_files():
            parts = _module_dotted(path)
            if not parts:  # asgard/__init__.py — 루트 파사드는 규칙 밖 (버전 표면)
                continue
            src_top = parts[0]
            if src_top not in _RANK:
                continue
            tree = ast.parse(open(path, encoding="utf-8").read())
            file_parts = _module_dotted(path)
            # __init__.py는 패키지 자신이 담는 패키지 — 상대 해석용 성분에 sentinel 추가
            rel = os.path.relpath(path, SRC)
            if rel.endswith("__init__.py"):
                file_parts = file_parts + ["__init__"]
            for node in tree.body:
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for target in _top_targets(node, file_parts):
                    if target == "assets" or target == src_top:
                        continue
                    if _RANK.get(target, -1) > _RANK[src_top]:
                        violations.append(
                            f"{rel}:{node.lineno} — {src_top}({_layer(src_top)}) → {target}({_layer(target)})"
                        )
        self.assertFalse(violations, "상향 계층 임포트 발견:\n" + "\n".join(violations))

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
        """위 모듈은 아래를 부르고, 아래는 위를 모른다."""
        rank = {name: index for index, name in enumerate(STUDIO_CHAIN)}
        violations: list[str] = []
        for name, tree in self._studio_modules().items():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level != 1 or node.col_offset != 0:
                    continue  # 함수 안 lazy 임포트는 의도된 탈출구다 (계층 규칙과 같은 관용)
                targets = {node.module} if node.module else {alias.name for alias in node.names}
                for target in targets:
                    if target in rank and rank[target] >= rank[name]:
                        violations.append(f"{name} → {target} (사슬을 거슬러 오른다)")
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
