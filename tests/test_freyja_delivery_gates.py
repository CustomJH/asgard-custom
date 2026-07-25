"""배달 게이트 — 소스 읽기는 통과하고 실물에서 깨지는 결함을 두 엔진이 놓치지 않게.

실측 계기(2026-07-25): 같은 브리프로 엔진1·2 랜딩을 만들고 나서 셋을 뒤늦게 발견했다.

- 엔진2 페이지의 "저작된 모션 하나"가 한 번도 발화하지 않았다. `--pos` 를 인라인으로 한 번
  박고 `<script>` 가 없으니 `transition: left 900ms` 는 죽은 선언이었다. 소스만 보면
  애니메이션이 있는 페이지로 읽힌다.
- 양쪽 다 링크가 전부 `href="#"` 였다. craft floor 의 "working controls" 위반.
- loading·error·empty 상태가 0건이었다. craft floor 는 다섯 상태를 전부 요구한다.

앞의 둘은 기계로 판정 가능하므로 detector 규칙으로 내렸다(모델의 기억에 맡기지 않는다).
셋째는 결정론적으로 판정할 수 없어 두 엔진의 계약 문서에 "이름을 대라"는 절차로 넣었다.
이 파일은 그 셋을 각각 고정한다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_E2 = _REPO / "src/asgard/assets/skill_plugins/freyja2/skills/asgard-freyja2/engine"
_E2_SCRIPTS = _E2 / "scripts"
_E1_SKILL = _REPO / "src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/SKILL.md"
_NODE = shutil.which("node")

_INERT_MOTION = """<!DOCTYPE html><html lang="en"><head><style>
.needle { left: var(--pos, 10%); transition: left 900ms cubic-bezier(0.16,1,0.3,1); }
</style></head><body>
<div class="needle" style="--pos: 34%"></div>
<p>실제 본문이 있어야 페이지 분석기가 돈다. 이 문단은 그 조건을 채운다.</p>
</body></html>
"""

_LIVE_MOTION = """<!DOCTYPE html><html lang="en"><head><style>
.needle { left: var(--pos, 10%); transition: left 900ms cubic-bezier(0.16,1,0.3,1); }
</style></head><body>
<div class="needle" style="--pos: 34%"></div>
<p>실제 본문이 있어야 페이지 분석기가 돈다. 이 문단은 그 조건을 채운다.</p>
<script>document.querySelector(".needle").style.setProperty("--pos", "60%");</script>
</body></html>
"""

_DEAD_LINKS = """<!DOCTYPE html><html lang="en"><head><title>t</title></head><body>
<p>실제 본문이 있어야 페이지 분석기가 돈다. 이 문단은 그 조건을 채운다.</p>
<a href="#">하나</a><a href="#">둘</a><a href="#">셋</a>
</body></html>
"""

_REAL_ANCHORS = """<!DOCTYPE html><html lang="en"><head><title>t</title></head><body>
<p>실제 본문이 있어야 페이지 분석기가 돈다. 이 문단은 그 조건을 채운다.</p>
<a href="#log">하나</a><a href="#play">둘</a><a href="#foot">셋</a><a href="/about">넷</a>
</body></html>
"""


def _node_bin() -> str:
    """호출부는 전부 skipIf(_NODE is None) 아래에 있다."""
    assert _NODE is not None
    return _NODE


def _registry() -> dict[str, dict]:
    """레지스트리의 *런타임* 값을 묻는다.

    소스 텍스트를 훑으면 문자열 연결(`'... at ' + 'its destination'`)에 걸려 헛통과하거나
    헛실패한다. 사용자가 실제로 읽는 값은 평가된 뒤의 문자열이므로 그것을 검사한다.
    """
    script = (
        "import { ANTIPATTERNS } from "
        f"'{(_E2_SCRIPTS / 'detector/registry/antipatterns.mjs').as_posix()}';"
        "process.stdout.write(JSON.stringify(Object.fromEntries("
        "ANTIPATTERNS.map(r => [r.id, r]))));"
    )
    proc = subprocess.run(
        [_node_bin(), "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"레지스트리 로드 실패: {proc.stderr[:400]}")
    return json.loads(proc.stdout)


def _detect(html: str) -> list[str]:
    """detect CLI 를 실제로 돌려 규칙 id 목록을 돌려준다."""
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "index.html"
        page.write_text(html, encoding="utf-8")
        proc = subprocess.run(
            [_node_bin(), str(_E2_SCRIPTS / "detect.mjs"), "--json", "--no-config", str(page)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        # detect 는 발견이 있으면 2, 없으면 0 으로 끝난다. 그 밖은 진짜 실패다.
        if proc.returncode not in (0, 2):
            raise AssertionError(f"detect 실패 rc={proc.returncode}: {proc.stderr[:400]}")
        return [f.get("antipattern") for f in json.loads(proc.stdout or "[]")]


@unittest.skipIf(_NODE is None, "node 부재 — detector 검사 생략")
class TestEngine2DetectorGates(unittest.TestCase):
    """기계로 판정 가능한 둘은 detector 가 잡는다 — 모델이 기억하든 말든."""

    def test_inert_transition_is_reported(self):
        self.assertIn("inert-transition", _detect(_INERT_MOTION))

    def test_driven_transition_is_not_reported(self):
        """값을 실제로 바꾸는 스크립트가 있으면 모션은 살아 있다 — 오탐 금지."""
        self.assertNotIn("inert-transition", _detect(_LIVE_MOTION))

    def test_placeholder_links_are_reported(self):
        self.assertIn("placeholder-link", _detect(_DEAD_LINKS))

    def test_real_destinations_are_not_reported(self):
        """`#log` 는 페이지 안의 진짜 목적지다. 빈 `#` 만 센다."""
        self.assertNotIn("placeholder-link", _detect(_REAL_ANCHORS))

    def test_rules_reach_html_without_the_static_parser(self):
        """htmlparser2 류가 없으면 detectHtml 은 detectText 로 폴백한다.

        규칙을 파서 경로에만 배선했다가 정작 .html 에서 한 번도 안 도는 것을 실측으로
        발견했다. 두 경로 모두에 배선돼 있어야 한다.
        """
        source = (_E2_SCRIPTS / "detector/engines/regex/detect-text.mjs").read_text(encoding="utf-8")
        self.assertIn("runPageStructureAnalyzers(content, filePath, options)", source)
        html_path = (_E2_SCRIPTS / "detector/engines/static-html/detect-html.mjs").read_text(encoding="utf-8")
        self.assertIn("runPageStructureAnalyzers(html, filePath, options)", html_path)


@unittest.skipIf(_NODE is None, "node 부재 — 레지스트리 검사 생략")
class TestDetectorRegistry(unittest.TestCase):
    def test_new_rules_are_registered_with_a_fix(self):
        rules = _registry()
        for rule_id in ("inert-transition", "placeholder-link"):
            self.assertIn(rule_id, rules, f"{rule_id} 이 레지스트리에 없다")
            entry = rules[rule_id]
            self.assertTrue(entry.get("name"), f"{rule_id} 에 이름이 없다")
            # 무엇을 고치라는 말이 없으면 발견은 잔소리로 끝난다.
            self.assertIn("Either drive the custom property", rules["inert-transition"]["description"])
            self.assertIn("Point each link at its destination", rules["placeholder-link"]["description"])

    def test_new_rules_are_not_advisory(self):
        """권고로 내리면 설계 훅이 건너뛴다 — 이 둘은 실패로 세야 한다."""
        rules = _registry()
        for rule_id in ("inert-transition", "placeholder-link"):
            self.assertFalse(rules[rule_id].get("advisory"), f"{rule_id} 이 권고로 내려갔다")


class TestContractsNameTheThreeChecks(unittest.TestCase):
    """다섯 상태는 기계 판정이 안 된다 — 대신 두 엔진이 이름을 대게 만든다."""

    def test_engine2_craft_floor_demands_delivery(self):
        floor = (_E2 / "reference/craft-floor.md").read_text(encoding="utf-8")
        self.assertIn("Deliver, don't declare", floor)
        self.assertIn("inert-transition", floor)
        self.assertIn("placeholder-link", floor)
        self.assertIn("a state nobody mentioned is a state nobody built", floor)

    def test_engine1_contract_demands_delivery(self):
        skill = _E1_SKILL.read_text(encoding="utf-8")
        for phrase in ("Motion runs.", "Controls resolve.", "The five states exist."):
            self.assertIn(phrase, skill, f"엔진1 계약이 '{phrase}' 를 요구하지 않는다")
        self.assertIn("silence on one counts as skipped", skill)

    def test_engine1_contract_names_self_report_for_what_it_is(self):
        """자기 채점을 리뷰로 제출한 실측 실패를 계약에 못박는다."""
        skill = _E1_SKILL.read_text(encoding="utf-8")
        self.assertIn("self-report", skill)
        self.assertIn("vanadis-final-qa", skill)


if __name__ == "__main__":
    unittest.main()
