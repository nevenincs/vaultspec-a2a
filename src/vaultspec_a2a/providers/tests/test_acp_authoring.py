"""Unit tests for the ACP authoring-tool binding and mcpServers builder (R4).

Pure tests over real catalog objects — no mocks, no network. They pin the
loopback-only invariant, the no-vault-write-path guard, token redaction (R7),
and the exact ``mcpServers`` entry shape the claude-agent-acp CLI consumes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ...authoring import ACTOR_TOKEN_HEADER, BEARER_HEADER, AgentTool, CatalogSnapshot
from .._acp_authoring import (
    AUTHORING_MCP_SERVER_NAME,
    AuthoringToolBinding,
    build_authoring_mcp_servers,
    is_write_tool_name,
)
from .._acp_rpc_handlers import on_fs_write_text_file
from .._acp_types import _AcpModelConfig, _AcpSessionContext

if TYPE_CHECKING:
    from pathlib import Path

_LOOPBACK_URL = "http://127.0.0.1:8200/mcp"


def _tool(name: str, *, risk_tier: str = "read_only") -> AgentTool:
    return AgentTool(
        name=name,
        description=f"{name} tool",
        input_schema={"type": "object"},
        risk_tier=risk_tier,
        permission_requirement="auto_permitted",
        idempotency_required=False,
        commands=(name,),
    )


def _catalog(*names: str) -> CatalogSnapshot:
    return CatalogSnapshot(
        schema_version="authoring.semantic_tools.v1",
        tools=tuple(_tool(name) for name in names),
    )


def _binding(
    *names: str,
    server_url: str = _LOOPBACK_URL,
    bearer: str = "machine-bearer",
    actor: str = "actor-token",
) -> AuthoringToolBinding:
    return AuthoringToolBinding(
        snapshot=_catalog(*(names or ("read_context", "propose_changeset"))),
        server_url=server_url,
        bearer_token=bearer,
        actor_token=actor,
    )


class TestWriteToolGuard:
    """The binding refuses any raw filesystem-write tool (R2)."""

    @pytest.mark.parametrize(
        "name",
        ["write_file", "fs_write_text_file", "save_file", "delete_file", "unlink"],
    )
    def test_write_names_flagged(self, name: str) -> None:
        assert is_write_tool_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "read_context",
            "search_graph",
            "propose_changeset",
            "validate_proposal",
            "request_approval",
            "cancel",
            "request_apply",
        ],
    )
    def test_engine_catalog_names_allowed(self, name: str) -> None:
        assert not is_write_tool_name(name)

    def test_binding_rejects_write_tool(self) -> None:
        with pytest.raises(ValueError, match="filesystem-write"):
            _binding("read_context", "write_file")


class TestLoopbackInvariant:
    """Only a loopback http(s) server URL is accepted (R4)."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.0.5:8200/mcp",
            "http://example.com/mcp",
            "https://198.51.100.7/mcp",
            "ftp://127.0.0.1/mcp",
            "not-a-url",
        ],
    )
    def test_non_loopback_rejected(self, url: str) -> None:
        with pytest.raises(ValueError, match="loopback"):
            _binding(server_url=url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8200/mcp",
            "http://localhost:8200/mcp",
            "https://127.0.0.1/mcp",
        ],
    )
    def test_loopback_accepted(self, url: str) -> None:
        binding = _binding(server_url=url)
        assert binding.server_url == url


class TestTokenHygiene:
    """Tokens never appear in repr (R7)."""

    def test_repr_redacts_tokens(self) -> None:
        binding = _binding(bearer="SECRET-BEARER", actor="SECRET-ACTOR")
        rendered = repr(binding)
        assert "SECRET-BEARER" not in rendered
        assert "SECRET-ACTOR" not in rendered
        assert "<redacted>" in rendered

    def test_empty_tokens_rejected(self) -> None:
        with pytest.raises(ValueError, match="bearer"):
            _binding(bearer="")
        with pytest.raises(ValueError, match="actor"):
            _binding(actor="")


class TestBuildMcpServers:
    """The mcpServers entry matches the CLI's http server shape."""

    def test_single_loopback_http_entry(self) -> None:
        binding = _binding("read_context", "propose_changeset")
        servers = build_authoring_mcp_servers(binding)
        assert len(servers) == 1
        entry = servers[0]
        assert entry["name"] == AUTHORING_MCP_SERVER_NAME
        assert entry["type"] == "http"
        assert entry["url"] == _LOOPBACK_URL

    def test_headers_carry_both_auth_layers(self) -> None:
        binding = _binding(bearer="mb", actor="at")
        entry = build_authoring_mcp_servers(binding)[0]
        headers = {h["name"]: h["value"] for h in entry["headers"]}
        assert headers[BEARER_HEADER] == "Bearer mb"
        assert headers[ACTOR_TOKEN_HEADER] == "at"

    def test_tool_names_expose_no_write_path(self) -> None:
        binding = _binding(
            "read_context", "search_graph", "propose_changeset", "request_apply"
        )
        assert binding.tool_names == (
            "read_context",
            "search_graph",
            "propose_changeset",
            "request_apply",
        )
        assert not any(is_write_tool_name(name) for name in binding.tool_names)


def _config_with_authoring(workspace_root: str) -> _AcpModelConfig:
    """Build an ACP config whose session advertises the bridged authoring tools."""
    binding = _binding("read_context", "propose_changeset")
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=workspace_root,
        cwd=None,
        command=["echo"],
        env_vars={},
        session_id=None,
        mcp_servers=build_authoring_mcp_servers(binding),
        allowed_tools=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


class TestAuthoringVisibleButVaultWriteDenied:
    """Bridged propose/read tools are wired AND the vault-write path stays closed.

    The config advertises the authoring MCP server (propose/read tools visible),
    yet the ACP fs write RPC still returns the value-typed forbidden_actor denial
    for a ``.vault`` path — the two halves of R2 + R4 hold together.
    """

    @pytest.mark.asyncio
    async def test_vault_write_denied_with_authoring_wired(
        self, tmp_path: Path
    ) -> None:
        config = _config_with_authoring(str(tmp_path))
        # The authoring tools are surfaced to the session.
        assert config.mcp_servers[0]["name"] == AUTHORING_MCP_SERVER_NAME
        # Yet a vault write through the ACP fs RPC is still denied as a value.
        result = await on_fs_write_text_file(
            1,
            {"path": ".vault/plan/x.md", "content": "SHOULD NOT LAND"},
            cast("_AcpSessionContext", None),
            config,
        )
        payload = cast("dict", result["result"])
        assert payload["status"] == "denied"
        assert payload["denial_kind"] == "forbidden_actor"
        assert "error" not in result
        assert not (tmp_path / ".vault" / "plan" / "x.md").exists()
