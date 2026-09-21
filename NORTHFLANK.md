# Tommy / Northflank deployment

## Service

Deploy the repository as a **Docker service** in Northflank. Use the Dockerfile in the repository and keep the service always running.

## Required environment variables

- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `STRING_SESSIONS`
- `MONGO_DB_URI`
- `OWNER_ID`
- `LOGGER_ID`

## YouTube reliability variables

Recommended:

- `YOUTUBE_COOKIES_B64` — base64-encoded Netscape-format YouTube cookies. Store this only as a Northflank secret; never commit the cookie file.
- `YOUTUBE_COOKIES` — alternative raw Netscape-format cookies, also secret-only.

Optional:

- `YOUTUBE_COOKIES_FILE` — path to a mounted Netscape cookie file.
- `YOUTUBE_POT_PROVIDER_URL` — defaults to the local bgutil provider at `http://127.0.0.1:4416`.
- `YOUTUBE_POT_PROVIDER_ENABLED` — defaults to `1`; set to `0` only for debugging.
- `PROXY_URL` — one stable HTTP(S) proxy used for yt-dlp and FFmpeg playback. Do not rotate the proxy during a track.

## Playback design

- Musii uses the official `bgutil-ytdlp-pot-provider` HTTP provider locally inside the same container.
- `mweb + PO token` is the first YouTube extraction path.
- Authenticated cookies are supplied to yt-dlp for age-restricted/account-gated videos.
- yt-dlp EJS support and Deno are installed in the image.
- Audio prefers direct HTTP M4A streams to reduce HLS buffering and reconnection problems.
- Direct stream URLs are cached briefly and the next queued YouTube item is prefetched.
- If direct streaming fails, the engine can fall back to yt-dlp download mode.
- Tini runs as PID 1/subreaper so child processes are reaped cleanly.

## Cookies

Export cookies from an authorized YouTube account in Netscape format and put the base64 value into `YOUTUBE_COOKIES_B64`. Cookies can expire or be invalidated by YouTube, so replace the secret when YouTube rejects the session.

## Important

A PO-token provider does not guarantee immunity from YouTube rate limits, IP blocks, bot checks, or account restrictions. The provider is an automatic token mechanism, not a permanent bypass. Keep request rates reasonable and use a valid authenticated session where YouTube requires one.
