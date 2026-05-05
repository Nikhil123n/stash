"""Create prompt examples table for classification learning.

Revision ID: 003_prompt_examples
Revises: 002_category_evolution
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "003_prompt_examples"
down_revision: str | None = "002_category_evolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create prompt examples used as few-shot classification guidance."""
    op.create_table(
        "prompt_examples",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("correct_category", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "source_type",
            "correct_category",
            name="prompt_examples_source_type_category_key",
        ),
    )


def downgrade() -> None:
    """Drop prompt examples."""
    op.drop_table("prompt_examples")
