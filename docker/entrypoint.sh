#!/bin/sh
set -eu

# Fail closed if required runtime configuration is absent or a placeholder.
if [ -z "${SPOOLMAN_URL:-}" ]; then
  echo "SPOOLMAN_URL is required" >&2
  exit 64
fi
case "$SPOOLMAN_URL" in
  http://*|https://*) ;;
  *) echo "SPOOLMAN_URL must start with http:// or https://" >&2; exit 64 ;;
esac
if [ -z "${MCP_PROXY_API_KEY:-}" ] || [ "${#MCP_PROXY_API_KEY}" -lt 32 ]; then
  echo "MCP_PROXY_API_KEY must be set to at least 32 characters" >&2
  exit 64
fi
case "$MCP_PROXY_API_KEY" in
  REPLACE_*|CHANGE_ME*|YOUR_*|example*)
    echo "Replace the example MCP_PROXY_API_KEY" >&2
    exit 64
    ;;
esac

# MCP_PROXY_API_KEY makes mcp-proxy require X-API-Key on /mcp.
# /ping is intentionally unauthenticated, so use localhost or a private subnet.
exec /app/proxy/node_modules/.bin/mcp-proxy \
  --server stream \
  --port 8080 \
  --maxBodySize 1048576 \
  --requestTimeout 30000 \
  --sessionIdleTimeout 300000 \
  --no-eventStore \
  -- node /app/spoolman/dist/index.js
