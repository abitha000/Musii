FROM python:3.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DENO_INSTALL=/usr/local/deno

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

WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/downloads /app/cache/tommy_thumbnails /app/cookies \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin tommy \
    && chown -R tommy:tommy /app /tmp

USER tommy

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "VenomX"]
