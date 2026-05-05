"""Digest query and formatting helpers shared by Celery and REST preview."""

from __future__ import annotations

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from storage.db import Artifact, Category


def _artifact_options() -> tuple[object, ...]:
    """Return eager-load options needed by digest serialization and formatting."""
    return (
        selectinload(Artifact.category).selectinload(Category.subcategories),
        selectinload(Artifact.subcategory),
    )


def get_digest_items(db: Session) -> tuple[list[Artifact], int, list[Artifact]]:
    """Return recent and forgotten artifacts for the weekly digest."""
    recent_window = text("now() - interval '7 days'")
    forgotten_window = text("now() - interval '30 days'")

    total_this_week = int(
        db.execute(
            select(func.count(Artifact.id)).where(Artifact.created_at > recent_window)
        ).scalar_one()
        or 0
    )

    recent = list(
        db.execute(
            select(Artifact)
            .options(*_artifact_options())
            .where(Artifact.created_at > recent_window)
            .order_by(Artifact.created_at.desc())
            .limit(5)
        )
        .scalars()
        .all()
    )

    forgotten = list(
        db.execute(
            select(Artifact)
            .options(*_artifact_options())
            .where(
                or_(
                    Artifact.last_viewed_at.is_(None),
                    Artifact.last_viewed_at < forgotten_window,
                ),
                Artifact.digest_sent.is_(False),
                Artifact.created_at < recent_window,
            )
            .order_by(func.random())
            .limit(3)
        )
        .scalars()
        .all()
    )

    return recent, total_this_week, forgotten


def _category_name(artifact: Artifact) -> str:
    """Return an artifact's category name for digest text."""
    if artifact.category is None:
        return "Uncategorized"
    return artifact.category.name


def _artifact_line(artifact: Artifact) -> str:
    """Return one digest item line."""
    title = artifact.ai_title or "Untitled"
    return f"  • {title} [{_category_name(artifact)}]"


def format_digest_message(
    recent: list[Artifact],
    total_this_week: int,
    forgotten: list[Artifact],
    dashboard_url: str,
) -> str:
    """Format the weekly Telegram digest message."""
    lines = ["Your Stash Digest", ""]

    if not recent:
        lines.append("You haven't saved anything this week. Forward something to @StashBot!")
    else:
        lines.append(f"This week you saved {total_this_week} things. Here are {min(5, len(recent))}:")
        lines.extend(_artifact_line(artifact) for artifact in recent)

    lines.extend(["", "From your archive (you might have forgotten these):"])
    lines.extend(_artifact_line(artifact) for artifact in forgotten)

    lines.extend(["", f"Open dashboard: {dashboard_url}"])
    return "\n".join(lines)
