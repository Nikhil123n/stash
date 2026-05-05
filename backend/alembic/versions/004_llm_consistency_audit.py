"""Add LLM consistency audit storage.

Revision ID: 004_llm_consistency_audit
Revises: 003_prompt_examples
Create Date: 2026-05-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "004_llm_consistency_audit"
down_revision: str | None = "003_prompt_examples"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add artifact audit JSON and model-change tracking tables."""
    op.add_column("artifacts", sa.Column("ai_audit", postgresql.JSONB(), nullable=True))

    op.create_table(
        "llm_model_state",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "model_change_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("old_model", sa.Text()),
        sa.Column("new_model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.execute("CREATE INDEX model_change_events_created_idx ON model_change_events(created_at DESC)")


def downgrade() -> None:
    """Remove LLM consistency audit storage."""
    op.execute("DROP INDEX IF EXISTS model_change_events_created_idx")
    op.drop_table("model_change_events")
    op.drop_table("llm_model_state")
    op.drop_column("artifacts", "ai_audit")
