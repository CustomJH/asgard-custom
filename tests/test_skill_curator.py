"""skill_curator — learned 스킬 수명주기 결정론 전이 테스트.

검증 축: 출처 게이팅(학습 계열 origin만) / pinned 면제 / 유예 플로어(미사용 = created 앵커)
/ stale 30d·archive 90d 판정 / --apply 보관 전이(복원 가능) / usage가 앵커를 갱신.
"""

import datetime as _dt
import json
import os
import shutil
import tempfile
import unittest

from asgard.skill_curator import ARCHIVE_DAYS, STALE_DAYS, curate


def _write_skill(
    root: str, name: str, *, origin: str = "retrospective", created_days_ago: int = 0, pinned: bool = False
):
    d = os.path.join(root, ".asgard", "skills", name)
    os.makedirs(d, exist_ok=True)
    created = (_dt.date.today() - _dt.timedelta(days=created_days_ago)).isoformat()
    lines = [
        "---",
        f"name: {name}",
        "description: test skill",
        "triggers: 테스트, trigger",
        "agent: worker",
        f"origin: {origin}" if origin else "",
        f"created: {created}",
        "pinned: true" if pinned else "",
        "---",
        "",
        "본문",
    ]
    open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8").write("\n".join(ln for ln in lines if ln != "") + "\n")


def _record_usage(root: str, name: str, days_ago: int):
    d = os.path.join(root, ".asgard", "state")
    os.makedirs(d, exist_ok=True)
    ts = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump({name: {"uses": 3, "last_used": ts}}, open(os.path.join(d, "skill-usage.json"), "w", encoding="utf-8"))


class CuratorBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="asgard-curator-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _state(self, result: dict, name: str) -> str:
        return next(f["state"] for f in result["findings"] if f["name"] == name)


class TestLifecycle(CuratorBase):
    def test_empty_bank_no_findings(self):
        self.assertEqual(curate(self.root), {"findings": [], "archived": []})

    def test_fresh_skill_active(self):
        _write_skill(self.root, "learned-fresh", created_days_ago=1)
        self.assertEqual(self._state(curate(self.root), "learned-fresh"), "active")

    def test_stale_and_archive_thresholds(self):
        _write_skill(self.root, "learned-stale", created_days_ago=STALE_DAYS + 5)
        _write_skill(self.root, "learned-old", created_days_ago=ARCHIVE_DAYS + 5)
        result = curate(self.root)
        self.assertEqual(self._state(result, "learned-stale"), "stale")
        self.assertEqual(self._state(result, "learned-old"), "archive-candidate")

    def test_recent_usage_resets_anchor(self):
        _write_skill(self.root, "learned-used", created_days_ago=ARCHIVE_DAYS + 30)
        _record_usage(self.root, "learned-used", days_ago=3)
        self.assertEqual(self._state(curate(self.root), "learned-used"), "active")

    def test_manual_origin_skipped(self):
        _write_skill(self.root, "hand-made", origin="", created_days_ago=200)
        self.assertEqual(self._state(curate(self.root), "hand-made"), "skipped-origin")

    def test_pinned_exempt_from_all_transitions(self):
        _write_skill(self.root, "learned-pinned", created_days_ago=ARCHIVE_DAYS + 100, pinned=True)
        result = curate(self.root, apply=True)
        self.assertEqual(self._state(result, "learned-pinned"), "exempt-pinned")
        self.assertEqual(result["archived"], [])

    def test_apply_archives_only_candidates_and_is_reversible(self):
        _write_skill(self.root, "learned-old", created_days_ago=ARCHIVE_DAYS + 5)
        _write_skill(self.root, "learned-fresh", created_days_ago=1)
        result = curate(self.root, apply=True)
        self.assertEqual(result["archived"], ["learned-old"])
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".asgard", "skills", "learned-old")))
        archive = os.path.join(self.root, ".asgard", "skills", ".archive")
        self.assertTrue(any(n.startswith("learned-old-") for n in os.listdir(archive)))
        from asgard.evolution import restore_skill

        ok, _ = restore_skill(self.root, "learned-old")
        self.assertTrue(ok)

    def test_dry_run_never_mutates(self):
        _write_skill(self.root, "learned-old", created_days_ago=ARCHIVE_DAYS + 5)
        result = curate(self.root, apply=False)
        self.assertEqual(result["archived"], [])
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".asgard", "skills", "learned-old")))


class TestWake(CuratorBase):
    """턴 끝에서 부르는 손 — 26-08-12 이전에는 `curate` 의 호출자가 CLI 하나뿐이라, 아무도
    치지 않는 저장소에서 학습 스킬은 영영 늙지 않았다."""

    def _skill_dir(self, name: str) -> str:
        return os.path.join(self.root, ".asgard", "skills", name)

    def _wake(self, grade: str) -> str | None:
        from unittest import mock

        from asgard.evolution import AUTONOMY_ENV
        from asgard.skill_curator import wake

        with mock.patch.dict(os.environ, {AUTONOMY_ENV: grade}):
            return wake(self.root)

    def test_silent_when_nothing_has_aged(self):
        _write_skill(self.root, "learned-fresh", created_days_ago=1)
        self.assertIsNone(self._wake("safe"))

    def test_an_idle_skill_is_put_away_and_the_line_names_the_way_back(self):
        _write_skill(self.root, "learned-old", created_days_ago=ARCHIVE_DAYS + 5)
        line = self._wake("safe")
        assert line is not None
        self.assertIn("learned-old", line)
        self.assertIn("restore", line)
        self.assertFalse(os.path.isdir(self._skill_dir("learned-old")))

    def test_off_reports_instead_of_touching(self):
        _write_skill(self.root, "learned-old", created_days_ago=ARCHIVE_DAYS + 5)
        line = self._wake("off")
        assert line is not None
        self.assertIn("curate", line)  # 사람이 칠 명령을 말한다
        self.assertTrue(os.path.isdir(self._skill_dir("learned-old")))

    def test_the_same_report_is_not_repeated(self):
        _write_skill(self.root, "learned-stale", created_days_ago=STALE_DAYS + 2)
        self.assertIsNotNone(self._wake("off"))
        self.assertIsNone(self._wake("off"))  # 같은 집합 재발화 금지
        _write_skill(self.root, "learned-stale2", created_days_ago=STALE_DAYS + 3)
        self.assertIsNotNone(self._wake("off"))  # 집합이 바뀌면 다시 한 번

    def test_a_hand_installed_skill_is_never_put_away(self):
        _write_skill(self.root, "manual-old", origin="manual", created_days_ago=ARCHIVE_DAYS + 30)
        self.assertIsNone(self._wake("full"))
        self.assertTrue(os.path.isdir(self._skill_dir("manual-old")))


if __name__ == "__main__":
    unittest.main()
