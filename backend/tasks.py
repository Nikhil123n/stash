"""Celery task definitions for Stash artifact ingestion and scheduled jobs."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from typing import Any
from uuid import UUID, uuid4

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ai.classify import classify_artifact, classify_from_transcript
from ai.evolve import run_tier2_evolution
from ai.transcribe import transcribe_from_r2
from bot import MessagePayload, get_bot, get_redis_client, send_confirmation, send_error, send_subcategory_proposal
from config import get_env, get_int_env
from digest import format_digest_message, get_digest_items
from logging_config import structlog
from storage.db import (
    Artifact,
    Category,
    PromptExample,
    SessionLocal,
    UserCorrection,
    get_existing_category_names,
    get_or_create_category,
    get_prompt_examples,
    record_model_change_if_needed,
)
from storage.r2 import download_telegram_file, fetch_og_metadata, upload_to_r2

logger = structlog.get_logger(__name__)

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


def _safe_async_run(coro: Any) -> Any:
    """Run an async Telegram helper from the synchronous Celery task context."""
    return asyncio.run(coro)


def _duration_ms(started_at: float) -> int:
    """Return elapsed milliseconds from a monotonic start time."""
    return int((time.perf_counter() - started_at) * 1000)


def _original_filename_or_type(payload: dict[str, Any]) -> str:
    """Return a stable filename component for an R2 object key."""
    for key in ("original_filename", "file_name", "filename"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\\", "_").replace("/", "_")

    input_type = str(payload.get("input_type") or "artifact")
    mime_type = payload.get("mime_type")
    extension = mimetypes.guess_extension(str(mime_type)) if mime_type else None
    return f"{input_type}{extension or ''}"


def _build_media_content_data(
    payload: MessagePayload,
    file_bytes: bytes | None,
) -> dict[str, Any]:
    """Create the classification content_data dictionary for a media payload."""
    input_type = payload["input_type"]
    if input_type == "image":
        return {"image_bytes": file_bytes, "caption": payload.get("caption")}
    if input_type == "video_file":
        max_video_bytes = get_int_env("GEMINI_INLINE_VIDEO_MAX_BYTES", 18_000_000)
        inline_video = file_bytes if file_bytes is not None and len(file_bytes) <= max_video_bytes else None
        return {
            "transcript": "",
            "image_bytes": None,
            "video_bytes": inline_video,
            "video_mime_type": payload.get("mime_type") or "video/mp4",
        }
    raise ValueError(f"Unsupported media input_type: {input_type}")


def _analysis_text_for_storage(
    content_data: dict[str, Any],
    classification_result: dict[str, Any],
) -> str | None:
    """Return searchable rich text produced during multimodal processing."""
    transcript = content_data.get("transcript")
    if isinstance(transcript, str) and transcript.strip():
        return transcript.strip()

    content_details = classification_result.get("content_details")
    if isinstance(content_details, str) and content_details.strip():
        return content_details.strip()

    return None


def _build_content_data(payload: MessagePayload, file_bytes: bytes | None) -> dict[str, Any]:
    """Create the content_data dictionary for classification."""
    input_type = payload["input_type"]

    if input_type == "text":
        return {"text": payload.get("text")}
    if input_type in {"image", "video_file"}:
        return _build_media_content_data(payload, file_bytes)
    if input_type in {"instagram_url", "linkedin_url", "url"}:
        url = payload.get("url")
        if not url:
            raise ValueError("URL artifact payload is missing url.")
        return fetch_og_metadata(url)

    raise ValueError(f"Unsupported input_type for processing: {input_type}")


def _update_search_vector(db: Session, artifact_id: Any) -> None:
    """Refresh the artifact search vector inside the current transaction."""
    db.execute(
        text(
            """
            UPDATE artifacts
            SET search_vector =
                to_tsvector(
                    'english',
                    coalesce(ai_title, '') || ' ' ||
                    coalesce(ai_summary, '') || ' ' ||
                    coalesce(ai_transcript, '') || ' ' ||
                    coalesce(array_to_string(ai_tags, ' '), '')
                )
            WHERE id = :id
            """
        ),
        {"id": artifact_id},
    )


def _increment_category_count(db: Session, category_id: Any) -> None:
    """Increment a category's item_count atomically."""
    db.execute(
        text("UPDATE categories SET item_count = item_count + 1 WHERE id = :id"),
        {"id": category_id},
    )


def _decrement_category_count(db: Session, category_id: Any) -> None:
    """Decrement a category's item_count without going below zero."""
    db.execute(
        text("UPDATE categories SET item_count = GREATEST(item_count - 1, 0) WHERE id = :id"),
        {"id": category_id},
    )


async def _send_video_processed(chat_id: int, title: str, category_name: str) -> None:
    """Send a Telegram update after delayed video transcription improves classification."""
    await get_bot().send_message(
        chat_id=chat_id,
        text=f"Video processed: {title} [{category_name}]",
        parse_mode="Markdown",
    )


@celery.task(bind=True, max_retries=3, default_retry_delay=30)
def process_artifact(self: Any, payload: dict[str, Any]) -> None:
    """Process one normalized Telegram artifact payload end to end."""
    artifact_id: Any = "pending"
    input_type = str(payload.get("input_type"))
    db: Session | None = None
    started_at = time.perf_counter()

    try:
        typed_payload: MessagePayload = payload  # type: ignore[assignment]
        db = SessionLocal()
        record_model_change_if_needed(db, get_env("GEMINI_MODEL", required=True), commit=True)

        logger.info("artifact_media_download_starting", artifact_id=artifact_id, input_type=input_type, duration_ms=0)
        file_bytes: bytes | None = None
        r2_key: str | None = None
        if input_type in {"video_file", "image"}:
            file_id = payload.get("file_id")
            if not isinstance(file_id, str) or not file_id:
                raise ValueError("Media artifact payload is missing file_id.")

            file_bytes = download_telegram_file(file_id)
            object_key = f"artifacts/{uuid4()}/{_original_filename_or_type(payload)}"
            content_type = str(payload.get("mime_type") or "application/octet-stream")
            r2_key = upload_to_r2(file_bytes, object_key, content_type)
        logger.info(
            "artifact_media_download_complete",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )

        logger.info(
            "artifact_content_extraction_starting",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        content_data = _build_content_data(typed_payload, file_bytes)
        logger.info(
            "artifact_content_extraction_complete",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )

        logger.info(
            "artifact_category_list_fetch_starting",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        existing_categories = get_existing_category_names(db)
        logger.info(
            "artifact_category_list_fetch_complete",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )

        logger.info(
            "artifact_classification_starting",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        result = classify_artifact(typed_payload, content_data, existing_categories, db=db)
        logger.info(
            "artifact_classification_complete",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )

        logger.info(
            "artifact_category_lookup_starting",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        category: Category = get_or_create_category(db, result["category"])
        logger.info(
            "artifact_category_lookup_complete",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )

        logger.info(
            "artifact_insert_starting",
            artifact_id=artifact_id,
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        artifact = Artifact(
            source_type=input_type,
            raw_url=payload.get("url"),
            r2_key=r2_key,
            telegram_msg_id=payload.get("telegram_msg_id"),
            ai_title=result["title"],
            ai_summary=result["summary"],
            ai_tags=result["tags"],
            ai_transcript=_analysis_text_for_storage(content_data, result),
            ai_confidence=result["confidence"],
            ai_audit=result.get("ai_audit"),
            category_id=category.id,
            subcategory_id=None,
            user_overridden=False,
            view_count=0,
            last_viewed_at=None,
            digest_sent=False,
        )
        db.add(artifact)
        db.flush()
        artifact_id = artifact.id
        _update_search_vector(db, artifact_id)
        logger.info(
            "artifact_insert_complete",
            artifact_id=str(artifact_id),
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )

        logger.info(
            "artifact_category_count_increment_starting",
            artifact_id=str(artifact_id),
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        _increment_category_count(db, category.id)
        db.commit()
        db.refresh(category)
        logger.info(
            "artifact_category_count_increment_complete",
            artifact_id=str(artifact_id),
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )

        if input_type == "video_file" and r2_key is not None:
            logger.info(
                "video_transcription_queued",
                artifact_id=str(artifact_id),
                input_type=input_type,
                duration_ms=_duration_ms(started_at),
            )
            transcribe_and_update.delay(str(artifact_id), r2_key, int(payload["chat_id"]))

        logger.info(
            "artifact_confirmation_send_starting",
            artifact_id=str(artifact_id),
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        confirmation_title = result["title"]
        if result["needs_review"]:
            confirmation_title = f"{confirmation_title} (low confidence - check dashboard)"
        _safe_async_run(send_confirmation(int(payload["chat_id"]), category.name, confirmation_title))
        logger.info(
            "artifact_confirmation_send_complete",
            artifact_id=str(artifact_id),
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
    except Exception as exc:
        logger.exception(
            "artifact_processing_failed",
            artifact_id=str(artifact_id),
            input_type=input_type,
            duration_ms=_duration_ms(started_at),
        )
        if db is not None:
            db.rollback()

        if self.request.retries >= self.max_retries:
            try:
                chat_id = payload.get("chat_id")
                if chat_id is not None:
                    _safe_async_run(send_error(int(chat_id), "Failed to process."))
            except Exception:
                logger.exception(
                    "telegram_final_processing_error_failed",
                    artifact_id=str(artifact_id),
                    input_type=input_type,
                    duration_ms=_duration_ms(started_at),
                )
            raise

        raise self.retry(exc=exc)
    finally:
        if db is not None:
            db.close()


@celery.task
def transcribe_and_update(artifact_id: str, r2_key: str, chat_id: int) -> None:
    """Transcribe a stored video and update artifact metadata when confidence improves."""
    db: Session | None = None
    started_at = time.perf_counter()

    try:
        artifact_uuid = UUID(str(artifact_id))
        logger.info(
            "video_transcription_task_started",
            artifact_id=artifact_id,
            input_type="video_file",
            r2_key=r2_key,
            duration_ms=0,
        )
        transcript = transcribe_from_r2(r2_key)
        if not transcript:
            logger.info(
                "video_transcription_empty",
                artifact_id=artifact_id,
                input_type="video_file",
                r2_key=r2_key,
                duration_ms=_duration_ms(started_at),
            )
            return

        db = SessionLocal()
        record_model_change_if_needed(db, get_env("GEMINI_MODEL", required=True), commit=True)
        db.execute(
            text("UPDATE artifacts SET ai_transcript = :transcript WHERE id = :id"),
            {"transcript": transcript, "id": artifact_uuid},
        )

        artifact = db.execute(select(Artifact).where(Artifact.id == artifact_uuid)).scalar_one_or_none()
        if artifact is None:
            logger.warning(
                "video_transcription_artifact_not_found",
                artifact_id=artifact_id,
                input_type="video_file",
                duration_ms=_duration_ms(started_at),
            )
            db.rollback()
            return

        existing_categories = get_existing_category_names(db)
        result = classify_from_transcript(
            transcript,
            existing_categories,
            few_shot_examples=get_prompt_examples(db, "video_file"),
        )

        stored_confidence = float(artifact.ai_confidence or 0.0)
        old_category_id = artifact.category_id
        category_changed = False
        category_name = artifact.category.name if artifact.category is not None else "Unknown"

        if result["confidence"] > stored_confidence:
            new_category = get_or_create_category(db, result["category"])
            category_changed = old_category_id != new_category.id

            if category_changed and old_category_id is not None:
                _decrement_category_count(db, old_category_id)
                _increment_category_count(db, new_category.id)

            artifact.category_id = new_category.id
            artifact.ai_title = result["title"]
            artifact.ai_summary = result["summary"]
            artifact.ai_tags = result["tags"]
            artifact.ai_confidence = result["confidence"]
            artifact.ai_audit = result.get("ai_audit")
            category_name = new_category.name

        _update_search_vector(db, artifact_uuid)
        db.commit()

        if category_changed:
            title = str(artifact.ai_title or result["title"])
            _safe_async_run(_send_video_processed(chat_id, title, category_name))

        logger.info(
            "video_transcription_task_completed",
            artifact_id=artifact_id,
            input_type="video_file",
            confidence=result["confidence"],
            category_changed=category_changed,
            duration_ms=_duration_ms(started_at),
        )
    except Exception:
        logger.exception(
            "video_transcription_task_failed",
            artifact_id=artifact_id,
            input_type="video_file",
            r2_key=r2_key,
            duration_ms=_duration_ms(started_at),
        )
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()


@celery.task
def check_category_evolution() -> None:
    """Check mature categories and ask the user to confirm proposed subcategories."""
    started_at = time.perf_counter()
    logger.info("category_evolution_check_triggered", duration_ms=0)
    chat_id_value = get_env("YOUR_CHAT_ID") or get_env("TELEGRAM_CHAT_ID")
    if not chat_id_value:
        logger.warning("category_evolution_skipped_missing_chat_id", duration_ms=_duration_ms(started_at))
        return

    try:
        chat_id = int(chat_id_value)
    except ValueError:
        logger.warning("category_evolution_skipped_invalid_chat_id", duration_ms=_duration_ms(started_at))
        return

    db: Session | None = None
    try:
        db = SessionLocal()
        redis_client = get_redis_client()
        categories = list(
            db.execute(select(Category).where(Category.item_count >= 10).order_by(Category.item_count.desc()))
            .scalars()
            .all()
        )

        for category in categories:
            proposals = run_tier2_evolution(db, category.id)
            if not proposals:
                continue

            redis_key = f"pending_proposal:{chat_id}:{category.id}"
            redis_client.setex(redis_key, 48 * 60 * 60, json.dumps(proposals))
            _safe_async_run(
                send_subcategory_proposal(
                    chat_id=chat_id,
                    category_name=category.name,
                    proposals=proposals,
                    category_id=str(category.id),
                )
            )
            logger.info(
                "category_evolution_proposal_stored",
                category_id=str(category.id),
                redis_key=redis_key,
                duration_ms=_duration_ms(started_at),
            )
    except Exception:
        logger.exception("category_evolution_check_failed", duration_ms=_duration_ms(started_at))
    finally:
        if db is not None:
            db.close()


@celery.task
def send_weekly_digest() -> None:
    """Send the weekly Telegram digest and mark archived items as surfaced."""
    started_at = time.perf_counter()
    logger.info("weekly_digest_triggered", duration_ms=0)
    chat_id_value = get_env("YOUR_CHAT_ID") or get_env("TELEGRAM_CHAT_ID")
    if not chat_id_value:
        logger.warning("weekly_digest_skipped_missing_chat_id", duration_ms=_duration_ms(started_at))
        return

    try:
        chat_id = int(chat_id_value)
    except ValueError:
        logger.warning("weekly_digest_skipped_invalid_chat_id", duration_ms=_duration_ms(started_at))
        return

    dashboard_url = get_env("DASHBOARD_URL", required=True)
    db: Session | None = None

    try:
        db = SessionLocal()
        recent, total_this_week, forgotten = get_digest_items(db)
        message = format_digest_message(
            recent=recent,
            total_this_week=total_this_week,
            forgotten=forgotten,
            dashboard_url=dashboard_url,
        )

        _safe_async_run(
            get_bot().send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )
        )

        forgotten_ids = [artifact.id for artifact in forgotten]
        if forgotten_ids:
            db.execute(
                update(Artifact)
                .where(Artifact.id.in_(forgotten_ids))
                .values(digest_sent=True)
            )
            db.commit()

        logger.info(
            "weekly_digest_sent",
            recent_count=len(recent),
            forgotten_count=len(forgotten),
            total_this_week=total_this_week,
            duration_ms=_duration_ms(started_at),
        )
    except Exception:
        logger.exception("weekly_digest_failed", duration_ms=_duration_ms(started_at))
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()


@celery.task
def update_classification_prompts() -> None:
    """Build few-shot prompt examples from repeated manual correction patterns."""
    started_at = time.perf_counter()
    logger.info("classification_prompt_update_triggered", duration_ms=0)
    db: Session | None = None

    try:
        db = SessionLocal()
        patterns = db.execute(
            select(
                UserCorrection.from_category,
                UserCorrection.to_category,
                Artifact.source_type,
                func.count(UserCorrection.id).label("correction_count"),
            )
            .join(Artifact, UserCorrection.artifact_id == Artifact.id)
            .where(
                UserCorrection.from_category.is_not(None),
                UserCorrection.to_category.is_not(None),
                UserCorrection.from_category != UserCorrection.to_category,
            )
            .group_by(
                UserCorrection.from_category,
                UserCorrection.to_category,
                Artifact.source_type,
            )
            .having(func.count(UserCorrection.id) >= 3)
        ).all()

        upsert_count = 0
        for from_category_id, to_category_id, source_type, _correction_count in patterns:
            target_category = db.get(Category, to_category_id)
            if target_category is None:
                continue

            artifact = db.execute(
                select(Artifact)
                .join(UserCorrection, UserCorrection.artifact_id == Artifact.id)
                .where(
                    UserCorrection.from_category == from_category_id,
                    UserCorrection.to_category == to_category_id,
                    Artifact.source_type == source_type,
                )
                .order_by(UserCorrection.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if artifact is None:
                continue

            content_text = (
                artifact.ai_summary
                or artifact.ai_title
                or artifact.ai_transcript
                or artifact.raw_url
                or ""
            ).strip()
            if not content_text:
                continue

            stmt = insert(PromptExample).values(
                source_type=source_type,
                content_text=content_text,
                correct_category=target_category.name,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["source_type", "correct_category"],
                set_={
                    "content_text": content_text,
                    "created_at": func.now(),
                },
            )
            db.execute(stmt)
            upsert_count += 1

        db.commit()
        logger.info(
            "classification_prompt_update_completed",
            upsert_count=upsert_count,
            duration_ms=_duration_ms(started_at),
        )
    except Exception:
        logger.exception("classification_prompt_update_failed", duration_ms=_duration_ms(started_at))
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()
