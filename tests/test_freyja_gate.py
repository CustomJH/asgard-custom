"""시각 표면 게이트 — 래칫과 정직한 미판정 보고.

이 게이트가 생긴 이유는 실측된 실패다: 에이전트가 엔진 이름을 부르고 판정기만 돌려 PASS를
받았는데, 사람은 그 화면을 슬롭이라고 했다. 그러니 여기서 지킬 것은 두 가지다.
  · 이번 변경이 **새로 만든** 표면 결함은 막는다.
  · 이미 있던 것은 안 막는다 — 안 그러면 아무도 이 게이트를 켜 두지 않는다.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from asgard import freyja_gate

# 엔진 4 판정기가 A3(사전 자기비평 없음) + A4(균일 타일 격자)를 둘 다 무는 최소 표면
SLOP = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>t</title><style>
  /* Freyja4 · component: sample */
  :root{--paper:#0C0A07;--ink:#E9E0CA}
  html,body{overflow-x:clip;margin:0;background:var(--paper);color:var(--ink)}
  .cards{display:grid;grid-template-columns:1fr 1fr}
  .card{padding:16px}
</style></head><body>
<div class="cards">
  <div class="card"><strong>하나</strong><span>설명</span></div>
  <div class="card"><strong>둘</strong><span>설명</span></div>
  <div class="card"><strong>셋</strong><span>설명</span></div>
  <div class="card"><strong>넷</strong><span>설명</span></div>
</div></body></html>
"""

CLEAN = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>t</title><style>
  /* Freyja4 · component: sample · pre-emit critique: P4 H4 E4 S4 R4 V4 */
  :root{--paper:#0C0A07;--ink:#E9E0CA}
  html,body{overflow-x:clip;margin:0;background:var(--paper);color:var(--ink)}
  .stack{display:flex;flex-direction:column}
</style></head><body>
<div class="stack"><p>한 줄</p></div></body></html>
"""


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@unittest.skipIf(shutil.which("node") is None, "판정기는 node 로 돈다 — 없으면 잴 수 없다")
@unittest.skipIf(shutil.which("git") is None, "래칫은 git base 를 읽는다")
class FreyjaGateCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="freyja-gate-")
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "gate@asgard.local")
        _git(self.root, "config", "user.name", "Gate")

    def _write(self, name, body):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def _commit(self, message="base"):
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", message)


class TestRatchet(FreyjaGateCase):
    def test_a_new_slop_surface_blocks(self):
        self._write("page.html", CLEAN)
        self._commit()
        self._write("new.html", SLOP)

        report = freyja_gate.judge(self.root)

        gates = {f.gate for f in report.findings}
        self.assertIn("A4", gates, "균일 타일 격자를 못 잡았다")
        self.assertIn("A3", gates, "사전 자기비평 누락을 못 잡았다")
        self.assertTrue(all(f.path == "new.html" for f in report.findings))

    def test_a_defect_that_was_already_there_does_not_block(self):
        """래칫의 전부 — 기존 부채로 사람을 막으면 게이트는 꺼진다."""
        self._write("page.html", SLOP)
        self._commit()
        # 같은 결함을 그대로 둔 채 무관한 한 줄만 바꾼다
        self._write("page.html", SLOP.replace("<p>", "<p>").replace("하나", "하나."))

        report = freyja_gate.judge(self.root)

        self.assertEqual(report.findings, [], f"기존 결함이 막았다: {[f.line() for f in report.findings]}")

    def test_making_an_existing_surface_worse_blocks(self):
        self._write("page.html", CLEAN)
        self._commit()
        self._write("page.html", SLOP)

        report = freyja_gate.judge(self.root)

        self.assertIn("A4", {f.gate for f in report.findings})

    def test_no_visual_surface_means_nothing_to_judge(self):
        self._write("notes.md", "# 글")
        self._commit()
        self._write("notes.md", "# 글 둘")

        report = freyja_gate.judge(self.root)

        self.assertEqual(report.surfaces, ())
        self.assertEqual(report.findings, [])

    def test_it_says_what_it_could_not_measure(self):
        """0건이 '안 봤다'를 뜻할 수 있으면 게이트가 아니라 장식이다."""
        self._write("page.html", CLEAN)

        report = freyja_gate.judge(self.root)

        self.assertTrue(report.unjudged)
        joined = " ".join(report.unjudged)
        for name in ("프레이야 1", "프레이야 2", "프레이야 3", "숀헤르빙", "토르"):
            self.assertIn(name, joined, f"{name} 을(를) 못 쟀다는 사실이 보고에 없다")
        self.assertIn("프레이야 4 · 마르될", report.engines)

    def test_line_shift_alone_is_not_a_new_finding(self):
        """같은 지적이 줄만 밀렸다고 새 결함이 되면 래칫이 매 턴 흔들린다."""
        self._write("page.html", SLOP)
        self._commit()
        self._write("page.html", SLOP.replace("<body>", "<body>\n<!-- 주석 한 줄 -->"))

        report = freyja_gate.judge(self.root)

        self.assertEqual(report.findings, [], f"줄 이동이 새 결함으로 셌다: {[f.line() for f in report.findings]}")


class TestEngineTable(unittest.TestCase):
    def test_every_engine_declares_where_its_evidence_lives(self):
        for engine in freyja_gate.ENGINES:
            self.assertTrue(engine.vault, engine.key)
            self.assertTrue(engine.judges, engine.key)

    def test_freyja4_runtime_ships_with_the_wheel(self):
        engine = next(e for e in freyja_gate.ENGINES if e.key == "freyja4")
        self.assertIsNotNone(freyja_gate.runtime_path(engine), "엔진 4 판정기가 배송되지 않는다")


if __name__ == "__main__":
    unittest.main()
