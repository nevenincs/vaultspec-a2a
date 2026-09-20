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

Project scope: a resolved spec says WHAT to launch, not WHICH PROJECT it serves.
A harness server that takes its project per tool call is bound to the run's
project by an explicit per-run pin (:func:`pin_harness_mcp_servers`) applied to
the rendered spec, through the environment variable each entry declares on its
root-pin axis. The pin lives outside the registry on purpose - see the axis
commentary below - and a server that declares no such channel is refused rather
than surfaced unpinned.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING, TypedDict, Unpack

from ..thread.errors import ConfigError
from ._harness_mcp_registry import (
    _DESKTOP_ACQUISITION_REASON,
    _DESKTOP_CAPABILITY_ACTIONS,
    _KNOWN_MCP_SERVERS,
    _UNPROVEN_EGRESS_REASON,
    HarnessMcpCapabilityUnavailable,
    HarnessMcpResolution,
    HarnessMcpRuntimeProfile,
    _frozen_object,
    _launch_spec,
    _registry_entry,
    _require_root_pin,
    declared_harness_tools,
    harness_server_egresses,
    registry_launch_divergence,
)
from .lane_admission import is_web_lane_proven

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from langchain_core.language_models import BaseChatModel

    from ._json_contract import FrozenJsonObject, JsonObject, JsonValue

__all__ = [
    "codex_mcp_server_specs",
    "compose_harness_mcp_servers",
    "harness_allowed_tool_names",
    "harness_spawn_env",
    "pin_harness_mcp_servers",
    "reject_duplicate_identities",
    "require_declared_surface",
    "resolve_harness_mcp_capabilities",
    "resolve_harness_mcp_servers",
]


def _desktop_available(entry: FrozenJsonObject) -> bool:
    """Return whether an entry explicitly proves offline desktop authority."""
    return (
        entry.get("desktop_available") is True
        and entry.get("runtime_acquisition") is False
    )


def resolve_harness_mcp_capabilities(
    names: Sequence[str],
    *,
    profile: object,
    lane: str | None = None,
) -> HarnessMcpResolution:
    """Resolve declared names under one explicit runtime profile.

    ``lane`` is the provider the composed session will run on, and it gates the
    NETWORK-EGRESS axis: a server declaring ``network_egress`` resolves only on a
    lane carrying recorded live-retrieval proof. The gate lives here rather than
    at any one call site because this is the stage every composition passes
    through, so outward reach cannot be granted by a caller that simply forgot to
    ask. It keys on the DECLARED axis and never on server identity, so a
    read-only local server keeps working on every lane and a server added
    tomorrow is covered by its own declaration rather than by a list somebody has
    to remember to update. ``None`` - a caller that stated no lane, and a model
    that declared none - is refused: absence of a lane is not permission.

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
        value = _KNOWN_MCP_SERVERS.get(name)
        if value is None:
            unknown.append(name)
            continue
        entry = _frozen_object(value, context=f"harness registry entry {name!r}")
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
        if harness_server_egresses(name) and not is_web_lane_proven(lane):
            unavailable.append(
                HarnessMcpCapabilityUnavailable(
                    code="lane_unproven_egress",
                    capability=name,
                    reason=_UNPROVEN_EGRESS_REASON,
                    action=(
                        "Run this role on a lane with recorded live-retrieval "
                        "proof, or declare a server that does not egress."
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
    lane: str | None = None,
) -> list[JsonObject]:
    """Resolve declared harness MCP server names to their launch specs.

    Raises :class:`ConfigError` naming every unknown server plus the known set,
    so a mistyped or unsupported declaration fails loudly here rather than
    silently dropping a server the run was told it would have. Desktop entries
    that require runtime acquisition are omitted; callers needing the actionable
    result use :func:`resolve_harness_mcp_capabilities` first.
    """
    resolution = resolve_harness_mcp_capabilities(names, profile=profile, lane=lane)
    return [
        _launch_spec(name, _registry_entry(name))
        for name in resolution.available_servers
    ]


def harness_allowed_tool_names(
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
    lane: str | None = None,
) -> list[str]:
    """Return the autonomous-allowlist names for the declared servers' read tools.

    Each declared server's registry ``tools`` are expanded to the CLI's flat
    exact-name allowlist form ``mcp__<server>__<tool>`` (parallel to
    ``authoring_allowed_tool_names``), so a headless run can auto-permit exactly
    the composed read tools and nothing else. Order-preserving and de-duplicated.
    Raises :class:`ConfigError` on an unknown declared name, matching
    :func:`resolve_harness_mcp_servers`.

    Reads through :func:`declared_harness_tools` rather than the registry field:
    this IS the auto-permit path that reader's contract names, so reading around
    it is how the advertised, permitted, and verified sets come apart.
    """
    tool_names: list[str] = []
    seen: set[str] = set()
    resolution = resolve_harness_mcp_capabilities(names, profile=profile, lane=lane)
    for name in resolution.available_servers:
        for tool in declared_harness_tools(name):
            qualified = f"mcp__{name}__{tool}"
            if qualified not in seen:
                seen.add(qualified)
                tool_names.append(qualified)
    return tool_names


def require_declared_surface(
    mcp_servers: Sequence[JsonObject],
    *,
    bridge_name: str,
) -> None:
    """Fail loud unless every advertised server is part of the declared surface.

    The declared-surface allowlist, enforced at the spawn seam: a session may
    advertise ONLY read-only registry-known harness servers (all three trust axes
    checked) plus at most the run's own authoring bridge under *bridge_name*.
    On the strict claude lane the session advertisement IS the agent's entire
    MCP surface - the CLI mounts exactly what ``session/new`` injects - so an
    entry that never passed the registry's trust root must refuse the run here
    rather than ride into the agent as a live tool mount. Duplicate identities
    are refused first, so a reviewed name can never be silently redeclared with
    a different command.

    Membership is checked by name, so the name alone is not allowed to BE the
    claim: every registry-known spec must also carry its entry's launch identity
    (:func:`registry_launch_divergence`). Without that, an entry borrowing a
    reviewed name rides its own command and arguments into the mounted surface
    while passing every check here - the trust root reduced to a string, which is
    what the refusal text below has always said this allowlist is keyed by.

    Raises:
        ConfigError: On a duplicate identity, a nameless spec, an unknown server
            name, a registry entry that fails any trust axis, or a spec whose
            launch diverges from the entry whose name it claims.
    """
    reject_duplicate_identities(mcp_servers)
    unknown: list[str] = []
    for spec in mcp_servers:
        name = spec.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError(
                "refusing to advertise an MCP server with no name: the declared-"
                "surface allowlist is keyed by name, so a nameless spec can never "
                "be part of the declared set"
            )
        if name == bridge_name:
            continue
        if name not in _KNOWN_MCP_SERVERS:
            unknown.append(name)
            continue
        _require_trust_root(name)
        divergence = registry_launch_divergence(spec, name=name)
        if divergence is not None:
            raise ConfigError(
                f"refusing to advertise harness MCP server {name!r}, which "
                f"{divergence}. The registry entry is what was reviewed, not the "
                "name that keys it, so a spec carrying its own launch under a "
                "reviewed name would mount an unreviewed command as a live tool "
                "surface - resolve the spec from the registry rather than "
                "assembling one beside it"
            )
    if unknown:
        raise ConfigError(
            f"refusing to advertise undeclared MCP server(s) "
            f"{', '.join(sorted(unknown))}: the session surface admits only the "
            "read-only harness registry plus the run's own authoring bridge, and "
            "an entry outside that set would mount as a live tool surface the "
            "declared harness never reviewed"
        )


def _repeated_names(names: Iterable[object]) -> list[str]:
    """Return every non-blank name appearing more than once, sorted.

    The shared body of the two duplicate guards, which answer the same question
    on two transports: one holds declared names, the other holds specs to read a
    name off. What a duplicate IS - a non-blank string seen twice, every one of
    them named rather than whichever the loop reached first - must be one answer,
    or the two transports could come to disagree about which configurations are
    admissible while both look guarded.

    Their REFUSALS stay their own: each names the artifact it was about to emit
    and the consequence there, which is error mapping rather than duplicated
    logic. A blank or non-string name is not an identity and so cannot duplicate
    one; it is skipped here rather than at each caller.
    """
    seen: dict[str, int] = {}
    for name in names:
        if isinstance(name, str) and name:
            seen[name] = seen.get(name, 0) + 1
    return sorted(name for name, count in seen.items() if count > 1)


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
    duplicates = _repeated_names(names)
    if duplicates:
        raise ConfigError(
            "refusing to emit a Codex configuration with duplicate MCP server "
            f"names: {', '.join(duplicates)}. Each name is a configuration key, "
            "so a repeat overwrites rather than conflicting"
        )


def reject_duplicate_identities(mcp_servers: Sequence[JsonObject]) -> None:
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
    duplicates = _repeated_names(spec.get("name") for spec in mcp_servers)
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
    if _registry_entry(name).get("read_only") is not True:
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
    if not isinstance(_registry_entry(name).get("network_egress"), bool):
        raise ConfigError(
            f"refusing to compose harness server {name!r} with no declared network "
            "egress axis into a surfacing config; local write and network reach are "
            "independent properties and the read-only marker expresses only the "
            "first, so the egress axis must be declared explicitly - omission is "
            "never read as no-egress"
        )


def _require_trust_root(name: str) -> None:
    """Fail loud unless the registry entry satisfies ALL THREE trust axes.

    The single trust-root guard shared by both delivery shapes (Claude config
    home and Codex config.toml), holding the local-write, network-egress, and
    root-pin assertions together so neither transport can surface an entry that
    satisfies one axis while leaving another unstated.

    The three it holds together are NOT of equal standing, and the grouping is for
    one call site rather than one status: :func:`_require_read_only` and
    :func:`_require_root_pin` each decide a policy the constructor never decides,
    while :func:`_require_declared_egress` is redundancy behind them. Each says so
    itself.
    """
    _require_read_only(name)
    _require_declared_egress(name)
    _require_root_pin(name, _registry_entry(name))


# The marker whose presence in a pin value would make it something other than a
# literal. The claude lane's session surface reaches the CLI as a dynamic MCP
# config parsed WITH environment expansion, so a ``${...}`` reaching an env value
# is resolved from the reading process's environment rather than carried as text -
# which is the mechanism the authoring bridge deliberately rides, and exactly what
# a project pin must not. The registry keeps this impossible by admitting only
# literals; the pin seam takes an outside value, so it re-establishes the same
# property by refusing rather than by escaping (an escaped placeholder would be a
# second spelling of the pin, and the whole point is that there is one).
_ENV_EXPANSION_MARKER = "${"


def _pin_value(project_root: str) -> str:
    """Return *project_root* once it is usable as a literal per-run pin.

    Three refusals, each closing a way a pin could exist while binding nothing:
    an empty value pins to nothing; a value carrying an expansion marker is
    resolved by the reading process instead of naming the run's project; and a
    relative value is resolved against the launched server's working directory,
    which reinstates the undeclared inheritance the pin exists to replace.

    Raises:
        ConfigError: If the value is blank, carries an expansion marker, or is
            not absolute.
    """
    if not project_root or not project_root.strip():
        raise ConfigError(
            "refusing to pin harness MCP servers to a blank project root; the pin "
            "names the run's project and an empty pin binds nothing"
        )
    if _ENV_EXPANSION_MARKER in project_root:
        raise ConfigError(
            f"refusing to pin harness MCP servers to {project_root!r}: an "
            f"environment-expansion marker ({_ENV_EXPANSION_MARKER}) in a pin value "
            "is expanded by the process that parses the surfacing config, so the "
            "server would be pinned to whatever that process's environment held "
            "rather than to the run's project"
        )
    if not PurePath(project_root).is_absolute():
        raise ConfigError(
            f"refusing to pin harness MCP servers to relative project root "
            f"{project_root!r}; a relative pin is resolved against the launched "
            "server's working directory, which is the undeclared inheritance the "
            "pin replaces"
        )
    return project_root


def _pinned_stdio_env(
    existing: JsonValue,
    *,
    name: str,
    variable: str,
    value: str,
) -> list[JsonValue]:
    """Return the ACP stdio ``env`` list carrying the run's pin.

    The ACP stdio shape models ``env`` as a list of ``{"name", "value"}`` pairs
    (the Codex ``config.toml`` block models the same data as a flat mapping, which
    is why the two transports render the pin separately). Existing pairs are
    preserved in order and the pin is appended; a spec that already carries the pin
    variable is refused rather than overwritten, because the pin is the run's
    single statement of its project and a second one is a disagreement, not a
    default.

    Raises:
        ConfigError: If ``env`` is present but not a list, or already declares the
            pin variable.
    """
    entries: list[JsonValue] = []
    if existing is not None:
        if not isinstance(existing, list):
            raise ConfigError(
                f"refusing to pin harness server {name!r}: its env is not the "
                "ACP stdio list of name/value pairs"
            )
        for item in existing:
            if isinstance(item, dict) and item.get("name") == variable:
                raise ConfigError(
                    f"refusing to pin harness server {name!r}: its spec already "
                    f"declares {variable!r}, so pinning it would silently replace "
                    "a value some other authority set"
                )
            entries.append(item)
    pin: JsonObject = {"name": variable, "value": value}
    entries.append(pin)
    return entries


def pin_harness_mcp_servers(
    specs: Sequence[JsonObject],
    *,
    project_root: str,
) -> list[JsonObject]:
    """Return *specs* with each registry server pinned to the run's project.

    The per-run pinning seam, and deliberately NOT part of the frozen registry.
    The registry's env values are literals so that a placeholder can never be
    expanded from the serving process's environment; a run's project is not
    knowable at registry-construction time, so expressing the pin as a registry
    value would mean either a placeholder (which that rule forbids) or a mutable
    registry (which the freeze forbids). Applying it here - to an already-rendered
    spec, per run, from an explicitly supplied value - leaves both rules standing
    and keeps the pin a statement the run makes rather than a property the
    registry claims.

    Each registry-known spec is pinned through the environment variable its entry
    declares on the root-pin axis, so the channel is the reviewed one rather than
    a convention restated here. A spec whose name the registry does not hold - the
    run's own authoring bridge travels in the same list - passes through untouched:
    whether such a spec belongs in the surface at all is the declared-surface
    allowlist's question (:func:`require_declared_surface`), not this seam's.

    Returns fresh spec objects; the inputs are not mutated.

    Raises:
        ConfigError: If the pin value is unusable, if a named registry server
            declares itself unpinnable, or if a spec already declares its pin
            variable.
    """
    value = _pin_value(project_root)
    pinned: list[JsonObject] = []
    for spec in specs:
        name = spec.get("name")
        shaped = dict(spec)
        if isinstance(name, str) and name in _KNOWN_MCP_SERVERS:
            shaped["env"] = _pinned_stdio_env(
                shaped.get("env"),
                name=name,
                variable=_require_root_pin(name, _registry_entry(name)),
                value=value,
            )
        pinned.append(shaped)
    return pinned


def harness_spawn_env(
    specs: Sequence[JsonObject], *, exclude: str | None = None
) -> dict[str, str]:
    """Return the real env values a strict session's placeholders expand from.

    On the strict claude lane every advertised spec's env VALUES are replaced
    with ``${NAME}`` references before the surface is serialized onto the CLI
    argv, and the CLI expands each reference from its own process environment at
    config parse time. A reference whose value was never hoisted therefore
    expands to nothing: the server starts with the variable unset, which for a
    pinned harness server means it falls back to resolving its own project from
    the directory it inherited - exactly the inheritance the pin exists to
    replace, and silently, because the spec still LOOKS pinned.

    The authoring bridge hoists its own values through its gatekeeper, which
    validates the bridge spec as it splits them off; pass its name as *exclude*
    so this never second-guesses that authority.
    """
    hoisted: dict[str, str] = {}
    for spec in specs:
        if exclude is not None and spec.get("name") == exclude:
            continue
        env = spec.get("env")
        if not isinstance(env, list):
            continue
        for item in env:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and isinstance(value, str):
                hoisted[name] = value
    return hoisted


def codex_mcp_server_specs(
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
    project_root: str | None = None,
    lane: str | None = None,
) -> list[JsonObject]:
    """Resolve declared harness names to full read-only registry specs for Codex.

    The registry's second serialization consumer (Codex ``config.toml`` vs the
    Claude ACP session): returns, per declared server, the fields the Codex
    ``[mcp_servers.<name>]`` block needs - ``name``, ``command``, ``args``,
    ``env``, and the read ``tools`` (for the ``enabled_tools`` allowlist). Applies
    the same fail-loud guards as the ACP path: an unknown name, a non-read-only
    entry, an entry with no declared network-egress axis, and an entry that
    declares itself unpinnable all raise :class:`ConfigError`, so one registry
    stays the single trust root across both transports.

    A second SERIALIZATION, not a second RENDERING: the launch comes from
    :func:`_launch_spec` and the read tools from :func:`declared_harness_tools`,
    the same two readers the ACP path and the contract check use. Reassembling
    them here would make this a second opinion about one declaration, which the
    divergence guard could not see - it is bound to the shared renderer, so a
    launch this function built by hand would be enforced against nothing. What
    stays local is only what the transport genuinely shapes differently.

    *project_root* carries the run's project pin, the Codex rendering of what
    :func:`pin_harness_mcp_servers` applies on the ACP transport: the same
    registry-declared variable, written into this transport's flat ``env``
    mapping instead of its list of pairs. Passing ``None`` renders an EMPTY env -
    the registry declares none and cannot - which leaves the launched server
    resolving its project from its working directory, correct only for a caller
    that has no run-bound project to state.
    """
    reject_duplicate_names(names)
    resolution = resolve_harness_mcp_capabilities(names, profile=profile, lane=lane)
    pin = None if project_root is None else _pin_value(project_root)
    specs: list[JsonObject] = []
    for name in resolution.available_servers:
        entry = _registry_entry(name)
        _require_trust_root(name)
        # Built here rather than read from the entry: the registry refuses ``env``
        # outright, so this transport's flat mapping starts empty and carries only
        # what the RUN states. There is consequently no declared value a pin could
        # collide with - the collision this once guarded is now unconstructible.
        env: JsonObject = {}
        if pin is not None:
            env[_require_root_pin(name, entry)] = pin
        specs.append(
            {
                **_launch_spec(name, entry),
                # The two fields this transport renders DIFFERENTLY, and the only
                # two: Codex models env as a flat table where ACP models it as a
                # list of name/value pairs, and Codex needs the read tools on the
                # spec because its ``enabled_tools`` allowlist is written from it.
                # Everything above is the shared launch, rendered once.
                "env": env,
                "tools": list(declared_harness_tools(name)),
            }
        )
    return specs


def _desktop_unavailable_attached_names(
    model: BaseChatModel, *, profile: HarnessMcpRuntimeProfile, lane: str | None
) -> set[str]:
    attached_names = {
        name
        for spec in (getattr(model, "mcp_servers", []) or [])
        if isinstance(name := spec.get("name"), str) and name in _KNOWN_MCP_SERVERS
    }
    attached_names.update(
        name
        for name in (getattr(model, "harness_mcp_servers", []) or [])
        if name in _KNOWN_MCP_SERVERS
    )
    if not attached_names:
        return set()
    # Use the same lane as the outer resolution for already attached servers.
    attached_resolution = resolve_harness_mcp_capabilities(
        sorted(attached_names), profile=profile, lane=lane
    )
    return {item.capability for item in attached_resolution.unavailable}


def _resolve_harness_composition(
    model: BaseChatModel,
    names: Sequence[str],
    *,
    profile: HarnessMcpRuntimeProfile,
    project_root: str | None = None,
    lane: str | None = None,
) -> tuple[HarnessMcpResolution, set[str], list[JsonObject]]:
    """Resolve and validate the declared names into specs and an unavailable set.

    The normalisation-and-validation stage, separated from projection. It
    validates the declared names first - so an unknown name is refused loudly
    regardless of the model type, rather than being swallowed when composition is
    inapplicable - resolves them to launch specs, applies the run's project pin to
    them when the caller states one, and computes the set of capability names the
    profile marks unavailable. Under the desktop profile it additionally folds in
    any already-attached server the profile now prohibits, so a capability that
    survived an earlier non-desktop composition is stripped.

    Returns the resolution, the unavailable-name set, and the resolved launch
    specs, which the projection stage delivers onto the model.

    Raises:
        ConfigError: On an unknown declared name or an unusable pin value.
    """
    resolution = resolve_harness_mcp_capabilities(names, profile=profile, lane=lane)
    unavailable_names = {
        unavailable.capability for unavailable in resolution.unavailable
    }
    if profile is HarnessMcpRuntimeProfile.DESKTOP:
        unavailable_names.update(
            _desktop_unavailable_attached_names(model, profile=profile, lane=lane)
        )
    resolved = [
        _launch_spec(name, _registry_entry(name))
        for name in resolution.available_servers
    ]
    if project_root is not None:
        resolved = pin_harness_mcp_servers(resolved, project_root=project_root)
    return resolution, unavailable_names, resolved


class _HarnessCompositionOptions(TypedDict, total=False):
    allowed_tools: Sequence[str] | None
    profile: HarnessMcpRuntimeProfile
    project_root: str | None
    lane: str | None


def compose_harness_mcp_servers(
    model: BaseChatModel,
    names: Sequence[str],
    **kwargs: Unpack[_HarnessCompositionOptions],
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

    ``project_root`` is the run's bound project, pinned onto every composed spec
    through :func:`pin_harness_mcp_servers`. It is the caller's to state and is
    never derived here: inferring it from the working directory would be the same
    undeclared inheritance the pin exists to replace, only spelled as a default.
    Passing ``None`` composes unpinned specs, which is what a caller with no
    run-bound project can honestly do; a caller that HAS one and omits it leaves
    the composed servers resolving their project from a working directory nobody
    declared. The Codex lane carries names rather than specs across this seam, so
    its pin is applied where its specs are rendered
    (:func:`codex_mcp_server_specs`) and a ``project_root`` given here does not
    reach it.
    """
    allowed_tools = kwargs.get("allowed_tools")
    profile = kwargs.get("profile", HarnessMcpRuntimeProfile.NON_DESKTOP)
    project_root = kwargs.get("project_root")
    lane = kwargs.get("lane")
    if not names and profile is HarnessMcpRuntimeProfile.NON_DESKTOP:
        return model
    resolution, unavailable_names, resolved = _resolve_harness_composition(
        model, names, profile=profile, project_root=project_root, lane=lane
    )
    if not resolved and not unavailable_names:
        return model
    return _project_composition_onto_model(
        model,
        _ResolvedMcpComposition(resolution, unavailable_names, resolved),
        allowed_tools=allowed_tools,
        profile=profile,
    )


@dataclass(frozen=True, slots=True)
class _ResolvedMcpComposition:
    resolution: HarnessMcpResolution
    unavailable_names: set[str]
    resolved: list[JsonObject]


def _project_codex_composition(
    model: BaseChatModel,
    resolution: HarnessMcpResolution,
    unavailable_names: set[str],
    profile: HarnessMcpRuntimeProfile,
) -> BaseChatModel:
    codex_attach = getattr(model, "with_harness_mcp_servers", None)
    if codex_attach is None:
        return model
    if profile is HarnessMcpRuntimeProfile.DESKTOP:
        existing_names = [
            name
            for name in (getattr(model, "harness_mcp_servers", []) or [])
            if name not in unavailable_names
        ]
        seen_names = set(existing_names)
        existing_names.extend(
            name for name in resolution.available_servers if name not in seen_names
        )
        return codex_attach(existing_names)
    return codex_attach(resolution.available_servers)


def _combined_mcp_specs(
    model: BaseChatModel, resolved: list[JsonObject], unavailable_names: set[str]
) -> list[JsonObject]:
    existing = [
        spec
        for spec in (getattr(model, "mcp_servers", []) or [])
        if spec.get("name") not in unavailable_names
    ]
    seen = {spec.get("name") for spec in existing}
    return existing + [spec for spec in resolved if spec.get("name") not in seen]


def _admitted_mcp_tools(
    model: BaseChatModel,
    resolution: HarnessMcpResolution,
    unavailable_names: set[str],
    allowed_tools: Sequence[str] | None,
    profile: HarnessMcpRuntimeProfile,
) -> tuple[list[str], list[str]]:
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
    return existing_allowed, admitted_tools


def _project_composition_onto_model(
    model: BaseChatModel,
    composition: _ResolvedMcpComposition,
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
        return _project_codex_composition(
            model, composition.resolution, composition.unavailable_names, profile
        )
    combined = _combined_mcp_specs(
        model, composition.resolved, composition.unavailable_names
    )
    existing_allowed, admitted_tools = _admitted_mcp_tools(
        model,
        composition.resolution,
        composition.unavailable_names,
        allowed_tools,
        profile,
    )
    if not admitted_tools:
        if composition.unavailable_names:
            return attach(combined, existing_allowed)
        return attach(combined)
    allow_seen = set(existing_allowed)
    merged_allowed = existing_allowed + [
        t for t in admitted_tools if t not in allow_seen
    ]
    return attach(combined, merged_allowed)
