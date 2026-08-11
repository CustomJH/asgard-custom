#!/usr/bin/env python3
"""선언된 짝 저장소의 코드 지도 — 세션 저장소 안에 그리고, 짝 저장소에는 쓰지 않는다."""

import json
import os
import tempfile
import unittest


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # macOS 의 /tmp 는 심링크라 안 펴면 설정이 적은 절대 경로와 해석된 경로가 갈린다.
        self.home = os.path.realpath(self.tmp.name)
        self.root = os.path.join(self.home, "control")
        self.peer = os.path.join(self.home, "product")
        for path in (self.root, self.peer):
            os.makedirs(os.path.join(path, ".asgard", "map"), exist_ok=True)
        self.write(self.root, "README.md", "# control\n")
        self.write(self.peer, "package.json", json.dumps({"name": "product", "scripts": {"test": "vitest"}}))
        self.write(self.peer, "src/widgets/co2.ts", "export function renderCo2(total: number) {\n  return total\n}\n")
        self.write(self.peer, "docs/GUIDE.md", "# Product guide\n\n## Widgets\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, root: str, rel: str, body: str = "") -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(body)

    def declare(self, *entries: str) -> None:
        setting = os.path.join(self.root, ".asgard", "asgard-setting-project.json")
        with open(setting, "w", encoding="utf-8") as stream:
            json.dump({"paths": {"additional_roots": list(entries)}}, stream)

    def peer_map_path(self, name: str = "PEER-product.md") -> str:
        return os.path.join(self.root, ".asgard", "map", name)

    def read(self, path: str) -> str:
        with open(path, encoding="utf-8") as stream:
            return stream.read()


class TestPeerMapWriting(Base):
    def test_declared_peer_is_drawn_into_the_session_repository(self):
        from asgard.code_map import refresh_map

        self.declare("../product")
        result = refresh_map(self.root)

        self.assertIn("PEER-product.md", result.peers_written)
        body = self.read(self.peer_map_path())
        self.assertIn("- `../product/src/widgets/co2.ts` — ", body)
        self.assertIn("- `../product/docs/GUIDE.md` — ", body)

    def test_nothing_is_written_inside_the_peer_repository(self):
        from asgard.code_map import refresh_map

        self.declare("../product")
        before = sorted(os.listdir(os.path.join(self.peer, ".asgard")))
        refresh_map(self.root)

        self.assertEqual(before, sorted(os.listdir(os.path.join(self.peer, ".asgard"))))
        self.assertEqual([], os.listdir(os.path.join(self.peer, ".asgard", "map")))

    def test_peer_map_carries_no_verification_command(self):
        """검증 명령은 그 저장소에서 돌아야 한다 — 세션 뿌리 지도에 넣으면 못 도는 명령을 권한다."""
        from asgard.code_map import refresh_map

        self.declare("../product")
        refresh_map(self.root)

        self.assertNotIn("## Detected verification", self.read(self.peer_map_path()))
        self.assertNotIn("- Command: `", self.read(self.peer_map_path()))

    def test_undeclared_peer_map_is_removed_on_refresh(self):
        from asgard.code_map import refresh_map

        self.declare("../product")
        refresh_map(self.root)
        self.declare()
        result = refresh_map(self.root)

        self.assertIn("PEER-product.md", result.peers_written)
        self.assertFalse(os.path.exists(self.peer_map_path()))

    def test_hand_written_file_with_the_peer_name_survives(self):
        from asgard.code_map import refresh_map

        self.write(self.root, ".asgard/map/PEER-product.md", "# map: mine\n\n- `README.md` — hand written\n")
        self.declare()
        refresh_map(self.root)

        self.assertIn("hand written", self.read(self.peer_map_path()))

    def test_declared_peer_never_overwrites_a_hand_written_file(self):
        """PROJECT.md 와 같은 소유 규칙 — 사람이 쓴 지도는 이름이 겹쳐도 우리가 안 덮는다."""
        from asgard.code_map import MapOwnershipError, refresh_map

        self.write(self.root, ".asgard/map/PEER-product.md", "# map: mine\n\n- `README.md` — hand written\n")
        self.declare("../product")

        with self.assertRaises(MapOwnershipError):
            refresh_map(self.root)
        self.assertIn("hand written", self.read(self.peer_map_path()))

    def test_untouched_peer_is_not_redrawn(self):
        """판정마다 짝을 통째로 다시 그리면 턴마다 값이 붙는다 — 스탯 지문이 같으면 건너뛴다."""
        from asgard.code_map import refresh_map

        self.declare("../product")
        refresh_map(self.root)
        stamped = os.stat(self.peer_map_path()).st_mtime_ns
        result = refresh_map(self.root)

        self.assertEqual((), result.peers_written)
        self.assertEqual(stamped, os.stat(self.peer_map_path()).st_mtime_ns)

    def test_missing_declaration_leaves_the_map_directory_alone(self):
        from asgard.code_map import refresh_map

        result = refresh_map(self.root)

        self.assertEqual((), result.peers_written)
        self.assertEqual(["INDEX.md", "PROJECT.md"], sorted(os.listdir(os.path.join(self.root, ".asgard", "map"))))


class TestPeerMapDrift(Base):
    def test_check_reports_peer_drift_until_refreshed(self):
        from asgard.code_map import check_map, refresh_map

        self.declare("../product")
        refresh_map(self.root)
        self.assertTrue(check_map(self.root).ok)

        self.write(self.peer, "src/widgets/chart.ts", "export const chart = 1\n")
        drifted = check_map(self.root)
        self.assertFalse(drifted.ok)
        self.assertEqual(("PEER-product.md",), drifted.peer_drift)

        refresh_map(self.root)
        self.assertTrue(check_map(self.root).ok)


class TestPeerMapInjection(Base):
    def test_peer_entries_reach_the_injected_slice(self):
        from asgard.code_map import refresh_map
        from asgard.map_context import build_map_context

        self.declare("../product")
        refresh_map(self.root)
        context = build_map_context(self.root, "co2 widget")

        paths = [entry.path for entry in context.entries]
        self.assertIn("../product/src/widgets/co2.ts", paths)
        self.assertIn("../product/src/widgets/co2.ts", context.text)

    def test_peer_map_is_not_judged_as_an_area_map(self):
        """우리가 그린 파일이라 사람이 쓰는 영역 지도 문법으로 재면 매번 위반이 뜬다."""
        from asgard.code_map import refresh_map
        from asgard.map_context import validate_area_maps

        self.declare("../product")
        refresh_map(self.root)
        _, issues = validate_area_maps(self.root)

        self.assertEqual((), issues)

    def test_undeclared_parent_path_is_still_refused(self):
        from asgard.map_context import _peer_bases, _safe_path

        self.write(self.home, "secret.txt", "x")
        bases = _peer_bases(__import__("pathlib").Path(self.root))

        self.assertFalse(_safe_path(bases, "../secret.txt"))

    def test_declared_peer_path_is_allowed(self):
        from pathlib import Path

        from asgard.map_context import _peer_bases, _safe_path

        self.declare("../product")
        bases = _peer_bases(Path(self.root))

        self.assertTrue(_safe_path(bases, "../product/src/widgets/co2.ts"))
        self.assertFalse(_safe_path(bases, "../product/src/widgets/gone.ts"))


class TestPeerMapDoctor(Base):
    def test_doctor_does_not_read_the_peer_map_as_a_manual_area(self):
        """뿌리 밖을 가리키는 것이 정상인 파일이라, 안 빼면 선언 한 번에 진단이 빨갛게 고정된다."""
        from asgard.code_map import refresh_map
        from asgard.commands.doctor.codemap import _codebase_map_check

        self.declare("../product")
        refresh_map(self.root)
        row = _codebase_map_check(self.root)[0]

        self.assertTrue(row["ok"], row["detail"])

    def test_doctor_names_the_peer_when_the_work_root_moved_on(self):
        from asgard.code_map import refresh_map
        from asgard.commands.doctor.codemap import _codebase_map_check

        self.declare("../product")
        refresh_map(self.root)
        self.write(self.peer, "src/widgets/chart.ts", "export const chart = 1\n")
        row = _codebase_map_check(self.root)[0]

        self.assertFalse(row["ok"])
        self.assertIn("PEER-product.md", row["detail"])

    def test_manual_area_map_may_point_into_a_declared_peer(self):
        """주입면과 진단이 같은 뿌리 집합을 봐야 한다 — 갈리면 한쪽만 위험이라고 답한다."""
        from asgard.commands.doctor.codemap import _entry_kind

        self.declare("../product")

        self.assertEqual("ok", _entry_kind(self.root, "../product/src/widgets/co2.ts"))
        self.assertEqual("unsafe", _entry_kind(self.root, "../product/../secret"))


class TestPeerFileBudget(Base):
    def test_budget_keeps_every_top_level_tree(self):
        """상한에 걸려도 서비스 하나가 통째로 사라지지 않는다 — 정렬순으로 자르면 그렇게 된다."""
        from pathlib import Path

        from asgard.code_map import _budget_files

        files = [Path(f"helios-{name}/src/file{index}.ts") for name in ("batch", "be", "fe") for index in range(50)]
        kept, omitted = _budget_files(files, 30)

        self.assertEqual(30, len(kept))
        self.assertEqual(120, omitted)
        self.assertEqual({"helios-batch", "helios-be", "helios-fe"}, {path.parts[0] for path in kept})


class TestPeerMapCommand(Base):
    def test_map_update_from_the_control_repository_draws_the_peer(self):
        """CLI 진입점까지 — `_project_root` 는 cwd 의 git 최상위를 뿌리로 잡는다."""
        import subprocess

        from asgard import ui
        from asgard.commands.map import run_map_update

        for path in (self.root, self.peer):
            subprocess.run(["git", "init", "-q", path], check=True, capture_output=True)
        self.declare("../product")
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            code = run_map_update(quiet=True)
        finally:
            os.chdir(cwd)
            ui.set_quiet(False)

        self.assertEqual(0, code)
        self.assertIn("- `../product/src/widgets/co2.ts` — ", self.read(self.peer_map_path()))


class TestPeerMapNaming(Base):
    def test_labels_that_collapse_to_one_name_are_separated(self):
        from asgard.code_map import peer_map_names

        names = peer_map_names(["../a/b", "../a-b"])

        self.assertEqual(2, len(set(names.values())))
        self.assertTrue(all(name.startswith("PEER-") for name in names.values()))


if __name__ == "__main__":
    unittest.main()
