"""Shared Celery application configuration for Stash tasks."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from config import get_env

REDIS_URL: str = get_env("REDIS_URL", required=True)

celery: Celery = Celery("stash", broker=REDIS_URL, backend=REDIS_URL)
celery.conf.update(
    accept_content=["json"],
    beat_schedule={
        "weekly-digest": {
            "task": "tasks.send_weekly_digest",
            "schedule": crontab(hour=10, minute=0, day_of_week="sun"),
        },
        "category-evolution": {
            "task": "tasks.check_category_evolution",
            "schedule": crontab(hour=2, minute=0),
        },
        "update-prompts": {
            "task": "tasks.update_classification_prompts",
            "schedule": crontab(hour=3, minute=0),
        },
    },
    enable_utc=True,
    result_serializer="json",
    task_serializer="json",
    timezone="UTC",
)
