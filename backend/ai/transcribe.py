"""Gemini video analysis helpers for Stash video artifacts."""

from __future__ import annotations

import mimetypes
import time
from typing import Any

import vertexai
from vertexai.generative_models import GenerativeModel, Part

from ai.consistency import (
    VIDEO_TRANSCRIPTION_GENERATION_CONFIG,
    VIDEO_TRANSCRIPTION_PROMPT_VERSION,
    generate_text_with_policy,
    prompt_metadata,
)
from config import get_env, get_int_env
from logging_config import structlog
from storage.r2 import get_r2_client

logger = structlog.get_logger(__name__)

_MAX_TRANSCRIPTION_TEXT_CHARS = 4000
_DEFAULT_MAX_VIDEO_BYTES = 18_000_000


def _initialize_vertexai() -> None:
    """Initialize Vertex AI with project and region from environment."""
    project = get_env("GOOGLE_CLOUD_PROJECT", required=True)
    region = get_env("VERTEX_REGION", required=True)
    vertexai.init(project=project, location=region)


def _max_video_bytes() -> int:
    """Return the maximum video size sent inline to Gemini for delayed analysis."""
    default = get_int_env("GEMINI_INLINE_VIDEO_MAX_BYTES", _DEFAULT_MAX_VIDEO_BYTES)
    return get_int_env("GEMINI_TRANSCRIPTION_INLINE_MAX_BYTES", default)


def _guess_mime_type(r2_key: str, content_type: str | None) -> str:
    """Return the best available video MIME type for Gemini."""
    if content_type and content_type != "binary/octet-stream":
        return content_type
    guessed, _encoding = mimetypes.guess_type(r2_key)
    return guessed or "video/mp4"


def _download_r2_video(r2_key: str) -> tuple[bytes, str] | None:
    """Download a small enough R2 video object for inline Gemini analysis."""
    bucket_name = get_env("R2_BUCKET_NAME", required=True)
    client = get_r2_client()
    metadata = client.head_object(Bucket=bucket_name, Key=r2_key)
    content_length = int(metadata.get("ContentLength") or 0)
    max_bytes = _max_video_bytes()

    if content_length and content_length > max_bytes:
        logger.warning(
            "gemini_video_analysis_skipped_large_file",
            r2_key=r2_key,
            content_length=content_length,
            max_bytes=max_bytes,
            duration_ms=0,
        )
        return None

    response = client.get_object(Bucket=bucket_name, Key=r2_key)
    body = response["Body"].read()
    if len(body) > max_bytes:
        logger.warning(
            "gemini_video_analysis_skipped_large_download",
            r2_key=r2_key,
            content_length=len(body),
            max_bytes=max_bytes,
            duration_ms=0,
        )
        return None

    content_type = response.get("ContentType") or metadata.get("ContentType")
    return body, _guess_mime_type(r2_key, str(content_type) if content_type else None)


def _build_video_transcription_prompt() -> str:
    """Build the prompt used for delayed Gemini video transcription."""
    return """SYSTEM:
You create searchable notes from personal video artifacts.
Analyze the attached video using visual frames, on-screen text, spoken words, audio cues, actions, objects, and scene changes.
Return plain text only. No markdown fences. No JSON.

USER:
Create a concise but detailed searchable transcript for this video.
Include:
- spoken words or a faithful summary if exact transcription is uncertain
- on-screen text
- notable visual objects, actions, scenes, and timestamps when useful
- enough context for a later classifier to categorize the video accurately

If there is no speech, still describe the visual content and any text visible in the video."""


def transcribe_from_r2(r2_key: str) -> str:
    """Analyze a stored video with Gemini and return searchable transcript text."""
    started_at = time.monotonic()

    try:
        downloaded = _download_r2_video(r2_key)
        if downloaded is None:
            return ""

        video_bytes, mime_type = downloaded
        _initialize_vertexai()
        model_name = get_env("GEMINI_VIDEO_MODEL") or get_env("GEMINI_MODEL", required=True)
        model = GenerativeModel(model_name)
        prompt = _build_video_transcription_prompt()
        prompt_info = prompt_metadata(prompt, VIDEO_TRANSCRIPTION_PROMPT_VERSION)
        response, call_policy = generate_text_with_policy(
            model,
            [Part.from_data(video_bytes, mime_type=mime_type), prompt],
            generation_config=VIDEO_TRANSCRIPTION_GENERATION_CONFIG,
        )
        transcript = str(getattr(response, "text", "") or "")[:_MAX_TRANSCRIPTION_TEXT_CHARS].strip()
        duration_seconds = time.monotonic() - started_at
        logger.info(
            "gemini_video_analysis_completed",
            r2_key=r2_key,
            model_name=model_name,
            prompt_version=prompt_info.version,
            prompt_hash=prompt_info.prompt_hash,
            generation_config=call_policy.generation_config,
            duration_seconds=round(duration_seconds, 2),
            duration_ms=int(duration_seconds * 1000),
            transcript_chars=len(transcript),
        )
        return transcript
    except Exception:
        duration_seconds = time.monotonic() - started_at
        logger.exception(
            "gemini_video_analysis_failed",
            r2_key=r2_key,
            duration_seconds=round(duration_seconds, 2),
            duration_ms=int(duration_seconds * 1000),
        )
        return ""
