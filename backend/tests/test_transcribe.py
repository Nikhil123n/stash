"""Tests for Gemini video transcription helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ai import transcribe


class FakeBody:
    """Minimal streaming body returned by the fake R2 client."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        """Return the configured bytes."""
        return self.data


class FakeR2Client:
    """Minimal R2 client that records object metadata and reads."""

    def __init__(self, data: bytes = b"fake-video", content_type: str = "video/mp4") -> None:
        self.data = data
        self.content_type = content_type
        self.head_calls: list[tuple[str, str]] = []
        self.get_calls: list[tuple[str, str]] = []

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        """Return fake object metadata."""
        self.head_calls.append((Bucket, Key))
        return {"ContentLength": len(self.data), "ContentType": self.content_type}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        """Return fake object bytes."""
        self.get_calls.append((Bucket, Key))
        return {"Body": FakeBody(self.data), "ContentType": self.content_type}


class FakePart:
    """Capture the video payload sent to Gemini."""

    @staticmethod
    def from_data(data: bytes, mime_type: str) -> dict[str, Any]:
        """Return a serializable stand-in for Vertex Part."""
        return {"data": data, "mime_type": mime_type}


class FakeModel:
    """Minimal Gemini model stand-in."""

    def __init__(self, name: str) -> None:
        self.name = name


def _configure_transcribe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_client: FakeR2Client,
    generated_text: str,
) -> list[dict[str, Any]]:
    """Patch external services and return captured Gemini calls."""
    generate_calls: list[dict[str, Any]] = []

    def fake_generate_text_with_policy(
        model: FakeModel,
        prompt_or_parts: list[Any],
        *,
        generation_config: dict[str, Any],
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        generate_calls.append(
            {
                "model": model,
                "prompt_or_parts": prompt_or_parts,
                "generation_config": generation_config,
            }
        )
        return SimpleNamespace(text=generated_text), SimpleNamespace(generation_config=dict(generation_config))

    monkeypatch.setenv("R2_BUCKET_NAME", "stash-bucket")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "stash-project")
    monkeypatch.setenv("VERTEX_REGION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_VIDEO_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_INLINE_VIDEO_MAX_BYTES", "18000000")
    monkeypatch.setenv("GEMINI_TRANSCRIPTION_INLINE_MAX_BYTES", "18000000")
    monkeypatch.setattr(transcribe, "_initialize_vertexai", lambda: None)
    monkeypatch.setattr(transcribe, "get_r2_client", lambda: fake_client)
    monkeypatch.setattr(transcribe, "GenerativeModel", FakeModel)
    monkeypatch.setattr(transcribe, "Part", FakePart)
    monkeypatch.setattr(transcribe, "generate_text_with_policy", fake_generate_text_with_policy)

    return generate_calls


def test_successful_transcription(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty Gemini result is stripped and returned."""
    fake_client = FakeR2Client(data=b"fake-video", content_type="video/mp4")
    generate_calls = _configure_transcribe(
        monkeypatch,
        fake_client=fake_client,
        generated_text="  hello from gemini  ",
    )

    transcript = transcribe.transcribe_from_r2("artifacts/video.mp4")

    assert transcript == "hello from gemini"
    assert fake_client.head_calls == [("stash-bucket", "artifacts/video.mp4")]
    assert fake_client.get_calls == [("stash-bucket", "artifacts/video.mp4")]
    assert generate_calls[0]["model"].name == "gemini-2.5-pro"
    assert generate_calls[0]["prompt_or_parts"][0] == {"data": b"fake-video", "mime_type": "video/mp4"}
    assert generate_calls[0]["generation_config"]["temperature"] == 0
    assert generate_calls[0]["generation_config"]["candidate_count"] == 1


def test_empty_transcription_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty Gemini result returns an empty transcript string."""
    fake_client = FakeR2Client()
    _configure_transcribe(monkeypatch, fake_client=fake_client, generated_text="")

    transcript = transcribe.transcribe_from_r2("artifacts/silent.mp4")

    assert transcript == ""


def test_large_video_skips_gemini_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Videos larger than the inline Gemini cap are not downloaded or analyzed."""
    fake_client = FakeR2Client(data=b"x" * 11)
    generate_calls = _configure_transcribe(monkeypatch, fake_client=fake_client, generated_text="unused")
    monkeypatch.setenv("GEMINI_TRANSCRIPTION_INLINE_MAX_BYTES", "10")

    transcript = transcribe.transcribe_from_r2("artifacts/large.mp4")

    assert transcript == ""
    assert fake_client.head_calls == [("stash-bucket", "artifacts/large.mp4")]
    assert fake_client.get_calls == []
    assert generate_calls == []


def test_transcript_truncates_at_4000_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini transcript-style output is capped at 4000 characters."""
    fake_client = FakeR2Client()
    _configure_transcribe(monkeypatch, fake_client=fake_client, generated_text="x" * 5000)

    transcript = transcribe.transcribe_from_r2("artifacts/long.mp4")

    assert transcript == "x" * 4000
