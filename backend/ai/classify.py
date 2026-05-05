"""Gemini Flash classification pipeline for Stash artifacts."""

from __future__ import annotations

import json
import re
from typing import Any, TypedDict
from urllib.parse import urlparse

import vertexai
from vertexai.generative_models import GenerativeModel, Part

from bot import MessagePayload
from config import get_env
from logging_config import structlog

logger = structlog.get_logger(__name__)


class ClassificationError(RuntimeError):
    """Raised when Gemini classification cannot produce a usable result."""


class ClassificationResult(TypedDict):
    """Validated classification response returned by the Gemini pipeline."""

    title: str
    summary: str
    tags: list[str]
    category: str
    is_new_category: bool
    confidence: float
    needs_review: bool


_MODEL_NAME = get_env("GEMINI_MODEL", required=True)
_REQUIRED_RESPONSE_FIELDS = {
    "title",
    "summary",
    "tags",
    "category",
    "is_new_category",
    "confidence",
}


def build_classification_prompt(
    source_type: str,
    content_text: str,
    category_list: list[str],
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> str:
    """Build the Section 7.1 Gemini classification prompt."""
    if category_list:
        category_instruction = "Reuse one of these if it fits:\n" + "\n".join(f"- {name}" for name in category_list)
    else:
        category_instruction = (
            "No categories exist yet. Create an appropriate high-level category for this content."
        )

    examples_block = ""
    if few_shot_examples:
        example_lines = [
            f"Content: {example.get('content_text', '')} -> Category: {example.get('correct_category', '')}"
            for example in few_shot_examples
        ]
        examples_block = "## Examples from your corrections:\n" + "\n".join(example_lines) + "\n\n"

    return f"""SYSTEM:
You are a personal content classifier for a knowledge library.
You will be given content metadata and must return structured JSON.
Return ONLY valid JSON. No markdown. No preamble.

USER:
Content type: {source_type}
Raw text / transcript / URL title: {content_text}
Existing categories in library:
{category_instruction}

{examples_block}\
Return this exact JSON structure:
{{
  "title": "<10-word title>",
  "summary": "<1-2 sentence description>",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "<best matching category name OR new category name>",
  "is_new_category": true/false,
  "confidence": 0.0-1.0
}}

Classify the substance of the saved content, not merely the source platform or website host.
If extracted page text, transcript, or article content is present, prioritize that over generic Open Graph metadata.
Only set "is_new_category" to true when no existing category fits well. Prefer existing categories unless a new category is clearly better."""


def _strip_json_fences(raw: str) -> str:
    """Remove common Markdown JSON fences from a Gemini response."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def parse_gemini_response(raw: str) -> ClassificationResult:
    """Parse and validate Gemini JSON into a ClassificationResult."""
    cleaned = _strip_json_fences(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.exception("gemini_classification_parse_failed", raw_response=raw, duration_ms=0)
        raise ValueError(f"Invalid Gemini JSON response: {raw}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Gemini response must be a JSON object: {raw}")

    missing_fields = _REQUIRED_RESPONSE_FIELDS.difference(parsed)
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ValueError(f"Gemini response missing required fields ({missing}): {raw}")

    tags = parsed["tags"]
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError(f"Gemini response field 'tags' must be a list of strings: {raw}")

    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Gemini response field 'confidence' must be numeric: {raw}") from exc

    if confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"Gemini response field 'confidence' must be between 0.0 and 1.0: {raw}")

    return {
        "title": str(parsed["title"]),
        "summary": str(parsed["summary"]),
        "tags": tags,
        "category": str(parsed["category"]),
        "is_new_category": bool(parsed["is_new_category"]),
        "confidence": confidence,
        "needs_review": confidence < 0.7,
    }


def _initialize_vertexai() -> None:
    """Initialize Vertex AI with project and region from environment."""
    project = get_env("GOOGLE_CLOUD_PROJECT", required=True)
    region = get_env("VERTEX_REGION", required=True)
    vertexai.init(project=project, location=region)


def _generate_and_parse(prompt_or_parts: str | list[Any], context: str) -> ClassificationResult:
    """Run Gemini and translate Vertex or parsing failures into ClassificationError."""
    try:
        _initialize_vertexai()
        model = GenerativeModel(_MODEL_NAME)
        response = model.generate_content(prompt_or_parts)
    except Exception as exc:
        message = str(exc)
        if "quota" in message.lower():
            raise ClassificationError(f"Vertex AI quota error during {context}: {message}") from exc
        raise ClassificationError(f"Vertex AI classification failed during {context}: {message}") from exc

    raw_response = getattr(response, "text", "")
    try:
        return parse_gemini_response(raw_response)
    except ValueError as exc:
        logger.exception("gemini_classification_invalid_response", raw_response=raw_response, duration_ms=0)
        raise ClassificationError(f"Invalid Gemini response during {context}: {raw_response}") from exc


def classify_text(
    text: str,
    existing_categories: list[str],
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> ClassificationResult:
    """Classify plain text content with Gemini Flash."""
    prompt = build_classification_prompt(
        source_type="text",
        content_text=text,
        category_list=existing_categories,
        few_shot_examples=few_shot_examples,
    )
    return _generate_and_parse(prompt, "text classification")


def classify_image(
    image_bytes: bytes,
    caption: str | None,
    existing_categories: list[str],
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> ClassificationResult:
    """Classify an image or screenshot with Gemini Flash vision."""
    image_part = Part.from_data(image_bytes, mime_type="image/jpeg")
    text_prompt = build_classification_prompt(
        source_type="image",
        content_text=caption or "[see attached image]",
        category_list=existing_categories,
        few_shot_examples=few_shot_examples,
    )
    return _generate_and_parse([image_part, text_prompt], "image classification")


def classify_url(
    og_title: str,
    og_description: str,
    url: str,
    existing_categories: list[str],
    few_shot_examples: list[dict[str, Any]] | None = None,
    source_type: str = "url",
    content_text: str | None = None,
    site_name: str | None = None,
    resolved_url: str | None = None,
    is_video: bool = False,
    video_url: str | None = None,
) -> ClassificationResult:
    """Classify URL metadata with Gemini Flash."""
    parsed_url = urlparse(url if "://" in url else f"https://{url}")
    domain = parsed_url.netloc or url
    prompt_source_type = "video_url" if is_video else source_type
    content_parts = [
        f"Title: {og_title}" if og_title else "",
        f"Description: {og_description}" if og_description else "",
        f"Source domain: {domain}",
        f"Resolved URL: {resolved_url}" if resolved_url and resolved_url != url else "",
        f"Source site: {site_name}" if site_name else "",
    ]
    if is_video:
        content_parts.append(
            "Detected video URL or embedded video. Use the actual video/article text below when available; "
            "do not categorize this only as a social media or video-platform link."
        )
    if video_url:
        content_parts.append(f"Embedded video URL: {video_url}")
    if content_text:
        content_parts.append(f"Extracted page content:\n{content_text[:12000]}")

    prompt_content = "\n".join(part for part in content_parts if part) or url
    prompt = build_classification_prompt(
        source_type=prompt_source_type,
        content_text=prompt_content,
        category_list=existing_categories,
        few_shot_examples=few_shot_examples,
    )
    return _generate_and_parse(prompt, "URL classification")


def classify_from_transcript(
    transcript: str,
    existing_categories: list[str],
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> ClassificationResult:
    """Classify a video transcript with Gemini Flash."""
    prompt = build_classification_prompt(
        source_type="video_file",
        content_text=transcript[:3000],
        category_list=existing_categories,
        few_shot_examples=few_shot_examples,
    )
    return _generate_and_parse(prompt, "transcript classification")


def _prompt_examples_for(db: Any | None, source_type: str) -> list[dict[str, str]]:
    """Load learned prompt examples when a database session is available."""
    if db is None:
        return []

    from storage.db import get_prompt_examples

    return get_prompt_examples(db, source_type)


def classify_artifact(
    payload: MessagePayload,
    content_data: dict[str, Any],
    existing_categories: list[str],
    db: Any | None = None,
) -> ClassificationResult:
    """Route normalized artifact content to the appropriate classifier."""
    input_type = payload["input_type"]
    few_shot_examples = _prompt_examples_for(db, input_type)

    if input_type == "text":
        result = classify_text(
            str(content_data.get("text") or payload.get("text") or ""),
            existing_categories,
            few_shot_examples=few_shot_examples,
        )
    elif input_type == "image":
        image_bytes = content_data.get("image_bytes")
        if not isinstance(image_bytes, bytes):
            raise ClassificationError("Image classification requires image_bytes.")
        result = classify_image(
            image_bytes=image_bytes,
            caption=payload.get("caption"),
            existing_categories=existing_categories,
            few_shot_examples=few_shot_examples,
        )
    elif input_type in {"instagram_url", "linkedin_url", "url"}:
        is_video_value = str(content_data.get("is_video") or "").lower() == "true"
        result = classify_url(
            og_title=str(content_data.get("og_title") or content_data.get("title") or payload.get("url") or ""),
            og_description=str(content_data.get("og_description") or content_data.get("description") or ""),
            url=str(payload.get("url") or ""),
            existing_categories=existing_categories,
            few_shot_examples=few_shot_examples,
            source_type=input_type,
            content_text=(
                str(content_data.get("content_text"))
                if content_data.get("content_text") is not None
                else None
            ),
            site_name=str(content_data.get("site_name")) if content_data.get("site_name") else None,
            resolved_url=str(content_data.get("resolved_url")) if content_data.get("resolved_url") else None,
            is_video=is_video_value,
            video_url=str(content_data.get("video_url")) if content_data.get("video_url") else None,
        )
    elif input_type == "video_file":
        transcript = content_data.get("transcript")
        result = classify_from_transcript(
            transcript if isinstance(transcript, str) else "",
            existing_categories,
            few_shot_examples=few_shot_examples,
        )
    else:
        raise ClassificationError(f"Unsupported artifact input_type for classification: {input_type}")

    logger.debug(
        "gemini_classification_result",
        input_type=input_type,
        result=result,
        duration_ms=0,
    )
    return result
