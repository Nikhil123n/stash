"""Gemini-powered taxonomy evolution helpers for Stash categories."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import vertexai
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from vertexai.generative_models import GenerativeModel

from ai.consistency import (
    LLM_RETRY_ATTEMPTS,
    TAXONOMY_CLUSTERING_PROMPT_VERSION,
    TAXONOMY_EVOLUTION_GENERATION_CONFIG,
    TAXONOMY_PARSER_VERSION,
    TAXONOMY_RESPONSE_SCHEMA,
    TAXONOMY_RESPONSE_SCHEMA_VERSION,
    generate_content_with_policy,
    prompt_metadata,
)
from config import get_env
from logging_config import structlog
from storage.db import Artifact, Category, Subcategory, record_model_change_if_needed

logger = structlog.get_logger(__name__)

_MODEL_NAME = get_env("GEMINI_MODEL", required=True)
_TIER2_MIN_ITEMS = 10
_TIER3_MIN_ITEMS = 50
_SKIP_WINDOW = timedelta(days=30)


def build_clustering_prompt(category_name: str, items: list[dict[str, Any]]) -> str:
    """Build the Section 7.4 Gemini clustering prompt for a category."""
    item_list = "\n".join(
        f"- {item['id']}: {item.get('title') or 'Untitled'} "
        f"(tags: {', '.join(str(tag) for tag in item.get('tags', []))})"
        for item in items
    )

    return f"""You have a collection of saved content items in the '{category_name}' category.
Here are their titles and tags:

{item_list}

Identify 2-5 meaningful sub-groups within this collection.
Return JSON:
{{
  "subcategories": [
    {{ "name": "...", "item_ids": ["uuid1", "uuid2", ...] }},
    ...
  ]
}}"""


def _strip_json_fences(raw: str) -> str:
    """Remove common Markdown JSON fences from Gemini responses."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def parse_clustering_response(raw: str) -> list[dict[str, Any]]:
    """Parse and validate Gemini clustering JSON."""
    cleaned = _strip_json_fences(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Gemini clustering JSON response: {raw}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Gemini clustering response must be a JSON object: {raw}")

    subcategories = parsed.get("subcategories")
    if not isinstance(subcategories, list):
        raise ValueError(f"Gemini clustering response missing subcategories list: {raw}")

    proposals: list[dict[str, Any]] = []
    for item in subcategories:
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        item_ids = item.get("item_ids")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(item_ids, list):
            continue

        valid_item_ids = [str(item_id) for item_id in item_ids if str(item_id).strip()]
        if len(valid_item_ids) < 2:
            continue

        proposals.append({"name": name.strip(), "item_ids": valid_item_ids})

    return proposals


def _initialize_vertexai() -> None:
    """Initialize Vertex AI with project and region from the environment."""
    project = get_env("GOOGLE_CLOUD_PROJECT", required=True)
    region = get_env("VERTEX_REGION", required=True)
    vertexai.init(project=project, location=region)


def _generate_clustering_response(prompt: str) -> list[dict[str, Any]]:
    """Run Gemini against a clustering prompt and parse its response."""
    _initialize_vertexai()
    model = GenerativeModel(_MODEL_NAME)
    prompt_info = prompt_metadata(prompt, TAXONOMY_CLUSTERING_PROMPT_VERSION)
    raw_response = ""
    last_parse_error: ValueError | None = None

    for attempt in range(1, LLM_RETRY_ATTEMPTS + 1):
        response, call_policy = generate_content_with_policy(
            model,
            prompt,
            generation_config=TAXONOMY_EVOLUTION_GENERATION_CONFIG,
            response_schema=TAXONOMY_RESPONSE_SCHEMA,
            response_schema_version=TAXONOMY_RESPONSE_SCHEMA_VERSION,
        )
        raw_response = getattr(response, "text", "")
        try:
            proposals = parse_clustering_response(raw_response)
        except ValueError as exc:
            last_parse_error = exc
            logger.warning(
                "gemini_taxonomy_invalid_response",
                attempt=attempt,
                max_attempts=LLM_RETRY_ATTEMPTS,
                raw_response=raw_response,
                duration_ms=0,
            )
            continue

        logger.debug(
            "gemini_taxonomy_audit",
            model_name=_MODEL_NAME,
            prompt_version=prompt_info.version,
            prompt_hash=prompt_info.prompt_hash,
            generation_config=call_policy.generation_config,
            parser_version=TAXONOMY_PARSER_VERSION,
            retry_count=attempt - 1,
            duration_ms=0,
        )
        return proposals

    raise ValueError(f"Invalid Gemini taxonomy response: {raw_response}") from last_parse_error


def _artifact_items(artifacts: list[Artifact]) -> list[dict[str, Any]]:
    """Convert artifact rows into the minimal item list Gemini needs."""
    return [
        {
            "id": str(artifact.id),
            "title": artifact.ai_title or "Untitled",
            "tags": artifact.ai_tags or [],
        }
        for artifact in artifacts
    ]


def _was_recently_skipped(skipped_at: datetime | None) -> bool:
    """Return whether a category evolution proposal was skipped in the last 30 days."""
    if skipped_at is None:
        return False

    if skipped_at.tzinfo is None:
        skipped_at = skipped_at.replace(tzinfo=timezone.utc)

    return skipped_at >= datetime.now(timezone.utc) - _SKIP_WINDOW


def run_tier2_evolution(db: Session, category_id: UUID) -> list[dict[str, Any]] | None:
    """Propose Tier 2 subcategories for a category once it has enough uncategorized items."""
    category = db.get(Category, category_id)
    if category is None:
        logger.warning("category_evolution_category_not_found", category_id=str(category_id), duration_ms=0)
        return None

    if _was_recently_skipped(category.evolution_skipped_at):
        logger.info("category_evolution_recently_skipped", category_id=str(category_id), duration_ms=0)
        return None

    artifacts = list(
        db.execute(
            select(Artifact)
            .where(Artifact.category_id == category_id)
            .where(Artifact.subcategory_id.is_(None))
            .order_by(Artifact.created_at.desc())
        )
        .scalars()
        .all()
    )
    if len(artifacts) < _TIER2_MIN_ITEMS:
        return None

    record_model_change_if_needed(db, _MODEL_NAME, commit=True)
    prompt = build_clustering_prompt(category.name, _artifact_items(artifacts))
    try:
        proposals = _generate_clustering_response(prompt)
    except Exception:
        logger.exception("tier2_category_evolution_failed", category_id=str(category_id), duration_ms=0)
        return None

    return proposals or None


def run_tier3_evolution(db: Session, subcategory_id: UUID) -> None:
    """Automatically create Tier 3 micro-clusters for large subcategories."""
    subcategory = db.get(Subcategory, subcategory_id)
    if subcategory is None:
        logger.warning("tier3_subcategory_not_found", subcategory_id=str(subcategory_id), duration_ms=0)
        return

    artifacts = list(
        db.execute(
            select(Artifact)
            .where(Artifact.subcategory_id == subcategory_id)
            .order_by(Artifact.created_at.desc())
        )
        .scalars()
        .all()
    )
    if len(artifacts) < _TIER3_MIN_ITEMS:
        return

    record_model_change_if_needed(db, _MODEL_NAME, commit=True)
    prompt = build_clustering_prompt(subcategory.name, _artifact_items(artifacts))
    try:
        proposals = _generate_clustering_response(prompt)
    except Exception:
        logger.exception("tier3_subcategory_evolution_failed", subcategory_id=str(subcategory_id), duration_ms=0)
        return

    for proposal in proposals:
        proposal["tier"] = 3

    apply_subcategories(db, proposals)


def _slugify(value: str) -> str:
    """Create a URL-safe subcategory slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = slug.strip("-")
    return slug or "subcategory"


def _uuid_values(item_ids: list[str]) -> list[UUID]:
    """Convert string item IDs into UUID values, skipping invalid IDs."""
    values: list[UUID] = []
    for item_id in item_ids:
        try:
            values.append(UUID(str(item_id)))
        except ValueError:
            logger.warning("invalid_subcategory_proposal_item_id", item_id=item_id, duration_ms=0)
    return values


def _get_or_create_subcategory(
    db: Session,
    category_id: UUID,
    name: str,
    tier: int,
) -> Subcategory:
    """Return an existing subcategory by name within a category or create it."""
    clean_name = name.strip()
    existing = db.execute(
        select(Subcategory).where(
            Subcategory.category_id == category_id,
            func.lower(Subcategory.name) == clean_name.lower(),
            Subcategory.tier == tier,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.confirmed = True
        existing.tier = tier
        return existing

    subcategory = Subcategory(
        category_id=category_id,
        name=clean_name,
        slug=_slugify(clean_name),
        item_count=0,
        tier=tier,
        confirmed=True,
    )
    db.add(subcategory)
    db.flush()
    return subcategory


def _refresh_subcategory_count(db: Session, subcategory_id: UUID) -> None:
    """Set a subcategory's item_count from the current artifact assignments."""
    db.execute(
        text(
            """
            UPDATE subcategories
            SET item_count = (
                SELECT count(*)
                FROM artifacts
                WHERE artifacts.subcategory_id = :subcategory_id
            )
            WHERE id = :subcategory_id
            """
        ),
        {"subcategory_id": subcategory_id},
    )


def apply_subcategories(db: Session, proposals: list[dict[str, Any]]) -> None:
    """Apply confirmed subcategory proposals to artifacts."""
    touched_subcategory_ids: set[UUID] = set()

    for proposal in proposals:
        name = str(proposal.get("name") or "").strip()
        item_ids_raw = proposal.get("item_ids")
        if not name or not isinstance(item_ids_raw, list):
            continue

        artifact_ids = _uuid_values([str(item_id) for item_id in item_ids_raw])
        if len(artifact_ids) < 2:
            continue

        artifacts = list(
            db.execute(select(Artifact).where(Artifact.id.in_(artifact_ids))).scalars().all()
        )
        if len(artifacts) < 2:
            continue

        category_id = artifacts[0].category_id
        if category_id is None:
            continue

        tier = int(proposal.get("tier") or 2)
        subcategory = _get_or_create_subcategory(db, category_id, name, tier)
        db.flush()

        previous_ids = {artifact.subcategory_id for artifact in artifacts if artifact.subcategory_id is not None}
        for artifact in artifacts:
            artifact.subcategory_id = subcategory.id

        touched_subcategory_ids.update(sub_id for sub_id in previous_ids if sub_id is not None)
        touched_subcategory_ids.add(subcategory.id)

    for subcategory_id in touched_subcategory_ids:
        _refresh_subcategory_count(db, subcategory_id)

    db.commit()
