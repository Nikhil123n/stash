"""Category API routes for the Stash dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.serializers import category_to_out
from auth import get_current_user
from schemas import CategoryOut
from storage.db import Artifact, Category, get_db
from storage.r2 import get_r2_url

router: APIRouter = APIRouter(
    prefix="/api/categories",
    tags=["categories"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    """Return all categories with subcategories and recent image thumbnails."""
    categories = db.execute(
        select(Category)
        .options(selectinload(Category.subcategories))
        .order_by(Category.item_count.desc())
    ).scalars().all()

    output: list[CategoryOut] = []
    for category in categories:
        thumbnail_rows = db.execute(
            select(Artifact.r2_key, Artifact.thumbnail_url)
            .where(
                Artifact.category_id == category.id,
                (Artifact.r2_key.is_not(None)) | (Artifact.thumbnail_url.is_not(None)),
            )
            .order_by(Artifact.created_at.desc())
            .limit(3)
        ).all()
        recent_thumbnails = [
            get_r2_url(r2_key) if r2_key else thumbnail_url
            for r2_key, thumbnail_url in thumbnail_rows
            if r2_key or thumbnail_url
        ]
        output.append(category_to_out(category, recent_thumbnails=recent_thumbnails))

    return output
