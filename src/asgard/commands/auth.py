"""Provider authentication commands owned by Asgard."""

from __future__ import annotations

import json
import sys

from .. import errors

_SUPPORTED = ("openai-native",)


def _require_supported(provider: str) -> None:
    """모르는 provider는 그 자리에서 거절한다.

    여태 이 자리는 `ValueError`를 던졌고 `run_status`가 그것을 "not logged in"으로 삼켰다.
    오타를 친 사용자는 로그인이 풀렸다고 읽고 다시 로그인하러 갔다 — 사유가 아예 다른데
    화면이 같았다."""
    if provider not in _SUPPORTED:
        raise errors.InvalidInput(
            f"unsupported OAuth provider: {provider}",
            remedy=f"run: asgard auth status {_SUPPORTED[0]}",
            detail={"provider": provider, "supported": list(_SUPPORTED)},
        )


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_login(provider: str) -> int:
    from .. import openai_codex

    _require_supported(provider)
    try:

        def notify(message: str) -> None:
            sys.stdout.write(message + "\n")

        tokens = openai_codex.device_login(notify)
        openai_codex.save_tokens(tokens)
    except (ValueError, openai_codex.OAuthError) as exc:
        raise errors.UpstreamError(
            f"Authentication failed: {exc}",
            remedy="브라우저에서 승인을 끝낸 뒤 다시 시도하세요",
            detail={"provider": provider},
            exit_code=2,
        ) from exc
    sys.stdout.write("OpenAI Codex: logged in with ChatGPT (Asgard-owned OAuth session).\n")
    return 0


def run_status(provider: str, json_out: bool = False) -> int:
    """로그인이 아직 유효한가 — 종료 코드 1은 실패가 아니라 "안 되어 있다"는 답이다."""
    from .. import openai_codex

    errors.set_json_surface(json_out)
    _require_supported(provider)
    try:
        ok, detail = openai_codex.login_status()
    except openai_codex.OAuthError as exc:
        ok, detail = False, str(exc)
    if json_out:
        _emit({"provider": provider, "logged_in": ok, "detail": detail})
    else:
        sys.stdout.write(f"OpenAI Codex: {detail}.\n")
    return 0 if ok else 1


def run_logout(provider: str, json_out: bool = False) -> int:
    from .. import openai_codex

    errors.set_json_surface(json_out)
    _require_supported(provider)
    try:
        removed = openai_codex.logout()
    except (ValueError, openai_codex.OAuthError) as exc:
        raise errors.Unavailable(
            f"Logout failed: {exc}", remedy="~/.asgard/auth.json 권한을 확인하세요", detail={"provider": provider}
        ) from exc
    if json_out:
        _emit({"provider": provider, "logged_out": True, "removed": removed})
    else:
        sys.stdout.write("OpenAI Codex: logged out.\n" if removed else "OpenAI Codex: no stored login.\n")
    return 0
