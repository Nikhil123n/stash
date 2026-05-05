"""Cloudflare R2 storage helpers and URL metadata fetching."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from config import get_bool_env, get_env, get_int_env
from logging_config import structlog
logger = structlog.get_logger(__name__)

_r2_client: Any | None = None
_MAX_EXTRACTED_TEXT_CHARS = 12000
_DEFAULT_VIDEO_DOWNLOAD_FORMAT = (
    "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/"
    "best[ext=mp4][height<=720]/best[height<=720]/best"
)
_VIDEO_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "tiktok.com",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "x.com",
    "twitter.com",
)


def _required_env(name: str) -> str:
    """Return a required environment variable or raise a clear configuration error."""
    return get_env(name, required=True)


def _get_r2_client() -> Any:
    """Return a lazy singleton Cloudflare R2 S3-compatible client."""
    global _r2_client

    if _r2_client is not None:
        return _r2_client

    import boto3

    account_id = _required_env("R2_ACCOUNT_ID")
    _r2_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=_required_env("R2_ACCESS_KEY"),
        aws_secret_access_key=_required_env("R2_SECRET_KEY"),
        region_name="auto",
    )
    return _r2_client


def get_r2_client() -> Any:
    """Return the lazy singleton Cloudflare R2 client."""
    return _get_r2_client()


def upload_to_r2(data: bytes, key: str, content_type: str) -> str:
    """Upload bytes to Cloudflare R2 and return the stored object key."""
    _get_r2_client().put_object(
        Bucket=_required_env("R2_BUCKET_NAME"),
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def get_r2_url(key: str) -> str:
    """Return the public R2 URL for an object key."""
    return f"https://pub-{_required_env('R2_BUCKET_ID')}.r2.dev/{key}"


async def _download_telegram_file_async(file_id: str) -> bytes:
    """Download a Telegram file using python-telegram-bot's async API."""
    from bot import get_bot

    telegram_file = await get_bot().get_file(file_id)
    data = await telegram_file.download_as_bytearray()
    return bytes(data)


def download_telegram_file(file_id: str) -> bytes:
    """Download a Telegram file from a synchronous Celery task."""
    return asyncio.run(_download_telegram_file_async(file_id))


def delete_from_r2(key: str) -> None:
    """Delete an object from Cloudflare R2."""
    _get_r2_client().delete_object(
        Bucket=_required_env("R2_BUCKET_NAME"),
        Key=key,
    )


def _meta_content(soup: object, *, property_name: str | None = None, name: str | None = None) -> str | None:
    """Return a meta tag content value from a BeautifulSoup document."""
    if property_name:
        tag = soup.find("meta", property=property_name)
    else:
        tag = soup.find("meta", attrs={"name": name})

    if tag is None:
        return None

    content = tag.get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None


def _clean_text(value: str) -> str:
    """Normalize whitespace in extracted page text."""
    return re.sub(r"\s+", " ", value).strip()


def _dedupe_lines(lines: list[str]) -> list[str]:
    """Keep extracted text lines in order while dropping repeats."""
    seen: set[str] = set()
    unique: list[str] = []
    for line in lines:
        clean = _clean_text(line)
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(clean)
    return unique


def _json_ld_text_values(value: Any) -> list[str]:
    """Extract useful text fields from JSON-LD objects recursively."""
    values: list[str] = []
    if isinstance(value, list):
        for item in value:
            values.extend(_json_ld_text_values(item))
        return values

    if not isinstance(value, dict):
        return values

    for key in ("headline", "name", "description", "articleBody", "text", "transcript"):
        text_value = value.get(key)
        if isinstance(text_value, str) and text_value.strip():
            values.append(text_value)

    for nested_key in ("@graph", "mainEntity", "video", "hasPart"):
        if nested_key in value:
            values.extend(_json_ld_text_values(value[nested_key]))

    return values


def _extract_json_ld_text(soup: object) -> str | None:
    """Extract article or video text from JSON-LD script blocks."""
    lines: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        lines.extend(_json_ld_text_values(parsed))

    cleaned = _dedupe_lines(lines)
    return "\n".join(cleaned)[:_MAX_EXTRACTED_TEXT_CHARS] if cleaned else None


def _extract_visible_page_text(soup: object) -> str | None:
    """Extract readable article/main text from a BeautifulSoup document."""
    for tag in soup.find_all(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    selectors = [
        "article",
        "main",
        "[role='main']",
        ".article",
        ".post-content",
        ".entry-content",
        ".content",
        "#content",
    ]
    containers = [container for selector in selectors for container in soup.select(selector)]
    if not containers:
        body = soup.find("body")
        containers = [body or soup]

    candidates: list[str] = []
    for container in containers:
        lines: list[str] = []
        for node in container.find_all(["h1", "h2", "h3", "p", "li", "blockquote"], limit=400):
            text = _clean_text(node.get_text(" ", strip=True))
            if len(text) >= 40 or node.name in {"h1", "h2", "h3"}:
                lines.append(text)

        unique_lines = _dedupe_lines(lines)
        if unique_lines:
            candidates.append("\n".join(unique_lines))

    if not candidates:
        text = _clean_text(soup.get_text(" ", strip=True))
        return text[:_MAX_EXTRACTED_TEXT_CHARS] if text else None

    best = max(candidates, key=len)
    return best[:_MAX_EXTRACTED_TEXT_CHARS]


def _extract_page_text(soup: object) -> str | None:
    """Extract the best available content text from structured data and visible HTML."""
    json_ld_text = _extract_json_ld_text(soup)
    visible_text = _extract_visible_page_text(soup)
    lines = _dedupe_lines([part for part in (json_ld_text, visible_text) if part])
    if not lines:
        return None
    return "\n".join(lines)[:_MAX_EXTRACTED_TEXT_CHARS]


def _is_video_like_url(url: str) -> bool:
    """Return whether a URL points to a common video/social-video provider."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(domain in host for domain in _VIDEO_DOMAINS):
        return True
    return any(marker in path for marker in ("/watch", "/video", "/videos", "/reel", "/reels", "/shorts"))


def _extract_video_url(soup: object) -> str | None:
    """Extract an embedded video/player URL from common HTML metadata."""
    for property_name in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player"):
        value = _meta_content(soup, property_name=property_name)
        if value:
            return value

    video = soup.find("video")
    if video is not None:
        src = video.get("src")
        if isinstance(src, str) and src.strip():
            return src.strip()
        source = video.find("source")
        source_src = source.get("src") if source is not None else None
        if isinstance(source_src, str) and source_src.strip():
            return source_src.strip()

    return None


def _fetch_youtube_oembed(url: str) -> dict[str, Any]:
    """Fetch YouTube oEmbed metadata, which is often better than scraped page metadata."""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    if "youtube.com" not in host and "youtu.be" not in host:
        return {}

    try:
        response = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=10.0,
            follow_redirects=True,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("youtube_oembed_fetch_failed", url=url, duration_ms=0)
        return {}


def _parse_caption_json3(raw: str) -> str | None:
    """Parse YouTube json3 caption text into plain transcript text."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    lines: list[str] = []
    for event in data.get("events", []):
        if not isinstance(event, dict):
            continue
        segments = event.get("segs")
        if not isinstance(segments, list):
            continue
        line = "".join(str(segment.get("utf8", "")) for segment in segments if isinstance(segment, dict))
        line = _clean_text(line)
        if line:
            lines.append(line)

    cleaned = _dedupe_lines(lines)
    return " ".join(cleaned)[:_MAX_EXTRACTED_TEXT_CHARS] if cleaned else None


def _parse_caption_vtt(raw: str) -> str | None:
    """Parse WebVTT caption text into plain transcript text."""
    lines: list[str] = []
    for line in raw.splitlines():
        clean = line.strip()
        if not clean or clean.upper().startswith("WEBVTT") or "-->" in clean:
            continue
        if re.match(r"^\d+$", clean):
            continue
        clean = re.sub(r"<[^>]+>", "", clean)
        clean = _clean_text(clean)
        if clean:
            lines.append(clean)

    cleaned = _dedupe_lines(lines)
    return " ".join(cleaned)[:_MAX_EXTRACTED_TEXT_CHARS] if cleaned else None


def _select_caption_tracks(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the best English caption tracks from yt-dlp metadata."""
    caption_groups = [info.get("subtitles"), info.get("automatic_captions")]
    for captions in caption_groups:
        if not isinstance(captions, dict):
            continue
        for language in ("en", "en-US", "en-GB", "en-orig"):
            tracks = captions.get(language)
            if isinstance(tracks, list) and tracks:
                return [track for track in tracks if isinstance(track, dict)]
        for language, tracks in captions.items():
            if str(language).lower().startswith("en") and isinstance(tracks, list) and tracks:
                return [track for track in tracks if isinstance(track, dict)]
    return []


def _fetch_caption_track_text(info: dict[str, Any]) -> str | None:
    """Fetch and parse a caption track from yt-dlp metadata when available."""
    tracks = _select_caption_tracks(info)
    if not tracks:
        return None

    preferred = sorted(
        tracks,
        key=lambda track: 0 if track.get("ext") == "json3" else 1 if track.get("ext") == "vtt" else 2,
    )
    for track in preferred:
        caption_url = track.get("url")
        if not isinstance(caption_url, str) or not caption_url:
            continue
        try:
            response = httpx.get(caption_url, timeout=15.0, follow_redirects=True, trust_env=False)
            response.raise_for_status()
            raw = response.text
            transcript = _parse_caption_json3(raw) if track.get("ext") == "json3" else _parse_caption_vtt(raw)
            if transcript:
                return transcript
        except Exception:
            logger.exception("video_caption_fetch_failed", duration_ms=0)
    return None


def _yt_dlp_base_options(logger_adapter: object) -> dict[str, Any]:
    """Return shared yt-dlp options for public metadata and video downloads."""
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "logger": logger_adapter,
        "noplaylist": True,
        "socket_timeout": get_int_env("YTDLP_SOCKET_TIMEOUT_SECONDS", 15),
        "retries": get_int_env("YTDLP_RETRIES", 2),
        "fragment_retries": get_int_env("YTDLP_FRAGMENT_RETRIES", 2),
    }
    cookie_file = get_env("YTDLP_COOKIES_FILE") or get_env("YTDLP_COOKIES_PATH")
    cookies_browser = get_env("YTDLP_COOKIES_BROWSER")
    if cookie_file:
        options["cookiefile"] = cookie_file
    elif cookies_browser:
        options["cookiesfrombrowser"] = (cookies_browser,)
    return options


def _coerce_single_video_info(info: Any) -> dict[str, Any]:
    """Return the first video info object from a yt-dlp response."""
    if not isinstance(info, dict):
        return {}
    entries = info.get("entries")
    if isinstance(entries, list) and entries:
        first_entry = entries[0]
        return first_entry if isinstance(first_entry, dict) else {}
    return info


def _video_info_within_limits(info: dict[str, Any]) -> bool:
    """Return whether a candidate social video is small enough for inline Gemini analysis."""
    max_duration_seconds = get_int_env("VIDEO_URL_MAX_DURATION_SECONDS", 180)
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > max_duration_seconds:
        logger.info(
            "video_url_analysis_skipped_duration",
            duration_seconds=duration,
            max_duration_seconds=max_duration_seconds,
            duration_ms=0,
        )
        return False

    max_bytes = get_int_env("VIDEO_URL_MAX_BYTES", 18_000_000)
    for key in ("filesize", "filesize_approx"):
        size = info.get(key)
        if isinstance(size, int) and size > max_bytes:
            logger.info(
                "video_url_analysis_skipped_size",
                size_bytes=size,
                max_bytes=max_bytes,
                duration_ms=0,
            )
            return False

    return True


def _downloaded_video_path(tmp_dir: Path, info: dict[str, Any]) -> Path | None:
    """Find the final downloaded video path from yt-dlp metadata or temp files."""
    requested_downloads = info.get("requested_downloads")
    if isinstance(requested_downloads, list):
        for download in requested_downloads:
            if not isinstance(download, dict):
                continue
            filepath = download.get("filepath")
            if isinstance(filepath, str) and Path(filepath).exists():
                return Path(filepath)

    candidates = [path for path in tmp_dir.iterdir() if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_size)


def _video_mime_type(path: Path, info: dict[str, Any]) -> str:
    """Infer a video MIME type from yt-dlp metadata or the downloaded filename."""
    mime_type = info.get("mime_type")
    if isinstance(mime_type, str) and mime_type.startswith("video/"):
        return mime_type

    extension = str(info.get("ext") or path.suffix.removeprefix(".")).lower()
    if extension == "mov":
        return "video/quicktime"
    guessed, _encoding = mimetypes.guess_type(f"video.{extension}" if extension else str(path))
    return guessed if guessed and guessed.startswith("video/") else "video/mp4"


def _download_video_for_analysis(url: str, logger_adapter: object) -> dict[str, Any]:
    """Download a bounded public social video for multimodal Gemini analysis."""
    if not get_bool_env("VIDEO_URL_ANALYSIS_ENABLED", True):
        return {}

    try:
        import yt_dlp
    except ImportError:
        logger.info("video_url_analysis_skipped_missing_ytdlp", url=url, duration_ms=0)
        return {}

    max_bytes = get_int_env("VIDEO_URL_MAX_BYTES", 18_000_000)
    tmp_parent_value = get_env("STASH_TMP_DIR")
    tmp_parent = Path(tmp_parent_value) if tmp_parent_value else None
    if tmp_parent is not None:
        tmp_parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="stash-video-", dir=tmp_parent))
    try:
        options = _yt_dlp_base_options(logger_adapter)
        options.update(
            {
                "format": get_env("VIDEO_URL_DOWNLOAD_FORMAT", _DEFAULT_VIDEO_DOWNLOAD_FORMAT),
                "max_filesize": max_bytes,
                "outtmpl": str(tmp_dir / "video.%(ext)s"),
                "merge_output_format": "mp4",
            }
        )

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = _coerce_single_video_info(downloader.extract_info(url, download=True))
        except Exception:
            logger.warning("video_url_download_failed", url=url, duration_ms=0)
            return {}

        downloaded_path = _downloaded_video_path(tmp_dir, info)
        if downloaded_path is None:
            logger.warning("video_url_download_missing_file", url=url, duration_ms=0)
            return {}

        size_bytes = downloaded_path.stat().st_size
        if size_bytes > max_bytes:
            logger.info(
                "video_url_analysis_skipped_downloaded_size",
                url=url,
                size_bytes=size_bytes,
                max_bytes=max_bytes,
                duration_ms=0,
            )
            return {}

        video_bytes = downloaded_path.read_bytes()
        if not video_bytes:
            return {}

        return {
            "video_bytes": video_bytes,
            "video_mime_type": _video_mime_type(downloaded_path, info),
            "video_duration_seconds": str(info.get("duration") or ""),
            "video_source": "yt-dlp",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _fetch_video_provider_metadata(url: str) -> dict[str, Any]:
    """Use optional yt-dlp support to fetch public video title, description, and captions."""
    try:
        import yt_dlp
    except ImportError:
        logger.info("video_provider_metadata_skipped_missing_ytdlp", url=url, duration_ms=0)
        return {}

    class _YtDlpLogger:
        """Suppress yt-dlp stderr noise while preserving structured Stash logs."""

        def debug(self, message: str) -> None:
            return None

        def info(self, message: str) -> None:
            return None

        def warning(self, message: str) -> None:
            logger.warning("video_provider_metadata_warning", url=url, message=message, duration_ms=0)

        def error(self, message: str) -> None:
            logger.warning("video_provider_metadata_error", url=url, message=message, duration_ms=0)

    try:
        options = _yt_dlp_base_options(_YtDlpLogger())
        options["skip_download"] = True
        with yt_dlp.YoutubeDL(options) as downloader:
            info = _coerce_single_video_info(downloader.extract_info(url, download=False))
    except Exception:
        logger.warning("video_provider_metadata_fetch_failed", url=url, duration_ms=0)
        return {}

    if not isinstance(info, dict):
        return {}

    transcript = _fetch_caption_track_text(info)
    title = info.get("title")
    description = info.get("description")
    uploader = info.get("uploader") or info.get("channel")
    webpage_url = info.get("webpage_url")
    thumbnail = info.get("thumbnail")

    lines = [
        f"Video title: {title}" if isinstance(title, str) and title.strip() else "",
        f"Channel: {uploader}" if isinstance(uploader, str) and uploader.strip() else "",
        f"Video transcript:\n{transcript}" if transcript else "",
        f"Video description:\n{description}" if isinstance(description, str) and description.strip() else "",
    ]
    content_text = "\n".join(part for part in lines if part)[:_MAX_EXTRACTED_TEXT_CHARS]
    video_download = _download_video_for_analysis(url, _YtDlpLogger()) if _video_info_within_limits(info) else {}

    return {
        "title": title.strip() if isinstance(title, str) and title.strip() else None,
        "description": description.strip() if isinstance(description, str) and description.strip() else None,
        "image_url": thumbnail.strip() if isinstance(thumbnail, str) and thumbnail.strip() else None,
        "content_text": content_text or None,
        "resolved_url": webpage_url.strip() if isinstance(webpage_url, str) and webpage_url.strip() else None,
        "site_name": uploader.strip() if isinstance(uploader, str) and uploader.strip() else None,
        "video_url": webpage_url.strip() if isinstance(webpage_url, str) and webpage_url.strip() else None,
        **video_download,
    }


def fetch_og_metadata(url: str) -> dict[str, Any]:
    """Fetch URL metadata and readable page text with a safe fallback on errors."""
    fallback: dict[str, Any] = {
        "title": url,
        "description": None,
        "image_url": None,
        "content_text": None,
        "resolved_url": url,
        "site_name": None,
        "is_video": "true" if _is_video_like_url(url) else "false",
        "video_url": None,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    provider_metadata: dict[str, str | None] = {}
    try:
        provider_metadata = _fetch_video_provider_metadata(url) if _is_video_like_url(url) else {}
        response = httpx.get(url, headers=headers, timeout=10.0, follow_redirects=True, trust_env=False)
        response.raise_for_status()

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "html.parser")
        html_title = soup.find("title")
        title_text = html_title.get_text(strip=True) if html_title is not None else None
        youtube_oembed = _fetch_youtube_oembed(url)
        oembed_title = youtube_oembed.get("title")
        oembed_author = youtube_oembed.get("author_name")
        oembed_thumbnail = youtube_oembed.get("thumbnail_url")

        title = (
            provider_metadata.get("title")
            or (
            str(oembed_title).strip()
            if isinstance(oembed_title, str) and oembed_title.strip()
            else _meta_content(soup, property_name="og:title") or title_text or url
            )
        )
        description = (
            provider_metadata.get("description")
            or _meta_content(soup, property_name="og:description")
            or _meta_content(soup, name="description")
        )
        image_url = (
            provider_metadata.get("image_url")
            or
            _meta_content(soup, property_name="og:image")
            or (str(oembed_thumbnail).strip() if isinstance(oembed_thumbnail, str) and oembed_thumbnail.strip() else None)
        )
        site_name = provider_metadata.get("site_name") or _meta_content(soup, property_name="og:site_name")
        video_url = provider_metadata.get("video_url") or _extract_video_url(soup)
        is_video = _is_video_like_url(url) or bool(video_url) or (_meta_content(soup, property_name="og:type") or "").startswith("video")
        content_text = _extract_page_text(soup)

        if provider_metadata.get("content_text"):
            content_text = "\n".join(
                part for part in (provider_metadata.get("content_text"), content_text) if part
            )[:_MAX_EXTRACTED_TEXT_CHARS]

        if youtube_oembed:
            oembed_lines = [f"Video title: {title}"]
            if isinstance(oembed_author, str) and oembed_author.strip():
                oembed_lines.append(f"Channel: {oembed_author.strip()}")
            oembed_lines.append("Provider: YouTube")
            if not content_text or "Video title:" not in content_text:
                content_text = "\n".join(oembed_lines + ([content_text] if content_text else []))[:_MAX_EXTRACTED_TEXT_CHARS]

        return {
            "title": title,
            "description": description,
            "image_url": image_url,
            "content_text": content_text,
            "resolved_url": str(response.url),
            "site_name": site_name,
            "is_video": "true" if is_video else "false",
            "video_url": video_url,
        }
    except Exception:
        logger.warning("og_metadata_fetch_failed", url=url, duration_ms=0)
        if provider_metadata:
            fallback.update({key: value for key, value in provider_metadata.items() if value})
        return fallback
