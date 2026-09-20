# All rights reserved.
#
# Tommy custom thumbnail renderer.
# The renderer keeps the original YouTube artwork as the source image,
# builds a blurred glassmorphic background from it, and places the sharp
# artwork inside the fixed Tommy artwork frame.

import hashlib
import os
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from py_yt import VideosSearch


_THUMB_CACHE = Path("cache/tommy_thumbnails")
_THUMB_CACHE.mkdir(parents=True, exist_ok=True)

_W, _H = 1280, 720


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _cover(image: Image.Image, size: Tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _rounded_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _paste_rounded(base: Image.Image, image: Image.Image, box, radius: int):
    x, y, w, h = box
    image = _cover(image, (w, h))
    mask = _rounded_mask((w, h), radius)
    base.paste(image, (x, y), mask)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    while text:
        text = text[:-1].rstrip()
        candidate = text + "…"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            return candidate
    return "…"


def _draw_glass(draw: ImageDraw.ImageDraw, box, radius, fill=(255, 255, 255, 30), outline=(255, 255, 255, 80), width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_waveform(draw: ImageDraw.ImageDraw):
    heights = [10, 18, 28, 14, 34, 48, 22, 62, 88, 42, 26, 18, 32, 20, 14, 30, 44, 24, 16, 26, 38, 54, 24, 14, 20, 34, 48, 30, 18, 26, 40, 62, 28, 18, 14, 24, 36, 50, 22, 16, 30, 46, 24, 18, 34, 52, 28, 18, 26]
    x = 650
    cy = 470
    for i, h in enumerate(heights):
        fill = (246, 212, 108, 220) if i < 11 else (220, 220, 220, 95)
        draw.rounded_rectangle((x, cy - h // 2, x + 7, cy + h // 2), radius=4, fill=fill)
        x += 13


def _draw_controls(draw: ImageDraw.ImageDraw):
    y = 600
    # Shuffle
    draw.line((700, y - 12, 712, y - 2, 724, y - 14), fill=(255, 255, 255, 225), width=3)
    draw.line((700, y + 12, 712, y + 2, 724, y + 14), fill=(255, 255, 255, 225), width=3)
    # Previous
    draw.polygon([(780, y), (798, y - 14), (798, y + 14)], fill=(255, 255, 255, 235))
    draw.rectangle((772, y - 14, 777, y + 14), fill=(255, 255, 255, 235))
    # Pause circle
    draw.ellipse((845, y - 38, 921, y + 38), fill=(255, 255, 255, 245))
    draw.rounded_rectangle((871, y - 14, 878, y + 14), radius=3, fill=(35, 35, 35, 255))
    draw.rounded_rectangle((889, y - 14, 896, y + 14), radius=3, fill=(35, 35, 35, 255))
    # Next
    draw.polygon([(1000, y), (982, y - 14), (982, y + 14)], fill=(255, 255, 255, 235))
    draw.rectangle((1008, y - 14, 1013, y + 14), fill=(255, 255, 255, 235))
    # Repeat
    draw.arc((1050, y - 14, 1080, y + 14), start=200, end=40, fill=(255, 255, 255, 225), width=3)
    draw.polygon([(1079, y - 14), (1070, y - 14), (1077, y - 5)], fill=(255, 255, 255, 225))


def _render_template(artwork: Image.Image, title: str, artist: str) -> Image.Image:
    # The same YouTube artwork becomes the ambient background and the sharp
    # artwork panel, matching the Tommy glassmorphic concept.
    bg = _cover(artwork, (_W, _H)).filter(ImageFilter.GaussianBlur(34))
    bg = ImageEnhance.Brightness(bg).enhance(0.48)
    bg = ImageEnhance.Saturation(bg).enhance(0.72).convert("RGBA")
    canvas = Image.alpha_composite(bg, Image.new("RGBA", (_W, _H), (8, 10, 16, 90)))
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Main glassmorphic card.
    card = (38, 36, 1242, 684)
    _draw_glass(draw, card, 36, fill=(10, 14, 22, 105), outline=(255, 255, 255, 85), width=2)
    draw.rounded_rectangle((50, 50, 1230, 670), radius=30, outline=(255, 255, 255, 28), width=1)

    # Sharp YouTube artwork inside the fixed glass frame.
    art_box = (68, 112, 590, 608)
    _paste_rounded(canvas, artwork, (art_box[0], art_box[1], art_box[2] - art_box[0], art_box[3] - art_box[1]), 28)
    draw = ImageDraw.Draw(canvas, "RGBA")
    _draw_glass(draw, art_box, 28, fill=(255, 255, 255, 12), outline=(255, 255, 255, 90), width=2)

    # Fixed labels/branding.
    draw.text((92, 138), "A", font=_font(19), fill=(255, 255, 255, 220))
    draw.text((92, 164), "MUSIC FOR EVERY MOOD", font=_font(15), fill=(255, 255, 255, 175))
    draw.text((1000, 118), "││ TOMMY", font=_font(42, True), fill=(255, 255, 255, 245), anchor="la")
    draw.text((1000, 166), "MUSIC FOR EVERY MOOD", font=_font(14), fill=(255, 255, 255, 165), anchor="la")

    # Now-playing pill.
    pill = (650, 218, 910, 276)
    _draw_glass(draw, pill, 28, fill=(255, 255, 255, 28), outline=(255, 255, 255, 70), width=1)
    draw.text((678, 231), "♫  NOW PLAYING", font=_font(22, True), fill=(255, 255, 255, 235))

    # Dynamic metadata.
    title_font = _font(35, True)
    artist_font = _font(24)
    draw.text((650, 315), _fit_text(draw, title or "Now Playing", title_font, 540), font=title_font, fill=(255, 255, 255, 245))
    draw.text((650, 370), _fit_text(draw, artist or "YouTube", artist_font, 520), font=artist_font, fill=(235, 235, 235, 205))

    # Progress line and labels.
    draw.rounded_rectangle((650, 425, 1185, 431), radius=3, fill=(255, 255, 255, 100))
    draw.ellipse((650, 418, 664, 432), fill=(255, 255, 255, 245))
    draw.ellipse((914, 418, 928, 432), fill=(255, 255, 255, 245))
    draw.text((650, 443), "0:00", font=_font(17), fill=(255, 255, 255, 175))
    draw.text((1145, 443), "—:—", font=_font(17), fill=(255, 255, 255, 175))

    _draw_waveform(draw)
    _draw_controls(draw)

    # Footer.
    draw.line((650, 660, 760, 660), fill=(255, 255, 255, 70), width=1)
    draw.text((782, 649), "GOOD MUSIC  •  BETTER PEOPLE", font=_font(14), fill=(255, 255, 255, 165))
    draw.line((1110, 660, 1220, 660), fill=(255, 255, 255, 70), width=1)
    return canvas.convert("RGB")


async def _download_image(url: str) -> Optional[Image.Image]:
    timeout = aiohttp.ClientTimeout(total=15, connect=5)
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.read()
                if not data:
                    return None
        return Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None


async def _resolve_thumbnail(videoid: str, thumb: Optional[str] = None):
    if thumb:
        return thumb, "Now Playing", "YouTube"

    try:
        query = f"https://www.youtube.com/watch?v={videoid}"
        results = VideosSearch(query, limit=1)
        found = (await results.next()).get("result", [])
        if found:
            result = found[0]
            thumbnails = result.get("thumbnails") or []
            thumbnail = thumbnails[0].get("url", "") if thumbnails else ""
            title = result.get("title") or "Now Playing"
            channel = result.get("channel", {}) or {}
            artist = channel.get("name") or result.get("author") or "YouTube"
            if thumbnail:
                return thumbnail.split("?")[0], title, artist
    except Exception:
        pass

    return f"https://img.youtube.com/vi/{videoid}/maxresdefault.jpg", "Now Playing", "YouTube"


async def gen_thumb(videoid, thumb=None):
    """Return a locally rendered Tommy glassmorphic thumbnail for Telegram."""
    source_url, title, artist = await _resolve_thumbnail(videoid, thumb)
    cache_key = hashlib.sha256(f"{videoid}|{source_url}".encode()).hexdigest()[:24]
    output = _THUMB_CACHE / f"{cache_key}.jpg"

    if output.exists() and output.stat().st_size > 4096:
        return str(output)

    artwork = await _download_image(source_url)
    if artwork is None:
        # Safe fallback to the old raw YouTube thumbnail behavior.
        return source_url

    try:
        rendered = _render_template(artwork, title, artist)
        rendered.save(output, "JPEG", quality=92, optimize=True, progressive=True)
        return str(output)
    except Exception:
        return source_url


async def gen_qthumb(vidid, thumb=None):
    # Keep the raw YouTube thumbnail behavior for video-stream internals.
    if thumb:
        return thumb
    try:
        query = f"https://www.youtube.com/watch?v={vidid}"
        results = VideosSearch(query, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail
    except Exception:
        return f"https://img.youtube.com/vi/{vidid}/maxresdefault.jpg"
