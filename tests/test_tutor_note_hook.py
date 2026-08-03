"""tutor-note 훅 — 22개 훅 중 유일하게 행위 테스트가 0이던 자리.

실행: uv run pytest tests/test_tutor_note_hook.py

`tests/test_tutor.py` 는 엔진(`asgard.tutor`)만 잰다. 훅은 그 엔진의 판정을 **클라이언트
프로토콜로 옮기는 층**이고, 거기서 고장 나면 Stop 시점마다 조용히 실패한다 — 막지 않는 훅이라
화면에 아무것도 안 남는다. 되짚기가 빠진 턴과 되짚을 것이 없던 턴은 똑같이 생겼다.

그래서 여기서 보는 것은 두 가지뿐이다: 정상 payload 가 카드를 내는가, 깨진 payload 가 턴을
막지 않는가. 판정 규칙 자체는 엔진 몫이라 여기서 다시 재지 않는다 (훅은 규칙을 안 갖는다).

구동은 `tests/test_mode_parity.py` 의 `_hook_payload` 를 그대로 쓴다 — 스캐폴드를 깔지 않고
훅 소스를 in-process 로 돌리는 같은 자.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from test_mode_parity import _hook_payload  # rootdir 삽입 경로 — test_orchestration_trinity 와 같은 관례

from asgard.hooks import tutor_note

_LESSON = {
    "files": ["app.py"],
    "added": 12,
    "removed": 3,
    "checkpoints": [
        {
            "kind": "silent-failure",
            "path": "app.py",
            "line": 42,
            "unit": "load_config",
            "ask": "이 except 가 삼키는 실패는 누가 알게 되나요?",
            "cid": "c1f2",
        }
    ],
    "revisits": [],
}


class TutorNoteHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        # 훅은 CLAUDE_PROJECT_DIR 를 cwd 보다 먼저 본다 — 이 스위트를 돌리는 세션이 그 변수를
        # 세워 두면 판정 대상이 사용자의 실제 저장소가 된다. 여기서 명시적으로 끊는다.
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def _sentinel(self, sid: str, paths: list[str]) -> None:
        state = os.path.join(self.root, ".asgard", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "writes-" + sid + ".json"), "w", encoding="utf-8") as fh:
            json.dump(paths, fh)

    def test_a_written_session_gets_the_review_card(self) -> None:
        """정상 payload — 이 턴이 쓴 파일이 있고 엔진이 물음을 냈으면 카드가 stdout 으로 나간다."""
        self._sentinel("s1", ["app.py"])
        with (
            mock.patch.object(tutor_note, "_lesson", return_value=_LESSON),
            mock.patch.object(tutor_note.shutil, "which", return_value="/usr/bin/asgard"),
        ):
            code, out = _hook_payload("tutor_note", {"session_id": "s1", "cwd": self.root}, [])
        self.assertEqual(code, 0, "되짚기는 규율이지 관문이 아니다 — 어떤 경우에도 0으로 끝난다")
        card = json.loads(out)["systemMessage"]
        self.assertIn("app.py:42 load_config", card, out)
        self.assertIn("이 except 가 삼키는 실패는 누가 알게 되나요?", card)
        self.assertIn("조용히 삼킨 실패", card, "kind 가 사람 말로 번역돼야 한다")

    def test_a_broken_payload_does_not_take_the_turn_down(self) -> None:
        """깨진 payload — 칸 타입이 어긋나도 훅은 조용히 0으로 끝나고 아무것도 안 낸다.

        여기서 예외가 새면 Stop 훅이 매 턴 끝을 오염시킨다. 카드를 못 내는 것보다 나쁘다.
        """
        code, out = _hook_payload("tutor_note", {"session_id": {"not": "a string"}, "cwd": 12}, [])
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "판정 못 한 턴에 빈 카드를 놓으면 다음 카드의 신뢰가 깎인다")


if __name__ == "__main__":
    unittest.main()
