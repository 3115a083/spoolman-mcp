#!/bin/sh
set -eu
IMAGE="${1:-spoolman-mcp:unified-test}"
PORT="${TEST_PORT:-18789}"
NAME="spoolman-unified-ci-$$"
TMP=$(mktemp)
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -f "$TMP"; }
trap cleanup EXIT INT TERM
if docker run --rm "$IMAGE" > "$TMP" 2>&1; then
  echo "FAIL: missing secrets did not prevent startup" >&2
  exit 1
fi
docker run -d --name "$NAME" \
  -p "127.0.0.1:$PORT:8080" \
  --read-only --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges \
  --memory=384m --pids-limit=64 \
  --tmpfs /tmp:rw,nosuid,noexec,size=32m \
  --tmpfs /data:rw,nosuid,uid=10001,gid=10001,mode=0700 \
  -e PUBLIC_URL=https://mcp.example.com \
  -e SPOOLMAN_URL=http://127.0.0.1:7912 \
  -e GITHUB_CLIENT_ID=test-client \
  -e GITHUB_CLIENT_SECRET=test-client-secret-with-20-chars \
  -e GITHUB_OWNER_ID=123456 \
  -e OAUTH_JWT_SIGNING_KEY=ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss \
  "$IMAGE" >/dev/null
ready=0
i=0
while [ "$i" -lt 45 ]; do
  if curl --fail --silent "http://127.0.0.1:$PORT/healthz" >/dev/null; then ready=1; break; fi
  i=$((i+1)); sleep 1
done
if [ "$ready" != 1 ]; then
  docker logs "$NAME" >&2
  echo "FAIL: unified service did not start" >&2
  exit 1
fi
status=$(curl --silent -o "$TMP" -w '%{http_code}' \
  -X POST "http://127.0.0.1:$PORT/MCP" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}')
case "$status" in 401|403) ;; *) cat "$TMP" >&2; echo "FAIL: /MCP returned $status without OAuth token" >&2; exit 1;; esac
status=$(curl --silent -o "$TMP" -w '%{http_code}' "http://127.0.0.1:$PORT/.well-known/oauth-authorization-server/auth")
if [ "$status" != 200 ] || ! grep -q 'authorization_endpoint' "$TMP"; then
  cat "$TMP" >&2
  echo "FAIL: OAuth discovery ($status)" >&2
  exit 1
fi
# Check that the bundled Disane87 Node MCP server can be started on demand.
# This only lists tool schemas and does not contact or modify Spoolman inventory.
docker exec -i "$NAME" python - <<'PYTEST'
import asyncio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

async def check():
    transport = StdioTransport(
        command="node",
        args=["/app/spoolman/dist/index.js"],
        env={"SPOOLMAN_URL": "http://127.0.0.1:7912"},
        keep_alive=False,
    )
    async with Client(transport, mode="legacy") as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert "spoolman_list_spools" in names, names
asyncio.run(check())
PYTEST

resource_status=$(curl --silent -o "$TMP" -w '%{http_code}' "http://127.0.0.1:$PORT/.well-known/oauth-protected-resource/MCP")
if [ "$resource_status" != 200 ] || ! grep -q 'https://mcp.example.com/MCP' "$TMP"; then
  cat "$TMP" >&2
  echo "FAIL: OAuth MCP protected resource metadata ($resource_status)" >&2
  exit 1
fi
echo "PASS: /MCP with OAuth /auth, 384 MiB, bearer 401 and bundled Node tools"
