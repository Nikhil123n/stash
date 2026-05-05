"""Telegram Login Widget authentication helpers for Stash API routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from config import get_bool_env, get_env


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
    """FastAPI dependency that verifies the current Telegram user."""
    if _skip_auth():
        return {"id": "local-dev"}

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    data = _parse_authorization_payload(authorization)
    if not verify_telegram_login(data):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram login.",
        )

    return data
