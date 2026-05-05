"""Artifact API routes for the Stash dashboard."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from api.serializers import artifact_to_detail, artifact_to_out
from auth import get_current_user
from schemas import (
    ArtifactDetail,
    ArtifactOut,
    ArtifactPage,
    ArtifactUpdateRequest,
    DeleteResponse,
    StatsOut,
    TopCategoryOut,
)
from storage.db import Artifact, Category, Subcategory, UserCorrection, get_db
from storage.r2 import delete_from_r2

router: APIRouter = APIRouter(
    prefix="/api/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(get_current_user)],
)

stats_router: APIRouter = APIRouter(
    prefix="/api",
    tags=["stats"],
    dependencies=[Depends(get_current_user)],
)


def _artifact_options() -> tuple[Any, ...]:
    """Return eager-load options shared by artifact endpoints."""
    return (
        selectinload(Artifact.category).selectinload(Category.subcategories),
        selectinload(Artifact.subcategory),
    )


def _increment_category_count(db: Session, category_id: UUID) -> None:
    """Increment a category's item_count atomically."""
    db.execute(
        text("UPDATE categories SET item_count = item_count + 1 WHERE id = :id"),
        {"id": category_id},
    )


def _decrement_category_count(db: Session, category_id: UUID) -> None:
    """Decrement a category's item_count without going below zero."""
    db.execute(
        text("UPDATE categories SET item_count = GREATEST(item_count - 1, 0) WHERE id = :id"),
        {"id": category_id},
    )


def _artifact_by_id(db: Session, artifact_id: UUID) -> Artifact | None:
    """Fetch one artifact by ID with dashboard relationships loaded."""
    return db.execute(
        select(Artifact)
        .options(*_artifact_options())
        .where(Artifact.id == artifact_id)
    ).scalar_one_or_none()


@router.get("", response_model=ArtifactPage)
def list_artifacts(
    category: str | None = None,
    sub: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ArtifactPage:
    """Return paginated artifacts ordered newest first."""
    filters: list[Any] = []
    stmt = select(Artifact).options(*_artifact_options())
    count_stmt = select(func.count(Artifact.id))

    if category:
        stmt = stmt.join(Category, Artifact.category_id == Category.id)
        count_stmt = count_stmt.join(Category, Artifact.category_id == Category.id)
        filters.append(Category.slug == category)

    if sub:
        stmt = stmt.join(Subcategory, Artifact.subcategory_id == Subcategory.id)
        count_stmt = count_stmt.join(Subcategory, Artifact.subcategory_id == Subcategory.id)
        filters.append(Subcategory.slug == sub)

    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    total = int(db.execute(count_stmt).scalar_one() or 0)
    artifacts = db.execute(
        stmt.order_by(Artifact.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).scalars().all()

    return ArtifactPage(
        items=[artifact_to_out(artifact) for artifact in artifacts],
        total=total,
        page=page,
        pages=math.ceil(total / limit) if total else 0,
    )


@router.get("/search", response_model=list[ArtifactOut])
def search_artifacts(
    q: str = Query(min_length=2),
    db: Session = Depends(get_db),
) -> list[ArtifactOut]:
    """Search artifacts using PostgreSQL full-text search."""
    ts_query = func.plainto_tsquery("english", q)
    artifacts = db.execute(
        select(Artifact)
        .options(*_artifact_options())
        .where(Artifact.search_vector.op("@@")(ts_query))
        .order_by(func.ts_rank(Artifact.search_vector, ts_query).desc())
        .limit(50)
    ).scalars().all()
    return [artifact_to_out(artifact) for artifact in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactDetail)
def get_artifact(artifact_id: UUID, db: Session = Depends(get_db)) -> ArtifactDetail:
    """Return artifact detail and mark the artifact as viewed."""
    artifact = _artifact_by_id(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    db.execute(
        text(
            """
            UPDATE artifacts
            SET view_count = view_count + 1,
                last_viewed_at = now()
            WHERE id = :id
            """
        ),
        {"id": artifact_id},
    )
    db.commit()

    updated = _artifact_by_id(db, artifact_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    return artifact_to_detail(updated)


@router.patch("/{artifact_id}", response_model=ArtifactOut)
def update_artifact(
    artifact_id: UUID,
    payload: ArtifactUpdateRequest,
    db: Session = Depends(get_db),
) -> ArtifactOut:
    """Manually re-categorize an artifact and record the correction."""
    artifact = _artifact_by_id(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    new_category = db.execute(
        select(Category).where(Category.id == payload.category_id)
    ).scalar_one_or_none()
    if new_category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")

    old_category_id = artifact.category_id
    if old_category_id != new_category.id:
        if old_category_id is not None:
            _decrement_category_count(db, old_category_id)
        _increment_category_count(db, new_category.id)

    artifact.category_id = new_category.id
    artifact.user_overridden = True
    db.add(
        UserCorrection(
            artifact_id=artifact.id,
            from_category=old_category_id,
            to_category=new_category.id,
        )
    )
    db.commit()

    updated = _artifact_by_id(db, artifact_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    return artifact_to_out(updated)


@router.delete("/{artifact_id}", response_model=DeleteResponse)
def delete_artifact(artifact_id: UUID, db: Session = Depends(get_db)) -> DeleteResponse:
    """Delete an artifact and its stored R2 media when present."""
    artifact = _artifact_by_id(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    if artifact.r2_key:
        delete_from_r2(artifact.r2_key)

    if artifact.category_id is not None:
        _decrement_category_count(db, artifact.category_id)
    db.delete(artifact)
    db.commit()
    return DeleteResponse(deleted=True)


@stats_router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)) -> StatsOut:
    """Return dashboard summary statistics."""
    total_artifacts = int(db.execute(select(func.count(Artifact.id))).scalar_one() or 0)
    top_categories = db.execute(
        select(Category)
        .order_by(Category.item_count.desc())
        .limit(5)
    ).scalars().all()
    recent = db.execute(
        select(Artifact)
        .options(*_artifact_options())
        .order_by(Artifact.created_at.desc())
        .limit(5)
    ).scalars().all()
    needs_review_count = int(
        db.execute(
            select(func.count(Artifact.id)).where(Artifact.ai_confidence < 0.7)
        ).scalar_one()
        or 0
    )

    return StatsOut(
        total_artifacts=total_artifacts,
        top_categories=[
            TopCategoryOut(name=category.name, count=int(category.item_count or 0))
            for category in top_categories
        ],
        recent=[artifact_to_out(artifact) for artifact in recent],
        needs_review_count=needs_review_count,
    )
