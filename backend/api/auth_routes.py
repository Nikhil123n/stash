"""Dashboard authentication API routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from auth import exchange_dashboard_magic_token

router: APIRouter = APIRouter(prefix="/api/auth", tags=["auth"])


class MagicLinkRequest(BaseModel):
    """Request body for exchanging a Telegram-issued dashboard link."""

    token: str


class AuthTokenResponse(BaseModel):
    """Dashboard session token response."""

    token: str


@router.post("/magic", response_model=AuthTokenResponse)
def exchange_magic_link(payload: MagicLinkRequest) -> AuthTokenResponse:
    """Exchange a one-time magic link token for a dashboard session token."""
    session_token = exchange_dashboard_magic_token(payload.token)
    if session_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired dashboard link.",
        )
    return AuthTokenResponse(token=session_token)
