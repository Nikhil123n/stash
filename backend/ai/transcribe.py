"""Whisper transcription helpers for Stash video artifacts."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

import psutil
import whisper

from config import get_env, get_int_env, get_path_env
from logging_config import structlog
from storage.r2 import get_r2_client

logger = structlog.get_logger(__name__)

_model: Any | None = None
_MIN_AVAILABLE_MEMORY_BYTES = get_int_env("WHISPER_MIN_AVAILABLE_MEMORY_BYTES", 800 * 1024 * 1024)


class TranscriptionResult(TypedDict):
    """Structured result metadata for a Whisper transcription run."""

    transcript: str
    duration_seconds: float


def get_whisper_model() -> Any:
    """Load and cache the Whisper base model."""
    global _model

    if _model is None:
        _model = whisper.load_model(get_env("WHISPER_MODEL", required=True))
    return _model


def _has_enough_memory() -> bool:
    """Return whether the worker has enough available memory for Whisper base."""
    available = psutil.virtual_memory().available
    if available < _MIN_AVAILABLE_MEMORY_BYTES:
        logger.warning(
            "whisper_transcription_skipped_low_memory",
            available_memory_bytes=available,
            duration_ms=0,
        )
        return False
    return True


def _tmp_video_path() -> Path:
    """Create a stable temporary MP4 path under /tmp."""
    tmp_dir = get_path_env("STASH_TMP_DIR", "/tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / f"{uuid4()}.mp4"


def transcribe_from_r2(r2_key: str) -> str:
    """Download a video from R2, transcribe it with Whisper, and clean up."""
    if not _has_enough_memory():
        return ""

    tmp_path = _tmp_video_path()
    started_at = time.monotonic()

    try:
        bucket_name = get_env("R2_BUCKET_NAME", required=True)

        get_r2_client().download_file(bucket_name, r2_key, str(tmp_path))
        result = get_whisper_model().transcribe(str(tmp_path), fp16=False)
        transcript = str(result.get("text") or "")[:4000].strip()
        duration_seconds = time.monotonic() - started_at
        logger.info(
            "whisper_transcription_completed",
            r2_key=r2_key,
            duration_seconds=round(duration_seconds, 2),
            duration_ms=int(duration_seconds * 1000),
            transcript_chars=len(transcript),
        )
        return transcript
    except Exception:
        duration_seconds = time.monotonic() - started_at
        logger.exception(
            "whisper_transcription_failed",
            r2_key=r2_key,
            duration_seconds=round(duration_seconds, 2),
            duration_ms=int(duration_seconds * 1000),
        )
        return ""
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            logger.exception("temporary_transcription_file_delete_failed", tmp_path=str(tmp_path), duration_ms=0)
