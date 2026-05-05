"""Shared LLM consistency policy helpers for Stash AI calls."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from logging_config import structlog

try:  # pragma: no cover - exercised through fake modules in unit tests.
    from vertexai.generative_models import GenerationConfig
except (ImportError, AttributeError):  # Older SDKs may not expose GenerationConfig.
    GenerationConfig = None  # type: ignore[assignment]


logger = structlog.get_logger(__name__)

LLM_RETRY_ATTEMPTS = 3

CLASSIFICATION_PROMPT_VERSION = "classification.v1"
VIDEO_CLASSIFICATION_PROMPT_VERSION = "video-classification.v1"
TAXONOMY_CLUSTERING_PROMPT_VERSION = "taxonomy-clustering.v1"

CLASSIFICATION_PARSER_VERSION = "classification-parser.v1"
TAXONOMY_PARSER_VERSION = "taxonomy-parser.v1"

CLASSIFICATION_RESPONSE_SCHEMA_VERSION = "classification-response.v1"
TAXONOMY_RESPONSE_SCHEMA_VERSION = "taxonomy-response.v1"

_DETERMINISTIC_GENERATION_CONFIG: dict[str, Any] = {
    "temperature": 0,
    "top_p": 1,
    "candidate_count": 1,
    "max_output_tokens": 1024,
}

CLASSIFICATION_GENERATION_CONFIG: dict[str, Any] = dict(_DETERMINISTIC_GENERATION_CONFIG)
IMAGE_ANALYSIS_GENERATION_CONFIG: dict[str, Any] = dict(_DETERMINISTIC_GENERATION_CONFIG)
VIDEO_ANALYSIS_GENERATION_CONFIG: dict[str, Any] = dict(_DETERMINISTIC_GENERATION_CONFIG)
URL_METADATA_EXTRACTION_GENERATION_CONFIG: dict[str, Any] = dict(_DETERMINISTIC_GENERATION_CONFIG)
TAXONOMY_EVOLUTION_GENERATION_CONFIG: dict[str, Any] = dict(_DETERMINISTIC_GENERATION_CONFIG)

CLASSIFICATION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string"},
        "is_new_category": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "content_details": {"type": "string"},
    },
    "required": [
        "title",
        "summary",
        "tags",
        "category",
        "is_new_category",
        "confidence",
    ],
}

TAXONOMY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subcategories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "item_ids"],
            },
        }
    },
    "required": ["subcategories"],
}


@dataclass(frozen=True)
class PromptMetadata:
    """Version and content hash for the prompt string sent to Gemini."""

    version: str
    prompt_hash: str


@dataclass(frozen=True)
class GeminiCallPolicy:
    """Resolved generation policy metadata for one Gemini call."""

    generation_config: dict[str, Any]
    schema_enforced: bool


def prompt_metadata(prompt: str, version: str) -> PromptMetadata:
    """Return versioned SHA256 metadata for a prompt string."""
    return PromptMetadata(
        version=version,
        prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


def _generation_config_variants(
    base_config: dict[str, Any],
    response_schema: dict[str, Any] | None,
) -> list[tuple[dict[str, Any], bool]]:
    """Return config attempts from strict schema enforcement to deterministic fallback."""
    variants: list[tuple[dict[str, Any], bool]] = []
    if response_schema is not None:
        variants.append(
            (
                {
                    **base_config,
                    "response_mime_type": "application/json",
                    "response_schema": response_schema,
                },
                True,
            )
        )
    variants.append(({**base_config, "response_mime_type": "application/json"}, False))
    variants.append((dict(base_config), False))
    return variants


def _to_vertex_generation_config(config: dict[str, Any]) -> Any:
    """Create a Vertex GenerationConfig when available, otherwise pass the dict through."""
    if GenerationConfig is None:
        return config
    return GenerationConfig(**config)


def _audit_generation_config(
    config: dict[str, Any],
    *,
    schema_enforced: bool,
    response_schema_version: str | None,
) -> dict[str, Any]:
    """Return a compact, serializable config snapshot for audit storage."""
    snapshot = {key: value for key, value in config.items() if key != "response_schema"}
    if schema_enforced and response_schema_version:
        snapshot["response_schema_version"] = response_schema_version
    snapshot["response_schema_enforced"] = schema_enforced
    return snapshot


def generate_content_with_policy(
    model: Any,
    prompt_or_parts: str | list[Any],
    *,
    generation_config: dict[str, Any],
    response_schema: dict[str, Any] | None,
    response_schema_version: str | None,
) -> tuple[Any, GeminiCallPolicy]:
    """Call Gemini using the strictest supported deterministic JSON config."""
    errors: list[TypeError] = []
    variants = _generation_config_variants(generation_config, response_schema)
    for index, (config, schema_enforced) in enumerate(variants):
        try:
            vertex_config = _to_vertex_generation_config(config)
            response = model.generate_content(prompt_or_parts, generation_config=vertex_config)
            if index > 0:
                logger.warning(
                    "gemini_generation_config_fallback",
                    schema_enforced=schema_enforced,
                    duration_ms=0,
                )
            return response, GeminiCallPolicy(
                generation_config=_audit_generation_config(
                    config,
                    schema_enforced=schema_enforced,
                    response_schema_version=response_schema_version,
                ),
                schema_enforced=schema_enforced,
            )
        except TypeError as exc:
            errors.append(exc)

    if errors:
        raise errors[-1]
    raise RuntimeError("No Gemini generation config variants were available.")


def build_ai_audit(
    *,
    model_name: str,
    prompt: PromptMetadata,
    generation_config: dict[str, Any],
    input_modality: str,
    extraction_source: str,
    confidence: float,
    parser_version: str,
    retry_count: int,
) -> dict[str, Any]:
    """Build the JSONB audit payload stored beside AI-generated artifact metadata."""
    return {
        "model_name": model_name,
        "prompt_version": prompt.version,
        "prompt_hash": prompt.prompt_hash,
        "generation_config": generation_config,
        "input_modality": input_modality,
        "extraction_source": extraction_source,
        "confidence": confidence,
        "parser_version": parser_version,
        "retry_count": retry_count,
    }
