"""Resolve and compose team-harness-declared MCP servers into an ACP session.

A team's ``[team.harness]`` declares MCP server NAMES (e.g. ``"vaultspec-rag"``);
this module maps each known name to its stdio launch spec and unions the specs
into an ACP session model's ``mcp_servers`` surface, which ``setup_session``
advertises in the CLI's ``session/new`` params. The registry is explicit and
closed: a declared name with no entry is a configuration error refused at
composition time, never a silent no-op, and there is no plugin/discovery
machinery.

Process topology: this module only RESOLVES launch specs. The declared harness
MCP servers are spawned by the ACP/Codex provider CLI as its own children when
it reads them from ``session/new`` (or ``config.toml``), so each one is a
descendant of the run-owned provider root and inherits that root's OS
containment. Nothing here spawns a process; there is no separate reaper to wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ..authoring.contract import is_document_authoring_role
from ..thread.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Literal

    from langchain_core.language_models import BaseChatModel

__all__ = [
    "NATIVE_READ_TOOL_NAMES",
    "NATIVE_TOOL_EGRESS",
    "RAG_MCP_REQUIREMENT",
    "HarnessMcpCapabilityUnavailable",
    "HarnessMcpResolution",
    "HarnessMcpRuntimeProfile",
    "codex_mcp_server_specs",
    "compose_harness_mcp_servers",
    "compose_native_read_tools",
    "config_home_mcp_servers",
    "declared_harness_tools",
    "harness_allowed_tool_names",
    "is_known_harness_server",
    "reject_duplicate_identities",
    "reject_duplicate_names",
    "resolve_harness_mcp_capabilities",
    "resolve_harness_mcp_servers",
]


class HarnessMcpRuntimeProfile(StrEnum):
    """Explicit runtime authority for harness MCP capability resolution."""

    NON_DESKTOP = "non-desktop"
    DESKTOP = "desktop"


@dataclass(frozen=True, slots=True)
class HarnessMcpCapabilityUnavailable:
    """Stable, path-free explanation of an unavailable harness capability."""

    code: Literal["capability_unavailable"]
    capability: str
    reason: str
    action: str


@dataclass(frozen=True, slots=True)
class HarnessMcpResolution:
    """Profile-bound capability names safe for downstream serialization."""

    profile: HarnessMcpRuntimeProfile
    available_servers: tuple[str, ...]
    unavailable: tuple[HarnessMcpCapabilityUnavailable, ...]


# Known MCP server name -> registry entry. Explicit and closed by design.
# ``uvx --from vaultspec-rag[mcp] vaultspec-search-mcp`` is used rather than the
# repo ``.mcp.json``'s ``uv run vaultspec-search-mcp`` because the ACP subprocess
# is spawned in the run workspace with no uv project cwd; the package extra names
# the MCP capability while remaining independent of the cwd.
#
# The requirement carries NO version constraint, deliberately. The harness servers
# are released independently of this project, so constraining them here - by exact
# pin, floor, or range alike - stalls the whole ecosystem behind this project's
# upgrade cadence while proving nothing about the capability the run actually
# needs. The compatibility boundary is the ``tools`` declaration below, and it is
# verified against the server's own ``tools/list`` before a run launches
# (``_mcp_contract.verify_harness_mcp_contract``). A future read-only launch flag
# is a one-line addition to ``args`` here.
#
# ``tools`` is registry metadata, NOT part of the ACP ``session/new`` mcpServer
# shape: it names the server's READ-ONLY tools that may join the autonomous
# allowlist (``mcp__<server>__<tool>``). It is stripped from the launch spec in
# ``resolve_harness_mcp_servers`` so it never leaks into the session payload. The
# write verbs the rag server also exposes (``reindex_vault``/``reindex_codebase``)
# are deliberately omitted, honoring the read-only composition boundary. It is
# also the LOAD-BEARING contract: the declared names are what a run advertises and
# auto-permits, so a server that does not serve them is refused at the spawn seam
# rather than handed to an agent whose grounding tools would silently be absent.
# The registry's trust root is TWO independent axes, not one marker. ``read_only``
# asserts an entry does not WRITE LOCALLY; ``network_egress`` asserts whether it
# REACHES OUTWARD. Neither implies the other: a fetch/search tool satisfies
# read-only completely while still able to carry workspace content outward in a
# URL, so a server that egresses can never ride a read-only-only assertion. Both
# default unsafe-by-omission (a missing declaration fails), never silently
# permissive.
#
# :func:`_declare_registry` is the ONLY construction seam, and it both validates
# and FREEZES: the returned mapping and every entry inside it are read-only views
# over immutable values, so the registry cannot be extended, re-pointed, or
# re-declared by an importer after import. Membership is a trust claim, and a
# trust claim that any module can add with one assignment is not a claim at all.
# WARNING: the config home is written with user-scope env expansion, so a literal
# ``${...}`` placed in a future registry ``env`` value would be expanded by the
# CLI from its process environment at parse time (the same mechanism the
# authoring bridge relies on) — registry env values must be literals, never
# accidental ``${...}`` strings.
_LAUNCH_SPEC_KEYS = ("name", "command", "args", "env")
_TRUST_AXES = ("read_only", "network_egress")
RAG_MCP_REQUIREMENT = "vaultspec-rag[mcp]"


def _frozen(value: Any) -> Any:
    """Return an immutable view of *value*, recursively.

    Lists become tuples and mappings become read-only proxies, so a frozen
    registry entry has no mutable interior a holder could reach through. Scalars
    are already immutable and pass through untouched.
    """
    if isinstance(value, list):
        return tuple(_frozen(item) for item in value)
    if isinstance(value, dict):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    return value


def _declare_registry(
    entries: dict[str, dict[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    """Return a FROZEN registry once every entry declares both trust axes.

    The registry's single construction seam, so the declaration obligation is
    discharged where entries are written rather than only where they are read.
    Local write and network reach are independent properties and each is declared
    per entry; an omitted or non-boolean axis is refused here, which makes an
    undeclared entry unconstructible rather than merely unsurfaceable.

    The returned mapping is a read-only view whose entries are themselves read-only
    views over immutable values. Membership in this registry IS a trust claim - it
    says a server was reviewed and may be surfaced into an agent's config - so it
    must not be assertable at runtime by any importer holding the name. Freezing
    here rather than at each reader keeps construction the only way in, which is
    what lets the surfacing seams reason about what can possibly reach them.

    Raises:
        ConfigError: If an entry omits either trust axis or declares it
            non-boolean.
    """
    for name, entry in entries.items():
        for axis in _TRUST_AXES:
            if not isinstance(entry.get(axis), bool):
                raise ConfigError(
                    f"harness registry entry {name!r} does not declare {axis!r}; "
                    "both trust axes (local write, network egress) must be declared "
                    "explicitly per entry - neither is inferred from the other, and "
                    "omission is never read as permission"
                )
    return MappingProxyType({name: _frozen(entry) for name, entry in entries.items()})


_KNOWN_MCP_SERVERS: Mapping[str, Mapping[str, Any]] = _declare_registry(
    {
        "vaultspec-rag": {
            "name": "vaultspec-rag",
            "command": "uvx",
            "args": ["--from", RAG_MCP_REQUIREMENT, "vaultspec-search-mcp"],
            "tools": ("search_vault", "search_codebase", "get_code_file"),
            "read_only": True,
            # Indexes and serves the local vault/codebase over stdio; no outbound
            # request leaves the agent host on its behalf.
            "network_egress": False,
            "runtime_acquisition": True,
            "desktop_available": False,
        },
    }
)

_DESKTOP_ACQUISITION_REASON = "runtime acquisition is disabled for the desktop profile"
_DESKTOP_CAPABILITY_ACTIONS = {
    "vaultspec-rag": (
        "Install the separately packaged vaultspec-rag desktop capability, then retry."
    ),
}


def _wire_value(value: Any) -> Any:
    """Return the mutable JSON-shaped counterpart of a frozen registry value.

    The registry stores tuples and read-only proxies; the ACP ``session/new``
    payload and the config-home writers are handed plain lists and dicts, which is
    the shape every downstream consumer already expects. Materialising a fresh
    container here also means a caller mutating the spec it was given cannot reach
    back into the registry through a shared interior.
    """
    if isinstance(value, tuple):
        return [_wire_value(item) for item in value]
    if isinstance(value, MappingProxyType):
        return {key: _wire_value(item) for key, item in value.items()}
    return value


def _launch_spec(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Return the ACP-shape launch spec, stripped of registry-only metadata."""
    return {k: _wire_value(entry[k]) for k in _LAUNCH_SPEC_KEYS if k in entry}


def is_known_harness_server(name: str) -> bool:
    """Return whether *name* is an entry of the closed harness registry.

    The membership predicate the contract verifier uses to tell a registry-owned
    server apart from the run's own authoring bridge, which travels in the same
    advertised list but carries no static tool declaration.
    """
    return name in _KNOWN_MCP_SERVERS


def declared_harness_tools(name: str) -> tuple[str, ...]:
    """Return the read-only tools the registry declares for *name*.

    The single reader of the ``tools`` declaration for contract verification, so
    the names a run advertises, the names it auto-permits, and the names it
    verifies the server serves can never drift apart.

    Raises:
        ConfigError: If *name* is not a known harness server.
    """
    entry = _KNOWN_MCP_SERVERS.get(name)
    if entry is None:
        raise ConfigError(
            f"unknown harness MCP server {name!r}; known servers are "
            f"{sorted(_KNOWN_MCP_SERVERS)}"
        )
    return tuple(entry.get("tools", ()))


def _desktop_available(entry: Mapping[str, Any]) -> bool:
    """Return whether an entry explicitly proves offline desktop authority."""
    return (
        entry.get("desktop_available") is True
        and entry.get("runtime_acquisition") is False
    )


def resolve_harness_mcp_capabilities(
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile,
) -> HarnessMcpResolution:
    """Resolve declared names under one explicit runtime profile.

    The desktop profile admits only a registry entry explicitly marked desktop
    available. An omitted marker fails closed, and a runtime-acquired entry becomes
    an actionable, path-free unavailable capability instead of a launch spec.
    Non-desktop resolution preserves the existing Compose and foreground-development
    behavior.

    The caller must select *profile* explicitly. Runtime integration will pass the
    authoritative desktop profile once that authority exists; this seam never
    infers policy from the environment, executable search path, or working directory.
    """
    if not isinstance(profile, HarnessMcpRuntimeProfile):
        raise ConfigError(
            "harness MCP resolution requires an explicit HarnessMcpRuntimeProfile"
        )

    available: list[str] = []
    unavailable: list[HarnessMcpCapabilityUnavailable] = []
    unknown: list[str] = []
    for name in names:
        entry = _KNOWN_MCP_SERVERS.get(name)
        if entry is None:
            unknown.append(name)
            continue
        if profile is HarnessMcpRuntimeProfile.DESKTOP and not _desktop_available(
            entry
        ):
            unavailable.append(
                HarnessMcpCapabilityUnavailable(
                    code="capability_unavailable",
                    capability=name,
                    reason=_DESKTOP_ACQUISITION_REASON,
                    action=_DESKTOP_CAPABILITY_ACTIONS.get(
                        name,
                        f"Install the separately packaged {name} desktop capability, "
                        "then retry.",
                    ),
                )
            )
            continue
        available.append(name)
    if unknown:
        raise ConfigError(
            f"unknown harness MCP server(s) {unknown}; known servers are "
            f"{sorted(_KNOWN_MCP_SERVERS)}"
        )
    return HarnessMcpResolution(
        profile=profile,
        available_servers=tuple(available),
        unavailable=tuple(unavailable),
    )


def resolve_harness_mcp_servers(
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
) -> list[dict[str, Any]]:
    """Resolve declared harness MCP server names to their launch specs.

    Raises :class:`ConfigError` naming every unknown server plus the known set,
    so a mistyped or unsupported declaration fails loudly here rather than
    silently dropping a server the run was told it would have. Desktop entries
    that require runtime acquisition are omitted; callers needing the actionable
    result use :func:`resolve_harness_mcp_capabilities` first.
    """
    resolution = resolve_harness_mcp_capabilities(names, profile=profile)
    return [
        _launch_spec(_KNOWN_MCP_SERVERS[name]) for name in resolution.available_servers
    ]


def harness_allowed_tool_names(
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
) -> list[str]:
    """Return the autonomous-allowlist names for the declared servers' read tools.

    Each declared server's registry ``tools`` are expanded to the CLI's flat
    exact-name allowlist form ``mcp__<server>__<tool>`` (parallel to
    ``authoring_allowed_tool_names``), so a headless run can auto-permit exactly
    the composed read tools and nothing else. Order-preserving and de-duplicated.
    Raises :class:`ConfigError` on an unknown declared name, matching
    :func:`resolve_harness_mcp_servers`.
    """
    tool_names: list[str] = []
    seen: set[str] = set()
    resolution = resolve_harness_mcp_capabilities(names, profile=profile)
    for name in resolution.available_servers:
        entry = _KNOWN_MCP_SERVERS[name]
        for tool in entry.get("tools", ()):
            qualified = f"mcp__{name}__{tool}"
            if qualified not in seen:
                seen.add(qualified)
                tool_names.append(qualified)
    return tool_names


def config_home_mcp_servers(
    mcp_servers: Sequence[dict[str, Any]],
    *,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
) -> dict[str, dict[str, Any]]:
    """Select the registry-known harness servers and shape them for ``.claude.json``.

    Given the session's advertised ``mcp_servers`` (which may also carry the per-run
    authoring bridge), keep ONLY those whose name is a known harness server and
    transform each ACP launch spec into the CLI user-global config shape keyed by
    name: ``{"<name>": {"type": "stdio", "command": ..., "args": [...], "env": ...}}``.
    Servers not in the registry (e.g. the per-run authoring bridge) are excluded
    here: the bridge is admitted into the same isolated home through its own
    guarded channel (``config_home_authoring_entry``), so together the home
    surfaces exactly the declared read-only harness servers PLUS at most the run's
    own authoring bridge. Returns an empty mapping when none match.
    """
    reject_duplicate_identities(mcp_servers)
    known_names = [
        str(spec.get("name"))
        for spec in mcp_servers
        if spec.get("name") in _KNOWN_MCP_SERVERS
    ]
    resolution = resolve_harness_mcp_capabilities(known_names, profile=profile)
    available = set(resolution.available_servers)
    home: dict[str, dict[str, Any]] = {}
    for spec in mcp_servers:
        name = spec.get("name")
        if name not in available:
            continue
        _require_trust_root(name)
        entry: dict[str, Any] = {"type": "stdio", "command": spec["command"]}
        if spec.get("args"):
            entry["args"] = list(spec["args"])
        if spec.get("env"):
            entry["env"] = dict(spec["env"])
        home[name] = entry
    return home


def reject_duplicate_names(names: Sequence[str]) -> None:
    """Fail loud when a declared server name is repeated.

    The name-list counterpart of :func:`reject_duplicate_identities`, for the
    transport that resolves names rather than specs. Emitting a repeated name
    produces two blocks with one key in the Codex configuration, which is either
    a parse failure or a last-wins overwrite - the same shadowing the specs path
    refuses, on a transport where it can also break the file outright.

    Raises:
        ConfigError: If any name appears more than once.
    """
    seen: dict[str, int] = {}
    for name in names:
        if name:
            seen[name] = seen.get(name, 0) + 1
    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        raise ConfigError(
            "refusing to emit a Codex configuration with duplicate MCP server "
            f"names: {', '.join(duplicates)}. Each name is a configuration key, "
            "so a repeat overwrites rather than conflicting"
        )


def reject_duplicate_identities(mcp_servers: Sequence[dict[str, Any]]) -> None:
    """Fail loud when two advertised servers claim the same identity.

    Composition is keyed by name, so a duplicate does not conflict - it
    overwrites, and the last spec silently wins. The harness invariant is that
    the spawned agent's MCP surface is exactly the declared set, and a name that
    can be redeclared with a different command breaks that: the surviving entry
    is no longer the one that was reviewed.

    Checked before composition rather than during it, so the refusal names every
    duplicated identity rather than whichever one the loop reached first.

    Raises:
        ConfigError: If any name appears more than once.
    """
    seen: dict[str, int] = {}
    for spec in mcp_servers:
        name = spec.get("name")
        if not isinstance(name, str) or not name:
            continue
        seen[name] = seen.get(name, 0) + 1
    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        raise ConfigError(
            "refusing to compose a surfacing config with duplicate MCP server "
            f"identities: {', '.join(duplicates)}. Composition is keyed by name, "
            "so a repeated identity silently overwrites rather than conflicting, "
            "and the agent would surface a server other than the declared one"
        )


def _require_read_only(name: str) -> None:
    """Fail loud unless the registry entry is explicitly marked read-only.

    The local-write axis of the trust root: registry drift toward a write-capable
    entry can never be silently composed into a surfacing config.

    This guard is ENFORCEMENT, not redundancy, and the distinction is worth being
    precise about because the frozen registry makes it easy to assume otherwise.
    :func:`_declare_registry` validates that the axis was DECLARED; it deliberately
    does not constrain what was declared, so ``read_only: False`` is a perfectly
    constructible entry. Deciding whether a declared value may be surfaced is this
    function's job alone. It cannot fire against today's registry only because the
    single shipped entry declares ``True`` - add a second entry that declares
    ``False`` and it fires immediately, with no change here and no weakening of the
    freeze. Compare :func:`_require_declared_egress`, which is genuinely redundant.
    """
    if not _KNOWN_MCP_SERVERS[name].get("read_only"):
        raise ConfigError(
            f"refusing to compose non-read-only harness server {name!r} into a "
            "surfacing config; only read-only servers may be composed"
        )


def _require_declared_egress(name: str) -> None:
    """Fail loud unless the registry entry declares its network-egress axis.

    The network-reach axis of the trust root, independent of the local-write one:
    an entry that writes nothing locally may still carry workspace content
    outward, so satisfying :func:`_require_read_only` says nothing about reach.
    An undeclared axis is refused rather than defaulted, so composing a server
    whose outbound behaviour was never stated is impossible on either transport.

    REDUNDANCY, not enforcement - kept deliberately, and labelled so nobody reads
    it as the thing standing between a run and an undeclared server. It applies the
    same predicate to the same values that :func:`_declare_registry` already
    refused at construction, and since the registry is frozen, no path exists that
    could present this seam an entry the constructor did not admit. It is retained
    as a cheap backstop for the one way that could change: a second registry, or a
    construction path that does not route through ``_declare_registry``. If that
    ever happens this guard still fires; until then it can only pass. The
    enforcement of the declaration obligation is the constructor.
    """
    if not isinstance(_KNOWN_MCP_SERVERS[name].get("network_egress"), bool):
        raise ConfigError(
            f"refusing to compose harness server {name!r} with no declared network "
            "egress axis into a surfacing config; local write and network reach are "
            "independent properties and the read-only marker expresses only the "
            "first, so the egress axis must be declared explicitly - omission is "
            "never read as no-egress"
        )


def _require_trust_root(name: str) -> None:
    """Fail loud unless the registry entry declares BOTH trust axes.

    The single trust-root guard shared by both delivery shapes (Claude config
    home and Codex config.toml), holding the local-write and network-egress
    assertions together so neither transport can surface an entry that satisfies
    one axis while leaving the other unstated.

    The two halves it holds together are NOT of equal standing, and the pairing is
    for one call site rather than one status: :func:`_require_read_only` decides a
    policy the constructor never decides, while :func:`_require_declared_egress` is
    redundancy behind it. Each says so itself.
    """
    _require_read_only(name)
    _require_declared_egress(name)


def codex_mcp_server_specs(
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
) -> list[dict[str, Any]]:
    """Resolve declared harness names to full read-only registry specs for Codex.

    The registry's second serialization consumer (Codex ``config.toml`` vs the
    Claude ACP session): returns, per declared server, the fields the Codex
    ``[mcp_servers.<name>]`` block needs - ``name``, ``command``, ``args``,
    ``env``, and the read ``tools`` (for the ``enabled_tools`` allowlist). Applies
    the same fail-loud guards as the ACP path: an unknown name, a non-read-only
    entry, and an entry with no declared network-egress axis all raise
    :class:`ConfigError`, so one registry stays the single trust root across both
    transports.
    """
    reject_duplicate_names(names)
    resolution = resolve_harness_mcp_capabilities(names, profile=profile)
    specs: list[dict[str, Any]] = []
    for name in resolution.available_servers:
        entry = _KNOWN_MCP_SERVERS[name]
        _require_trust_root(name)
        specs.append(
            {
                "name": name,
                "command": entry["command"],
                "args": list(entry.get("args", ())),
                "env": dict(entry.get("env", {})),
                "tools": list(entry.get("tools", ())),
            }
        )
    return specs


def _resolve_harness_composition(
    model: BaseChatModel,
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile,
) -> tuple[HarnessMcpResolution, set[str], list[dict[str, Any]]]:
    """Resolve and validate the declared names into specs and an unavailable set.

    The normalisation-and-validation stage, separated from projection. It
    validates the declared names first - so an unknown name is refused loudly
    regardless of the model type, rather than being swallowed when composition is
    inapplicable - resolves them to launch specs, and computes the set of
    capability names the profile marks unavailable. Under the desktop profile it
    additionally folds in any already-attached server the profile now prohibits,
    so a capability that survived an earlier non-desktop composition is stripped.

    Returns the resolution, the unavailable-name set, and the resolved launch
    specs, which the projection stage delivers onto the model.

    Raises:
        ConfigError: On an unknown declared name.
    """
    resolution = resolve_harness_mcp_capabilities(names, profile=profile)
    unavailable_names = {
        unavailable.capability for unavailable in resolution.unavailable
    }
    if profile is HarnessMcpRuntimeProfile.DESKTOP:
        attached_names = {
            str(spec.get("name"))
            for spec in (getattr(model, "mcp_servers", []) or [])
            if spec.get("name") in _KNOWN_MCP_SERVERS
        }
        attached_names.update(
            name
            for name in (getattr(model, "harness_mcp_servers", []) or [])
            if name in _KNOWN_MCP_SERVERS
        )
        if attached_names:
            attached_resolution = resolve_harness_mcp_capabilities(
                sorted(attached_names),
                profile=profile,
            )
            unavailable_names.update(
                unavailable.capability
                for unavailable in attached_resolution.unavailable
            )
    resolved = [
        _launch_spec(_KNOWN_MCP_SERVERS[name]) for name in resolution.available_servers
    ]
    return resolution, unavailable_names, resolved


def compose_harness_mcp_servers(
    model: BaseChatModel,
    names: Sequence[str],
    *,
    allowed_tools: Sequence[str] | None = None,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
) -> BaseChatModel:
    """Return a model advertising the declared harness MCP servers, or *model*.

    Non-desktop composition is ADD-only: the resolved specs are UNIONED (by
    server name) with any the model already advertises - e.g. the per-run
    authoring bridge - never replacing them. Desktop composition additionally
    removes any requested capability that its profile marks unavailable, including
    stale matching allowlist entries, so prohibited acquisition material cannot
    survive an earlier non-desktop composition. A model with no ACP
    ``with_mcp_servers`` surface (mock, hosted API) is returned unchanged, and an
    empty *names* is a no-op for non-desktop callers. Desktop callers still inspect
    pre-attached state when *names* is empty so a stale prohibited launch cannot
    survive a profile transition. Raises :class:`ConfigError` on an unknown declared
    name.

    ``allowed_tools`` (headless runs only) are the exact ``mcp__<server>__<tool>``
    names to auto-permit for the composed servers - typically
    :func:`harness_allowed_tool_names` for *names*. They are UNIONED with the
    model's existing ``allowed_tools`` (e.g. the authoring bridge's names set by
    the worker's authoring-attach step) rather than replacing them, closing the
    prior ``attach(combined)`` gap where composed servers' tools were served but
    never joined the autonomous allowlist. Passing ``None`` (or an empty
    sequence) preserves the model's existing allowlist unchanged.

    Provider dispatch: an ACP model (Claude/Z.ai) exposes ``with_mcp_servers`` and
    takes the session-inject + allowlist path below; a Codex model exposes
    ``with_harness_mcp_servers`` and takes the ``CODEX_HOME`` ``config.toml`` path
    (``allowed_tools`` does not apply - the read-verb constraint is applied at
    config.toml emission). ONLY a model with neither delivery mechanism (mock,
    hosted API) is returned unchanged. A model that HAS a harness delivery
    mechanism is never silently no-oped.
    """
    if not names and profile is HarnessMcpRuntimeProfile.NON_DESKTOP:
        return model
    resolution, unavailable_names, resolved = _resolve_harness_composition(
        model, names, profile=profile
    )
    if not resolved and not unavailable_names:
        return model
    return _project_composition_onto_model(
        model,
        resolution,
        unavailable_names,
        resolved,
        allowed_tools=allowed_tools,
        profile=profile,
    )


def _project_composition_onto_model(
    model: BaseChatModel,
    resolution: HarnessMcpResolution,
    unavailable_names: set[str],
    resolved: list[dict[str, Any]],
    *,
    allowed_tools: Sequence[str] | None,
    profile: HarnessMcpRuntimeProfile,
) -> BaseChatModel:
    """Deliver the resolved composition onto the model via its own mechanism.

    The projection stage, separated from resolution. It dispatches on the model's
    delivery surface - an ACP model's session-inject ``with_mcp_servers``, a Codex
    model's ``config.toml`` ``with_harness_mcp_servers``, or neither - and in each
    case unions the resolved specs and allowlist with what the model already
    carries while dropping anything the profile marks unavailable. A model with no
    delivery mechanism is returned unchanged.
    """
    attach = getattr(model, "with_mcp_servers", None)
    if attach is None:
        # Codex lane: no ACP session surface, but its own config.toml delivery.
        codex_attach = getattr(model, "with_harness_mcp_servers", None)
        if codex_attach is not None:
            if profile is HarnessMcpRuntimeProfile.DESKTOP:
                existing_names = [
                    name
                    for name in (getattr(model, "harness_mcp_servers", []) or [])
                    if name not in unavailable_names
                ]
                seen_names = set(existing_names)
                existing_names.extend(
                    name
                    for name in resolution.available_servers
                    if name not in seen_names
                )
                return codex_attach(existing_names)
            return codex_attach(resolution.available_servers)
        return model
    existing = [
        spec
        for spec in (getattr(model, "mcp_servers", []) or [])
        if spec.get("name") not in unavailable_names
    ]
    seen = {s.get("name") for s in existing}
    combined = existing + [s for s in resolved if s.get("name") not in seen]
    existing_allowed = [
        tool
        for tool in (getattr(model, "allowed_tools", []) or [])
        if not any(tool.startswith(f"mcp__{name}__") for name in unavailable_names)
    ]
    resolved_allowed = set(
        harness_allowed_tool_names(resolution.available_servers, profile=profile)
    )
    admitted_tools = [
        tool for tool in (allowed_tools or ()) if tool in resolved_allowed
    ]
    if not admitted_tools:
        if unavailable_names:
            return attach(combined, existing_allowed)
        return attach(combined)
    allow_seen = set(existing_allowed)
    merged_allowed = existing_allowed + [
        t for t in admitted_tools if t not in allow_seen
    ]
    return attach(combined, merged_allowed)


# The spawned CLI's own built-in read tools. These execute agent-side over the
# workspace fs (no MCP, no registration-scope surfacing gate) and give document
# roles their deterministic grounding floor: read a named .vault document, grep
# code, discover files. They are added by exact name — never a wildcard — so a
# document role in autonomous mode can invoke them without a local prompt while
# every write/exec built-in stays gated (the .vault deny remains write-only).
# Named here because there is nothing to ask. Every other tool surface in this
# system is enumerated by its provider - the engine serves its authoring catalog,
# the harness registry declares its servers - and is consumed rather than
# restated. These are the CLI's own compiled-in built-ins: they are exposed
# through no listing, no capability response, and no registration handshake, so
# an exact-name allowlist is the only expression available. Treat this as the
# documented exception to "ask, do not hardcode", not an instance of it, and
# re-open it only if a provider starts advertising its built-ins.
NATIVE_READ_TOOL_NAMES: tuple[str, ...] = ("Read", "Grep", "Glob")

# The native built-ins' network-egress axis, the same axis the harness registry
# declares per entry and for the same reason: the built-ins are NOT uniformly
# local. Read/Grep/Glob touch only the workspace fs, but the CLI's web built-ins
# reach outward while writing nothing locally, so a native tool set is no safer to
# compose undeclared than a registry entry is. Membership IS the declaration: a
# name absent from this mapping has never stated its reach and is refused at
# :func:`compose_native_read_tools` rather than defaulted to no-egress.
#
# Because membership is the declaration, the mapping is a read-only view and not a
# plain dict: this name is exported, so a mutable one would let any importer
# declare ``WebFetch`` no-egress with a single assignment and walk it straight
# through the composition guard below. The guard checks the catalog; the catalog
# has to be something the guard can trust. Editing this source literal is the only
# way to add a native tool, which is the point - it is the same deliberate,
# reviewable act that adding a harness registry entry is.
NATIVE_TOOL_EGRESS: Mapping[str, bool] = MappingProxyType(
    {
        "Read": False,
        "Grep": False,
        "Glob": False,
    }
)


def _require_declared_native_egress(names: Sequence[str]) -> None:
    """Fail loud unless every native tool being composed declares its egress axis.

    The native-built-in counterpart of :func:`_require_declared_egress`, applied
    to the tool set rather than a registry entry. Checked before the autonomy and
    role gates so a tool set whose reach was never stated is refused uniformly,
    rather than only on the runs where composition happens to apply - the same
    validate-first discipline :func:`_resolve_harness_composition` applies to
    declared server names.

    Raises:
        ConfigError: If any name has no entry in :data:`NATIVE_TOOL_EGRESS`.
    """
    undeclared = [name for name in names if name not in NATIVE_TOOL_EGRESS]
    if undeclared:
        raise ConfigError(
            "refusing to compose native built-in tool(s) with no declared network "
            f"egress axis: {', '.join(undeclared)}. Every native tool joining the "
            "autonomous allowlist must state whether it reaches outward; the axis "
            "is independent of local write and omission is never read as no-egress"
        )


# The floor discharges the same declaration obligation at construction that
# :func:`_declare_registry` imposes on registry entries, so a name added to the
# floor without an egress declaration fails at import rather than at the first
# autonomous document run.
_require_declared_native_egress(NATIVE_READ_TOOL_NAMES)


def compose_native_read_tools(
    model: BaseChatModel,
    *,
    autonomous: bool,
    role: str | None,
    extra_tool_names: Sequence[str] | None = None,
) -> BaseChatModel:
    """Permit the native built-ins for autonomous document-authoring roles.

    In autonomous (headless) mode ONLY, and for a document-authoring role ONLY,
    union the CLI's native Read/Grep/Glob - plus any *extra_tool_names* the caller
    composes on top of that floor - into the session's exact-name ``allowedTools``
    so the floor grounding is invocable without a local prompt. The existing
    allowlist (e.g. the bridged authoring tools) and the advertised MCP servers are
    preserved unchanged; the names are added by exact name, never a wildcard, and
    never for human-in-loop runs, which keep their prompts. Models with no ACP
    allowlist surface (mock, hosted APIs) are returned unchanged.

    Every composed name must declare its network-egress axis in
    :data:`NATIVE_TOOL_EGRESS`; an undeclared one raises :class:`ConfigError`
    before any gate or projection, so an outward-reaching built-in cannot join the
    allowlist on the strength of the local-read floor's assumptions.

    The native-built-in counterpart of :func:`compose_harness_mcp_servers`: both
    mutate only the ACP session's advertised surface and allowlist, so they live
    together rather than in the graph node that sequences them.
    """
    composed_names = list(NATIVE_READ_TOOL_NAMES)
    composed_names += [
        name for name in (extra_tool_names or ()) if name not in composed_names
    ]
    _require_declared_native_egress(composed_names)
    if not autonomous or not is_document_authoring_role(role):
        return model
    attach = getattr(model, "with_mcp_servers", None)
    if attach is None:
        return model
    existing = list(getattr(model, "allowed_tools", []) or [])
    combined = existing + [name for name in composed_names if name not in existing]
    if combined == existing:
        return model
    return attach(list(getattr(model, "mcp_servers", []) or []), combined)
