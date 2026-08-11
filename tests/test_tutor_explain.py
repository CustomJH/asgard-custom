"""설명 카드의 한 자리는 무엇을 말하는가 — 좌표와 줄 수가 아니라 **그 단위가 하는 일**.

실행: uv run pytest tests/test_tutor_explain.py

`test_tutor_teach.py` 가 재는 것은 엔진의 재료다 — 무엇이 바뀐 단위인가, 어떤 순서로 읽나,
무엇이 무엇을 부르나. 여기서 재는 것은 그 재료가 사람 앞에 놓이는 **모양**이다. 두 축을 갈라
두는 이유는 실패 방식이 다르기 때문이다: 재료가 틀리면 설명이 거짓이 되고, 모양이 틀리면
설명이 안 읽힌다. 26-08-11 에 오딘이 지적한 것은 뒤쪽이었다 — 스물일곱 곳이 바뀐 턴에서 카드가
한 자리만, 그것도 "본문이 바뀐 단위예요 (57행 → 67행)" 로만 말해서 요약처럼 읽혔다.

계약 두 줄:

  ① 한 자리는 그 단위가 무엇을 하는지 먼저 말한다. 그 문장은 **인용**이다 — 저자가 적어 둔
     docstring 첫 문장이고, 없으면 그 줄도 없다(기계가 의도를 지어내지 않는다, `tutor_teach`
     계약 ②).
  ② 엔진과 훅이 같은 줄을 낸다. 훅은 stdlib 전용이라 엔진을 못 부르고 JSON 칸만 보고 다시
     그리므로, 두 렌더러가 갈리면 같은 판정이 클라이언트마다 다르게 보인다.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import asdict, replace

from asgard import tutor_teach
from asgard.hooks import tutor_note

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _exp(**over) -> tutor_teach.Explanation:
    base = {
        "base": "HEAD",
        "depth": "first",
        "mission": "",
        "steps": (
            tutor_teach.Step(1, "m.py", 8, "alpha", "새로 생긴 단위예요 (2행)", "여기가 먼저예요", "우유를 데워요."),
            tutor_teach.Step(2, "m.py", 4, "zeta", "새로 생긴 단위예요 (2행)", "그 다음이에요"),
        ),
        "terms": (),
        "checks": (),
        "recall": (),
        "gaps": (),
        "primary_units": 2,
        "total_units": 2,
        "flow_count": 1,
    }
    return tutor_teach.Explanation(**{**base, **over})


class QuotedPurposeTest(unittest.TestCase):
    """계약 ① — 인용이지 요약이 아니다. 지어낸 의도가 들어오면 이 층은 `tutor` 가 막으려던 일을 한다."""

    def _repo(self, stack) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
        with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True, env=_ENV, capture_output=True)
        return root

    def test_a_step_says_what_the_unit_does_by_quoting_its_docstring(self):
        """줄 수 증감만 적던 자리에 그 단위가 스스로 적어 둔 한 문장이 붙는다.

        오딘의 지적 (26-08-11): 카드가 "본문이 바뀐 단위예요 (57행 → 67행)" 만 말하면 그 단위를
        이미 아는 사람에게만 뜻이 있다. 처음 보는 사람에게 필요한 것은 그 자리가 무엇을 하는가고,
        그건 저자가 이미 적어 뒀다.
        """
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            body = (
                'def brew(bean):\n    """설정을 읽기 위해 물을 부어요. 두 번째 문장은 안 나와요."""\n'
                "    return bean\n\n\ndef steam(cup):\n    return cup\n"
            )
            with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
                handle.write(body)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)
            steps = {s.unit: s for s in tutor_teach.explain(root, "HEAD").steps}

            self.assertEqual(steps["brew"].does, "설정을 읽기 위해 물을 부어요.")
            self.assertIn(steps["brew"].does, body, "인용이지 요약이 아니다")
            self.assertEqual(steps["steam"].does, "", "docstring 이 없으면 아무것도 안 쓴다")
            self.assertIn("(2행)", steps["steam"].what, "변경 사실은 그대로 남는다")

    def test_a_class_and_a_method_keep_their_own_sentences(self):
        """이름은 점 이어붙인 이름이다 — 꼬리만 맞추면 같은 이름의 메서드가 남의 문장을 받는다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            body = (
                'class Kettle:\n    """물을 끓여요."""\n\n    def pour(self):\n        """컵에 부어요."""\n'
                '        return 1\n\n\ndef pour():\n    """바닥에 부어요."""\n    return 2\n'
            )
            with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
                handle.write(body)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)
            docs = tutor_teach._doclines(body)

            self.assertEqual(docs["Kettle.pour"], "컵에 부어요.")
            self.assertEqual(docs["pour"], "바닥에 부어요.")
            self.assertEqual(docs["Kettle"], "물을 끓여요.")


class CardShapeTest(unittest.TestCase):
    def test_a_step_with_a_docstring_leads_with_it_and_keeps_the_change_below(self):
        lines = tutor_teach.card(_exp()).splitlines()

        head = next(line for line in lines if "m.py:8 alpha" in line)
        self.assertTrue(head.endswith("— 우유를 데워요."), head)
        self.assertIn("     새로 생긴 단위예요 (2행) · 여기가 먼저예요", lines)
        self.assertIn("  2. m.py:4 zeta — 새로 생긴 단위예요 (2행) · 그 다음이에요", lines, "없으면 한 줄 그대로다")

    def test_an_owned_reader_still_gets_only_coordinates(self):
        """깊이가 올라가면 화면이 줄어든다(계약 ④) — 새 줄이 그 규칙을 뚫고 나오면 안 된다."""
        card = tutor_teach.card(replace(_exp(), depth="owned"))

        self.assertNotIn("우유를 데워요", card)
        self.assertIn("m.py:8 alpha", card)


class TwoRenderersTest(unittest.TestCase):
    """계약 ② — 엔진의 `card` 와 훅의 `_explain` 이 글자까지 같은 줄을 낸다."""

    def test_the_two_screens_are_one_screen_at_every_depth(self):
        for depth in tutor_teach.DEPTHS:
            row = replace(_exp(), depth=depth)
            engine = tutor_teach.card(row, 3)
            hook = "\n".join(tutor_note._explain(json.loads(json.dumps(asdict(row))), 3))

            self.assertEqual(hook, engine, depth)

    def test_an_old_payload_without_the_field_still_draws(self):
        """훅과 엔진의 배송 시점은 어긋날 수 있다 — 칸이 없으면 종전 한 줄 모양 그대로다."""
        payload = json.loads(json.dumps(asdict(_exp())))
        for step in payload["steps"]:
            step.pop("does", None)

        lines = tutor_note._explain(payload, 3)

        self.assertTrue(any("1. m.py:8 alpha — 새로 생긴 단위예요 (2행) · 여기가 먼저예요" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
