#!/bin/sh
set -eu

# A local Deno PO-token provider is too memory-heavy for the 256 MB
# Northflank container. Keep PO-token support optional via an external URL.
if [ "${YOUTUBE_POT_PROVIDER_ENABLED:-0}" = "1" ] && [ -z "${YOUTUBE_POT_PROVIDER_URL:-}" ]; then
  echo "YOUTUBE_POT_PROVIDER_ENABLED=1 requires YOUTUBE_POT_PROVIDER_URL"
  exit 1
fi

exec "$@"
