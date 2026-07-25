"""엔진2가 Asgard 것으로 말하고, Asgard 밖으로 말을 걸지 않는다.

원본(impeccable) 대조 검증(2026-07-25)에서 셋이 같이 나왔다.

- 엔진이 상류 제품명을 1,349곳에 그대로 달고 있어, 훅이 발견을 보고할 때마다 Asgard 에
  없는 `/impeccable audit`·`/impeccable hooks ignore-value` 를 실행하라고 지시했다.
  억제 워크플로가 통째로 끊긴 상태였다.
- `context.mjs` 가 세션마다 상류 호스트로 버전을 물으러 나갔고, 새 버전이면 `npx` 로
  업데이트하라고 안내했다. 엔진은 Asgard 휠에 실려 오므로 둘 다 성립하지 않는다.
- `engine/hooks/*.json` 이 상류 설치 경로를 가리켜, 배선해도 맞지 않았다.

셋 다 봉합했고 이 파일이 되돌아가지 못하게 잡는다. 개명에서 **의도적으로 제외**한 것은
은퇴한 금고 루트 `.impeccable` 하나뿐이다 — 그걸 아직 들고 있는 프로젝트를 읽어야 한다.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ENGINE = _REPO / "src/asgard/assets/skill_plugins/freyja2/skills/asgard-freyja2/engine"
_SCRIPTS = _ENGINE / "scripts"
_VENDOR_DIR = _SCRIPTS / "detector/vendor"

# 은퇴 금고 루트는 남는다. `.impeccable-overlay` 같은 클래스명은 개명 대상이었다.
_LEGACY_VAULT_RE = re.compile(r"\.impeccable(?![-\w])")

# 두 번째 면제: 파일 안에 박혀 이동하는 waiver 는 옛 철자로 쓰여 있어도 계속 먹혀야 한다.
# 그 호환은 이 파일 하나에만 산다 (TestUpstreamSpellingStillHonored 가 존재를 강제한다).
_SPELLING_COMPAT = "scripts/detector/shared/inline-ignores.mjs"


def _engine_files() -> list[Path]:
    return [
        p
        for p in sorted(_ENGINE.rglob("*"))
        if p.is_file() and _VENDOR_DIR not in p.parents  # 벤더 번들은 제3자 텍스트
    ]


class TestUpstreamNameIsGone(unittest.TestCase):
    def test_only_the_retired_vault_root_keeps_the_upstream_name(self):
        leftovers: list[str] = []
        for path in _engine_files():
            if path.relative_to(_ENGINE).as_posix() == _SPELLING_COMPAT:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            stripped = _LEGACY_VAULT_RE.sub("", text)
            for i, line in enumerate(stripped.splitlines(), 1):
                if "impeccable" in line.lower():
                    leftovers.append(f"{path.relative_to(_ENGINE)}:{i}: {line.strip()[:100]}")
        self.assertEqual(
            leftovers,
            [],
            "상류 제품명이 남아 있다(은퇴 금고 루트 `.impeccable` 은 예외):\n" + "\n".join(leftovers[:20]),
        )

    def test_agent_files_carry_the_engine_name(self):
        names = sorted(p.name for p in (_ENGINE / "agents").glob("*.md"))
        self.assertTrue(names, "엔진 서브에이전트 파일이 없다")
        for name in names:
            self.assertTrue(name.startswith("freyja2-"), f"에이전트 파일명이 개명되지 않았다: {name}")

    def test_slash_commands_name_this_engine(self):
        provider = (_SCRIPTS / "lib/provider.mjs").read_text(encoding="utf-8")
        self.assertIn("FREYJA2_COMMAND = `${FREYJA2_COMMAND_PREFIX}freyja2`", provider)


class TestUpstreamSpellingStillHonored(unittest.TestCase):
    """면제는 하나 더 있다 — 파일 안에 박혀 이동하는 waiver."""

    def test_inline_ignore_accepts_both_spellings(self):
        source = (_SCRIPTS / "detector/shared/inline-ignores.mjs").read_text(encoding="utf-8")
        self.assertIn("(?:freyja2|impeccable)-(disable-next-line", source)
        self.assertIn("(?:freyja2|impeccable)-disable", source)

    def test_legacy_vault_root_is_still_read(self):
        vault = (_SCRIPTS / "lib/vault.mjs").read_text(encoding="utf-8")
        self.assertIn("LEGACY_VAULT_RELS = Object.freeze(['.impeccable'])", vault)


class TestNoOutboundUpdateCheck(unittest.TestCase):
    def test_boot_makes_no_network_call(self):
        context = (_SCRIPTS / "context.mjs").read_text(encoding="utf-8")
        for banned in ("fetch(", "UPDATE_HOST", "UPDATE_AVAILABLE", "npx "):
            self.assertNotIn(banned, context, f"세션 부팅 경로에 {banned!r} 이 돌아왔다")

    def test_the_seam_survives(self):
        """넛지를 되살릴 자리는 남겨 둔다 — 다만 Asgard 신호로."""
        context = (_SCRIPTS / "context.mjs").read_text(encoding="utf-8")
        self.assertIn("async function computeUpdateDirective()", context)


class TestHookManifestsPointAtTheRealEngine(unittest.TestCase):
    def test_manifests_are_valid_and_self_locating(self):
        hooks_dir = _ENGINE / "hooks"
        manifests = sorted(hooks_dir.glob("*.json"))
        self.assertEqual(len(manifests), 2, "훅 매니페스트 2종이 있어야 한다")
        for path in manifests:
            payload = json.dumps(json.load(open(path, encoding="utf-8")))
            self.assertIn("${FREYJA2_ENGINE}/scripts/hook.mjs", payload, f"{path.name} 이 실경로를 가리키지 않는다")
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", payload)
            self.assertNotIn(".claude/skills", payload)
        self.assertTrue((hooks_dir / "README.md").is_file(), "매니페스트 사용법 문서가 없다")

    def test_doctor_resolves_that_variable(self):
        """README 가 안내하는 경로 해석이 실제로 그 엔진을 가리킨다."""
        from asgard.commands.doctor import _freyja_engine_dir

        self.assertEqual(_freyja_engine_dir().resolve(), _ENGINE.resolve())


if __name__ == "__main__":
    unittest.main()
