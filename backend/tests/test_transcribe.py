"""Tests for Whisper transcription helpers."""

from __future__ import annotations

import importlib
import shutil
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class FakeR2Client:
    """Minimal R2 client that records downloads and writes a temp file."""

    def __init__(self) -> None:
        self.downloads: list[tuple[str, str, str]] = []

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        """Write a small fake video file to the requested temp path."""
        self.downloads.append((bucket, key, filename))
        Path(filename).write_bytes(b"fake-video")


class FakeWhisperModel:
    """Minimal Whisper model stand-in."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.transcribe_calls: list[tuple[str, bool]] = []

    def transcribe(self, tmp_path: str, fp16: bool = False) -> dict[str, str]:
        """Return the configured transcript text."""
        self.transcribe_calls.append((tmp_path, fp16))
        return {"text": self.text}


def import_transcribe_with_fakes(monkeypatch: pytest.MonkeyPatch, text: str) -> tuple[types.ModuleType, FakeWhisperModel]:
    """Import ai.transcribe with fake whisper and psutil modules installed."""
    model = FakeWhisperModel(text)
    fake_whisper = types.ModuleType("whisper")
    fake_whisper.load_model = Mock(return_value=model)

    fake_psutil = types.ModuleType("psutil")
    fake_psutil.virtual_memory = Mock(return_value=SimpleNamespace(available=2 * 1024 * 1024 * 1024))

    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    sys.modules.pop("ai.transcribe", None)

    return importlib.import_module("ai.transcribe"), model


@pytest.fixture
def writable_tmp_dir() -> Path:
    """Create and clean up a writable temp directory inside the workspace."""
    tmp_dir = BACKEND_ROOT / "tests" / "_tmp" / f"stash_transcribe_{uuid4()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_successful_transcription(monkeypatch: pytest.MonkeyPatch, writable_tmp_dir: Path) -> None:
    """A non-empty Whisper result is stripped and returned."""
    transcribe, model = import_transcribe_with_fakes(monkeypatch, "  hello from video  ")
    fake_client = FakeR2Client()
    monkeypatch.setenv("R2_BUCKET_NAME", "stash-bucket")
    monkeypatch.setenv("STASH_TMP_DIR", str(writable_tmp_dir))
    monkeypatch.setattr(transcribe, "get_r2_client", lambda: fake_client)

    transcript = transcribe.transcribe_from_r2("artifacts/video.mp4")

    assert transcript == "hello from video"
    assert fake_client.downloads[0][0] == "stash-bucket"
    assert fake_client.downloads[0][1] == "artifacts/video.mp4"
    assert model.transcribe_calls[0][1] is False
    assert not Path(model.transcribe_calls[0][0]).exists()


def test_empty_transcription_result(monkeypatch: pytest.MonkeyPatch, writable_tmp_dir: Path) -> None:
    """An empty Whisper result returns an empty transcript string."""
    transcribe, _model = import_transcribe_with_fakes(monkeypatch, "")
    fake_client = FakeR2Client()
    monkeypatch.setenv("R2_BUCKET_NAME", "stash-bucket")
    monkeypatch.setenv("STASH_TMP_DIR", str(writable_tmp_dir))
    monkeypatch.setattr(transcribe, "get_r2_client", lambda: fake_client)

    transcript = transcribe.transcribe_from_r2("artifacts/silent.mp4")

    assert transcript == ""


def test_transcript_truncates_at_4000_chars(monkeypatch: pytest.MonkeyPatch, writable_tmp_dir: Path) -> None:
    """Whisper transcripts are capped at 4000 characters."""
    transcribe, _model = import_transcribe_with_fakes(monkeypatch, "x" * 5000)
    fake_client = FakeR2Client()
    monkeypatch.setenv("R2_BUCKET_NAME", "stash-bucket")
    monkeypatch.setenv("STASH_TMP_DIR", str(writable_tmp_dir))
    monkeypatch.setattr(transcribe, "get_r2_client", lambda: fake_client)

    transcript = transcribe.transcribe_from_r2("artifacts/long.mp4")

    assert transcript == "x" * 4000
