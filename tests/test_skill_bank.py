#!/usr/bin/env python3
"""skill_bank 직접 단위 검증 — 파싱 거부 규칙 + 라우팅(agent 필터·상한·순위) + usage 기록.

기존 커버리지는 test_evolution 경유 간접뿐이었다 (26-07-16 스킬 체계 조사에서 확인된 갭).
실행: uv run pytest tests/test_skill_bank.py
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import skill_bank  # noqa: E402


def _write_skill(
    root: str, name: str, *, triggers: str, agent: str = "worker", body: str = "본문", approved: bool = True
) -> None:
    d = os.path.join(root, ".asgard", "skills", name)
    os.makedirs(d, exist_ok=True)
    text = f"---\nname: {name}\ndescription: d\ntriggers: {triggers}\nagent: {agent}\n---\n\n{body}\n"
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(text)
    if approved:
        with open(os.path.join(d, skill_bank.APPROVAL_FILE), "w", encoding="utf-8") as f:
            json.dump(skill_bank.approval_receipt(root, name, text, create_key=True), f)


class TestParse(unittest.TestCase):
    def test_valid(self):
        parsed = skill_bank.parse_skill_md("---\nname: a\ntriggers: X, y\n---\n\nbody")
        assert parsed is not None  # ty 내로잉 — 실패 시 여기서 즉사
        meta, body = parsed
        self.assertEqual(meta["triggers"], ("x", "y"))  # 소문자 정규화
        self.assertEqual(meta["agent"], "worker")  # 기본 표면
        self.assertEqual(body, "body")

    def test_rejects_missing_frontmatter_or_triggers(self):
        # trigger 없는 스킬은 영원히 라우팅되지 않는다 — 등록 자체를 거부 (fail-open)
        self.assertIsNone(skill_bank.parse_skill_md("no frontmatter"))
        self.assertIsNone(skill_bank.parse_skill_md("---\nname: a\n---\nbody"))
        self.assertIsNone(skill_bank.parse_skill_md("---\ntriggers: x\n---\nbody"))


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(self.root, "home")
        skill_bank._cache.clear()

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.tmp.cleanup()
        skill_bank._cache.clear()

    def test_agent_filter(self):
        _write_skill(self.root, "w-skill", triggers="배치", agent="worker")
        _write_skill(self.root, "t-skill", triggers="배치", agent="thor")
        _write_skill(self.root, "any-skill", triggers="배치", agent="any")
        names = [n for n, _ in skill_bank.resolve_learned(self.root, "배치 작업", "worker")]
        self.assertIn("w-skill", names)
        self.assertIn("any-skill", names)
        self.assertNotIn("t-skill", names)

    def test_unsigned_project_skill_is_not_routed(self):
        _write_skill(self.root, "unsigned", triggers="배치", approved=False)
        self.assertEqual(skill_bank.resolve_learned(self.root, "배치", "worker"), [])

    def test_repository_forged_sha_only_receipt_is_not_routed(self):
        _write_skill(self.root, "forged", triggers="배치", approved=False)
        skill = os.path.join(self.root, ".asgard", "skills", "forged", "SKILL.md")
        text = open(skill, encoding="utf-8").read()
        receipt = os.path.join(os.path.dirname(skill), skill_bank.APPROVAL_FILE)
        with open(receipt, "w", encoding="utf-8") as handle:
            json.dump({"sha256": hashlib.sha256(text.encode()).hexdigest()}, handle)
        self.assertEqual(skill_bank.resolve_learned(self.root, "배치", "worker"), [])

    def test_approval_receipt_is_bound_to_canonical_project(self):
        import shutil

        _write_skill(self.root, "bound", triggers="배치")
        other = os.path.join(self.root, "other-project")
        source = os.path.join(self.root, ".asgard", "skills", "bound")
        target = os.path.join(other, ".asgard", "skills", "bound")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copytree(source, target)
        skill_bank._cache.clear()
        self.assertEqual(skill_bank.resolve_learned(other, "배치", "worker"), [])

    def test_cap_and_ranking(self):
        # 상한 _CAP=2 — 히트 수 많은 순 (과주입 = 노이즈)
        _write_skill(self.root, "one-hit", triggers="배치")
        _write_skill(self.root, "two-hit", triggers="배치, 마이그레이션")
        _write_skill(self.root, "also-one", triggers="마이그레이션")
        got = [n for n, _ in skill_bank.resolve_learned(self.root, "배치 마이그레이션", "worker")]
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0], "two-hit")

    def test_no_match_empty(self):
        _write_skill(self.root, "w-skill", triggers="배치")
        self.assertEqual(skill_bank.resolve_learned(self.root, "오탈자 수정", "worker"), [])

    def test_hidden_archive_excluded(self):
        _write_skill(self.root, ".archive", triggers="배치")  # 보관 = 라우팅 제외
        self.assertEqual(skill_bank.resolve_learned(self.root, "배치", "worker"), [])

    def test_mtime_cache_detects_new_skill(self):
        _write_skill(self.root, "first", triggers="배치")
        self.assertEqual(len(skill_bank.learned_skills(self.root)), 1)
        _write_skill(self.root, "second", triggers="배치")  # 재시작 없이 다음 스캔에 반영
        self.assertEqual(len(skill_bank.learned_skills(self.root)), 2)


class TestUsage(unittest.TestCase):
    def test_record_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            skill_bank.record_use(root, ["a", "b"])
            skill_bank.record_use(root, ["a"])
            u = skill_bank.usage(root)
            self.assertEqual(u["a"]["uses"], 2)
            self.assertEqual(u["b"]["uses"], 1)
            self.assertIn("last_used", u["a"])  # 큐레이션(노화 판정)의 원료

    def test_record_failure_harmless(self):
        skill_bank.record_use("/nonexistent-root-zzz", ["a"])  # 실패 무해 (fail-open)

    def test_usage_tolerates_corrupt_file(self):
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, ".asgard", "state")
            os.makedirs(d)
            with open(os.path.join(d, skill_bank.USAGE_FILE), "w", encoding="utf-8") as f:
                f.write("not json")
            self.assertEqual(skill_bank.usage(root), {})
            skill_bank.record_use(root, ["a"])  # 손상 파일은 새로 시작
            self.assertEqual(skill_bank.usage(root)["a"]["uses"], 1)


class TestBundledCollisionGuard(unittest.TestCase):
    def test_learned_cannot_shadow_bundled_names(self):
        # evolution.approve 가 이 레지스트리로 충돌을 거부한다 — 번들 전 종목이 등록돼 있어야 한다
        from asgard.evolution import _bundled_names

        names = _bundled_names()
        for expected in (
            "asgard-freyja-brisingamen",
            "asgard-freyja-hildisvini",
            "asgard-thor-mjollnir",
            "asgard-eitri-draupnir",
            "asgard-eitri-gullinbursti",
            "asgard-worker-debugging",
            "asgard-worker-testing",
        ):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
