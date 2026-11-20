"""Single-listener GitHub OAuth gateway for the upstream Spoolman MCP stdio server.

The upstream Node process starts only when an MCP client needs a tool or
discovery call. No standing mcp-proxy, extra listener, or API-key bridge.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider, GitHubTokenVerifier
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

UPSTREAM_SCRIPT = "/app/spoolman/dist/index.js"
MCP_PATH = "/MCP"
OAUTH_PATH = "/auth"

# Server-side allowlist, even when a client guesses a forbidden tool name.
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
    if len(value) < minimum or value.upper().startswith(
        ("REPLACE_", "CHANGE_ME", "YOUR_", "EXAMPLE_")
    ):
        raise ValueError(f"{name} missing or invalid (minimum {minimum} characters)")
    return value


def _validate_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("PUBLIC_URL must be a HTTPS origin with no URL path")
    return value.rstrip("/")


def _validate_spoolman_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("SPOOLMAN_URL must be a HTTP(S) origin with no URL path")
    return value.rstrip("/")


@dataclass(frozen=True)
class Config:
    public_url: str
    spoolman_url: str
    github_client_id: str
    github_client_secret: str
    github_owner_id: str
    signing_key: str

    @classmethod
    def from_env(cls) -> "Config":
        owner_id = _require("GITHUB_OWNER_ID")
        if not owner_id.isdecimal() or int(owner_id) < 1:
            raise ValueError("GITHUB_OWNER_ID must be a positive numeric GitHub user ID")
        return cls(
            public_url=_validate_origin(_require("PUBLIC_URL")),
            spoolman_url=_validate_spoolman_url(_require("SPOOLMAN_URL")),
            github_client_id=_require("GITHUB_CLIENT_ID"),
            github_client_secret=_require("GITHUB_CLIENT_SECRET", 20),
            github_owner_id=owner_id,
            signing_key=_require("OAUTH_JWT_SIGNING_KEY", 32),
        )


class OwnerOnlyGitHubVerifier(GitHubTokenVerifier):
    """Verify GitHub identity by immutable numeric ID, not user-supplied name."""

    def __init__(self, owner_id: str) -> None:
        super().__init__(required_scopes=["user"], cache_ttl_seconds=None)
        self.owner_id = owner_id

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await super().verify_token(token)
        if verified is None or verified.subject != self.owner_id:
            return None
        return verified


class PathScopedGitHubProvider(GitHubProvider):
    """Keep OAuth operations under /auth, serving RFC metadata at /.well-known.

    FastMCP's built-in OAuth routes use origin-root paths even if base_url
    contains a path. Remap route registrations to match their advertised URLs.
    This must remain covered by integration tests when updating FastMCP.
    """

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        if mcp_path != MCP_PATH:
            raise RuntimeError("Unexpected MCP path: refusing to expose OAuth routes")
        routes = super().get_routes(mcp_path)
        scoped = []
        for route in routes:
            if not isinstance(route, Route):
                raise RuntimeError("Unexpected OAuth route type; refusing to start")
            if route.path == "/.well-known/oauth-authorization-server":
                path = "/.well-known/oauth-authorization-server/auth"
            elif route.path.startswith("/.well-known/"):
                # RFC 9728 must remain at the domain root for MCP discovery.
                path = route.path
            else:
                path = f"{OAUTH_PATH}{route.path}"
            scoped.append(Route(
                path=path,
                endpoint=route.endpoint,
                methods=list(route.methods) if route.methods is not None else None,
                name=route.name,
                include_in_schema=route.include_in_schema,
            ))
        return scoped


class ReadOnlyPolicy(Middleware):
    async def on_list_tools(self, context: MiddlewareContext, call_next):
        tools = await call_next(context)
        return [tool for tool in tools if tool.name in READ_ONLY_TOOLS]

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        if getattr(context.message, "name", None) not in READ_ONLY_TOOLS:
            raise AuthorizationError("Tool forbidden by read-only policy")
        return await call_next(context)


def build_server(cfg: Config) -> FastMCPProxy:
    auth = PathScopedGitHubProvider(
        client_id=cfg.github_client_id,
        client_secret=cfg.github_client_secret,
        base_url=f"{cfg.public_url}{OAUTH_PATH}",
        resource_base_url=cfg.public_url,
        issuer_url=f"{cfg.public_url}{OAUTH_PATH}",
        redirect_path="/callback",
        jwt_signing_key=cfg.signing_key,
        required_scopes=["user"],
        require_authorization_consent=True,
    )
    # Version-specific integration is checked and tested, failing closed if it changes.
    if not isinstance(auth._token_validator, GitHubTokenVerifier):
        raise RuntimeError("FastMCP verifier integration changed")
    auth._token_validator = OwnerOnlyGitHubVerifier(cfg.github_owner_id)

    def backend_client() -> ProxyClient:
        # Spawn on demand, do not keep a background Node/MCP bridge running.
        # The command/arguments are immutable and cannot be supplied by callers.
        transport = StdioTransport(
            command="node",
            args=[UPSTREAM_SCRIPT],
            env={"SPOOLMAN_URL": cfg.spoolman_url},
            keep_alive=False,
        )
        return ProxyClient(transport, forward_incoming_headers=False)

    gateway = FastMCPProxy(
        client_factory=backend_client,
        name="Spoolman MCP",
        auth=auth,
        provider_error_strategy="raise",
    )
    gateway.add_middleware(ReadOnlyPolicy())

    # Intentionally unauthenticated for the *container healthcheck*. It reveals
    # no internal data. Pangolin still protects the public resource if enabled.
    @gateway.custom_route("/healthz", methods=["GET"])
    async def health(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return gateway


def main() -> None:
    config = Config.from_env()
    server = build_server(config)
    server.run(transport="http", path=MCP_PATH, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
