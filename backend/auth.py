"""Dashboard authentication helpers for Stash API routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from config import get_bool_env, get_env

MAGIC_LINK_TOKEN_TYPE = "dashboard_magic"
SESSION_TOKEN_TYPE = "dashboard_session"
DEFAULT_MAGIC_LINK_TTL_SECONDS = 10 * 60
DEFAULT_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


def _token_secret() -> bytes:
    """Return the signing secret used for dashboard tokens."""
    secret = get_env("SECRET_KEY") or get_env("TELEGRAM_BOT_TOKEN")
    if not secret:
        raise RuntimeError("SECRET_KEY is not configured.")
    return secret.encode("utf-8")


def _base64url_encode(data: bytes) -> str:
    """Return unpadded base64url text."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    """Decode unpadded base64url text."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}")


def _sign_payload(payload_text: str) -> str:
    """Return a stable HMAC signature for a token payload."""
    signature = hmac.new(_token_secret(), payload_text.encode("ascii"), hashlib.sha256).digest()
    return _base64url_encode(signature)


def _encode_token(payload: dict[str, Any]) -> str:
    """Encode and sign a compact JSON token."""
    payload_text = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{payload_text}.{_sign_payload(payload_text)}"


def _decode_token(token: str) -> dict[str, Any] | None:
    """Verify and decode a compact JSON token."""
    try:
        payload_text, signature = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = _sign_payload(payload_text)
    if not hmac.compare_digest(expected_signature, signature):
        return None

    try:
        payload = json.loads(_base64url_decode(payload_text).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    try:
        expires_at = int(payload.get("exp") or "0")
    except (TypeError, ValueError):
        return None

    if expires_at < int(time.time()):
        return None

    return payload


def _get_magic_link_redis() -> Any:
    """Return the Redis client used to enforce one-time magic link use."""
    from bot import get_redis_client

    return get_redis_client()


def _magic_nonce_key(nonce: str) -> str:
    """Return the Redis key for a one-time magic link nonce."""
    return f"dashboard_magic_nonce:{nonce}"


def _get_int_env(name: str, default: int) -> int:
    """Return an integer env var without importing additional config helpers."""
    value = get_env(name)
    if not value:
        return default
    return int(value)


def _allowed_chat_ids() -> set[str]:
    """Return dashboard chat IDs allowed to create and use dashboard sessions."""
    configured = get_env("DASHBOARD_ALLOWED_CHAT_IDS") or get_env("YOUR_CHAT_ID")
    return {item.strip() for item in configured.split(",") if item.strip()}


def is_dashboard_chat_allowed(chat_id: int | str) -> bool:
    """Return whether a Telegram chat ID can access the dashboard."""
    allowed = _allowed_chat_ids()
    return not allowed or str(chat_id) in allowed


def create_dashboard_magic_token(chat_id: int) -> str:
    """Create a short-lived one-time dashboard magic link token."""
    if not is_dashboard_chat_allowed(chat_id):
        raise PermissionError("Telegram chat is not allowed to access this dashboard.")

    ttl_seconds = _get_int_env("DASHBOARD_MAGIC_LINK_TTL_SECONDS", DEFAULT_MAGIC_LINK_TTL_SECONDS)
    nonce = secrets.token_urlsafe(24)
    expires_at = int(time.time()) + ttl_seconds
    payload = {
        "typ": MAGIC_LINK_TOKEN_TYPE,
        "chat_id": int(chat_id),
        "nonce": nonce,
        "exp": expires_at,
    }
    _get_magic_link_redis().setex(_magic_nonce_key(nonce), ttl_seconds, str(chat_id))
    return _encode_token(payload)


def exchange_dashboard_magic_token(token: str) -> str | None:
    """Consume a magic link token and return a long-lived dashboard session token."""
    payload = _decode_token(token)
    if payload is None or payload.get("typ") != MAGIC_LINK_TOKEN_TYPE:
        return None

    nonce = str(payload.get("nonce") or "")
    chat_id = str(payload.get("chat_id") or "")
    if not nonce or not chat_id or not is_dashboard_chat_allowed(chat_id):
        return None

    stored_chat_id = _get_magic_link_redis().getdel(_magic_nonce_key(nonce))
    if isinstance(stored_chat_id, bytes):
        stored_chat_id = stored_chat_id.decode("utf-8")
    if str(stored_chat_id) != chat_id:
        return None

    return create_dashboard_session_token(int(chat_id))


def create_dashboard_session_token(chat_id: int) -> str:
    """Create a dashboard session token for an authorized Telegram chat."""
    if not is_dashboard_chat_allowed(chat_id):
        raise PermissionError("Telegram chat is not allowed to access this dashboard.")

    ttl_seconds = _get_int_env("DASHBOARD_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS)
    return _encode_token(
        {
            "typ": SESSION_TOKEN_TYPE,
            "chat_id": int(chat_id),
            "exp": int(time.time()) + ttl_seconds,
        }
    )


def verify_dashboard_session(token: str) -> dict[str, Any] | None:
    """Verify a dashboard session token and return the authenticated user payload."""
    payload = _decode_token(token)
    if payload is None or payload.get("typ") != SESSION_TOKEN_TYPE:
        return None

    chat_id = payload.get("chat_id")
    if chat_id is None or not is_dashboard_chat_allowed(str(chat_id)):
        return None

    return {"id": str(chat_id), "auth_type": "dashboard_session"}


def _skip_auth() -> bool:
    """Return whether API auth should be bypassed for local development."""
    return get_bool_env("SKIP_AUTH")


def verify_telegram_login(data: dict[str, Any]) -> bool:
    """Verify Telegram Login Widget data using the configured bot token."""
    bot_token = get_env("TELEGRAM_BOT_TOKEN")
    provided_hash = str(data.get("hash") or "")
    if not bot_token or not provided_hash:
        return False

    try:
        auth_date = int(str(data.get("auth_date") or "0"))
    except ValueError:
        return False

    age_seconds = time.time() - auth_date
    if age_seconds < 0 or age_seconds > 86400:
        return False

    check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(data.items())
        if key != "hash" and value is not None
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hash, provided_hash)


def _parse_authorization_payload(authorization: str) -> dict[str, Any]:
    """Parse a JSON or query-string Telegram login payload from the auth header."""
    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    try:
        parsed = json.loads(token)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    return dict(parse_qsl(token, keep_blank_values=True))


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """FastAPI dependency that verifies the current dashboard user."""
    if _skip_auth():
        return {"id": "local-dev"}

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    raw_token = authorization.strip()
    if raw_token.lower().startswith("bearer "):
        raw_token = raw_token[7:].strip()

    session_user = verify_dashboard_session(raw_token)
    if session_user is not None:
        return session_user

    data = _parse_authorization_payload(authorization)
    if not verify_telegram_login(data) or not is_dashboard_chat_allowed(str(data.get("id") or "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram login.",
        )

    return data
