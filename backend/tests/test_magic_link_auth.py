"""Tests for Telegram-issued dashboard magic links."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import auth
from main import app


class FakeRedis:
    """Minimal Redis stand-in for one-time magic link nonce tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setex(self, key: str, _ttl: int, value: str) -> None:
        """Store a value with ignored TTL semantics."""
        self.values[key] = value

    def getdel(self, key: str) -> str | None:
        """Return and delete a stored value."""
        return self.values.pop(key, None)


def configure_auth(monkeypatch, fake_redis: FakeRedis) -> None:
    """Set deterministic auth env and Redis for tests."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("YOUR_CHAT_ID", "123")
    monkeypatch.setenv("DASHBOARD_MAGIC_LINK_TTL_SECONDS", "600")
    monkeypatch.setenv("DASHBOARD_SESSION_TTL_SECONDS", "3600")
    monkeypatch.setattr(auth, "_get_magic_link_redis", lambda: fake_redis)


def test_magic_link_exchanges_once(monkeypatch) -> None:
    """Magic links produce a dashboard session and cannot be reused."""
    fake_redis = FakeRedis()
    configure_auth(monkeypatch, fake_redis)

    magic_token = auth.create_dashboard_magic_token(123)
    session_token = auth.exchange_dashboard_magic_token(magic_token)

    assert session_token is not None
    assert auth.verify_dashboard_session(session_token) == {
        "id": "123",
        "auth_type": "dashboard_session",
    }
    assert auth.exchange_dashboard_magic_token(magic_token) is None


def test_magic_link_rejects_unapproved_chat(monkeypatch) -> None:
    """Only the configured dashboard owner can create magic links."""
    fake_redis = FakeRedis()
    configure_auth(monkeypatch, fake_redis)

    assert not auth.is_dashboard_chat_allowed(999)

    try:
        auth.create_dashboard_magic_token(999)
    except PermissionError:
        pass
    else:
        raise AssertionError("Expected unapproved chat to be rejected.")


def test_magic_auth_route_returns_session_token(monkeypatch) -> None:
    """POST /api/auth/magic exchanges a valid magic link for a session token."""
    fake_redis = FakeRedis()
    configure_auth(monkeypatch, fake_redis)
    magic_token = auth.create_dashboard_magic_token(123)

    response = TestClient(app).post("/api/auth/magic", json={"token": magic_token})

    assert response.status_code == 200
    session_token = response.json()["token"]
    assert auth.verify_dashboard_session(session_token)["id"] == "123"
