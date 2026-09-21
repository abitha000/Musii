# All rights reserved.
"""Reliable YouTube resolver for Musii using cookies + bgutil PO tokens."""
import asyncio
import base64
import logging
import os
import time
from pathlib import Path
from typing import Optional

from py_yt import VideosSearch
from yt_dlp import YoutubeDL
from .Youtube import YouTube as LegacyYouTube

_LOGGER = logging.getLogger("VenomX.platforms.youtube_engine")
_STREAM_CACHE_TTL = 90.0
_MAX_CACHE = 128
_EXTRACT_TIMEOUT = 28.0
_DOWNLOAD_TIMEOUT = 150.0
_DOWNLOAD_DIR = Path("downloads")
_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
_COOKIE_RUNTIME_PATH = Path("/tmp/musii-youtube-cookies.txt")
_STREAM_CACHE: dict[tuple[str, bool], tuple[float, str]] = {}
_PREFETCH_TASKS: dict[tuple[str, bool], asyncio.Task] = {}


def _log(level: str, message: str, *args) -> None:
    getattr(_LOGGER, level)("[YoutubeEngine] " + message, *args)


def _youtube_url(value: str, videoid: bool = False) -> str:
    if videoid:
        return f"https://www.youtube.com/watch?v={value}"
    return value.split("&", 1)[0] if "&" in value else value


def _cookie_file() -> Optional[str]:
    encoded = os.getenv("YOUTUBE_COOKIES_B64", "").strip()
    raw = os.getenv("YOUTUBE_COOKIES", "")
    configured = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    if encoded or raw:
        try:
            data = base64.b64decode(encoded).decode("utf-8") if encoded else raw
            if "# Netscape HTTP Cookie File" not in data and "# HTTP Cookie File" not in data:
                data = data.replace("\\n", "\n")
            if "# Netscape HTTP Cookie File" in data or "# HTTP Cookie File" in data:
                _COOKIE_RUNTIME_PATH.write_text(data, encoding="utf-8")
                os.chmod(_COOKIE_RUNTIME_PATH, 0o600)
                return str(_COOKIE_RUNTIME_PATH)
        except Exception as exc:
            _log("warning", "failed to materialize YouTube cookies: %s", exc)
    if configured and Path(configured).is_file():
        return configured
    root = Path.cwd() / "cookies"
    if root.is_dir():
        for path in sorted(root.glob("*.txt")):
            try:
                head = path.read_text(errors="ignore")[:300]
            except OSError:
                continue
            if "# Netscape HTTP Cookie File" in head or "# HTTP Cookie File" in head:
                return str(path)
    return None


def _js_runtimes() -> dict:
    deno = Path("/usr/local/deno/bin/deno")
    return {"deno": {"path": str(deno)}} if deno.is_file() else {}


def _common_options(client: Optional[str], use_pot: bool, **extra) -> dict:
    extractor_args: dict = {}
    if client:
        youtube_args = {"player_client": [client]}
        if use_pot:
            youtube_args["fetch_pot"] = ["auto"]
        extractor_args["youtube"] = youtube_args
    if use_pot:
        extractor_args["youtubepot-bgutilhttp"] = {
            "base_url": os.getenv("YOUTUBE_POT_PROVIDER_URL", "http://127.0.0.1:4416")
        }
    options = {
        "extractor_args": extractor_args,
        "js_runtimes": _js_runtimes(),
        "cookiefile": _cookie_file(),
        "proxy": os.getenv("PROXY_URL", "").strip() or None,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "extractor_retries": 1,
        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 7,
        "concurrent_fragment_downloads": 2,
        "buffersize": "1M",
    }
    options.update({k: v for k, v in extra.items() if v is not None})
    return options


def _client_profiles() -> tuple[tuple[Optional[str], bool], ...]:
    profiles: list[tuple[Optional[str], bool]] = [("mweb", True), (None, False)]
    if _cookie_file():
        profiles.append(("web_creator", False))
    profiles.append(("web_embedded", False))
    return tuple(profiles)


def _format_for(video: bool) -> str:
    if video:
        return "best[height<=720]/best"
    return "bestaudio[ext=m4a][protocol^=http]/bestaudio[protocol^=http]/bestaudio/best"


def _extract_sync(url: str, video: bool, *, download: bool = False, **extra):
    is_search = url.startswith("ytsearch")
    fmt = None if is_search else _format_for(video)
    last_error = None
    for client, use_pot in _client_profiles():
        label = client or "default"
        started = time.monotonic()
        try:
            opts = _common_options(client, use_pot, **extra)
            if fmt:
                opts["format"] = fmt
            else:
                opts.setdefault("extract_flat", True)
            _log("info", "extracting client=%s format=%s pot=%s download=%s", label, fmt or "search", use_pot, download)
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=download)
            if not info:
                raise RuntimeError("yt-dlp returned empty metadata")
            _log("info", "client=%s succeeded in %.1fs protocol=%s", label, time.monotonic() - started, info.get("protocol", "unknown"))
            return info
        except Exception as exc:
            last_error = exc
            _log("warning", "client=%s failed after %.1fs: %s", label, time.monotonic() - started, str(exc)[:300])
    raise RuntimeError(f"all YouTube extraction profiles failed: {last_error}") from last_error


async def _extract(url: str, video: bool, *, download: bool = False, timeout: float = _EXTRACT_TIMEOUT, **extra):
    try:
        return await asyncio.wait_for(asyncio.to_thread(_extract_sync, url, video, download=download, **extra), timeout=timeout)
    except asyncio.TimeoutError as exc:
        _log("error", "YouTube extraction timed out after %.0fs: %s", timeout, url[:120])
        raise RuntimeError(f"YouTube extraction timed out after {timeout:.0f}s") from exc


def _duration_text(seconds: int) -> str:
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _cleanup_cache() -> None:
    if len(_STREAM_CACHE) <= _MAX_CACHE:
        return
    old = sorted(_STREAM_CACHE.items(), key=lambda item: item[1][0])
    for key, _ in old[:len(old) - _MAX_CACHE]:
        _STREAM_CACHE.pop(key, None)


def _direct_url(info: dict) -> Optional[str]:
    if info.get("url"):
        return info["url"]
    requested = info.get("requested_formats") or []
    if len(requested) == 1:
        return requested[0].get("url")
    return None


class YouTubeResilient(LegacyYouTube):
    async def details(self, link: str, videoid: bool | str = None):
        url = _youtube_url(link, bool(videoid))
        if "youtube.com/" not in url and "youtu.be/" not in url:
            return await super().details(link, videoid)
        info = await _extract(url, False, skip_download=True)
        vid = info.get("id")
        thumb = info.get("thumbnail") or f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
        return info.get("title") or "Unknown title", _duration_text(info.get("duration") or 0), int(info.get("duration") or 0), thumb.split("?", 1)[0], vid

    async def track(self, link: str, videoid: bool | str = None):
        if videoid or (isinstance(link, str) and ("youtube.com/" in link or "youtu.be/" in link)):
            title, duration, _, thumb, vid = await self.details(link, videoid)
            return {"title": title, "link": _youtube_url(link, bool(videoid)), "vidid": vid, "duration_min": duration, "thumb": thumb}, vid
        try:
            results = VideosSearch(link, limit=1, timeout=10)
            data = await asyncio.wait_for(results.next(), timeout=12)
            items = data.get("result", [])
            if items:
                item = items[0]
                return {"title": item["title"], "link": item["link"], "vidid": item["id"], "duration_min": item["duration"], "thumb": item["thumbnails"][0]["url"].split("?", 1)[0]}, item["id"]
        except Exception as exc:
            _log("warning", "py_yt search failed: %s", exc)
        info = await _extract(f"ytsearch1:{link}", False, skip_download=True)
        entry = next(iter(info.get("entries") or []), None)
        if not entry:
            raise RuntimeError("YouTube search returned no result")
        vid = entry["id"]
        thumb = entry.get("thumbnail") or f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
        return {"title": entry.get("title") or "Unknown title", "link": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}", "vidid": vid, "duration_min": _duration_text(entry.get("duration") or 0), "thumb": thumb.split("?", 1)[0]}, vid

    async def title(self, link, videoid=None):
        return (await self.details(link, videoid))[0]

    async def duration(self, link, videoid=None):
        return (await self.details(link, videoid))[1]

    async def thumbnail(self, link, videoid=None):
        return (await self.details(link, videoid))[3]

    async def stream_url(self, link, videoid: bool | str = None, video: bool = False):
        key = (str(videoid if videoid else link), bool(video))
        cached = _STREAM_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _STREAM_CACHE_TTL:
            _log("info", "stream cache hit video=%s", video)
            return 1, cached[1]
        url = _youtube_url(link, bool(videoid))
        try:
            info = await _extract(url, bool(video), skip_download=True)
            direct = _direct_url(info)
            if not direct:
                raise RuntimeError("yt-dlp returned no direct media URL")
            _STREAM_CACHE[key] = (time.monotonic(), direct)
            _cleanup_cache()
            _log("info", "direct stream ready video=%s protocol=%s", video, info.get("protocol", "unknown"))
            return 1, direct
        except Exception as exc:
            text = str(exc)
            if ("age-restricted" in text.lower() or "confirm your age" in text.lower()) and not _cookie_file():
                text = "YouTube requires an authenticated age-verified session; configure YOUTUBE_COOKIES_B64."
            _log("error", "stream_url failed: %s", text[:500])
            return 0, text

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

    async def video(self, link, videoid=None):
        return await self.stream_url(link, videoid=videoid, video=True)

    async def download(self, link, mystic, video=None, videoid=None, songaudio=None, songvideo=None, format_id=None, title=None):
        url = _youtube_url(link, bool(videoid))
        if songaudio:
            fmt = format_id or "bestaudio[ext=m4a]/bestaudio/best"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s"), "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}]}
        elif songvideo or video:
            fmt = format_id or "bv*[height<=720]+ba/b[height<=720]/best"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s"), "merge_output_format": "mp4"}
        else:
            fmt = format_id or "bestaudio[ext=m4a]/bestaudio/best"
            extra = {"outtmpl": str(_DOWNLOAD_DIR / "%(id)s_%(format_id)s.%(ext)s")}
        def run():
            last = None
            for client, pot in _client_profiles():
                try:
                    opts = _common_options(client, pot, format=fmt, **extra)
                    with YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        prepared = Path(ydl.prepare_filename(info))
                        if prepared.is_file() and prepared.stat().st_size > 10240:
                            return str(prepared), True
                        for candidate in _DOWNLOAD_DIR.glob(f"{info.get('id','')}*"):
                            if candidate.is_file() and candidate.stat().st_size > 10240:
                                return str(candidate), True
                except Exception as exc:
                    last = exc
                    _log("warning", "download client=%s failed: %s", client or "default", str(exc)[:300])
            raise RuntimeError(f"all YouTube download profiles failed: {last}") from last
        try:
            return await asyncio.wait_for(asyncio.to_thread(run), timeout=_DOWNLOAD_TIMEOUT)
        except asyncio.TimeoutError as exc:
            _log("error", "YouTube download timed out after %.0fs", _DOWNLOAD_TIMEOUT)
            raise RuntimeError(f"YouTube download timed out after {_DOWNLOAD_TIMEOUT:.0f}s") from exc


__all__ = ["YouTubeResilient"]
