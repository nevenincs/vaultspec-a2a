"""The trust root's network-egress axis, proven at the real composition seams.

Real objects only, no mocks and no patching. The refusals are driven through the
production calls themselves: the registry constructor that builds the shipped
``_KNOWN_MCP_SERVERS``, the native-tool composition the worker node performs at
spawn, and the config-home writers that render the real ``.claude.json`` and
Codex ``config.toml`` on disk.

The axis exists because ``read_only`` and network reach are independent: a
fetch/search tool writes nothing locally while still able to carry workspace
content outward in a URL, so a surface that satisfies the local-write assertion
says nothing at all about whether it egresses.

The same trust root is only worth as much as the structures that carry it, so the
final classes here prove those structures are frozen: an axis declaration that any
importer could add at runtime is not a declaration, and the guards downstream of it
are only meaningful if the catalog they consult cannot be edited underneath them.
"""

from __future__ import annotations

import json
import tomllib
from typing import TYPE_CHECKING, Any, cast

import pytest

from ...thread.errors import ConfigError
from ...utils.enums import CodexWebSearchMode
from .._acp_config_home import cleanup_isolated_config_home, create_isolated_config_home
from .._acp_mcp import (
    _KNOWN_MCP_SERVERS,
    NATIVE_READ_TOOL_NAMES,
    NATIVE_TOOL_EGRESS,
    _declare_registry,
    codex_mcp_server_specs,
    compose_harness_mcp_servers,
    compose_native_read_tools,
    config_home_mcp_servers,
    harness_allowed_tool_names,
    resolve_harness_mcp_servers,
)
from .._codex_config_home import build_codex_config_home, cleanup_codex_config_home
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_RAG = "vaultspec-rag"


def _as_an_importer_sees_it(structure: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a declaration structure the way a would-be declarer would bind it.

    The freeze is a RUNTIME property; the annotation only advertises it, and a
    module that imports one of these names is free to bind it as a plain ``dict``
    and assign. That is precisely the attempt under test, so the cast is how the
    attempt gets made at all - a statically refused statement would prove nothing
    about what the object does when the assignment actually runs.
    """
    return cast("dict[str, Any]", structure)


def _entry(**overrides: Any) -> dict[str, dict[str, Any]]:
    """A registry-shaped candidate entry, minus whatever the caller drops."""
    entry: dict[str, Any] = {
        "name": "candidate",
        "command": "uvx",
        "args": ["--from", "candidate", "candidate-mcp"],
        "tools": ("search",),
        "read_only": True,
        "network_egress": False,
    }
    entry.update(overrides)
    for key, value in list(entry.items()):
        if value is None:
            del entry[key]
    return {"candidate": entry}


class TestRegistryDeclarationRefusal:
    """The registry constructor refuses an entry that never stated its reach."""

    def test_entry_with_no_declared_egress_is_refused(self) -> None:
        # The production constructor that builds the shipped registry, given an
        # entry that declares only the local-write axis. An undeclared reach must
        # make the entry unconstructible, not merely unsurfaceable.
        with pytest.raises(ConfigError) as excinfo:
            _declare_registry(_entry(network_egress=None))
        message = str(excinfo.value)
        assert "candidate" in message
        assert "network_egress" in message

    def test_entry_with_no_declared_local_write_is_still_refused(self) -> None:
        # The pre-existing axis keeps its own failure mode after the split.
        with pytest.raises(ConfigError) as excinfo:
            _declare_registry(_entry(read_only=None))
        assert "read_only" in str(excinfo.value)

    def test_non_boolean_egress_declaration_is_refused(self) -> None:
        # A truthy-but-unstructured value ("no", 0, "false") is not a declaration;
        # accepting it would let a string that READS as no-egress assert egress.
        with pytest.raises(ConfigError) as excinfo:
            _declare_registry(_entry(network_egress="no"))
        assert "network_egress" in str(excinfo.value)

    def test_a_fully_declared_entry_is_admitted_unchanged(self) -> None:
        declared = _declare_registry(_entry())
        assert declared["candidate"]["network_egress"] is False

    def test_an_entry_may_declare_that_it_does_egress(self) -> None:
        # The axis is expressive, not prohibitive: an outward-reaching entry is
        # admissible precisely because it can now be stated rather than hidden
        # behind a read-only-only assertion.
        declared = _declare_registry(_entry(network_egress=True))
        assert declared["candidate"]["network_egress"] is True

    def test_the_shipped_registry_declares_both_axes(self) -> None:
        for name, entry in _KNOWN_MCP_SERVERS.items():
            assert entry.get("read_only") is True, name
            assert isinstance(entry.get("network_egress"), bool), name
        # The migrated sole entry serves the local vault over stdio.
        assert _KNOWN_MCP_SERVERS[_RAG]["network_egress"] is False


class TestSpawnCompositionRefusesUndeclaredNativeTools:
    """The worker's spawn composition refuses a tool set with no declared reach."""

    def _model(self) -> AcpChatModel:
        return AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")

    def test_undeclared_native_tool_is_refused_at_the_composition_seam(self) -> None:
        # The exact production call the worker node makes at spawn, composing a
        # built-in whose egress axis was never declared. WebFetch is the real
        # motivating case: it writes nothing locally, so the local-write axis
        # would have admitted it silently.
        model = self._model()
        with pytest.raises(ConfigError) as excinfo:
            compose_native_read_tools(
                model,
                autonomous=True,
                role="researcher",
                extra_tool_names=("WebFetch",),
            )
        message = str(excinfo.value)
        assert "WebFetch" in message
        assert "egress" in message
        # The refusal is total: nothing was projected onto the session first.
        assert model.allowed_tools == []

    def test_the_refusal_names_every_undeclared_tool(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            compose_native_read_tools(
                self._model(),
                autonomous=True,
                role="researcher",
                extra_tool_names=("WebSearch", "WebFetch"),
            )
        message = str(excinfo.value)
        assert "WebSearch" in message
        assert "WebFetch" in message

    def test_refusal_precedes_the_autonomy_and_role_gates(self) -> None:
        # Validate-first: an undeclared tool set is a configuration error on every
        # run, not only on the runs where composition happens to apply. Otherwise
        # the gap would surface for the first time on a document role in
        # production, having passed every supervised and non-document run.
        for autonomous, role in ((True, None), (False, "researcher"), (False, None)):
            with pytest.raises(ConfigError):
                compose_native_read_tools(
                    self._model(),
                    autonomous=autonomous,
                    role=role,
                    extra_tool_names=("WebFetch",),
                )

    def test_refusal_applies_to_a_model_with_no_acp_surface(self) -> None:
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(model="gpt-4o-mini", api_key="unused-test-key")
        with pytest.raises(ConfigError):
            compose_native_read_tools(
                model,
                autonomous=True,
                role="researcher",
                extra_tool_names=("WebFetch",),
            )

    def test_the_declared_read_floor_still_composes(self) -> None:
        # The migration leaves the shipped floor green: every floor name declares
        # no-egress, so the default worker call is unchanged.
        wired = compose_native_read_tools(
            self._model(), autonomous=True, role="researcher"
        )
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == list(NATIVE_READ_TOOL_NAMES)
        assert all(NATIVE_TOOL_EGRESS[name] is False for name in NATIVE_READ_TOOL_NAMES)


class TestConfigHomeCarriesTheDeclaredAxis:
    """The real config-home writers surface only entries that declared the axis."""

    def test_claude_config_home_written_from_the_composed_session(self) -> None:
        """Walks worker spawn composition -> config home -> the real .claude.json.

        The production chain: the worker composes the declared harness servers and
        the native read floor onto the model, ``AcpChatModel`` then selects the
        registry-known servers for the isolated home, and the home is written to
        disk. Every name that survives to the file passed the two-axis trust root.
        """
        model = compose_harness_mcp_servers(
            AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws"),
            [_RAG],
            allowed_tools=harness_allowed_tool_names([_RAG]),
        )
        assert isinstance(model, AcpChatModel)
        model = compose_native_read_tools(model, autonomous=True, role="researcher")
        assert isinstance(model, AcpChatModel)

        surfacing = config_home_mcp_servers(model.mcp_servers)
        home = create_isolated_config_home(surfacing)
        try:
            cfg = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
        finally:
            cleanup_isolated_config_home(home)

        assert set(cfg["mcpServers"]) == {_RAG}
        # Nothing reached the file that had not declared both axes.
        for name in cfg["mcpServers"]:
            assert _KNOWN_MCP_SERVERS[name]["read_only"] is True
            assert _KNOWN_MCP_SERVERS[name]["network_egress"] is False
        # Registry-only trust metadata never leaks into the surfaced shape.
        assert "network_egress" not in cfg["mcpServers"][_RAG]
        assert "read_only" not in cfg["mcpServers"][_RAG]

    def test_codex_config_home_carries_the_same_trust_root(
        self, tmp_path: Path
    ) -> None:
        # The second transport reads the same registry through the same guard, so
        # the axis cannot be satisfied on one delivery shape and skipped on the
        # other.
        specs = codex_mcp_server_specs([_RAG])
        # The web posture is a required argument on this builder (unsafe-by-
        # omission, like the trust axes this test covers); this case is about the
        # registry's axes, so it declares the closed posture explicitly.
        home = build_codex_config_home(
            specs, tmp_path, web_search=CodexWebSearchMode.DISABLED
        )
        try:
            config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        finally:
            cleanup_codex_config_home(home)

        assert set(config["mcp_servers"]) == {_RAG}
        assert _KNOWN_MCP_SERVERS[_RAG]["network_egress"] is False
        # The emitted Codex spec carries launch + allowlist fields only.
        assert "network_egress" not in specs[0]


class TestNativeEgressCatalogRefusesRuntimeDeclaration:
    """The exported egress catalog cannot be declared into at runtime."""

    def _model(self) -> AcpChatModel:
        return AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")

    def test_declaring_a_web_tool_at_runtime_is_refused(self) -> None:
        # The attack the mutable catalog allowed: membership IS the declaration,
        # so one assignment from any importer would have declared the CLI's
        # outward-reaching fetch built-in local and walked it through the
        # composition guard, which consults exactly this mapping.
        with pytest.raises(TypeError):
            _as_an_importer_sees_it(NATIVE_TOOL_EGRESS)["WebFetch"] = False

        assert "WebFetch" not in NATIVE_TOOL_EGRESS
        # The refusal is not merely cosmetic: the production composition seam still
        # rejects the name after the attempt, which is the property that matters.
        with pytest.raises(ConfigError):
            compose_native_read_tools(
                self._model(),
                autonomous=True,
                role="researcher",
                extra_tool_names=("WebFetch",),
            )

    def test_redeclaring_a_floor_tool_as_egressing_is_refused(self) -> None:
        # Overwriting an existing declaration is the same defect from the other
        # direction - it would let a caller relabel a tool the floor already
        # composes rather than smuggle a new one in.
        with pytest.raises(TypeError):
            _as_an_importer_sees_it(NATIVE_TOOL_EGRESS)["Read"] = True
        assert NATIVE_TOOL_EGRESS["Read"] is False

    def test_withdrawing_a_declaration_is_refused(self) -> None:
        with pytest.raises(TypeError):
            del _as_an_importer_sees_it(NATIVE_TOOL_EGRESS)["Read"]
        assert set(NATIVE_READ_TOOL_NAMES) <= set(NATIVE_TOOL_EGRESS)


class TestHarnessRegistryRefusesRuntimeDeclaration:
    """The harness registry is closed by design AND frozen in fact."""

    def test_declaring_a_server_at_runtime_is_refused(self) -> None:
        with pytest.raises(TypeError):
            _as_an_importer_sees_it(_KNOWN_MCP_SERVERS)["candidate"] = _entry()[
                "candidate"
            ]

        assert "candidate" not in _KNOWN_MCP_SERVERS
        # Still unknown at the production resolver, which is what "closed" means.
        with pytest.raises(ConfigError) as excinfo:
            resolve_harness_mcp_servers(["candidate"])
        assert "candidate" in str(excinfo.value)

    def test_flipping_a_declared_trust_axis_is_refused(self) -> None:
        # Freezing only the outer mapping would leave the axes themselves writable,
        # which defeats the trust root just as completely as adding an entry.
        entry = _as_an_importer_sees_it(_KNOWN_MCP_SERVERS[_RAG])
        with pytest.raises(TypeError):
            entry["read_only"] = False
        with pytest.raises(TypeError):
            entry["network_egress"] = True
        assert _KNOWN_MCP_SERVERS[_RAG]["read_only"] is True
        assert _KNOWN_MCP_SERVERS[_RAG]["network_egress"] is False

    def test_the_launch_command_line_is_immutable(self) -> None:
        # The registry declares the argv that is actually executed, so a mutable
        # interior is a reachable interior even when membership is sealed.
        with pytest.raises(AttributeError):
            _KNOWN_MCP_SERVERS[_RAG]["args"].append("--from=elsewhere")
        assert "--from=elsewhere" not in _KNOWN_MCP_SERVERS[_RAG]["args"]

    def test_a_resolved_launch_spec_is_a_detached_mutable_copy(self) -> None:
        # The wire shape downstream consumers expect is unchanged (plain list), and
        # mutating what a caller was handed cannot reach the registry through a
        # shared interior.
        spec = resolve_harness_mcp_servers([_RAG])[0]
        assert isinstance(spec["args"], list)
        spec["args"].append("--from=elsewhere")

        assert "--from=elsewhere" not in resolve_harness_mcp_servers([_RAG])[0]["args"]
        assert "--from=elsewhere" not in _KNOWN_MCP_SERVERS[_RAG]["args"]


class TestConstructionSeamIsTheOnlyWayIn:
    """What the constructor does and does not decide, stated as executable claims."""

    def test_the_constructor_freezes_what_it_admits(self) -> None:
        declared = _declare_registry(_entry())
        with pytest.raises(TypeError):
            _as_an_importer_sees_it(declared)["other"] = {}
        with pytest.raises(TypeError):
            _as_an_importer_sees_it(declared["candidate"])["read_only"] = False
        assert isinstance(declared["candidate"]["args"], tuple)

    def test_the_constructor_admits_a_non_read_only_entry(self) -> None:
        # The premise behind keeping ``_require_read_only`` at the surfacing seams.
        # The constructor validates that both axes were DECLARED; it deliberately
        # does not constrain what was declared, so a write-capable entry is
        # constructible and only the seam guard refuses to surface it. That guard
        # is therefore live enforcement of a policy nothing else decides - unlike
        # the egress assertion, which re-applies the constructor's own predicate.
        declared = _declare_registry(_entry(read_only=False))
        assert declared["candidate"]["read_only"] is False
