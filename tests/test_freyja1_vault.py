"""엔진1(freyja-design) 산출물 금고 앵커.

엔진1 은 벤더링된 Vanadis 스킬·롤을 "gates, artifacts, handoffs 를 보존"하며 그대로
수행한다. 그 산출물이 프로젝트 루트의 `.vanadis/` 였다 — preferences·state·timeline·
context JSON 이 git 에 그대로 보였고, 상류가 자체로 심던 `.vanadis/.gitignore` 는
`runs/`·`cache/` 만 가려서 나머지는 커밋 대상으로 남았다.

포팅 계약:
- 위치: `.asgard/.vanadis/engine1/`. 엔진2 는 같은 지붕 아래 `engine2/` 를 쓰므로 두
  엔진이 한 프로젝트에서 돌아도 `config.json` 류가 서로를 덮지 않는다.
- 불가시: 이미 무시되는 `.asgard/` 를 상속한다. 어떤 ignore 파일도 만들지 않는다.
- 영구 기록은 금고가 아니다: `preferences.md` 는 `vanadis:learn` 이 `DESIGN.md` 로
  승격시키는 버퍼이고, 팀이 보관하는 것은 `DESIGN.md` 다.

엔진1 의 쓰기 주체는 코드가 아니라 프롬프트 텍스트라, 결정론적으로 고정할 수 있는 것은
지시문 자체다. 이 파일은 그 지시문을 앵커한다.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SKILL_ROOT = _REPO / "src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design"
_VANADIS = _SKILL_ROOT / "references/vanadis"

_VAULT_REL = ".asgard/.vanadis/engine1"

# 정본 형태 두 가지. 위반을 찾기 전에 이것부터 지운다 — 안 그러면 세그먼트로 쪼갠
# `join(root, '.asgard', '.vanadis', 'engine1')` 의 가운데 조각이 위반으로 잡힌다.
_CANONICAL = (
    ".asgard/.vanadis/engine1",
    "'.asgard', '.vanadis', 'engine1'",
    '".asgard", ".vanadis", "engine1"',
)

# 남은 것 중 은퇴한 루트를 *경로로* 쓰는 형태만 잡는다. `.vanadis-managed.json` 처럼
# 하이픈이 이어지는 이름은 산출물 디렉터리가 아니다.
_ROOT_VANADIS = re.compile(r"(?<![A-Za-z0-9_./-])\.vanadis(?![A-Za-z0-9_-])")


def _strip_canonical(line: str) -> str:
    for form in _CANONICAL:
        line = line.replace(form, "")
    return line


# 기록물은 검사 대상이 아니다: lab-02 의 runs/ 는 과거 실행 전사(轉寫)이고,
# architecture-proposals 는 당시 결정을 남긴 문서다. 둘 다 지시문이 아니므로 그때의
# 경로를 보존한다. node_modules 는 벤더링 대상이 아니다.
_RECORDS = (
    "vanadis-lab-02-design-harness/runs/",
    "data/architecture-proposals/",
    "/node_modules/",
)


def _scanned_files() -> list[Path]:
    """벤더링 트리 전체. 프롬프트 미러(.claude/·.codex/)와 훅 코드까지 포함한다.

    처음엔 `skills/`·`agents/` 만 훑었는데, 그 사이 `.claude/skills`·`.claude/agents`·
    `.codex/agents` 미러 26개와 실제로 경로를 만드는 `.claude/hooks/*.cjs` 5개가
    옛 루트를 그대로 들고 살아남았다(실측으로 발각). 좁은 스캔이 통과시킨 결함이라
    스캔 범위를 트리 전체로 넓혀 고정한다.
    """
    out = []
    for path in sorted(_VANADIS.rglob("*")):
        if not path.is_file():
            continue
        posix = path.as_posix()
        if any(marker in posix for marker in _RECORDS):
            continue
        out.append(path)
    return out


def _prompt_files() -> list[Path]:
    return [p for p in _scanned_files() if p.suffix in {".md", ".toml"}]


class TestEngine1VaultContract(unittest.TestCase):
    def test_scan_reaches_the_mirrors(self):
        """경로가 틀리면 아래 검사들이 조용히 0건을 통과한다 — 먼저 못을 박는다."""
        scanned = {p.relative_to(_VANADIS).as_posix() for p in _scanned_files()}
        self.assertGreater(len(scanned), 500, f"벤더링 트리를 찾지 못했다: {_VANADIS}")
        for must in (
            "skills/vanadis-remember/SKILL.md",
            ".claude/skills/vanadis-remember/SKILL.md",
            ".claude/agents/vanadis-master.md",
            ".codex/agents/vanadis-master.toml",
            ".claude/hooks/session-end-foldin.cjs",
            "scripts/ctx-prime.cjs",
        ):
            self.assertIn(must, scanned, f"스캔이 {must} 를 놓친다 — 미러가 다시 새어나간다")

    def test_nothing_writes_to_the_project_root(self):
        """스킬·롤·미러·훅 코드 어디도 루트 `.vanadis/` 를 지시하거나 만들지 않는다."""
        offenders: list[str] = []
        for path in _scanned_files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError, OSError:
                continue  # 바이너리 자산은 경로 지시를 담지 않는다
            for lineno, line in enumerate(text.splitlines(), 1):
                if _ROOT_VANADIS.search(_strip_canonical(line)):
                    rel = path.relative_to(_VANADIS).as_posix()
                    offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(
            offenders,
            [],
            "엔진1 이 아직 루트 `.vanadis/` 를 쓴다:\n" + "\n".join(offenders),
        )

    def test_code_builds_the_vault_path_in_segments(self):
        """훅·스크립트는 `path.join(root, '.asgard', '.vanadis', 'engine1', …)` 형태여야 한다.

        치환을 두 번 먹여 `'.asgard', '.asgard/.vanadis/engine1', 'engine1'` 같은 잡종이
        생겼던 자리다 — 문법은 통과하고 경로만 조용히 틀린다.
        """
        offenders: list[str] = []
        for path in _scanned_files():
            if path.suffix not in {".cjs", ".mjs", ".js", ".ts"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "'.asgard/.vanadis/engine1'" in line or "'.asgard', '.asgard" in line:
                    offenders.append(f"{path.relative_to(_VANADIS).as_posix()}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(offenders, [], "금고 경로가 세그먼트로 쪼개지지 않았다:\n" + "\n".join(offenders))

    def test_artifacts_are_named_under_the_engine1_vault(self):
        """이동이 실제로 일어났는지 — 산출물 이름들이 새 경로를 달고 있어야 한다."""
        corpus = "\n".join(p.read_text(encoding="utf-8") for p in _prompt_files())
        for artifact in ("preferences.md", "runs/INDEX.md", "context.json"):
            self.assertIn(
                f"{_VAULT_REL}/{artifact}",
                corpus,
                f"{artifact} 가 금고 경로로 옮겨지지 않았다",
            )

    def test_no_prompt_plants_an_ignore_file(self):
        """상류의 `.vanadis/.gitignore` 자가 설치는 제거됐다 — `.asgard/` 로 충분하다."""
        offenders: list[str] = []
        for path in _prompt_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if ".gitignore" not in line:
                    continue
                # 읽기·언급은 무해하다. 쓰기만 잡는다.
                if re.search(r"(>|>>|Write|write_file|touch)\s*[\"'`]?[^\s\"'`]*\.gitignore", line):
                    rel = path.relative_to(_VANADIS).as_posix()
                    offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(
            offenders,
            [],
            "엔진1 프롬프트가 ignore 파일을 심는다 — `.asgard/` 가 이미 덮는다:\n" + "\n".join(offenders),
        )

    def test_cli_points_at_the_vault(self):
        """설치 CLI 가 사용자에게 안내하는 preferences 경로도 금고여야 한다."""
        source = (_VANADIS / "src/cli/install-skills.ts").read_text(encoding="utf-8")
        self.assertIn(f"@{_VAULT_REL}/preferences.md", source)
        self.assertNotIn("@.vanadis/preferences.md", source)

    def test_skill_contract_states_the_vault(self):
        """엔진1 의 아스가르드측 계약이 위치·불가시·비영구성을 명시한다."""
        skill = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"{_VAULT_REL}/", skill)
        self.assertIn("never create or edit a `.gitignore`", skill)
        self.assertIn("DESIGN.md", skill)

    def test_both_engines_share_the_roof_without_colliding(self):
        """엔진1·2 는 `.asgard/.vanadis/` 아래 서로 다른 칸을 쓴다."""
        engine2_vault = (
            _REPO / "src/asgard/assets/skill_plugins/freyja2/skills/asgard-freyja2" / "engine/scripts/lib/vault.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("'.asgard', '.vanadis', 'engine2'", engine2_vault)
        self.assertTrue(_VAULT_REL.endswith("engine1"))

    def test_repo_gitignore_needs_no_entry_for_engine1(self):
        lines = [line.strip() for line in (_REPO / ".gitignore").read_text(encoding="utf-8").splitlines()]
        self.assertIn("**/.asgard/", lines)
        rules = [line for line in lines if line and not line.startswith("#")]
        self.assertFalse(
            [line for line in rules if "vanadis" in line],
            "엔진1 전용 gitignore 항목이 생겼다",
        )


if __name__ == "__main__":
    unittest.main()
