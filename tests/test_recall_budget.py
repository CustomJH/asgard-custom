#!/usr/bin/env python3
"""주입 예산의 단일 출처 계약 — 여섯 레인이 **하나의** 천장 아래서 겨룬다.

여기서 지키는 불변식 넷:

  1. 네이티브 루프(DIRECT·Trinity)와 CC 훅 표면의 주입면 상한이 같다. 전에는 네이티브만
     에피소드 블록을 조립기 **밖**에서 이어 붙여 그 경로의 천장이 에피소드 예산만큼 높았다.
  2. 에피소드 구간도 레인 간 중복 판정을 지난다 — 조립기 밖에 있으면 개인·프로젝트·문서
     레인과 같은 사실을 두 번 실을 수 있다.
  3. 총 예산은 형제 상수에서 파생된다. 숫자 복사본이 있으면 형제를 고칠 때 조용히 어긋난다.
  4. 조립기가 버린 스킬은 사용으로 안 센다 — `skill_curator`의 노화 판정이 그 수를 원료로
     삼으므로, 자르기 전에 세면 주입된 적 없는 스킬이 영영 안 늙는다.

실행: uv run pytest tests/test_recall_budget.py
"""

import inspect
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import memory, memory_context, skill_bank  # noqa: E402
from asgard.agent import episodes, turn_store  # noqa: E402
from asgard.agent.heimdall import core as heimdall_core  # noqa: E402
from asgard.agent.heimdall import trinity  # noqa: E402
from asgard.project_memory import documents  # noqa: E402

# 여섯 레인 중 넷은 이 시험에서 후보를 못 낸다(프로젝트 backend 없음). 그 넷의 예산을 0으로
# 눌러 두면 총 천장이 개인+에피소드 둘의 합이 되어, 작은 코퍼스로도 **포화**를 만들 수 있다.
# 천장은 여섯 항의 합이라, 두 레인만 채워서는 실제 7,060에 절대 못 닿는다.
_SHRUNK_LANES = (
    (memory_context, "PROJECT_RECALL_BUDGET", 0),
    (memory_context, "SYNTHESIS_BUDGET", 0),
    (memory_context, "SKILLS_BUDGET", 0),
    (documents, "DOCUMENT_BUDGET", 0),
    (memory, "RECALL_BUDGET", 260),
    (episodes, "EPISODE_BUDGET", 260),
)


def _write_skill(base: str, name: str, triggers: str, description: str) -> None:
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    text = (
        f"---\nname: {name}\ndescription: {description}\ntriggers: {triggers}\n"
        f"agent: worker\norigin: retrospective\ncreated: 2026-08-01\n---\n\n본문 절차\n"
    )
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write(text)
    receipt = skill_bank.approval_receipt(os.path.dirname(os.path.dirname(base)), name, text, create_key=True)
    with open(os.path.join(d, skill_bank.APPROVAL_FILE), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "proj")
        self.home = os.path.join(self._tmp.name, "home")
        self.memdir = os.path.join(self._tmp.name, "memory")
        os.makedirs(self.root)
        os.makedirs(self.home)
        os.makedirs(self.memdir)
        self._env = mock.patch.dict(
            os.environ,
            {
                "HOME": self.home,
                "USERPROFILE": self.home,
                "ASGARD_MEMORY_DIR": self.memdir,
                "ASGARD_MEMORY_INJECT": "on",
                "ASGARD_MEMORY_SEMANTIC": "off",  # 임베더 없이 결정론 어휘 경로로만 잰다
            },
        )
        self._env.start()
        skill_bank._cache.clear()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _pad_turns(self, n: int = 4) -> None:
        """최근 _EXCLUDE_TAIL 턴은 라이브 history 몫이라 주입에서 빠진다 — 꼬리를 채워 둔다."""
        for i in range(n):
            turn_store.append_turn(self.root, f"잡담 질문 {i}", f"잡담 응답 {i}")


class TestOneCeilingForEverySurface(Base):
    """네이티브 루프와 CC 훅이 같은 천장을 쓰는가 — 실제로 길이를 잰다."""

    QUERY = "결제 정산 배치 재처리"

    def _fill(self) -> None:
        for i in range(6):
            memory.add(
                f"결제 정산 배치 재처리 절차 {i} 는 실패 건만 골라 다시 돌린다. "
                f"큐를 비우지 않고 커서만 되감는다 (기록 {i}).",
                title=f"결제 정산 배치 재처리 {i}",
                kind="note",
                d=self.memdir,
            )
        for i in range(6):
            turn_store.append_turn(
                self.root,
                f"결제 정산 배치 재처리 어떻게 했더라 {i}",
                f"실패 건만 골라 다시 돌렸다. 커서를 되감는 방식이다 (세션 {i}).",
            )
        self._pad_turns()

    def _shrink(self) -> None:
        """레인 예산을 눌러 작은 코퍼스로 천장을 포화시킨다 — 시험이 끝나면 되돌린다."""
        for owner, name, value in _SHRUNK_LANES:
            patcher = mock.patch.object(owner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_native_and_hook_surfaces_share_one_ceiling(self):
        self._fill()
        self._shrink()
        ceiling = memory_context.recall_total_budget()
        self.assertEqual(ceiling, 520)  # 260 + 260 — 나머지 넷은 이 시험에서 0

        native = memory_context.recall_note(self.QUERY, start=self.root, include_episodes=True)
        hook = memory_context.recall_note(self.QUERY, start=self.root, include_skills=True, include_episodes=True)
        # 조립기 밖에서 이어 붙이던 옛 모양 — 같은 코퍼스에서 천장을 넘는다는 것이 결함의 증거다.
        spliced = memory_context.recall_note(self.QUERY, start=self.root) + episodes.episode_note(self.QUERY, self.root)

        self.assertTrue(native.strip(), "개인·에피소드 두 레인이 다 비면 이 시험은 아무것도 안 잰다")
        self.assertIn("episode-recall", native)
        self.assertLessEqual(len(native), ceiling)
        self.assertLessEqual(len(hook), ceiling)
        self.assertGreater(len(spliced), ceiling)  # 옛 모양은 천장 밖이었다

    def test_the_native_loop_does_not_splice_the_episode_block_itself(self):
        """DIRECT·Trinity 호출부가 조립기 밖에서 블록을 이어 붙이지 않는가.

        길이만 재면 '호출부가 include_episodes 를 켰는가'는 안 잡힌다 — 회귀가 되돌아올
        자리가 정확히 그 호출부라 소스로 못을 박는다."""
        direct = inspect.getsource(heimdall_core.Heimdall._direct)
        self.assertIn("include_episodes=True", direct)
        self.assertNotIn("episode_note", direct)
        # Trinity 는 Thinker·Worker 두 자리에서 회수를 부른다. 개수를 박아 두는 대신 호출부
        # 수와 맞춰 둔다 — 세 번째 호출부가 생겨도 그쪽이 인자를 빠뜨리면 여기서 걸린다.
        source = inspect.getsource(trinity)
        self.assertNotIn("episode_note", source)
        self.assertEqual(
            source.count("include_episodes=True"),
            source.count("memory_context import recall_note"),
            "Trinity 의 회수 호출부 중 에피소드를 조립기 밖에 두는 자리가 있다",
        )


class TestEpisodesFaceTheDedupPass(Base):
    """에피소드 구간도 레인 간 중복 판정을 지난다 — 조립기 밖에 있으면 안 지나던 그 판정."""

    SHARED = (
        "정산 마감 배치는 실패 건만 골라 다시 돌린다. 큐를 비우지 않고 커서만 되감아 "
        "중복 정산을 막는 것이 이 절차의 핵심이다."
    )

    def test_the_same_fact_lands_once_across_personal_and_episode(self):
        memory.add(self.SHARED, title="정산 마감 배치 재처리", kind="note", d=self.memdir)
        turn_store.append_turn(self.root, "정산 마감 배치 재처리 어떻게 하지", self.SHARED)
        self._pad_turns()

        # 두 레인이 각자 후보를 내는지부터 확인한다 — 한쪽이 비면 중복 제거를 안 재는 셈이다.
        self.assertTrue(memory.recall_rows("정산 마감 배치 재처리", k=3, d=self.memdir))
        self.assertTrue(episodes.episode_rows("정산 마감 배치 재처리", self.root))

        note = memory_context.recall_note("정산 마감 배치 재처리", start=self.root, include_episodes=True)

        needle = "커서만 되감아"
        self.assertIn(needle, note)
        self.assertEqual(note.count(needle), 1)  # 두 레인에 있어도 주입면에는 한 번만 들어간다

    def test_a_distinct_episode_still_gets_in(self):
        """중복 제거가 '에피소드 레인을 통째로 끈다'로 번지지 않았는가 (과차단 방어)."""
        memory.add(self.SHARED, title="정산 마감 배치 재처리", kind="note", d=self.memdir)
        turn_store.append_turn(
            self.root,
            "야간 마감 알림은 누가 받나",
            "당직 채널로만 간다. 담당자 개인 연락처는 장부에 안 남긴다.",
        )
        self._pad_turns()

        note = memory_context.recall_note("마감", start=self.root, include_episodes=True)

        self.assertIn("당직 채널", note)


class TestTotalBudgetFollowsItsSiblings(Base):
    """총 예산이 형제 상수에서 파생되는가 — 숫자 복사본 회귀 방지."""

    def test_document_and_episode_budgets_move_the_total(self):
        base = memory_context.recall_total_budget()
        with mock.patch.object(documents, "DOCUMENT_BUDGET", documents.DOCUMENT_BUDGET + 111):
            self.assertEqual(memory_context.recall_total_budget(), base + 111)
        with mock.patch.object(episodes, "EPISODE_BUDGET", episodes.EPISODE_BUDGET + 222):
            self.assertEqual(memory_context.recall_total_budget(), base + 222)
        self.assertEqual(memory_context.recall_total_budget(), base)

    def test_every_lane_budget_moves_the_total(self):
        """여섯 항 전부 — 하나라도 숫자로 박히면 여기서 걸린다."""
        base = memory_context.recall_total_budget()
        for owner, name in (
            (memory, "RECALL_BUDGET"),
            (memory_context, "PROJECT_RECALL_BUDGET"),
            (documents, "DOCUMENT_BUDGET"),
            (memory_context, "SYNTHESIS_BUDGET"),
            (memory_context, "SKILLS_BUDGET"),
            (episodes, "EPISODE_BUDGET"),
        ):
            with mock.patch.object(owner, name, getattr(owner, name) + 7):
                self.assertEqual(
                    memory_context.recall_total_budget(), base + 7, f"{owner.__name__}.{name} 이 총 예산과 끊겨 있다"
                )

    def test_the_documented_ceiling_is_what_the_lanes_actually_sum_to(self):
        self.assertEqual(
            memory_context.recall_total_budget(),
            memory.RECALL_BUDGET
            + memory_context.PROJECT_RECALL_BUDGET
            + documents.DOCUMENT_BUDGET
            + memory_context.SYNTHESIS_BUDGET
            + memory_context.SKILLS_BUDGET
            + episodes.EPISODE_BUDGET,
        )


class TestSkillUseCountsOnlyWhatShipped(Base):
    """조립기가 버린 스킬은 사용으로 안 센다 — 큐레이터 노화 판정의 원료가 부풀지 않게."""

    def _two_skills(self) -> str:
        base = os.path.join(self.root, ".asgard", "skills")
        _write_skill(base, "learned-alpha", "부가세", "부가세 반올림 규칙" + " 설명 채움" * 12)
        _write_skill(base, "learned-beta", "부가세", "부가세 신고 마감 절차" + " 설명 채움" * 12)
        skill_bank._cache.clear()
        return base

    def test_a_dropped_skill_is_not_recorded_as_used(self):
        self._two_skills()
        rows = memory_context.learned_skills_rows("부가세 처리", start=self.root)
        self.assertEqual(len(rows), 2)  # 후보는 둘 — 그중 하나만 실릴 예산을 만든다
        self.assertEqual(skill_bank.usage(self.root), {})  # 후보 산출은 사용이 아니다

        overhead = len(memory_context.SKILLS_PREFIX) + len(memory_context.SKILLS_SUFFIX)
        only_first = overhead + len(rows[0]) + 3  # `- ` 접두 2자 + 줄바꿈 1자
        with mock.patch.object(memory_context, "SKILLS_BUDGET", only_first):
            note = memory_context.learned_skills_note("부가세 처리", start=self.root)

        shipped = [name for name in ("learned-alpha", "learned-beta") if name in note]
        self.assertEqual(len(shipped), 1, "예산이 한 줄만 허용해야 이 시험이 성립한다")
        self.assertEqual(sorted(skill_bank.usage(self.root)), shipped)

    def test_the_rendered_skill_is_recorded(self):
        """계수를 뒤로 미룬 것이 '아무것도 안 센다'가 되지 않았는가 (M7 수리의 반대편)."""
        self._two_skills()
        note = memory_context.learned_skills_note("부가세 처리", start=self.root)
        self.assertIn("learned-alpha", note)
        self.assertEqual(skill_bank.usage(self.root)["learned-alpha"]["uses"], 1)

    def test_the_assembled_recall_surface_counts_the_same_way(self):
        """조립기를 지나는 회수면(CC 훅)도 실린 것만 센다 — 표면마다 규율이 다르면 안 된다."""
        self._two_skills()
        note = memory_context.recall_note("부가세 처리", start=self.root, include_skills=True)
        counted = set(skill_bank.usage(self.root))
        self.assertTrue(counted)
        for name in counted:
            self.assertIn(name, note)


class _Recorder:
    """`documents.search`가 실제로 어떤 SQL을 돌렸는지 받아 적는 연결 프록시."""

    def __init__(self, conn: sqlite3.Connection, log: list[str]) -> None:
        self._conn, self._log = conn, log

    def execute(self, sql: str, *args):
        self._log.append(" ".join(sql.split()))
        return self._conn.execute(sql, *args)

    def close(self) -> None:
        self._conn.close()


class TestDocumentScanCapIsPaidBeforeTheLoad(Base):
    """상한을 넘는 코퍼스에서 본문 전량을 파이썬으로 끌어올리지 않는가 (M3)."""

    def _corpus(self) -> None:
        os.makedirs(os.path.join(self.root, ".asgard", "memory", "documents"), exist_ok=True)
        body = "\n\n".join(
            f"## {i} 절 제목 {i}\n계량기 통신 규격 항목 {i} 의 동작을 규정한다. " + ("본문 채움. " * 40)
            for i in range(1, 13)
        )
        path = os.path.join(self.root, ".asgard", "memory", "documents", "규격.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"---\nschema: {documents.DOCUMENT_SCHEMA}\nname: 규격서\nlane: local\n---\n\n{body}\n")
        self.assertGreater(documents.sync(self.root), 4)

    def _search_sql(self, cap: int) -> tuple[list[dict], list[str]]:
        log: list[str] = []
        real = documents._db
        with (
            mock.patch.object(documents, "MAX_SCAN_CHUNKS", cap),
            mock.patch.object(documents, "_db", lambda root: _Recorder(real(root), log)),
        ):
            hits = documents.search(self.root, "계량기 통신 규격", k=2)
        return hits, log

    def test_over_the_cap_only_the_matched_chunks_are_loaded(self):
        self._corpus()
        hits, log = self._search_sql(cap=1)
        self.assertTrue(hits)  # FTS 스트림만으로도 회수는 산다
        self.assertNotIn("SELECT seq, name, heading, body FROM doc", log)
        self.assertIn("SELECT count(*) FROM doc", log)

    def test_under_the_cap_the_scan_stream_still_reads_everything(self):
        """상한 이내면 두 스트림이 다 돈다 — 수리가 스캔 스트림을 조용히 끄지 않았는가."""
        self._corpus()
        hits, log = self._search_sql(cap=10_000)
        self.assertTrue(hits)
        self.assertIn("SELECT seq, name, heading, body FROM doc", log)


if __name__ == "__main__":
    unittest.main()
