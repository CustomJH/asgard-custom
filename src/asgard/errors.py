"""오류의 정본 — 무엇이 틀어졌고, 무엇을 하면 되는가.

여태 이 저장소의 실패는 **발화 지점에서 터미널용으로 이미 조립**되어 있었다. `run --json`의
프리플라이트 실패가 그 표본이다: ANSI로 칠한 ✔/✘ 체크리스트를 stdout에 적고 2로 끝냈다.
사람이 터미널에서 보면 읽을 만하지만, 그 명령을 자식 프로세스로 띄우는 스튜디오는 JSON을
기다리다 아무것도 못 찾고 **그 체크리스트 원문을 결과 칸에 통째로 부어** 놓았다. 창에서 본
난잡함은 화면의 잘못이 아니라, 오류가 자기를 어떻게 보일지까지 스스로 정해 버린 탓이다.

그래서 규칙은 하나다 — **오류는 사실만 든다. 문장은 표면이 만든다.**

  · 사실: `code`(기계가 분기하는 이름) · `message`(무엇이 틀어졌나) · `remedy`(무엇을 하면
    되나) · `detail`(구조화된 맥락). 여기까지가 예외의 몫이다.
  · 문장: 터미널은 `render_cli`, HTTP는 `envelope`, 창은 그 envelope을 읽어 자기 방식으로
    그린다. 세 표면이 같은 사실을 각자의 얼굴로 낸다.

`remedy`가 새로 생긴 칸이다. 처방은 여태 프리플라이트 체크리스트의 `fix` 문자열과 `ui.warn`
산문 안에만 살았다 — 즉 터미널 밖으로 나가는 순간 사라졌다. 처방을 필드로 올려야 창이
"실행 못 했습니다" 대신 "claude CLI가 없습니다 → 이렇게 설치하세요"를 말할 수 있다.

**어휘가 둘인 이유.** 여기 코드는 snake_case(`store_unavailable`)이고 `failures.py`의 게이트
코드는 kebab-case(`stale-pass`)다. 우연이 아니라 다른 이름 공간이다: 저쪽은 검증 게이트가
차단한 **사유**를 퀘스트 로그에 영속시키는 어휘고, 이쪽은 예외가 HTTP·CLI 경계를 건널 때
쓰는 어휘다. 이미 배송된 API 응답(`invalid_ticket`·`not_ready`)이 snake_case라 그쪽을 정본으로
둔다 — 표기를 통일하겠다고 나가 있는 계약을 깨지 않는다.
"""

from __future__ import annotations

import os
import time
from typing import Any

# 상세 맥락에 실을 수 있는 최대 크기. 예외가 로그·응답으로 새 나갈 때 통짜 payload가
# 실려 가지 않게 — 오류는 진단이지 덤프가 아니다.
_DETAIL_CAP = 4_000
_MESSAGE_CAP = 2_000


class AsgardError(Exception):
    """아스가르드가 스스로 아는 실패 — 코드와 처방을 담는다.

    하위 클래스는 클래스 속성으로 기본값을 정하고, 필요하면 생성 시 덮어쓴다. `str(exc)`는
    여전히 메시지만 돌려준다 — 기존 호출부 수백 곳이 그렇게 읽고 있고, 그 계약을 깨면서까지
    얻을 것이 없다.
    """

    code: str = "internal_error"
    http_status: int = 500
    exit_code: int = 1

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        remedy: str = "",
        detail: dict[str, Any] | None = None,
        http_status: int | None = None,
        exit_code: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.message = str(message)[:_MESSAGE_CAP]
        super().__init__(self.message)
        if code:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        if exit_code is not None:
            self.exit_code = exit_code
        self.remedy = str(remedy)
        self.detail: dict[str, Any] = dict(detail or {})
        if cause is not None:
            self.__cause__ = cause
        if self.exit_code == 2 and not self.remedy:
            _note_remedyless(self)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """전송 가능한 사실 — 빈 칸은 넣지 않는다.

        비어 있는 `remedy`를 굳이 `""`로 넣으면 소비자가 "처방이 있는데 빈 문자열"과 "처방이
        없다"를 구별하지 못한다. 없으면 키가 없다."""
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.remedy:
            out["remedy"] = self.remedy
        if self.detail:
            out["detail"] = _safe_detail(self.detail)
        return out

    def envelope(self) -> dict[str, Any]:
        """HTTP 본문 한 겹 — 세 창이 이미 `{"error": {...}}`를 읽고 있다."""
        return {"error": self.to_dict()}


# ── 경계에서 자주 쓰는 갈래 ───────────────────────────────────────────────────
# 도메인마다 예외를 새로 만들 것까지는 없지만 상태 코드는 갈라야 하는 자리들.


class InvalidInput(AsgardError):
    """호출자가 고칠 수 있는 잘못 — 400."""

    code = "invalid_input"
    http_status = 400
    exit_code = 2


class NotFound(AsgardError):
    """찾는 것이 없다 — 404."""

    code = "not_found"
    http_status = 404
    exit_code = 2


class Conflict(AsgardError):
    """지금 상태와 어긋난다 — 409. 다시 시도한다고 풀리지 않는다."""

    code = "conflict"
    http_status = 409
    exit_code = 2


class Unavailable(AsgardError):
    """정본을 열 수 없다 — 503. **빈 결과로 가장하지 않는다.**

    이 갈래가 따로 있는 이유가 그것이다. 저장소를 못 열었을 때 빈 목록을 돌려주면 사용자는
    "내 것이 사라졌다"고 읽고, 그 오해 위에서 새로 만들기 시작한다."""

    code = "unavailable"
    http_status = 503
    exit_code = 1


class PreflightFailed(AsgardError):
    """세션을 열 수 없는 환경 — 처방이 붙는 대표적인 실패.

    `detail["checks"]`에 점검 항목이 그대로 들어간다: 각 항목은 `{name, ok, detail, fix}`.
    터미널은 이것을 체크리스트로 그리고, 창은 못 넘은 항목만 카드로 세운다 — **같은 사실,
    다른 얼굴**. 여태 이 사실은 터미널 출력 문자열로만 존재해서 창이 쓸 수 없었다."""

    code = "preflight_failed"
    http_status = 503
    exit_code = 2

    def failed_checks(self) -> list[dict]:
        return [c for c in self.detail.get("checks") or [] if not c.get("ok")]


class UpstreamError(AsgardError):
    """바깥(모델·네트워크·외부 CLI)이 실패했다 — 502. 우리 잘못이 아니라는 것도 사실이다."""

    code = "upstream_error"
    http_status = 502
    exit_code = 1


# ── 처방 없는 exit 2 — 세기만 한다 ────────────────────────────────────────────
# `exit_code == 2`는 "호출자가 고칠 수 있는 잘못"이라는 선언이다. 고칠 수 있다고 해 놓고
# 무엇을 하면 되는지는 안 적으면, 사용자가 받는 것은 사유 한 줄뿐이고 `render_cli`는 처방
# 줄을 아예 안 그린다. 그렇다고 그 자리에서 예외를 던지면 **오류를 내려다 오류가 난다** —
# 진짜 사유가 그 순간 사라지므로 `_safe_detail`이 피하는 함정과 같은 함정이다.
# 그래서 여기서는 만들어진 사실만 남기고, 판정은 테스트가 한다.

_REMEDYLESS_CAP = 64
_remedyless: list[dict[str, str]] = []


def _note_remedyless(err: AsgardError) -> None:
    """처방 없이 만들어진 exit 2 예외 한 건 — 어디서 났는지까지 적는다.

    코드와 메시지만 남기면 테스트가 "어딘가에 처방이 빠졌다"까지만 말하고, 고칠 사람은
    다시 저장소를 뒤져야 한다. 만든 자리를 같이 적어야 그 실패가 곧 작업 지시가 된다."""
    import sys

    where = ""
    try:
        frame = sys._getframe(2)  # 0=여기 · 1=__init__ · 2=예외를 만든 자리
        where = f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_lineno}"
    except ValueError:
        pass
    if len(_remedyless) >= _REMEDYLESS_CAP:
        del _remedyless[0]
    _remedyless.append({"code": err.code, "message": err.message, "where": where})


def remedyless() -> list[dict[str, str]]:
    """처방 없이 만들어진 exit 2 예외들 — 최근 `_REMEDYLESS_CAP`건까지."""
    return list(_remedyless)


def clear_remedyless() -> None:
    _remedyless.clear()


# ── 아무 예외나 이 어휘로 ─────────────────────────────────────────────────────


def coerce(exc: BaseException, *, code: str = "internal_error", remedy: str = "") -> AsgardError:
    """어떤 예외든 경계를 건널 수 있는 모양으로.

    이미 `AsgardError`면 그대로 통과시킨다 — 감싸면 하위 클래스가 정한 상태 코드와 처방이
    `internal_error` 500에 가려진다. 그게 여태 경계에서 벌어지던 일이다."""
    if isinstance(exc, AsgardError):
        return exc
    return AsgardError(
        f"{type(exc).__name__}: {exc}",
        code=code,
        remedy=remedy,
        detail={"exception": type(exc).__name__},
        cause=exc,
    )


def _safe_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """JSON으로 낼 수 있는 것만 남긴다.

    맥락 dict에 프로세스 핸들·소켓 같은 것이 섞여 들어오면 직렬화가 터지고, **오류를 내려다
    오류가 난다**. 그 자리에서 응답이 통째로 500으로 바뀌므로 진짜 사유는 영영 안 보인다.

    직렬화 안 되는 값은 **버린다, `str()`로 굽지 않는다.** 낯선 객체의 repr에는 무엇이든 들어
    있을 수 있고(설정 객체 안의 키·토큰), 이 dict는 HTTP 응답과 디스크 흔적 양쪽으로 나간다.
    진단을 조금 얻자고 비밀을 흘리는 거래는 하지 않는다. 대신 **버렸다는 사실은 남긴다** —
    소리 없이 사라지면 나중에 이 자리를 읽는 사람이 원래 없었다고 오해한다.

    탐침에 `default=` 를 걸면 안 된다: 무엇이든 문자열로 굽혀 버려서 탐침이 영영 성공하고,
    거르는 일을 하나도 안 하게 된다."""
    import json

    out: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in detail.items():
        try:
            encoded = json.dumps(value, ensure_ascii=False)
        except TypeError, ValueError:
            dropped.append(str(key))
            continue
        out[str(key)] = value if len(encoded) <= _DETAIL_CAP else encoded[:_DETAIL_CAP] + "…"
    if dropped:
        out["_dropped"] = dropped
    return out


# ── 이 실행의 표면 ────────────────────────────────────────────────────────────
# `--json`은 명령 하나의 취향이 아니라 **이 실행 전체의 성질**이다: 그 플래그를 받은 순간
# stdout은 기계의 것이 되고, 실패도 성공과 같은 문법으로 나가야 소비자가 한 자리에서 읽는다.
# 그런데 예외는 자기가 어느 표면으로 나갈지 모른다 — 그게 이 모듈의 규칙이다. 그래서
# 플래그를 받은 명령이 경계에 한 줄로 알리고, 마지막 방어선(`cli.main`)은 그 선언을 읽는다.
# 프로세스 하나가 명령 하나를 실행하고 끝나므로 이 상태는 실행 한 번의 수명과 같다.

_json_surface = False


def set_json_surface(on: bool) -> None:
    """이 실행이 `--json` 표면임을 경계에 알린다."""
    global _json_surface
    _json_surface = bool(on)


def json_surface() -> bool:
    return _json_surface


# ── 표면별 얼굴 ───────────────────────────────────────────────────────────────


def render_cli(err: AsgardError) -> None:
    """터미널의 얼굴 — ✘ 한 줄, 처방 한 줄, 그리고 필요하면 점검표.

    `--json`을 받은 실행에서는 그 얼굴이 JSON이다. 실패만 사람 말로 새면 그 표면은 실패를
    다룰 수 없는 표면이 된다 — 자식 프로세스로 이 명령을 띄운 쪽이 파싱할 것을 못 찾고
    원문을 그대로 화면에 붓는다 (`run --json`에서 실제로 벌어지던 일).

    사람용 문장은 **전부 stderr로** 나간다. stdout은 그 명령의 산출물 자리다: 처방 한 줄을
    거기 적으면 `asgard agent show X > out.json`이 데이터 스트림에 사람 말을 받는다. 같은
    이유로 `--quiet`이 처방을 지우지 않는다 — 조용히 하라는 말은 장식을 빼라는 뜻이지,
    무엇을 하면 되는지를 감추라는 뜻이 아니다.

    `ui`를 여기서 늦게 임포트하는 것은 순환 때문이다: `ui`는 테마·윈터미널을 끌고 오고,
    오류 모듈은 그보다 아래에 있어야 어디서든 임포트된다."""
    import sys

    from . import ui

    if _json_surface:
        import json

        sys.stdout.write(json.dumps(json_error(err), ensure_ascii=False) + "\n")
        return

    ui.fail(err.message)
    checks = err.detail.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                _render_check(check)
    if err.remedy:
        sys.stderr.write(f"  {ui.paint(ui._INFO, '→')} {err.remedy}\n")


def _render_check(check: dict) -> None:
    import sys

    from . import ui

    mark = ui.paint("32", "✔") if check.get("ok") else ui.paint("31", "✘")
    sys.stderr.write(f"  {mark} {str(check.get('name', '')).ljust(22)} {ui.dim(str(check.get('detail', '')))}\n")
    if not check.get("ok") and check.get("fix"):
        sys.stderr.write(f"      {ui.paint(ui._INFO, '→')} {check['fix']}\n")


def json_error(err: AsgardError) -> dict[str, Any]:
    """`--json` 표면의 얼굴 — 성공 응답과 같은 자리에서 읽히는 한 겹.

    성공은 `{"result": ...}`, 실패는 `{"error": {...}}`. 소비자는 `error` 키의 유무 하나로
    갈린다 — 종료 코드를 못 보는 자리(파이프 끝, 로그 수집기)에서도 판정이 성립한다."""
    return err.envelope()


# ── 진단 흔적 ─────────────────────────────────────────────────────────────────
# 경계에서 삼킨 예외는 어딘가에 남아야 한다. 안 남기면 "500 error: KeyError" 한 줄이
# 사고의 전부가 되고, 어느 줄에서 났는지는 아무도 모른다.

_TRACE_CAP = 20_000
MAX_BYTES = 2_000_000  # 초과 시 .1로 1세대 로테이션 (io_journal과 같은 규칙)


def trace_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", "errors.jsonl")


def enabled() -> bool:
    return os.environ.get("ASGARD_ERROR_TRACE", "").lower() not in {"0", "off", "false"}


def record(root: str, err: AsgardError, *, surface: str, where: str = "") -> None:
    """경계가 삼킨 예외 한 건을 남긴다 — fail-open.

    기록이 실패해도 조용히 넘어간다. 오류를 적으려다 오류가 나서 응답이 안 나가면, 사용자는
    사유 대신 침묵을 받는다 — 진단이 실행을 인질로 잡는 그 순간 진단이 아니게 된다."""
    if not enabled():
        return
    import json
    import traceback

    entry: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "surface": surface,
        "code": err.code,
        "message": err.message,
        "status": err.http_status,
    }
    if where:
        entry["where"] = where
    if err.detail:
        entry["detail"] = _safe_detail(err.detail)
    cause = err.__cause__ or err
    if cause.__traceback__ is not None:
        entry["traceback"] = "".join(traceback.format_exception(type(cause), cause, cause.__traceback__))[-_TRACE_CAP:]
    try:
        os.makedirs(os.path.join(root, ".asgard", "state"), exist_ok=True)
        gi = os.path.join(root, ".asgard", ".gitignore")
        if not os.path.exists(gi):
            with open(gi, "w", encoding="utf-8") as handle:
                handle.write("*\n")
        path = trace_path(root)
        try:
            if os.path.getsize(path) > MAX_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(path, os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        pass  # fail-open — 진단이 실행을 막지 않는다
