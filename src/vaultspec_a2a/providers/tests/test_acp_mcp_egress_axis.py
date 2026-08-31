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

import tomllib
from collections.abc import MutableMapping
from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from ...thread.errors import ConfigError
from ...utils.enums import CodexWebSearchMode
from .._acp_authoring import AUTHORING_MCP_SERVER_NAME
from .._acp_mcp import (
    _KNOWN_MCP_SERVERS,
    NATIVE_READ_TOOL_NAMES,
    NATIVE_TOOL_EGRESS,
    NATIVE_WEB_TOOL_BOUNDS,
    HarnessMcpRuntimeProfile,
    NativeToolBoundHolder,
    NativeToolDomainPosture,
    NativeWebToolBounds,
    _declare_registry,
    _require_bounds_match_the_egress_axis,
    codex_mcp_server_specs,
    compose_harness_mcp_servers,
    compose_native_read_tools,
    harness_allowed_tool_names,
    harness_server_egresses,
    require_declared_surface,
    resolve_harness_mcp_capabilities,
    resolve_harness_mcp_servers,
)
from .._codex_config_home import build_codex_config_home, cleanup_codex_config_home
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import (
        FrozenJsonObject,
        FrozenJsonValue,
        JsonObject,
        JsonValue,
    )

_RAG = "vaultspec-rag"

# An outward-reaching built-in this tree has never heard of. It stands for the
# live hazard the no-pinning house rule accepts: the provider ships a new web
# built-in, a lane's proof names it, and it must be refused until somebody states
# its reach here - membership IS the declaration, so an unknown name can never be
# admitted on the strength of looking like one that was.
_UNDECLARED_WEB_TOOL = "WebCrawl"
_ALSO_UNDECLARED_WEB_TOOL = "WebScrape"

# A built-in the CLI genuinely ships and this tree deliberately does not declare.
# The refusal is not about whether a name is real; it is about whether its reach
# was stated.
_UNDECLARED_SHIPPED_TOOL = "Bash"


def _frozen_object(value: FrozenJsonValue) -> FrozenJsonObject:
    assert isinstance(value, MappingProxyType)
    return value


def _entry(**overrides: JsonValue) -> JsonObject:
    """A registry-shaped candidate entry, minus whatever the caller drops.

    An override of ``None`` DROPS its key, which is how a case here asks for an
    undeclared axis. That spelling is unavailable for the root-pin axis, whose
    declared-unpinnable value IS ``None``: dropping the key and declaring it null
    are different facts to the constructor, and only the first is an omission.
    A case wanting the unpinnable shape declares it against the constructor
    directly rather than through this helper.
    """
    entry: JsonObject = {
        "name": "candidate",
        "command": "uvx",
        "args": ["--from", "candidate", "candidate-mcp"],
        "tools": ["search"],
        "read_only": True,
        "network_egress": False,
        # Fully declared on every axis, so a case about one axis is never
        # answered by a refusal from another.
        "root_pin": "CANDIDATE_ROOT",
        "exact_surface": False,
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
        assert _frozen_object(declared["candidate"])["network_egress"] is False

    def test_an_entry_may_declare_that_it_does_egress(self) -> None:
        # The axis is expressive, not prohibitive: an outward-reaching entry is
        # admissible precisely because it can now be stated rather than hidden
        # behind a read-only-only assertion.
        declared = _declare_registry(_entry(network_egress=True))
        assert _frozen_object(declared["candidate"])["network_egress"] is True

    def test_the_shipped_registry_declares_both_axes(self) -> None:
        for name, entry in _KNOWN_MCP_SERVERS.items():
            assert isinstance(entry, MappingProxyType)
            assert entry.get("read_only") is True, name
            assert isinstance(entry.get("network_egress"), bool), name
        # The migrated sole entry serves the local vault over stdio.
        assert _frozen_object(_KNOWN_MCP_SERVERS[_RAG])["network_egress"] is False


class TestSpawnCompositionRefusesUndeclaredNativeTools:
    """The worker's spawn composition refuses a tool set with no declared reach."""

    def _model(self) -> AcpChatModel:
        return AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")

    def test_undeclared_native_tool_is_refused_at_the_composition_seam(self) -> None:
        # The exact production call the worker node makes at spawn, composing a
        # built-in whose egress axis was never declared. An outward-reaching one is
        # the motivating case: it writes nothing locally, so the local-write axis
        # would have admitted it silently.
        model = self._model()
        with pytest.raises(ConfigError) as excinfo:
            compose_native_read_tools(
                model,
                autonomous=True,
                role="researcher",
                extra_tool_names=(_UNDECLARED_WEB_TOOL,),
            )
        message = str(excinfo.value)
        assert _UNDECLARED_WEB_TOOL in message
        assert "egress" in message
        # The refusal is total: nothing was projected onto the session first.
        assert model.allowed_tools == []

    def test_a_shipped_but_undeclared_builtin_is_refused_too(self) -> None:
        # Being a real tool the CLI compiles in earns nothing here. The floor is
        # three names because three names stated their reach, not because the
        # others are unknown to the provider.
        with pytest.raises(ConfigError) as excinfo:
            compose_native_read_tools(
                self._model(),
                autonomous=True,
                role="researcher",
                extra_tool_names=(_UNDECLARED_SHIPPED_TOOL,),
            )
        assert _UNDECLARED_SHIPPED_TOOL in str(excinfo.value)

    def test_the_refusal_names_every_undeclared_tool(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            compose_native_read_tools(
                self._model(),
                autonomous=True,
                role="researcher",
                extra_tool_names=(_UNDECLARED_WEB_TOOL, _ALSO_UNDECLARED_WEB_TOOL),
            )
        message = str(excinfo.value)
        assert _UNDECLARED_WEB_TOOL in message
        assert _ALSO_UNDECLARED_WEB_TOOL in message

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
                    extra_tool_names=(_UNDECLARED_WEB_TOOL,),
                )

    def test_refusal_applies_to_a_model_with_no_acp_surface(self) -> None:
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(model="gpt-4o-mini", api_key=SecretStr("unused-test-key"))
        with pytest.raises(ConfigError):
            compose_native_read_tools(
                model,
                autonomous=True,
                role="researcher",
                extra_tool_names=(_UNDECLARED_WEB_TOOL,),
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


class TestSessionSurfaceCarriesTheDeclaredAxis:
    """The real surfacing emitters admit only entries that declared the axis."""

    def test_claude_session_surface_from_the_composed_model(
        self, tmp_path: Path
    ) -> None:
        """Walks worker spawn composition -> the declared-surface session guard.

        The production chain: the worker composes the declared harness servers
        and the native read floor onto the model; the session seam then guards
        the advertisement with :func:`require_declared_surface`, the same
        allowlist the strict claude CLI mounts verbatim. Every name that
        survives to the session passed the two-axis trust root.
        """
        model = compose_harness_mcp_servers(
            AcpChatModel(command=["echo"], env_vars={}, workspace_root=str(tmp_path)),
            [_RAG],
            allowed_tools=harness_allowed_tool_names([_RAG]),
        )
        assert isinstance(model, AcpChatModel)
        model = compose_native_read_tools(model, autonomous=True, role="researcher")
        assert isinstance(model, AcpChatModel)

        require_declared_surface(
            model.mcp_servers, bridge_name=AUTHORING_MCP_SERVER_NAME
        )
        registry_entry = _frozen_object(_KNOWN_MCP_SERVERS[_RAG])
        assert registry_entry["read_only"] is True
        assert registry_entry["network_egress"] is False
        # Registry-only trust metadata never leaks into the advertised shape.
        names: list[str] = []
        for spec in model.mcp_servers:
            name = spec.get("name")
            assert isinstance(name, str)
            names.append(name)
            assert "network_egress" not in spec
            assert "read_only" not in spec
            assert "tools" not in spec
        assert names == [_RAG]

    def test_an_undeclared_entry_is_refused_at_the_session_guard(self) -> None:
        # The same guard refuses an entry the registry never admitted, which on
        # the strict lane is the difference between a reviewed mount and an
        # arbitrary one.
        with pytest.raises(ConfigError) as excinfo:
            require_declared_surface(
                [{"name": "operator-extra", "command": "npx"}],
                bridge_name=AUTHORING_MCP_SERVER_NAME,
            )
        assert "operator-extra" in str(excinfo.value)

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
        assert _frozen_object(_KNOWN_MCP_SERVERS[_RAG])["network_egress"] is False
        # The emitted Codex spec carries launch + allowlist fields only.
        assert "network_egress" not in specs[0]


class TestNativeEgressCatalogRefusesRuntimeDeclaration:
    """The exported egress catalog cannot be declared into at runtime."""

    def _model(self) -> AcpChatModel:
        return AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")

    def test_declaring_a_web_tool_at_runtime_is_refused(self) -> None:
        # The attack the mutable catalog allowed: membership IS the declaration,
        # so one assignment from any importer would have declared an unknown
        # outward-reaching built-in local and walked it through the composition
        # guard, which consults exactly this mapping.
        assert isinstance(NATIVE_TOOL_EGRESS, MappingProxyType)
        assert not isinstance(NATIVE_TOOL_EGRESS, MutableMapping)

        assert _UNDECLARED_WEB_TOOL not in NATIVE_TOOL_EGRESS
        # The refusal is not merely cosmetic: the production composition seam still
        # rejects the name after the attempt, which is the property that matters.
        with pytest.raises(ConfigError):
            compose_native_read_tools(
                self._model(),
                autonomous=True,
                role="researcher",
                extra_tool_names=(_UNDECLARED_WEB_TOOL,),
            )

    def test_relabelling_a_declared_web_tool_as_local_is_refused(self) -> None:
        # The same attack against a tool that IS declared, and the sharper of the
        # two now that the web built-ins are in the catalog: flipping the fetch
        # tool's axis to false would not add a name, it would strip the reach off
        # one already composable and drop it into the local read floor's
        # assumptions - including the bounds guard, which only fires on names the
        # axis marks as egressing.
        assert isinstance(NATIVE_TOOL_EGRESS, MappingProxyType)
        assert not isinstance(NATIVE_TOOL_EGRESS, MutableMapping)
        assert NATIVE_TOOL_EGRESS["WebFetch"] is True
        assert NATIVE_TOOL_EGRESS["WebSearch"] is True

    def test_redeclaring_a_floor_tool_as_egressing_is_refused(self) -> None:
        # Overwriting an existing declaration is the same defect from the other
        # direction - it would let a caller relabel a tool the floor already
        # composes rather than smuggle a new one in.
        assert isinstance(NATIVE_TOOL_EGRESS, MappingProxyType)
        assert not isinstance(NATIVE_TOOL_EGRESS, MutableMapping)
        assert NATIVE_TOOL_EGRESS["Read"] is False

    def test_withdrawing_a_declaration_is_refused(self) -> None:
        assert isinstance(NATIVE_TOOL_EGRESS, MappingProxyType)
        assert not isinstance(NATIVE_TOOL_EGRESS, MutableMapping)
        assert set(NATIVE_READ_TOOL_NAMES) <= set(NATIVE_TOOL_EGRESS)


class TestEgressingBuiltinsMustStateTheirBounds:
    """Stated reach is half a declaration; how far it may go per branch is the rest."""

    def _model(self) -> AcpChatModel:
        return AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")

    def test_every_egressing_builtin_declares_bounds(self) -> None:
        egressing = {name for name, reaches in NATIVE_TOOL_EGRESS.items() if reaches}
        assert egressing == set(NATIVE_WEB_TOOL_BOUNDS)
        assert egressing == {"WebSearch", "WebFetch"}

    def test_no_local_builtin_carries_web_bounds(self) -> None:
        # The bounds declaration governs outward reach and nothing else; a bound on
        # a local tool would be a rule with no enforcement path behind it.
        for name in NATIVE_READ_TOOL_NAMES:
            assert name not in NATIVE_WEB_TOOL_BOUNDS

    def test_the_declared_bounds_are_the_decided_ones(self) -> None:
        search = NATIVE_WEB_TOOL_BOUNDS["WebSearch"]
        fetch = NATIVE_WEB_TOOL_BOUNDS["WebFetch"]
        assert search.max_uses_per_branch == 8
        assert fetch.max_uses_per_branch == 16
        # Who holds each bound is part of the decision, not an implementation note:
        # a provider-held bound is re-verified against the binary, while a
        # channel-held one is ours to change and ours to keep honest.
        assert search.uses_held_by is NativeToolBoundHolder.PROVIDER
        assert fetch.uses_held_by is NativeToolBoundHolder.CITATION_CHANNEL
        assert search.content_held_by is NativeToolBoundHolder.PROVIDER
        assert fetch.content_held_by is NativeToolBoundHolder.PROVIDER
        assert search.domain_posture is NativeToolDomainPosture.BLOCKLIST
        assert fetch.domain_posture is NativeToolDomainPosture.BLOCKLIST

    def test_the_fetch_budget_and_the_citation_cap_are_one_number(self) -> None:
        """The fetch bound has no provider knob, so the citation channel holds it.

        Imported from the finding contract rather than restated, because the whole
        claim is that a branch cannot cite more retrievals than it may make. Two
        independently-edited copies of 16 would let the bound drift out from under
        the tool that has no other limit.
        """
        from ...graph.nodes.diverge import MAX_WEB_LOCATORS_PER_FINDING

        fetch = NATIVE_WEB_TOOL_BOUNDS["WebFetch"]
        assert fetch.uses_held_by is NativeToolBoundHolder.CITATION_CHANNEL
        assert fetch.max_uses_per_branch == MAX_WEB_LOCATORS_PER_FINDING

    def test_an_egressing_tool_without_bounds_is_refused_at_import(self) -> None:
        # The production guard, run against a declaration pair that disagrees.
        # Reaching it in the shipped tree is impossible by construction - that IS
        # the property - so the disagreement is supplied rather than provoked, and
        # the same call runs at import over the real declarations.
        with pytest.raises(ConfigError) as excinfo:
            _require_bounds_match_the_egress_axis(
                {"Read": False, "WebSearch": True, "WebFetch": True},
                {"WebSearch": NATIVE_WEB_TOOL_BOUNDS["WebSearch"]},
            )
        assert "WebFetch" in str(excinfo.value)

    def test_bounds_for_a_tool_that_never_declared_egress_are_refused(self) -> None:
        # The mirror defect: a bound nothing enforces, because the guard that reads
        # it only ever fires on names the egress axis marks as reaching outward.
        with pytest.raises(ConfigError) as excinfo:
            _require_bounds_match_the_egress_axis(
                {"Read": False},
                {
                    "Read": NativeWebToolBounds(
                        max_uses_per_branch=1,
                        uses_held_by=NativeToolBoundHolder.PROVIDER,
                        content_held_by=NativeToolBoundHolder.PROVIDER,
                        domain_posture=NativeToolDomainPosture.BLOCKLIST,
                    )
                },
            )
        assert "Read" in str(excinfo.value)

    def test_the_bounds_catalog_cannot_be_declared_into_at_runtime(self) -> None:
        # Same reasoning as the egress catalog: a guard is worth what its catalog
        # is worth, and a mutable one would let an importer widen a use cap or flip
        # the domain posture to an allowlist with a single assignment.
        assert isinstance(NATIVE_WEB_TOOL_BOUNDS, MappingProxyType)
        assert not isinstance(NATIVE_WEB_TOOL_BOUNDS, MutableMapping)
        assert _UNDECLARED_WEB_TOOL not in NATIVE_WEB_TOOL_BOUNDS

    def test_a_declared_bound_is_itself_immutable(self) -> None:
        fetch = NATIVE_WEB_TOOL_BOUNDS["WebFetch"]
        field_name = "max_uses_per_branch"
        with pytest.raises(FrozenInstanceError):
            setattr(fetch, field_name, 4096)
        assert fetch.max_uses_per_branch == 16

    def test_a_fully_declared_web_tool_composes(self) -> None:
        # The lit path through the production seam: both declarations satisfied, an
        # autonomous document role, and the names land on the session by exact name.
        wired = compose_native_read_tools(
            self._model(),
            autonomous=True,
            role="researcher",
            extra_tool_names=("WebSearch", "WebFetch"),
        )
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == [*NATIVE_READ_TOOL_NAMES, "WebSearch", "WebFetch"]


class TestHarnessRegistryRefusesRuntimeDeclaration:
    """The harness registry is closed by design AND frozen in fact."""

    def test_declaring_a_server_at_runtime_is_refused(self) -> None:
        assert isinstance(_KNOWN_MCP_SERVERS, MappingProxyType)
        assert not isinstance(_KNOWN_MCP_SERVERS, MutableMapping)

        assert "candidate" not in _KNOWN_MCP_SERVERS
        # Still unknown at the production resolver, which is what "closed" means.
        with pytest.raises(ConfigError) as excinfo:
            resolve_harness_mcp_servers(["candidate"])
        assert "candidate" in str(excinfo.value)

    def test_flipping_a_declared_trust_axis_is_refused(self) -> None:
        # Freezing only the outer mapping would leave the axes themselves writable,
        # which defeats the trust root just as completely as adding an entry.
        entry = _frozen_object(_KNOWN_MCP_SERVERS[_RAG])
        assert isinstance(entry, MappingProxyType)
        assert not isinstance(entry, MutableMapping)
        assert entry["read_only"] is True
        assert entry["network_egress"] is False

    def test_the_launch_command_line_is_immutable(self) -> None:
        # The registry declares the argv that is actually executed, so a mutable
        # interior is a reachable interior even when membership is sealed.
        args = _frozen_object(_KNOWN_MCP_SERVERS[_RAG])["args"]
        assert isinstance(args, tuple)
        assert "--from=elsewhere" not in args

    def test_a_resolved_launch_spec_is_a_detached_mutable_copy(self) -> None:
        # The wire shape downstream consumers expect is unchanged (plain list), and
        # mutating what a caller was handed cannot reach the registry through a
        # shared interior.
        spec = resolve_harness_mcp_servers([_RAG])[0]
        args = spec["args"]
        assert isinstance(args, list)
        args.append("--from=elsewhere")

        resolved_args = resolve_harness_mcp_servers([_RAG])[0]["args"]
        assert isinstance(resolved_args, list)
        assert "--from=elsewhere" not in resolved_args
        registry_args = _frozen_object(_KNOWN_MCP_SERVERS[_RAG])["args"]
        assert isinstance(registry_args, tuple)
        assert "--from=elsewhere" not in registry_args


class TestConstructionSeamIsTheOnlyWayIn:
    """What the constructor does and does not decide, stated as executable claims."""

    def test_the_constructor_freezes_what_it_admits(self) -> None:
        declared = _declare_registry(_entry())
        assert isinstance(declared, MappingProxyType)
        assert not isinstance(declared, MutableMapping)
        candidate = _frozen_object(declared["candidate"])
        assert isinstance(candidate, MappingProxyType)
        assert not isinstance(candidate, MutableMapping)
        assert isinstance(candidate["args"], tuple)

    def test_the_constructor_admits_a_non_read_only_entry(self) -> None:
        # The premise behind keeping ``_require_read_only`` at the surfacing seams.
        # The constructor validates that both axes were DECLARED; it deliberately
        # does not constrain what was declared, so a write-capable entry is
        # constructible and only the seam guard refuses to surface it. That guard
        # is therefore live enforcement of a policy nothing else decides - unlike
        # the egress assertion, which re-applies the constructor's own predicate.
        declared = _declare_registry(_entry(read_only=False))
        assert _frozen_object(declared["candidate"])["read_only"] is False


class TestTheLaneGatesTheEgressAxis:
    """The harness axis admits outward reach only on a lane that proved it.

    Reachability had been gated on the NATIVE read-floor axis and not at all on
    the harness ``mcp_servers`` axis, so a declared server was composed on every
    lane - including one with no completed-turn proof, and a model declaring no
    lane at all. The gate lives in the resolution stage every composition passes
    through, so it cannot be skipped by a caller that forgot to ask.

    The exhaustiveness claim below is load-bearing rather than decorative. No
    shipped registry entry declares egress today, so the REFUSAL branch has
    nothing live to fire against and cannot be driven end to end through the
    frozen registry - deliberately frozen, since an axis any importer could add
    at runtime would not be a declaration. Pinning the empty set in BOTH
    directions is what keeps that honest: the first entry to declare egress
    breaks this test, which is precisely the moment someone must prove the lane
    gate against it rather than discover it in production.
    """

    def test_no_shipped_server_declares_egress_in_either_direction(self) -> None:
        egressing = {
            name for name in _KNOWN_MCP_SERVERS if harness_server_egresses(name)
        }
        assert egressing == set(), (
            "a shipped harness server now declares network_egress; the lane gate "
            "in resolve_harness_mcp_capabilities must be proven against it "
            "end-to-end before this entry ships"
        )

    def test_a_local_read_only_server_survives_every_lane(self) -> None:
        # The constraint that shaped the gate: vaultspec-rag is read-only and
        # local, so it must keep resolving on an unproven lane, on a proven one,
        # and on a model that declared no lane at all. Keying the gate on server
        # identity instead of the declared axis would have broken exactly this.
        for lane in (None, "kimi", "codex", "not-a-lane"):
            resolution = resolve_harness_mcp_capabilities(
                ["vaultspec-rag"],
                profile=HarnessMcpRuntimeProfile.NON_DESKTOP,
                lane=lane,
            )
            assert resolution.available_servers == ("vaultspec-rag",), lane
            assert resolution.unavailable == (), lane

    def test_the_allowlist_and_the_composition_read_the_same_lane(self) -> None:
        # Two halves that must agree: the allowlist auto-permits the composed
        # servers' tools in an autonomous run, so a name admitted by one and
        # refused by the other would leave the role's reach ambiguous.
        for lane in (None, "kimi"):
            allowed = harness_allowed_tool_names(["vaultspec-rag"], lane=lane)
            resolution = resolve_harness_mcp_capabilities(
                ["vaultspec-rag"],
                profile=HarnessMcpRuntimeProfile.NON_DESKTOP,
                lane=lane,
            )
            assert bool(allowed) is bool(resolution.available_servers), lane
