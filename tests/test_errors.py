"""오류 계층 — 사실은 예외가 들고, 문장은 표면이 만든다.

여기서 못 박는 것은 세 가지다:
  · 예외 하나가 코드·처방·상태를 **스스로** 안다 (경계마다 매핑을 다시 적지 않는다)
  · 기존 `except ValueError` / `except RuntimeError` 가 계속 잡는다 (하위 호환)
  · 경계를 건널 때 사실이 안 깎인다 (JSON 한 겹, 그리고 삼킨 예외의 흔적)
"""

import json
import os
import tempfile
import unittest

from asgard import errors
from asgard.commands import loopback


class TestErrorFacts(unittest.TestCase):
    def test_an_error_carries_code_remedy_and_status(self):
        err = errors.InvalidInput("티켓 제목이 비었습니다", remedy="제목을 한 줄 적어 주세요")
        self.assertEqual((err.code, err.http_status, err.exit_code), ("invalid_input", 400, 2))
        self.assertEqual(err.remedy, "제목을 한 줄 적어 주세요")

    def test_str_is_still_just_the_message(self):
        """호출부 수백 곳이 `str(exc)`로 읽는다 — 그 계약을 깨면서 얻을 것이 없다."""
        self.assertEqual(str(errors.NotFound("ticket not found: NOR-9")), "ticket not found: NOR-9")

    def test_empty_fields_are_absent_not_blank(self):
        """빈 처방을 `""`로 실으면 소비자가 '없다'와 '비었다'를 구별하지 못한다."""
        payload = errors.Conflict("이미 닫힌 티켓입니다").to_dict()
        self.assertEqual(set(payload), {"code", "message"})

    def test_envelope_is_the_one_wire_shape(self):
        env = errors.Unavailable("저장소를 열 수 없습니다", remedy="다시 열어 보세요").envelope()
        self.assertEqual(env["error"]["code"], "unavailable")
        self.assertEqual(env["error"]["remedy"], "다시 열어 보세요")

    def test_detail_drops_what_cannot_be_serialized(self):
        """오류를 내려다 직렬화가 터지면 응답이 통째로 500이 되고 진짜 사유는 사라진다.

        굽지 않고 버리는 이유는 비밀이다 — 낯선 객체의 repr에 무엇이 들었는지 모르는데
        이 dict는 HTTP 응답과 디스크 흔적 양쪽으로 나간다. 다만 버렸다는 사실은 남긴다."""
        payload = errors.InvalidInput("x", detail={"ok": [1, 2], "sock": object()}).to_dict()
        self.assertEqual(payload["detail"], {"ok": [1, 2], "_dropped": ["sock"]})

    def test_a_clean_detail_gains_no_dropped_marker(self):
        payload = errors.InvalidInput("x", detail={"ok": 1}).to_dict()
        self.assertEqual(payload["detail"], {"ok": 1})

    def test_the_envelope_always_serializes(self):
        """이 계층의 존재 이유 — 어떤 맥락이 실려도 응답이 나가야 한다."""
        err = errors.InvalidInput("x", detail={"proc": object(), "nan": float("inf")})
        self.assertTrue(json.dumps(err.envelope(), ensure_ascii=False))

    def test_detail_caps_a_runaway_value(self):
        payload = errors.InvalidInput("x", detail={"blob": "가" * 50_000}).to_dict()
        self.assertLess(len(payload["detail"]["blob"]), 5_000)


class TestCoerce(unittest.TestCase):
    def test_a_known_error_passes_through_untouched(self):
        """감싸면 하위 클래스가 정한 상태와 처방이 500에 먹힌다 — 그게 여태 경계의 일이었다."""
        original = errors.Unavailable("보드를 못 엽니다", remedy="다시 여세요")
        self.assertIs(errors.coerce(original), original)
        self.assertEqual(errors.coerce(original).http_status, 503)

    def test_a_stranger_becomes_a_500_that_still_names_itself(self):
        err = errors.coerce(KeyError("root"))
        self.assertEqual((err.code, err.http_status), ("internal_error", 500))
        self.assertIn("KeyError", err.message)


class TestDomainErrorsKnowTheirStatus(unittest.TestCase):
    """상태 코드는 표가 아니라 예외가 든다. 표가 여러 벌이면 언젠가 한 벌만 고친다."""

    def test_each_domain_error_maps_itself(self):
        from asgard.plan import edits, store
        from asgard.studio import db, projects, teams, tickets

        for exc, code, status in (
            (tickets.TicketError("bad"), "invalid_ticket", 400),
            (teams.TeamError("bad"), "invalid_team", 400),
            (projects.ProjectError("bad"), "invalid_project", 400),
            (db.StoreError("shut"), "store_unavailable", 503),
            (store.RevisionConflict("stale"), "plan_conflict", 409),
            (store.PlanNotReady("empty"), "not_ready", 409),
            (edits.UnknownOp("nope"), "unknown_edit", 400),
        ):
            with self.subTest(code=code):
                self.assertEqual((exc.code, exc.http_status), (code, status))

    def test_the_old_base_classes_still_catch_them(self):
        """이 예외들을 `except ValueError`로 받는 자리가 아직 남아 있다."""
        from asgard.plan import store
        from asgard.studio import db, tickets

        self.assertIsInstance(tickets.TicketError("x"), ValueError)
        self.assertIsInstance(store.PlanNotReady("x"), ValueError)
        self.assertIsInstance(db.StoreError("x"), RuntimeError)
        self.assertIsInstance(tickets.TicketError("x"), errors.AsgardError)


class TestHttpBoundary(unittest.TestCase):
    def test_a_domain_error_keeps_its_status_and_code(self):
        from asgard.studio import db

        status, ctype, body = loopback.error_result(db.StoreError("보드를 못 엽니다"))
        self.assertEqual(status, 503)
        self.assertIn("json", ctype)
        self.assertEqual(json.loads(body)["error"]["code"], "store_unavailable")

    def test_an_unknown_exception_is_json_not_a_bare_type_name(self):
        """여태 여기서 나가던 것은 `error: KeyError` 한 줄이었다 — JSON이 아니라 창이 못 읽었다."""
        status, ctype, body = loopback.error_result(KeyError("root"))
        self.assertEqual(status, 500)
        self.assertIn("json", ctype)
        self.assertEqual(json.loads(body)["error"]["code"], "internal_error")

    def test_a_remedy_rides_along_when_there_is_one(self):
        err = errors.PreflightFailed("막혔습니다", remedy="claude /login")
        body = json.loads(loopback.error_result(err)[2])
        self.assertEqual(body["error"]["remedy"], "claude /login")


class TestTheTrail(unittest.TestCase):
    """삼킨 예외는 어딘가 남아야 한다 — 안 남기면 한 줄이 사고의 전부가 된다."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="asgard-errtrace-")

    def _lines(self):
        path = errors.trace_path(self.root)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_a_swallowed_exception_leaves_a_traceback(self):
        try:
            raise KeyError("missing-root")
        except KeyError as exc:
            loopback.error_result(exc, surface="studio", root=self.root, where="/api/tasks")
        rows = self._lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["surface"], rows[0]["where"]), ("studio", "/api/tasks"))
        self.assertIn("KeyError", rows[0]["traceback"])

    def test_client_mistakes_are_not_incidents(self):
        """400은 사고가 아니다 — 전부 적으면 진짜 사고가 잡음에 묻힌다."""
        loopback.error_result(errors.InvalidInput("제목이 비었습니다"), surface="studio", root=self.root)
        self.assertEqual(self._lines(), [])

    def test_the_trail_can_be_switched_off(self):
        os.environ["ASGARD_ERROR_TRACE"] = "off"
        self.addCleanup(os.environ.pop, "ASGARD_ERROR_TRACE", None)
        loopback.error_result(RuntimeError("boom"), surface="studio", root=self.root)
        self.assertEqual(self._lines(), [])

    def test_writing_the_trail_never_breaks_the_response(self):
        """진단이 실행을 인질로 잡는 순간 진단이 아니게 된다."""
        status, _, body = loopback.error_result(RuntimeError("boom"), surface="studio", root="/proc/nonexistent/nope")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body)["error"]["code"], "internal_error")


class TestPreflightBecomesOneFact(unittest.TestCase):
    def setUp(self):
        from asgard.commands import start

        self.start = start

    def test_a_clean_checklist_is_not_a_failure(self):
        self.assertIsNone(self.start.preflight_error([{"name": "provider", "ok": True, "detail": "", "fix": ""}]))

    def test_the_first_actionable_fix_becomes_the_remedy(self):
        """처방이 다시 목록이 되면 사람이 무엇부터 할지 못 고른다 — 나머지는 detail에 남는다."""
        checks = [
            {"name": "provider", "ok": True, "detail": "ok", "fix": ""},
            {"name": "claude CLI", "ok": False, "detail": "not found", "fix": "설치하세요"},
            {"name": "SDK", "ok": False, "detail": "missing", "fix": "asgard update"},
        ]
        err = self.start.preflight_error(checks)
        self.assertEqual(err.code, "preflight_failed")
        self.assertEqual(err.remedy, "설치하세요")
        self.assertIn("claude CLI", err.message)
        self.assertIn("SDK", err.message)
        self.assertEqual(len(err.detail["checks"]), 3)
        self.assertEqual([c["name"] for c in err.failed_checks()], ["claude CLI", "SDK"])

    def test_it_exits_two_because_the_environment_is_the_problem(self):
        err = self.start.preflight_error([{"name": "k", "ok": False, "detail": "", "fix": ""}])
        self.assertEqual(err.exit_code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
