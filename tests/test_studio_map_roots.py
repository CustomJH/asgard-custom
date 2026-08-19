#!/usr/bin/env python3
"""맵 창구 — 여러 뿌리를 보되, 남의 뿌리에는 한 글자도 안 쓴다.

여기서 봉인하는 것은 넷이다.

  (a) 뿌리 목록은 세 출처(session·workspace·declared)의 합집합이고, 같은 자리는 realpath 로 접힌다
  (b) 사라진 자리는 목록에 안 뜨고, `scanned` 는 상태 파일의 존재와 일치한다
  (c) 스캔 안 된 뿌리는 **대신 스캔하지 않고** 409 로 거절한다 — 그 디렉터리에 아무것도 안 만든다
  (d) 목록 밖 경로는 거절한다 — 창구가 파일 시스템 탐색기가 되면 안 된다

(c)가 이 화면의 경계다. 그래프 상태 파일은 `<뿌리>/.asgard/state/` 에 쓰이므로, 편의로 대신
스캔하면 남의 저장소에 파일을 만들게 된다.

실행: uv run pytest tests/test_studio_map_roots.py
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from asgard.commands.studio import map_api, server

# 최소한의 유효 상태 — `graph_state` 가 요구하는 다섯 칸(schema·revision·counts·nodes·edges).
_STATE = {
    "schema": 1,
    "revision": "rev-1",
    "counts": {"nodes": 2, "edges": 1},
    "nodes": [
        {"id": "mod:alpha", "kind": "module", "files": []},
        {"id": "file:beta.py", "kind": "file", "files": []},
    ],
    "edges": [{"from": "mod:alpha", "to": "file:beta.py", "kind": "touches"}],
}


def _scan(root: str) -> str:
    """그 뿌리를 스캔된 것으로 만든다 — 상태 파일 하나가 곧 스캔의 흔적이다."""
    path = Path(root, ".asgard", "state", "map-graph.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_STATE), encoding="utf-8")
    return str(path)


@contextmanager
def _sources(workspaces: list[dict], declared: list[str]):
    """등록부와 선언을 갈아 끼운다 — 여기서 재는 것은 합치는 규칙이지 두 출처의 저장 형식이 아니다."""
    with (
        mock.patch("asgard.commands.studio_store.list_projects", return_value=workspaces),
        mock.patch("asgard.settings.declared_roots", return_value=declared),
    ):
        yield


def _body(response: tuple[int, str, bytes]) -> dict:
    return json.loads(response[2].decode())


class RootUnionTest(unittest.TestCase):
    def test_three_sources_merge_and_the_same_place_folds_once(self):
        with tempfile.TemporaryDirectory() as base:
            session, workspace, declared = (os.path.join(base, name) for name in ("session", "ws", "decl"))
            for path in (session, workspace, declared):
                os.mkdir(path)
            link = os.path.join(base, "ws-link")
            os.symlink(workspace, link)
            with _sources(
                [{"root": workspace, "name": "ws"}, {"root": os.path.join(session, "."), "name": "again"}],
                [declared, link],
            ):
                rows = map_api.roots(session)
            self.assertEqual(
                {row["root"]: row["source"] for row in rows},
                {
                    os.path.realpath(session): "session",
                    os.path.realpath(workspace): "workspace",
                    os.path.realpath(declared): "declared",
                },
            )
            self.assertEqual([row["current"] for row in rows], [True, False, False])
            self.assertEqual([row["name"] for row in rows], ["session", "ws", "decl"])

    def test_a_vanished_directory_never_reaches_the_picker(self):
        """등록부에는 지운 임시 디렉터리가 남는다 — 실측으로 여섯 중 셋이 그랬다."""
        with tempfile.TemporaryDirectory() as base:
            gone = os.path.join(base, "gone")
            with _sources([{"root": gone, "name": "gone"}], [os.path.join(base, "never")]):
                rows = map_api.roots(base)
            self.assertEqual([row["root"] for row in rows], [os.path.realpath(base)])

    def test_scanned_follows_the_state_file(self):
        with tempfile.TemporaryDirectory() as base:
            with _sources([], []):
                self.assertFalse(map_api.roots(base)[0]["scanned"])
                _scan(base)
                self.assertTrue(map_api.roots(base)[0]["scanned"])


class GraphWindowTest(unittest.TestCase):
    def test_an_unscanned_root_is_refused_and_stays_untouched(self):
        """경계 시험 — 편의로 대신 스캔하면 남의 저장소에 상태 파일이 생긴다."""
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as other:
            with _sources([{"root": other, "name": "other"}], []):
                status, _, raw = map_api.dispatch("GET", "/api/map/graph", {"root": [other]}, base)
            self.assertEqual(status, 409)
            error = json.loads(raw.decode())["error"]
            self.assertEqual(error["code"], "map_unscanned")
            self.assertIn("asgard map scan", error["remedy"])
            self.assertEqual(os.listdir(other), [])

    def test_a_root_outside_the_list_is_refused(self):
        with tempfile.TemporaryDirectory() as base:
            with _sources([], []):
                status, _, raw = map_api.dispatch("GET", "/api/map/graph", {"root": ["/etc"]}, base)
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(raw.decode())["error"]["code"], "map_root_unknown")

    def test_the_payload_is_what_build_view_bakes(self):
        """굽는 쪽과 내는 쪽이 갈리지 않는가 — 템플릿을 `__DATA__` 한 줄로 바꿔 구운 자료만 꺼낸다."""
        from asgard.map_graph import view

        with tempfile.TemporaryDirectory() as base:
            _scan(base)
            with _sources([], []):
                status, kind, raw = map_api.dispatch("GET", "/api/map/graph", {}, base)
            self.assertEqual(status, 200)
            self.assertIn("application/json", kind)
            with mock.patch.object(view, "_template", return_value="__DATA__"):
                baked = json.loads(view.build_view(base))
            served = json.loads(raw.decode())
            self.assertEqual(set(served), set(baked))
            self.assertEqual(served, baked)

    def test_writes_are_not_this_window(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(map_api.dispatch("POST", "/api/map/roots", {}, base)[0], 405)


class ServedMapTest(unittest.TestCase):
    """실제 서버 하나 — 경로표부터 창구까지 이어져 있는가."""

    def _get(self, port: int, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as refused:
            return refused.code, json.loads(refused.read().decode())

    def test_roots_and_graph_answer_end_to_end(self):
        with tempfile.TemporaryDirectory() as root:
            httpd = server._bind("127.0.0.1", 0, root)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            port = httpd.server_address[1]
            try:
                status, listing = self._get(port, "/api/map/roots")
                self.assertEqual(status, 200)
                self.assertEqual(listing["current"], os.path.realpath(root))
                current = [row for row in listing["roots"] if row["current"]]
                self.assertEqual([row["scanned"] for row in current], [False])

                status, error = self._get(port, "/api/map/graph")
                self.assertEqual(status, 409)
                self.assertEqual(error["error"]["code"], "map_unscanned")

                _scan(root)
                status, payload = self._get(port, "/api/map/graph")
                self.assertEqual(status, 200)
                self.assertEqual(payload["counts"], _STATE["counts"])
                self.assertEqual([node["id"] for node in payload["nodes"]], ["mod:alpha", "file:beta.py"])
                self.assertEqual(payload["records"], {})
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
