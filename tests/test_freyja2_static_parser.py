"""엔진2 정적 HTML 검출기가 배포 형태에서 실제로 돈다 — 무음 폴백 회귀 가드.

원본(impeccable) 대조 검증(2026-07-25)에서 잡은 격차다. `detect-html.mjs`는
htmlparser2·css-select·css-tree·domutils를 bare import 하고, 하나라도 실패하면
`catch`에서 조용히 정규식 경로로 되돌아간다. 상류는 그 넷을 npm 패키지 의존성으로
받지만 Asgard는 엔진을 파이썬 패키지 자산으로 실어 옆에 node_modules가 없다.
결과는 경고 한 줄 없는 반쪽 검출기였다 — 상류 픽스처 55개 기준 findings 291→135,
구별 규칙 40→15. low-contrast·cramped-padding·tiny-text·oversized-h1 등 26종이
한 번도 발화하지 않았다.

봉합은 `vendor/static-parser.mjs`(그 넷의 번들)이고, 이 파일은 그것이 살아 있는지를
소스 존재가 아니라 *실측 발견*으로 확인한다. 번들이 사라지거나 깨지면 아래 probe의
low-contrast가 사라진다 — 캐스케이드를 실제로 풀어야만 나오는 발견이기 때문이다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ENGINE = _REPO / "src/asgard/assets/skill_plugins/freyja2/skills/asgard-freyja2/engine"
_SCRIPTS = _ENGINE / "scripts"
_VENDOR = _SCRIPTS / "detector/vendor"
_NODE = shutil.which("node")

# 클래스 선택자로만 색이 정해진다 — 정규식은 이 문단의 실제 대비를 계산할 수 없다.
_LOW_CONTRAST = """<!DOCTYPE html><html lang="en"><head><title>Probe</title><style>
body { background: #ffffff; }
.muted { color: #c9cdd3; font-size: 15px; }
</style></head><body>
<p class="muted">흰 배경 위의 옅은 회색 본문. 대비는 캐스케이드를 풀어야만 나온다.</p>
</body></html>
"""


def _node_bin() -> str:
    assert _NODE is not None
    return _NODE


def _detect(html: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "index.html"
        page.write_text(html, encoding="utf-8")
        proc = subprocess.run(
            [_node_bin(), str(_SCRIPTS / "detect.mjs"), "--json", "--no-config", str(page)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        # detect는 발견이 있으면 2, 없으면 0으로 끝난다. 그 밖은 진짜 실패다.
        if proc.returncode not in (0, 2):
            raise AssertionError(f"detect 실패 rc={proc.returncode}: {proc.stderr[:400]}")
        return [f.get("antipattern") for f in json.loads(proc.stdout or "[]")]


class TestVendoredParserIsPresent(unittest.TestCase):
    def test_bundle_and_attribution_ship(self):
        self.assertTrue((_VENDOR / "static-parser.mjs").is_file(), "정적 파서 번들이 없다")
        self.assertTrue((_VENDOR / "LICENSES.md").is_file(), "번들 저작권 고지가 없다")
        self.assertTrue((_VENDOR / "rebuild.sh").is_file(), "번들 재생성 레시피가 없다")

    def test_fallback_is_wired_after_the_bare_specifiers(self):
        """실제 설치가 있으면 그쪽이 이긴다 — 번들은 어디까지나 폴백이다."""
        source = (_SCRIPTS / "detector/engines/static-html/detect-html.mjs").read_text(encoding="utf-8")
        self.assertIn("import('htmlparser2')", source, "상류 bare import 경로가 사라졌다")
        self.assertLess(
            source.index("import('htmlparser2')"),
            source.index("vendor/static-parser.mjs"),
            "번들이 bare 지정자보다 먼저 시도된다 — 실제 설치를 가린다",
        )


@unittest.skipIf(_NODE is None, "node 부재 — 검출기 실행 검사 생략")
class TestStaticEngineRunsAsShipped(unittest.TestCase):
    def test_cascade_rule_fires_without_node_modules(self):
        """정적 경로에서만 나오는 발견이 배포 트리 그대로 나온다."""
        self.assertIn(
            "low-contrast",
            _detect(_LOW_CONTRAST),
            "정적 HTML 엔진이 돌지 않았다 — vendor/static-parser.mjs 가 깨졌거나 폴백 배선이 끊겼다",
        )

    def test_bundle_exports_the_four_packages(self):
        script = (
            f"import * as m from '{(_VENDOR / 'static-parser.mjs').as_posix()}';"
            "const need = ['htmlparser2','cssSelect','csstree','domutils'];"
            "process.stdout.write(JSON.stringify({"
            "missing: need.filter(k => !m[k]),"
            "parseDocument: typeof m.htmlparser2?.parseDocument,"
            "selectAll: typeof m.cssSelect?.selectAll,"
            # css-tree는 데이터(mdn-data·patch.json)가 인라인돼야 lexer가 선다.
            "csstreeParse: typeof m.csstree?.parse,"
            "csstreeLexer: typeof m.csstree?.lexer}));"
        )
        proc = subprocess.run(
            [_node_bin(), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, f"번들 로드 실패: {proc.stderr[:400]}")
        got = json.loads(proc.stdout)
        self.assertEqual(got["missing"], [], "번들에 빠진 패키지가 있다")
        self.assertEqual(got["parseDocument"], "function")
        self.assertEqual(got["selectAll"], "function")
        self.assertEqual(got["csstreeParse"], "function")
        self.assertEqual(got["csstreeLexer"], "object", "css-tree 데이터가 인라인되지 않았다")


if __name__ == "__main__":
    unittest.main()
