# Spoolman MCP GitHub OAuth facade

A **separate** FastMCP 4.2.2 service. It does not alter the existing protected Spoolman MCP container. GitHub OAuth is converted to MCP OAuth 2.1 (DCR and PKCE), with local JWTs and encrypted persistent client/token storage. The original Pangolin resource **keeps its authentication enabled**.

The OAuth facade itself must have a **different hostname** that allows public access to OAuth discovery/callback endpoints. That new resource uses the facade's own OAuth authentication, NOT Pangolin's browser login. All MCP tool calls need GitHub OAuth, and the facade checks the verified numeric GitHub user ID. An OAuth client request can never directly reach the existing protected MCP resource: only the facade's backend client can, using resource-scoped Pangolin token headers plus the MCP `X-API-Key`.

Default-deny tool policy: read-only Spoolman MCP tools are allowlisted; writes, deletions, settings changes and unknown tools are hidden AND blocked server-side.

See [instructions for Dockge and Pangolin](../docs/GITHUB_OAUTH_SETUP.md). Do not place real tokens or private network configuration in this public repository.

The new OAuth host's protected resource metadata, authorization server metadata and GitHub callback need HTTPS and must be forwarded without path rewrite. JWT signing key and `FASTMCP_HOME=/data` must remain persistent across restarts. The active signed-in user is revalidated against GitHub by the upstream verifier on each MCP request.

Not a promise of ChatGPT plan entitlement: custom MCP creation requires permission for the selected account/workspace. Live GitHub, Pangolin and ChatGPT login are operator acceptance tests, not CI claims.
