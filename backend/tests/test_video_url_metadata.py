"""Tests for social video URL metadata and bounded download helpers."""

from __future__ import annotations

import sys
import shutil
import types
from pathlib import Path
from uuid import uuid4

import pytest
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from storage import r2


@pytest.fixture
def writable_tmp_dir() -> Path:
    """Create and clean up a writable temp directory inside the workspace."""
    tmp_dir = BACKEND_ROOT / "tests" / "_tmp" / f"stash_video_url_{uuid4()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


class FakeYtDlpLogger:
    """Minimal logger adapter for yt-dlp tests."""

    def debug(self, _message: str) -> None:
        return None

    def info(self, _message: str) -> None:
        return None

    def warning(self, _message: str) -> None:
        return None

    def error(self, _message: str) -> None:
        return None


def test_fetch_video_provider_metadata_downloads_video_bytes(monkeypatch, writable_tmp_dir: Path) -> None:
    """Public video metadata includes bounded downloaded bytes for Gemini analysis."""

    class FakeYoutubeDL:
        """Fake yt-dlp downloader that writes a small MP4 file only on download."""

        def __init__(self, options: dict[str, object]) -> None:
            self.options = options

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_info(self, _url: str, download: bool = False) -> dict[str, object]:
            info: dict[str, object] = {
                "title": "Useful design reel",
                "description": "A quick UI workflow.",
                "duration": 12,
                "ext": "mp4",
                "uploader": "Design Channel",
                "webpage_url": "https://example.com/reel/1",
            }
            if download:
                outtmpl = str(self.options["outtmpl"])
                video_path = Path(outtmpl.replace("%(ext)s", "mp4"))
                video_path.write_bytes(b"fake-video-bytes")
                info["requested_downloads"] = [{"filepath": str(video_path)}]
            return info

    fake_yt_dlp = types.ModuleType("yt_dlp")
    fake_yt_dlp.YoutubeDL = FakeYoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_yt_dlp)
    monkeypatch.setenv("VIDEO_URL_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("VIDEO_URL_MAX_BYTES", "18000000")
    monkeypatch.setenv("VIDEO_URL_MAX_DURATION_SECONDS", "180")
    monkeypatch.setenv("STASH_TMP_DIR", str(writable_tmp_dir))
    download_dir = writable_tmp_dir / "download"
    download_dir.mkdir()
    monkeypatch.setattr(r2.tempfile, "mkdtemp", lambda prefix, dir=None: str(download_dir))
    monkeypatch.setattr(r2.shutil, "rmtree", lambda *_args, **_kwargs: None)

    result = r2._fetch_video_provider_metadata(
        "https://example.com/reel/1",
        include_video_download=True,
    )

    assert result["title"] == "Useful design reel"
    assert result["site_name"] == "Design Channel"
    assert result["video_bytes"] == b"fake-video-bytes"
    assert result["video_mime_type"] == "video/mp4"


def test_video_provider_metadata_skips_oversized_duration(monkeypatch) -> None:
    """Very long videos skip download but keep captions for transcript classification."""

    class FakeYoutubeDL:
        def __init__(self, _options: dict[str, object]) -> None:
            pass

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_info(self, _url: str, download: bool = False) -> dict[str, object]:
            assert download is False
            return {
                "title": "Long talk",
                "duration": 3600,
                "ext": "mp4",
                "automatic_captions": {
                    "en": [{"ext": "json3", "url": "https://captions.example/json3"}],
                },
            }

    class FakeResponse:
        text = '{"events":[{"segs":[{"utf8":"This section explains database indexing."}]}]}'

        def raise_for_status(self) -> None:
            return None

    fake_yt_dlp = types.ModuleType("yt_dlp")
    fake_yt_dlp.YoutubeDL = FakeYoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_yt_dlp)
    monkeypatch.setattr(r2.httpx, "get", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setenv("VIDEO_URL_MAX_DURATION_SECONDS", "180")

    result = r2._fetch_video_provider_metadata(
        "https://example.com/video/long",
        include_video_download=True,
    )

    assert result["title"] == "Long talk"
    assert result["transcript"] == "This section explains database indexing."
    assert "Video transcript:" in result["content_text"]
    assert "video_bytes" not in result
