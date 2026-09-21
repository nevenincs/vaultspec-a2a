"""Closed harness MCP registry and immutable launch declarations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..thread.errors import ConfigError
from ._json_contract import (
    FrozenJsonObject,
    FrozenJsonValue,
    JsonObject,
    JsonValue,
    freeze_json,
)
from ._subprocess import redact_secrets

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Literal


__all__ = [
    "_DESKTOP_ACQUISITION_REASON",
    "_DESKTOP_CAPABILITY_ACTIONS",
    "_KNOWN_MCP_SERVERS",
    "_LAUNCH_IDENTITY_KEYS",
    "_UNPROVEN_EGRESS_REASON",
    "HarnessMcpCapabilityUnavailable",
    "HarnessMcpResolution",
    "HarnessMcpRuntimeProfile",
    "_declare_registry",
    "_frozen_object",
    "_launch_spec",
    "_registry_entry",
    "_require_root_pin",
    "declared_harness_tools",
    "harness_server_egresses",
    "harness_server_exact_surface",
    "is_known_harness_server",
    "registry_launch_divergence",
]


class HarnessMcpRuntimeProfile(StrEnum):
    """Explicit runtime authority for harness MCP capability resolution."""

    NON_DESKTOP = "non-desktop"
    DESKTOP = "desktop"


@dataclass(frozen=True, slots=True)
class HarnessMcpCapabilityUnavailable:
    """Stable, path-free explanation of an unavailable harness capability."""

    code: Literal["capability_unavailable", "lane_unproven_egress"]
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
# The registry's trust root is THREE independent axes, not one marker.
# ``read_only`` asserts an entry does not WRITE LOCALLY; ``network_egress``
# asserts whether it REACHES OUTWARD; ``root_pin`` asserts whether the run can
# BIND IT TO ONE PROJECT. None implies another: a fetch/search tool satisfies
# read-only completely while still able to carry workspace content outward in a
# URL, so a server that egresses can never ride a read-only-only assertion, and a
# server that is both read-only and local still hands an agent another project's
# content when the project is chosen per call rather than per launch. The first
# two axes are booleans; the third names the ENVIRONMENT VARIABLE through which a
# launching host pins the server to the run's project, or is explicitly null to
# declare the entry unpinnable. It is a channel rather than a flag because the
# advertised stdio shape carries no working directory, so naming the channel is
# the only way a declaration of pinnability can be acted on rather than believed.
# All three default unsafe-by-omission (a missing declaration fails), never
# silently permissive.
#
# :func:`_declare_registry` is the ONLY construction seam, and it both validates
# and FREEZES: the returned mapping and every entry inside it are read-only views
# over immutable values, so the registry cannot be extended, re-pointed, or
# re-declared by an importer after import. Membership is a trust claim, and a
# trust claim that any module can add with one assignment is not a claim at all.
# An entry may NOT declare ``env``: the field is refused at construction, because
# the two transports shape it irreconcilably and neither shape is servable to
# both. The ACP stdio spec models env as a LIST of name/value pairs; the Codex
# ``config.toml`` block models the same data as a FLAT MAPPING. A registry entry
# is read by both, so a flat mapping renders correctly for Codex and reaches an
# ACP session malformed (loudly if the run pins it, SILENTLY if it does not),
# while a list of pairs renders correctly for ACP and is refused outright by the
# Codex reader. There is no third shape: whichever an author picked, one
# transport would be wrong, and the dangerous half is the silent one.
#
# Refusing the field is smaller than teaching either side a projection, and it
# also makes a standing hazard unbreakable rather than merely documented. The
# session surface reaches the claude CLI as a dynamic MCP config parsed WITH env
# expansion, so a literal ``${...}`` in a registry env value would be expanded by
# the CLI from the SERVING process's environment at parse time - the same
# mechanism the authoring bridge deliberately rides, and precisely what a project
# pin must not do. A field that cannot be declared cannot carry that placeholder.
# The one env value a run still states - its project pin - enters through
# :func:`pin_harness_mcp_servers` (ACP) or the ``project_root`` argument (Codex),
# per run, from an explicit value, and :func:`_pin_value` refuses an expansion
# marker there. So the literals-only rule now holds by construction on the
# registry side and by enforcement on the one side values can still arrive.
#
# ``env`` remains in the launch key partition below because the Codex spec still
# CARRIES the field - it is built per run to hold the pin, rather than read from
# an entry.
_ENV_FIELD = "env"
_TRUST_AXES = ("read_only", "network_egress")
_ROOT_PIN_AXIS = "root_pin"
_EXACT_SURFACE_AXIS = "exact_surface"
RAG_MCP_REQUIREMENT = "vaultspec-rag[mcp]"
# The restricted launch is served from 0.1.56 onward. NO version constraint,
# per the registry's standing policy (asserted by its own test): the boundary
# is the SERVED SURFACE, checked before every launch. An older resolution
# rejects `--read-only` and is refused at the contract seam rather than
# surfaced wide. Operationally that means a stale `uvx` cache fails the lane
# loudly and repeatedly until it refreshes - accepted as fail-loud, and the
# reason a2a's own dependency floor names 0.1.56.
CORE_MCP_REQUIREMENT = "vaultspec-core"


def _validate_registry_entry(name: str, value: JsonValue) -> None:
    """Validate one declared server before registry freezing."""
    if not isinstance(value, dict):
        raise ConfigError(f"harness registry entry {name!r} must be a JSON object")
    for axis in _TRUST_AXES:
        if not isinstance(value.get(axis), bool):
            raise ConfigError(
                f"harness registry entry {name!r} does not declare {axis!r}; "
                "all three trust axes (local write, network egress, root pin) "
                "must be declared explicitly per entry - none is inferred from "
                "another, and omission is never read as permission"
            )
    if _ROOT_PIN_AXIS not in value:
        raise ConfigError(
            f"harness registry entry {name!r} does not declare "
            f"{_ROOT_PIN_AXIS!r}; state the environment variable a launching "
            "host pins the run's project through, or state null to declare the "
            "server unpinnable - a server whose project is chosen per call is "
            "not constrained by the other two axes, and omission is never read "
            "as permission"
        )
    pin = value[_ROOT_PIN_AXIS]
    if pin is not None and (not isinstance(pin, str) or not pin):
        raise ConfigError(
            f"harness registry entry {name!r} declares {_ROOT_PIN_AXIS!r} as "
            f"{pin!r}; the axis names the environment variable carrying the "
            "pin, or is null when the server cannot be pinned"
        )
    if not isinstance(value.get(_EXACT_SURFACE_AXIS), bool):
        raise ConfigError(
            f"harness registry entry {name!r} does not declare "
            f"{_EXACT_SURFACE_AXIS!r}; state whether the server's safety rests "
            "on a RESTRICTED LAUNCH, in which case the contract check asserts "
            "served-equals-declared so a lost restricting argument is a refused "
            "launch rather than a silently widened surface - omission is never "
            "read as permission"
        )
    if _ENV_FIELD in value:
        raise ConfigError(
            f"harness registry entry {name!r} declares {_ENV_FIELD!r}; the "
            "registry cannot carry an environment because the two transports "
            "shape it irreconcilably - the ACP stdio spec takes a list of "
            "name/value pairs and the Codex block takes a flat mapping, so "
            "either shape reaches the other transport wrong, and the flat one "
            "reaches an unpinned ACP session wrong WITHOUT complaint. State a "
            "run's project through the root-pin axis, which both transports "
            "render for themselves"
        )


def _declare_registry(
    entries: JsonObject,
) -> FrozenJsonObject:
    """Return a FROZEN registry once every entry declares all three trust axes.

    The registry's single construction seam, so the declaration obligation is
    discharged where entries are written rather than only where they are read.
    Local write, network reach, and root-pinnability are independent properties
    and each is declared per entry; an omitted or malformed axis is refused here,
    which makes an undeclared entry unconstructible rather than merely
    unsurfaceable.

    The two boolean axes are refused when absent or non-boolean. The root-pin axis
    is refused when ABSENT or when present as anything other than a non-empty
    string (the environment variable carrying the pin) or ``None`` (an explicit
    declaration that the server cannot be pinned). Presence is what is checked,
    not truthiness, so the unpinnable declaration is a deliberate statement an
    author had to write rather than a key they forgot.

    The returned mapping is a read-only view whose entries are themselves read-only
    views over immutable values. Membership in this registry IS a trust claim - it
    says a server was reviewed and may be surfaced into an agent's config - so it
    must not be assertable at runtime by any importer holding the name. Freezing
    here rather than at each reader keeps construction the only way in, which is
    what lets the surfacing seams reason about what can possibly reach them.

    An entry declaring ``env`` is refused outright. That is a REFUSAL rather than
    a validation because no shape would be correct: the two transports model a
    server's environment irreconcilably, so a declaration servable to one reaches
    the other malformed - and on the ACP path an unpinned run carries the wrong
    shape all the way to the session without complaint. Refusing the field at the
    only construction seam is what makes the silent half unreachable, and it keeps
    the registry's literals-only rule true by construction rather than by memory.

    Raises:
        ConfigError: If an entry omits any trust axis, declares either boolean
            axis non-boolean, declares the root-pin axis as anything other than a
            non-empty string or ``None``, or declares ``env``.
    """
    for name, value in entries.items():
        _validate_registry_entry(name, value)
    frozen = freeze_json(entries)
    if not isinstance(frozen, MappingProxyType):
        raise ConfigError("harness MCP registry must freeze to a JSON object")
    return frozen


_KNOWN_MCP_SERVERS: FrozenJsonObject = _declare_registry(
    {
        "vaultspec-rag": {
            "name": "vaultspec-rag",
            "command": "uvx",
            "args": ["--from", RAG_MCP_REQUIREMENT, "vaultspec-search-mcp"],
            "tools": ["search_vault", "search_codebase", "get_code_file"],
            "read_only": True,
            # Indexes and serves the local vault/codebase over stdio; no outbound
            # request leaves the agent host on its behalf.
            "network_egress": False,
            # The stdio server resolves the project a call addresses from the
            # call's explicit root, then this variable, then its own working
            # directory. Naming the variable here is what lets a run REPLACE the
            # working-directory fallback - undeclared inheritance through a
            # third-party CLI, correct as far as anyone has checked and verified
            # for nothing - with a stated per-run pin. The pin sets the project a
            # call addresses when it names none; a call that names another project
            # is a separate boundary, refused at the permission layer until the
            # server locks its stdio session to its launch root.
            "root_pin": "VAULTSPEC_RAG_ROOT",
            # The served surface legitimately exceeds this declaration: the search
            # server also mounts index-rebuild and index-clean verbs. That is
            # tolerable because those mutate a recoverable index under the search
            # storage root, never the vault, so the declaration is an allowlist
            # rather than the safety case.
            "exact_surface": False,
            "runtime_acquisition": True,
            "desktop_available": False,
        },
        "vaultspec-core": {
            "name": "vaultspec-core",
            "command": "uvx",
            # ``--read-only`` is the whole admission case. Unrestricted, this
            # server registers document scaffolding, body edits, plan mutation and
            # a gateway that subprocesses any cataloged verb - a writable vault
            # MCP, which a live incident proved an agent will use to write into the
            # vault behind every deny that guards the filesystem path. The
            # restricted launch registers only non-mutating handlers, so no
            # write-capable tool exists in the process to be handed or approved.
            "args": ["--from", CORE_MCP_REQUIREMENT, "vaultspec-mcp", "--read-only"],
            # Exactly what the restricted launch registers. ``check`` is safe to
            # declare ONLY here: unrestricted it takes a repair argument that a
            # tool-name allowlist cannot see, while the read-only launch registers
            # a validation-only signature and rejects a smuggled repair argument
            # server-side.
            "tools": ["status", "find", "check", "discover"],
            "read_only": True,
            # Local stdio server over the pinned project's own records; no
            # outbound request leaves the agent host on its behalf.
            "network_egress": False,
            # Bound ONCE at launch: the entrypoint takes no target argument, so
            # this variable is the whole channel, and the tool surface carries no
            # per-call project parameter at all. That makes the binding stronger
            # than a per-call default - there is no argument through which a run
            # could address another project.
            "root_pin": "VAULTSPEC_TARGET_DIR",
            # The restriction IS the safety case, so serving more than is declared
            # means the restriction is gone. Asserting equality turns a lost
            # ``--read-only`` into a refused launch instead of a silently restored
            # write surface that still passes a subset check.
            "exact_surface": True,
            "runtime_acquisition": True,
            "desktop_available": False,
        },
        # NO web-search entry belongs here. Web reach is delivered by the tools a
        # lane already has - the CLI lanes' own first-party search and fetch,
        # admitted through the native allowlist below - never by a server this
        # registry mounts. An entry naming a first-party web-search server was
        # briefly present and is removed: no such server exists or is planned, and
        # it wrapped a third-party package under a first-party name. The closed
        # registry gains nothing by carrying one, which is the standing decision.
    }
)

_DESKTOP_ACQUISITION_REASON = "runtime acquisition is disabled for the desktop profile"

# Path-free and provider-agnostic, like every other unavailable reason here: it
# is projected outward, so it names the axis and the missing proof rather than
# the server, the lane, or anything about the machine.
_UNPROVEN_EGRESS_REASON = (
    "the declared server reaches the network, and this lane carries no recorded "
    "live-retrieval proof"
)
_DESKTOP_CAPABILITY_ACTIONS = {
    "vaultspec-rag": (
        "Install the separately packaged vaultspec-rag desktop capability, then retry."
    ),
}


def _frozen_object(value: FrozenJsonValue, *, context: str) -> FrozenJsonObject:
    """Narrow one frozen JSON value to an object or refuse the registry shape."""
    if not isinstance(value, MappingProxyType):
        raise ConfigError(f"{context} must be a JSON object")
    return value


def _registry_entry(name: str) -> FrozenJsonObject:
    """Return one closed registry entry as a frozen JSON object."""
    value = _KNOWN_MCP_SERVERS.get(name)
    if value is None:
        raise ConfigError(
            f"unknown harness MCP server {name!r}; known servers are "
            f"{sorted(_KNOWN_MCP_SERVERS)}"
        )
    return _frozen_object(value, context=f"harness registry entry {name!r}")


def _frozen_strings(
    entry: FrozenJsonObject,
    field: str,
    *,
    required: bool = False,
) -> tuple[str, ...]:
    """Read one tuple-shaped string field from a frozen registry object."""
    value = entry.get(field)
    if value is None and not required:
        return ()
    if not isinstance(value, tuple):
        raise ConfigError(f"harness registry field {field!r} must be a string list")
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(f"harness registry field {field!r} must be a string list")
        strings.append(item)
    return tuple(strings)


def _frozen_string(entry: FrozenJsonObject, field: str) -> str:
    """Read one required string field from a frozen registry object."""
    value = entry.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            f"harness registry field {field!r} must be a non-empty string"
        )
    return value


def _declared_root_pin(name: str, entry: FrozenJsonObject) -> str | None:
    """Return the environment variable pinning *entry*, or ``None`` if unpinnable.

    The typed reader of the root-pin axis, sibling of :func:`harness_server_egresses`
    and for the same reason: an entry is a recursive JSON value, so reading the
    axis at each call site would narrow it a different way each time.

    Takes the entry rather than fetching it by name so the axis can be read off
    ANY entry the construction seam admitted, not only one the shipped registry
    happens to hold. That is what makes the refusal below reachable: the registry
    is closed and frozen by design, so a guard that could only ever see today's
    single pinnable entry would be a guard nothing can exercise.
    """
    value = entry.get(_ROOT_PIN_AXIS)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(
            f"harness registry entry {name!r} declares {_ROOT_PIN_AXIS!r} as "
            f"{value!r}; the axis names the environment variable carrying the pin"
        )
    return value


def _require_root_pin(name: str, entry: FrozenJsonObject) -> str:
    """Return *entry*'s pin variable, refusing a server that cannot be pinned.

    The root-pin axis of the trust root, and ENFORCEMENT rather than redundancy:
    :func:`_declare_registry` validates that the axis was DECLARED and admits a
    declared-unpinnable entry deliberately, exactly as it admits
    ``read_only: False``. Deciding whether an unpinnable server may reach a run is
    this function's job alone, and the decision is that it may not - an unpinnable
    server is one whose project is chosen per call with nothing on the launch side
    able to bind it, so surfacing it makes the absence of pinning a runtime hope
    instead of a composition-time refusal.

    Raises:
        ConfigError: If the entry declares itself unpinnable.
    """
    variable = _declared_root_pin(name, entry)
    if variable is None:
        raise ConfigError(
            f"refusing to compose harness server {name!r}, which declares no root "
            "pin: its project would be chosen per tool call with nothing on the "
            "launch side binding it to the run's, so it may not be surfaced to a "
            "run at all until it can be pinned"
        )
    return variable


def harness_server_exact_surface(name: str) -> bool:
    """Return whether *name*'s served surface must EQUAL its declaration.

    True for a server whose safety case is a restricted launch: the tools it
    would serve unrestricted are precisely the ones the restriction withholds, so
    serving more than was declared means the restriction is gone. False for a
    server that legitimately mounts more than a run declares, where the
    declaration is only the allowlist.

    Raises:
        ConfigError: If *name* is not a known harness server.
    """
    value = _registry_entry(name).get(_EXACT_SURFACE_AXIS)
    return bool(value)


def _launch_spec(name: str, entry: FrozenJsonObject) -> JsonObject:
    """Return the launch spec for one registry entry, free of registry metadata.

    The single renderer of a registry entry's LAUNCH, so the root-pin refusal
    applies to every spec either transport can produce rather than only to the
    ones that reach the spawn seam's trust-root check. Both transports render
    through it - the Codex path layers its own ``env`` shape and ``tools``
    allowlist on top - so the launch a run advertises cannot depend on which
    serialization asked for it, and the divergence guard
    (:func:`registry_launch_divergence`) can be bound to one rendering rather
    than to one of two.

    The name is taken from the registry KEY rather than from the entry body: the
    key is what every seam looks the entry up by, and an entry that omitted the
    field would otherwise render a nameless spec - refused later, far from the
    cause.

    Command and arguments are read through the typed registry readers rather than
    thawed blindly. :func:`_declare_registry` validates the trust axes and NOT the
    launch, so a malformed command or a non-string argument is a constructible
    entry; this is the only place that refusal exists for either transport.

    Raises:
        ConfigError: If the entry declares itself unpinnable, or declares a
            malformed command or argument vector.
    """
    _require_root_pin(name, entry)
    spec: JsonObject = {
        "name": name,
        "command": _frozen_string(entry, "command"),
        "args": list(_frozen_strings(entry, "args")),
    }
    return spec


# The launch fields a spec riding a registry-known name must carry unchanged from
# its entry. ``name`` is absent because it is the lookup key rather than a
# compared field, and ``env`` is absent because it legitimately VARIES PER RUN:
# no registry entry CAN declare one (the field is refused at construction, and a
# run's project is not knowable there anyway), the per-run pin appends
# the run's project through :func:`pin_harness_mcp_servers`, and the strict claude
# surface then rewrites every env value into a ``${NAME}`` placeholder. Comparing
# it would refuse every pinned run - which is why this is a comparison of LAUNCH
# IDENTITY rather than of the whole spec.
#
_LAUNCH_IDENTITY_KEYS = ("command", "args")


def registry_launch_divergence(
    spec: Mapping[str, JsonValue], *, name: str
) -> str | None:
    """Return how *spec*'s launch differs from *name*'s registry entry, or ``None``.

    The single comparison of a spec's launch identity against the entry it claims
    to be, so the registry is the trust root rather than the STRING that keys it.
    Membership in the closed registry is a review claim about a command, but every
    surfacing seam keys that claim by name and then reads command and arguments off
    the spec in hand - so a spec that merely BORROWS a reviewed name carries its own
    launch into a probe, into an agent's mounted tool surface, and into a
    client-visible refusal. Nothing in the type system stops one being built:
    ``mcp_servers`` is a settable field with a public setter.

    Command and arguments are BOTH compared. A reviewed name pointing at a
    different command is the same bypass as one pointing at different arguments -
    and for the entries whose safety case IS a restricting argument
    (``exact_surface``), the argument half is the safety case itself. The
    served-tool contract cannot substitute for either: a server that serves the
    declared names satisfies it whatever else it is.

    Equality is strict on both compared fields, and they are the only two
    compared; see :data:`_LAUNCH_IDENTITY_KEYS` for why ``env`` is excluded rather
    than forgotten.

    The comparison runs against :func:`_launch_spec` - the same renderer that
    produces every resolved spec - rather than against a second reading of the
    entry. A hand-rolled reading here would be a second opinion about what the
    registry declares, and this whole guard exists because a second opinion about
    a launch is what a borrowed name is.

    The returned description is redacted HERE rather than at the callers, for the
    reason the stderr tail is: it quotes a spec this project did not author, both
    raise sites put it in front of a client, and masking at the single point the
    text is produced is a property no later caller can forget to apply.

    Raises:
        ConfigError: If *name* is not a known harness server, or the entry it
            names cannot be rendered into a launch spec.
    """
    declared = _launch_spec(name, _registry_entry(name))
    for key in _LAUNCH_IDENTITY_KEYS:
        expected = declared.get(key)
        actual = spec.get(key)
        if actual != expected:
            return redact_secrets(
                f"declares the {key} {actual!r} where its registry entry declares "
                f"{expected!r}"
            )
    return None


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
    return _frozen_strings(_registry_entry(name), "tools")


def harness_server_egresses(name: str) -> bool:
    """Return whether the registry declares *name* as reaching outward.

    The single typed reader of the ``network_egress`` axis, and the sibling of
    :func:`declared_harness_tools`. Consumers ask this rather than subscripting
    the registry, for the reason the registry is frozen at all: an entry is a
    recursive JSON value, so ``entry.get("network_egress")`` is untypeable at the
    call site and each consumer would narrow it its own way. One reader keeps the
    axis meaning one thing.

    Raises:
        ConfigError: If *name* is not a known harness server.
    """
    return _registry_entry(name).get("network_egress") is True
