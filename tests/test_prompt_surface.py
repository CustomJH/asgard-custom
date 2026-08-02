#!/usr/bin/env python3
"""상시 주입면의 계약 — 한 프롬프트가 스스로를 부정하거나 같은 말을 두 번 하지 않는다.

네이티브 루프의 DIRECT 턴은 AGENTS.md 전문 + Lagom 전문 + Bragi 전문을 한 문자열로 지고 간다
(`core.py`의 `delivery_identity`). 그 문자열이 커지는 것 자체는 값을 치를 만한 일이지만, 아래
넷은 값을 못 치른다 — 셋은 모델을 서로 반대 방향으로 당기고, 하나는 깨진 마크다운이다.

  1. **자기모순** — `NATIVE_NOTE`는 "quest-log 명령을 직접 실행하지 마라"고 하는데, 같은
     프롬프트의 Trinity 절이 그 명령들의 사용법을 문단째 가르친다. 모드 B(CC·Cursor·Codex)에는
     필요한 계약이지만 네이티브에는 실행하면 안 되는 절차다.
  2. **이중 정의** — Lagom·Bragi가 AGENTS.md 요약 절과 별도 전문으로 두 번 실린다. 이미 문구가
     갈라졌다(요약 "shortest explanation" vs 전문 "Fragment compression").
  3. **역할 불일치** — 주석 계약은 코드를 쓰는 역할만 받기로 설계돼 있는데(`core.py`의
     `self.comments` 주석), AGENTS.md 절을 타고 readonly DIRECT 턴까지 흘러든다.
  4. **깨진 표** — Lagom 전문의 표 둘에 마크다운 구분선이 없어 표로 렌더되지 않는다.

실행: uv run pytest tests/test_prompt_surface.py
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.agent.heimdall.roles import NATIVE_NOTE, delivery_identity, direct_identity  # noqa: E402
from asgard.bragi import note as bragi_note  # noqa: E402
from asgard.lagom import note as lagom_note  # noqa: E402
from asgard.templates.lagom import render_lagom  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")


def direct_prompt(root: str) -> str:
    """DIRECT 턴이 실제로 받는 문자열 — `core.py`가 조립하는 것과 같은 순서.

    charter/manual/memory는 이 저장소에서 빈 문자열이라 뺐다. 넣어도 아래 판정은 안 바뀐다."""
    return direct_identity(root) + lagom_note(root) + bragi_note(root)


class TestSelfContradiction(unittest.TestCase):
    """금지된 명령의 사용법을 같은 프롬프트가 가르치면, 모델은 둘 중 하나를 어겨야 한다."""

    def test_native_note_forbids_quest_log_commands(self):
        self.assertIn("do not run quest-log commands", NATIVE_NOTE)

    def test_identity_does_not_teach_the_forbidden_commands(self):
        for label, text in (("direct", direct_identity(REPO)), ("delivery", delivery_identity(REPO))):
            taught = sorted({m for m in re.findall(r"quest-log\.py [a-z-]+", text)})
            self.assertEqual(
                [],
                taught,
                f"[{label}] NATIVE_NOTE가 금지한 quest-log 명령의 사용법을 같은 프롬프트가 가르친다: "
                + ", ".join(taught),
            )

    def test_identity_does_not_carry_mode_b_ticket_protocol(self):
        """`[ASGARD_UNIT:<id>]` 티켓 프로토콜은 모드 B 계약 — 네이티브는 waves가 코드로 한다."""
        self.assertFalse("[ASGARD_UNIT:" in direct_identity(REPO), "모드 B 티켓 프로토콜이 네이티브 정체성에 있다")


class TestNoDoubleContract(unittest.TestCase):
    """같은 계약이 두 벌 실리면 토큰만 드는 게 아니라 문구가 갈라진다 — 이미 갈라져 있다."""

    def test_lagom_stated_once(self):
        text = direct_prompt(REPO)
        n = text.count("Lagom — Minimalism Contract") + text.count("Asgard — Lagom (Minimalism Contract)")
        self.assertEqual(1, n, f"Lagom 계약이 {n}벌 실렸다 (요약 절 + 전문)")

    def test_bragi_stated_once(self):
        text = direct_prompt(REPO)
        n = text.count("Bragi — Human Voice Contract") + text.count("Asgard — Bragi (Human Voice)")
        self.assertEqual(1, n, f"Bragi 계약이 {n}벌 실렸다 (요약 절 + 전문)")

    def test_clipped_word_example_does_not_exceed_the_two_contracts(self):
        """`불요` 예시 하나로 중복 배수를 잰다 — 요약 절이 살아 있으면 네 벌이 된다.

        바닥은 둘이지 하나가 아니다. Trinity 역할 중 bragi를 받는 역할이 없어서(thinker·worker는
        lagom만, verifier는 LAGOM_VERIFIER_NOTE만) `LAGOM_CANON`의 문법 절이 그 역할들의 유일한
        문법 계약이다. 하나로 줄이려면 문법을 공용 노트로 빼고 역할 배선을 바꿔야 한다 — 이
        수리의 범위가 아니다."""
        n = direct_prompt(REPO).count("불요")
        self.assertLessEqual(n, 2, f"같은 맞춤법 예시가 {n}번 실렸다 (요약 절이 안 빠졌다)")


class TestRoleFit(unittest.TestCase):
    """주석 계약은 코드를 쓰는 역할의 것 — readonly DIRECT는 쓸 일이 없다."""

    def test_direct_identity_has_no_comment_contract(self):
        self.assertFalse(
            "Asgard — Comments and Docstrings" in direct_identity(REPO),
            "readonly DIRECT 턴이 주석 계약을 진다 (core.py의 설계 의도와 반대)",
        )

    def test_delivery_identity_keeps_the_comment_contract(self):
        """딜리버리 자식은 코드를 쓰고 COMMENT_CANON을 따로 안 받는다 — 여기서 빼면 계약을 잃는다."""
        self.assertTrue(
            "Asgard — Comments and Docstrings" in delivery_identity(REPO),
            "딜리버리 자식이 주석 계약을 잃었다",
        )


class TestModeBKeepsTheWholeContract(unittest.TestCase):
    """게이팅은 주입 시점의 필터다 — 템플릿을 줄이면 훅 없는 표면이 계약을 잃는다.

    Codex와 Cursor는 SessionStart 훅이 없어서 AGENTS.md가 유일한 접점이고, CC는 이 파일을
    `.claude/CLAUDE.md`로 브릿지한다. 네이티브가 안 읽는다고 템플릿에서 지우면 그 셋이 조용히
    맨몸이 된다. 그래서 여기서 절과 절차를 통째로 지킨다."""

    def test_every_marker_section_survives_in_the_template(self):
        from asgard.templates.agents import agents_md

        text = agents_md("demo")
        for name in ("identity", "law", "trinity", "map", "lagom", "bragi", "comments", "memory", "manual", "agents"):
            self.assertIn(f"asgard:{name}", text, f"모드 B 템플릿에서 {name} 절이 사라졌다")

    def test_mode_b_still_gets_the_quest_log_protocol(self):
        from asgard.templates.agents import agents_md

        text = agents_md("demo")
        for s in ("quest-log.py open", "ticket-claim --unit", "[ASGARD_UNIT:", "ASGARD_OK"):
            self.assertIn(s, text, f"모드 B가 {s!r} 계약을 잃었다")


class TestConflictsResolved(unittest.TestCase):
    """서로 반대로 당기던 조항 쌍 — 한쪽을 어겨야 지킬 수 있으면 규칙이 아니라 함정이다."""

    def test_canon5_exempts_secret_stores(self):
        """Canon 4는 `.env`를 못 읽게 하고 Canon 5는 재정의 자리를 전부 읽게 한다."""
        from asgard.templates.canon import CANON_SECTION

        self.assertIn("Secret stores stay closed even here", CANON_SECTION)

    def test_unattended_restatement_keeps_the_safety_exemption(self):
        """Canon 8 본문은 2·3을 예외로 두는데 Trinity 재진술이 3만 남기면 안전이 샌다."""
        from asgard.templates.agents import agents_md

        text = agents_md("demo")
        self.assertNotIn("Unless destructive (Canon 3)", text)
        self.assertIn("Unless Canon 2 (safety) or Canon 3 (destructive) applies", text)

    def test_lagom_brevity_does_not_flatten_sentence_rhythm(self):
        """Lagom '짧은 문장'과 Bragi '길이를 섞어라'가 같은 프롬프트에 있었다."""
        body = render_lagom("full")
        self.assertNotIn("use shorter synonyms and short sentences", body)
        self.assertIn("Brevity caps the total, not every sentence", body)


class TestLeanFlagRestoresLegacy(unittest.TestCase):
    """되돌림 손잡이 — `ASGARD_PROMPT_LEAN=0`이면 종전 주입면과 바이트 동일해야 한다."""

    def test_flag_zero_keeps_every_section(self):
        prev = os.environ.get("ASGARD_PROMPT_LEAN")
        os.environ["ASGARD_PROMPT_LEAN"] = "0"
        try:
            text = direct_identity(REPO)
        finally:
            if prev is None:
                os.environ.pop("ASGARD_PROMPT_LEAN", None)
            else:
                os.environ["ASGARD_PROMPT_LEAN"] = prev
        for name in ("trinity", "lagom", "bragi", "comments"):
            self.assertIn(f"asgard:{name}", text, f"LEAN=0인데 {name} 절이 빠졌다")


class TestLagomTableRenders(unittest.TestCase):
    """구분선 없는 표는 마크다운이 아니라 파이프가 섞인 줄 두 개다."""

    def test_tables_have_separator_rows(self):
        for mode in ("lite", "full"):
            body = render_lagom(mode)
            for line in body.splitlines():
                if line.startswith("| Mode |"):
                    idx = body.splitlines().index(line)
                    nxt = body.splitlines()[idx + 1]
                    self.assertRegex(
                        nxt,
                        r"^\|\s*-{3,}\s*\|",
                        f"[{mode}] 표 머리 뒤에 구분선이 없다: {nxt!r}",
                    )


if __name__ == "__main__":
    unittest.main()
