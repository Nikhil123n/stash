"""Tests for Telegram message payload extraction and bot reply helpers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import bot


def make_file(
    file_id: str = "file-id",
    file_unique_id: str = "unique-id",
    mime_type: str | None = None,
    file_size: int | None = 1024,
) -> SimpleNamespace:
    """Create a Telegram file-like object for parser tests."""
    return SimpleNamespace(
        file_id=file_id,
        file_unique_id=file_unique_id,
        mime_type=mime_type,
        file_size=file_size,
    )


def make_message(**overrides: object) -> SimpleNamespace:
    """Create a Telegram Message-like object for parser tests."""
    defaults: dict[str, object] = {
        "animation": None,
        "audio": None,
        "caption": None,
        "chat_id": 123,
        "contact": None,
        "document": None,
        "location": None,
        "message_id": 456,
        "photo": None,
        "sticker": None,
        "text": None,
        "venue": None,
        "video": None,
        "video_note": None,
        "voice": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_extract_instagram_url_payload() -> None:
    """Instagram URLs are classified as instagram_url."""
    message = make_message(text="Save this https://instagram.com/reel/abc123")

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "instagram_url"
    assert payload["text"] == message.text
    assert payload["url"] == "https://instagram.com/reel/abc123"
    assert payload["chat_id"] == 123
    assert payload["telegram_msg_id"] == 456


def test_extract_linkedin_url_payload() -> None:
    """LinkedIn URLs are classified as linkedin_url."""
    message = make_message(text="Useful post: https://www.linkedin.com/posts/example")

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "linkedin_url"
    assert payload["url"] == "https://www.linkedin.com/posts/example"


def test_extract_generic_url_payload() -> None:
    """Generic URLs are classified as url and trailing punctuation is ignored."""
    message = make_message(text="Read later: https://example.com/article.")

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "url"
    assert payload["url"] == "https://example.com/article"


def test_extract_video_file_payload_from_video() -> None:
    """Telegram video messages are classified as video_file."""
    video = make_file(mime_type="video/mp4", file_size=2048)
    message = make_message(video=video, caption="A short clip")

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "video_file"
    assert payload["file_id"] == "file-id"
    assert payload["file_unique_id"] == "unique-id"
    assert payload["mime_type"] == "video/mp4"
    assert payload["file_size"] == 2048
    assert payload["caption"] == "A short clip"


def test_extract_video_file_payload_from_video_document() -> None:
    """Telegram documents with a video MIME type are classified as video_file."""
    document = make_file(mime_type="video/quicktime")
    message = make_message(document=document)

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "video_file"
    assert payload["mime_type"] == "video/quicktime"


def test_extract_image_payload() -> None:
    """Telegram photo messages are classified as image using the largest photo."""
    small_photo = make_file(file_id="small", file_unique_id="small-unique", file_size=100)
    large_photo = make_file(file_id="large", file_unique_id="large-unique", file_size=300)
    message = make_message(photo=[small_photo, large_photo], caption="Screenshot")

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "image"
    assert payload["file_id"] == "large"
    assert payload["file_unique_id"] == "large-unique"
    assert payload["file_size"] == 300
    assert payload["caption"] == "Screenshot"


def test_extract_text_payload() -> None:
    """Plain text with no URL is classified as text."""
    message = make_message(text="This is worth saving as a note.")

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "text"
    assert payload["text"] == "This is worth saving as a note."
    assert payload["url"] is None
    assert payload["file_id"] is None


def test_extract_unsupported_payload() -> None:
    """Unsupported media messages are classified as unsupported."""
    message = make_message(voice=make_file(mime_type="audio/ogg"))

    payload = bot.extract_message_payload(message)

    assert payload["input_type"] == "unsupported"
    assert payload["file_id"] is None


def test_send_helpers_use_bot_send_message(monkeypatch) -> None:
    """Bot reply helpers send expected Telegram messages through the application bot."""
    send_message = AsyncMock()
    fake_application = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
    monkeypatch.setattr(bot, "application", fake_application)

    asyncio.run(bot.send_confirmation(123, "Coding", "FastAPI webhook"))
    asyncio.run(bot.send_processing_ack(123))
    asyncio.run(bot.send_error(123, "Please try again."))
    asyncio.run(bot.send_unsupported(123))

    assert send_message.await_count == 4
    send_message.assert_any_await(
        chat_id=123,
        text="Saved under Coding\nFastAPI webhook",
        parse_mode="Markdown",
    )
    send_message.assert_any_await(
        chat_id=123,
        text="Got it, processing...",
        parse_mode="Markdown",
    )
    send_message.assert_any_await(
        chat_id=123,
        text="Sorry, I couldn't save that. Please try again.",
        parse_mode="Markdown",
    )
    send_message.assert_any_await(
        chat_id=123,
        text="I can only save URLs, images, videos, and text. Stickers/voice/audio not supported yet.",
        parse_mode="Markdown",
    )


def test_dashboard_command_sends_magic_link(monkeypatch) -> None:
    """The /dashboard command is handled without becoming a saved artifact."""
    send_message = AsyncMock()
    fake_application = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
    monkeypatch.setattr(bot, "application", fake_application)
    monkeypatch.setattr(bot, "_build_dashboard_link", lambda _chat_id: "https://dashboard.test/auth?token=abc")

    handled = asyncio.run(bot.handle_dashboard_command(make_message(text="/dashboard")))

    assert handled is True
    assert send_message.await_count == 1
    assert send_message.await_args.kwargs["chat_id"] == 123
    assert "private link" in send_message.await_args.kwargs["text"]


def test_non_dashboard_command_is_not_handled() -> None:
    """Regular messages still flow into artifact extraction."""
    handled = asyncio.run(bot.handle_dashboard_command(make_message(text="save this note")))

    assert handled is False
