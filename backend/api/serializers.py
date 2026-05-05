"""Serialization helpers for converting SQLAlchemy models into API schemas."""

from datetime import UTC, datetime
from typing import Iterable

from schemas import ArtifactDetail, ArtifactOut, CategoryOut, SubcategoryOut
from storage.db import Artifact, Category, Subcategory
from storage.r2 import get_r2_url


def _created_at(value: datetime | None) -> datetime:
    """Return a concrete timestamp for API fields that are non-nullable."""
    return value or datetime.now(UTC)


def subcategory_to_out(subcategory: Subcategory) -> SubcategoryOut:
    """Serialize a Subcategory model."""
    return SubcategoryOut(
        id=subcategory.id,
        name=subcategory.name,
        slug=subcategory.slug,
        item_count=int(subcategory.item_count or 0),
        tier=int(subcategory.tier or 2),
        confirmed=bool(subcategory.confirmed),
    )


def category_to_out(
    category: Category,
    recent_thumbnails: Iterable[str] | None = None,
) -> CategoryOut:
    """Serialize a Category model."""
    subcategories = sorted(
        list(category.subcategories or []),
        key=lambda subcategory: int(subcategory.item_count or 0),
        reverse=True,
    )
    return CategoryOut(
        id=category.id,
        name=category.name,
        slug=category.slug,
        icon=category.icon,
        item_count=int(category.item_count or 0),
        created_at=_created_at(category.created_at),
        subcategories=[subcategory_to_out(subcategory) for subcategory in subcategories],
        recent_thumbnails=list(recent_thumbnails or []),
    )


def _artifact_r2_url(artifact: Artifact) -> str | None:
    """Return a public R2 URL for an artifact when it has stored media."""
    if not artifact.r2_key:
        return None
    return get_r2_url(artifact.r2_key)


def artifact_to_out(artifact: Artifact) -> ArtifactOut:
    """Serialize an Artifact model for list responses."""
    if artifact.category is None:
        raise ValueError(f"Artifact {artifact.id} is missing a category.")

    return ArtifactOut(
        id=artifact.id,
        created_at=_created_at(artifact.created_at),
        source_type=artifact.source_type,
        raw_url=artifact.raw_url,
        r2_url=_artifact_r2_url(artifact),
        ai_title=artifact.ai_title or "",
        ai_summary=artifact.ai_summary or "",
        ai_tags=list(artifact.ai_tags or []),
        ai_confidence=float(artifact.ai_confidence or 0.0),
        needs_review=float(artifact.ai_confidence or 0.0) < 0.7,
        category=category_to_out(artifact.category),
        subcategory=subcategory_to_out(artifact.subcategory) if artifact.subcategory is not None else None,
        user_overridden=bool(artifact.user_overridden),
        view_count=int(artifact.view_count or 0),
        last_viewed_at=artifact.last_viewed_at,
    )


def artifact_to_detail(artifact: Artifact) -> ArtifactDetail:
    """Serialize an Artifact model for detail responses."""
    base = artifact_to_out(artifact)
    return ArtifactDetail(**base.model_dump(), ai_transcript=artifact.ai_transcript)
