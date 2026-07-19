"""아키텍처 계층 규칙 — 계층형(도메인 패키지 변형) 의존 방향을 코드로 강제한다.

실행: uv run pytest tests/test_architecture.py

계층 (아래가 하위 — 상위는 하위만 임포트할 수 있다):
  foundation   settings·platform·theme·ui·i18n·io_journal·registry — 무의존 기반
  providers    providers·openai_codex — 외부 LLM/자격 인프라
  domain       memory군·skill_bank·lagom·charter·code_map·evolution·templates·hooks — 비즈니스 규칙
  application  agent — 오케스트레이션 (Heimdall/Trinity/세션)
  interface    cli·commands — 진입점·표면

규칙은 **모듈 top-level 임포트**에만 적용한다 — 함수 내부 lazy import 는 의도된 탈출구다
(예: repl → commands.update 의 /update 실행, evolution → agent.session 의 LLM 클라이언트).
새 상시 결합이 상향으로 생기면 이 테스트가 막는다.

hooks/ 는 별도 불변식: `.claude/hooks/` 로 단일 파일 복사 배포되는 계약이므로 상대 임포트는
금지, asgard 절대 임포트는 try 안 lazy(미설치 시 fail-open 되는 선택적 강화)만 허용된다.
"""

from __future__ import annotations

import ast
import os
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "asgard")

LAYERS: list[tuple[str, frozenset[str]]] = [
    ("foundation", frozenset({"settings", "platform", "theme", "ui", "i18n", "io_journal", "registry"})),
    ("providers", frozenset({"providers", "openai_codex"})),
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
                "lagom",
                "charter",
                "code_map",
                "evolution",
                "evolution_bench",
                "templates",
                "hooks",
            }
        ),
    ),
    ("application", frozenset({"agent"})),
    ("interface", frozenset({"cli", "commands", "__main__"})),
]
_RANK = {name: i for i, (layer, names) in enumerate(LAYERS) for name in names}


def _module_dotted(path: str) -> list[str]:
    """src/asgard 기준 상대 경로 → 패키지 경로 성분 (파일명 제외 규칙: __init__ 은 패키지 자신)."""
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
            # 상대 임포트 해석 — parts 는 파일의 패키지 경로 성분 (파일이 모듈이면 모듈명 포함)
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
            # __init__.py 는 패키지 자신이 담는 패키지 — 상대 해석용 성분에 sentinel 추가
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
        """훅 배포 계약 — hooks/*.py 는 단일 파일로 `.claude/hooks/` 에 복사 배포된다.

        따라서 asgard 임포트는 ① 상대 임포트 금지(복사본에서 즉사) ② 절대 `asgard.*` 임포트는
        try 블록 안 lazy 만 허용(미설치 환경에서 fail-open 되는 선택적 강화 — 예: code_map 갱신,
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


def _layer(top: str) -> str:
    return LAYERS[_RANK[top]][0]


if __name__ == "__main__":
    unittest.main()
