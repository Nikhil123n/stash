"""Add source metadata and URL thumbnails to artifacts.

Revision ID: 005_artifact_source_metadata
Revises: 004_llm_consistency_audit
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "005_artifact_source_metadata"
down_revision: str | None = "004_llm_consistency_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store original source metadata and thumbnail URLs for URL artifacts."""
    op.add_column("artifacts", sa.Column("thumbnail_url", sa.Text(), nullable=True))
    op.add_column("artifacts", sa.Column("source_metadata", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Remove source metadata and thumbnail URL storage."""
    op.drop_column("artifacts", "source_metadata")
    op.drop_column("artifacts", "thumbnail_url")
