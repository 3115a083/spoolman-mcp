"""Tests for security boundary, configuration, and the single-process gateway."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubTokenVerifier
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.client.transports import StdioTransport

from oauth_gateway.app import (
    Config, OwnerOnlyGitHubVerifier, ReadOnlyPolicy, UPSTREAM_SCRIPT, MCP_PATH, OAUTH_PATH, build_server
)

SETTINGS = {
    "PUBLIC_URL": "https://mcp.example.com",
    "SPOOLMAN_URL": "http://127.0.0.1:7912",
    "GITHUB_CLIENT_ID": "test-client-id",
    "GITHUB_CLIENT_SECRET": "test-client-secret-with-20-chars",
    "GITHUB_OWNER_ID": "123456",
    "OAUTH_JWT_SIGNING_KEY": "s" * 64,
}


class ConfigurationTests(unittest.TestCase):
    def test_valid(self):
        with patch.dict(os.environ, SETTINGS, clear=True):
            cfg = Config.from_env()
            gateway = build_server(cfg)
        self.assertEqual(cfg.public_url, "https://mcp.example.com")
        self.assertEqual(cfg.spoolman_url, "http://127.0.0.1:7912")
        self.assertEqual(gateway.auth._token_validator.owner_id, "123456")

    def test_missing_secrets_fail_closed(self):
        for name in SETTINGS:
            with self.subTest(name=name):
                env = {key: value for key, value in SETTINGS.items() if key != name}
                with patch.dict(os.environ, env, clear=True):
                    with self.assertRaises(ValueError):
                        Config.from_env()

    def test_bad_urls(self):
        for url in (
            "http://mcp.example.com", "https://mcp.example.com/mcp",
            "https://foo:bar@mcp.example.com", "https://mcp.example.com?token=x",
        ):
            with self.subTest(url=url):
                with patch.dict(os.environ, {**SETTINGS, "PUBLIC_URL": url}, clear=True):
                    with self.assertRaises(ValueError):
                        Config.from_env()
        for url in ("file:///etc/passwd", "http://user:pass@server", "http://localhost:7912/api/v1"):
            with self.subTest(url=url):
                with patch.dict(os.environ, {**SETTINGS, "SPOOLMAN_URL": url}, clear=True):
                    with self.assertRaises(ValueError):
                        Config.from_env()

    def test_owner_is_numeric(self):
        with patch.dict(os.environ, {**SETTINGS, "GITHUB_OWNER_ID": "octocat"}, clear=True):
            with self.assertRaises(ValueError):
                Config.from_env()

    def test_routes_and_oauth_metadata_are_consistent(self):
        from starlette.testclient import TestClient

        with patch.dict(os.environ, SETTINGS, clear=True):
            gateway = build_server(Config.from_env())
            app = gateway.http_app(path=MCP_PATH)

        paths = {route.path for route in app.routes}
        for path in (
            "/MCP", "/auth/authorize", "/auth/token", "/auth/register",
            "/auth/callback", "/auth/consent",
            "/.well-known/oauth-authorization-server/auth",
            "/.well-known/oauth-protected-resource/MCP",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)
        for forbidden in ("/mcp", "/authorize", "/token", "/register"):
            self.assertNotIn(forbidden, paths)

        with TestClient(app) as client:
            meta_response = client.get("/.well-known/oauth-authorization-server/auth")
            self.assertEqual(meta_response.status_code, 200, meta_response.text)
            metadata = meta_response.json()
            self.assertEqual(metadata["issuer"], "https://mcp.example.com/auth")
            for name, url in (
                ("authorization_endpoint", "https://mcp.example.com/auth/authorize"),
                ("token_endpoint", "https://mcp.example.com/auth/token"),
                ("registration_endpoint", "https://mcp.example.com/auth/register"),
            ):
                self.assertEqual(metadata[name], url)

            resource_response = client.get("/.well-known/oauth-protected-resource/MCP")
            self.assertEqual(resource_response.status_code, 200, resource_response.text)
            resource = resource_response.json()
            self.assertEqual(resource["resource"], "https://mcp.example.com/MCP")
            self.assertIn("https://mcp.example.com/auth", resource["authorization_servers"])
            self.assertEqual(client.get("/mcp").status_code, 404)
            body = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
            denied = client.post(
                "/MCP", json=body,
                headers={"Accept": "application/json, text/event-stream"},
            )
            self.assertEqual(denied.status_code, 401)
            self.assertIn("Bearer", denied.headers.get("WWW-Authenticate", ""))

    def test_only_fixed_node_subprocess(self):
        with patch.dict(os.environ, SETTINGS, clear=True):
            gateway = build_server(Config.from_env())
        backend = gateway.client_factory()
        self.assertIsInstance(backend.transport, StdioTransport)
        self.assertEqual(backend.transport.command, "node")
        self.assertEqual(backend.transport.args, [UPSTREAM_SCRIPT])
        self.assertFalse(backend.transport.keep_alive)
        self.assertFalse(backend._transport_options.forward_incoming_headers)


class IdentityAndToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_owner_is_accepted(self):
        verifier = OwnerOnlyGitHubVerifier("123456")
        for identity, accepted in (("123456", True), ("654321", False)):
            result = AccessToken(
                token="opaque", client_id=identity, scopes=["user"], subject=identity
            )
            with patch.object(GitHubTokenVerifier, "verify_token", new=AsyncMock(return_value=result)):
                actual = await verifier.verify_token("github-opaque-token")
                self.assertEqual(actual is not None, accepted)

    async def test_invalid_identity_fails(self):
        verifier = OwnerOnlyGitHubVerifier("123456")
        with patch.object(GitHubTokenVerifier, "verify_token", new=AsyncMock(return_value=None)):
            self.assertIsNone(await verifier.verify_token("invalid"))

    async def test_mutations_hidden_and_blocked(self):
        policy = ReadOnlyPolicy()
        tools = await policy.on_list_tools(
            MiddlewareContext(message={}),
            AsyncMock(return_value=[
                SimpleNamespace(name="spoolman_list_spools"),
                SimpleNamespace(name="spoolman_delete_spool"),
                SimpleNamespace(name="unknown_tool"),
            ]),
        )
        self.assertEqual([x.name for x in tools], ["spoolman_list_spools"])
        next_call = AsyncMock(return_value="ok")
        self.assertEqual(
            await policy.on_call_tool(
                MiddlewareContext(message=SimpleNamespace(name="spoolman_get_spool")),
                next_call,
            ),
            "ok",
        )
        for name in ("spoolman_delete_spool", "spoolman_create_spool", "other"):
            next_call.reset_mock()
            with self.subTest(name=name):
                with self.assertRaises(AuthorizationError):
                    await policy.on_call_tool(
                        MiddlewareContext(message=SimpleNamespace(name=name)), next_call
                    )
                next_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
