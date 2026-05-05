"""Pydantic response and request schemas for the Stash REST API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubcategoryOut(BaseModel):
    """Dashboard representation of a Stash subcategory."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    item_count: int
    tier: int
    confirmed: bool


class CategoryOut(BaseModel):
    """Dashboard representation of a Stash top-level category."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    icon: str | None
    item_count: int
    created_at: datetime
    subcategories: list[SubcategoryOut]
    recent_thumbnails: list[str]


class ArtifactOut(BaseModel):
    """Dashboard representation of a saved artifact."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    source_type: str
    raw_url: str | None
    r2_url: str | None
    ai_title: str
    ai_summary: str
    ai_tags: list[str]
    ai_confidence: float
    needs_review: bool
    category: CategoryOut
    subcategory: SubcategoryOut | None
    user_overridden: bool
    view_count: int
    last_viewed_at: datetime | None


class ArtifactDetail(ArtifactOut):
    """Detailed artifact representation including transcript text."""

    ai_transcript: str | None
    ai_audit: dict[str, Any] | None


class ArtifactPage(BaseModel):
    """Paginated artifact response."""

    items: list[ArtifactOut]
    total: int
    page: int
    pages: int


class ArtifactUpdateRequest(BaseModel):
    """Request body for manual artifact re-categorization."""

    category_id: UUID


class DeleteResponse(BaseModel):
    """Deletion status response."""

    deleted: bool


class TopCategoryOut(BaseModel):
    """Compact category count used in API stats."""

    name: str
    count: int


class StatsOut(BaseModel):
    """Dashboard summary statistics."""

    total_artifacts: int
    top_categories: list[TopCategoryOut]
    recent: list[ArtifactOut]
    needs_review_count: int


class DigestPreviewOut(BaseModel):
    """Preview payload for the weekly digest."""

    recent: list[ArtifactOut]
    forgotten: list[ArtifactOut]
