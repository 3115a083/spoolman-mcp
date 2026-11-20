# One container, one hostname, GitHub OAuth

This variant is built on the earlier GitHub OAuth PR but **replaces the two-service architecture**. A single FastMCP HTTP server runs as PID 1. The upstream Disane87 Node MCP process is started through stdio **on demand**, not as a permanent proxy process. One published port, one container, a persistent OAuth data volume, no database mount.

## Critical Pangolin limitation

The existing resource `https://spoolman-mcp.example.com/mcp` is protected by Pangolin browser SSO and requires Pangolin-specific credentials. A remote ChatGPT MCP client **cannot** complete GitHub OAuth through that same public URL while Pangolin intercepts `/mcp`, `/.well-known/*`, `/authorize`, `/token`, and `/auth/callback` first. This cannot be solved inside this container.

This repository does **not** disable Pangolin authentication and does **not** add an authorization bypass.

For a fully working ChatGPT OAuth connection at this exact URL, one of the following changes must be separately authorized and reviewed:
- Make the Pangolin HTTP resource transport-only for the **OAuth-protected gateway**, so GitHub OAuth becomes the enforced authentication for MCP; or
- Implement a standards-compatible, trusted OAuth integration at Pangolin's edge, so it can admit OAuth Bearer tokens while enforcing its resource policies (not available as a documented stock Pangolin feature).

If Pangolin SSO must remain enforced on every request, keep the existing stack; ordinary ChatGPT custom MCP is **not reachable** through this URL. Local MCP clients able to present Pangolin credentials may still use Pangolin.

## GitHub OAuth app

Create an OAuth App in GitHub Developer Settings:

- Homepage: `https://spoolman-mcp.example.com`
- Authorization callback URL: `https://spoolman-mcp.example.com/auth/callback`
- Scopes requested by provider: `user` (no repositories).

The server allows only the configured numeric `GITHUB_OWNER_ID`, and only read-only MCP tools. The user ID is matched to a verified GitHub token, not a user-controlled request header.

## Deploy safely (Dockge on TrueNAS)

1. **Keep the current legacy stack running.** Create a separate test stack from this commit, using `compose.unified.yaml`. Set port to `18789`. Local test URL: `http://127.0.0.1:18789`.
2. Copy `.env.unified.example` into the private Dockge stack environment and fill all required values. Use your existing Spoolman API address for `SPOOLMAN_URL`. Keep `PUBLIC_URL` set to the same existing external hostname, without `/mcp`.
3. Generate one permanent signing key with `openssl rand -hex 32`, and keep `oauth_state` and the key across redeploys. Never put credentials in Git or URLs.
4. Deploy using an immutable reviewed commit in `build.context`. Check `/healthz`, `/.well-known/oauth-authorization-server`, and unauthorized `/mcp` on localhost.
5. **Do not switch the current Pangolin target yet.** To connect a standard OAuth client under the existing protected hostname, first resolve the edge-authentication conflict above. Switching the target alone will break the previously working API-key MCP access and will not make ChatGPT OAuth work.

### Local shell tests

```bash
curl -i http://127.0.0.1:18789/healthz
curl -i http://127.0.0.1:18789/.well-known/oauth-authorization-server
curl -i -X POST http://127.0.0.1:18789/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'
```

Expect HTTP 200 `ok` for health, HTTP 200 JSON metadata for OAuth, and HTTP 401 for /mcp without an OAuth token. These tests do not touch inventory.

## Runtime security

- One non-root container (UID 10001) with read-only root, no capabilities, no-new-privileges.
- Single port bound to NAS loopback, no Docker socket, no Spoolman database mount.
- FastMCP 4.2.2; upstream Spoolman MCP pinned to a Git commit.
- The Node process is started only for MCP component discovery/interaction, and exited when its session ends. This saves idle memory relative to a resident `mcp-proxy` process, but increases first-call latency.
- Resource limit: 384 MiB, 64 PIDs. Actual usage should be measured on TrueNAS and the limit adjusted if necessary.
- A small `/healthz` endpoint is unauthenticated at the application layer but never exposes secrets. Pangolin still guards public access when its resource auth is active.
- OAuth tokens and dynamic client registrations persist in `oauth_state`. Changing the signing key can invalidate sessions.
- Build-stage images and Python transitive dependencies are not yet fully digest/lockfile pinned. Audit before high-assurance deployment.

Note: the old `MCP_PROXY_API_KEY` is **not used** by this OAuth-only listener. Do not assume both historical authentication mechanisms are enforced here. Pangolin's existing auth controls are external and separate.
