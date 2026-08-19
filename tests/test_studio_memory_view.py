"""메모리 화면의 자료 창구 — 옛 대시보드 서버의 다섯 문을 스튜디오 주소로 옮긴 자리.

검증 축: 옛 창구와 **같은 모양**을 내는가(자료원이 같으므로 키가 같아야 한다) / 매개변수
범위가 실제로 먹는가 / 슬러그가 임의 파일을 여는 문이 되지 않는가 / 서고가 없는 자리에서
터지지 않고 빈 상태를 내는가 / 실제 서버를 띄운 끝에서 끝까지 한 번.

전부 temp HOME + ASGARD_MEMORY_DIR 격리 — 이 시험이 오딘의 진짜 기억을 읽거나 만들지 않는다.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request

from asgard import memory
from asgard.commands.memory_dashboard import server as old_server
from asgard.commands.studio import memory_api
from asgard.commands.studio import server as studio_server


def _body(result):
    status, ctype, payload = result
    return status, ctype, json.loads(payload.decode("utf-8"))


class MemoryDoorBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-studio-memory-")
        self._home, self._mem = os.environ.get("HOME"), os.environ.get(memory.MEMORY_ENV)
        os.environ["HOME"] = self.tmp
        self.d = os.path.join(self.tmp, "memory")
        os.environ[memory.MEMORY_ENV] = self.d
        self.root = os.path.join(self.tmp, "project")
        os.makedirs(self.root, exist_ok=True)

    def tearDown(self):
        for key, value in (("HOME", self._home), (memory.MEMORY_ENV, self._mem)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self):
        memory.ensure_home(self.d)
        memory.add("토르 편대는 백엔드 전문가 팀이다", title="Thor squad", kind="insight", d=self.d)
        memory.add(
            "프레이야는 디자인 딜리버리를 담당한다. [[thor-squad]] 와 협업한다.",
            title="Freyja design",
            kind="note",
            links="thor-squad",
            d=self.d,
        )

    def get(self, path, **params):
        query = {name: [str(value)] for name, value in params.items()}
        return _body(memory_api.dispatch("GET", path, query, self.root))


# ── 옛 창구와 같은 모양 ────────────────────────────────────────────────────────────
#
# 다섯 문은 자료를 새로 만들지 않고 `memory_dashboard.data` 에 그대로 위임한다. 그 사실이
# 깨지는 순간은 조용하다 — 응답은 여전히 200 이고 화면만 빈칸이 된다. 그래서 옛 서버를 옆에
# 세워 두고 키를 맞대 본다. 값까지 맞대지 않는 자리는 시각이 끼어 있는 자리뿐이다.


class SameShapeAsOldServer(MemoryDoorBase):
    DOORS = (
        ("/api/snapshot", "/api/memory/snapshot"),
        ("/api/injection", "/api/memory/injection"),
        ("/api/search", "/api/memory/search"),
        ("/api/page", "/api/memory/page"),
        ("/api/log", "/api/memory/log"),
    )

    def test_every_door_answers_200_with_the_same_keys(self):
        self._seed()
        for old_path, new_path in self.DOORS:
            params = {"slug": ["thor-squad"]} if old_path == "/api/page" else {"q": ["토르"]}
            old_status, _, old_data = _body(old_server.dispatch("GET", old_path, params))
            new_status, ctype, new_data = _body(memory_api.dispatch("GET", new_path, params, self.root))
            self.assertEqual((old_status, new_status), (200, 200), new_path)
            self.assertEqual(ctype, "application/json; charset=utf-8", new_path)
            self.assertEqual(sorted(old_data), sorted(new_data), new_path)

    def test_the_deterministic_doors_answer_byte_for_byte(self):
        """log·page·search 는 시각이 안 끼어 있다 — 위임이 끊기면 값까지 갈린다."""
        self._seed()
        for old_path, new_path, params in (
            ("/api/log", "/api/memory/log", {"limit": ["5"]}),
            ("/api/page", "/api/memory/page", {"slug": ["thor-squad"]}),
            ("/api/search", "/api/memory/search", {"q": ["토르"], "k": ["3"]}),
        ):
            _, _, old_data = _body(old_server.dispatch("GET", old_path, params))
            _, _, new_data = _body(memory_api.dispatch("GET", new_path, params, self.root))
            self.assertEqual(old_data, new_data, new_path)

    def test_the_snapshot_carries_the_seeded_pages(self):
        """빈 껍데기를 200 으로 내고 있지 않은가 — 모양이 같아도 자료가 안 실리면 화면은 빈칸이다."""
        self._seed()
        status, _, data = self.get("/api/memory/snapshot")
        self.assertEqual(status, 200)
        self.assertEqual(data["meta"]["pages"], 2)
        self.assertIn("Thor squad", {row["title"] for row in data["catalog"]})


# ── 매개변수 범위 ─────────────────────────────────────────────────────────────────
#
# 상한은 `data.py` 가 든다(k 1..25 · limit 1..500 · offset ≥ 0). 이 문이 그것을 우회하거나
# 자기 상한을 하나 더 만들지 않았는지를, 창이 실제로 보낼 수 있는 값으로 본다.


class ParameterBounds(MemoryDoorBase):
    def test_an_enormous_k_is_capped(self):
        _, _, data = self.get("/api/memory/search", q="토르", k=10**9)
        self.assertEqual(data["k"], 25)

    def test_an_enormous_limit_is_capped(self):
        self._seed()
        _, _, data = self.get("/api/memory/log", limit=10**9)
        self.assertEqual(data["limit"], 500)

    def test_a_negative_offset_lands_on_zero(self):
        self._seed()
        _, _, data = self.get("/api/memory/log", offset=-500)
        self.assertEqual(data["offset"], 0)

    def test_a_non_numeric_value_falls_back_to_the_default(self):
        self.assertEqual(self.get("/api/memory/search", q="토르", k="abc")[2]["k"], 5)
        self.assertEqual(self.get("/api/memory/log", limit="")[2]["limit"], 60)

    def test_a_digit_string_past_the_conversion_ceiling_does_not_raise(self):
        """`int()` 는 4300 자리를 넘는 문자열을 거절한다 — 그 거절이 500 이 되면 안 된다."""
        status, _, data = self.get("/api/memory/log", limit="9" * 6000)
        self.assertEqual(status, 200)
        self.assertEqual(data["limit"], 60)

    def test_a_malformed_day_filter_is_ignored_not_refused(self):
        self._seed()
        _, _, filtered = self.get("/api/memory/log", day="어제")
        _, _, plain = self.get("/api/memory/log")
        self.assertEqual(filtered["total"], plain["total"])


# ── 슬러그 ────────────────────────────────────────────────────────────────────────


class SlugSafety(MemoryDoorBase):
    def test_a_path_shaped_slug_is_refused_with_a_code(self):
        """`page_data` 앞단의 `memory.valid_slug` 가 이미 막는 자리 — 문이 그것을 우회하지 않았는가."""
        for slug in ("../../../etc/passwd", "/etc/passwd", "..", "pages/thor-squad", "thor-squad.md"):
            status, _, data = self.get("/api/memory/page", slug=slug)
            self.assertEqual(status, 400, slug)
            self.assertEqual(data["error"]["code"], "memory_slug_invalid", slug)
            self.assertNotIn("body", data)

    def test_a_missing_page_is_404_with_its_own_code(self):
        self._seed()
        status, _, data = self.get("/api/memory/page", slug="없는-페이지")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "memory_page_not_found")

    def test_a_real_page_comes_back_with_its_body(self):
        self._seed()
        status, _, data = self.get("/api/memory/page", slug="thor-squad")
        self.assertEqual(status, 200)
        self.assertEqual(data["slug"], "thor-squad")
        self.assertIn("백엔드", data["body"])


# ── 없는 경로 · 쓰기 ──────────────────────────────────────────────────────────────


class UnknownRoutes(MemoryDoorBase):
    def test_an_unknown_memory_path_is_404(self):
        for path in ("/api/memory/", "/api/memory/nope", "/api/memory/snapshot/extra"):
            status, ctype, _ = memory_api.dispatch("GET", path, {}, self.root)
            self.assertEqual(status, 404, path)
            self.assertTrue(ctype.startswith("text/plain"), path)

    def test_writes_are_refused(self):
        """읽기 전용 관측 창이다 — 옛 서버와 같이 비-GET 은 문 앞에서 끊는다."""
        for method in ("POST", "PUT", "DELETE"):
            status, _, _ = memory_api.dispatch(method, "/api/memory/snapshot", {}, self.root)
            self.assertEqual(status, 405, method)


# ── 서고가 없는 자리 ──────────────────────────────────────────────────────────────


class EmptyBank(MemoryDoorBase):
    """시험은 임시 디렉터리에서 돈다 — 서고가 아직 없는 자리가 실제로 걸리는 자리다."""

    def setUp(self):
        super().setUp()
        os.environ[memory.MEMORY_ENV] = os.path.join(self.tmp, "not-made-yet", "memory")

    def test_every_door_answers_an_empty_state(self):
        for path, params in (
            ("/api/memory/snapshot", {}),
            ("/api/memory/injection", {}),
            ("/api/memory/search", {"q": "토르"}),
            ("/api/memory/log", {}),
        ):
            status, _, data = self.get(path, **params)
            self.assertEqual(status, 200, path)
            self.assertIsInstance(data, dict)
        self.assertEqual(self.get("/api/memory/snapshot")[2]["meta"]["pages"], 0)
        self.assertEqual(self.get("/api/memory/log")[2]["entries"], [])
        self.assertEqual(self.get("/api/memory/search", q="토르")[2]["hits"], [])

    def test_a_page_lookup_on_an_empty_bank_is_404_not_a_crash(self):
        status, _, data = self.get("/api/memory/page", slug="thor-squad")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "memory_page_not_found")


# ── 끝에서 끝까지 ─────────────────────────────────────────────────────────────────


class ServedMemoryDoors(MemoryDoorBase):
    """실제 서버를 띄워 — 경로표가 이 모듈을 실제로 부르는가(배선은 `routes.py` 가 쥐고 있다)."""

    def _serve_forever(self, root: str):
        httpd = studio_server._bind("127.0.0.1", 0, root)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, httpd.server_address[1]

    def test_the_studio_server_answers_the_memory_doors(self):
        self._seed()
        httpd, port = self._serve_forever(self.root)
        try:
            for path in (
                "/api/memory/snapshot",
                "/api/memory/injection",
                "/api/memory/search?q=%ED%86%A0%EB%A5%B4&k=3",
                "/api/memory/page?slug=thor-squad",
                "/api/memory/log?limit=5",
            ):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
                    self.assertEqual(response.status, 200, path)
                    self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8", path)
                    self.assertIsInstance(json.loads(response.read().decode("utf-8")), dict, path)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
