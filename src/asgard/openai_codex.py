"""Asgard-owned ChatGPT OAuth for the OpenAI Codex Responses endpoint.

This is deliberately independent from both ``OPENAI_API_KEY`` and the stock Codex CLI's
``~/.codex/auth.json``.  Asgard creates and refreshes its own OAuth session so refresh-token
rotation in another client cannot silently break this provider.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

AUTH_PATH = Path.home() / ".asgard" / "auth.json"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
OAUTH_ISSUER = "https://auth.openai.com"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = f"{OAUTH_ISSUER}/oauth/token"
_REFRESH_SKEW_SECONDS = 120
_MODEL_CONTEXTS: dict[str, int] = {}


class OAuthError(RuntimeError):
    def __init__(self, message: str, *, code: str = "oauth_error", relogin_required: bool = False):
        super().__init__(message)
        self.code = code
        self.relogin_required = relogin_required


@dataclass(frozen=True)
class RuntimeCredentials:
    access_token: str = field(repr=False)
    account_id: str = ""


def _read_store() -> dict:
    if AUTH_PATH.is_symlink():
        raise OAuthError("Refusing to read a symlinked Asgard auth store.", code="auth_store_unsafe")
    try:
        payload = json.loads(AUTH_PATH.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise OAuthError("Asgard auth store is unreadable; run `asgard auth login openai-native` again.") from exc
    if not isinstance(payload, dict):
        raise OAuthError("Asgard auth store has an invalid shape; run `asgard auth login openai-native` again.")
    return payload


def load_tokens() -> dict[str, str]:
    entry = _read_store().get("openai-native") or {}
    tokens = entry.get("tokens") if isinstance(entry, dict) else None
    if not isinstance(tokens, dict):
        raise OAuthError(
            "No Asgard ChatGPT login. Run `asgard auth login openai-native`.",
            code="auth_missing",
            relogin_required=True,
        )
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    if not access or not refresh:
        raise OAuthError(
            "Asgard ChatGPT login is incomplete. Run `asgard auth login openai-native` again.",
            code="auth_incomplete",
            relogin_required=True,
        )
    return {"access_token": access, "refresh_token": refresh}


def _secure_auth_dir() -> None:
    parent = AUTH_PATH.parent
    if parent.is_symlink():
        raise OAuthError("Refusing to use a symlinked Asgard auth directory.", code="auth_store_unsafe")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)


def _write_store(store: dict) -> None:
    _secure_auth_dir()
    fd, raw_tmp = tempfile.mkstemp(prefix=".auth-", suffix=".tmp", dir=AUTH_PATH.parent)
    tmp = Path(raw_tmp)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(store, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        if AUTH_PATH.is_symlink():
            raise OAuthError("Refusing to replace a symlinked Asgard auth store.", code="auth_store_unsafe")
        os.replace(tmp, AUTH_PATH)
        directory_fd = os.open(AUTH_PATH.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def _save_tokens_unlocked(tokens: dict[str, str]) -> None:
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    if not access or not refresh:
        raise OAuthError("Refusing to store an incomplete ChatGPT OAuth token pair.", code="auth_incomplete")
    store = _read_store()
    store["openai-native"] = {
        "auth_mode": "chatgpt",
        "tokens": {"access_token": access, "refresh_token": refresh},
        "updated_at": int(time.time()),
    }
    _write_store(store)


def save_tokens(tokens: dict[str, str]) -> None:
    with _refresh_lock():
        _save_tokens_unlocked(tokens)


def _logout_unlocked() -> bool:
    store = _read_store()
    if "openai-native" not in store:
        return False
    del store["openai-native"]
    _write_store(store)
    return True


def logout() -> bool:
    with _refresh_lock():
        return _logout_unlocked()


def _jwt_claims(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        value = json.loads(base64.urlsafe_b64decode(encoded))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _account_id(token: str) -> str:
    auth = _jwt_claims(token).get("https://api.openai.com/auth") or {}
    return str(auth.get("chatgpt_account_id") or "").strip() if isinstance(auth, dict) else ""


def _token_expiring(token: str, skew_seconds: int = _REFRESH_SKEW_SECONDS) -> bool:
    exp = _jwt_claims(token).get("exp")
    return isinstance(exp, int | float) and float(exp) <= time.time() + skew_seconds


@contextmanager
def _refresh_lock():
    """Serialize refresh-token rotation across concurrent Asgard processes."""
    import fcntl

    _secure_auth_dir()
    lock_path = AUTH_PATH.with_suffix(".lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _post(url: str, *, json_body: dict | None = None, data: dict | None = None, timeout: float = 20.0):
    import httpx

    headers = {"Accept": "application/json", "User-Agent": "asgard-native"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        return httpx.post(url, json=json_body, data=data, headers=headers, timeout=timeout, follow_redirects=False)
    except Exception:
        raise OAuthError(
            "ChatGPT OAuth request could not reach the authentication service.",
            code="transport_failed",
            relogin_required=False,
        ) from None


def _get(url: str, *, headers: dict[str, str], timeout: float = 10.0):
    import httpx

    try:
        return httpx.get(url, headers=headers, timeout=timeout, follow_redirects=False)
    except Exception:
        raise OAuthError(
            "ChatGPT OAuth request could not reach the service.",
            code="transport_failed",
            relogin_required=False,
        ) from None


def _decode_response_json(response, *, code: str, message: str) -> dict:
    content = getattr(response, "content", b"")
    if isinstance(content, bytes | bytearray) and len(content) > 2_000_000:
        raise OAuthError(message, code=code, relogin_required=False)
    try:
        payload = response.json()
    except Exception:
        raise OAuthError(message, code=code, relogin_required=False) from None
    if not isinstance(payload, dict):
        raise OAuthError(message, code=code, relogin_required=False)
    return payload


def _retry_after(response) -> str:
    value = str((getattr(response, "headers", None) or {}).get("retry-after") or "").strip()
    return f" after {value}s" if value.isdigit() else " later"


def refresh_tokens(refresh_token: str) -> dict[str, str]:
    response = _post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": OAUTH_CLIENT_ID},
    )
    if response.status_code == 429:
        raise OAuthError(
            f"OpenAI is rate-limiting ChatGPT token refresh; retry{_retry_after(response)}.",
            code="rate_limited",
            relogin_required=False,
        )
    if response.status_code != 200:
        relogin = response.status_code in {400, 401, 403}
        raise OAuthError(
            f"ChatGPT token refresh failed with HTTP {response.status_code}.",
            code="refresh_failed",
            relogin_required=relogin,
        )
    payload = _decode_response_json(
        response,
        code="refresh_invalid",
        message="ChatGPT token refresh returned invalid JSON.",
    )
    access = str(payload.get("access_token") or "").strip() if isinstance(payload, dict) else ""
    rotated = str(payload.get("refresh_token") or "").strip() if isinstance(payload, dict) else ""
    if not access:
        raise OAuthError("ChatGPT token refresh returned no access token.", code="refresh_incomplete")
    return {"access_token": access, "refresh_token": rotated or refresh_token}


def runtime_credentials(*, force_refresh: bool = False) -> RuntimeCredentials:
    tokens = load_tokens()
    if force_refresh or _token_expiring(tokens["access_token"]):
        observed_access = tokens["access_token"]
        with _refresh_lock():
            tokens = load_tokens()
            should_refresh = _token_expiring(tokens["access_token"])
            if force_refresh and tokens["access_token"] == observed_access:
                should_refresh = True
            if should_refresh:
                tokens = refresh_tokens(tokens["refresh_token"])
                _save_tokens_unlocked(tokens)
    return RuntimeCredentials(tokens["access_token"], _account_id(tokens["access_token"]))


def request_headers(credentials: RuntimeCredentials) -> dict[str, str]:
    headers = {
        "User-Agent": "codex_cli_rs/0.0.0 (Asgard)",
        "originator": "codex_cli_rs",
    }
    if credentials.account_id:
        headers["ChatGPT-Account-ID"] = credentials.account_id
    return headers


def make_client(*, force_refresh: bool = False):
    import httpx
    from openai import OpenAI

    credentials = runtime_credentials(force_refresh=force_refresh)
    return OpenAI(
        base_url=CODEX_BASE_URL,
        api_key=credentials.access_token,
        default_headers=request_headers(credentials),
        http_client=httpx.Client(follow_redirects=False),
        max_retries=0,
    )


def model_catalog() -> list[str]:
    """Fetch the visible model catalog for the currently authenticated ChatGPT account."""
    from .providers import is_agent_model_id, normalize_model_id

    credentials = runtime_credentials()
    headers = request_headers(credentials)
    headers["Authorization"] = f"Bearer {credentials.access_token}"
    response = _get(f"{CODEX_BASE_URL}/models?client_version=1.0.0", headers=headers, timeout=10.0)
    if response.status_code != 200:
        return []
    raw = bytes(response.content or b"")
    if len(raw) > 2_000_000:
        return []
    try:
        payload = json.loads(raw)
    except UnicodeDecodeError, json.JSONDecodeError:
        return []
    entries = payload.get("models", []) if isinstance(payload, dict) else []
    visible: list[tuple[int, str]] = []
    contexts: dict[str, int] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        visibility = str(item.get("visibility") or "").lower()
        if visibility in {"hide", "hidden"}:
            continue
        model = normalize_model_id(item.get("slug"))
        if not model or not is_agent_model_id(model):
            continue
        priority = item.get("priority", 10_000)
        rank = int(priority) if isinstance(priority, int | float) else 10_000
        visible.append((rank, model))
        context_window = item.get("context_window")
        percent = item.get("effective_context_window_percent", 100)
        if isinstance(context_window, int) and context_window > 0 and isinstance(percent, int | float):
            contexts[model] = max(1, context_window * max(1, min(100, int(percent))) // 100)
    visible.sort(key=lambda value: (value[0], value[1]))
    _MODEL_CONTEXTS.clear()
    _MODEL_CONTEXTS.update(contexts)
    return list(dict.fromkeys(model for _, model in visible))


def model_context_window(model: str) -> int:
    return _MODEL_CONTEXTS.get(model, 0)


def login_status() -> tuple[bool, str]:
    """Validate the stored login against the fixed Codex backend without exposing tokens."""
    try:
        credentials = runtime_credentials()
        headers = request_headers(credentials)
        headers["Authorization"] = f"Bearer {credentials.access_token}"
        response = _get(f"{CODEX_BASE_URL}/models?client_version=1.0.0", headers=headers, timeout=10.0)
        if response.status_code == 401:
            credentials = runtime_credentials(force_refresh=True)
            headers = request_headers(credentials)
            headers["Authorization"] = f"Bearer {credentials.access_token}"
            response = _get(f"{CODEX_BASE_URL}/models?client_version=1.0.0", headers=headers, timeout=10.0)
    except OAuthError:
        return False, "login required"
    except Exception:
        return False, "login validation unavailable"
    if response.status_code == 200:
        detail = "logged in" + (" · account selected" if credentials.account_id else "")
        return True, detail
    if response.status_code == 429:
        return True, "stored login · validation rate-limited"
    return False, f"login rejected (HTTP {response.status_code})"


def device_login(notify: Callable[[str], None], *, timeout: float = 15 * 60) -> dict[str, str]:
    response = None
    for attempt in range(4):
        response = _post(
            f"{OAUTH_ISSUER}/api/accounts/deviceauth/usercode",
            json_body={"client_id": OAUTH_CLIENT_ID},
        )
        if response.status_code != 429 or attempt == 3:
            break
        retry_after = str((getattr(response, "headers", None) or {}).get("retry-after") or "")
        delay = float(retry_after) if retry_after.isdigit() else float(min(2**attempt, 8))
        time.sleep(delay)
    assert response is not None
    if response.status_code == 429:
        raise OAuthError(
            f"OpenAI is rate-limiting login; retry{_retry_after(response)}.",
            code="rate_limited",
        )
    if response.status_code != 200:
        raise OAuthError(f"ChatGPT device login failed with HTTP {response.status_code}.", code="device_request_failed")
    payload = _decode_response_json(
        response,
        code="device_invalid",
        message="ChatGPT device login returned invalid JSON.",
    )
    user_code = str(payload.get("user_code") or "").strip()
    device_auth_id = str(payload.get("device_auth_id") or "").strip()
    if not user_code or not device_auth_id:
        raise OAuthError("ChatGPT device login response was incomplete.", code="device_incomplete")
    try:
        interval = max(3.0, float(payload.get("interval", 5)))
    except TypeError, ValueError:
        interval = 5.0
    notify(f"Open https://auth.openai.com/codex/device and enter code {user_code}")

    deadline = time.monotonic() + timeout
    authorization: dict | None = None
    while time.monotonic() < deadline:
        time.sleep(interval)
        polled = _post(
            f"{OAUTH_ISSUER}/api/accounts/deviceauth/token",
            json_body={"device_auth_id": device_auth_id, "user_code": user_code},
        )
        if polled.status_code == 200:
            authorization = _decode_response_json(
                polled,
                code="poll_invalid",
                message="ChatGPT device login polling returned invalid JSON.",
            )
            break
        if polled.status_code not in {403, 404}:
            raise OAuthError(f"ChatGPT device login polling failed with HTTP {polled.status_code}.", code="poll_failed")
    if not isinstance(authorization, dict):
        raise OAuthError("ChatGPT device login timed out.", code="device_timeout")

    code = str(authorization.get("authorization_code") or "").strip()
    verifier = str(authorization.get("code_verifier") or "").strip()
    if not code or not verifier:
        raise OAuthError("ChatGPT authorization response was incomplete.", code="exchange_incomplete")
    exchanged = _post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{OAUTH_ISSUER}/deviceauth/callback",
            "client_id": OAUTH_CLIENT_ID,
            "code_verifier": verifier,
        },
    )
    if exchanged.status_code != 200:
        raise OAuthError(f"ChatGPT token exchange failed with HTTP {exchanged.status_code}.", code="exchange_failed")
    token_payload = _decode_response_json(
        exchanged,
        code="exchange_invalid",
        message="ChatGPT token exchange returned invalid JSON.",
    )
    access = str(token_payload.get("access_token") or "").strip()
    refresh = str(token_payload.get("refresh_token") or "").strip()
    if not access or not refresh:
        raise OAuthError("ChatGPT token exchange returned an incomplete token pair.", code="exchange_incomplete")
    return {"access_token": access, "refresh_token": refresh}
