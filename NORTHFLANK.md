# Tommy / Northflank deployment

## Service

Deploy the repository as a **Docker service** in Northflank. Use the Dockerfile in the repository and keep the service always running. Singapore is the preferred region for an India-focused bot.

## Required environment variables

- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `STRING_SESSIONS`
- `MONGO_DB_URI`
- `OWNER_ID`
- `LOGGER_ID`

## YouTube reliability variables

Optional:

- `PROXY_URL` — one stable HTTP(S) proxy used for both yt-dlp extraction and FFmpeg playback. Do not rotate the proxy during a track.
- `YOUTUBE_COOKIES_B64` — base64-encoded Netscape-format YouTube cookies. Keep this as a Northflank secret; never commit the cookie file.
- `YOUTUBE_COOKIES` — raw Netscape-format cookies, also supplied only as a secret.
- `WPC_BROWSER_PATH` — normally unnecessary; the Docker image includes Chromium and auto-detects it.

The bot uses the WebPoClient provider (`yt-dlp-getpot-wpc`) to obtain PO tokens when yt-dlp requests them. YouTube currently recommends a PO-token provider for clients whose Google Video Server requests require PO tokens. See the current yt-dlp PO Token Guide for details.

## Playback design

- `mweb` is tried first, followed by `web_safari`, `web`, and `tv`.
- yt-dlp EJS support and a JavaScript runtime are installed in the image.
- Audio uses `bestaudio/best/18`.
- Video playback uses a single audio+video format capped at 720p for stable PyTgCalls playback instead of returning separate video/audio URLs and accidentally selecting video-only.
- Direct stream URLs are cached briefly and the next queued YouTube item is prefetched in the background.
- If direct streaming fails, the engine falls back to a full yt-dlp download.
- Proxy and cookie handling are shared by extraction and download paths.

## Important

No YouTube extractor can guarantee permanent immunity from YouTube-side rate limits, IP blocks, format changes, or PO-token changes. The engine is designed to recover by changing supported client profiles and falling back to download mode. Keep request rates reasonable.
