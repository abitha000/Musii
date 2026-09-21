FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DENO_INSTALL=/usr/local/deno \
    YOUTUBE_POT_PROVIDER_URL=http://127.0.0.1:4416 \
    TINI_SUBREAPER=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       aria2 \
       chromium \
       curl \
       ca-certificates \
       unzip \
       git \
       gcc \
       procps \
       tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p "$DENO_INSTALL" \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -sf "$DENO_INSTALL/bin/deno" /usr/local/bin/deno

# Build the official bgutil POT HTTP provider alongside Musii.
RUN git clone --depth 1 --branch 2.0.0 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server \
    && deno install --allow-scripts=npm:canvas --frozen \
    && chown -R root:root /opt/bgutil

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
