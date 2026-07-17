"""Provider authentication commands owned by Asgard."""

from __future__ import annotations

import sys


def _require_openai_native(provider: str) -> None:
    if provider != "openai-native":
        raise ValueError("supported OAuth provider: openai-native")


def run_login(provider: str) -> int:
    from .. import openai_codex

    try:
        _require_openai_native(provider)
        def notify(message: str) -> None:
            sys.stdout.write(message + "\n")

        tokens = openai_codex.device_login(notify)
        openai_codex.save_tokens(tokens)
    except (ValueError, openai_codex.OAuthError) as exc:
        sys.stderr.write(f"Authentication failed: {exc}\n")
        return 2
    sys.stdout.write("OpenAI Codex: logged in with ChatGPT (Asgard-owned OAuth session).\n")
    return 0


def run_status(provider: str) -> int:
    from .. import openai_codex

    try:
        _require_openai_native(provider)
        ok, detail = openai_codex.login_status()
    except (ValueError, openai_codex.OAuthError) as exc:
        sys.stdout.write(f"OpenAI Codex: not logged in ({exc})\n")
        return 1
    sys.stdout.write(f"OpenAI Codex: {detail}.\n")
    return 0 if ok else 1


def run_logout(provider: str) -> int:
    from .. import openai_codex

    try:
        _require_openai_native(provider)
        removed = openai_codex.logout()
    except (ValueError, openai_codex.OAuthError) as exc:
        sys.stderr.write(f"Logout failed: {exc}\n")
        return 2
    sys.stdout.write("OpenAI Codex: logged out.\n" if removed else "OpenAI Codex: no stored login.\n")
    return 0
