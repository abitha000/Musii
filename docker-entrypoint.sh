#!/bin/sh
set -eu

# Start the local bgutil PO-token server. It stays private inside the container.
if [ "${YOUTUBE_POT_PROVIDER_ENABLED:-1}" = "1" ]; then
  deno run \
    --allow-env \
    --allow-net \
    --allow-ffi=/opt/bgutil/server/node_modules \
    --allow-read=/opt/bgutil/server/node_modules \
    /opt/bgutil/server/src/main.ts \
    --host 127.0.0.1 \
    --port 4416 >/tmp/bgutil-pot.log 2>&1 &

  POT_PID=$!
  i=0
  while [ "$i" -lt 30 ]; do
    if ! kill -0 "$POT_PID" 2>/dev/null; then
      echo "bgutil PO-token provider exited unexpectedly"
      cat /tmp/bgutil-pot.log || true
      exit 1
    fi
    if curl -fsS http://127.0.0.1:4416/ >/dev/null 2>&1 || curl -fsS http://127.0.0.1:4416/ping >/dev/null 2>&1; then
      break
    fi
    i=$((i + 1))
    sleep 1
  done

  if [ "$i" -ge 30 ]; then
    echo "bgutil PO-token provider did not become ready"
    cat /tmp/bgutil-pot.log || true
    exit 1
  fi
fi

exec "$@"
