# All rights reserved.
"""Resilient YouTube extraction/streaming engine for Tommy."""

import asyncio
import base64
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from py_yt import VideosSearch
from yt_dlp import YoutubeDL

from .Youtube import YouTube as LegacyYouTube


_LOG_TAG = "YoutubeEngine"
_CACHE_TTL = 240.0
_MAX_CACHE = 512
_DOWNLOAD_DIR = Path("downloads")
_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
_COOKIE_RUNTIME_PATH = Path("/tmp/tommy-youtube-cookies.txt")

# Profiles are tried independently. This avoids relying on one YouTube client
# when YouTube changes SABR/PO-token behaviour for another client.
_CLIENT_PROFILES = (
    "mweb",
    "web_safari",
    "web",
    "tv",
)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

_STREAM_CACHE: dict[tuple[str, bool], tuple[float, str]] = {}
_PREFETCH_TASKS: dict[tuple[str, bool], asyncio.Task] = {}


def _log(level: str, message: str, *args):
    import logging
    getattr(logging.getLogger("VenomX.platforms.youtube_engine"), level)(f"[{_LOG_TAG}] {message}", *args)


def _youtube_url(value: str, videoid: bool = False) -> str:
    if videoid:
        return f"https://www.youtube.com/watch?v={value}"
    return value.split("&", 1)[0] if "&" in value else value


def _cookie_file() -> Optional[str]:
    """Return a safe runtime cookie file without requiring secrets in Git."""
    encoded = os.getenv("YOUTUBE_COOKIES_B64", "").strip()
    raw = os.getenv("YOUTUBE_COOKIES", "")
    if encoded or raw:
        try:
            data = base64.b64decode(encoded).decode("utf-8") if encoded else raw
            if "# Netscape HTTP Cookie File" in data or "# HTTP Cookie File" in data:
                _COOKIE_RUNTIME_PATH.write_text(data)
                os.chmod(_COOKIE_RUNTIME_PATH, 0o600)
                return str(_COOKIE_RUNTIME_PATH)
        except Exception as exc:
            _log("warning", "failed to materialize YOUTUBE_COOKIES secret: %s", exc)

    root = Path.cwd() / "cookies"
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.txt")):
        try:
            head = path.read_text(errors="ignore")[:200]
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


def _common_options(client: str, **extra) -> dict:
    extractor_args = {
        "youtube": {
            "player_client": [client],
            "fetch_pot": ["auto"],
        }
    }
    browser = _browser_path()
    if browser:
        extractor_args["youtubepot-wpc"] = {
            "browser_path": browser,
            "no_sandbox": True,
        }

    opts = {
        "extractor_args": extractor_args,
        "js_runtimes": _js_runtimes(),
        "remote_components": ["ejs:github"],
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
        "extractor_retries": 3,
        "fragment_retries": 5,
        "retries": 5,
        "socket_timeout": 15,
        "concurrent_fragment_downloads": 4,
        "buffersize": "1M",
    }
    opts = {k: v for k, v in opts.items() if v is not None}
    opts.update(extra)
    return opts


def _extract_sync(url: str, fmt: str, *, download: bool = False, **extra):
    last_error = None
    for client in _CLIENT_PROFILES:
        options = _common_options(client, format=fmt, **extra)
        try:
            _log("info", "extracting client=%s format=%s", client, fmt)
            with YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=download)
        except Exception as exc:
            last_error = exc
            _log("warning", "client=%s failed: %s", client, exc)
    raise RuntimeError(f"all YouTube extraction profiles failed: {last_error}")


def _cleanup_cache():
    if len(_STREAM_CACHE) <= _MAX_CACHE:
        return
    oldest = sorted(_STREAM_CACHE.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: max(1, len(oldest) - _MAX_CACHE)]:
        _STREAM_CACHE.pop(key, None)


class YouTubeResilient(LegacyYouTube):
    """Drop-in YouTube implementation used by Platform.youtube."""

    async def details(self, link: str, videoid: bool | str = None):
        url = _youtube_url(link, bool(videoid))
        if "youtube.com/" in url or "youtu.be/" in url:
            info = await asyncio.to_thread(_extract_sync, url, "best", download=False, skip_download=True)
            duration = info.get("duration") or 0
            duration_min = self._duration_text(duration)
            thumbnail = info.get("thumbnail") or f"https://img.youtube.com/vi/{info['id']}/maxresdefault.jpg"
            return info.get("title") or "Unknown title", duration_min, int(duration), thumbnail.split("?", 1)[0], info["id"]
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
                return {"title": item["title"], "link": item["link"], "vidid": item["id"], "duration_min": item["duration"], "thumb": item["thumbnails"][0]["url"].split("?", 1)[0]}, item["id"]
        except Exception as exc:
            _log("warning", "py_yt search failed: %s", exc)

        info = await asyncio.to_thread(_extract_sync, f"ytsearch1:{link}", "best", download=False, skip_download=True)
        entry = (info.get("entries") or [None])[0]
        if not entry:
            raise RuntimeError("YouTube search returned no results")
        thumb = entry.get("thumbnail") or f"https://img.youtube.com/vi/{entry['id']}/maxresdefault.jpg"
        result = {"title": entry.get("title") or "Unknown title", "link": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry['id']}", "vidid": entry["id"], "duration_min": self._duration_text(entry.get("duration") or 0), "thumb": thumb.split("?", 1)[0]}
        return result, entry["id"]

    async def title(self, link: str, videoid: bool | str = None):
        return (await self.details(link, videoid))[0]

    async def duration(self, link: str, videoid: bool | str = None):
        return (await self.details(link, videoid))[1]

    async def thumbnail(self, link: str, videoid: bool | str = None):
        return (await self.details(link, videoid))[3]

    async def stream_url(self, link: str, videoid: bool | str = None, video: bool = False):
        key = (str(link), bool(video))
        cached = _STREAM_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return 1, cached[1]
        url = _youtube_url(link, bool(videoid))
        # PyTgCalls accepts one media URL. For video, select a single-file
        # audio+video format capped at 720p to prevent the old video-only URL bug.
        fmt = "best[height<=720]/18/best" if video else "bestaudio/best/18"
        try:
            info = await asyncio.to_thread(_extract_sync, url, fmt, download=False, skip_download=True)
            direct = info.get("url")
            if not direct:
                requested = info.get("requested_formats") or []
                if requested and requested[0].get("url"):
                    direct = requested[0]["url"]
            if not direct:
                raise RuntimeError("yt-dlp returned no direct stream URL")
            _STREAM_CACHE[key] = (time.monotonic(), direct)
            _cleanup_cache()
            return 1, direct
        except Exception as exc:
            _log("error", "stream_url failed for %s: %s", url[:90], exc)
            return 0, str(exc)

    async def prefetch(self, videoid: str, video: bool = False):
        key = (videoid, bool(video))
        if key in _STREAM_CACHE and time.monotonic() - _STREAM_CACHE[key][0] < _CACHE_TTL:
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

    async def video(self, link: str, videoid: bool | str = None):
        return await self.stream_url(link, videoid=videoid, video=True)

    async def download(self, link: str, mystic, video: bool | str = None, videoid: bool | str = None, songaudio: bool | str = None, songvideo: bool | str = None, format_id: bool | str = None, title: bool | str = None):
        url = _youtube_url(link, bool(videoid))
        if songaudio:
            fmt = format_id or "bestaudio/best"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s"), "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}], "postprocessor_args": {"ffmpeg": ["-b:a", "320k"]}}
        elif songvideo:
            fmt = f"{format_id}+bestaudio/best" if format_id else "bv*[height<=720]+ba/b[height<=720]"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s"), "merge_output_format": "mp4"}
        elif video:
            fmt = "bv*[height<=720]+ba/b[height<=720]"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s.%(ext)s"), "merge_output_format": "mp4"}
        else:
            fmt = "bestaudio/best"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s.%(ext)s")}

        def _download_sync():
            last_error = None
            for client in _CLIENT_PROFILES:
                options = _common_options(client, format=fmt, **extra)
                try:
                    with YoutubeDL(options) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if songaudio:
                            expected = _DOWNLOAD_DIR / f"{info['id']}_{info.get('format_id', format_id)}.mp3"
                            if expected.exists():
                                return str(expected)
                        prepared = Path(ydl.prepare_filename(info))
                        if extra.get("merge_output_format") == "mp4" and prepared.with_suffix(".mp4").exists():
                            return str(prepared.with_suffix(".mp4"))
                        if prepared.exists():
                            return str(prepared)
                        candidates = sorted(_DOWNLOAD_DIR.glob(f"{info['id']}*"), key=lambda p: p.stat().st_mtime, reverse=True)
                        if candidates:
                            return str(candidates[0])
                except Exception as exc:
                    last_error = exc
                    _log("warning", "download client=%s failed: %s", client, exc)
            raise RuntimeError(f"all YouTube download profiles failed: {last_error}")

        path = await asyncio.to_thread(_download_sync)
        return path, True


__all__ = ["YouTubeResilient"]
