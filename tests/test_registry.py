"""등록부 자가 치유 — 훅이 남긴 흔적을 sync 가 흡수한다.

왜 이 스위트가 있는가. `asgard sync` 는 `~/.asgard/projects.json` 에 이름이 오른 프로젝트만
고친다. 그 파일에 이름이 오르는 길이 `asgard init` 과 "그 폴더에 서서 sync" 둘뿐이라, clone 해
온 저장소나 `~/.asgard` 를 잃은 기계의 프로젝트는 업그레이드가 아무리 돌아도 옛 코어인 채로
남았다. 게다가 sync 는 등록된 것만 세어 "all projects on the latest core" 로 끝나므로 그 상태가
화면에서 초록으로 보인다 — 안 고쳐진 것과 고칠 게 없는 것이 같은 줄을 낸다.

여기서 재는 것은 흔적 하나가 아니라 그 두 가지가 갈라져 있다는 불변식이다: 훅은 경로만 남기고,
등록할 만한지는 sync 가 정한다. 판단이 두 벌로 갈라지면 한쪽만 고쳐진 채 남는다.
"""

import os
import tempfile
import unittest
from unittest import mock

from asgard import registry
from asgard.commands import sync
from asgard.hooks.asgard_hooklib import seen


class _Home(unittest.TestCase):
    """`~` 를 임시 폴더로 돌린 채 도는 시험 — 진짜 등록부를 건드리지 않는다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        patch = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def project(self, name: str, host: str = ".claude") -> str:
        root = os.path.join(self.home, name)
        os.makedirs(os.path.join(root, host), exist_ok=True)
        return root


class TestSeen(_Home):
    def test_note_is_idempotent(self):
        """같은 뿌리를 여러 번 남겨도 흔적은 하나다 — 훅은 세션마다 이 길을 지난다."""
        root = self.project("alpha")
        for _ in range(3):
            seen.note(root)
        self.assertEqual(seen.roots(), [os.path.realpath(root)])

    def test_note_survives_an_unwritable_home(self):
        """흔적을 못 남겨도 예외가 훅으로 새지 않는다 — 계측이 판단을 막으면 안 된다."""
        with mock.patch("asgard.hooks.asgard_hooklib.seen._dir", side_effect=OSError("nope")):
            seen.note(self.project("beta"))  # 던지면 실패

    def test_note_does_not_decide_membership(self):
        """훅은 프로젝트인지 아닌지를 안 가린다 — 배선 디렉토리가 없어도 흔적은 남는다.

        가리는 자리가 훅에도 있으면 판단이 두 벌이 된다. 거르는 것은 sync 의 몫이고,
        아래 TestAbsorb 가 그 거름망을 잰다."""
        bare = os.path.join(self.home, "not-a-project")
        os.makedirs(bare, exist_ok=True)
        seen.note(bare)
        self.assertEqual(seen.roots(), [os.path.realpath(bare)])


class TestAbsorb(_Home):
    def test_a_project_opened_but_never_init_ed_becomes_known(self):
        """이 스위트가 있는 이유 그 자체 — 세션이 열린 적 있는 프로젝트는 목록에 오른다."""
        root = self.project("cloned-from-a-teammate")
        seen.note(root)
        self.assertEqual(registry.load(), [])

        sync._absorb_seen()

        self.assertEqual([p["root"] for p in registry.load()], [os.path.realpath(root)])

    def test_absorption_reads_the_host_profile_from_disk(self):
        """어느 호스트로 깔렸는지는 폴더가 말한다 — 흔적은 경로만 들고 있다."""
        seen.note(self.project("codex-only", host=".codex"))
        sync._absorb_seen()
        entry = registry.load()[0]
        self.assertEqual((entry["cc"], entry["cursor"], entry["codex"]), (False, False, True))

    def test_a_folder_without_host_wiring_is_not_absorbed(self):
        """배선이 없으면 Asgard 프로젝트가 아니다 — 흔적만으로 목록에 올리지 않는다."""
        bare = os.path.join(self.home, "bare")
        os.makedirs(bare, exist_ok=True)
        seen.note(bare)
        sync._absorb_seen()
        self.assertEqual(registry.load(), [])
        self.assertEqual(seen.roots(), [], "판정이 끝난 흔적은 남지 않는다")

    def test_a_vanished_folder_is_dropped(self):
        """폴더가 사라졌으면 흔적도 간다 — 지운 프로젝트가 목록을 영영 어지럽히지 않는다."""
        root = self.project("temporary")
        seen.note(root)
        os.rmdir(os.path.join(root, ".claude"))
        os.rmdir(root)
        sync._absorb_seen()
        self.assertEqual(registry.load(), [])
        self.assertEqual(seen.roots(), [])

    def test_absorption_does_not_duplicate_a_known_project(self):
        """이미 등록된 프로젝트는 그대로 두고 흔적만 치운다."""
        root = self.project("already-known")
        registry.record(root, True, False, False)
        seen.note(root)
        sync._absorb_seen()
        self.assertEqual(len(registry.load()), 1)
        self.assertEqual(seen.roots(), [])

    def test_absorption_keeps_every_seen_project(self):
        """흡수는 하나가 아니라 전부다 — 사용자가 프로젝트마다 찾아다니지 않게 하는 것이 요점이다."""
        roots = [self.project(f"p{i}") for i in range(3)]
        for root in roots:
            seen.note(root)
        sync._absorb_seen()
        self.assertEqual(
            sorted(p["root"] for p in registry.load()),
            sorted(os.path.realpath(r) for r in roots),
        )


class TestWiring(unittest.TestCase):
    def test_the_shared_hook_runner_leaves_the_trace(self):
        """모든 훅이 지나는 자리에 배선돼 있다 — 여기서 빠지면 흔적은 영영 안 생긴다.

        훅 하나를 골라 배선하면 그 훅을 안 쓰는 호스트에서 통째로 꺼진다. 세 호스트가 공통으로
        지나는 곳은 `firing.run` 하나뿐이라 그 사실을 시험으로 박는다."""
        from asgard.hooks.asgard_hooklib import firing

        source = open(firing.__file__, encoding="utf-8").read()
        self.assertIn("note_project(root)", source)


if __name__ == "__main__":
    unittest.main()
