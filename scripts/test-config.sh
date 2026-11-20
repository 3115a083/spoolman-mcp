#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
entrypoint="./docker/entrypoint.sh"
check_fail() {
  label="$1"
  shift
  if "$@" > /dev/null 2>&1; then
    echo "FAIL: $label should be rejected" >&2
    exit 1
  fi
}
check_fail 'missing URL and key' env -u SPOOLMAN_URL -u MCP_PROXY_API_KEY sh "$entrypoint"
check_fail 'missing key' env SPOOLMAN_URL=http://localhost:7912 -u MCP_PROXY_API_KEY sh "$entrypoint"
check_fail 'short key' env SPOOLMAN_URL=http://localhost:7912 MCP_PROXY_API_KEY=short sh "$entrypoint"
check_fail 'placeholder key' env SPOOLMAN_URL=http://localhost:7912 MCP_PROXY_API_KEY=REPLACE_WITH_64_RANDOM_HEX_CHARACTERS sh "$entrypoint"
check_fail 'invalid URL' env SPOOLMAN_URL=file:///etc/passwd MCP_PROXY_API_KEY=012345678901234567890123456789ab sh "$entrypoint"
printf 'Entrypoint configuration rejection tests passed\n'
