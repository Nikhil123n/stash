"""Tests for Gemini model change tracking."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://stash:stash@localhost:5432/stash")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from storage.db import LLMModelState, ModelChangeEvent, record_model_change_if_needed


class FakeSession:
    """Minimal session fake for model-state guard tests."""

    def __init__(self, state: LLMModelState | None = None) -> None:
        self.state = state
        self.added: list[Any] = []
        self.flushes = 0
        self.commits = 0

    def get(self, model: object, key: str) -> LLMModelState | None:
        """Return the stored model state."""
        if model is LLMModelState and key == "gemini_model":
            return self.state
        return None

    def add(self, value: Any) -> None:
        """Record added ORM objects."""
        self.added.append(value)
        if isinstance(value, LLMModelState):
            self.state = value

    def flush(self) -> None:
        """Record flush calls."""
        self.flushes += 1

    def commit(self) -> None:
        """Record commit calls."""
        self.commits += 1


def test_record_model_change_initializes_state() -> None:
    """The first observed model is saved as state without a change event."""
    session = FakeSession()

    record_model_change_if_needed(session, "gemini-2.5-flash", commit=True)  # type: ignore[arg-type]

    assert isinstance(session.state, LLMModelState)
    assert session.state.model_name == "gemini-2.5-flash"
    assert not any(isinstance(value, ModelChangeEvent) for value in session.added)
    assert session.commits == 1


def test_record_model_change_writes_event() -> None:
    """A changed GEMINI_MODEL value creates an audit event before work continues."""
    state = LLMModelState(name="gemini_model", model_name="gemini-2.5-flash")
    session = FakeSession(state)

    record_model_change_if_needed(session, "gemini-2.5-pro", commit=True)  # type: ignore[arg-type]

    events = [value for value in session.added if isinstance(value, ModelChangeEvent)]
    assert len(events) == 1
    assert events[0].old_model == "gemini-2.5-flash"
    assert events[0].new_model == "gemini-2.5-pro"
    assert state.model_name == "gemini-2.5-pro"
    assert session.commits == 1
