"""commands.studio 안쪽 사슬 — 한 파일이던 것을 책임별로 가른 뒤의 불변식."""

from __future__ import annotations

import ast
import os
import unittest

from architecture.astscan import _iter_py_files, _module_level_imports, _resolved_targets
from architecture.layers import SRC

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


if __name__ == "__main__":
    unittest.main()
