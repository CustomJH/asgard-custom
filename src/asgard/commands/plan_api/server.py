"""기획 화면의 HTTP 계약 — 루프백 전용, 의존성 0.

경로는 두 갈래뿐이다. **읽기**는 문서·진척·심사를 한 왕복에 넣어 주고(`GET /api/plans/<id>`),
문서 한 장을 마크다운으로 내보내는 문이 하나 더 있다(`GET /api/plans/<id>/export`).
**쓰기**는 셋 중 하나다:

  · `/edit`      손으로 고치기 — 연산 이름은 `plan.edits.OPS`가 전량이다
  · `/ask · /prd · /spec · /flow · /chat`   모델을 불러 문서를 짓기
  · `/refine`    고칠 글을 **돌려주기만** 한다 (반영은 사람이 `/edit`으로 누른다)

모델을 부르는 경로는 오래 걸리고 실패할 수 있다. 그래서 실패를 502로 내보내되 **무엇이
왜 실패했는지**를 같이 준다 — 화면이 "잠시 후 다시"라고만 말하면 사용자는 provider 설정이
비어 있다는 것을 영원히 모른다.
"""

from __future__ import annotations

import json
import os
from importlib.resources import files as _files
from urllib.parse import urlsplit

from ... import errors
from ...plan import build, edits, folders, store

# 파사드에서 `plan.review`는 같은 이름의 모듈이 아니라 **함수**다(`plan/__init__.py`). 여기서
# 모듈 경로로 직접 들여오는 이유는 그 가림을 읽는 사람이 매번 되짚지 않게 하려는 것이다.
from ...plan.export import to_markdown
from ...plan.review import GRADE_LABEL, review
from .. import loopback

# 루프백 경계와 응답 헤더는 세 창이 한 곳을 같이 쓴다 (`commands.loopback`) — 세 곳에 적으면
# 고칠 때 세 번 고쳐야 하고 언젠가 두 번만 고친다.
_LOOPBACK_HOSTS = loopback.LOOPBACK_HOSTS
_MAX_BODY_BYTES = 512_000
host_allowed = loopback.host_allowed
origin_allowed = loopback.origin_allowed


def plan_view(plan_id: str) -> dict:
    """화면이 한 번에 받는 것 — 문서·진척·심사·다음 할 일·트리. 나눠 주면 왕복마다 어긋난다.

    `review`는 `readiness['prd']`가 든 점수 세 칸의 원본이다. 두 칸을 다 싣는 이유는 쓰는
    자리가 다르기 때문이다 — 진척은 탭이 읽고, 지적·칸별 상태·가정 목록은 PRD 화면이 읽는다.
    `grades`는 등급의 사람 이름표다: 화면이 등급 이름을 HTML 에 베껴 적으면 정본이 둘이 된다."""
    plan = store.load_plan(plan_id)
    return {
        "plan": plan,
        "readiness": store.readiness(plan),
        "review": review(plan),
        "grades": dict(GRADE_LABEL),
        "next": store.next_step(plan),
        "tree": store.spec_tree(plan),
    }


def dispatch(method: str, path: str, body: bytes = b"", root: str | None = None) -> tuple[int, str, bytes]:
    """`root`는 이제 **경계가 아니다.**

    기획은 워크스페이스 하나에 있다. 그래서 창이 어느 폴더를 보고 있든 목록은 같고, root가
    하는 일은 둘뿐이다 — 새 기획에 폴더 링크를 걸어 주는 것(`?root=`로 끌 수 있다), 그리고
    모델을 부를 때 설정을 어디서 읽을지 정하는 것."""
    root = os.path.abspath(root or os.getcwd())
    if path == "/api/plans":
        if method in ("GET", "HEAD"):
            return _json(200, {**store.list_plans(), "pending": _pending_roots(root)})
        if method == "POST":
            try:
                payload = _payload(body)
                # `mode`는 저장만 한다 — `auto`라도 여기서 PRD를 짓지 않는다. 한 왕복에 묶으면
                # 진행 표시가 사라지고, 실패했을 때 기획이 안 만들어진 것인지 초안만 실패한
                # 것인지 화면이 구분하지 못한다.
                plan = store.create_plan(
                    payload.get("idea", ""),
                    payload.get("title", ""),
                    str(payload.get("root") or ""),
                    str(payload.get("mode") or ""),
                    payload.get("engine"),
                )
                return _json(201, plan_view(plan["id"]))
            except ValueError as exc:
                return _api_error(400, "invalid_plan", str(exc))
        return _api_error(405, "method_not_allowed", "method not allowed")

    if path == "/api/plans/import":
        if method != "POST":
            return _api_error(405, "method_not_allowed", "method not allowed")
        try:
            target = str(_payload(body).get("root") or "")
            if not target:
                raise ValueError("root is required")
            imported = folders.import_root(target)
        except ValueError as exc:
            return _api_error(400, "invalid_plan", str(exc))
        # `imported`와 목록을 통째로 겹치면 `plans`가 **건수에서 목록으로** 바뀐다(둘 다 그
        # 이름을 쓴다). 화면이 "기획 [object]건"을 말하게 되는 자리라 결과는 따로 넣는다.
        return _json(200, {"imported": imported, **store.list_plans(), "pending": _pending_roots(root)})

    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[:2] == ["api", "plans"]:
        return _plan_route(method, parts[2], parts[3:], body, root)

    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path == "/asset/logo":
        return 200, "image/png", (_files("asgard") / "assets" / "gold-brand-logo.png").read_bytes()
    if path == "/health":
        return 200, "application/json; charset=utf-8", b'{"ok":true,"surface":"plan"}'
    return 404, "text/plain; charset=utf-8", b"not found"


def _pending_roots(root: str) -> list[str]:
    """폴더에 갇혀 있는 기획이 남은 자리들 — 등록부 전체를 훑는다.

    창은 개인 작업 공간에서 열리므로 그 자리만 보면 옛 기획은 영영 안 보인다. 폴더를 열어야
    알 수 있는 반입은 반입이 아니라 숨김이다."""
    try:
        from ..studio_store import known_roots

        roots = known_roots(root or None)
    except Exception:
        roots = [root] if root else []
    return folders.pending_roots(roots)


def _plan_route(method: str, plan_id: str, tail: list[str], body: bytes, root: str) -> tuple[int, str, bytes]:
    try:
        if not tail and method in ("GET", "HEAD"):
            return _json(200, plan_view(plan_id))
        if not tail and method == "PUT":
            payload = _payload(body)
            if payload.get("id") != plan_id:
                raise ValueError("path id and plan id must match")
            store.save_plan(payload)
            return _json(200, plan_view(plan_id))
        if tail == ["readiness"] and method in ("GET", "HEAD"):
            plan = store.load_plan(plan_id)
            return _json(200, {"readiness": store.readiness(plan), "next": store.next_step(plan)})
        if tail == ["export"] and method in ("GET", "HEAD"):
            # 내보내기는 읽기다 — 그래서 JSON 관문(`X-Asgard-Plan`)이 아니라 다른 GET 경로와
            # 같은 자리를 지난다. 본문은 JSON이 아니라 마크다운 원문이라 화면이 그대로
            # 복사하거나 파일로 내린다.
            return 200, "text/markdown; charset=utf-8", to_markdown(store.load_plan(plan_id)).encode("utf-8")
        if len(tail) == 1 and method == "POST":
            return _plan_action(tail[0], plan_id, _payload(body), root)
    except errors.AsgardError as exc:
        # 코드와 상태는 예외가 든다 — plan_conflict·not_ready 409, unknown_edit 400.
        # (재료가 없어 못 만드는 것은 잘못된 요청이 아니라 **아직 이른 요청**이라 409다.)
        # 이 세 갈래는 전부 ValueError 이기도 하므로 아래 일반 절보다 **반드시 먼저** 온다.
        return loopback.error_result(exc, surface="plan", root=root, where=plan_id)
    except KeyError:
        return _api_error(404, "plan_not_found", "plan not found")
    except ValueError as exc:
        return _api_error(400, "invalid_plan", str(exc))
    except (RuntimeError, OSError, TypeError) as exc:
        # 모델 호출이 죽은 자리 — 화면이 이유를 그대로 읽을 수 있어야 손쓸 곳을 안다
        return _api_error(502, "planner_failed", f"{type(exc).__name__}: {exc}")
    return _api_error(405, "method_not_allowed", "method not allowed")


def _plan_action(action: str, plan_id: str, payload: dict, root: str) -> tuple[int, str, bytes]:
    if action == "delete":
        store.delete_plan(plan_id)
        return _json(200, store.list_plans())
    if action == "edit":
        edits.apply(plan_id, str(payload.get("op") or ""), payload)
        return _json(200, plan_view(plan_id))
    if action == "engine":
        store.set_engine(plan_id, str(payload.get("provider") or ""), str(payload.get("model") or ""))
        return _json(200, plan_view(plan_id))
    if action == "mode":
        # 갈래는 한 번만 고른다. 이미 다른 갈래로 시작했으면 400 invalid_plan 으로 올라간다.
        store.set_mode(plan_id, str(payload.get("mode") or ""))
        return _json(200, plan_view(plan_id))
    if action == "refine":
        # 유일하게 저장하지 않는 쓰기 — 글만 돌려주고 반영은 사람이 누른다
        return _json(200, _refine(plan_id, payload, root))
    return _plan_build(action, plan_id, payload, root)


def _refine(plan_id: str, payload: dict, root: str) -> dict:
    """다듬기 세 갈래 — **좁은 범위가 우선한다.**

    `scope == "document"`면 문서 전체, 고른 글(`selection`)이 들어오면 그 구간만, 그 외에는
    칸 하나다. 좁을수록 사람이 안 고른 자리가 갈릴 확률이 낮으므로 넓은 쪽을 기본으로 두지
    않는다. 고른 글이 그 칸 본문에 없으면 `build`가 모델을 부르기 전에 `ValueError`이고, 그건
    부르는 쪽의 400이다."""
    request = str(payload.get("request") or "")
    if str(payload.get("scope") or "") == "document":
        return build.propose_document(plan_id, request, root)
    section = str(payload.get("section") or "")
    selection = str(payload.get("selection") or "")
    if selection:
        return build.propose_selection(plan_id, section, request, selection, root)
    # 칸 전체 갈래에는 `selection`을 안 넘긴다 — 이 프롬프트는 칸 하나의 대체 본문을 요구하므로
    # 고른 글을 함께 넘기면 칸 전체가 그 구간의 뜻으로 다시 쓰인다.
    return build.propose_section(plan_id, section, request, "", root)


def _plan_build(action: str, plan_id: str, payload: dict, root: str) -> tuple[int, str, bytes]:
    """모델을 불러 문서를 짓는 갈래 — 전부 저장하고 문서 전체를 돌려준다."""
    runner = {
        "ask": lambda: build.ask(plan_id, root),
        "prd": lambda: build.draft_prd(plan_id, root),
        "spec": lambda: build.draft_spec(plan_id, str(payload.get("note") or ""), bool(payload.get("replace")), root),
        "flow": lambda: build.draft_flow(
            plan_id, str(payload.get("note") or ""), bool(payload.get("replace", True)), root
        ),
        "chat": lambda: build.converse(plan_id, str(payload.get("text") or ""), root),
    }.get(action)
    if runner is None:
        return _api_error(404, "unknown_action", f"unknown plan action: {action}")
    runner()
    return _json(200, plan_view(plan_id))


class _Handler(loopback.LoopbackHandler):
    server_version = "AsgardPlanDashboard"

    def _route(self, head_only: bool = False) -> None:
        if not host_allowed(self.headers.get("Host")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden host", head_only)
            return
        path = urlsplit(self.path).path
        body = b""
        if self.command in ("POST", "PUT") and path.startswith("/api/"):
            if (
                self.headers.get("X-Asgard-Plan") != "1"
                or not self.headers.get("Content-Type", "").lower().startswith("application/json")
                or not origin_allowed(self.headers.get("Origin"))
            ):
                self._send(*_api_error(403, "forbidden", "local JSON request required"), head_only)
                return
            try:
                size = int(self.headers.get("Content-Length") or -1)
            except ValueError:
                size = -1
            if size < 0:
                self._send(*_api_error(411, "length_required", "Content-Length is required"), head_only)
                return
            if size > _MAX_BODY_BYTES:
                self._send(*_api_error(413, "payload_too_large", "request body is too large"), head_only)
                return
            body = self.rfile.read(size)
        root = getattr(self.server, "root", os.getcwd())
        try:
            status, ctype, body = dispatch(self.command, path, body, root)
        except Exception as exc:
            if path.startswith("/api/"):
                status, ctype, body = loopback.error_result(exc, surface="plan", root=root, where=path)
            else:
                status, ctype, body = 500, "text/plain; charset=utf-8", f"error: {type(exc).__name__}".encode()
        self._send(status, ctype, body, head_only)

    _send = loopback.LoopbackHandler.send_guarded

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def do_POST(self) -> None:
        self._route()

    def do_PUT(self) -> None:
        self._route()


class _RootServer(loopback.LoopbackServer):
    root: str


def _bind(host: str, port: int, root: str | None = None) -> _RootServer:
    try:
        httpd = _RootServer((host, port), _Handler)
    except OSError:
        httpd = _RootServer((host, 0), _Handler)
    httpd.root = os.path.abspath(root or os.getcwd())
    return httpd


# 창을 여는 문은 여기 없다 — 기획은 **스튜디오 안에서만** 쓴다(`asgard open studio`의 기획
# 목적지). 여태 이 자리엔 스튜디오를 `?view=plan`으로 열어 주는 `run_dashboard`가 있었고,
# 그래서 같은 창에 이름이 둘이었다. 이 모듈이 지는 것은 계약뿐이다: `dispatch`는
# `commands.studio.routes`가 `/api/plans*`에서 부른다.


def _payload(body: bytes) -> dict:
    if len(body) > _MAX_BODY_BYTES:
        raise ValueError("request body is too large")
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    return payload


def _json(status: int, value: object) -> tuple[int, str, bytes]:
    # `allow_nan=False`가 이 표면의 추가 조건이다 — 기획 문서에 NaN이 들어가면 화면의
    # JSON.parse가 통째로 죽는다. 나머지 모양은 공용 계약과 같다.
    return status, loopback.JSON_TYPE, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


_api_error = loopback.api_error
