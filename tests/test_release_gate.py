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

import json
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


class VersionSourcesAgree(unittest.TestCase):
    """한 릴리즈가 내는 산출물은 한 버전을 말해야 한다.

    이 저장소는 버전을 두 곳에 든다 — 파이썬 패키지의 `src/asgard/__init__.py` 와 윈도우 창의
    `studio-shell`(자기 매니페스트 다섯). 태그를 대조하는 `verify-tag` 잡은 앞의 하나만 봐서,
    v0.10.18 릴리즈에 `Asgard.Studio_0.10.17_x64-setup.exe` 가 붙어 나갔다. 휠은 이름이 맞아
    `install.sh` 는 성립했고, 그래서 아무 잡도 빨개지지 않았다 — 어긋남이 파일 이름에만 남는
    종류라 사람이 릴리즈 페이지를 볼 때까지 안 보인다.
    """

    def _asgard_version(self) -> str:
        text = _read(os.path.join(ROOT, "src", "asgard", "__init__.py"))
        found = re.search(r'__version__ = "([^"]+)"', text)
        assert found, "src/asgard/__init__.py 에서 __version__ 을 못 읽었어요"
        return found.group(1)

    # 버전을 **필드로** 읽는다. 정규식 첫 일치로 읽던 판은 조용히 덜 쟀다 — `package-lock.json`
    # 에서 `"version": "..."` 은 14번 걸리고 그중 열둘이 의존성 버전이라, `re.search` 는 첫 자리
    # 하나만 보고 `re.findall` 은 남의 버전까지 우리 것과 견준다. 어느 쪽도 "이 패키지의 버전"을
    # 재지 않는다. JSON 은 파서로 열어 이름으로 집고, 나머지 둘은 그 값이 사는 구간에 앵커를 건다.
    #
    # 락파일 둘이 목록에 있는 이유는 빌드가 그것을 읽어서다 — 매니페스트만 올리고 락을 두면
    # 빌드가 옛 버전으로 이름을 짓는다. `package-lock.json` 은 자기 버전을 두 자리에 든다.
    _JSON_SOURCES = (
        (("studio-shell", "package.json"), (("version",),)),
        (("studio-shell", "package-lock.json"), (("version",), ("packages", "", "version"))),
        (("studio-shell", "src-tauri", "tauri.conf.json"), (("version",),)),
    )
    # `Cargo.toml` 의 앵커가 `[package]` 인 이유: `[dependencies.foo]` 절 안의 `version` 도 줄
    # 머리에 서므로 `(?m)^version` 만으로는 의존성을 우리 것으로 읽는다.
    _TEXT_SOURCES = (
        (("studio-shell", "src-tauri", "Cargo.toml"), r'\[package\][^\[]*?^version = "([^"]+)"'),
        (("studio-shell", "src-tauri", "Cargo.lock"), r'name = "asgard-studio"\nversion = "([^"]+)"'),
    )

    def _field(self, data: object, path: tuple[str, ...], rel: str) -> str:
        """`path` 가 가리키는 값. 없으면 시험을 세운다 — 조용히 건너뛰면 안 재고 통과한다."""
        node: object = data
        for key in path:
            # `self.fail` 이 아니라 `raise` 인 이유: ty 는 `fail` 을 종료로 안 읽어서 그 뒤의 접근이
            # 여전히 `object` 위에서 도는 것으로 본다. 그리고 좁혀진 `dict` 는 키 타입이 미지라
            # 문자열로 첨자를 걸 수 없으므로, JSON 객체의 키가 문자열이라는 사실을 여기서 적는다.
            if not isinstance(node, dict):
                raise AssertionError(f"{rel} 의 {'.'.join(path)} 위쪽이 객체가 아니에요")
            table: dict[str, object] = {str(k): v for k, v in node.items()}
            if key not in table:
                raise AssertionError(f"{rel} 에 {'.'.join(path) or '(root)'} 가 없어요 — 형식이 바뀌었으면 표도 바꿔요")
            node = table[key]
        if not isinstance(node, str):
            raise AssertionError(f"{rel} 의 {'.'.join(path)} 가 문자열이 아니에요: {type(node).__name__}")
        return node

    def test_the_studio_shell_ships_the_version_the_package_ships(self) -> None:
        expected = self._asgard_version()
        for parts, paths in self._JSON_SOURCES:
            rel = os.path.join(*parts)
            data = json.loads(_read(os.path.join(ROOT, rel)))
            for path in paths:
                with self.subTest(file=rel, field=".".join(path)):
                    self.assertEqual(
                        self._field(data, path, rel),
                        expected,
                        f"{rel} 의 {'.'.join(path)} 이 __version__({expected}) 과 갈렸어요"
                        " — 릴리즈 산출물 이름이 어긋납니다",
                    )
        for parts, pattern in self._TEXT_SOURCES:
            rel = os.path.join(*parts)
            with self.subTest(file=rel):
                found = re.search(pattern, _read(os.path.join(ROOT, rel)), re.M | re.S)
                if found is None:  # `assertIsNotNone` 은 타입을 안 좁힌다 — 아래 group() 이 ty 에 걸린다
                    self.fail(f"{rel} 에서 버전을 못 읽었어요 — 형식이 바뀌었으면 정규식도 바꿔요")
                self.assertEqual(
                    found.group(1),
                    expected,
                    f"{rel} 이 __version__({expected}) 과 갈렸어요 — 릴리즈 산출물 이름이 어긋납니다",
                )

    def test_the_tag_check_covers_every_version_source(self) -> None:
        """`verify-tag` 가 파이썬 쪽만 보면, 창 버전은 태그를 밀 때까지 아무도 안 본다."""
        workflow = _read(WORKFLOW)
        start = workflow.index("\n  verify-tag:")
        body = workflow[start : workflow.index("\n  quality:")]
        self.assertIn("src/asgard/__init__.py", body)
        self.assertIn("tauri.conf.json", body, "verify-tag 가 studio-shell 버전을 안 봐요")


if __name__ == "__main__":
    unittest.main()
