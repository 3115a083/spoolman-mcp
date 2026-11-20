"""Negative security tests. No network, credentials, or real Spoolman state."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubTokenVerifier
from fastmcp.server.middleware import MiddlewareContext

from oauth_gateway.app import Config, OwnerOnlyGitHubVerifier, ReadOnlyPolicy, build_server

ENV = {
    "OAUTH_PUBLIC_URL": "https://oauth.example.com",
    "MCP_BACKEND_URL": "https://protected.example.com/mcp",
    "GITHUB_CLIENT_ID": "test-client",
    "GITHUB_CLIENT_SECRET": "test-client-secret-with-20-chars",
    "GITHUB_OWNER_ID": "123456",
    "OAUTH_JWT_SIGNING_KEY": "s" * 64,
    "PANGOLIN_ACCESS_TOKEN_ID": "service-id",
    "PANGOLIN_ACCESS_TOKEN": "test-service-token-with-20-chars",
    "MCP_BACKEND_API_KEY": "k" * 64,
}


class ConfigTests(unittest.TestCase):
    def test_accept_valid_configuration(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(Config.from_env().github_owner_id, "123456")

    def test_reject_missing_key(self):
        for key in ENV:
            with self.subTest(key=key):
                values = dict(ENV)
                values.pop(key)
                with patch.dict(os.environ, values, clear=True):
                    with self.assertRaises(ValueError):
                        Config.from_env()

    def test_reject_bad_urls(self):
        for url in ("http://oauth.example.com", "https://example.com/mcp", "https://u:p@example.com", "https://example.com?token=x"):
            with self.subTest(url=url):
                values = {**ENV, "OAUTH_PUBLIC_URL": url}
                with patch.dict(os.environ, values, clear=True):
                    with self.assertRaises(ValueError):
                        Config.from_env()
        with patch.dict(os.environ, {**ENV, "MCP_BACKEND_URL": "https://oauth.example.com/mcp"}, clear=True):
            with self.assertRaises(ValueError):
                Config.from_env()

    def test_owner_verifier_installed(self):
        with patch.dict(os.environ, ENV, clear=True):
            server = build_server(Config.from_env())
            self.assertIsInstance(server.auth._token_validator, OwnerOnlyGitHubVerifier)
            self.assertEqual(server.auth._token_validator.owner_id, "123456")


class IdentityAndPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_allow_only_owner(self):
        verifier = OwnerOnlyGitHubVerifier("123456")
        for user, allowed in [("123456", True), ("654321", False)]:
            upstream = AccessToken(token="ignored", client_id=user, scopes=["user"], subject=user)
            with patch.object(GitHubTokenVerifier, "verify_token", new=AsyncMock(return_value=upstream)):
                result = await verifier.verify_token("opaque-github-token")
                self.assertEqual(result is not None, allowed)

    async def test_reject_missing_identity(self):
        verifier = OwnerOnlyGitHubVerifier("123456")
        with patch.object(GitHubTokenVerifier, "verify_token", new=AsyncMock(return_value=None)):
            self.assertIsNone(await verifier.verify_token("bad"))

    async def test_hide_and_block_mutating_tools(self):
        from types import SimpleNamespace
        policy = ReadOnlyPolicy()
        listed = await policy.on_list_tools(MiddlewareContext(message={}), AsyncMock(return_value=[
            SimpleNamespace(name="spoolman_list_spools"),
            SimpleNamespace(name="spoolman_delete_spool"),
            SimpleNamespace(name="other_tool"),
        ]))
        self.assertEqual([t.name for t in listed], ["spoolman_list_spools"])
        next_call = AsyncMock(return_value="ok")
        self.assertEqual(await policy.on_call_tool(MiddlewareContext(message=SimpleNamespace(name="spoolman_get_spool")), next_call), "ok")
        for name in ("spoolman_delete_spool", "spoolman_create_spool", "unknown"):
            next_call.reset_mock()
            with self.subTest(name=name):
                with self.assertRaises(AuthorizationError):
                    await policy.on_call_tool(MiddlewareContext(message=SimpleNamespace(name=name)), next_call)
                next_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
