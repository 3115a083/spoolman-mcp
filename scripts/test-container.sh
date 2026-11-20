#!/bin/sh
set -eu
IMAGE="${1:-spoolman-mcp:test}"
PORT="${TEST_PORT:-18788}"
NAME="spoolman-mcp-ci-$$"
KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
RESPONSE=$(mktemp)
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -f "$RESPONSE"; }
trap cleanup EXIT INT TERM

docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8080" \
  -e SPOOLMAN_URL=http://127.0.0.1:30590 \
  -e MCP_PROXY_API_KEY="$KEY" \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,noexec,size=32m \
  "$IMAGE" >/dev/null

ready=0
i=0
while [ "$i" -lt 30 ]; do
  if curl --silent --fail "http://127.0.0.1:$PORT/ping" >/dev/null; then ready=1; break; fi
  i=$((i+1))
  sleep 1
done
if [ "$ready" != 1 ]; then
  docker logs "$NAME" >&2
  echo 'FAIL: service did not become ready' >&2
  exit 1
fi

body='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}'
status=$(curl --silent -o "$RESPONSE" -w '%{http_code}' \
  -X POST "http://127.0.0.1:$PORT/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data "$body")
case "$status" in 401|403) ;; *) echo "FAIL: unauthenticated /mcp returned HTTP $status" >&2; exit 1;; esac

status=$(curl --silent -o "$RESPONSE" -w '%{http_code}' \
  -X POST "http://127.0.0.1:$PORT/mcp" \
  -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data "$body")
case "$status" in 200) ;; *) cat "$RESPONSE" >&2; echo "FAIL: authenticated initialize returned HTTP $status" >&2; exit 1;; esac
printf 'Container auth and MCP initialization smoke tests passed\n'
