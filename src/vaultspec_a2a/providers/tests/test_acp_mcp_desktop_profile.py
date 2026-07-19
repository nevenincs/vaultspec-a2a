"""Real production-seam tests for desktop harness MCP capability resolution."""

from __future__ import annotations

from dataclasses import asdict

from ...team.team_config import load_team_config
from .. import _acp_mcp
from .._acp_mcp import (
    HarnessMcpRuntimeProfile,
    codex_mcp_server_specs,
    compose_harness_mcp_servers,
    config_home_mcp_servers,
    harness_allowed_tool_names,
    resolve_harness_mcp_capabilities,
    resolve_harness_mcp_servers,
)
from ..acp_chat_model import AcpChatModel
from ..codex_chat_model import CodexChatModel

RAG_SERVER = "vaultspec-rag"
RAG_NAMES = [RAG_SERVER]


def test_desktop_registry_admission_is_explicit_and_fail_closed() -> None:
    assert _acp_mcp._desktop_available({}) is False
    assert (
        _acp_mcp._desktop_available(
            {"desktop_available": True, "runtime_acquisition": True}
        )
        is False
    )
    assert _acp_mcp._desktop_available({"desktop_available": True}) is False
    assert (
        _acp_mcp._desktop_available(
            {"desktop_available": True, "runtime_acquisition": False}
        )
        is True
    )
    assert _acp_mcp._desktop_available(_acp_mcp._KNOWN_MCP_SERVERS[RAG_SERVER]) is False


def test_desktop_resolution_returns_actionable_path_free_unavailability() -> None:
    resolution = resolve_harness_mcp_capabilities(
        RAG_NAMES,
        profile=HarnessMcpRuntimeProfile.DESKTOP,
    )

    assert resolution.profile is HarnessMcpRuntimeProfile.DESKTOP
    assert resolution.available_servers == ()
    assert len(resolution.unavailable) == 1
    result = asdict(resolution.unavailable[0])
    assert result == {
        "code": "capability_unavailable",
        "capability": RAG_SERVER,
        "reason": "runtime acquisition is disabled for the desktop profile",
        "action": (
            "Install the separately packaged vaultspec-rag desktop capability, "
            "then retry."
        ),
    }
    assert "uvx" not in repr(result)
    assert "/" not in repr(result)
    assert "\\" not in repr(result)


def test_desktop_serializers_emit_no_runtime_acquisition_material() -> None:
    non_desktop_specs = resolve_harness_mcp_servers(RAG_NAMES)
    assert non_desktop_specs[0]["command"] == "uvx"

    assert (
        resolve_harness_mcp_servers(
            RAG_NAMES,
            profile=HarnessMcpRuntimeProfile.DESKTOP,
        )
        == []
    )
    assert (
        harness_allowed_tool_names(
            RAG_NAMES,
            profile=HarnessMcpRuntimeProfile.DESKTOP,
        )
        == []
    )
    assert (
        config_home_mcp_servers(
            non_desktop_specs,
            profile=HarnessMcpRuntimeProfile.DESKTOP,
        )
        == {}
    )
    assert (
        codex_mcp_server_specs(
            RAG_NAMES,
            profile=HarnessMcpRuntimeProfile.DESKTOP,
        )
        == []
    )


def test_desktop_acp_composition_scrubs_stale_launch_and_allowlist_entries() -> None:
    stale_specs = resolve_harness_mcp_servers(RAG_NAMES)
    stale_allowlist = harness_allowed_tool_names(RAG_NAMES)
    model = AcpChatModel(
        command=["echo"],
        env_vars={},
        mcp_servers=[
            {"name": "vaultspec-authoring", "command": "python"},
            *stale_specs,
        ],
        allowed_tools=["mcp__vaultspec-authoring__read", *stale_allowlist],
    )

    composed = compose_harness_mcp_servers(
        model,
        RAG_NAMES,
        allowed_tools=stale_allowlist,
        profile=HarnessMcpRuntimeProfile.DESKTOP,
    )

    assert isinstance(composed, AcpChatModel)
    assert composed.mcp_servers == [
        {"name": "vaultspec-authoring", "command": "python"}
    ]
    assert composed.allowed_tools == ["mcp__vaultspec-authoring__read"]
    assert "uvx" not in repr(composed.mcp_servers)


def test_desktop_codex_composition_cannot_build_a_uvx_config_home() -> None:
    model = CodexChatModel(
        command=["codex", "app-server"],
        harness_mcp_servers=RAG_NAMES,
    )

    composed = compose_harness_mcp_servers(
        model,
        RAG_NAMES,
        profile=HarnessMcpRuntimeProfile.DESKTOP,
    )

    assert isinstance(composed, CodexChatModel)
    assert composed.harness_mcp_servers == []
    assert composed._build_codex_config_home() is None


def test_desktop_empty_declaration_scrubs_pre_attached_acp_uvx_state() -> None:
    model = AcpChatModel(
        command=["echo"],
        env_vars={},
        mcp_servers=resolve_harness_mcp_servers(RAG_NAMES),
        allowed_tools=harness_allowed_tool_names(RAG_NAMES),
    )

    composed = compose_harness_mcp_servers(
        model,
        [],
        profile=HarnessMcpRuntimeProfile.DESKTOP,
    )

    assert isinstance(composed, AcpChatModel)
    assert composed.mcp_servers == []
    assert composed.allowed_tools == []


def test_desktop_empty_declaration_scrubs_pre_attached_codex_rag_state() -> None:
    model = CodexChatModel(
        command=["codex", "app-server"],
        harness_mcp_servers=RAG_NAMES,
    )

    composed = compose_harness_mcp_servers(
        model,
        [],
        profile=HarnessMcpRuntimeProfile.DESKTOP,
    )

    assert isinstance(composed, CodexChatModel)
    assert composed.harness_mcp_servers == []
    assert composed._build_codex_config_home() is None


def test_non_desktop_empty_declaration_remains_an_identity_noop() -> None:
    acp_model = AcpChatModel(
        command=["echo"],
        env_vars={},
        mcp_servers=resolve_harness_mcp_servers(RAG_NAMES),
    )
    codex_model = CodexChatModel(
        command=["codex", "app-server"],
        harness_mcp_servers=RAG_NAMES,
    )

    assert (
        compose_harness_mcp_servers(
            acp_model,
            [],
            profile=HarnessMcpRuntimeProfile.NON_DESKTOP,
        )
        is acp_model
    )
    assert (
        compose_harness_mcp_servers(
            codex_model,
            [],
            profile=HarnessMcpRuntimeProfile.NON_DESKTOP,
        )
        is codex_model
    )


def test_non_desktop_profile_preserves_live_preset_resolution() -> None:
    config = load_team_config("vaultspec-adr-research")
    harness = config.effective_harness()
    assert harness is not None

    resolution = resolve_harness_mcp_capabilities(
        harness.mcp_servers,
        profile=HarnessMcpRuntimeProfile.NON_DESKTOP,
    )
    specs = resolve_harness_mcp_servers(
        harness.mcp_servers,
        profile=HarnessMcpRuntimeProfile.NON_DESKTOP,
    )

    assert resolution.available_servers == (RAG_SERVER,)
    assert resolution.unavailable == ()
    assert specs[0]["command"] == "uvx"
    assert config_home_mcp_servers(specs)[RAG_SERVER]["command"] == "uvx"
    assert codex_mcp_server_specs(harness.mcp_servers)[0]["command"] == "uvx"
    assert harness_allowed_tool_names(harness.mcp_servers) == [
        "mcp__vaultspec-rag__search_vault",
        "mcp__vaultspec-rag__search_codebase",
        "mcp__vaultspec-rag__get_code_file",
    ]
