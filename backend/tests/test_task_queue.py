"""Tests for task publishing modes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import task_queue


class FakeThread:
    """Thread stand-in that runs the target immediately."""

    def __init__(
        self,
        *,
        target: Any,
        args: tuple[object, ...],
        name: str,
        daemon: bool,
    ) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        """Run the configured target synchronously for deterministic tests."""
        self.target(*self.args)


def test_enqueue_process_artifact_uses_celery_by_default(monkeypatch) -> None:
    """Celery remains the default execution mode."""
    sent: list[tuple[str, list[dict[str, str]]]] = []
    fake_celery = SimpleNamespace(send_task=lambda name, args: sent.append((name, args)))
    monkeypatch.delenv("TASK_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(task_queue, "celery", fake_celery)

    task_queue.enqueue_process_artifact({"input_type": "text"})

    assert sent == [(task_queue.PROCESS_ARTIFACT_TASK, [{"input_type": "text"}])]


def test_enqueue_process_artifact_inline_runs_in_background_thread(monkeypatch) -> None:
    """Inline mode executes the Celery task in the API process."""
    applied: list[tuple[list[dict[str, str]], bool]] = []
    fake_task = SimpleNamespace(
        apply=lambda args, throw: applied.append((args, throw)) or SimpleNamespace(failed=lambda: False)
    )
    fake_tasks_module = SimpleNamespace(process_artifact=fake_task)
    monkeypatch.setenv("TASK_EXECUTION_MODE", "inline")
    monkeypatch.setitem(sys.modules, "tasks", fake_tasks_module)
    monkeypatch.setattr(task_queue.threading, "Thread", FakeThread)

    task_queue.enqueue_process_artifact({"input_type": "video_file"})

    assert applied == [([{"input_type": "video_file"}], False)]
