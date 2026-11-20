# Security and ChatGPT access

This gateway exposes the complete upstream Spoolman MCP API, **including destructive write and delete tools**. An authorized MCP client can alter inventory. Protect API keys as credentials with full access.

## Boundaries

1. Keep the Pangolin resource login and authorization ENABLED.
2. Newt forwards the complete path to the HTTP gateway on TrueNAS. Bind its Docker host port to `127.0.0.1` when Newt shares the host network.
3. The MCP gateway also requires `MCP_PROXY_API_KEY` on `/mcp` using `X-API-Key`. Generate with `openssl rand -hex 32`. The key must be at least 32 characters.
4. The `/ping` endpoint needs no key by design. Never expose the gateway directly to the public Internet.
5. Only the existing Spoolman HTTP API is accessed. No Spoolman database or storage volumes are mounted.

Store secrets only in private Dockge runtime config. Do not paste them into Git, URLs, screenshots or logs. Docker administrators can inspect container environment variables. Scope Pangolin machine tokens narrowly to the MCP resource, and rotate all credentials upon exposure.

There is **no server-enforced read-only policy**. Client-side confirmation is insufficient to create an authorization boundary.

## Direct ChatGPT is not yet supported behind Pangolin login

ChatGPT cannot supply arbitrary Pangolin access-token headers (nor `X-API-Key`) on an external MCP connection. Pangolin browser sessions are not an MCP OAuth 2.1 flow. Merely adding the public protected URL to ChatGPT does not authenticate.

Do NOT disable Pangolin auth, bypass `/mcp`, or put service tokens into query parameters.

Two future architectures require separate integration and live validation:
- OpenAI Secure MCP Tunnel can reach a private gateway over an **independent outbound tunnel**. Pangolin remains protected for its own URL; the tunnel does not route through Pangolin and needs its own access review.
- An audited OAuth 2.1 authorization broker may permit direct ChatGPT integration only if Pangolin's enforcement and discovery/token flows remain compatible. Pangolin's ordinary login redirect by itself is not sufficient.

ChatGPT account and workspace permissions may also limit custom MCP servers.

## Checks

- Missing, invalid, short and placeholder secrets are rejected before process startup.
- CI checks that anonymous `/mcp` is rejected and authenticated MCP initialization succeeds.
- No direct inbound public port, Docker socket, privileged process, or Spoolman data mount.
- Upstream commit and direct proxy version are fixed, but the Node base image and transitive dependency resolution are not immutable.
- Real Pangolin, Newt, TrueNAS and ChatGPT access remains to be tested by the operator.
