"""Lightweight task publishing helpers for API processes."""

from __future__ import annotations

import threading
from typing import Any

from celery_app import celery
from config import get_env
from logging_config import structlog

PROCESS_ARTIFACT_TASK = "tasks.process_artifact"

logger = structlog.get_logger(__name__)


def _runs_inline() -> bool:
    """Return whether the API process should execute queued work itself."""
    return get_env("TASK_EXECUTION_MODE", "celery").strip().lower() == "inline"


def _run_process_artifact_inline(payload: dict[str, Any]) -> None:
    """Run artifact processing in the API process for free-tier deployments."""
    try:
        from tasks import process_artifact

        result = process_artifact.apply(args=[payload], throw=False)
        failed = getattr(result, "failed", lambda: False)
        if failed():
            logger.error(
                "inline_process_artifact_failed",
                task_name=PROCESS_ARTIFACT_TASK,
                error=str(getattr(result, "result", "")),
                duration_ms=0,
            )
    except Exception:
        logger.exception(
            "inline_process_artifact_failed",
            task_name=PROCESS_ARTIFACT_TASK,
            duration_ms=0,
        )


def enqueue_process_artifact(payload: dict[str, Any]) -> None:
    """Publish an artifact processing job without importing worker task modules."""
    if _runs_inline():
        thread = threading.Thread(
            target=_run_process_artifact_inline,
            args=(dict(payload),),
            name="stash-process-artifact",
            daemon=True,
        )
        thread.start()
        logger.info(
            "inline_process_artifact_started",
            task_name=PROCESS_ARTIFACT_TASK,
            input_type=payload.get("input_type"),
            duration_ms=0,
        )
        return

    celery.send_task(PROCESS_ARTIFACT_TASK, args=[payload])
