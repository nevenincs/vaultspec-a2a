"""Unit tests for the harness MCP-server registry and composition.

Real objects only, no mocks: composition runs against production
``AcpChatModel``, ``CodexChatModel``, and ``ChatOpenAI`` instances.

No outward-reaching server is exercised here, and the absence is the point rather
than a gap. The registry is closed and every entry it now carries declares no egress,
so there is nothing here that reaching outward would even describe. The cases that
used to exercise it were written against a first-party web-search server that does
not exist, and they went with it: a test proving a fiction resolves, renders a
launch spec, and gets advertised is worse than no test, because it passes. Should
a real egressing entry ever be declared, its coverage belongs here and must be
written against that entry, never against a placeholder.
"""

from __future__ import annotations

import subprocess
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ...thread.errors import ConfigError
from .._acp_mcp import (
    NATIVE_READ_TOOL_NAMES,
    codex_mcp_server_specs,
    compose_harness_mcp_servers,
    compose_native_read_tools,
    config_home_mcp_servers,
    harness_allowed_tool_names,
    is_known_harness_server,
    resolve_harness_mcp_servers,
)
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from .._json_contract import JsonObject


def test_resolve_known_server_returns_stdio_spec() -> None:
    specs = resolve_harness_mcp_servers(["vaultspec-rag"])
    assert len(specs) == 1
    spec = specs[0]
    assert spec["name"] == "vaultspec-rag"
    assert spec["command"] == "uvx"
    # uvx invokes the published package's console script, cwd-independent.
    assert spec["args"] == [
        "--from",
        "vaultspec-rag[mcp]",
        "vaultspec-search-mcp",
    ]


def test_harness_specs_are_provider_child_launch_specs_not_self_spawned() -> None:
    """Audit lock: the harness registry emits launch SPECS only, never a spawn.

    The ACP/Codex provider CLI spawns each declared harness server as its own
    child, so the server is a descendant of the run-owned provider root and
    inherits that root's OS containment. This registry module never spawns a
    process itself, so there is no separate reaper to wire.
    """
    from .. import _acp_mcp as mod

    spec = resolve_harness_mcp_servers(["vaultspec-rag"])[0]
    # A child-launch spec the provider spawns: command + args, no live process.
    assert set(spec) <= {"name", "command", "args", "env"}
    assert "command" in spec
    for banned in (
        "subprocess",
        "Popen",
        "spawn_acp_process",
        "create_subprocess_exec",
        "ProcessContainment",
    ):
        assert not hasattr(mod, banned), f"registry module must not spawn ({banned})"


def test_no_registry_launch_spec_constrains_a_version() -> None:
    """No registry entry may constrain the version of the server it launches.

    The harness servers are released independently of this project, so every form
    of version constraint - exact pin, floor, ceiling, or compatible-release - in a
    launch spec stalls the ecosystem behind this project's upgrade cadence. The
    compatibility boundary is the declared tool surface, verified against the
    server's own ``tools/list``, so a constraint reappearing here is a regression
    caught in the suite rather than in a downstream consumer's blocked upgrade.
    """
    from .._acp_mcp import _KNOWN_MCP_SERVERS

    for name, entry in _KNOWN_MCP_SERVERS.items():
        assert isinstance(entry, MappingProxyType)
        args = entry.get("args")
        assert isinstance(args, tuple)
        for arg in args:
            assert isinstance(arg, str)
            assert not any(
                operator in arg for operator in ("==", ">=", "<=", "~=", "!=")
            ), f"{name} launch spec constrains a version: {arg!r}"


def test_rag_runtime_acquisition_executes_the_published_cli() -> None:
    """The resolved production launch command acquires a runnable MCP CLI."""
    spec = resolve_harness_mcp_servers(["vaultspec-rag"])[0]
    command = spec["command"]
    args = spec["args"]
    assert isinstance(command, str)
    assert isinstance(args, list)
    command_line = [command]
    for arg in args:
        assert isinstance(arg, str)
        command_line.append(arg)
    proc = subprocess.run(
        [*command_line, "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "vaultspec-search-mcp" in proc.stdout


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
    # Construction is network-free; the model is never invoked. A production
    # hosted model has no local MCP delivery surface, so composition must remain
    # an identity-preserving pass-through.
    model = ChatOpenAI(model="gpt-4o-mini", api_key=SecretStr("unused-test-key"))
    assert compose_harness_mcp_servers(model, ["vaultspec-rag"]) is model


def test_compose_advertises_the_declared_server() -> None:
    model = AcpChatModel(command=["echo"], env_vars={})
    composed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    assert isinstance(composed, AcpChatModel)
    assert [s["name"] for s in composed.mcp_servers] == ["vaultspec-rag"]


def test_compose_dispatches_to_codex_harness_delivery() -> None:
    # A Codex model has no with_mcp_servers but DOES have a harness delivery
    # mechanism (with_harness_mcp_servers); compose must thread the names to it,
    # never silently no-op. This is the seam whose silent no-op dropped the
    # preset's harness on the Codex lane.
    from ..codex_chat_model import CodexChatModel

    model = CodexChatModel(command=["codex", "app-server"])
    composed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    assert isinstance(composed, CodexChatModel)
    assert composed.harness_mcp_servers == ["vaultspec-rag"]


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
    session: list[JsonObject] = [
        {"name": "vaultspec-authoring", "command": "node", "args": ["bridge.js"]},
        {
            "name": "vaultspec-rag",
            "command": "uvx",
            "args": [
                "--from",
                "vaultspec-rag[mcp]",
                "vaultspec-search-mcp",
            ],
        },
    ]
    home = config_home_mcp_servers(session)
    assert set(home) == {"vaultspec-rag"}
    assert home["vaultspec-rag"] == {
        "type": "stdio",
        "command": "uvx",
        "args": [
            "--from",
            "vaultspec-rag[mcp]",
            "vaultspec-search-mcp",
        ],
    }


def test_config_home_servers_preserves_env_when_present() -> None:
    session: list[JsonObject] = [
        {"name": "vaultspec-rag", "command": "uvx", "args": ["x"], "env": {"K": "V"}},
    ]
    home = config_home_mcp_servers(session)
    assert home["vaultspec-rag"]["env"] == {"K": "V"}


def test_live_preset_harness_drives_read_only_rag_composition() -> None:
    """The live preset's declared harness composes exactly its read-only servers.

    The real ``vaultspec-adr-research`` preset's ``[team.harness]`` declaration
    flows through ``effective_harness`` into composition, so the opt-in makes RAG
    grounding live for its document roles. Walks the full chain preset harness ->
    effective_harness -> harness allowlist -> compose, and asserts the composed
    session advertises exactly the declared stdio servers while exactly their READ
    tools join the autonomous allowlist - no write verb anywhere, and no
    registry-only metadata leaking into the session payload.

    The declared names are READ from the preset rather than restated, so this
    proves the chain rather than a copy of the preset. What IS stated literally is
    the exclusion below, because that is the claim with a safety consequence.
    """
    from ...team.team_config import load_team_config

    cfg = load_team_config("vaultspec-adr-research")
    harness = cfg.effective_harness()
    assert harness is not None
    names = harness.mcp_servers

    # Every declared name is one the closed registry knows; an unknown one would
    # refuse below rather than surface, but naming the claim here says which of
    # the two failures a red line means.
    assert all(is_known_harness_server(name) for name in names)

    allow = harness_allowed_tool_names(names)
    assert allow == [
        "mcp__vaultspec-rag__search_vault",
        "mcp__vaultspec-rag__search_codebase",
        "mcp__vaultspec-rag__get_code_file",
    ]
    # Read-only boundary: no server's write verbs ever reach the allowlist.
    assert not any("reindex" in name for name in allow)

    model = AcpChatModel(command=["echo"], env_vars={})
    composed = compose_harness_mcp_servers(model, names, allowed_tools=allow)
    assert isinstance(composed, AcpChatModel)
    advertised: set[str] = set()
    for spec in composed.mcp_servers:
        name = spec.get("name")
        assert isinstance(name, str)
        advertised.add(name)
    assert advertised == set(names)
    for server_name in names:
        spec = next(
            spec for spec in composed.mcp_servers if spec.get("name") == server_name
        )
        assert spec["command"] == "uvx"
        # Registry-only ``tools`` metadata is stripped from the session launch spec.
        assert "tools" not in spec
    # Exactly the composed read tools are auto-permitted (autonomous-only surface).
    assert composed.allowed_tools == allow


def test_config_home_servers_empty_when_none_registry_known() -> None:
    session: list[JsonObject] = [{"name": "vaultspec-authoring", "command": "node"}]
    assert config_home_mcp_servers(session) == {}


def test_every_registry_entry_is_marked_read_only() -> None:
    # Trust-root invariant: only read-only servers exist in the registry, so a
    # drifted write-capable entry fails at test time before it can ever surface.
    from .._acp_mcp import _KNOWN_MCP_SERVERS

    # A loop over an empty registry asserts nothing, and "no entries" is exactly
    # what a broken registry looks like - so the entry this invariant is about is
    # named before it is iterated. Otherwise the strongest statement this test
    # could make about the trust root is that it holds vacuously.
    assert "vaultspec-rag" in _KNOWN_MCP_SERVERS, sorted(_KNOWN_MCP_SERVERS)

    for name, entry in _KNOWN_MCP_SERVERS.items():
        assert isinstance(entry, MappingProxyType)
        assert entry.get("read_only") is True, name


def test_codex_specs_resolves_read_only_registry_entry_with_tools() -> None:
    specs = codex_mcp_server_specs(["vaultspec-rag"])
    assert len(specs) == 1
    spec = specs[0]
    assert spec["name"] == "vaultspec-rag"
    assert spec["command"] == "uvx"
    assert spec["args"] == [
        "--from",
        "vaultspec-rag[mcp]",
        "vaultspec-search-mcp",
    ]
    # The read tools ride along for the Codex enabled_tools allowlist.
    assert spec["tools"] == ["search_vault", "search_codebase", "get_code_file"]


def test_codex_specs_unknown_name_raises() -> None:
    with pytest.raises(ConfigError):
        codex_mcp_server_specs(["does-not-exist"])


def test_compose_unknown_name_raises() -> None:
    model = AcpChatModel(command=["echo"], env_vars={})
    with pytest.raises(ConfigError):
        compose_harness_mcp_servers(model, ["totally-unknown"])


def test_compose_unknown_name_raises_even_on_non_acp_model() -> None:
    # An unknown declared name is a configuration error even when composition is
    # inapplicable: the loud refusal is uniform across model types, not swallowed
    # by the non-ACP pass-through.
    model = ChatOpenAI(model="gpt-4o-mini", api_key=SecretStr("unused-test-key"))
    with pytest.raises(ConfigError):
        compose_harness_mcp_servers(model, ["totally-unknown"])


class TestHarnessCompositionStages:
    """The resolve stage, exercised apart from projection after the split.

    Composition was one function doing resolution-and-validation then projection.
    The resolve stage is separable now, so the validate-first guarantee - an
    unknown name is refused before any delivery is attempted - can be asserted
    directly rather than only through a composed model.
    """

    def test_resolve_refuses_an_unknown_name_before_projection(self) -> None:
        from .._acp_mcp import HarnessMcpRuntimeProfile, _resolve_harness_composition

        model = ChatOpenAI(model="gpt-4o-mini", api_key=SecretStr("unused-test-key"))
        with pytest.raises(ConfigError):
            _resolve_harness_composition(
                model,
                ["not-a-real-server"],
                profile=HarnessMcpRuntimeProfile.NON_DESKTOP,
            )

    def test_resolve_returns_specs_for_a_known_name(self) -> None:
        from .._acp_mcp import HarnessMcpRuntimeProfile, _resolve_harness_composition

        model = AcpChatModel(command=["echo"], env_vars={})
        resolution, unavailable, resolved = _resolve_harness_composition(
            model, ["vaultspec-rag"], profile=HarnessMcpRuntimeProfile.NON_DESKTOP
        )

        assert "vaultspec-rag" in resolution.available_servers
        assert unavailable == set()
        assert [s["name"] for s in resolved] == ["vaultspec-rag"]


class TestComposeNativeReadTools:
    """The native-read composition is exact, role-scoped, and autonomous-only."""

    def _fresh_model(self) -> AcpChatModel:
        return AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")

    def test_autonomous_document_role_unions_read_names(self) -> None:
        wired = compose_native_read_tools(
            self._fresh_model(), autonomous=True, role="researcher"
        )
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == list(NATIVE_READ_TOOL_NAMES)

    def test_non_document_role_is_unchanged(self) -> None:
        model = self._fresh_model()
        wired = compose_native_read_tools(model, autonomous=True, role=None)
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == []

    def test_human_in_loop_is_unchanged(self) -> None:
        model = self._fresh_model()
        wired = compose_native_read_tools(model, autonomous=False, role="researcher")
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == []

    def test_existing_allowlist_is_preserved_and_deduped(self) -> None:
        model = self._fresh_model().model_copy(
            update={"allowed_tools": ["mcp__x__y", "Read"]}
        )
        wired = compose_native_read_tools(model, autonomous=True, role="synthesist")
        assert isinstance(wired, AcpChatModel)
        # Pre-existing entries kept in place; only the missing read names appended.
        assert wired.allowed_tools == ["mcp__x__y", "Read", "Grep", "Glob"]

    def test_advertised_mcp_servers_survive_the_allowlist_union(self) -> None:
        """The read grant must not clear a server the authoring attach advertised."""
        model = self._fresh_model().model_copy(
            update={"mcp_servers": [{"name": "vaultspec-authoring", "type": "http"}]}
        )
        wired = compose_native_read_tools(model, autonomous=True, role="researcher")
        assert isinstance(wired, AcpChatModel)
        assert wired.mcp_servers == [{"name": "vaultspec-authoring", "type": "http"}]
        assert wired.allowed_tools == list(NATIVE_READ_TOOL_NAMES)

    def test_model_without_acp_surface_is_returned_unchanged(self) -> None:
        """A hosted model exposing no with_mcp_servers is passed through as-is."""
        model = ChatOpenAI(api_key=SecretStr("test-key"), model="gpt-4o")
        wired = compose_native_read_tools(model, autonomous=True, role="researcher")
        assert wired is model
