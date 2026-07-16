"""Unit tests for the harness MCP-server registry and composition.

Real objects only, no mocks: the registry is a plain dict and the composition
runs against a real ``AcpChatModel`` and a real non-ACP stand-in.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from ...thread.errors import ConfigError
from .._acp_mcp import compose_harness_mcp_servers, resolve_harness_mcp_servers
from ..acp_chat_model import AcpChatModel


def test_resolve_known_server_returns_stdio_spec() -> None:
    specs = resolve_harness_mcp_servers(["vaultspec-rag"])
    assert len(specs) == 1
    spec = specs[0]
    assert spec["name"] == "vaultspec-rag"
    assert spec["command"] == "uvx"
    # uvx invokes the published package's console script, cwd-independent.
    assert spec["args"] == ["--from", "vaultspec-rag", "vaultspec-search-mcp"]


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
