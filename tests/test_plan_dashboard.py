"""Asgard Plan 로컬 목업의 라우팅·보안 헤더·라이브 서버 계약."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from asgard.commands import plan_dashboard as plan


class TestDispatch(unittest.TestCase):
    def test_root_serves_selfcontained_interactive_html(self):
        status, ctype, body = plan.dispatch("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        page = body.decode("utf-8")
        self.assertIn("<!doctype html>", page.lower())
        self.assertIn("Asgard Plan", page)
        self.assertIn("Studio로 보내기", page)
        self.assertNotIn('src="http', page)

    def test_logo_and_health_routes(self):
        status, ctype, body = plan.dispatch("GET", "/asset/logo")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

        status, ctype, body = plan.dispatch("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(body), {"ok": True, "surface": "plan"})

    def test_head_is_allowed_but_mutation_and_unknown_routes_are_not(self):
        self.assertEqual(plan.dispatch("HEAD", "/")[0], 200)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(plan.dispatch(method, "/")[0], 405)
        self.assertEqual(plan.dispatch("GET", "/missing")[0], 404)


class TestHostGuard(unittest.TestCase):
    def test_loopback_allowed(self):
        for host in ("127.0.0.1", "127.0.0.1:8767", "localhost:8767", "[::1]:8767", "LOCALHOST"):
            self.assertTrue(plan.host_allowed(host), host)

    def test_external_rejected(self):
        for host in (None, "", "evil.example", "evil.example:8767", "10.0.0.5:80"):
            self.assertFalse(plan.host_allowed(host), repr(host))


class TestLiveServer(unittest.TestCase):
    def test_roundtrip_security_headers_and_forbidden_host(self):
        httpd = plan._bind("127.0.0.1", 0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["surface"], "plan")
                self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

            request = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(rejected.exception.code, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
