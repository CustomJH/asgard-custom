#!/usr/bin/env python3
"""릴리즈 게이트 — 로컬에서 도는 것과 CI 가 도는 것이 같은가.

실행: uv run pytest tests/test_release_gate.py

이 파일이 있는 까닭은 26-08-17 에 태그 둘이 릴리즈 없이 남은 사고다. `release` 워크플로는
`quality` 잡이 통과해야 `release` 잡을 돌리는데, 그 잡과 같은 것을 로컬에서 돌 자리가 없었다.
`just check` 는 넷을 돌고 워크플로는 여섯을 돌아서, 로컬 초록이 CI 초록을 뜻하지 않았다 —
v0.10.15 는 포맷에서, v0.10.16 은 `ty check` 에서 멈췄고 둘 다 휠이 안 나갔다.

그래서 `just gate` 를 세우고 여기서 **워크플로와 대조한다**. 목록을 손으로 맞추면 다음에 CI 에
한 단이 늘 때 그 한 단이 그대로 구멍이 되므로, 양쪽을 파싱해 순서까지 같은지 본다.
"""

from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "release.yml")
JUSTFILE = os.path.join(ROOT, "Justfile")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _quality_steps() -> list[str]:
    """`release.yml` 의 quality 잡이 실제로 돌리는 명령 — 선언 순서 그대로.

    lagom: YAML 파서를 안 쓴다. 이 저장소에 의존이 없고, 재는 것은 한 잡 안의 `run:` 한 줄
    목록이라 블록을 잘라 훑는 것으로 충분하다. 여러 줄 `run: |` 은 이 워크플로에 없다 —
    생기면 아래 정규식이 그 줄을 못 보고 시험이 조용히 덜 재게 되므로, 그때 파서를 올려야 한다."""
    text = _read(WORKFLOW)
    start = text.index("\n  quality:")
    rest = text[start + 1 :]
    # 다음 최상위 잡(두 칸 들여쓴 `이름:`)까지가 이 잡의 몸통이다.
    end = re.search(r"^  [a-z][a-z0-9-]*:$", rest[len("  quality:") :], re.M)
    body = rest[: len("  quality:") + end.start()] if end else rest
    return [line.strip() for line in re.findall(r"^\s*- run: (.+)$", body, re.M)]


def _gate_recipe() -> list[str]:
    """Justfile `gate` 레시피의 명령 줄 — 들여쓴 줄이 끝날 때까지."""
    lines = _read(JUSTFILE).splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("gate:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        if not line[:1].isspace():
            break
        body.append(line.strip())
    return body


class GateMatchesCI(unittest.TestCase):
    def test_the_workflow_declares_the_steps_this_test_reads(self) -> None:
        """파싱이 조용히 빈 목록을 내면 아래 대조가 통과하는 시늉만 한다."""
        steps = _quality_steps()
        self.assertGreaterEqual(len(steps), 5, f"quality 잡에서 읽어 낸 단이 너무 적어요: {steps}")
        self.assertIn("uv run ty check", steps)

    def test_the_local_gate_runs_exactly_what_ci_runs(self) -> None:
        self.assertEqual(
            _gate_recipe(),
            _quality_steps(),
            "`just gate` 와 release.yml 의 quality 잡이 갈렸어요 — 로컬 초록이 CI 초록을 뜻하지 않게 됩니다",
        )

    def test_the_recipe_lives_outside_the_managed_region(self) -> None:
        """관리 구역 안에 두면 다음 `asgard just sync` 가 지운다 — 그 삭제는 조용하다."""
        from asgard import justfile

        text = _read(JUSTFILE)
        managed = text[text.index(justfile.BEGIN) : text.index(justfile.END)]
        self.assertNotIn("gate:", managed)
        self.assertIn("gate:", text)


if __name__ == "__main__":
    unittest.main()
