"""개인 메모리 백업·서버 연동 테스트.

검증 축: 백업(정본만 담김·manifest 다이제스트·손상 거절·경로 탈출 거절·보존 개수) /
복원(정본 교체·파생 재생성·직전 상태 자동 보관) / dir 동기화(3-way 판정·삭제 전파·
로그 union·충돌 시 로컬 보존과 재판정) / git 동기화(파생 제외·원격 반영). 전부 temp HOME 격리.
"""

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from asgard import memory
from asgard.memory import backup as mb
from asgard.memory import sync as ms


class MemoryHomeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-memsync-")
        self._home, self._mem = os.environ.get("HOME"), os.environ.get(memory.MEMORY_ENV)
        os.environ["HOME"] = self.tmp
        self.d = os.path.join(self.tmp, "memory")
        os.environ[memory.MEMORY_ENV] = self.d
        memory.ensure_home(self.d)

    def tearDown(self):
        for key, value in (("HOME", self._home), (memory.MEMORY_ENV, self._mem)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, text: str, title: str) -> str:
        slug, _ = memory.add(text, title=title, d=self.d)
        return slug


class BackupTest(MemoryHomeBase):
    def test_archive_carries_canonical_only(self):
        self._add("첫 사실은 백업에 담긴다", "first")
        summary = mb.create(self.d)
        manifest, payload = mb.read_archive(summary["path"])
        self.assertEqual(manifest["pages"], 1)
        self.assertIn("pages/first.md", payload)
        self.assertIn("SCHEMA.md", payload)
        # 파생물은 담기지 않는다 — 복원본이 남의 시점 인덱스를 들고 살아나는 경로 차단
        self.assertNotIn("index.md", payload)
        self.assertFalse(any(name.startswith("state.db") for name in payload))

    def test_tampered_member_is_rejected(self):
        self._add("무결성 검사 대상", "probe")
        path = mb.create(self.d)["path"]
        with tarfile.open(path, "r:gz") as archive:
            members = {}
            for info in archive:
                handle = archive.extractfile(info) if info.isfile() else None
                if handle is not None:
                    members[info.name] = handle.read()
        members["pages/probe.md"] = "---\ntitle: swapped\n---\n\n조작된 본문\n".encode()
        with tarfile.open(path, "w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        with self.assertRaises(mb.BackupError):
            mb.read_archive(path)

    def test_traversal_member_is_rejected(self):
        path = os.path.join(self.d, "evil.tar.gz")
        with tarfile.open(path, "w:gz") as archive:
            blob = json.dumps({"schema": 1, "files": {"../../escape.md": "0" * 64}}).encode()
            for name, data in ((mb.MANIFEST_NAME, blob), ("../../escape.md", b"x")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        with self.assertRaises(mb.BackupError):
            mb.read_archive(path)

    def test_restore_replaces_canonical_and_rebuilds_derived(self):
        self._add("복원 뒤에도 남아야 하는 사실", "keeper")
        created = mb.create(self.d)
        os.remove(os.path.join(self.d, memory.PAGES, "keeper.md"))
        self._add("복원으로 사라져야 하는 사실", "later")
        result = mb.restore(created["name"], self.d)
        pages = set(memory._pages(self.d))
        self.assertEqual(pages, {"keeper"})
        self.assertEqual(result["pages"], 1)
        # 되돌릴 수 있어야 한다 — 복원 직전 상태가 자동으로 보관된다
        names = [row["name"] for row in mb.listing(self.d)]
        self.assertIn(result["safety_backup"], names)
        restored_safety = mb.read_archive(os.path.join(self.d, mb.BACKUPS_DIR, result["safety_backup"]))[1]
        self.assertIn("pages/later.md", restored_safety)
        # 파생은 백업에 없으므로 정본에서 다시 만들어진다 — 삭제된 페이지는 색인에서도 사라진다
        hits = {hit["slug"] for hit in memory.query("사실", d=self.d)}
        self.assertIn("keeper", hits)
        self.assertNotIn("later", hits)

    def test_restore_never_prunes_away_the_archive_it_is_restoring(self):
        # 보존 한도에 걸린 복원이 자기 원본을 지우면, 두 번째 복원이 불가능해진다
        self._add("보존 한도 경계", "edge")
        oldest = mb.create(self.d, label="oldest", keep=99)
        for index in range(mb.KEEP_DEFAULT + 2):
            mb.create(self.d, label=f"f{index}", keep=99)
        mb.restore(oldest["name"], self.d)
        self.assertTrue(os.path.isfile(oldest["path"]))
        self.assertEqual(mb.restore(oldest["name"], self.d)["restored"], oldest["name"])

    def test_prune_keeps_newest(self):
        self._add("보존 개수 검증", "retention")
        for index in range(4):
            mb.create(self.d, label=f"r{index}", keep=99)
        removed = mb.prune(self.d, keep=2)
        self.assertEqual(len(removed), 2)
        self.assertEqual(len(mb.listing(self.d)), 2)


class DirSyncTest(MemoryHomeBase):
    def setUp(self):
        super().setUp()
        self.remote = os.path.join(self.tmp, "remote")

    def test_first_sync_pushes_and_marks_the_remote(self):
        self._add("원격으로 올라갈 사실", "outbound")
        result = ms.sync_dir(self.d, self.remote)
        self.assertIn("pages/outbound.md", result["push"])
        self.assertTrue(os.path.isfile(os.path.join(self.remote, "pages", "outbound.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.remote, ms.MARKER_NAME)))
        self.assertTrue(result["remote_id"])

    def test_unmarked_nonempty_remote_needs_adopt(self):
        os.makedirs(self.remote, exist_ok=True)
        with open(os.path.join(self.remote, "someone-elses.txt"), "w", encoding="utf-8") as handle:
            handle.write("남의 폴더")
        with self.assertRaises(ms.SyncError):
            ms.sync_dir(self.d, self.remote)
        self.assertIn("push", ms.sync_dir(self.d, self.remote, adopt=True))

    def test_remote_side_creation_is_pulled_and_indexed(self):
        self._add("로컬 사실", "local-one")
        ms.sync_dir(self.d, self.remote)
        with open(os.path.join(self.remote, "pages", "inbound.md"), "w", encoding="utf-8") as handle:
            handle.write("---\ntitle: inbound\nkind: note\n---\n\n다른 기계가 쓴 문장\n")
        result = ms.sync_dir(self.d, self.remote)
        self.assertIn("pages/inbound.md", result["pull"])
        self.assertIn("inbound", memory._pages(self.d))
        self.assertTrue(any(hit["slug"] == "inbound" for hit in memory.query("다른 기계", d=self.d)))

    def test_deletion_propagates_only_from_the_side_that_changed(self):
        self._add("지워질 사실", "doomed")
        ms.sync_dir(self.d, self.remote)
        os.remove(os.path.join(self.remote, "pages", "doomed.md"))
        result = ms.sync_dir(self.d, self.remote)
        self.assertIn("pages/doomed.md", result["delete_local"])
        self.assertNotIn("doomed", memory._pages(self.d))

    def test_divergent_edit_keeps_local_and_stays_flagged(self):
        self._add("양쪽이 고칠 사실", "contested")
        ms.sync_dir(self.d, self.remote)
        local_path = os.path.join(self.d, memory.PAGES, "contested.md")
        remote_path = os.path.join(self.remote, "pages", "contested.md")
        for path, suffix in ((local_path, "\n로컬 판단\n"), (remote_path, "\n원격 판단\n")):
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(suffix)
        result = ms.sync_dir(self.d, self.remote)
        self.assertEqual(result["conflict"], ["pages/contested.md"])
        with open(local_path, encoding="utf-8") as handle:
            self.assertIn("로컬 판단", handle.read())
        stashed = os.path.join(self.d, ms.CONFLICTS_DIR, *result["conflict_copies"][0].split(os.sep)[1:])
        self.assertTrue(os.path.isfile(os.path.join(self.d, result["conflict_copies"][0])), stashed)
        # 사람이 풀 때까지 판정이 유지된다 — 기준선에 흡수되어 조용히 사라지지 않는다
        self.assertEqual(ms.sync_dir(self.d, self.remote)["conflict"], ["pages/contested.md"])

    def test_append_only_log_merges_instead_of_conflicting(self):
        self._add("로그가 쌓일 사실", "logged")
        ms.sync_dir(self.d, self.remote)
        remote_log = os.path.join(self.remote, memory.LOG)
        with open(remote_log, "a", encoding="utf-8") as handle:
            handle.write("- 2026-07-27T01:00Z [add] remote-only\n")
        with open(os.path.join(self.d, memory.LOG), "a", encoding="utf-8") as handle:
            handle.write("- 2026-07-27T02:00Z [add] local-only\n")
        result = ms.sync_dir(self.d, self.remote)
        self.assertEqual(result["conflict"], [])
        self.assertIn(memory.LOG, result["merge"])
        with open(os.path.join(self.d, memory.LOG), encoding="utf-8") as handle:
            merged = handle.read()
        self.assertIn("remote-only", merged)
        self.assertIn("local-only", merged)

    def test_merge_log_is_ordered_and_deduplicated(self):
        merged = ms.merge_log(
            "# Memory Log\n- 2026-07-27T02:00Z [add] b\n- 2026-07-27T01:00Z [add] a\n",
            "# Memory Log\n- 2026-07-27T01:00Z [add] a\n- 2026-07-27T03:00Z [add] c\n",
        )
        lines = [line for line in merged.splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines, sorted(lines))


class GitSyncTest(MemoryHomeBase):
    def setUp(self):
        super().setUp()
        if shutil.which("git") is None:  # pragma: no cover - git 없는 환경
            self.skipTest("git is not installed")
        self.bare = os.path.join(self.tmp, "bare.git")
        subprocess.run(["git", "init", "--bare", "-q", self.bare], check=True)

    def test_push_carries_canonical_only(self):
        self._add("git 원격으로 갈 사실", "gitbound")
        result = ms.sync_git(self.d, self.bare, branch="main")
        self.assertTrue(result["pushed"], result.get("detail", ""))
        listed = subprocess.run(
            ["git", "-C", self.bare, "ls-tree", "-r", "--name-only", "main"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertIn("pages/gitbound.md", listed)
        self.assertNotIn("index.md", listed)
        self.assertNotIn("state.db", listed)
        self.assertNotIn("sync-state.json", listed)


class SettingsTest(MemoryHomeBase):
    def test_transport_is_validated_and_round_trips(self):
        with self.assertRaises(ms.SyncError):
            ms.save_settings("/tmp/x", transport="ftp")
        saved = ms.save_settings(os.path.join(self.tmp, "vault"), transport="dir")
        self.assertEqual(ms.settings()["remote"], saved["remote"])
        ms.clear_settings()
        self.assertEqual(ms.settings(), {})

    def test_sync_without_remote_is_a_clear_error(self):
        ms.clear_settings()
        with self.assertRaises(ms.SyncError):
            ms.sync(self.d)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
