"""studio dashboard (세스룸니르) — 스튜디오 표면 첫 조각 테스트.

검증 축: 데이터 조립(projects·project·snapshot 이 디스크 사실에서) / 아티팩트 경로 경계
(realpath — 순회·심링크 탈출·메타 파일 차단) / 라우팅·JSON 직렬화·HTML 렌더 /
읽기 전용(비-GET 거부) + Host 가드 / 로컬 서버 왕복(live http).
전부 temp HOME + ASGARD_STUDIO_DIR 격리 — memory dashboard 와 별개 표면(CUS-263).
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from asgard.commands import studio_dashboard as studio


class StudioBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-studio-")
        self._home = os.environ.get("HOME")
        self._env = os.environ.get(studio.STUDIO_ENV)
        os.environ["HOME"] = self.tmp
        self.d = os.path.join(self.tmp, "studio")
        os.environ[studio.STUDIO_ENV] = self.d
        studio.ensure_home(self.d)

    def tearDown(self):
        for k, v in (("HOME", self._home), (studio.STUDIO_ENV, self._env)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _project(self, slug: str, meta: dict | None = None, files: dict[str, str] | None = None) -> str:
        pdir = os.path.join(self.d, studio.PROJECTS, slug)
        os.makedirs(pdir, exist_ok=True)
        if meta is not None:
            with open(os.path.join(pdir, studio.META), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
        for rel, content in (files or {}).items():
            p = os.path.join(pdir, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        return pdir

    def _seed(self):
        self._project(
            "landing-page",
            meta={"name": "랜딩 페이지", "brief": "관문 아치 랜딩", "created": "2026-07-18", "updated": "2026-07-18"},
            files={"index.html": "<h1>gate</h1>", "assets/style.css": "body{}"},
        )
        self._project("deck", meta={"name": "덱"}, files={"deck.html": "<section/>"})


class TestDataAssembly(StudioBase):
    def test_ensure_home_scaffolds_projects_dir(self):
        self.assertTrue(os.path.isdir(os.path.join(self.d, studio.PROJECTS)))

    def test_ensure_home_rejects_symlink_home(self):
        real = os.path.join(self.tmp, "elsewhere")
        os.makedirs(real)
        link = os.path.join(self.tmp, "link-home")
        os.symlink(real, link)
        with self.assertRaises(ValueError):
            studio.ensure_home(link)

    def test_projects_reads_meta_and_counts_artifacts(self):
        self._seed()
        rows = {r["slug"]: r for r in studio.projects_data(self.d)}
        self.assertEqual(set(rows), {"landing-page", "deck"})
        self.assertEqual(rows["landing-page"]["name"], "랜딩 페이지")
        self.assertEqual(rows["landing-page"]["artifacts"], 2)  # project.json 은 아티팩트가 아니다
        self.assertEqual(rows["deck"]["artifacts"], 1)

    def test_broken_meta_fails_open_to_directory_fact(self):
        pdir = self._project("broken", files={"a.html": "x"})
        with open(os.path.join(pdir, studio.META), "w", encoding="utf-8") as f:
            f.write("{not json")
        row = next(r for r in studio.projects_data(self.d) if r["slug"] == "broken")
        self.assertEqual(row["name"], "broken")
        self.assertEqual(row["artifacts"], 1)

    def test_project_detail_lists_relative_paths(self):
        self._seed()
        p = studio.project_data("landing-page", self.d)
        self.assertEqual({a["path"] for a in p["artifacts"]}, {"index.html", os.path.join("assets", "style.css")})
        self.assertNotIn("error", p)

    def test_project_detail_unknown_or_bad_slug(self):
        self.assertEqual(studio.project_data("nope", self.d).get("error"), "not found")
        self.assertEqual(studio.project_data("../escape", self.d).get("error"), "not found")

    def test_snapshot_is_json_serializable(self):
        self._seed()
        snap = studio.snapshot_data(self.d)
        parsed = json.loads(json.dumps(snap, ensure_ascii=False))
        self.assertEqual(parsed["meta"]["projects"], 2)
        self.assertEqual(parsed["meta"]["artifacts"], 3)


class TestArtifactBoundary(StudioBase):
    def test_valid_artifact_resolves(self):
        self._seed()
        p = studio.artifact_path("landing-page", "index.html", self.d)
        assert p is not None
        self.assertTrue(p.endswith("index.html"))

    def test_traversal_and_absolute_rejected(self):
        self._seed()
        secret = os.path.join(self.tmp, "secret.txt")
        with open(secret, "w") as f:
            f.write("s")
        self.assertIsNone(studio.artifact_path("landing-page", "../../secret.txt", self.d))
        self.assertIsNone(studio.artifact_path("landing-page", secret, self.d))
        self.assertIsNone(studio.artifact_path("../..", "index.html", self.d))

    def test_symlink_escape_rejected(self):
        self._seed()
        secret = os.path.join(self.tmp, "secret.txt")
        with open(secret, "w") as f:
            f.write("s")
        pdir = os.path.join(self.d, studio.PROJECTS, "landing-page")
        os.symlink(secret, os.path.join(pdir, "leak.txt"))
        self.assertIsNone(studio.artifact_path("landing-page", "leak.txt", self.d))

    def test_meta_file_not_served(self):
        self._seed()
        self.assertIsNone(studio.artifact_path("landing-page", studio.META, self.d))


class TestDispatch(StudioBase):
    def test_root_serves_selfcontained_html(self):
        status, ctype, body = studio.dispatch("GET", "/", {})
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        text = body.decode("utf-8")
        self.assertIn("<!doctype html>", text.lower())
        self.assertNotIn('src="http', text)  # 자기완결 — 외부 로드 없음

    def test_snapshot_endpoint(self):
        self._seed()
        status, ctype, body = studio.dispatch("GET", "/api/snapshot", {})
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(body)["meta"]["projects"], 2)

    def test_project_endpoint_and_404(self):
        self._seed()
        status, _, body = studio.dispatch("GET", "/api/project", {"slug": ["deck"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["slug"], "deck")
        status, _, _ = studio.dispatch("GET", "/api/project", {"slug": ["nope"]})
        self.assertEqual(status, 404)

    def test_artifact_endpoint_serves_and_guards(self):
        self._seed()
        status, ctype, body = studio.dispatch("GET", "/artifact", {"slug": ["landing-page"], "path": ["index.html"]})
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertEqual(body, b"<h1>gate</h1>")
        status, _, _ = studio.dispatch("GET", "/artifact", {"slug": ["landing-page"], "path": ["../../x"]})
        self.assertEqual(status, 404)

    def test_non_get_rejected(self):
        for method in ("POST", "PUT", "DELETE"):
            status, _, _ = studio.dispatch(method, "/api/snapshot", {})
            self.assertEqual(status, 405)

    def test_unknown_route(self):
        status, _, _ = studio.dispatch("GET", "/api/nope", {})
        self.assertEqual(status, 404)


class TestTemplatesAndEngine(StudioBase):
    """번들 템플릿 라이브러리(CUS-264 슬라이스) + 생성 엔진 토글."""

    def test_bundle_is_rich_and_categorized(self):
        data = studio.templates_data()
        self.assertGreaterEqual(data["total"], 200)  # 디자인 106 + 미디어 106 — 풍부함이 계약
        for cat in ("슬라이드", "이미지", "동영상", "프로토타입"):
            self.assertIn(cat, data["categories"], cat)
        kinds = {t["kind"] for t in data["templates"]}
        self.assertEqual(kinds, {"design", "media"})

    def test_template_file_whitelist(self):
        name = next(t["name"] for t in studio.templates_data()["templates"] if t["kind"] == "design")
        got = studio.template_file(name)
        assert got is not None
        self.assertIn(b"<", got[1])
        self.assertIsNone(studio.template_file(name, "../index.json"))
        self.assertIsNone(studio.template_file("no-such-template"))

    def test_use_template_scaffolds_instant_artifact(self):
        from asgard.commands import studio as core

        name = next(t["name"] for t in studio.templates_data()["templates"] if t["kind"] == "design")
        p = core.use_template(name, d=self.d)
        assert p is not None
        self.assertTrue(os.path.isfile(os.path.join(p["dir"], "index.html")))
        runs = studio.read_runs(p["dir"])
        self.assertEqual(runs[0]["stage"], "template")
        self.assertGreaterEqual(runs[0]["artifacts"], 1)

    def test_use_media_template_copies_prompt(self):
        from asgard.commands import studio as core

        name = next(t["name"] for t in studio.templates_data()["templates"] if t["kind"] == "media")
        p = core.use_template(name, d=self.d)
        assert p is not None
        self.assertTrue(os.path.isfile(os.path.join(p["dir"], "prompt.json")))

    def test_engine_default_set_and_alias(self):
        from asgard.commands import studio as core

        self.assertEqual(studio.engine(self.d), "claude-native")
        self.assertEqual(core.set_engine("codex", self.d), "openai-native")
        self.assertEqual(studio.engine(self.d), "openai-native")
        self.assertEqual(core.set_engine("claude-code", self.d), "claude-native")
        self.assertIsNone(core.set_engine("gpt-5", self.d))

    def test_dispatch_template_routes(self):
        status, _, body = studio.dispatch("GET", "/api/templates", {})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(json.loads(body)["total"], 200)
        name = next(t["name"] for t in studio.templates_data()["templates"] if t["kind"] == "design")
        status, ctype, body = studio.dispatch("GET", "/template", {"name": [name]})
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertEqual(studio.dispatch("GET", "/template", {"name": ["../etc"]})[0], 404)

    def test_post_engine_and_template_use(self):
        status, _, body = studio.dispatch_post("/api/engine", {"engine": "codex"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["engine"], "openai-native")
        self.assertEqual(studio.engine(self.d), "openai-native")
        self.assertEqual(studio.dispatch_post("/api/engine", {"engine": "nope"})[0], 400)
        name = next(t["name"] for t in studio.templates_data()["templates"] if t["kind"] == "design")
        status, _, body = studio.dispatch_post("/api/template-use", {"name": name})
        self.assertEqual(status, 201)
        slug = json.loads(body)["slug"]
        self.assertTrue(os.path.isfile(os.path.join(self.d, studio.PROJECTS, slug, "index.html")))
        self.assertEqual(studio.dispatch_post("/api/template-use", {"name": "ghost"})[0], 404)


class TestHostGuard(unittest.TestCase):
    def test_loopback_allowed(self):
        for h in ("127.0.0.1", "127.0.0.1:8766", "localhost:8766", "[::1]:8766", "LOCALHOST"):
            self.assertTrue(studio.host_allowed(h), h)

    def test_external_rejected(self):
        for h in (None, "", "evil.example", "evil.example:8766", "10.0.0.5:80"):
            self.assertFalse(studio.host_allowed(h), repr(h))


class TestLiveServer(StudioBase):
    def test_roundtrip_and_forbidden_host(self):
        self._seed()
        httpd = studio._bind("127.0.0.1", 0)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=5) as r:
                self.assertEqual(r.status, 200)
                self.assertEqual(json.loads(r.read())["meta"]["projects"], 2)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.example"})
            try:
                urllib.request.urlopen(req, timeout=5)
                self.fail("forbidden host must be rejected")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 403)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/artifact?slug=landing-page&path=index.html", timeout=5
            ) as r:
                self.assertEqual(r.headers.get("Content-Security-Policy"), "sandbox allow-scripts")
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestStudioCore(StudioBase):
    """commands/studio.py — 스캐폴드·슬러그·이력. 생성(LLM)은 여기서 돌리지 않는다."""

    def test_slugify_dedup_and_hangul_fallback(self):
        from asgard.commands import studio as core

        self.assertEqual(core.slugify("Landing Page for Cafe", self.d), "landing-page-for-cafe")
        self._project("landing-page-for-cafe")
        self.assertEqual(core.slugify("Landing Page for Cafe", self.d), "landing-page-for-cafe-2")
        self.assertEqual(core.slugify("한글 브리프만 있는 경우", self.d), "studio-1")

    def test_create_project_writes_meta_and_bookkeeping(self):
        from asgard.commands import studio as core

        p = core.create_project("카페 랜딩 페이지\n두번째 줄", d=self.d)
        self.assertTrue(os.path.isdir(os.path.join(p["dir"], studio.BOOK)))
        with open(os.path.join(p["dir"], studio.META), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["name"], "카페 랜딩 페이지")
        self.assertIn("두번째 줄", meta["brief"])
        row = next(r for r in studio.projects_data(self.d) if r["slug"] == p["slug"])
        self.assertEqual(row["artifacts"], 0)  # .studio 북키핑은 아티팩트가 아니다

    def test_create_project_initializes_git_evidence_tree(self):
        """Trinity 쓰기 퀘스트 요건 — HEAD 있는 git 저장소 + 북키핑은 ignore (라이브 e2e 회귀 방지)."""
        import subprocess

        from asgard.commands import studio as core

        p = core.create_project("cafe landing", d=self.d)
        head = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=p["dir"], capture_output=True)
        self.assertEqual(head.returncode, 0)
        with open(os.path.join(p["dir"], ".gitignore"), encoding="utf-8") as f:
            self.assertIn(".studio/", f.read())

    def test_state_and_runs_roundtrip(self):
        from asgard.commands import studio as core

        p = core.create_project("brief", d=self.d)
        core._write_state(p["dir"], {"status": "running"})
        self.assertEqual(studio.read_state(p["dir"])["status"], "running")
        core._finish(p["dir"], {"name": "brief", "brief": "brief"}, status="ok", wall=1.2, tokens=42, note="")
        runs = studio.read_runs(p["dir"])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "ok")
        self.assertEqual(runs[0]["stage"], "generate")
        self.assertEqual(studio.read_state(p["dir"])["status"], "ok")

    def test_generation_rejects_unknown_or_briefless(self):
        from asgard import ui
        from asgard.commands import studio as core

        ui.set_quiet(True)
        try:
            self.assertEqual(core.run_generation("nope", d=self.d), 2)
            p = core.create_project("x", d=self.d)
            with open(os.path.join(p["dir"], studio.META), "w", encoding="utf-8") as f:
                json.dump({"name": "x", "brief": ""}, f)
            self.assertEqual(core.run_generation(p["slug"], d=self.d), 2)
        finally:
            ui.set_quiet(False)


class TestPostDispatch(StudioBase):
    """POST /api/generate — 서버는 워커를 스폰만 한다 (_spawn 을 패치해 소켓·LLM 없이 검증)."""

    def setUp(self):
        super().setUp()
        from unittest import mock

        from asgard.commands.studio_dashboard import server

        self.spawned: list[str] = []

        def _fake(slug: str, d: str | None = None) -> int:
            self.spawned.append(slug)
            return 4242

        patcher = mock.patch.object(server, "_spawn", _fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_new_project_from_brief(self):
        status, ctype, body = studio.dispatch_post("/api/generate", {"brief": "cafe landing page"})
        self.assertEqual(status, 202)
        data = json.loads(body)
        self.assertEqual(data["status"], "running")
        self.assertEqual(self.spawned, [data["slug"]])
        self.assertTrue(os.path.isdir(os.path.join(self.d, studio.PROJECTS, data["slug"])))

    def test_regenerate_existing(self):
        self._seed()
        status, _, body = studio.dispatch_post("/api/generate", {"slug": "deck"})
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)["slug"], "deck")
        self.assertEqual(self.spawned, ["deck"])

    def test_regenerate_with_instruction_appends_brief(self):
        """스레드 추가 지시(refine-lite) — slug+brief POST 는 브리프에 병합 후 재생성한다."""
        self._seed()
        status, _, _ = studio.dispatch_post("/api/generate", {"slug": "deck", "brief": "여백을 더 넉넉하게"})
        self.assertEqual(status, 202)
        self.assertEqual(self.spawned, ["deck"])
        brief = studio.project_data("deck", self.d)["brief"]
        self.assertIn("여백을 더 넉넉하게", brief)
        self.assertIn("[추가 지시", brief)

    def test_rejects_bad_input(self):
        self.assertEqual(studio.dispatch_post("/api/generate", {})[0], 400)  # 브리프 없음
        self.assertEqual(studio.dispatch_post("/api/generate", {"slug": "../evil"})[0], 400)
        self.assertEqual(studio.dispatch_post("/api/generate", {"slug": "ghost"})[0], 404)
        self.assertEqual(studio.dispatch_post("/api/nope", {"brief": "x"})[0], 404)
        self.assertFalse(self.spawned)

    def test_origin_guard(self):
        for origin in (None, "", "http://127.0.0.1:8766", "http://localhost:1234"):
            self.assertTrue(studio.origin_allowed(origin), repr(origin))
        for origin in ("https://evil.example", "http://10.0.0.5", "null"):
            self.assertFalse(studio.origin_allowed(origin), repr(origin))

    def test_runlog_route(self):
        self._seed()
        pdir = os.path.join(self.d, studio.PROJECTS, "deck")
        os.makedirs(os.path.join(pdir, studio.BOOK), exist_ok=True)
        with open(os.path.join(pdir, studio.BOOK, studio.RUN_LOG), "w", encoding="utf-8") as f:
            f.write("hello log\n")
        status, ctype, body = studio.dispatch("GET", "/api/runlog", {"slug": ["deck"]})
        self.assertEqual(status, 200)
        self.assertIn("hello log", body.decode())
        self.assertEqual(studio.dispatch("GET", "/api/runlog", {"slug": ["../x"]})[0], 404)


if __name__ == "__main__":
    unittest.main()
