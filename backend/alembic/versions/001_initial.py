"""Create initial Stash tables and indexes."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create categories, subcategories, artifacts, and user correction tables."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text()),
        sa.Column("item_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("ai_generated", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "subcategories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("item_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("tier", sa.Integer(), server_default=sa.text("2")),
        sa.Column("confirmed", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("raw_url", sa.Text()),
        sa.Column("r2_key", sa.Text()),
        sa.Column("telegram_msg_id", sa.BigInteger()),
        sa.Column("ai_title", sa.Text()),
        sa.Column("ai_summary", sa.Text()),
        sa.Column("ai_tags", postgresql.ARRAY(sa.Text())),
        sa.Column("ai_transcript", sa.Text()),
        sa.Column("ai_confidence", sa.Float()),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id")),
        sa.Column("subcategory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subcategories.id")),
        sa.Column("user_overridden", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("view_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True)),
        sa.Column("digest_sent", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("search_vector", postgresql.TSVECTOR()),
    )
    op.create_index("artifacts_category_idx", "artifacts", ["category_id"])
    op.create_index("artifacts_subcategory_idx", "artifacts", ["subcategory_id"])
    op.execute("CREATE INDEX artifacts_search_idx ON artifacts USING GIN(search_vector)")
    op.execute("CREATE INDEX artifacts_created_idx ON artifacts(created_at DESC)")

    op.create_table(
        "user_corrections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
        ),
        sa.Column("from_category", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id")),
        sa.Column("to_category", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    """Drop initial Stash tables and indexes."""
    op.drop_table("user_corrections")
    op.execute("DROP INDEX IF EXISTS artifacts_created_idx")
    op.execute("DROP INDEX IF EXISTS artifacts_search_idx")
    op.drop_index("artifacts_subcategory_idx", table_name="artifacts")
    op.drop_index("artifacts_category_idx", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_table("subcategories")
    op.drop_table("categories")
