# All rights reserved.
"""Reliable YouTube resolver for VenomX playback.

A YouTube numeric format id is never hard-coded here. yt-dlp selects a format
that is actually exposed by the current extractor/client, with mweb+WPC used
only as a fallback for bot-check protected videos.
"""

import asyncio
import base64
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from py_yt import VideosSearch
from yt_dlp import YoutubeDL

from .Youtube import YouTube as LegacyYouTube

_LOGGER_NAME = "VenomX.platforms.youtube_engine"
_STREAM_CACHE_TTL = 90.0
_MAX_CACHE = 256
_EXTRACT_TIMEOUT = 45.0
_DOWNLOAD_TIMEOUT = 240.0
_DOWNLOAD_DIR = Path("downloads")
_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
_COOKIE_RUNTIME_PATH = Path("/tmp/tommy-youtube-cookies.txt")

# Default extraction is first. Forced player clients were causing the repeated
# "Requested format is not available" failures seen in deployment logs.
_CLIENT_PROFILES = (
    (None, False),
    ("mweb", True),
    ("tv", False),
)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
_STREAM_CACHE: dict[tuple[str, bool], tuple[float, str]] = {}
_PREFETCH_TASKS: dict[tuple[str, bool], asyncio.Task] = {}


def _log(level: str, message: str, *args) -> None:
    getattr(logging.getLogger(_LOGGER_NAME), level)(
        f"[YoutubeEngine] {message}", *args
    )


def _youtube_url(value: str, videoid: bool = False) -> str:
    if videoid:
        return f"https://www.youtube.com/watch?v={value}"
    return value.split("&", 1)[0] if "&" in value else value


def _cookie_file() -> Optional[str]:
    encoded = os.getenv("YOUTUBE_COOKIES_B64", "").strip()
    raw = os.getenv("YOUTUBE_COOKIES", "")
    if encoded or raw:
        try:
            data = base64.b64decode(encoded).decode("utf-8") if encoded else raw
            if "# Netscape HTTP Cookie File" in data or "# HTTP Cookie File" in data:
                _COOKIE_RUNTIME_PATH.write_text(data, encoding="utf-8")
                os.chmod(_COOKIE_RUNTIME_PATH, 0o600)
                return str(_COOKIE_RUNTIME_PATH)
        except Exception as exc:
            _log("warning", "failed to materialize YouTube cookies: %s", exc)

    root = Path.cwd() / "cookies"
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.txt")):
        try:
            head = path.read_text(errors="ignore")[:300]
        except OSError:
            continue
        if "# Netscape HTTP Cookie File" in head or "# HTTP Cookie File" in head:
            return str(path)
    return None


def _browser_path() -> str:
    configured = os.getenv("WPC_BROWSER_PATH", "").strip()
    if configured and os.path.isfile(configured):
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def _js_runtimes() -> dict:
    deno = shutil.which("deno")
    if deno:
        return {"deno": {"path": deno}}
    node = shutil.which("node")
    if node:
        return {"node": {"path": node}}
    return {}


def _common_options(client: Optional[str], use_pot: bool, **extra) -> dict:
    extractor_args = {}
    if client:
        youtube_args = {"player_client": [client]}
        if use_pot:
            youtube_args["fetch_pot"] = ["auto"]
        extractor_args["youtube"] = youtube_args
        browser = _browser_path()
        if use_pot and browser:
            extractor_args["youtubepot-wpc"] = {"browser_path": browser}

    options = {
        "extractor_args": extractor_args,
        "js_runtimes": _js_runtimes(),
        "cookiefile": _cookie_file(),
        "proxy": os.getenv("PROXY_URL", "").strip() or None,
        "http_headers": {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "extractor_retries": 1,
        "fragment_retries": 2,
        "retries": 2,
        "socket_timeout": 10,
        "concurrent_fragment_downloads": 2,
        "buffersize": "1M",
    }
    options = {k: v for k, v in options.items() if v is not None}
    options.update(extra)
    return options


def _format_for(video: bool) -> str:
    if video:
        return "best[height<=720]/best"
    return "bestaudio/best"


def _extract_sync(url: str, video: bool, *, download: bool = False, **extra):
    fmt = _format_for(video)
    last_error = None
    for client, use_pot in _CLIENT_PROFILES:
        label = client or "default"
        options = _common_options(client, use_pot, format=fmt, **extra)
        started = time.monotonic()
        try:
            _log("info", "extracting client=%s format=%s pot=%s download=%s", label, fmt, use_pot, download)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=download)
            if not info:
                raise RuntimeError("yt-dlp returned empty metadata")
            _log("info", "client=%s succeeded in %.1fs protocol=%s", label, time.monotonic() - started, info.get("protocol", "unknown"))
            return info
        except Exception as exc:
            last_error = exc
            _log("warning", "client=%s failed after %.1fs: %s", label, time.monotonic() - started, exc)
    raise RuntimeError(f"all YouTube extraction profiles failed: {last_error}")


async def _extract(url: str, video: bool, *, download: bool = False, timeout: float = _EXTRACT_TIMEOUT, **extra):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_extract_sync, url, video, download=download, **extra),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        _log("error", "YouTube extraction timed out after %.0fs: %s", timeout, url[:120])
        raise RuntimeError(f"YouTube extraction timed out after {timeout:.0f}s") from exc


def _cleanup_cache() -> None:
    if len(_STREAM_CACHE) <= _MAX_CACHE:
        return
    oldest = sorted(_STREAM_CACHE.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: max(1, len(oldest) - _MAX_CACHE)]:
        _STREAM_CACHE.pop(key, None)


def _valid_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 10_240
    except OSError:
        return False


def _find_downloaded(video_id: str, prepared: Optional[Path] = None) -> Optional[str]:
    if prepared and _valid_file(prepared):
        return str(prepared)
    candidates = [p for p in _DOWNLOAD_DIR.glob(f"{video_id}*") if _valid_file(p)]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0])


class YouTubeResilient(LegacyYouTube):
    """Drop-in YouTube implementation used by Platform.youtube."""

    async def details(self, link: str, videoid: bool | str = None):
        url = _youtube_url(link, bool(videoid))
        if "youtube.com/" in url or "youtu.be/" in url:
            info = await _extract(url, False, download=False, skip_download=True)
            duration = int(info.get("duration") or 0)
            thumbnail = info.get("thumbnail") or f"https://img.youtube.com/vi/{info['id']}/maxresdefault.jpg"
            return info.get("title") or "Unknown title", self._duration_text(duration), duration, thumbnail.split("?", 1)[0], info["id"]
        return await super().details(link, videoid)

    @staticmethod
    def _duration_text(seconds: int) -> str:
        seconds = max(int(seconds or 0), 0)
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    async def track(self, link: str, videoid: bool | str = None):
        if videoid or (isinstance(link, str) and ("youtube.com/" in link or "youtu.be/" in link)):
            return await self.details(link, videoid)
        try:
            results = VideosSearch(link, limit=1, timeout=10)
            data = await asyncio.wait_for(results.next(), timeout=15)
            items = data.get("result", [])
            if items:
                item = items[0]
                return {
                    "title": item["title"],
                    "link": item["link"],
                    "vidid": item["id"],
                    "duration_min": item["duration"],
                    "thumb": item["thumbnails"][0]["url"].split("?", 1)[0],
                }, item["id"]
        except Exception as exc:
            _log("warning", "py_yt search failed: %s", exc)

        info = await _extract(f"ytsearch1:{link}", False, download=False, skip_download=True)
        entry = (info.get("entries") or [None])[0]
        if not entry:
            raise RuntimeError("YouTube search returned no results")
        thumb = entry.get("thumbnail") or f"https://img.youtube.com/vi/{entry['id']}/maxresdefault.jpg"
        return {
            "title": entry.get("title") or "Unknown title",
            "link": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry['id']}",
            "vidid": entry["id"],
            "duration_min": self._duration_text(entry.get("duration") or 0),
            "thumb": thumb.split("?", 1)[0],
        }, entry["id"]

    async def title(self, link: str, videoid: bool | str = None):
        return (await self.details(link, videoid))[0]

    async def duration(self, link: str, videoid: bool | str = None):
        return (await self.details(link, videoid))[1]

    async def thumbnail(self, link: str, videoid: bool | str = None):
        return (await self.details(link, videoid))[3]

    async def stream_url(self, link: str, videoid: bool | str = None, video: bool = False):
        key = (str(link), bool(video))
        cached = _STREAM_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _STREAM_CACHE_TTL:
            _log("info", "stream cache hit video=%s", video)
            return 1, cached[1]
        url = _youtube_url(link, bool(videoid))
        try:
            info = await _extract(url, bool(video), download=False, skip_download=True)
            direct = info.get("url")
            if not direct:
                requested = info.get("requested_formats") or []
                if len(requested) == 1:
                    direct = requested[0].get("url")
            if not direct:
                raise RuntimeError("yt-dlp returned no single direct media URL")
            _STREAM_CACHE[key] = (time.monotonic(), direct)
            _cleanup_cache()
            _log("info", "direct stream ready video=%s protocol=%s", video, info.get("protocol", "unknown"))
            return 1, direct
        except Exception as exc:
            _log("error", "stream_url failed for %s: %s", url[:100], exc)
            return 0, str(exc)

    async def prefetch(self, videoid: str, video: bool = False):
        key = (videoid, bool(video))
        cached = _STREAM_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _STREAM_CACHE_TTL:
            return
        existing = _PREFETCH_TASKS.get(key)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self.stream_url(videoid, videoid=True, video=video))
        _PREFETCH_TASKS[key] = task
        try:
            await task
        except Exception:
            pass
        finally:
            _PREFETCH_TASKS.pop(key, None)

    async def video(self, link: str, videoid: str | bool = None):
        return await self.stream_url(link, videoid=videoid, video=True)

    async def download(
        self, link: str, mystic, video: bool | str = None,
        videoid: bool | str = None, songaudio: bool | str = None,
        songvideo: bool | str = None, format_id: bool | str = None,
        title: bool | str = None,
    ):
        url = _youtube_url(link, bool(videoid))
        if songaudio:
            fmt = format_id or "bestaudio/best"
            extra = {
                "outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s"),
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
                "postprocessor_args": {"ffmpeg": ["-b:a", "320k"]},
            }
        elif songvideo or video:
            fmt = format_id or "bv*[height<=720]+ba/b[height<=720]"
            extra = {
                "outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s"),
                "merge_output_format": "mp4",
            }
        else:
            fmt = format_id or "bestaudio/best"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s")}

        def _download_sync():
            last_error = None
            for client, use_pot in _CLIENT_PROFILES:
                label = client or "default"
                try:
                    _log("info", "download client=%s format=%s pot=%s", label, fmt, use_pot)
                    with YoutubeDL(_common_options(client, use_pot, format=fmt, **extra)) as ydl:
                        info = ydl.extract_info(url, download=True)
                        found = _find_downloaded(info.get("id", ""), Path(ydl.prepare_filename(info)))
                        if found:
                            return found, True
                except Exception as exc:
                    last_error = exc
                    _log("warning", "download client=%s failed: %s", label, exc)
            raise RuntimeError(f"all YouTube download profiles failed: {last_error}")

        try:
            return await asyncio.wait_for(asyncio.to_thread(_download_sync), timeout=_DOWNLOAD_TIMEOUT)
        except asyncio.TimeoutError as exc:
            _log("error", "YouTube download timed out after %.0fs", _DOWNLOAD_TIMEOUT)
            raise RuntimeError(f"YouTube download timed out after {_DOWNLOAD_TIMEOUT:.0f}s") from exc


__all__ = ["YouTubeResilient"]
