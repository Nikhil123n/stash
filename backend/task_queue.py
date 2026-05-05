"""Lightweight task publishing helpers for API processes."""

from __future__ import annotations

from typing import Any

from celery_app import celery

PROCESS_ARTIFACT_TASK = "tasks.process_artifact"


def enqueue_process_artifact(payload: dict[str, Any]) -> None:
    """Publish an artifact processing job without importing worker task modules."""
    celery.send_task(PROCESS_ARTIFACT_TASK, args=[payload])
