#!/usr/bin/env python3
"""번들 last30days 스킬 — 상류 스냅샷 무결성과 네 모드 도달성.

이 스킬은 앞선 벤더링 팩들과 두 가지가 다르다.

① 본문이 222KB 다. 카탈로그로 흘려보내면 어느 호스트에서든 명령 출력 상한에 잘려
   **조용히 반쪽짜리 지시**가 모델에 들어간다. ② 본문의 모든 경로가 자기 SKILL.md가
   놓인 디렉터리(`SKILL_DIR`)를 기준으로 풀린다 — 텍스트만 건네면 그 기준점이 없다.

그래서 앵커 배달을 쓴다: 트리를 `<root>/.asgard/skills/<name>/`에 풀고 **본문 대신
위치**를 넘긴다. 상류 SKILL.md는 한 바이트도 고치지 않는다("원본 그대로") — 대신 그
파일이 자기 규약대로 동작할 수 있는 자리를 만들어 준다.

가드가 지는 불변식:
- 실린 트리가 상류 스냅샷 그대로다(지문 고정) + 부분 벤더링이 아니다(import 해석).
- 배달은 위치이지 본문이 아니다 — 본문이 다시 파이프로 새면 잘림이 돌아온다.
- 푼 트리는 실린 트리와 같고, 손상되면 스스로 복구되며, 파생물이라 git에 안 섞인다.
- 네 모드(Claude Code · Cursor · Codex · 네이티브) 전부에서 닿는다.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cli_boundary import strip_ansi  # noqa: E402

from asgard import skill_registry  # noqa: E402
from asgard.templates.skill_router import direct_skill, openai_skill_metadata  # noqa: E402

_PLUGIN = "last30days-skill"
_SKILL = "last30days"
_UPSTREAM_REVISION = "0188da7ce7a216978434210eece23d79c48c821b"
# 상류 스냅샷 지문 — 벤더링 트리에 손이 닿으면(패치·부분 갱신·재포맷) 여기서 먼저 걸린다.
_TREE_DIGEST = "2d7846b965799b36dd5ca9227fe3611819710b97970187e934a83ce1cbef6db8"
_SKILL_MD_DIGEST = "1884e255fad7ec9b99f0eb39badc53adada430e389c0bff376a224b1a73b3803"
_SKILL_MD_BYTES = 222241

# `from lib import a, b, c` (엔진)와 `from .x import ...` (lib 내부) 두 형태만 정적 해석한다.
_LIB_IMPORT = re.compile(r"^from lib import (.+)$", re.M)
_REL_IMPORT = re.compile(r"^from \.(\w+) import ", re.M)


def _shipped_root() -> Path:
    return Path(skill_registry.bundled_plugins()[_PLUGIN]["root"], "skills", _SKILL)


def _digest(root: Path) -> tuple[int, str]:
    sha = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == skill_registry._ANCHOR_STAMP:
            continue
        # 바이트코드는 트리의 일부가 아니다 — 푸는 쪽도 걸러내므로 지문에서도 뺀다.
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        sha.update(path.relative_to(root).as_posix().encode())
        sha.update(b"\0")
        sha.update(path.read_bytes())
        count += 1
    return count, sha.hexdigest()


class VendoredSnapshotTest(unittest.TestCase):
    def test_tree_is_the_pinned_upstream_snapshot(self):
        plugin = skill_registry.bundled_plugins()[_PLUGIN]
        self.assertEqual(plugin["revision"], _UPSTREAM_REVISION)
        self.assertEqual(plugin["license"], "MIT")
        self.assertEqual(plugin["skills"], [_SKILL])
        self.assertEqual(plugin["anchored"], [_SKILL])

        root = _shipped_root()
        count, digest = _digest(root)
        self.assertEqual((count, digest), (118, _TREE_DIGEST))

        skill_md = root / "SKILL.md"
        self.assertEqual(skill_md.stat().st_size, _SKILL_MD_BYTES)
        self.assertEqual(hashlib.sha256(skill_md.read_bytes()).hexdigest(), _SKILL_MD_DIGEST)
        # 재배포 조건 — 상류 라이선스 원문이 팩에 함께 실려야 한다.
        self.assertIn("MIT License", Path(plugin["root"], "LICENSE").read_text(encoding="utf-8"))

    def test_runtime_the_body_names_is_actually_present(self):
        """SKILL.md가 부르는 것들이 디스크에 있어야 한다 — 없으면 실행 즉사, 그런데 조용하다."""
        root = _shipped_root()
        for relative in ("scripts/last30days.py", "references/save-html-brief.md"):
            self.assertTrue((root / relative).is_file(), relative)
        # 예제 미디어 14MB는 뺐다(본문이 한 번도 안 부른다). 뺀 것이 되살아나면 휠이 여섯 배가 된다.
        self.assertFalse((root / "assets").exists())
        self.assertIn("scripts/last30days.py", (root / "SKILL.md").read_text(encoding="utf-8"))

    def test_python_imports_resolve_inside_the_pack(self):
        """부분 벤더링 적발 — 벤더링 스크립트가 없는 이웃 모듈을 import 하면 안 된다."""
        scripts = _shipped_root() / "scripts"
        missing: list[str] = []
        scanned = 0
        for source in sorted(scripts.rglob("*.py")):
            scanned += 1
            text = source.read_text(encoding="utf-8", errors="replace")
            for group in _LIB_IMPORT.findall(text):
                for raw in group.split(","):
                    name = raw.strip().split(" as ")[0].strip()
                    if name and not _module_exists(scripts / "lib", name):
                        missing.append(f"{source.name} → lib.{name}")
            for name in _REL_IMPORT.findall(text):
                if not _module_exists(source.parent, name):
                    missing.append(f"{source.name} → .{name}")
        self.assertGreater(scanned, 0)
        self.assertEqual(missing, [], "벤더링 엔진이 실재하지 않는 모듈을 import 한다:\n" + "\n".join(missing))

    def test_engine_starts_from_the_shipped_tree(self):
        """정적 해석이 못 보는 것 — 인터프리터가 실제로 엔진을 띄우는지 한 번 확인한다."""
        proc = subprocess.run(
            [sys.executable, str(_shipped_root() / "scripts" / "last30days.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=120,
            # 설치 트리에 .pyc를 남기지 않는다 — `run_skill`과 같은 규율이고, 남기면 휠 소스가
            # 오염되는 데다 그 파일이 스냅샷 지문을 조용히 흔든다.
            # 색 없이 받는다 — Python 3.14 부터 argparse 가 help 를 ANSI 로 칠하고, 그러면
            # `usage:` 와 프로그램 이름 사이에 이스케이프가 끼어 평문 대조가 깨진다.
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1", "TERM": "dumb"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("usage: last30days.py", strip_ansi(proc.stdout))


def _module_exists(package: Path, name: str) -> bool:
    return (package / f"{name}.py").is_file() or (package / name / "__init__.py").is_file()


class AnchoredDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _anchor(self) -> Path:
        return Path(self.root, ".asgard", "skills", _SKILL)

    def test_delivery_is_a_location_not_the_body(self):
        text = skill_registry.show_skill(self.root, _SKILL) or ""
        body = skill_registry.load_skill_for_agent(self.root, "worker", _SKILL)

        # 프론트매터는 상류 것 그대로여야 설명·모델 노출 판정이 안 바뀐다.
        self.assertIn("name: last30days", text)
        self.assertIn("Research what people actually say", text)
        # 그런데 본문은 안 실려 온다 — 222KB가 파이프로 다시 새면 이 값이 폭발한다.
        self.assertLess(len(body), 2_000)
        self.assertNotIn("STEP 0: STALE-CLONE SELF-CHECK", body)
        self.assertIn(f"SKILL_DIR={self._anchor()}", body)
        self.assertIn("$SKILL_DIR/SKILL.md", body)
        # 줄 수는 정확해야 한다 — 틀린 목표를 주면 모델이 다 못 읽고 다 읽었다고 판단한다.
        expected = len((_shipped_root() / "SKILL.md").read_text(encoding="utf-8").splitlines())
        self.assertIn(f"all {expected} lines", body)
        self.assertEqual(expected, 2255)

        # 그리고 그 자리엔 상류가 기대하는 것이 실재한다 (SKILL.md와 그 직계 자식 엔진).
        self.assertTrue((self._anchor() / "SKILL.md").is_file())
        self.assertTrue((self._anchor() / "scripts" / "last30days.py").is_file())

    def test_unpacked_tree_equals_the_shipped_tree(self):
        skill_registry.show_skill(self.root, _SKILL)
        self.assertEqual(_digest(self._anchor()), _digest(_shipped_root()))

    def test_unpack_is_idempotent_but_repairs_damage_and_follows_updates(self):
        skill_registry.show_skill(self.root, _SKILL)
        engine = self._anchor() / "scripts" / "last30days.py"
        stamp = self._anchor() / skill_registry._ANCHOR_STAMP
        first = stamp.stat().st_mtime_ns

        skill_registry.show_skill(self.root, _SKILL)  # 같은 판본·온전한 트리 — 다시 풀지 않는다
        self.assertEqual(stamp.stat().st_mtime_ns, first)

        # 실행 부산물은 손상이 아니다 — 엔진이 남긴 .pyc 때문에 매번 다시 풀면 그게 더 나쁘다.
        bytecode = self._anchor() / "scripts" / "lib" / "__pycache__"
        bytecode.mkdir(parents=True, exist_ok=True)
        (bytecode / "env.cpython-314.pyc").write_bytes(b"\0")
        skill_registry.show_skill(self.root, _SKILL)
        self.assertEqual(stamp.stat().st_mtime_ns, first)

        engine.unlink()  # 손상 — 가리켜 놓고 그 안이 비면 스킬은 역추적으로 죽는다. 스스로 고친다.
        skill_registry.show_skill(self.root, _SKILL)
        self.assertTrue(engine.is_file())

        stamp.write_text(json.dumps({"plugin": _PLUGIN, "version": "0", "revision": "old"}), encoding="utf-8")
        skill_registry.show_skill(self.root, _SKILL)  # 판본이 바뀌면 통째로 다시 푼다
        self.assertEqual(json.loads(stamp.read_text(encoding="utf-8"))["version"], "3.18.4")
        self.assertEqual(_digest(self._anchor()), _digest(_shipped_root()))

    def test_derived_tree_never_reaches_a_commit(self):
        """`.asgard/.gitignore`는 셋업이 심는다 — 셋업 전에 스킬이 먼저 불려도 안 새야 한다."""
        skill_registry.show_skill(self.root, _SKILL)
        self.assertEqual(Path(self.root, ".asgard", "skills", ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_unwritable_project_still_gets_a_real_directory(self):
        """읽기 전용 체크아웃·낯선 cwd — 못 풀면 휠 사본을 가리킨다. 빈손으로 돌려보내지 않는다."""
        blocked = os.path.join(self.root, "blocked")
        os.makedirs(blocked)
        os.chmod(blocked, 0o500)
        try:
            body = skill_registry.load_skill_for_agent(blocked, "worker", _SKILL)
        finally:
            os.chmod(blocked, 0o700)
        match = re.search(r"SKILL_DIR=(\S+)", body)
        assert match is not None
        self.assertTrue(Path(match.group(1), "SKILL.md").is_file())
        self.assertTrue(Path(match.group(1), "scripts", "last30days.py").is_file())

    def test_full_upstream_text_is_still_reachable_on_demand(self):
        text = skill_registry.show_skill_resource(self.root, _SKILL, "SKILL.md")
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), _SKILL_MD_DIGEST)


class AllModesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_claude_code_scaffolds_a_discoverable_adapter(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root=self.root)
        adapter = dict(files)[os.path.join(self.root, ".claude", "skills", _SKILL, "SKILL.md")]
        self.assertIn("name: last30days", adapter)
        self.assertIn("Research what people actually say", adapter)
        self.assertIn("asgard skills show last30days", adapter)
        # 모델이 스스로 고를 수 있어야 한다 — Claude Code 스코프에서는 명시 호출로 못 박지 않는다.
        self.assertNotIn("disable-model-invocation", adapter)
        self.assertIn("argument-hint:", adapter)

    def test_cursor_and_codex_share_one_adapter_plus_codex_policy(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=False, cursor=True, codex=True, root=self.root)
        table = dict(files)
        adapter = table[os.path.join(self.root, ".agents", "skills", _SKILL, "SKILL.md")]
        self.assertIn("asgard skills show last30days", adapter)
        self.assertIn("disable-model-invocation: true", adapter)

        policy = table[os.path.join(self.root, ".agents", "skills", _SKILL, "agents", "openai.yaml")]
        self.assertIn("allow_implicit_invocation: false", policy)
        self.assertIn('short_description: "Research what people', policy)

    def test_native_loop_discovers_and_loads_through_its_own_tool(self):
        from asgard.agent.heimdall.roles import _skill_support

        note, tools, handlers = _skill_support("worker", self.root)
        self.assertIn(_SKILL, note)
        self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
        loaded = handlers["load_skill"]({"name": _SKILL})
        self.assertIn("SKILL_DIR=", loaded)
        self.assertTrue(Path(self.root, ".asgard", "skills", _SKILL, "SKILL.md").is_file())

    def test_user_typed_slash_command_expands_in_the_native_loop(self):
        prompt = skill_registry.invoked_skill_prompt(self.root, "/last30days nvidia earnings reaction")
        assert prompt is not None
        self.assertIn('<user_invoked_skill name="last30days">', prompt)
        self.assertIn("SKILL_DIR=", prompt)
        self.assertIn("Arguments: nvidia earnings reaction", prompt)

    def test_router_resolves_the_skill_in_both_languages(self):
        """Codex·Cursor는 `asgard skills resolve`가 유일한 통로다 — 한쪽 언어만 서면 절반이 못 쓴다."""
        for task in (
            "what are people on reddit saying about nvidia",
            "지난 30일 동안 이 제품에 대한 여론 좀 조사해줘",
            "최근 한 달 커뮤니티 반응 정리",
            "trending topics in AI video tools",
        ):
            with self.subTest(task=task):
                names = {name for name, _ in skill_registry.resolve_skills(self.root, task, "worker")}
                self.assertIn(_SKILL, names, task)

    def test_assignable_to_delivery_roles_without_polluting_their_default_catalog(self):
        for agent in ("freyja", "thor", "thor-lead"):
            with self.subTest(agent=agent):
                self.assertNotIn(_SKILL, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
                skill_registry.assign_skill(self.root, _SKILL, agent, assigned=True)
                self.assertIn(_SKILL, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
        # 판정 표면에는 어떤 조언 스킬도 안 붙는다.
        self.assertEqual(skill_registry.resolve_skills(self.root, "reddit trend research", "verifier"), [])


class AdapterFrontmatterTest(unittest.TestCase):
    """상류가 프론트매터를 채워 보내는 첫 번들 스킬이라, 어댑터 생성의 두 결함이 여기서 처음 산다."""

    _UPSTREAM = (
        "---\n"
        "name: sample\n"
        'description: "Quoted: with a colon"\n'
        "argument-hint: 'sample topic'\n"
        "allowed-tools: Bash, Read, Write, WebSearch\n"
        "---\n\nBODY\n"
    )

    def test_upstream_tools_survive_as_separate_entries(self):
        adapter = direct_skill(self._UPSTREAM)
        line = next(row for row in adapter.splitlines() if row.startswith("allowed-tools:"))
        entries = [item.strip() for item in line.split(":", 1)[1].split(",")]
        self.assertEqual(entries, ["Bash", "Read", "Write", "WebSearch", "Bash(asgard skills *)"])

    def test_quoted_description_stays_quoted_in_yaml_but_not_in_prose(self):
        # 프론트매터로 되돌아가는 자리 — 콜론이 든 설명은 인용부호를 잃으면 YAML이 깨진다.
        self.assertIn('description: "Quoted: with a colon"', direct_skill(self._UPSTREAM))
        # 사람이 읽는 자리 — 따옴표가 문장 첫 글자로 새면 안 된다.
        policy = openai_skill_metadata(direct_skill(self._UPSTREAM, implicit=False))
        assert policy is not None
        self.assertIn('short_description: "Quoted: with a colon"', policy)


class AnchorManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        # 플러그인 설치는 `~/.asgard/plugins`로 간다 — 밀폐 안 하면 테스트가 사용자 홈에 쓴다.
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(self.root, "home")

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        self.tmp.cleanup()

    def _pack(self, anchored) -> str:
        source = os.path.join(self.root, "pack")
        skill = os.path.join(source, "skills", "declared")
        os.makedirs(skill)
        Path(source, "plugin.json").write_text(
            json.dumps({"schema": 1, "name": "pack", "skills": ["declared"], "anchored": anchored}),
            encoding="utf-8",
        )
        Path(skill, "SKILL.md").write_text(
            "---\nname: declared\ndescription: Declared\ntriggers: declared\nagent: worker\n---\n\nINLINE\n",
            encoding="utf-8",
        )
        return source

    def test_anchored_must_name_a_declared_skill(self):
        with self.assertRaisesRegex(ValueError, "anchored"):
            skill_registry._validate_manifest(self._pack(["ghost"]))

    def test_plugins_without_the_field_keep_shipping_their_body_inline(self):
        skill_registry.install_plugin(self._pack([]))
        self.assertIn("INLINE", skill_registry.show_skill(self.root, "declared") or "")
        self.assertFalse(Path(self.root, ".asgard", "skills").exists())


if __name__ == "__main__":
    unittest.main()
