#!/usr/bin/env python3
"""파일 하나의 크기 — 저장소가 이미 쥔 상한을 보통의 시험 실행이 같이 본다.

`asgard health --gate` 가 `severe_files`(1,000 코드줄 초과 파일 수)를 pyproject 기준선과 대조한다.
그것을 여기로 데려오는 이유는 실행 시점이다: 게이트는 사람이 따로 부르는 명령이라, 부르지 않은
커밋에서는 파일이 자라도 아무도 모른다. 시험은 매번 돈다.

기준선은 여기 안 적는다 — 두 자리에 적으면 하나가 낡고, 낡은 쪽이 계약처럼 보인다. 정본은
`pyproject.toml` 의 `[tool.asgard.health-gate]` 다.

수만 세지 않고 이름까지 보는 이유: 한 파일을 쪼갠 자리에 다른 파일이 자라 들어오면 수는
그대로라 초록으로 남는다. 26-08-06 까지 그 이름 검사는 훅 둘(`quest_log.py`·`verifier_gate.py`)을
면제하고 있었다 — 단일 파일 배포 계약 때문이었다. 그 계약이 바뀌어(공용 라이브러리가 훅과 같은
폴더에 함께 깔린다) 면제도 사라졌다. 지금은 상한을 넘는 파일이 없어야 한다.

실행: uv run pytest tests/test_module_size.py
"""

import os
import unittest

from asgard.health import FILE_LINES_SEVERE, _code_lines, _is_test, _iter_files, _read, gate_baseline, scan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _oversized() -> list[str]:
    """상한을 넘은 소스 파일 경로. `scan` 과 같은 목록·같은 줄 세기·같은 시험 제외를 쓴다.

    시험 파일을 빼는 것은 `severe_files` 가 그렇게 세기 때문이다 — 큰 시험 파일은 한 계약을
    한자리에 모아 둔 결과라 분해가 오히려 계약을 흩는다."""
    listing, _excluded = _iter_files(ROOT)
    out = []
    for rel, lang in listing:
        if _is_test(rel):
            continue
        text = _read(ROOT, rel)
        if text is not None and len(_code_lines(text, lang)) > FILE_LINES_SEVERE:
            out.append(rel)
    return sorted(out)


class TestFileSize(unittest.TestCase):
    def test_severe_file_count_does_not_exceed_the_recorded_baseline(self):
        baseline = gate_baseline(ROOT).get("severe_files")
        assert isinstance(baseline, int), "pyproject 의 [tool.asgard.health-gate] 에 severe_files 기준선이 없다"
        self.assertLessEqual(
            scan(ROOT).severe_files,
            baseline,
            f"{FILE_LINES_SEVERE}줄을 넘긴 파일이 기준선({baseline})보다 많다 — 쪼개거나, 왜 넘겨야 했는지와 "
            "함께 pyproject 의 기준선을 올려라",
        )

    def test_no_source_file_is_past_the_line(self):
        strays = _oversized()
        self.assertEqual(
            strays,
            [],
            f"{FILE_LINES_SEVERE}줄을 넘긴 소스 파일: {strays} — 면제는 없다. 쪼개거나, 왜 넘겨야 "
            "했는지와 함께 pyproject 의 기준선을 올려라",
        )


if __name__ == "__main__":
    unittest.main()
