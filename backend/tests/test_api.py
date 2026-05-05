"""Tests for Stash dashboard REST API routes."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app
from storage.db import get_db


class FakeResult:
    """Small stand-in for SQLAlchemy execute results used by API tests."""

    def __init__(self, value: object = None) -> None:
        self.value = value

    def scalars(self) -> "FakeResult":
        """Return self for chained scalars().all() calls."""
        return self

    def all(self) -> list[object]:
        """Return the stored list value."""
        return list(self.value or [])

    def scalar_one(self) -> object:
        """Return the stored scalar value."""
        return self.value

    def scalar_one_or_none(self) -> object:
        """Return the stored object or None."""
        return self.value


class FakeSession:
    """Queue-backed fake database session for route tests."""

    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.added: list[object] = []
        self.commits = 0

    def execute(self, _statement: object, _params: object | None = None) -> FakeResult:
        """Return the next queued fake execute result."""
        if not self.results:
            return FakeResult()
        return self.results.pop(0)

    def add(self, value: object) -> None:
        """Record an added ORM object."""
        self.added.append(value)

    def commit(self) -> None:
        """Record a commit call."""
        self.commits += 1

    def close(self) -> None:
        """Fake close hook for dependency compatibility."""

    def delete(self, _value: object) -> None:
        """Fake delete hook for dependency compatibility."""


def make_category(
    category_id: UUID | None = None,
    name: str = "Coding",
    slug: str = "coding",
    count: int = 1,
) -> SimpleNamespace:
    """Create a category-like object for serializers."""
    return SimpleNamespace(
        id=category_id or uuid4(),
        name=name,
        slug=slug,
        icon=None,
        item_count=count,
        created_at=datetime.now(UTC),
        subcategories=[],
    )


def make_artifact(
    artifact_id: UUID | None = None,
    category: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Create an artifact-like object for serializers."""
    resolved_category = category or make_category()
    return SimpleNamespace(
        id=artifact_id or uuid4(),
        created_at=datetime.now(UTC),
        source_type="text",
        raw_url=None,
        r2_key=None,
        ai_title="FastAPI Routes",
        ai_summary="Dashboard API route notes.",
        ai_tags=["fastapi", "api", "dashboard"],
        ai_transcript=None,
        ai_confidence=0.91,
        category_id=resolved_category.id,
        subcategory_id=None,
        category=resolved_category,
        subcategory=None,
        user_overridden=False,
        view_count=0,
        last_viewed_at=None,
    )


@contextmanager
def override_db(session: FakeSession) -> Iterator[None]:
    """Temporarily override the FastAPI database dependency."""
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_get_categories_returns_list(monkeypatch) -> None:
    """GET /api/categories returns serialized categories with thumbnails."""
    monkeypatch.setenv("SKIP_AUTH", "true")
    monkeypatch.setenv("R2_BUCKET_ID", "bucket")
    category = make_category()
    session = FakeSession(
        [
            FakeResult([category]),
            FakeResult(["artifacts/image.jpg"]),
        ]
    )

    with override_db(session):
        response = TestClient(app).get("/api/categories")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Coding"
    assert response.json()[0]["recent_thumbnails"] == [
        "https://pub-bucket.r2.dev/artifacts/image.jpg"
    ]


def test_search_artifacts_returns_results(monkeypatch) -> None:
    """GET /api/artifacts/search returns artifact results."""
    monkeypatch.setenv("SKIP_AUTH", "true")
    artifact = make_artifact()
    session = FakeSession([FakeResult([artifact])])

    with override_db(session):
        response = TestClient(app).get("/api/artifacts/search?q=api")

    assert response.status_code == 200
    assert response.json()[0]["ai_title"] == "FastAPI Routes"
    assert response.json()[0]["category"]["name"] == "Coding"


def test_patch_recategorize_updates_category_and_logs_correction(monkeypatch) -> None:
    """PATCH /api/artifacts/{id} updates category and records a correction."""
    monkeypatch.setenv("SKIP_AUTH", "true")
    artifact_id = uuid4()
    old_category = make_category(name="Coding", slug="coding")
    new_category = make_category(name="Business", slug="business")
    old_artifact = make_artifact(artifact_id=artifact_id, category=old_category)
    updated_artifact = make_artifact(artifact_id=artifact_id, category=new_category)
    updated_artifact.category_id = new_category.id
    updated_artifact.user_overridden = True
    session = FakeSession(
        [
            FakeResult(old_artifact),
            FakeResult(new_category),
            FakeResult(),
            FakeResult(),
            FakeResult(updated_artifact),
        ]
    )

    with override_db(session):
        response = TestClient(app).patch(
            f"/api/artifacts/{artifact_id}",
            json={"category_id": str(new_category.id)},
        )

    assert response.status_code == 200
    assert response.json()["category"]["name"] == "Business"
    assert response.json()["user_overridden"] is True
    assert session.commits == 1
    assert len(session.added) == 1
    correction = session.added[0]
    assert correction.artifact_id == artifact_id
    assert correction.from_category == old_category.id
    assert correction.to_category == new_category.id
