# Dockge setup: GitHub OAuth with Pangolin protection retained

## Architecture

```text
OAuth-compatible MCP client
     | public HTTPS, OAuth 2.1 authorization + GitHub account ID restriction
Pangolin: NEW oauth-resource (no Pangolin browser SSO on this new resource)
     | Newt (same NAS host network) -> 127.0.0.1:18789
spoolman-oauth (new stack: GitHubProvider + FastMCPProxy)
     | outbound HTTPS, P-Access-Token-Id + P-Access-Token + X-API-Key
Pangolin: EXISTING protected MCP resource (Pangolin authentication still ON)
     | Newt -> 127.0.0.1:18788
existing spoolman-mcp stack -> existing Spoolman app
```

**Why a second public resource?** OAuth discovery, token exchanges, and GitHub callbacks must be reachable before the OAuth client has a token. Pangolin browser SSO on the same hostname blocks that flow. The new resource is protected at the application layer by GitHub OAuth and a strict user ID allowlist. Never disable the existing resource's Pangolin login or remove its token enforcement. Never add a bypass on the existing `/mcp` path.

## 1. GitHub OAuth application

At https://github.com/settings/developers -> OAuth Apps -> New OAuth App:

- Application name: Spoolman MCP OAuth
- Homepage: `https://oauth-mcp.example.com`
- Authorization callback: `https://oauth-mcp.example.com/auth/callback`
- Copy the Client ID and generate a Client Secret. Use your actual new domain consistently, with HTTPS.
- Do not request repository access. Restrict the gateway to your numeric GitHub user ID from `https://api.github.com/user` when authenticated. No username-based trust.

## 2. Pangolin

Create a **second** Public HTTP Resource with another hostname, for example `oauth-mcp.example.com`, linked to the existing host-network Newt site. Target HTTP `127.0.0.1:18789`; forward all paths and query strings unchanged, enable HTTPS. **The new resource must not use Pangolin's browser SSO** because OAuth flows require unauthenticated access to discovery and callback paths. Application-level OAuth on `/mcp` remains compulsory.

Do **not** alter the existing protected resource (e.g. `protected-mcp.example.com`), its Pangolin auth policy, access-token policy, or its `127.0.0.1:18788` target.

## 3. Existing Pangolin resource access token

Create or reuse a short-lived, narrowly resource-scoped **Pangolin Access Token** for the existing protected MCP resource. Record its ID and secret privately. The existing `MCP_PROXY_API_KEY` is a separate required secret; supply it as `MCP_BACKEND_API_KEY` to the facade.

## 4. Dockge deployment

Create a new stack directory with the reviewed repository revision. Keep the original Dockge stack running. Copy `dockge-oauth.compose.yaml` to the new stack's `compose.yaml` and configure its variables using a private `.env` or Dockge's private stack environment.

Alternatively use a build from a reviewed immutable Git commit using:

```yaml
build:
  context: https://github.com/3115a083/spoolman-mcp.git#REVIEWED_OAUTH_COMMIT
  dockerfile: oauth_gateway/Dockerfile
```

Required variables (names only here; real values remain on NAS): `OAUTH_PUBLIC_URL`, `MCP_BACKEND_URL`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_OWNER_ID`, `OAUTH_JWT_SIGNING_KEY`, `PANGOLIN_ACCESS_TOKEN_ID`, `PANGOLIN_ACCESS_TOKEN`, `MCP_BACKEND_API_KEY`.

Generate the signing key independently: `openssl rand -hex 32`. The MCP backend API key is the one already configured in the old MCP container. Store all secrets outside Git; protect the Dockge stack and Docker socket. Persist named volume `oauth_state`. Run only one OAuth replica (its default encrypted file store is not multi-node). Never re-create the volume casually, or clients may need reauthorization.

Default binding: `127.0.0.1:18789`. No local Spoolman database mounts or additional publicly accessible container ports.

## 5. Acceptance tests

1. From outside, `GET https://oauth-mcp.example.com/.well-known/oauth-protected-resource` and `GET https://oauth-mcp.example.com/.well-known/oauth-authorization-server` return OAuth metadata; no Pangolin 401/login HTML for the *new* resource.
2. `POST https://oauth-mcp.example.com/mcp` without a bearer token must return an OAuth 401 challenge (not 200 or an HTML login).
3. Complete OAuth authorization through an MCP client; browser login redirects to GitHub and consent screen. Only the configured numeric GitHub user ID must be accepted. A different GitHub user must fail (no token usable for MCP).
4. As the authorized user, `tools/list` contains `spoolman_list_spools` but **not** `spoolman_delete_spool`, and direct calls to deletion are rejected. Live tests must not modify inventory.
5. Reboot/redeploy OAuth service; authorized clients and tokens persist (same signing key and `oauth_state`). Revoke the Pangolin machine token and verify the facade cannot access backend tools; restore only after successful denial.
6. Existing protected resource must still return a Pangolin 401 when accessed without its Pangolin token, regardless of the new facade's status.

**ChatGPT:** support for creating custom MCP servers is account/workspace dependent. If no Add Custom MCP option exists for the account, OAuth cannot override that limit. Do not expose tokens or disable the old resource as a workaround.
