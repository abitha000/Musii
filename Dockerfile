FROM python:3.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DENO_INSTALL=/usr/local/deno

# Runtime tools required by Tommy: FFmpeg for media, aria2 for resilient
# downloads, Chromium for the WPC PO-token provider, and Node/Deno for
# yt-dlp's current JavaScript/EJS challenge solving.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       aria2 \
       chromium \
       curl \
       ca-certificates \
       git \
       gcc \
       procps \
       tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Deno as an additional yt-dlp JS runtime. Keep it outside the app
# tree so deployments cannot accidentally overwrite it.
RUN mkdir -p "$DENO_INSTALL" \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -sf "$DENO_INSTALL/bin/deno" /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt ./

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# Runtime directories. Cookie files must be supplied as deployment secrets or
# mounted files; never commit real YouTube cookies to Git.
RUN mkdir -p /app/downloads /app/cache/tommy_thumbnails /app/cookies \
    && chmod 755 /app/downloads /app/cache /app/cache/tommy_thumbnails /app/cookies

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "VenomX"]
