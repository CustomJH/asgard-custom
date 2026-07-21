#!/usr/bin/env python3
"""Purpose-routed Freyja motion/video skills and the Aceternity live catalog."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import skill_bank, skill_registry  # noqa: E402

IART_MOTION_PACKS = {
    "iart-ad-video-skills": (
        "0de0f2a1c1f42a98103fc0ec436509276428372c",
        ("ad-creative-video", "launch-video", "testimonial-video"),
    ),
    "iart-data-animation-skills": (
        "8ce2709c3992490251e8a991535b1945f01c6865",
        ("animated-infographic", "chart-animation", "presentation-video"),
    ),
    "iart-ecommerce-video-skills": (
        "2bd0dd19c9b2df5230f5d8f7453861b9681e49b4",
        ("photo-slideshow", "product-demo-video", "promo-video"),
    ),
    "iart-explainer-video-skills": (
        "3e2d411b725d9a72939cf8e5eb81579e751373e7",
        ("diagram-animation", "explainer-video", "isometric-animation", "whiteboard-animation", "wrapped-video"),
    ),
    "iart-freelance-motion-skills": (
        "d85c2b484693d0387333c778d9c95230fa1856ce",
        ("brand-motion-guidelines", "client-revisions", "creative-brief", "motion-pricing", "video-delivery-specs"),
    ),
    "iart-generative-illustration-skills": (
        "e7d62437c875fc8ad5eff6e90fe0e25b30e43933",
        ("generative-illustration",),
    ),
    "iart-kinetic-typography-skills": (
        "fccc94bd325d824235ee9e715e65abde57b6513a",
        ("kinetic-typography",),
    ),
    "iart-manim-skills": ("a15833c44de5108a3ee68f178a1fca126aa7c6d8", ("manim",)),
    "iart-map-animation-skills": ("390ca98bbcf2ea88a430a69c0dcbf423e43d075d", ("map-animation",)),
    "iart-motion-design-skills": (
        "3c129f769d90a1328c209c386492333c9ac62312",
        (
            "after-effects",
            "animation-principles",
            "beat-sync-editing",
            "color-motion",
            "logo-animation",
            "motion-art-direction",
            "motion-background",
            "remotion-video",
            "shot-composition",
        ),
    ),
    "iart-text-message-video-skills": (
        "3a800e1e9b9635fa196a07b0143c80f7e9648558",
        ("text-message-animation",),
    ),
    "iart-tiktok-video-skills": (
        "2a775336b5a638cbf8a61dbd785f9a1b649be016",
        ("caption-animation", "countdown-video", "lower-thirds", "short-form-video"),
    ),
    "iart-web-animation-skills": (
        "b6dba3eb759726845a44163ff0bad70dd9e7fbb6",
        (
            "60fps-animation",
            "accessible-animation",
            "ascii-animation",
            "glassmorphism",
            "gsap-web",
            "lottie-animation",
            "micro-interaction",
            "page-transition-animation",
            "svg-animation",
        ),
    ),
    "iart-webgl-animation-skills": (
        "50697d659fbf70152f48f9f8aadf1efe78bbdde1",
        ("particle-system", "shader-glsl", "threejs-animation"),
    ),
    "iart-youtube-video-skills": (
        "f3df381d65abe5078f5ed410bbc3ed72e7cb92bd",
        ("audiogram", "youtube-intro-outro"),
    ),
}


class MotionSkillStackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(self.tmp.name, "home")
        skill_bank._cache.clear()

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        skill_bank._cache.clear()
        self.tmp.cleanup()

    def test_animate_uses_asgard_design_prerequisite_chain(self):
        from asgard.templates.freyja import FREYJA_SKILLS, resolve_freyja_skills

        motion = dict(FREYJA_SKILLS)["asgard-freyja-motion"]
        for anchor in (
            "외부 `animate` 선행 스킬 호환 계약",
            "asgard skills show asgard-freyja-brisingamen",
            "asgard skills show asgard-freyja-hnoss",
            "asgard skills show asgard-freyja-syn",
            "/frontend-design",
            "/teach-impeccable",
        ):
            self.assertIn(anchor, motion)

        resolved = dict(resolve_freyja_skills("animate this landing page"))
        self.assertIn("asgard-freyja-motion", resolved)
        self.assertIn("asgard-freyja-hnoss", resolved)
        self.assertIn("asgard-freyja-brisingamen", resolved["asgard-freyja-deferred"])

    def test_video_and_web_tasks_compose_only_freyja_skills(self):
        video = {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "제품 설명 영상 제작", "freyja")}
        self.assertIn("asgard-freyja-video", video)
        self.assertIn("explainer-video", video)

        data_video = {
            name for name, _ in skill_registry.resolve_skills(self.tmp.name, "CSV 차트 데이터 영상 제작", "freyja")
        }
        self.assertIn("asgard-freyja-video", data_video)
        self.assertIn("chart-animation", data_video)

        web = {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "Lottie 마이크로인터랙션", "freyja")}
        self.assertIn("asgard-freyja-motion", web)
        self.assertIn("lottie-animation", web)
        self.assertIn("micro-interaction", web)
        self.assertNotIn(
            "explainer-video",
            {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "제품 설명 영상 제작", "worker")},
        )

        available = {row["name"] for row in skill_registry.available_skills(self.tmp.name, "freyja")}
        for name in ("chart-animation", "kinetic-typography", "lottie-animation", "aceternity-ui", "21st-cli-use"):
            self.assertIn(name, available)
        self.assertIn(
            "@lottiefiles/dotlottie-web",
            skill_registry.show_skill_resource(
                self.tmp.name, "lottie-animation", "references/integration-and-export.md"
            ),
        )

        from asgard.agent.heimdall import _skill_support

        note, tools, handlers = _skill_support("freyja", self.tmp.name)
        self.assertIn("explainer-video", note)
        self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
        self.assertIn("The pipeline", handlers["load_skill"]({"name": "explainer-video"}))

    def test_all_51_iart_motion_skills_are_bundled_available_and_routable(self):
        plugins = skill_registry.bundled_plugins()
        expected_skills = {skill for _, skills in IART_MOTION_PACKS.values() for skill in skills}
        self.assertEqual(len(IART_MOTION_PACKS), 15)
        self.assertEqual(len(expected_skills), 51)

        for plugin_name, (revision, skills) in IART_MOTION_PACKS.items():
            with self.subTest(plugin=plugin_name):
                plugin = plugins[plugin_name]
                self.assertEqual(plugin["revision"], revision)
                self.assertEqual(plugin["license"], "MIT")
                self.assertEqual(tuple(plugin["skills"]), skills)
                self.assertEqual(plugin["source"], f"https://github.com/iart-ai/{plugin_name.removeprefix('iart-')}")
            for skill in skills:
                route = plugin["routing"][skill]
                with self.subTest(skill=skill):
                    self.assertEqual(route["agents"], ["freyja", "freyja-lead"])
                    with mock.patch.object(skill_registry, "bundled_plugins", return_value={plugin_name: plugin}):
                        resolved = {
                            name
                            for name, _ in skill_registry.resolve_skills(
                                self.tmp.name, route["triggers"][0], "freyja", include_learned=False
                            )
                        }
                    self.assertIn(skill, resolved)

        available = {row["name"] for row in skill_registry.available_skills(self.tmp.name, "freyja")}
        worker = {row["name"] for row in skill_registry.available_skills(self.tmp.name, "worker")}
        self.assertLessEqual(expected_skills, available)
        self.assertTrue(expected_skills.isdisjoint(worker))

        self.assertIn(
            "ValueTracker",
            skill_registry.load_skill_for_agent(self.tmp.name, "freyja", "manim", "references/graphs-and-updaters.md"),
        )
        self.assertIn(
            "ShaderMaterial",
            skill_registry.load_skill_for_agent(self.tmp.name, "freyja", "shader-glsl", "references/glsl-cookbook.md"),
        )
        self.assertIn(
            "app.project",
            skill_registry.load_skill_for_agent(self.tmp.name, "freyja", "after-effects", "scripts/batch-rename.jsx"),
        )

    def test_new_motion_domains_compose_with_freyja_core_contracts(self):
        cases = {
            "틱톡 숏폼 영상": ("asgard-freyja-video", "short-form-video"),
            "팟캐스트 오디오그램": ("asgard-freyja-video", "audiogram"),
            "제품 데모 영상": ("asgard-freyja-video", "product-demo-video"),
            "광고 모션그래픽 A/B 테스트": ("asgard-freyja-video", "ad-creative-video"),
            "수학 애니메이션": ("asgard-freyja-video", "manim"),
            "Three.js 파티클 시스템": ("asgard-freyja-folkvangr", "particle-system", "threejs-animation"),
            "3D 로고 시스템 interactive showcase": (
                "asgard-freyja-logo-studio",
                "asgard-freyja-folkvangr",
                "brand",
                "threejs-animation",
                "threejs-skills",
            ),
            "모션 견적 작성": ("motion-pricing",),
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                resolved = {name for name, _ in skill_registry.resolve_skills(self.tmp.name, task, "freyja")}
                self.assertLessEqual(set(expected), resolved)

    def test_aceternity_parser_keeps_only_live_free_components(self):
        hits = {
            name
            for name, _ in skill_registry.resolve_skills(
                self.tmp.name, "Next.js 인터랙티브 히어로에 비교 슬라이더를 넣어줘", "freyja"
            )
        }
        self.assertIn("aceternity-ui", hits)

        plugin = skill_registry.bundled_plugins()["aceternity-ui"]
        script = Path(plugin["root"], "skills", "aceternity-ui", "scripts", "aceternity.py")
        spec = importlib.util.spec_from_file_location("aceternity_skill", script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        old_dont_write_bytecode = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = old_dont_write_bytecode

        rows = [
            {
                "name": "compare",
                "title": "Compare",
                "description": "Interactive comparison slider",
                "categories": ["slider"],
                "dependencies": ["motion"],
                "installCommand": "npx shadcn@latest add @aceternity/compare",
                "documentationUrl": "https://ui.aceternity.com/components/compare",
                "isPro": False,
                "isTemplate": False,
            },
            {
                "name": "paid-block",
                "installCommand": "npx shadcn@latest add @aceternity/paid-block",
                "isPro": True,
            },
        ]
        page = f"<html><pre>{json.dumps(rows).replace('&', '&amp;')}</pre></html>".encode()
        response = io.BytesIO(page)
        with mock.patch.object(module.urllib.request, "urlopen", return_value=response):
            catalog = module._catalog()
        self.assertEqual([row["name"] for row in catalog], ["compare"])
        self.assertEqual(module._search(catalog, "comparison slider", 8)[0]["name"], "compare")

    def test_21st_cli_is_freyja_only_and_uses_the_pinned_official_cli(self):
        hits = {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "21st 컴포넌트 검색", "freyja")}
        self.assertIn("21st-cli-use", hits)
        natural = {
            name
            for name, _ in skill_registry.resolve_skills(
                self.tmp.name, "React로 재사용 가능한 프라이싱 컴포넌트를 만들어줘", "freyja"
            )
        }
        self.assertIn("21st-cli-use", natural)
        self.assertNotIn(
            "21st-cli-use",
            {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "기존 버튼 패딩 수정", "freyja")},
        )
        self.assertNotIn(
            "21st-cli-use",
            {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "21st 컴포넌트 검색", "worker")},
        )
        with mock.patch("asgard.skill_registry.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertEqual(skill_registry.run_skill(self.tmp.name, "21st-cli-use", ["search", "pricing"]), 0)
        self.assertTrue(run.call_args.args[0][1].endswith("scripts/21st.py"))

        plugin = skill_registry.bundled_plugins()["21st-dev"]
        script = Path(plugin["root"], "skills", "21st-cli-use", "scripts", "21st.py")
        spec = importlib.util.spec_from_file_location("twenty_first_skill", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        old_dont_write_bytecode = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = old_dont_write_bytecode
        with mock.patch.object(module.subprocess, "run") as cli:
            cli.return_value.returncode = 0
            self.assertEqual(module.main(["search", "pricing"]), 0)
        self.assertEqual(cli.call_args.args[0], ["npx", "-y", "@21st-dev/cli@1.7.2", "search", "pricing"])

    def test_specialist_intent_routes_to_one_exact_motion_skill(self):
        cases = {
            "이 효과 이름이 뭐라고 부르는지 모션 용어 알려줘": "animation-vocabulary",
            "애플 디자인 제스처 UI와 스프링 애니메이션": "apple-design",
            "기존 화면 어디에 애니메이션을 넣을지 찾아줘": "find-animation-opportunities",
            "전체 앱 모션 감사와 개선 로드맵": "improve-animations",
            "이 애니메이션 diff를 검토해줘": "review-animations",
            "터미널 ASCII 애니메이션": "ascii-animation",
            "리퀴드 글래스 UI": "glassmorphism",
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                self.assertIn(
                    expected, {name for name, _ in skill_registry.resolve_skills(self.tmp.name, task, "freyja")}
                )


if __name__ == "__main__":
    unittest.main()
