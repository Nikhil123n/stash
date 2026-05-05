"""Add category evolution skip timestamp.

Revision ID: 002_category_evolution
Revises: 001_initial
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "002_category_evolution"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the timestamp used to suppress repeated evolution proposals."""
    op.add_column("categories", sa.Column("evolution_skipped_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Remove the category evolution skip timestamp."""
    op.drop_column("categories", "evolution_skipped_at")
