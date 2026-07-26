"""Freyja 4 엔진(마르될) — 계약과 결정론 게이트 런타임.

이 엔진의 값어치는 "화면을 소스에서 판정한다"에 있으므로, 테스트도 문서 문자열이 아니라
실제 HTML/CSS 를 검사기에 물려 판정이 맞는지 본다. 특히 네 가지를 고정한다.
① 활자 화살표(→ ↳)를 이모지로 세지 않는다.
② CSS 가 font-style: normal 로 되돌린 <em> 을 기울임 헤딩으로 세지 않는다.
③ oklch() 값은 공백을 품으므로 색 추출이 조용히 실패해선 안 된다 — 대비 게이트가 실제로 돈다.
④ 기계가 판정 못 한 게이트는 절대 pass 로 세지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from asgard import skill_registry

_NODE = shutil.which("node")
_PLUGIN = Path(skill_registry.__file__).parent / "assets" / "skill_plugins" / "freyja4"
_SKILL = _PLUGIN / "skills" / "asgard-freyja4"
_REFS = _SKILL / "references"
_GATE = _SKILL / "engine" / "scripts" / "slop_gate.mjs"

# 판정 가능한 모든 게이트를 통과하도록 만든 기준 산출물. 이 픽스처가 깨지면
# 게이트 집합이 서로 모순됐다는 뜻이다(= 어떤 페이지도 통과할 수 없다).
CLEAN_CSS = """\
/* Freyja4 · macrostructure: Workbench · tone: technical · anchor hue: 200 */
:root {
  --color-paper: oklch(96% 0.008 250);
  --color-paper-2: oklch(92% 0.010 250);
  --color-ink: oklch(24% 0.020 250);
  --color-muted: oklch(52% 0.014 250);
  --color-accent: oklch(48% 0.140 250);
  --color-accent-ink: oklch(98% 0.008 250);
  --color-rule: oklch(84% 0.010 250);
  --font-display: "Fraunces", Georgia, serif;
  --font-body: "Source Sans 3", Verdana, sans-serif;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 32px;
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --dur-short: 140ms;
}
html, body { overflow-x: clip; }
body {
  background: var(--color-paper);
  color: var(--color-ink);
  font-family: var(--font-body);
  margin: 0;
}
.masthead { position: sticky; top: 0; background: var(--color-paper); }
.hero__title {
  font-family: var(--font-display);
  font-size: 3.5rem;
  line-height: 1.05;
  overflow-wrap: anywhere;
  min-width: 0;
  margin: 0;
}
.section__head { display: flex; flex-direction: column; gap: var(--space-sm); }
.btn {
  background: var(--color-accent);
  color: var(--color-accent-ink);
  border: 1px solid var(--color-accent);
  padding: var(--space-sm) var(--space-md);
  font-family: var(--font-body);
  transition: transform var(--dur-short) var(--ease-out);
}
.btn:hover { background: var(--color-ink); border-color: var(--color-ink); }
.btn:active { transform: translateY(1px); }
.btn:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.spec { color: var(--color-muted); background: var(--color-paper); }
@media (prefers-reduced-motion: reduce) {
  .btn { transition: none; }
}
"""

CLEAN_HTML = """\
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><link rel="stylesheet" href="style.css"></head>
  <body>
    <header class="masthead"><a href="/specs">Specifications</a></header>
    <main>
      <div class="section__head">
        <p class="eyebrow">Detent</p>
        <h1 class="hero__title">A switch you can measure</h1>
      </div>
      <p class="spec">Travel and force are stated from the model, not from a brochure.</p>
      <button class="btn" type="button">Reserve one</button>
      <svg aria-hidden="true" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3"></circle></svg>
    </main>
  </body>
</html>
"""


def _write(root: Path, css: str = CLEAN_CSS, html: str = CLEAN_HTML) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "style.css").write_text(css, encoding="utf-8")
    (root / "index.html").write_text(html, encoding="utf-8")
    return root


def _gate(target: Path, *args: str, cwd: Path | None = None) -> tuple[dict, int]:
    proc = subprocess.run(  # noqa: S603
        [str(_NODE), str(_GATE), str(target), "--json", *args],
        cwd=str(cwd or target),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if not proc.stdout.strip():
        raise AssertionError(f"slop_gate produced no output: {proc.stderr}")
    return json.loads(proc.stdout), proc.returncode


def _by_id(payload: dict, gate_id) -> dict:
    for gate in payload["gates"]:
        if str(gate["id"]) == str(gate_id):
            return gate
    raise AssertionError(f"gate {gate_id} not reported")


class Freyja4Contract(unittest.TestCase):
    """엔진이 스킬 레지스트리에 실제로 실려 있고, 규칙 코퍼스가 온전한가."""

    def test_plugin_is_discovered_and_named(self) -> None:
        plugins = skill_registry.bundled_plugins()
        self.assertIn("freyja4", plugins, "freyja4 플러그인이 번들 목록에 없다")
        manifest = plugins["freyja4"]
        self.assertEqual(manifest["skills"], ["asgard-freyja4"])
        routing = manifest["routing"]["asgard-freyja4"]
        self.assertIn("freyja", routing["defaults"])
        for trigger in ("freyja4", "엔진4", "4번엔진"):
            self.assertIn(trigger, routing["triggers"], f"트리거 누락: {trigger}")

    def test_rule_corpus_is_complete(self) -> None:
        """상류 참조를 한 개도 빼지 않고 옮겼는가 — 개수와 필수 축을 같이 본다."""
        refs = [p for p in _REFS.rglob("*.md") if p.is_file()]
        self.assertGreaterEqual(len(refs), 100, "참조 문서가 100개 미만 — 이식 중 누락")
        self.assertEqual(len(list((_REFS / "macrostructures").glob("*.md"))), 21)
        self.assertEqual(len(list((_REFS / "genres").glob("*.md"))), 4)
        self.assertGreaterEqual(len(list((_REFS / "components").glob("*.md"))), 50)
        self.assertTrue((_REFS / "slop-test.md").is_file())
        self.assertTrue((_REFS / "tokens.css").is_file(), "20테마 토큰 정본이 없으면 로테이션 규칙이 죽는다")

    def test_theme_catalog_is_intact(self) -> None:
        tokens = (_REFS / "tokens.css").read_text(encoding="utf-8")
        for theme in ("specimen", "brutal", "newsprint", "terminal", "midnight", "hum", "lumen", "cobalt"):
            self.assertIn(f'[data-theme="{theme}"]', tokens, f"테마 블록 누락: {theme}")

    def test_internal_links_resolve(self) -> None:
        """SKILL.md 와 참조가 가리키는 상대 경로가 실제로 존재하는가.

        예외 1건은 상류에도 똑같이 깨져 있다(`site/_tests/verbs/refine/` 은 원본에 없다).
        이식본은 원본과 같게 동작하는 것이 목적이므로 고치지 않고 여기 이름으로 남긴다 —
        새로 생기는 파손은 그대로 잡힌다.
        """
        import re

        known_upstream_breakage = {"references/examples/verbs/redesign/notes.md -> ../refine/"}
        broken: list[str] = []
        for doc in [_SKILL / "SKILL.md", *_REFS.rglob("*.md")]:
            text = doc.read_text(encoding="utf-8")
            for target in re.findall(r"\]\((?!https?:|#|mailto:)([^)#]+)", text):
                candidate = (doc.parent / target.strip()).resolve()
                if candidate.exists():
                    continue
                entry = f"{doc.relative_to(_SKILL)} -> {target}"
                if entry not in known_upstream_breakage:
                    broken.append(entry)
        self.assertEqual(broken, [], f"끊긴 내부 링크: {broken[:8]}")

    def test_surface_carries_no_upstream_product_name(self) -> None:
        """프롬프트 표면에서는 상류 제품명을 쓰지 않는다. 예외는 주석 달린 외부 자산 호스트뿐."""
        hits: list[str] = []
        for doc in [_SKILL / "SKILL.md", *_REFS.rglob("*.md")]:
            for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                if "hallmark" in line.lower() and "usehallmark.com" not in line:
                    hits.append(f"{doc.name}:{i}")
        self.assertEqual(hits, [], f"상류 제품명 잔존: {hits[:8]}")

    def test_upstream_license_is_reproduced(self) -> None:
        notice = (_PLUGIN / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("MIT License", notice)
        self.assertIn("Copyright (c)", notice)
        self.assertIn("WITHOUT WARRANTY OF ANY KIND", notice)

    def test_skill_states_the_asgard_contract(self) -> None:
        skill = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
        for clause in (
            ".asgard/.vanadis/engine4/",  # 금고
            "Self-scoring is not a review",  # 자기채점 금지
            "slop_gate.mjs",  # 결정론 런타임 배선
            "unverified",  # 침묵은 통과가 아니다
        ):
            self.assertIn(clause, skill, f"계약 조항 누락: {clause}")


@unittest.skipIf(_NODE is None, "node 없음")
class SlopGateRuntime(unittest.TestCase):
    """검사기가 실제 지오메트리 대신 실제 마크업을 물고 판정하는지 본다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_clean_page_passes_every_judged_gate(self) -> None:
        """게이트 집합이 서로 모순되지 않는다 — 통과 가능한 산출물이 실제로 존재한다."""
        target = _write(self.root / "clean")
        payload, code = _gate(target)
        failing = [g["id"] for g in payload["gates"] if g["status"] == "fail"]
        self.assertEqual(failing, [], f"기준 산출물이 떨어졌다: {failing}")
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "pass")

    def test_unjudged_gates_are_never_counted_as_passes(self) -> None:
        target = _write(self.root / "manual")
        payload, _ = _gate(target)
        judged = {str(g["id"]) for g in payload["gates"]}
        manual = {str(m["id"]) for m in payload["manual"]}
        self.assertTrue(manual, "판정 못 한 게이트 목록이 비어 있다 — 침묵 통과")
        self.assertEqual(judged & manual, set(), "같은 게이트를 판정과 미판정 양쪽에 넣었다")
        self.assertEqual(payload["summary"]["manual"], len(manual))

    def test_ink_on_ink_button_is_caught(self) -> None:
        css = CLEAN_CSS.replace(
            "  color: var(--color-accent-ink);",
            "  color: var(--color-accent);",
        )
        target = _write(self.root / "inkoninK", css=css)
        payload, code = _gate(target)
        gate = _by_id(payload, 41)
        self.assertEqual(gate["status"], "fail")
        self.assertTrue(any("text ≈ fill" in f for f in gate["findings"]), gate["findings"])
        self.assertEqual(code, 1)

    def test_oklch_contrast_actually_computes(self) -> None:
        """oklch() 는 공백을 품는다. 색 추출이 조용히 실패하면 대비 게이트는 아무 일도 안 하고 pass 한다."""
        css = CLEAN_CSS.replace(
            "--color-muted: oklch(52% 0.014 250);",
            "--color-muted: oklch(90% 0.014 250);",  # 종이 위 90% — 본문 대비 미달
        )
        target = _write(self.root / "faint", css=css)
        payload, _ = _gate(target)
        gate = _by_id(payload, 41)
        self.assertEqual(gate["status"], "fail", "옅은 본문색이 통과했다 — 색 추출이 죽어 있다")
        self.assertTrue(any(":1 (needs 4.5:1" in f for f in gate["findings"]), gate["findings"])

    def test_contrast_threshold_follows_the_text_size(self) -> None:
        """oklch(60% 0.09 250) 은 이 종이 위에서 3.49:1 — 큰 활자엔 되고 본문엔 안 된다.

        임계값을 하나로 뭉개면 둘 중 하나는 반드시 틀린다. 같은 색을 두 크기에 물려
        경계가 실제로 갈리는지 본다.
        """
        borderline = "--color-borderline: oklch(60% 0.09 250);"
        base = CLEAN_CSS.replace("  --color-rule:", f"  {borderline}\n  --color-rule:")

        large = base.replace(
            "  font-size: 3.5rem;",
            "  font-size: 3.5rem;\n  color: var(--color-borderline);\n  background: var(--color-paper);",
        )
        gate_large = _by_id(_gate(_write(self.root / "large", css=large))[0], 41)
        self.assertEqual(
            gate_large["status"], "pass", f"3.49:1 인 3.5rem 디스플레이가 떨어졌다: {gate_large['findings']}"
        )

        body = base.replace(
            ".spec { color: var(--color-muted); background: var(--color-paper); }",
            ".spec { font-size: 1rem; color: var(--color-borderline); background: var(--color-paper); }",
        )
        gate_body = _by_id(_gate(_write(self.root / "body", css=body))[0], 41)
        self.assertEqual(
            gate_body["status"], "fail", "같은 3.49:1 이 본문 크기에서도 통과했다 — 임계값이 하나로 뭉개졌다"
        )
        self.assertTrue(any("needs 4.5:1" in f for f in gate_body["findings"]), gate_body["findings"])

    def test_state_variants_are_the_same_element(self) -> None:
        """`:hover` / `:active` / `[open]` 은 같은 원소의 다른 상태다.

        이걸 별개 규칙으로 읽으면 소스 전용 판정기의 오탐이 폭증한다. 실측된 네 갈래를
        한 번에 물린다 — 상속 색, 상속 wrap, 축약형 프로퍼티, 상태 선택자 경유 구동.
        """
        css = CLEAN_CSS.replace(
            ".btn:disabled { opacity: 0.55; cursor: not-allowed; }",
            # 1. :active 는 background 만 바꾸고 color 는 기본 규칙에서 상속한다.
            ".btn:active { background: var(--color-accent); }\n"
            # 2. :disabled 의 색을 :active 가 물려받은 것으로 착각하면 안 된다.
            ".btn:disabled { opacity: 0.55; cursor: not-allowed; color: var(--color-muted); }\n"
            # 3. border-bottom-color 는 border-color 트랜지션을 구동한다.
            ".tab { border-bottom: 1px solid var(--color-rule); "
            "transition: border-color 120ms var(--ease-out); }\n"
            ".tab:hover { border-bottom-color: var(--color-accent); }\n"
            # 4. 미디어쿼리 안의 크기 재선언은 기본 규칙의 wrap 을 물려받는다.
            "@media (max-width: 30rem) { .hero__title { font-size: 2rem; } }\n",
        )
        html = CLEAN_HTML.replace("</main>", '  <a class="tab" href="/x">Tab</a>\n    </main>')
        payload, code = _gate(_write(self.root / "states", css=css, html=html))
        for gate_id, why in (
            (41, "상태 규칙이 기본 색을 상속한다"),
            (51, "미디어 재선언이 기본 wrap 을 상속한다"),
            ("A1", "축약형·상태 선택자가 모션을 구동한다"),
        ):
            gate = _by_id(payload, gate_id)
            self.assertEqual(gate["status"], "pass", f"게이트 {gate_id} 오탐 ({why}): {gate['findings']}")
        self.assertEqual(code, 0)

    def test_ua_driven_discrete_property_is_not_dead_motion(self) -> None:
        """content-visibility 는 저자 선언이 아니라 UA 가 뒤집는다 — allow-discrete 가 그 증거다."""
        css = CLEAN_CSS + (
            "\ndetails::details-content { block-size: 0; overflow: hidden;"
            " transition: block-size 200ms var(--ease-out), content-visibility 200ms allow-discrete; }\n"
            "details[open]::details-content { block-size: auto; }\n"
        )
        html = CLEAN_HTML.replace("</main>", "  <details><summary>Q</summary><p>A</p></details>\n    </main>")
        gate = _by_id(_gate(_write(self.root / "discrete", css=css, html=html))[0], "A1")
        self.assertEqual(gate["status"], "pass", gate["findings"])

    def test_typographic_arrows_are_not_emoji(self) -> None:
        """→ 와 ↳ 는 활자다. 이걸 이모지로 세면 정상 버튼이 전부 떨어진다."""
        html = CLEAN_HTML.replace(
            ">Reserve one<",
            '>Reserve one <span aria-hidden="true">→</span><',
        )
        target = _write(self.root / "arrows", html=html)
        payload, _ = _gate(target)
        self.assertEqual(_by_id(payload, 30)["status"], "pass")

    def test_actual_emoji_glyph_is_caught(self) -> None:
        html = CLEAN_HTML.replace(">Reserve one<", ">\N{ROCKET} Reserve one<")
        target = _write(self.root / "emoji", html=html)
        payload, _ = _gate(target)
        self.assertEqual(_by_id(payload, 30)["status"], "fail")

    def test_em_reset_to_roman_is_not_an_italic_header(self) -> None:
        """CSS 가 기울임을 끄고 강조를 색으로 옮긴 것은 규칙이 권하는 처방이지 결함이 아니다."""
        css = CLEAN_CSS + "\n.hero__title em { font-style: normal; color: var(--color-accent); }\n"
        html = CLEAN_HTML.replace(
            "A switch you can measure",
            "A switch you can <em>measure</em>",
        )
        target = _write(self.root / "romanem", css=css, html=html)
        payload, _ = _gate(target)
        gate = _by_id(payload, "38a")
        self.assertEqual(gate["status"], "pass", gate["findings"])
        self.assertTrue(gate["notes"], "되돌림 사실을 근거로 남기지 않았다")

    def test_italic_emphasis_in_heading_is_caught(self) -> None:
        html = CLEAN_HTML.replace(
            "A switch you can measure",
            "A switch you can <em>measure</em>",
        )
        target = _write(self.root / "italicem", html=html)
        self.assertEqual(_by_id(_gate(target)[0], "38a")["status"], "fail")

    def test_decorative_accent_fill_is_not_an_unreadable_surface(self) -> None:
        """글자가 없는 장식 면에는 판정할 잉크가 없다."""
        css = CLEAN_CSS + "\n.rule { background: var(--color-accent); height: 4px; }\n"
        html = CLEAN_HTML.replace("</main>", '  <div class="rule"></div>\n    </main>')
        target = _write(self.root / "decor", css=css, html=html)
        self.assertEqual(_by_id(_gate(target)[0], 41)["status"], "pass")

    def test_root_overflow_must_be_clip_not_hidden(self) -> None:
        css = CLEAN_CSS.replace("html, body { overflow-x: clip; }", "html, body { overflow-x: hidden; }")
        target = _write(self.root / "hidden", css=css)
        gate = _by_id(_gate(target)[0], 34)
        self.assertEqual(gate["status"], "fail")
        self.assertTrue(any("clip" in f for f in gate["findings"]))

    def test_token_improvisation_is_caught(self) -> None:
        css = CLEAN_CSS + "\n.spec strong { color: #b4531f; }\n"
        target = _write(self.root / "improv", css=css)
        gate = _by_id(_gate(target)[0], 48)
        self.assertEqual(gate["status"], "fail")
        self.assertTrue(any("#b4531f" in f for f in gate["findings"]))

    def test_eyebrow_beside_heading_is_caught(self) -> None:
        css = CLEAN_CSS.replace(
            ".section__head { display: flex; flex-direction: column; gap: var(--space-sm); }",
            ".section__head { display: grid; grid-template-columns: minmax(0, 0.4fr) minmax(0, 1fr); }",
        )
        target = _write(self.root / "eyebrow", css=css)
        gate = _by_id(_gate(target)[0], 54)
        self.assertEqual(gate["status"], "fail", "탭-왼쪽/헤딩-오른쪽 패턴을 놓쳤다")

    def test_dead_motion_is_caught(self) -> None:
        css = CLEAN_CSS.replace(".btn:active { transform: translateY(1px); }", "")
        target = _write(self.root / "deadmotion", css=css)
        gate = _by_id(_gate(target)[0], "A1")
        self.assertEqual(gate["status"], "fail")
        self.assertTrue(any("transform" in f for f in gate["findings"]))

    def test_placeholder_link_is_caught(self) -> None:
        html = CLEAN_HTML.replace('href="/specs"', 'href="#"')
        target = _write(self.root / "deadlink", html=html)
        self.assertEqual(_by_id(_gate(target)[0], "A2")["status"], "fail")

    def test_missing_stamp_is_caught(self) -> None:
        css = CLEAN_CSS.split("\n", 1)[1]
        target = _write(self.root / "nostamp", css=css)
        self.assertEqual(_by_id(_gate(target)[0], 20)["status"], "fail")

    def test_genre_override_relaxes_the_neutral_gate(self) -> None:
        css = CLEAN_CSS.replace("--color-rule: oklch(84% 0.010 250);", "--color-rule: oklch(84% 0 250);")
        target = _write(self.root / "flatgrey", css=css)
        self.assertEqual(_by_id(_gate(target)[0], 22)["status"], "fail")
        self.assertEqual(_by_id(_gate(target, "--genre", "modern-minimal")[0], 22)["status"], "n/a")

    def test_class_carried_state_is_the_same_element(self) -> None:
        """상태가 의사클래스가 아니라 클래스로 올 때도 같은 원소다 — `.chip` / `.chip.on`.

        아스가르드 맵 화면에서 실측된 오탐이다. 주어 컴파운드를 문자열로 비교하면
        클래스 하나가 붙었다는 이유로 다른 원소가 되고, 죽은 모션이 아닌 것이 죽었다고 잡힌다.
        같은 규칙이 `.zoombar button` 과 `.modebar button` 을 뭉개서도 안 된다.
        """
        css = CLEAN_CSS + (
            "\n.chip { color: var(--color-muted); transition: color var(--dur-short) var(--ease-out); }\n"
            ".chip.on { color: var(--color-ink); }\n"
            # 조상 문맥이 다른 같은 태그는 여전히 남남이다 — 이쪽은 진짜 죽은 모션이다.
            ".zoombar button { transition: border-color var(--dur-short) var(--ease-out); }\n"
            ".modebar button:hover { border-color: var(--color-accent); }\n"
        )
        html = CLEAN_HTML.replace("</main>", '  <button class="chip on" type="button">route</button>\n    </main>')
        gate = _by_id(_gate(_write(self.root / "classstate", css=css, html=html))[0], "A1")
        self.assertEqual(gate["status"], "fail", "조상 문맥이 다른 죽은 모션까지 통과시켰다")
        joined = " ".join(gate["findings"])
        self.assertNotIn(".chip transitions", joined, f"클래스 상태 변형을 오탐했다: {gate['findings']}")
        self.assertIn(".zoombar button", joined, gate["findings"])

    def test_reduced_motion_kill_switch_is_not_dead_motion(self) -> None:
        """`transition: none!important` 는 모션이 아니라 모션을 끄는 스위치다."""
        css = CLEAN_CSS.replace(
            "  .btn { transition: none; }",
            "  *, *::before, *::after { transition: none!important; animation: none!important; }",
        )
        gate = _by_id(_gate(_write(self.root / "killswitch", css=css))[0], "A1")
        self.assertEqual(gate["status"], "pass", gate["findings"])

    def test_translucent_fill_is_not_judged_as_an_opaque_surface(self) -> None:
        """8% 틴트는 그 색이 아니다 — 뒤에 깔린 것과 합성된 면이다.

        리터럴을 전강도로 읽으면 어두운 바탕의 읽히는 칩이 대비 실패로 떨어진다.
        판정을 접되 침묵하지 않는다: 몇 % 불투명인지 근거로 남긴다.
        """
        css = CLEAN_CSS + (
            "\n.tint { color: var(--color-ink);"
            " background: color-mix(in oklab, var(--color-accent) 8%, transparent); }\n"
        )
        html = CLEAN_HTML.replace("</main>", '  <p class="tint">Eight per cent</p>\n    </main>')
        gate = _by_id(_gate(_write(self.root / "tint", css=css, html=html))[0], 41)
        self.assertEqual(gate["status"], "pass", gate["findings"])
        self.assertTrue(
            any("8% opaque" in n for n in gate["notes"]),
            f"판정을 접고 근거를 남기지 않았다 (혼합 비율 오독 포함): {gate['notes']}",
        )
        # 불투명한 잉크-온-잉크는 그대로 떨어져야 한다 — 위 완화가 게이트를 무디게 만들면 안 된다.
        opaque = CLEAN_CSS + "\n.tint { color: var(--color-accent); background: var(--color-accent); }\n"
        self.assertEqual(
            _by_id(_gate(_write(self.root / "opaquetint", css=opaque, html=html))[0], 41)["status"],
            "fail",
            "틴트 예외가 진짜 잉크-온-잉크까지 통과시켰다",
        )

    def test_report_lands_in_the_vault(self) -> None:
        target = _write(self.root / "vaulted")
        cwd = self.root / "project"
        cwd.mkdir()
        _gate(target, "--report", cwd=cwd)
        vault = cwd / ".asgard" / ".vanadis" / "engine4"
        written = list(vault.glob("gate-*.json"))
        self.assertEqual(len(written), 1, f"금고에 보고서가 없다: {list(vault.rglob('*'))}")
        self.assertNotIn(".gitignore", os.listdir(vault), "금고가 제 ignore 파일을 만들었다")


if __name__ == "__main__":
    unittest.main()
