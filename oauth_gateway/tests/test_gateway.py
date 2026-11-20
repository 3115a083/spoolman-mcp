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
    Config, OwnerOnlyGitHubVerifier, ReadOnlyPolicy, UPSTREAM_SCRIPT, build_server
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

    def test_only_fixed_node_subprocess(self):
        with patch.dict(os.environ, SETTINGS, clear=True):
            gateway = build_server(Config.from_env())
        backend = gateway.provider.client_factory()
        self.assertIsInstance(backend.transport, StdioTransport)
        self.assertEqual(backend.transport.command, "node")
        self.assertEqual(backend.transport.args, [UPSTREAM_SCRIPT])
        self.assertFalse(backend.transport.keep_alive)
        self.assertFalse(backend.forward_incoming_headers)


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
