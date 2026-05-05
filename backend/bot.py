"""Telegram bot helpers for webhook parsing and user-facing replies."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, TypedDict
from uuid import UUID

from config import get_env
from logging_config import structlog

if TYPE_CHECKING:
    from telegram import CallbackQuery, Message

logger = structlog.get_logger(__name__)

InputType = Literal[
    "instagram_url",
    "linkedin_url",
    "url",
    "video_file",
    "image",
    "text",
    "unsupported",
]


class MessagePayload(TypedDict):
    """Normalized Telegram message payload for asynchronous artifact processing."""

    chat_id: int
    telegram_msg_id: int
    input_type: InputType
    text: str | None
    file_id: str | None
    file_unique_id: str | None
    mime_type: str | None
    file_size: int | None
    url: str | None
    caption: str | None


application: Any | None = None
_redis_client: Any | None = None
_URL_PATTERN = re.compile(r"(https?://[^\s<>\]]+|www\.[^\s<>\]]+)", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,!?;:)]}'\""
_UNSUPPORTED_ATTACHMENT_FIELDS = (
    "animation",
    "audio",
    "contact",
    "location",
    "sticker",
    "venue",
    "video_note",
    "voice",
)


def _get_application() -> Any:
    """Return the lazily initialized python-telegram-bot application."""
    global application

    if application is not None:
        return application

    for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(proxy_var, None)

    token = get_env("TELEGRAM_BOT_TOKEN", required=True)

    from telegram.ext import Application

    application = Application.builder().token(token).build()
    return application


def get_bot() -> Any:
    """Return the Telegram bot attached to the configured application."""
    return _get_application().bot


def get_redis_client() -> Any:
    """Return a lazily initialized Redis client for bot conversation state."""
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    from redis import Redis

    redis_url = get_env("REDIS_URL", required=True)
    _redis_client = Redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def _extract_chat_id(message: Message) -> int:
    """Extract a chat ID from a Telegram Message-like object."""
    chat_id = getattr(message, "chat_id", None)
    if chat_id is None:
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
    if chat_id is None:
        raise ValueError("Telegram message is missing chat_id.")
    return int(chat_id)


def _extract_message_id(message: Message) -> int:
    """Extract a Telegram message ID from a Message-like object."""
    message_id = getattr(message, "message_id", None)
    if message_id is None:
        raise ValueError("Telegram message is missing message_id.")
    return int(message_id)


def _extract_first_url(value: str | None) -> str | None:
    """Return the first URL found in text, stripped of common trailing punctuation."""
    if not value:
        return None

    match = _URL_PATTERN.search(value)
    if not match:
        return None

    return match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)


def _classify_url(url: str) -> InputType:
    """Classify a URL by source domain."""
    normalized = url.lower()
    if "instagram.com" in normalized:
        return "instagram_url"
    if "linkedin.com" in normalized:
        return "linkedin_url"
    return "url"


def _select_largest_photo(photo: Any) -> Any:
    """Select the largest Telegram PhotoSize from a message photo collection."""
    if isinstance(photo, Sequence) and not isinstance(photo, (str, bytes)):
        return photo[-1] if photo else None
    return photo


def _has_unsupported_attachment(message: Message) -> bool:
    """Return whether a message contains a media type Stash does not support yet."""
    if any(getattr(message, field, None) is not None for field in _UNSUPPORTED_ATTACHMENT_FIELDS):
        return True

    document = getattr(message, "document", None)
    if document is None:
        return False

    mime_type = getattr(document, "mime_type", None) or ""
    return not mime_type.startswith("video/")


def _base_payload(message: Message, input_type: InputType) -> MessagePayload:
    """Build the common payload fields shared by all Telegram message types."""
    caption = getattr(message, "caption", None)
    return {
        "chat_id": _extract_chat_id(message),
        "telegram_msg_id": _extract_message_id(message),
        "input_type": input_type,
        "text": None,
        "file_id": None,
        "file_unique_id": None,
        "mime_type": None,
        "file_size": None,
        "url": _extract_first_url(caption),
        "caption": caption,
    }


def _attach_file_metadata(payload: MessagePayload, file_object: Any) -> MessagePayload:
    """Copy Telegram file metadata into a normalized payload."""
    payload["file_id"] = getattr(file_object, "file_id", None)
    payload["file_unique_id"] = getattr(file_object, "file_unique_id", None)
    payload["mime_type"] = getattr(file_object, "mime_type", None)
    payload["file_size"] = getattr(file_object, "file_size", None)
    return payload


def extract_message_payload(message: Message) -> MessagePayload:
    """Normalize a Telegram message into the payload shape used by Celery tasks."""
    video = getattr(message, "video", None)
    if video is not None:
        payload = _base_payload(message, "video_file")
        return _attach_file_metadata(payload, video)

    document = getattr(message, "document", None)
    document_mime_type = getattr(document, "mime_type", None) or ""
    if document is not None and document_mime_type.startswith("video/"):
        payload = _base_payload(message, "video_file")
        return _attach_file_metadata(payload, document)

    photo = _select_largest_photo(getattr(message, "photo", None))
    if photo is not None:
        payload = _base_payload(message, "image")
        return _attach_file_metadata(payload, photo)

    if _has_unsupported_attachment(message):
        return _base_payload(message, "unsupported")

    text = getattr(message, "text", None)
    caption = getattr(message, "caption", None)
    text_or_caption = text or caption
    if text_or_caption:
        url = _extract_first_url(text_or_caption)
        input_type = _classify_url(url) if url else "text"
        payload = _base_payload(message, input_type)
        payload["text"] = text
        payload["url"] = url
        return payload

    return _base_payload(message, "unsupported")


async def send_confirmation(chat_id: int, category_name: str, title: str) -> None:
    """Send a successful save confirmation to the user."""
    await get_bot().send_message(
        chat_id=chat_id,
        text=f"Saved under {category_name}\n{title}",
        parse_mode="Markdown",
    )


async def send_processing_ack(chat_id: int) -> None:
    """Tell the user their artifact has been accepted for processing."""
    await get_bot().send_message(
        chat_id=chat_id,
        text="Got it, processing...",
        parse_mode="Markdown",
    )


async def send_error(chat_id: int, error_msg: str) -> None:
    """Send a user-friendly processing error message."""
    await get_bot().send_message(
        chat_id=chat_id,
        text=f"Sorry, I couldn't save that. {error_msg}",
        parse_mode="Markdown",
    )


async def send_unsupported(chat_id: int) -> None:
    """Tell the user that the submitted Telegram message type is unsupported."""
    await get_bot().send_message(
        chat_id=chat_id,
        text="I can only save URLs, images, videos, and text. Stickers/voice/audio not supported yet.",
        parse_mode="Markdown",
    )


def _proposal_key(chat_id: int, category_id: str) -> str:
    """Return the Redis key for a pending category proposal."""
    return f"pending_proposal:{chat_id}:{category_id}"


def _proposal_state_key(chat_id: int) -> str:
    """Return the Redis key for the user's current proposal edit state."""
    return f"proposal_state:{chat_id}"


def _load_pending_proposal(chat_id: int, category_id: str) -> list[dict[str, Any]] | None:
    """Load pending subcategory proposals for a chat/category pair."""
    raw = get_redis_client().get(_proposal_key(chat_id, category_id))
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        logger.exception("pending_subcategory_proposal_decode_failed", category_id=category_id, duration_ms=0)
        return None

    if not isinstance(parsed, list):
        return None
    return [proposal for proposal in parsed if isinstance(proposal, dict)]


async def send_subcategory_proposal(
    chat_id: int,
    category_name: str,
    proposals: list[dict[str, Any]],
    category_id: str | None = None,
) -> None:
    """Send an inline Telegram proposal for AI-generated subcategories."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    lines = [
        f"I noticed enough items in {category_name}.",
        "Here are suggested sub-categories:",
        "",
    ]
    for index, proposal in enumerate(proposals, start=1):
        name = str(proposal.get("name") or "Unnamed")
        item_ids = proposal.get("item_ids")
        item_count = len(item_ids) if isinstance(item_ids, list) else 0
        lines.append(f"{index}. {name} ({item_count} items)")

    callback_category_id = category_id or "unknown"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes, apply", callback_data=f"subcategory:yes:{callback_category_id}"),
                InlineKeyboardButton("Skip for 30d", callback_data=f"subcategory:skip:{callback_category_id}"),
            ],
            [InlineKeyboardButton("Edit names", callback_data=f"subcategory:edit:{callback_category_id}")],
        ]
    )

    await get_bot().send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=keyboard,
    )


def _chat_id_from_callback(callback_query: CallbackQuery) -> int | None:
    """Extract the chat ID associated with a Telegram callback query."""
    message = getattr(callback_query, "message", None)
    chat_id = getattr(message, "chat_id", None)
    if chat_id is None:
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
    if chat_id is None:
        user = getattr(callback_query, "from_user", None)
        chat_id = getattr(user, "id", None)
    return int(chat_id) if chat_id is not None else None


async def handle_subcategory_callback(callback_query: CallbackQuery) -> bool:
    """Handle inline keyboard callbacks for pending subcategory proposals."""
    answer = getattr(callback_query, "answer", None)
    if callable(answer):
        await answer()

    data = getattr(callback_query, "data", "") or ""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "subcategory":
        return False

    action = parts[1]
    category_id = parts[2]
    chat_id = _chat_id_from_callback(callback_query)
    if chat_id is None:
        logger.warning("subcategory_callback_missing_chat_id", callback_data=data, duration_ms=0)
        return True

    proposals = _load_pending_proposal(chat_id, category_id)
    if not proposals:
        await get_bot().send_message(chat_id=chat_id, text="That proposal expired. I will suggest it again later.")
        return True

    redis_client = get_redis_client()
    if action == "edit":
        current_names = "\n".join(str(proposal.get("name") or "") for proposal in proposals)
        redis_client.setex(_proposal_state_key(chat_id), 48 * 60 * 60, f"awaiting_edit:{category_id}")
        await get_bot().send_message(
            chat_id=chat_id,
            text=f"Reply with new names, one per line. Current suggestions:\n{current_names}",
        )
        return True

    from storage.db import Category, SessionLocal

    db = SessionLocal()
    try:
        category_uuid = UUID(category_id)
        category = db.get(Category, category_uuid)
        category_name = category.name if category is not None else "this category"

        if action == "yes":
            from ai.evolve import apply_subcategories

            apply_subcategories(db, proposals)
            redis_client.delete(_proposal_key(chat_id, category_id))
            redis_client.delete(_proposal_state_key(chat_id))
            await get_bot().send_message(
                chat_id=chat_id,
                text=f"Sub-categories applied to {category_name}. Check the dashboard.",
            )
            return True

        if action == "skip":
            if category is not None:
                category.evolution_skipped_at = datetime.now(timezone.utc)
                db.commit()
            redis_client.delete(_proposal_key(chat_id, category_id))
            redis_client.delete(_proposal_state_key(chat_id))
            await get_bot().send_message(
                chat_id=chat_id,
                text="Got it. I will not re-suggest sub-categories for 30 days.",
            )
            return True

        logger.warning(
            "unknown_subcategory_callback_action",
            action=action,
            category_id=category_id,
            duration_ms=0,
        )
        return True
    except ValueError:
        logger.exception("invalid_subcategory_callback_category_id", category_id=category_id, duration_ms=0)
        await get_bot().send_message(chat_id=chat_id, text="I could not apply that proposal.")
        return True
    except Exception:
        logger.exception(
            "subcategory_callback_handling_failed",
            action=action,
            category_id=category_id,
            duration_ms=0,
        )
        db.rollback()
        await get_bot().send_message(chat_id=chat_id, text="I could not apply that proposal.")
        return True
    finally:
        db.close()


async def handle_awaiting_edit_message(message: Message) -> bool:
    """Apply edited subcategory names when the user replies to an edit prompt."""
    chat_id = _extract_chat_id(message)
    redis_client = get_redis_client()
    state = redis_client.get(_proposal_state_key(chat_id))
    if isinstance(state, bytes):
        state = state.decode("utf-8")
    if not isinstance(state, str) or not state.startswith("awaiting_edit:"):
        return False

    category_id = state.removeprefix("awaiting_edit:")
    proposals = _load_pending_proposal(chat_id, category_id)
    if not proposals:
        redis_client.delete(_proposal_state_key(chat_id))
        await get_bot().send_message(chat_id=chat_id, text="That proposal expired. I will suggest it again later.")
        return True

    text = getattr(message, "text", None) or ""
    names = [line.strip() for line in text.splitlines() if line.strip()]
    if not names:
        await get_bot().send_message(chat_id=chat_id, text="Reply with at least one sub-category name.")
        return True

    for index, name in enumerate(names):
        if index >= len(proposals):
            break
        proposals[index]["name"] = name

    from ai.evolve import apply_subcategories
    from storage.db import Category, SessionLocal

    db = SessionLocal()
    try:
        category_uuid = UUID(category_id)
        category = db.get(Category, category_uuid)
        category_name = category.name if category is not None else "this category"
        apply_subcategories(db, proposals)
        redis_client.delete(_proposal_key(chat_id, category_id))
        redis_client.delete(_proposal_state_key(chat_id))
        await get_bot().send_message(
            chat_id=chat_id,
            text=f"Sub-categories applied to {category_name}. Check the dashboard.",
        )
    except Exception:
        logger.exception("edited_subcategory_proposal_failed", category_id=category_id, duration_ms=0)
        db.rollback()
        await get_bot().send_message(chat_id=chat_id, text="I could not apply those names.")
    finally:
        db.close()

    return True


async def register_webhook(url: str) -> None:
    """Register the Telegram webhook URL for this backend."""
    if not url:
        logger.warning("telegram_webhook_registration_skipped_empty_url", duration_ms=0)
        return

    await get_bot().set_webhook(url=url)
