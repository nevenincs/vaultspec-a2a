"""Unit tests for the harness MCP-server registry and composition.

Real objects only, no mocks: the registry is a plain dict and the composition
runs against a real ``AcpChatModel`` and a real non-ACP stand-in.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from ...thread.errors import ConfigError
from .._acp_mcp import (
    compose_harness_mcp_servers,
    config_home_mcp_servers,
    harness_allowed_tool_names,
    resolve_harness_mcp_servers,
)
from ..acp_chat_model import AcpChatModel


def test_resolve_known_server_returns_stdio_spec() -> None:
    specs = resolve_harness_mcp_servers(["vaultspec-rag"])
    assert len(specs) == 1
    spec = specs[0]
    assert spec["name"] == "vaultspec-rag"
    assert spec["command"] == "uvx"
    # uvx invokes the published package's console script, cwd-independent.
    assert spec["args"] == ["--from", "vaultspec-rag", "vaultspec-search-mcp"]


def test_resolve_launch_spec_excludes_registry_only_tools_metadata() -> None:
    # ``tools`` is allowlist metadata, not part of the ACP session/new mcpServer
    # shape; it must never leak into the launch spec advertised to the CLI.
    spec = resolve_harness_mcp_servers(["vaultspec-rag"])[0]
    assert "tools" not in spec
    assert set(spec) <= {"name", "command", "args", "env"}


def test_harness_allowed_tool_names_expands_read_tools_to_flat_allowlist() -> None:
    names = harness_allowed_tool_names(["vaultspec-rag"])
    # Exactly the read-only tools, in the CLI's flat mcp__<server>__<tool> form.
    assert names == [
        "mcp__vaultspec-rag__search_vault",
        "mcp__vaultspec-rag__search_codebase",
        "mcp__vaultspec-rag__get_code_file",
    ]
    # The rag server's write verbs are never auto-permitted.
    assert not any("reindex" in n for n in names)


def test_harness_allowed_tool_names_empty_is_empty() -> None:
    assert harness_allowed_tool_names([]) == []


def test_harness_allowed_tool_names_unknown_raises_naming_it() -> None:
    with pytest.raises(ConfigError) as excinfo:
        harness_allowed_tool_names(["does-not-exist"])
    assert "does-not-exist" in str(excinfo.value)


def test_resolve_unknown_server_raises_naming_it_and_the_known_set() -> None:
    with pytest.raises(ConfigError) as excinfo:
        resolve_harness_mcp_servers(["vaultspec-rag", "does-not-exist"])
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "vaultspec-rag" in message  # the known set is named for the operator


def test_resolve_empty_is_empty() -> None:
    assert resolve_harness_mcp_servers([]) == []


def test_compose_empty_names_is_a_noop() -> None:
    model = AcpChatModel(command=["echo"], env_vars={})
    assert compose_harness_mcp_servers(model, []) is model


def test_compose_on_non_acp_model_returns_it_unchanged() -> None:
    # A model without a ``with_mcp_servers`` surface (hosted API, fake) is a
    # pass-through: composition never fabricates an MCP surface.
    model = FakeListChatModel(responses=["ok"])
    assert compose_harness_mcp_servers(model, ["vaultspec-rag"]) is model


def test_compose_advertises_the_declared_server() -> None:
    model = AcpChatModel(command=["echo"], env_vars={})
    composed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    assert isinstance(composed, AcpChatModel)
    assert [s["name"] for s in composed.mcp_servers] == ["vaultspec-rag"]


def test_compose_is_add_only_union_with_existing_servers() -> None:
    # An existing (e.g. authoring) server must survive; the harness server is
    # added beside it, never replacing it.
    model = AcpChatModel(
        command=["echo"],
        env_vars={},
        mcp_servers=[{"name": "vaultspec-authoring", "command": "x"}],
    )
    composed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    assert isinstance(composed, AcpChatModel)
    names = [s["name"] for s in composed.mcp_servers]
    assert "vaultspec-authoring" in names
    assert "vaultspec-rag" in names


def test_compose_does_not_duplicate_an_already_present_server() -> None:
    model = AcpChatModel(command=["echo"], env_vars={})
    once = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    twice = compose_harness_mcp_servers(once, ["vaultspec-rag"])
    assert isinstance(twice, AcpChatModel)
    assert [s["name"] for s in twice.mcp_servers] == ["vaultspec-rag"]


def test_compose_without_allowlist_leaves_allowed_tools_unchanged() -> None:
    # The prior behavior: composing servers with no allowlist preserves whatever
    # allowed_tools the model already carried (e.g. authoring names), and adds
    # none of the composed servers' tool names.
    model = AcpChatModel(
        command=["echo"], env_vars={}, allowed_tools=["mcp__vaultspec-authoring__x"]
    )
    composed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    assert isinstance(composed, AcpChatModel)
    assert composed.allowed_tools == ["mcp__vaultspec-authoring__x"]


def test_compose_unions_allowlist_with_existing_allowed_tools() -> None:
    # Closing the attach(combined) gap: the composed server's tool names JOIN the
    # autonomous allowlist, unioned with (never replacing) the existing authoring
    # names the worker's authoring-attach step set.
    model = AcpChatModel(
        command=["echo"], env_vars={}, allowed_tools=["mcp__vaultspec-authoring__x"]
    )
    composed = compose_harness_mcp_servers(
        model,
        ["vaultspec-rag"],
        allowed_tools=harness_allowed_tool_names(["vaultspec-rag"]),
    )
    assert isinstance(composed, AcpChatModel)
    assert composed.allowed_tools == [
        "mcp__vaultspec-authoring__x",
        "mcp__vaultspec-rag__search_vault",
        "mcp__vaultspec-rag__search_codebase",
        "mcp__vaultspec-rag__get_code_file",
    ]


def test_compose_allowlist_union_does_not_duplicate() -> None:
    # An allowlist name already present is not appended twice.
    model = AcpChatModel(
        command=["echo"],
        env_vars={},
        allowed_tools=["mcp__vaultspec-rag__search_vault"],
    )
    composed = compose_harness_mcp_servers(
        model,
        ["vaultspec-rag"],
        allowed_tools=harness_allowed_tool_names(["vaultspec-rag"]),
    )
    assert isinstance(composed, AcpChatModel)
    assert composed.allowed_tools.count("mcp__vaultspec-rag__search_vault") == 1
    assert composed.allowed_tools == [
        "mcp__vaultspec-rag__search_vault",
        "mcp__vaultspec-rag__search_codebase",
        "mcp__vaultspec-rag__get_code_file",
    ]


def test_config_home_servers_selects_registry_known_shapes_for_claude_json() -> None:
    # From a mixed session set (authoring bridge + harness rag), only the
    # registry-known harness server is selected and shaped for .claude.json.
    session = [
        {"name": "vaultspec-authoring", "command": "node", "args": ["bridge.js"]},
        {"name": "vaultspec-rag", "command": "uvx",
         "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"]},
    ]
    home = config_home_mcp_servers(session)
    assert set(home) == {"vaultspec-rag"}
    assert home["vaultspec-rag"] == {
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
    }


def test_config_home_servers_preserves_env_when_present() -> None:
    session = [
        {"name": "vaultspec-rag", "command": "uvx", "args": ["x"],
         "env": {"K": "V"}},
    ]
    home = config_home_mcp_servers(session)
    assert home["vaultspec-rag"]["env"] == {"K": "V"}


def test_config_home_servers_empty_when_none_registry_known() -> None:
    session = [{"name": "vaultspec-authoring", "command": "node"}]
    assert config_home_mcp_servers(session) == {}


def test_every_registry_entry_is_marked_read_only() -> None:
    # Trust-root invariant: only read-only servers exist in the registry, so a
    # drifted write-capable entry fails at test time before it can ever surface.
    from .._acp_mcp import _KNOWN_MCP_SERVERS

    for name, entry in _KNOWN_MCP_SERVERS.items():
        assert entry.get("read_only") is True, name


def test_config_home_refuses_a_non_read_only_registry_entry() -> None:
    # Runtime fail-loud guard: even if a non-read-only entry drifts into the
    # registry, config_home_mcp_servers refuses to write it into the surfacing
    # home rather than silently exposing a write-capable server.
    from .. import _acp_mcp

    _acp_mcp._KNOWN_MCP_SERVERS["danger-writer"] = {
        "name": "danger-writer",
        "command": "x",
        "tools": ("write_thing",),
    }
    try:
        with pytest.raises(ConfigError):
            config_home_mcp_servers([{"name": "danger-writer", "command": "x"}])
    finally:
        del _acp_mcp._KNOWN_MCP_SERVERS["danger-writer"]


def test_compose_unknown_name_raises() -> None:
    model = AcpChatModel(command=["echo"], env_vars={})
    with pytest.raises(ConfigError):
        compose_harness_mcp_servers(model, ["totally-unknown"])


def test_compose_unknown_name_raises_even_on_non_acp_model() -> None:
    # An unknown declared name is a configuration error even when composition is
    # inapplicable: the loud refusal is uniform across model types, not swallowed
    # by the non-ACP pass-through.
    model = FakeListChatModel(responses=["ok"])
    with pytest.raises(ConfigError):
        compose_harness_mcp_servers(model, ["totally-unknown"])
