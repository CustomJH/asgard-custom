"""memory 커맨드의 공용 바닥 — 승인 계획의 보관·선점, 그리고 모든 run_* 가 쓰는 오류 봉투.

`_guard` 가 35곳, `_emit` 이 15곳에서 불린다. 명령을 표면별로 갈랐어도 이 둘은 한 자리에
있어야 오류 문구와 종료 코드가 갈라지지 않는다."""

import contextlib
import hashlib
import hmac
import json as _json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable

from ... import errors, memory

_PLAN_ID = re.compile(r"^[0-9a-f]{64}$")
_PLAN_THREAD_LOCK = threading.Lock()
PERSONAL_CLAIM_LEASE_SECONDS = 300


def _pending_dir() -> str:
    d = os.path.join(memory.ensure_home(), ".pending-plans")
    if os.path.islink(d):
        # 심링크면 승인 대기 계획이 어디에 적히는지 우리가 모른다 — 환경이 안 된 것이지
        # 부른 쪽이 틀린 게 아니다 (exit 1).
        raise errors.Unavailable("personal approval directory must not be a symlink")
    os.makedirs(d, mode=0o700, exist_ok=True)
    memory._chmod(d, 0o700)
    return d


def _save_plan(text: str, kind: str, plan: dict) -> str:
    text_sha256 = hashlib.sha256(text.encode()).hexdigest()
    raw = _json.dumps(
        {"text_sha256": text_sha256, "kind": kind, "plan": plan},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    plan_id = hashlib.sha256(raw.encode()).hexdigest()
    memory._atomic_write(os.path.join(_pending_dir(), f"{plan_id}.json"), raw)
    return plan_id


def _load_plan(plan_id: str, text: str, kind: str) -> dict:
    if not _PLAN_ID.fullmatch(plan_id):
        raise ValueError("invalid approval plan id")
    path = os.path.join(_pending_dir(), f"{plan_id}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as e:
        raise ValueError("approval plan not found or already consumed — re-run ingest") from e
    if not hmac.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), plan_id):
        raise ValueError("approval plan integrity check failed — re-run ingest")
    payload = _json.loads(raw)
    text_matches = payload.get("text") == text or hmac.compare_digest(
        str(payload.get("text_sha256") or ""), hashlib.sha256(text.encode()).hexdigest()
    )
    if not text_matches or payload.get("kind") != kind or not isinstance(payload.get("plan"), dict):
        raise ValueError("approval plan does not match text/kind — re-run ingest")
    return payload["plan"]


@contextlib.contextmanager
def _personal_plan_guard():
    """개인 approval 파일의 프로세스·스레드 공통 claim lock."""
    with _PLAN_THREAD_LOCK:
        with memory._lock(_pending_dir()):
            yield


def _claimed_path(plan_id: str, token: str) -> str:
    return os.path.join(_pending_dir(), f"{plan_id}.{token}.claimed.json")


def _recover_stale_claim(plan_id: str) -> None:
    """lease가 만료된 crash claim을 pending으로 되돌린다. 호출자는 plan guard를 보유한다."""
    pending = _pending_dir()
    original = os.path.join(pending, f"{plan_id}.json")
    if os.path.exists(original):
        return
    prefix, suffix = f"{plan_id}.", ".claimed.json"
    for name in sorted(os.listdir(pending)):
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        claimed = os.path.join(pending, name)
        try:
            if time.time() - os.stat(claimed, follow_symlinks=False).st_mtime > PERSONAL_CLAIM_LEASE_SECONDS:
                os.replace(claimed, original)
                return
        except OSError:
            continue


def _claim_plan(plan_id: str, text: str, kind: str) -> tuple[dict, str]:
    """approval ID를 원자 claim한다. ingest 실패 시 _finish_plan(..., success=False)로 복구한다."""
    with _personal_plan_guard():
        _recover_stale_claim(plan_id)
        plan = _load_plan(plan_id, text, kind)
        token = secrets.token_hex(8)
        os.replace(
            os.path.join(_pending_dir(), f"{plan_id}.json"),
            _claimed_path(plan_id, token),
        )
        return plan, token


def _finish_plan(plan_id: str, token: str, *, success: bool) -> None:
    with _personal_plan_guard():
        claimed = _claimed_path(plan_id, token)
        if success:
            with contextlib.suppress(OSError):
                os.remove(claimed)
            return
        original = os.path.join(_pending_dir(), f"{plan_id}.json")
        if os.path.exists(claimed) and not os.path.exists(original):
            os.replace(claimed, original)


def _guard(fn: Callable[[], int]) -> int:
    """공통 예외 변환 — ValueError는 처방 메시지, 그 외는 짧은 오류 한 줄 (traceback 금지).

    문장을 여기서 조립하지 않고 `errors.render_cli`에 넘기는 이유는 표면이 둘이기 때문이다:
    `--json`을 받은 실행에서 실패만 사람 말로 나가면 자식 프로세스로 이 명령을 띄운 쪽이
    파싱할 것을 못 찾는다. 어느 얼굴로 그릴지는 `errors.set_json_surface`가 이미 정해 뒀다."""
    try:
        return fn()
    except errors.AsgardError as e:
        errors.render_cli(e)
        return e.exit_code
    except ValueError as e:
        # 이 표면에서 ValueError는 "그대로는 받을 수 없는 요청"이라는 뜻이다 — 잘못된 slug,
        # 어긋난 계획, 짝이 안 맞는 플래그. 정본의 InvalidInput 자리이므로 2로 나간다.
        # 환경이 안 된 자리(연결 안 됨·미신뢰)는 그 자리에서 Unavailable을 던져 1로 남는다.
        err = _error(str(e))
        errors.render_cli(err)
        return err.exit_code
    except Exception as e:  # 파일 권한·손상 등 — 사용자용 한 줄로
        err = errors.coerce(e)
        errors.render_cli(err)
        return err.exit_code


# 이 표면이 쓰는 코드 → 정본 갈래. 종료 코드는 갈래가 정한다 (`errors.py`): 호출자가 고칠 수
# 있는 잘못은 2, 환경이 안 된 것은 1. 모르는 코드는 `AsgardError`로 떨어져 1이 된다 — 무엇을
# 고쳐야 하는지 모르는 실패를 "고칠 수 있다"고 선언하지 않는다.
_CANON: dict[str, type[errors.AsgardError]] = {
    "invalid_input": errors.InvalidInput,
    "not_found": errors.NotFound,
    "conflict": errors.Conflict,
    "unavailable": errors.Unavailable,
    "upstream_error": errors.UpstreamError,
}


def _error(
    message: str, *, code: str = "invalid_input", remedy: str = "", detail: dict | None = None
) -> errors.AsgardError:
    """이 표면의 실패 한 건 — 종료 코드는 여기서 안 정한다.

    여태 이 자리가 1을 손으로 박아서, 같은 "없는 페이지"가 `memory show`에서는 1이고
    `skills show`에서는 2였다. 종료 코드로 분기하는 쪽(CI·훅·스튜디오)은 그 차이를 명령별로
    외워야 했다. 이제 갈래만 고르고 숫자는 `_CANON`이 가리키는 정본 클래스가 정한다."""
    return _CANON.get(code, errors.AsgardError)(message, code=code, remedy=remedy, detail=detail or {})


def _fail(message: str, *, code: str = "invalid_input", remedy: str = "", detail: dict | None = None) -> int:
    """실패를 이 실행의 표면으로 내고 종료 코드를 돌려준다 — 사람은 ✘ 한 줄, `--json`은 error 봉투."""
    err = _error(message, code=code, remedy=remedy, detail=detail)
    errors.render_cli(err)
    return err.exit_code


def _emit(payload: dict) -> None:
    """`--json` 산출물 — 사람 문장이 차지하던 stdout을 이것 하나가 받는다."""
    print(_json.dumps(payload, ensure_ascii=False, indent=2))
