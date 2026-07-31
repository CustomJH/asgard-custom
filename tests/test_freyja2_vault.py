"""엔진2(freyja2) 산출물 금고 — Fólkvangr 앵커.

엔진2는 프로젝트 루트에 점 디렉터리 `.impeccable/`를 만들어 디자인 사이드카·크리티크
스냅샷·live 저널·훅 캐시를 쌓아 뒀다. git에 그대로 보였고, 판별이 끝나도 남았다.

포팅 계약 3항:
- 위치: 산출물은 `.asgard/.vanadis/engine2/` 아래에만 쓴다. `.asgard`는 `asgard init`이 만드는
  아스가르드 런타임 디렉터리다.
- 불가시: 이미 무시되는 `.asgard/`를 상속한다. 엔진은 어떤 ignore 파일도 쓰거나 고치지
  않는다 — 금고 몫의 gitignore 항목은 존재하지 않는다.
- 정리: 판별이 끝나면 `vault.mjs sweep`(런 한정) / `purge`(전부)로 비운다.

레거시 `.impeccable/`는 읽기 폴백으로만 살아 있다(기존 프로젝트 무손실). 쓰기는 절대 그리
가지 않는다 — 이 파일이 그 비대칭을 고정한다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ENGINE = _REPO / "src/asgard/assets/skill_plugins/freyja2/skills/asgard-freyja2/engine"
_SCRIPTS = _ENGINE / "scripts"
_NODE = shutil.which("node")

# 은퇴한 산출물 루트를 *경로로* 쓰는 형태만 잡는다: `.impeccable/` 또는 따옴표로 닫힌
# `'.impeccable'`. CSS 클래스·DOM dataset·npm 스크립트 키는 산출물 경로가 아니다.
_RETIRED_PATH = re.compile(r"\.impeccable(?:/|['\"`])")


def _node(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert _NODE is not None  # 호출부는 전부 skipIf(_NODE is None) 아래에 있다
    return subprocess.run(
        [_NODE, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


@unittest.skipIf(_NODE is None, "node 부재 — 엔진2 금고 검사 생략")
class TestVaultRuntime(unittest.TestCase):
    """실제 프로젝트를 만들어 금고가 어디에 생기고 git이 뭘 보는지 확인한다."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q", "."], cwd=self.project, check=True)
        (self.project / "package.json").write_text("{}\n", encoding="utf-8")
        # `asgard init`이 하는 일: .asgard/ 와 그 자기무시 .gitignore. 엔진2는 이걸
        # 전제로만 동작하고 스스로 만들지 않는다.
        asgard = self.project / ".asgard"
        asgard.mkdir()
        (asgard / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_snapshot(self) -> Path:
        body = self.project / "body.md"
        body.write_text("critique body\n", encoding="utf-8")
        proc = _node(
            str(_SCRIPTS / "critique-storage.mjs"),
            "write",
            "home",
            str(body),
            cwd=self.project,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return Path(proc.stdout.strip())

    def test_artifacts_land_in_the_freyja_folder_under_asgard(self):
        written = self._write_snapshot()
        rel = written.relative_to(self.project.resolve()).as_posix()
        self.assertTrue(
            rel.startswith(".asgard/.vanadis/engine2/critique/"),
            f"산출물이 금고 밖에 쓰였다: {rel}",
        )
        self.assertFalse((self.project / ".impeccable").exists(), "레거시 루트가 새로 생겼다")

    def test_vault_inherits_asgard_invisibility(self):
        """금고는 이미 무시되는 `.asgard/` 안에 있다 — git이 아무것도 보지 못한다."""
        self._write_snapshot()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=True,
        )
        # `.asgard/.gitignore` 자신은 아스가르드가 커밋하는 파일이라 보여도 정상이다.
        # 금고 아래로 무엇도 새어 나오지 않는 것이 계약이다.
        seen = {line[3:] for line in status.stdout.splitlines()}
        self.assertFalse(
            [p for p in seen if p.startswith(".asgard/.vanadis")],
            f"금고가 git 에 노출됐다: {sorted(seen)}",
        )

    def test_engine_writes_no_ignore_file_of_its_own(self):
        """엔진은 ignore 파일을 만들지도 고치지도 않는다 — `.asgard/` 커버리지에 얹힌다."""
        exclude = self.project / ".git" / "info" / "exclude"
        before = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        asgard_gitignore = (self.project / ".asgard" / ".gitignore").read_text(encoding="utf-8")

        self._write_snapshot()
        proc = _node(str(_SCRIPTS / "hook-admin.mjs"), "off", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        self.assertFalse(
            (self.project / ".asgard" / ".vanadis" / "engine2" / ".gitignore").exists(),
            "금고가 자기 .gitignore 를 찍었다 — .asgard/ 만으로 충분하다",
        )
        self.assertFalse((self.project / ".gitignore").exists(), "프로젝트 .gitignore 를 새로 만들었다")
        self.assertEqual(
            asgard_gitignore,
            (self.project / ".asgard" / ".gitignore").read_text(encoding="utf-8"),
            "아스가르드 소유의 .asgard/.gitignore 를 건드렸다",
        )
        after = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        self.assertNotIn("freyja", after)
        self.assertNotIn("impeccable", after)
        self.assertEqual(before.strip(), after.strip(), ".git/info/exclude 에 항목을 남겼다")

    def test_sweep_clears_run_scoped_state_and_keeps_the_record(self):
        self._write_snapshot()
        live = self.project / ".asgard" / ".vanadis" / "engine2" / "live" / "sessions"
        live.mkdir(parents=True)
        (live / "s.jsonl").write_text("{}\n", encoding="utf-8")
        cache = self.project / ".asgard" / ".vanadis" / "engine2" / "hook.cache.json"
        cache.write_text("{}\n", encoding="utf-8")

        proc = _node(str(_SCRIPTS / "vault.mjs"), "sweep", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(live.parent.exists(), "런 한정 live 상태가 남았다")
        self.assertFalse(cache.exists(), "훅 캐시가 남았다")
        self.assertTrue(
            (self.project / ".asgard" / ".vanadis" / "engine2" / "critique").exists(),
            "sweep 이 기록(크리티크 스냅샷)까지 지웠다",
        )

    def test_purge_takes_the_vault_and_the_retired_root(self):
        self._write_snapshot()
        legacy = self.project / ".impeccable" / "critique"
        legacy.mkdir(parents=True)
        (legacy / "old.md").write_text("old\n", encoding="utf-8")

        proc = _node(str(_SCRIPTS / "vault.mjs"), "purge", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((self.project / ".asgard" / ".vanadis" / "engine2").exists())
        self.assertFalse((self.project / ".impeccable").exists())

    def test_legacy_root_is_read_but_never_written(self):
        """기존 프로젝트의 `.impeccable/config.json`은 계속 읽힌다 — 쓰기는 금고로 간다."""
        legacy = self.project / ".impeccable"
        legacy.mkdir()
        (legacy / "config.json").write_text(
            json.dumps({"detector": {"ignoreRules": ["overused-font"]}}) + "\n",
            encoding="utf-8",
        )

        proc = _node(str(_SCRIPTS / "hook-admin.mjs"), "status", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("overused-font", proc.stdout, "레거시 config 를 읽지 못했다")

        proc = _node(str(_SCRIPTS / "hook-admin.mjs"), "off", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(
            (self.project / ".asgard" / ".vanadis" / "engine2" / "config.json").exists(),
            "쓰기가 금고로 가지 않았다",
        )

    def test_doctor_fix_retires_the_legacy_root(self):
        """`doctor --fix`가 포팅의 나머지 절반이다 — 기존 프로젝트를 금고로 옮기고 옛 루트를 없앤다."""
        legacy = self.project / ".impeccable"
        (legacy / "critique").mkdir(parents=True)
        (legacy / "critique" / "old.md").write_text("old\n", encoding="utf-8")
        (legacy / "config.json").write_text("{}\n", encoding="utf-8")

        proc = _node(str(_SCRIPTS / "doctor.mjs"), "--fix", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("legacy-artifact-root", proc.stdout)

        vault = self.project / ".asgard" / ".vanadis" / "engine2"
        self.assertFalse(legacy.exists(), "옛 루트가 남았다")
        self.assertTrue((vault / "config.json").exists())
        self.assertTrue((vault / "critique" / "old.md").exists())
        self.assertFalse((vault / ".gitignore").exists(), "이관이 불필요한 ignore 파일을 남겼다")

    def test_doctor_fix_never_overwrites_a_conflicting_entry(self):
        """양쪽에 같은 이름이 있으면 승자를 말없이 고르지 않는다 — 옛 사본을 남기고 보고한다."""
        legacy = self.project / ".impeccable"
        legacy.mkdir()
        (legacy / "config.json").write_text('{"from": "legacy"}\n', encoding="utf-8")
        vault = self.project / ".asgard" / ".vanadis" / "engine2"
        vault.mkdir(parents=True)
        (vault / "config.json").write_text('{"from": "vault"}\n', encoding="utf-8")

        proc = _node(str(_SCRIPTS / "doctor.mjs"), "--fix", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("vault", json.loads((vault / "config.json").read_text())["from"])
        self.assertTrue((legacy / "config.json").exists(), "충돌 사본이 말없이 사라졌다")

    def test_critique_snapshots_stay_bounded(self):
        """스냅샷은 대상별 최근 5개만 남는다 — 판별이 반복돼도 금고가 무한히 자라지 않는다.

        파일명 타임스탬프는 초 단위라, 한 루프에서 연속으로 쓰면 같은 이름끼리 덮어써
        6개에 닿지도 못한다(샌드박스 실측). 그래서 과거 스냅샷을 직접 심어 초를 벌린 뒤
        한 번 더 쓴다 — 그래야 prune이 실제로 돈다.
        """
        critique = self.project / ".asgard" / ".vanadis" / "engine2" / "critique"
        critique.mkdir(parents=True)
        seeded = []
        for minute in range(8):
            path = critique / f"2026-07-25T10-{minute:02d}-00Z__home.md"
            path.write_text(f"---\nslug: home\n---\nrun {minute}\n", encoding="utf-8")
            seeded.append(path)

        self._write_snapshot()

        kept = sorted(critique.glob("*__home.md"))
        self.assertEqual(len(kept), 5, f"최근 5개로 정리되지 않았다: {[p.name for p in kept]}")
        # 지워진 것은 가장 오래된 쪽이어야 한다 — 최신을 지우면 trend와 polish가 깨진다.
        self.assertEqual([p.name for p in kept[:4]], [p.name for p in seeded[4:]])
        self.assertNotIn(seeded[0].name, [p.name for p in kept])

    def test_snapshots_for_other_targets_survive_a_prune(self):
        """정리는 대상별이다 — 한 화면을 반복 판별해도 다른 화면의 기록은 남는다."""
        critique = self.project / ".asgard" / ".vanadis" / "engine2" / "critique"
        critique.mkdir(parents=True)
        other = critique / "2026-07-25T09-00-00Z__checkout.md"
        other.write_text("---\nslug: checkout\n---\nkeep me\n", encoding="utf-8")
        for minute in range(8):
            (critique / f"2026-07-25T10-{minute:02d}-00Z__home.md").write_text(
                "---\nslug: home\n---\n", encoding="utf-8"
            )

        self._write_snapshot()

        self.assertTrue(other.exists(), "다른 대상의 스냅샷이 함께 지워졌다")
        self.assertEqual(len(list(critique.glob("*__home.md"))), 5)


class TestVaultSourceContract(unittest.TestCase):
    """소스 자체가 계약을 어기지 않는지 — 런타임 없이 읽어서 고정한다."""

    def test_no_script_writes_to_the_retired_root(self):
        """`.impeccable` 문자열은 레거시 읽기 폴백에만 남아 있어야 한다."""
        allowed = {
            "lib/vault.mjs",  # 폴백 목록의 정본
            "lib/vault-paths.mjs",  # 문서 주석
            "lib/vault-config.mjs",  # git exclude 패턴(구·신 동시 기재)
            "hook-lib.mjs",  # 루트 마커 + 발자국 탐지
            "vault.mjs",  # purge --legacy-only 도움말
            "doctor.mjs",  # 은퇴 루트 이관(migrateRetiredVaultRoot) 주석
            "live/source-search.mjs",  # 탐색 제외 디렉터리 이름
            "live-commit-manual-edits.mjs",  # 롤백 스킵 디렉터리 이름
            "live-manual-edit-evidence.mjs",  # 증거 수집 스킵 디렉터리 이름
            "live-inject.mjs",  # 호스트 .gitignore 블록(구 경로 동시 기재)
            "detector/design-system.mjs",  # 검출기 미러(별도 트리)
        }
        offenders: list[str] = []
        for src in sorted(_SCRIPTS.rglob("*.mjs")):
            rel = src.relative_to(_SCRIPTS).as_posix()
            if rel in allowed or "detector/browser" in rel:
                continue
            text = src.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                # 파일시스템 경로 형태만 본다. CSS 클래스(`.impeccable-overlay`)와
                # DOM dataset(`dataset.impeccableLive…`)은 산출물 경로가 아니고,
                # `.impeccable-live`는 별개의 은퇴 경로라 이 검사 대상이 아니다.
                if _RETIRED_PATH.search(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "엔진2 스크립트가 은퇴한 `.impeccable/` 경로를 아직 참조한다:\n" + "\n".join(offenders),
        )

    def test_playbooks_name_the_vault_not_the_retired_root(self):
        offenders: list[str] = []
        for doc in sorted((_ENGINE / "reference").glob("*.md")):
            for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.replace(".impeccable-live", "")
                if ".impeccable/" in stripped and "vault.mjs" not in line:
                    offenders.append(f"{doc.name}:{lineno}")
        self.assertEqual(offenders, [], f"플레이북이 옛 경로를 지시한다: {offenders}")

    def test_skill_contract_states_the_vault_and_the_cleanup(self):
        skill = (_ENGINE.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(".asgard/.vanadis/engine2/", skill)
        self.assertIn("vault.mjs sweep", skill)
        self.assertIn("vault.mjs purge", skill)

    def test_repo_gitignore_needs_no_entry_for_the_vault(self):
        """리포 .gitignore는 금고 때문에 한 줄도 늘지 않는다 — `**/.asgard/`가 이미 덮는다."""
        lines = [line.strip() for line in (_REPO / ".gitignore").read_text(encoding="utf-8").splitlines()]
        self.assertIn("**/.asgard/", lines)
        rules = [line for line in lines if line and not line.startswith("#")]
        self.assertFalse(
            [line for line in rules if "freyja" in line or "folkvangr" in line],
            "금고 전용 gitignore 항목이 생겼다",
        )

    def test_engine_plants_no_ignore_patterns(self):
        """훅·live 주입이 **금고** 경로를 ignore 파일에 심지 않는다.

        live 모드가 사용자 소스 트리 *안에* 심는 스크래치 파일(`.freyja2-live/` 등)은
        예외다 — 금고 밖이라 다른 무엇도 가려 주지 않는다. 금지 대상은 어디까지나
        `.asgard/` 아래 금고이고, Asgard가 이미 git밖에 두므로 항목이 필요 없다.
        엔진 개명 전에는 브랜드 토큰이 그 둘을 우연히 갈라 줬지만(`.impeccable-live`),
        지금은 아니다. 그래서 금고 경로 자체로 검사한다.
        """
        hook_lib = (_SCRIPTS / "hook-lib.mjs").read_text(encoding="utf-8")
        self.assertIn("HOOK_LOCAL_IGNORE_PATTERNS = Object.freeze([])", hook_lib)
        live_inject = (_SCRIPTS / "live-inject.mjs").read_text(encoding="utf-8")
        patterns = live_inject.split("LIVE_IGNORE_PATTERNS", 1)[1].split("]);", 1)[0]
        self.assertNotIn(".asgard", patterns)
        self.assertNotIn("vanadis", patterns)
        # 그리고 이 블록은 live 전용 마커 사이에만 쓰인다 — 범용 ignore 관리가 아니다.
        self.assertIn("freyja2-live-ignore-start", live_inject)
        self.assertIn("freyja2-live-ignore-end", live_inject)


if __name__ == "__main__":
    unittest.main()
