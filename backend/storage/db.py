"""SQLAlchemy models and session dependency for the Stash backend."""

import re
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from config import get_env
from logging_config import structlog


logger = structlog.get_logger(__name__)


def _normalize_database_url(database_url: str) -> str:
    """Ensure SQLAlchemy uses the PostgreSQL psycopg2 dialect."""
    if database_url.startswith("postgresql+psycopg2://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg2://", 1)
    return database_url


DATABASE_URL: str = _normalize_database_url(
    get_env("DATABASE_URL", required=True)
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _slugify(value: str) -> str:
    """Create a URL-safe category slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = slug.strip("-")
    return slug or "category"


class Base(DeclarativeBase):
    """Base class for all Stash SQLAlchemy models."""


class Category(Base):
    """Top-level AI-generated or user-confirmed content category."""

    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    icon: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    ai_generated: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    evolution_skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    subcategories: Mapped[list["Subcategory"]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="category")
    corrections_from: Mapped[list["UserCorrection"]] = relationship(
        back_populates="from_category_record",
        foreign_keys="UserCorrection.from_category",
    )
    corrections_to: Mapped[list["UserCorrection"]] = relationship(
        back_populates="to_category_record",
        foreign_keys="UserCorrection.to_category",
    )


class Subcategory(Base):
    """Second- or third-tier content grouping beneath a category."""

    __tablename__ = "subcategories"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    category_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    item_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    tier: Mapped[int | None] = mapped_column(Integer, server_default=text("2"))
    confirmed: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    category: Mapped[Category | None] = relationship(back_populates="subcategories")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="subcategory")


class Artifact(Base):
    """Saved content artifact and its AI-generated metadata."""

    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    raw_url: Mapped[str | None] = mapped_column(Text)
    r2_key: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    telegram_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    ai_title: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    ai_transcript: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_audit: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    category_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("categories.id"))
    subcategory_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("subcategories.id"))
    user_overridden: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    view_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    digest_sent: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    category: Mapped[Category | None] = relationship(back_populates="artifacts")
    subcategory: Mapped[Subcategory | None] = relationship(back_populates="artifacts")
    corrections: Mapped[list["UserCorrection"]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
    )


Index("artifacts_category_idx", Artifact.category_id)
Index("artifacts_subcategory_idx", Artifact.subcategory_id)
Index("artifacts_search_idx", Artifact.search_vector, postgresql_using="gin")
Index("artifacts_created_idx", Artifact.created_at.desc())


class UserCorrection(Base):
    """Learning signal produced when an artifact is manually re-categorized."""

    __tablename__ = "user_corrections"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
    )
    from_category: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("categories.id"))
    to_category: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("categories.id"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    artifact: Mapped[Artifact | None] = relationship(back_populates="corrections")
    from_category_record: Mapped[Category | None] = relationship(
        back_populates="corrections_from",
        foreign_keys=[from_category],
    )
    to_category_record: Mapped[Category | None] = relationship(
        back_populates="corrections_to",
        foreign_keys=[to_category],
    )


class PromptExample(Base):
    """Few-shot classification example learned from repeated user corrections."""

    __tablename__ = "prompt_examples"
    __table_args__ = (
        UniqueConstraint("source_type", "correct_category", name="prompt_examples_source_type_category_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    correct_category: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class LLMModelState(Base):
    """Last-seen model value used to detect model changes across worker runs."""

    __tablename__ = "llm_model_state"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class ModelChangeEvent(Base):
    """Audit event written when the configured Gemini model changes."""

    __tablename__ = "model_change_events"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    old_model: Mapped[str | None] = mapped_column(Text)
    new_model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


Index("model_change_events_created_idx", ModelChangeEvent.created_at.desc())


_GEMINI_MODEL_STATE_KEY = "gemini_model"


def record_model_change_if_needed(
    db: Session,
    current_model: str,
    *,
    commit: bool = False,
) -> None:
    """Persist a warning event when GEMINI_MODEL differs from the last recorded run."""
    clean_model = current_model.strip()
    if not clean_model:
        return

    now = datetime.now(UTC)
    state = db.get(LLMModelState, _GEMINI_MODEL_STATE_KEY)
    if state is None:
        db.add(
            LLMModelState(
                name=_GEMINI_MODEL_STATE_KEY,
                model_name=clean_model,
                updated_at=now,
            )
        )
        logger.info("gemini_model_state_initialized", model_name=clean_model, duration_ms=0)
        if commit:
            db.commit()
        else:
            db.flush()
        return

    if state.model_name == clean_model:
        return

    old_model = state.model_name
    db.add(
        ModelChangeEvent(
            old_model=old_model,
            new_model=clean_model,
            created_at=now,
        )
    )
    state.model_name = clean_model
    state.updated_at = now
    logger.warning(
        "gemini_model_changed",
        old_model=old_model,
        new_model=clean_model,
        duration_ms=0,
    )
    if commit:
        db.commit()
    else:
        db.flush()


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI dependencies."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_existing_category_names(db: Session) -> list[str]:
    """Return all category names ordered by descending item count."""
    result = db.execute(select(Category.name).order_by(Category.item_count.desc()))
    return list(result.scalars().all())


def get_or_create_category(db: Session, name: str, ai_generated: bool = True) -> Category:
    """Return an existing category by case-insensitive name or create it."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Category name cannot be empty.")

    existing = db.execute(
        select(Category).where(func.lower(Category.name) == clean_name.lower())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    category = Category(
        name=clean_name,
        slug=_slugify(clean_name),
        ai_generated=ai_generated,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def get_prompt_examples(db: Session, source_type: str) -> list[dict[str, str]]:
    """Return few-shot examples for a source type from repeated user corrections."""
    examples = db.execute(
        select(PromptExample)
        .where(PromptExample.source_type == source_type)
        .order_by(PromptExample.created_at.desc())
    ).scalars().all()

    return [
        {
            "source_type": example.source_type,
            "content_text": example.content_text,
            "correct_category": example.correct_category,
        }
        for example in examples
    ]
