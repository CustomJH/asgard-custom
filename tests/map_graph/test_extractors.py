#!/usr/bin/env python3
"""증거 추출 — 파이썬·TS/JS 소스와 위임 요약.

실행: uv run pytest tests/map_graph
"""

import unittest

from map_graph.map_base import (
    _PRISMA_FIXTURE,
    _PY_FIXTURE,
    _TS_FIXTURE,
    Base,
)


class TestPythonExtractor(Base):
    def kinds(self, source: str) -> dict:
        from asgard.map_graph.extract_python import extract_python

        out = {}
        for item in extract_python("src/app/api.py", source):
            out.setdefault(item.kind, []).append(item)
        return out

    def test_extracts_routes_models_jobs_services_with_locations(self):
        found = self.kinds(_PY_FIXTURE)
        route_names = {e.name for e in found["route"]}
        self.assertEqual(route_names, {"GET /users", "POST /users"})
        self.assertTrue(all(e.confidence == "confirmed" and e.line > 0 for e in found["route"]))
        self.assertEqual([e.name for e in found["model"]], ["User"])
        self.assertEqual([e.name for e in found["job"]], ["nightly_sync"])
        self.assertEqual({e.name for e in found["external_service"]}, {"stripe"})

    def test_api_call_literal_url_confirmed_and_db_execute_stays_candidate(self):
        found = self.kinds(_PY_FIXTURE)
        api = found["api_call"][0]
        self.assertEqual(api.confidence, "confirmed")
        self.assertTrue(api.name.startswith("https://api.stripe.com"))
        self.assertTrue(all(e.confidence == "candidate" for e in found["db_access"]))

    def test_api_call_does_not_copy_url_credentials_or_query(self):
        found = self.kinds('import httpx\nhttpx.get("https://user:pass@example.com/x?token=secret#frag")')
        self.assertEqual(found["api_call"][0].name, "https://example.com/x")

    def test_typer_command_and_syntax_error_fail_open(self):
        from asgard.map_graph.extract_python import extract_python

        source = "import typer\napp = typer.Typer()\n\n@app.command('scan')\ndef run():\n    pass\n"
        commands = [e for e in extract_python("x.py", source) if e.kind == "command"]
        self.assertEqual([c.name for c in commands], ["scan"])
        self.assertEqual(commands[0].confidence, "confirmed")
        self.assertEqual(extract_python("x.py", "def broken(:"), [])

    def test_unbound_decorator_and_generic_base_remain_candidates(self):
        found = self.kinds('@app.get("/looks-real")\ndef f(): pass\nclass User(Base): pass\n')
        self.assertEqual(found["route"][0].confidence, "candidate")
        self.assertEqual(found["model"][0].confidence, "candidate")


class TestDelegatedSummaries(Base):
    """역할 문장을 번역 표에 맡긴 선언 — 26-08-12 에 명령 22개가 이 자리에서 통째로 사라졌다.

    `help=t("hc_tk_board")` 는 리터럴이 아니라 호출이라 추출기가 빈 요약을 냈고, 프로젝션은 요약
    없는 명령을 카탈로그에서 뺀다. 결과는 `asgard ticket *` 이 주입면에서 후보로도 못 서는 것이었고,
    map-shortcut 벤치의 상위3 적중이 92%에서 69%로 내려앉아 게이트가 빨간불이 됐다.
    """

    _CLI = (
        "import typer\n"
        "from .i18n import t\n"
        "app = typer.Typer()\n"
        "ticket_app = typer.Typer()\n"
        'app.add_typer(ticket_app, name="ticket")\n'
        '@ticket_app.command("board", help=t("hc_tk_board"))\n'
        "def ticket_board():\n"
        "    pass\n"
        '@ticket_app.command("orphan", help=t("hc_missing_key"))\n'
        "def ticket_orphan():\n"
        "    pass\n"
    )
    _TABLE = (
        "_M: dict[str, tuple[str, str]] = {\n"
        '    "hc_tk_board": ("the board as it stands, in status columns", "지금 보드를 상태 칸으로"),\n'
        "}\n"
        'PLAIN = {"hc_plain": "one sentence"}\n'
        'COMPUTED = {"hc_computed": "a" + "b"}\n'
    )

    def commands(self, source: str) -> dict:
        from asgard.map_graph.extract_python import extract_python

        return {item.name: item for item in extract_python("src/app/cli.py", source) if item.kind == "command"}

    def test_call_valued_help_records_the_key_instead_of_dropping_it(self):
        board = self.commands(self._CLI)["ticket board"]
        self.assertEqual(board.summary, "")
        self.assertEqual(board.summary_key, "hc_tk_board")

    def test_literal_help_and_docstring_still_win_over_the_key(self):
        source = (
            "import typer\n"
            "app = typer.Typer()\n"
            '@app.command("lit", help="a literal wins")\n'
            "def lit():\n"
            "    pass\n"
            '@app.command("doc", help=t("hc_ignored"))\n'
            "def doc():\n"
            '    """a docstring beats the key."""\n'
            "    pass\n"
        )
        found = self.commands(source)
        self.assertEqual((found["lit"].summary, found["lit"].summary_key), ("a literal wins", ""))
        self.assertEqual((found["doc"].summary, found["doc"].summary_key), ("a docstring beats the key.", ""))

    def test_string_table_reads_annotated_tuple_and_plain_values_only(self):
        from asgard.map_graph.extract_python import extract_string_table

        table = extract_string_table(self._TABLE)
        self.assertEqual(table["hc_tk_board"], "the board as it stands, in status columns")
        self.assertEqual(table["hc_plain"], "one sentence")
        # 계산된 값은 소스만 읽어서 결과를 알 수 없다 — 반쪽을 적느니 비운다.
        self.assertNotIn("hc_computed", table)

    def test_resolution_fills_known_keys_and_leaves_unknown_ones_empty(self):
        from asgard.map_graph.extract_python import extract_python, extract_string_table, resolve_summaries

        resolved = {
            item.name: item
            for item in resolve_summaries(extract_python("cli.py", self._CLI), extract_string_table(self._TABLE))
            if item.kind == "command"
        }
        self.assertEqual(resolved["ticket board"].summary, "the board as it stands, in status columns")
        self.assertEqual(resolved["ticket board"].summary_key, "")
        # 표에 없는 열쇠는 열쇠 이름을 역할 문장으로 승격시키지 않는다.
        self.assertEqual(resolved["ticket orphan"].summary, "")

    def test_scan_puts_a_table_declared_command_into_the_routing_catalog(self):
        from asgard.map_graph import scan_graph

        self.seed()
        self.write("src/app/cli.py", self._CLI)
        self.write("src/app/i18n.py", self._TABLE)
        with open(scan_graph(self.root).graph_md_path, encoding="utf-8") as stream:
            body = stream.read()
        # 라우팅되는 것은 `## Commands` 절뿐이다 — 파일별 관계나 시드에 이름이 있는 것은 라우팅이 아니다.
        catalog = body.split("## Commands", 1)[1].split("\n## ", 1)[0]
        self.assertIn("- `ticket board` — the board as it stands, in status columns", catalog)
        # 역할을 못 밝힌 명령은 여전히 카탈로그 밖이다 — 이 수리가 문턱을 내린 것은 아니다.
        self.assertNotIn("ticket orphan", catalog)


class TestTsJsExtractor(Base):
    def test_express_routes_calls_services_and_prisma_models(self):
        from asgard.map_graph.extract_tsjs import extract_tsjs

        found = {}
        for item in extract_tsjs("web/server.ts", _TS_FIXTURE):
            found.setdefault(item.kind, []).append(item)
        self.assertEqual({e.name for e in found["route"]}, {"GET /health", "POST /orders"})
        self.assertTrue(all(e.confidence == "confirmed" for e in found["route"]))
        confidences = {e.name: e.confidence for e in found["api_call"]}
        self.assertEqual(confidences["https://api.example.com/v1/items"], "confirmed")
        self.assertEqual(confidences["/internal/items"], "candidate")
        self.assertEqual({e.name for e in found["external_service"]}, {"stripe"})
        models = extract_tsjs("web/schema.prisma", _PRISMA_FIXTURE)
        self.assertEqual([(e.kind, e.name, e.confidence) for e in models], [("model", "Order", "confirmed")])

    def test_unbound_express_like_receiver_is_candidate(self):
        from asgard.map_graph.extract_tsjs import extract_tsjs

        routes = [e for e in extract_tsjs("web/fake.ts", "app.get('/x', handler)") if e.kind == "route"]
        self.assertEqual(routes[0].confidence, "candidate")


if __name__ == "__main__":
    unittest.main(verbosity=1)
