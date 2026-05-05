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
        r2_keys = db.execute(
            select(Artifact.r2_key)
            .where(
                Artifact.category_id == category.id,
                Artifact.source_type == "image",
                Artifact.r2_key.is_not(None),
            )
            .order_by(Artifact.created_at.desc())
            .limit(3)
        ).scalars().all()
        recent_thumbnails = [get_r2_url(r2_key) for r2_key in r2_keys if r2_key]
        output.append(category_to_out(category, recent_thumbnails=recent_thumbnails))

    return output
