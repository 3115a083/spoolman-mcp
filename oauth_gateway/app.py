"""MCP OAuth frontend. Does not modify the existing protected MCP service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider, GitHubTokenVerifier
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient

# Default deny. Users with OAuth tokens can only list/call the following tools.
READ_ONLY_TOOLS = frozenset({
    "spoolman_list_vendors", "spoolman_get_vendor",
    "spoolman_list_filaments", "spoolman_get_filament",
    "spoolman_list_spools", "spoolman_get_spool",
    "spoolman_get_all_settings", "spoolman_get_setting",
    "spoolman_list_fields", "spoolman_list_materials",
    "spoolman_list_locations", "spoolman_list_lot_numbers",
    "spoolman_list_article_numbers", "spoolman_export_spools",
    "spoolman_export_filaments", "spoolman_export_vendors",
    "spoolman_get_info", "spoolman_health_check",
})


def _require(name: str, minimum: int = 1) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) < minimum or value.upper().startswith(("REPLACE_", "CHANGE_ME", "YOUR_", "EXAMPLE_")):
        raise ValueError(f"{name} must be configured (minimum {minimum} characters)")
    return value


def _validate_url(name: str, value: str, *, mcp_path: bool) -> str:
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password or
            url.fragment or url.query or (mcp_path and url.path != "/mcp") or
            (not mcp_path and url.path not in ("", "/"))):
        raise ValueError(f"{name} must be a valid HTTPS URL with the expected path")
    return value.rstrip("/")


@dataclass(frozen=True)
class Config:
    public_url: str
    backend_url: str
    github_client_id: str
    github_client_secret: str
    github_owner_id: str
    signing_key: str
    pangolin_token_id: str
    pangolin_token: str
    backend_api_key: str

    @classmethod
    def from_env(cls) -> "Config":
        public_url = _validate_url("OAUTH_PUBLIC_URL", _require("OAUTH_PUBLIC_URL"), mcp_path=False)
        backend_url = _validate_url("MCP_BACKEND_URL", _require("MCP_BACKEND_URL"), mcp_path=True)
        if urlsplit(public_url).netloc == urlsplit(backend_url).netloc:
            raise ValueError("The OAuth endpoint must have its own hostname, separate from the Pangolin-protected MCP endpoint")
        owner = _require("GITHUB_OWNER_ID")
        if not owner.isdecimal() or int(owner) < 1:
            raise ValueError("GITHUB_OWNER_ID must be a positive numeric GitHub account ID")
        return cls(
            public_url=public_url,
            backend_url=backend_url,
            github_client_id=_require("GITHUB_CLIENT_ID"),
            github_client_secret=_require("GITHUB_CLIENT_SECRET", 20),
            github_owner_id=owner,
            signing_key=_require("OAUTH_JWT_SIGNING_KEY", 32),
            pangolin_token_id=_require("PANGOLIN_ACCESS_TOKEN_ID"),
            pangolin_token=_require("PANGOLIN_ACCESS_TOKEN", 20),
            backend_api_key=_require("MCP_BACKEND_API_KEY", 32),
        )


class OwnerOnlyGitHubVerifier(GitHubTokenVerifier):
    """Verify upstream GitHub identity against a stable numeric account ID."""

    def __init__(self, owner_id: str) -> None:
        super().__init__(required_scopes=["user"], cache_ttl_seconds=None)
        self.owner_id = owner_id

    async def verify_token(self, token: str) -> AccessToken | None:
        checked = await super().verify_token(token)
        if checked is None or checked.subject != self.owner_id:
            return None
        return checked


class ReadOnlyPolicy(Middleware):
    """Hide unauthorized tools AND block direct invocations by guessed name."""

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        tools = await call_next(context)
        return [tool for tool in tools if tool.name in READ_ONLY_TOOLS]

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        if getattr(context.message, "name", None) not in READ_ONLY_TOOLS:
            raise AuthorizationError("Tool not allowed by read-only policy")
        return await call_next(context)


def build_server(cfg: Config) -> FastMCPProxy:
    auth = GitHubProvider(
        client_id=cfg.github_client_id,
        client_secret=cfg.github_client_secret,
        base_url=cfg.public_url,
        jwt_signing_key=cfg.signing_key,
        required_scopes=["user"],
        require_authorization_consent=True,
    )
    # GitHubProvider verifies all GitHub accounts by default. Replace the
    # upstream verifier, used both during token issue and for every request.
    # FastMCP is version-pinned because this is an internal integration point.
    if not isinstance(auth._token_validator, GitHubTokenVerifier):
        raise RuntimeError("FastMCP GitHub verifier changed: refusing to start")
    auth._token_validator = OwnerOnlyGitHubVerifier(cfg.github_owner_id)

    def backend_client() -> ProxyClient:
        transport = StreamableHttpTransport(
            cfg.backend_url,
            headers={
                "P-Access-Token-Id": cfg.pangolin_token_id,
                "P-Access-Token": cfg.pangolin_token,
                "X-API-Key": cfg.backend_api_key,
            },
        )
        # Crucial: do not pass ChatGPT's Authorization header to Pangolin or
        # leak OAuth bearer tokens to the upstream MCP gateway.
        return ProxyClient(transport, forward_incoming_headers=False)

    proxy = FastMCPProxy(client_factory=backend_client, name="Spoolman OAuth Gateway", auth=auth)
    proxy.add_middleware(ReadOnlyPolicy())
    return proxy


def main() -> None:
    cfg = Config.from_env()
    server = build_server(cfg)
    server.run(transport="http", host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
