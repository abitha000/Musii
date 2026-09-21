FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    YOUTUBE_POT_PROVIDER_ENABLED=0 \
    TINI_SUBREAPER=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       aria2 \
       chromium \
       ca-certificates \
       unzip \
       procps \
       tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python --version \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .
COPY docker-entrypoint.sh /usr/local/bin/musii-entrypoint

RUN chmod +x /usr/local/bin/musii-entrypoint \
    && mkdir -p /app/downloads /app/cache/tommy_thumbnails /app/cookies \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin tommy \
    && chown -R tommy:tommy /app /tmp

USER tommy

ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/local/bin/musii-entrypoint"]
CMD ["python3", "-m", "VenomX"]
