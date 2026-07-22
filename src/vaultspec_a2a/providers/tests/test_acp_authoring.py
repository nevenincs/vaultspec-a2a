"""Unit tests for the ACP authoring-tool binding and mcpServers builder (R4).

Pure tests over real catalog objects — no mocks, no network. They pin the
loopback-only invariant, the no-vault-write-path guard, token redaction (R7),
and the exact ``mcpServers`` entry shape the claude-agent-acp CLI consumes.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

import pytest

from ...authoring import ACTOR_TOKEN_HEADER, BEARER_HEADER, AgentTool, CatalogSnapshot
from ...authoring.catalog import parse_catalog, snapshot_to_catalog_payload
from ...protocols.mcp.authoring_stdio import (
    ENV_ACTOR_TOKEN,
    ENV_BASE_URL,
    ENV_BEARER,
    ENV_CATALOG_JSON,
    ENV_RUN_ID,
    ENV_SERVER_NAME,
)
from ...thread.errors import ConfigError
from .._acp_authoring import (
    AUTHORING_MCP_SERVER_NAME,
    AUTHORING_STDIO_MODULE,
    AuthoringToolBinding,
    build_authoring_mcp_servers,
    build_authoring_stdio_mcp_servers,
    config_home_authoring_entry,
    is_write_tool_name,
)
from .._acp_rpc_handlers import on_fs_write_text_file
from .._acp_types import _AcpModelConfig, _AcpSessionContext

if TYPE_CHECKING:
    from collections.abc import Iterator
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


_ENGINE_URL = "http://127.0.0.1:8767"


def _stdio_binding(
    *names: str,
    engine_base_url: str = _ENGINE_URL,
    run_id: str = "run-xyz",
    bearer: str = "machine-bearer",
    actor: str = "actor-token",
) -> AuthoringToolBinding:
    return AuthoringToolBinding(
        snapshot=_catalog(*(names or ("read_context", "propose_changeset"))),
        engine_base_url=engine_base_url,
        run_id=run_id,
        bearer_token=bearer,
        actor_token=actor,
    )


class TestConfigHomeAuthoringEntry:
    """Admit the run's stdio authoring bridge into the isolated home (S18).

    Driven through the real seam: a real ``AuthoringToolBinding`` ->
    ``build_authoring_stdio_mcp_servers`` -> ``config_home_authoring_entry``, so a
    production gap in the builder or the selector surfaces here rather than being
    masked by a hand-built spec dict.
    """

    def test_placeholders_on_disk_values_in_spawn_env(self) -> None:
        binding = _stdio_binding(
            bearer="SECRET-BEARER", actor="SECRET-ACTOR", run_id="run-777"
        )
        specs = build_authoring_stdio_mcp_servers(binding)
        home, spawn_env = config_home_authoring_entry(specs)

        entry = home[AUTHORING_MCP_SERVER_NAME]
        assert entry["type"] == "stdio"
        assert entry["args"] == ["-m", AUTHORING_STDIO_MODULE]

        # Every home env value is a ${VAR} placeholder keyed by its own name,
        # never a real value.
        home_env = entry["env"]
        for name, value in home_env.items():
            assert value == f"${{{name}}}"

        # Each bridge env name carries a placeholder, and the spawn env carries the
        # matching real value the CLI expands the placeholder from - including the
        # handed catalog snapshot (JSON) that lets the bridge serve list_tools
        # without an engine fetch at spawn.
        expected_values = {
            ENV_BASE_URL: _ENGINE_URL,
            ENV_BEARER: "SECRET-BEARER",
            ENV_ACTOR_TOKEN: "SECRET-ACTOR",
            ENV_RUN_ID: "run-777",
            ENV_SERVER_NAME: AUTHORING_MCP_SERVER_NAME,
            ENV_CATALOG_JSON: json.dumps(snapshot_to_catalog_payload(binding.snapshot)),
        }
        assert set(home_env) == set(expected_values)
        assert spawn_env == expected_values
        # The handed catalog round-trips back to the run's snapshot.
        assert (
            parse_catalog(json.loads(spawn_env[ENV_CATALOG_JSON])).tool_names()
            == binding.snapshot.tool_names()
        )

        # No secret ever appears in the on-disk placeholder mapping.
        assert "SECRET-BEARER" not in json.dumps(home_env)
        assert "SECRET-ACTOR" not in json.dumps(home_env)

    def test_no_bridge_spec_is_noop(self) -> None:
        rag = {
            "name": "vaultspec-rag",
            "command": "uvx",
            "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
        }
        assert config_home_authoring_entry([rag]) == ({}, {})
        assert config_home_authoring_entry([]) == ({}, {})

    def test_http_binding_under_bridge_name_raises(self) -> None:
        # An HTTP-transport authoring server carries no stdio ``args`` signature,
        # so it cannot ride the home channel.
        http_specs = build_authoring_mcp_servers(_binding())
        assert http_specs[0]["name"] == AUTHORING_MCP_SERVER_NAME
        with pytest.raises(ConfigError, match="stdio authoring bridge"):
            config_home_authoring_entry(http_specs)

    def test_foreign_module_under_bridge_name_raises(self) -> None:
        # A spec claiming the bridge name but pointing at a foreign module is not
        # the guarded per-run bridge and must be refused.
        foreign = {
            "name": AUTHORING_MCP_SERVER_NAME,
            "command": "python",
            "args": ["-m", "attacker.module"],
            "env": [{"name": ENV_BEARER, "value": "x"}],
        }
        with pytest.raises(ConfigError, match="stdio authoring bridge"):
            config_home_authoring_entry([foreign])

    def test_missing_env_under_bridge_name_raises(self) -> None:
        no_env = {
            "name": AUTHORING_MCP_SERVER_NAME,
            "command": "python",
            "args": ["-m", AUTHORING_STDIO_MODULE],
        }
        with pytest.raises(ConfigError, match="no env"):
            config_home_authoring_entry([no_env])


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


class TestAcpWriteGitSerialization:
    """ACP writes serialize through the shared workspace mutex.

    The workspace-global ``git_workspace_mutex`` (in ``workspace/concurrency.py``)
    serializes every subsystem that writes the working tree; the ACP fs-write
    handler acquires it, so a write cannot proceed while a repository-wide holder
    of that lock is in its critical section. This proves the contention through
    the production handler and the production lock, not a stand-in.
    """

    @pytest.fixture
    def loop_bound_mutex(self) -> Iterator[asyncio.Lock]:
        """A fresh workspace mutex bound to the running test loop.

        ``git_workspace_mutex`` is a process-global ``asyncio.Lock`` - correct
        for the single production uvicorn loop, but pytest gives each test its
        own loop, and a lock binds to the first loop that uses it. Reset it to a
        fresh instance so this test's hold and the handler's acquisition (which
        re-imports the module attribute on every call) contend on the same loop,
        then restore the original so the global is never left mutated.
        """
        import vaultspec_a2a.workspace.concurrency as concurrency

        original = concurrency.git_workspace_mutex
        fresh = asyncio.Lock()
        concurrency.git_workspace_mutex = fresh
        try:
            yield fresh
        finally:
            concurrency.git_workspace_mutex = original

    @pytest.mark.asyncio
    async def test_acp_write_is_serialized_behind_a_held_git_mutex(
        self, tmp_path: Path, loop_bound_mutex: asyncio.Lock
    ) -> None:
        """A concurrent ACP write cannot proceed while the shared mutex is held.

        Hold the shared workspace mutex, launch a real write through the
        production handler, and prove it is serialized behind the lock: it stays
        pending while the lock is held and completes only once it is released. A
        handler acquiring a different lock would finish during the hold and fail
        the not-done assertion, so this pins the shared-lock routing, not just
        that some lock exists.
        """
        config = _config_with_authoring(str(tmp_path))
        order: list[str] = []

        async with loop_bound_mutex:
            order.append("holder-acquired")
            write = asyncio.create_task(
                on_fs_write_text_file(
                    1,
                    {
                        "path": "serialized.txt",
                        "content": "written after the lock frees",
                    },
                    cast("_AcpSessionContext", None),
                    config,
                )
            )
            # Ample opportunity to run if the write were NOT serialized.
            await asyncio.sleep(0.1)
            # If the handler used a different lock it would finish during the
            # hold; serialization on the shared mutex keeps it pending.
            assert not write.done(), "ACP write ran while the shared git lock was held"
            order.append("holder-still-holding")

        result = await write
        order.append("write-completed")

        assert order == ["holder-acquired", "holder-still-holding", "write-completed"]
        assert cast("dict", result["result"]) == {}
        assert (tmp_path / "serialized.txt").read_text(encoding="utf-8") == (
            "written after the lock frees"
        )
