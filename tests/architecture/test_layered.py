"""계층·등급·훅 배포 계약 — 상향 임포트와 훅 자립을 막는다."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import unittest

from architecture.astscan import _layer, _toplevel_edges
from architecture.layers import _RANK, _SUBRANK, _SUBTIER_NAME, HOOK_LIBRARY, LAYERS, SRC, SUBTIERS


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
                # 줄 번호는 임포트 노드에서만 읽는다 — `iter_child_nodes` 가 주는 `ast.AST` 에는
                # `lineno` 가 없고, 아래 보고 줄은 `targets` 가 찬 두 갈래에서만 돈다.
                line = 0
                if isinstance(child, ast.ImportFrom) and child.level == 0:
                    targets, line = [(child.module or "").split(".")[0]], child.lineno
                elif isinstance(child, ast.Import):
                    targets, line = [a.name.split(".")[0] for a in child.names], child.lineno
                for target in targets:
                    if target == "asgard" and not guarded:
                        violations.append(f"{HOOK_LIBRARY}/{fname}:{line} — try 밖 asgard 임포트")
                    elif target in hook_modules:
                        violations.append(f"{HOOK_LIBRARY}/{fname}:{line} — 훅({target})을 부른다 (방향 역전)")
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

    def test_hooks_do_not_evaluate_new_union_syntax_at_import(self):
        """문법 바닥의 두 번째 축 — 파싱되는데 **정의될 때** 죽는 어노테이션.

        위 시험은 `ast.parse` 로 문법만 본다. `str | None` 은 3.9 에서 문법으로는 멀쩡히 파싱되고
        함수를 정의하는 순간 `TypeError: unsupported operand type(s) for |` 로 죽는다. 죽는 자리가
        모듈 임포트 시점이라 훅의 fail-open(`main()` 의 except)보다 앞이고, 그래서 훅 계약이
        약속한 조용한 exit 0 대신 traceback 과 exit 1 이 나간다.

        26-08-13 에 그 자리가 둘 있었다 — codex 독립 판정이 3.9.6 에서 실제로 재현했다. 위 시험은
        그동안 초록이었다: 두 시험이 보는 것이 문법과 평가로 서로 다르다.

        고치는 법은 하나다: `from __future__ import annotations`. 그러면 어노테이션이 문자열로
        남아 평가되지 않는다. 그것을 쓴 모듈은 여기서 면제된다."""
        hooks_dir = os.path.join(SRC, "hooks")
        library_dir = os.path.join(hooks_dir, HOOK_LIBRARY)
        listing = [(hooks_dir, f) for f in sorted(os.listdir(hooks_dir)) if f.endswith(".py")]
        listing += [(library_dir, f) for f in sorted(os.listdir(library_dir)) if f.endswith(".py")]
        offenders: list[str] = []
        for directory, name in listing:
            path = os.path.join(directory, name)
            tree = ast.parse(open(path, encoding="utf-8").read())
            deferred = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "__future__"
                and any(alias.name == "annotations" for alias in node.names)
                for node in tree.body
            )
            if deferred:
                continue
            rel = os.path.relpath(path, hooks_dir).replace(os.sep, "/")
            for node in ast.walk(tree):
                spots = []
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = node.args
                    spots = [a.annotation for a in (*args.posonlyargs, *args.args, *args.kwonlyargs) if a.annotation]
                    spots += [a.annotation for a in (args.vararg, args.kwarg) if a is not None and a.annotation]
                    spots += [node.returns] if node.returns else []
                elif isinstance(node, ast.AnnAssign):
                    spots = [node.annotation]
                for annotation in spots:
                    if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(annotation)):
                        offenders.append(f"hooks/{rel}:{annotation.lineno} — {ast.unparse(annotation)}")
        self.assertFalse(
            offenders,
            "훅 어노테이션이 임포트 시점에 평가되어 낡은 파이썬에서 죽는다 "
            "(`from __future__ import annotations` 를 넣어라):\n" + "\n".join(offenders),
        )

    def test_hooks_import_on_the_floor_interpreter_when_one_is_installed(self):
        """위 둘이 못 보는 나머지 — 실제로 바닥 인터프리터에 태워 본다.

        앞의 두 시험은 각자 구멍이 있다. `ast.parse` 는 문법만 보고, 어노테이션 검사는 어노테이션
        자리만 본다. 모듈 수준 별칭(`MaybeText = str | None`)은 둘 다 지나가면서 3.9 임포트에서
        TypeError 로 죽는다 — 26-08-13 codex 독립 판정 3회차가 이 구멍을 만들어 보였다. 패턴을
        넓혀 잡으려 하면 `A | B` 가 집합 연산인 멀쩡한 줄까지 잡거나 다시 구멍이 난다 (이 저장소가
        가드 정규식에서 세 턴 연속 겪은 진동). 그래서 패턴을 넓히는 대신 **실행**으로 판정한다.

        임포트만 하고 `main()` 은 안 돈다 — 훅은 `if __name__ == "__main__"` 뒤에 있어서 부작용이
        없고, 죽는 자리는 정의 시점이라 임포트로 잡힌다.

        바닥 인터프리터가 없는 기계에서는 건너뛴다. 건너뛴 시험은 가드가 아니므로 위 둘을 지운
        대신이 아니라 그 위에 얹는 층이다."""
        floor = self._floor_interpreter()
        if not floor:
            self.skipTest("python 3.9 인터프리터가 이 기계에 없다 — 위 두 정적 시험만 선다")
        hooks_dir = os.path.join(SRC, "hooks")
        # `sys.modules` 등록은 생략하면 안 된다 — 3.9 의 dataclasses 는 필드 타입을 풀 때
        # `sys.modules.get(cls.__module__)` 를 거치고, 등록 안 된 모듈에서는 그것이 None 이라
        # 멀쩡한 훅이 AttributeError 로 죽는다. 실제 호스트는 훅을 `__main__` 으로 돌려 그 자리가
        # 없으므로, 등록을 빼면 시험만 빨개진다 (budget_guard 가 실제로 그렇게 걸렸다).
        probe = (
            "import importlib.util,os,sys\n"
            "h=sys.argv[1]\n"
            "sys.path.insert(0,h)\n"
            "bad=[]\n"
            "for f in sorted(os.listdir(h)):\n"
            "    if not f.endswith('.py'): continue\n"
            "    name='hk_'+f[:-3].replace('-','_')\n"
            "    s=importlib.util.spec_from_file_location(name,os.path.join(h,f))\n"
            "    m=importlib.util.module_from_spec(s)\n"
            "    sys.modules[name]=m\n"
            # `Exception` 만 잡으면 `SystemExit` 이 그물을 빠져나간다 — 그것은 `BaseException` 이라
            # 탐침 프로세스를 조용히 끝내고, stdout 만 보던 판정은 초록을 냈다 (26-08-14 codex
            # 독립 판정이 import 시점 `SystemExit(7)` 로 그 구멍을 만들어 보였다). 종료 코드도 함께
            # 본다: 탐침이 끝까지 못 간 것과 훅이 멀쩡한 것은 서로 다른 사실이다.
            "    try: s.loader.exec_module(m)\n"
            "    except BaseException as e: bad.append('%s: %s: %s'%(f,type(e).__name__,e))\n"
            "print('\\n'.join(bad))\n"
        )
        p = subprocess.run([floor, "-c", probe, hooks_dir], capture_output=True, text=True, cwd=SRC)
        self.assertEqual(
            p.returncode,
            0,
            "바닥 인터프리터(%s) 탐침이 끝까지 못 갔다 — 훅 임포트 판정을 못 세운다:\n%s"
            % (floor, (p.stderr or p.stdout).strip()[-800:]),
        )
        self.assertFalse(
            p.stdout.strip(),
            "훅이 바닥 인터프리터(%s) 임포트에서 죽는다 — fail-open 보다 앞이라 조용하지도 않다:\n%s"
            % (floor, p.stdout.strip()),
        )

    @staticmethod
    def _floor_interpreter() -> str | None:
        """이 기계에 있는 3.9 인터프리터 — 없으면 None. 정본 경로(uv)가 아니라 폴백 경로를 흉내낸다."""
        for candidate in ("python3.9", "/usr/bin/python3"):
            path = shutil.which(candidate) if not candidate.startswith("/") else candidate
            if not path or not os.path.exists(path):
                continue
            probe = subprocess.run(
                [path, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True
            )
            if probe.returncode == 0 and probe.stdout.strip() == "3.9":
                return path
        return None


if __name__ == "__main__":
    unittest.main()
