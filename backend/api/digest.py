"""Digest preview API route for the Stash dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.serializers import artifact_to_out
from auth import get_current_user
from digest import get_digest_items
from schemas import DigestPreviewOut
from storage.db import get_db

router: APIRouter = APIRouter(
    prefix="/api/digest",
    tags=["digest"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/preview", response_model=DigestPreviewOut)
def preview_digest(db: Session = Depends(get_db)) -> DigestPreviewOut:
    """Return the artifacts that would appear in the weekly digest."""
    recent, _total_this_week, forgotten = get_digest_items(db)
    return DigestPreviewOut(
        recent=[artifact_to_out(artifact) for artifact in recent],
        forgotten=[artifact_to_out(artifact) for artifact in forgotten],
    )
