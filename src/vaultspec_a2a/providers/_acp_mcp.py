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
from enum import StrEnum
from pathlib import PurePath
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..authoring.contract import is_document_authoring_role
from ..thread.errors import ConfigError
from ._json_contract import (
    FrozenJsonObject,
    FrozenJsonValue,
    JsonObject,
    JsonValue,
    freeze_json,
)
from ._subprocess import redact_secrets
from .lane_admission import is_web_lane_proven

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from typing import Literal

    from langchain_core.language_models import BaseChatModel

__all__ = [
    "CORE_MCP_REQUIREMENT",
    "NATIVE_READ_TOOL_NAMES",
    "NATIVE_TOOL_EGRESS",
    "NATIVE_WEB_TOOL_BOUNDS",
    "RAG_MCP_REQUIREMENT",
    "HarnessMcpCapabilityUnavailable",
    "HarnessMcpResolution",
    "HarnessMcpRuntimeProfile",
    "NativeToolBoundHolder",
    "NativeToolDomainPosture",
    "NativeWebToolBounds",
    "codex_mcp_server_specs",
    "compose_harness_mcp_servers",
    "compose_native_read_tools",
    "declared_harness_tools",
    "harness_allowed_tool_names",
    "harness_server_egresses",
    "harness_server_exact_surface",
    "harness_server_root_pin",
    "harness_spawn_env",
    "is_known_harness_server",
    "pin_harness_mcp_servers",
    "registry_launch_divergence",
    "reject_duplicate_identities",
    "reject_duplicate_names",
    "require_declared_surface",
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
_LAUNCH_SPEC_KEYS = ("name", "command", "args", _ENV_FIELD)
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


def harness_server_root_pin(name: str) -> str | None:
    """Return the environment variable that pins *name*, or ``None``.

    The registry-keyed reader of the root-pin axis, for consumers that hold a
    declared name rather than an entry.

    Raises:
        ConfigError: If *name* is not a known harness server.
    """
    return _declared_root_pin(name, _registry_entry(name))


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
# Stated as a partition of ``_LAUNCH_SPEC_KEYS`` rather than as its own list, and
# asserted as one: a launch field added there but not classified here would be
# rendered into every spec while nothing compared it, which is the same silent
# widening this guard exists to close.
_LAUNCH_IDENTITY_KEYS = ("command", "args")
_LAUNCH_VARIANT_KEYS = ("name", "env")


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
        _launch_spec(name, _registry_entry(name))
        for name in resolution.available_servers
    ]
    if project_root is not None:
        resolved = pin_harness_mcp_servers(resolved, project_root=project_root)
    return resolution, unavailable_names, resolved


def compose_harness_mcp_servers(
    model: BaseChatModel,
    names: Sequence[str],
    *,
    allowed_tools: Sequence[str] | None = None,
    profile: HarnessMcpRuntimeProfile = HarnessMcpRuntimeProfile.NON_DESKTOP,
    project_root: str | None = None,
    lane: str | None = None,
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
    if not names and profile is HarnessMcpRuntimeProfile.NON_DESKTOP:
        return model
    resolution, unavailable_names, resolved = _resolve_harness_composition(
        model, names, profile=profile, project_root=project_root, lane=lane
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
    resolved: list[JsonObject],
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
        # The CLI's web built-ins, siblings of the read floor and delivered by the
        # same exact-name allowlist. They write nothing locally and would have
        # ridden the local-write assertion unchallenged; the egress axis is what
        # makes their reach sayable, and saying it is what lets them be composed
        # at all. Declared true here is a statement of reach, NOT an activation:
        # the names only ever reach an allowlist by way of a lane whose own
        # completed-retrieval proof carries them, and the guard below additionally
        # refuses any egressing built-in whose usage bounds were never stated.
        "WebSearch": True,
        "WebFetch": True,
    }
)


class NativeToolBoundHolder(StrEnum):
    """Who actually holds a native web built-in's bound.

    Named rather than assumed because the answer is not uniform and the difference
    decides what a change to the bound would even mean. :attr:`PROVIDER` bounds are
    compiled into the spawned CLI and are not settable by an embedder: the declared
    value is a contract asserted against served behaviour (the discipline the
    harness registry already applies to declared tool names), so revising it means
    re-verifying the binary, never editing a setting. :attr:`CITATION_CHANNEL`
    bounds are ours, held one layer up by the research-finding contract's cap on
    web locators per finding - a branch cannot cite more retrievals than it may
    make, so capping the citations caps the useful retrievals.
    """

    PROVIDER = "provider"
    CITATION_CHANNEL = "citation-channel"


class NativeToolDomainPosture(StrEnum):
    """Which way a web built-in's domain control is pointed.

    :attr:`BLOCKLIST` permits the open web minus what the provider refuses;
    :attr:`ALLOWLIST` permits only named domains and is the stricter posture held
    in reserve for a feature that needs it. The posture is visible in the spawn
    payload rather than only here: the CLI reads an allowlist entry as a permission
    rule, so a bare ``WebFetch`` is the blocklist posture rendered, while a
    domain-scoped ``WebFetch(domain:...)`` rule would be the allowlist one. Only
    bare declared names compose, so the served posture cannot silently invert.
    """

    BLOCKLIST = "blocklist"
    ALLOWLIST = "allowlist"


@dataclass(frozen=True, slots=True)
class NativeWebToolBounds:
    """The bounds one egressing native built-in runs under, and who holds each."""

    max_uses_per_branch: int
    uses_held_by: NativeToolBoundHolder
    content_held_by: NativeToolBoundHolder
    domain_posture: NativeToolDomainPosture


# The decided bounds for the egressing built-ins, in one place because the axis
# they express - how far outward reach may go per branch - is exactly as much a
# trust declaration as the reach itself, and an outward-reaching tool composed with
# no stated bound is the same unsafe-by-omission default the egress axis exists to
# refuse. The guard below enforces the bijection: every egressing name has bounds,
# and nothing else does.
#
# Verified against the CLI bundled with the pinned ACP adapter (claude-code 2.1.62)
# rather than taken from documentation, which describes the hosted API's server
# tools and their per-request parameters - a different surface that this lane does
# not expose to an embedder:
#
#   - search uses: the CLI pins its search tool at eight uses per request. The
#     decided bound and the served one coincide; there is no knob, and none is
#     invented here to pretend otherwise.
#   - fetch uses: the CLI offers no use cap for fetch, so the bound is held by the
#     citation channel's per-finding web-locator cap, which carries the same value.
#   - fetch content: the CLI never returns a fetched document to the agent's own
#     context - it converts the body and applies the tool's prompt through a
#     separate model turn - so the content bound is structural on that lane.
#   - domain posture: the CLI runs a per-hostname blocklist check before every
#     fetch unless a config-home setting disables it. Blocklist is therefore the
#     served posture by leaving that setting unwritten, and the isolated config
#     home must keep it that way.
NATIVE_WEB_TOOL_BOUNDS: Mapping[str, NativeWebToolBounds] = MappingProxyType(
    {
        "WebSearch": NativeWebToolBounds(
            max_uses_per_branch=8,
            uses_held_by=NativeToolBoundHolder.PROVIDER,
            content_held_by=NativeToolBoundHolder.PROVIDER,
            domain_posture=NativeToolDomainPosture.BLOCKLIST,
        ),
        "WebFetch": NativeWebToolBounds(
            max_uses_per_branch=16,
            uses_held_by=NativeToolBoundHolder.CITATION_CHANNEL,
            content_held_by=NativeToolBoundHolder.PROVIDER,
            domain_posture=NativeToolDomainPosture.BLOCKLIST,
        ),
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


def _require_bounds_match_the_egress_axis(
    egress: Mapping[str, bool], bounds: Mapping[str, NativeWebToolBounds]
) -> None:
    """Fail loud unless the bounds declaration and the egress axis name the same set.

    This bijection is the whole enforcement, and it is deliberately the only one.
    A per-composition bounds check would read well and never run: holding the two
    declarations in step means an egressing name is a bounded name by construction,
    so :func:`_require_declared_native_egress` already refuses everything such a
    check could have caught. Enforcing the invariant once, at import, is the honest
    shape - the alternative ships a guard nothing can reach and calls it defence.

    Stating it the other way round matters too: a bounds entry for a tool that
    never declared egress is a bound nothing enforces, because every consumer of
    the bounds selects by the egress axis first.

    Raises:
        ConfigError: If either declaration names a tool the other does not.
    """
    egressing = {name for name, reaches in egress.items() if reaches}
    bounded = set(bounds)
    if egressing != bounded:
        unbounded = sorted(egressing - bounded)
        unreaching = sorted(bounded - egressing)
        raise ConfigError(
            "the native tool egress axis and the web bounds declaration disagree: "
            f"egressing with no bounds: {unbounded or 'none'}; bounded but not "
            f"declared egressing: {unreaching or 'none'}. Both declarations govern "
            "the same tools and a guard consulting one must be able to trust the "
            "other"
        )


# The floor discharges the same declaration obligation at construction that
# :func:`_declare_registry` imposes on registry entries, so a name added to the
# floor without an egress declaration fails at import rather than at the first
# autonomous document run.
_require_declared_native_egress(NATIVE_READ_TOOL_NAMES)
_require_bounds_match_the_egress_axis(NATIVE_TOOL_EGRESS, NATIVE_WEB_TOOL_BOUNDS)


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
    allowlist on the strength of the local-read floor's assumptions. That single
    check also carries the bounds obligation, because the axis and
    :data:`NATIVE_WEB_TOOL_BOUNDS` are held to the same tool set at import: a name
    this seam admits as egressing has necessarily stated its bounds too.

    *extra_tool_names* is the composition point for lane-earned capability: it is
    where a lane's own completed-retrieval proof delivers the exact web built-ins
    that proof exercised. This function deliberately does NOT re-derive that
    verdict - the lane declaration has one reader, and a second one here could
    disagree with it - so an unearned name reaching this parameter is a caller
    defect, not a state this seam can distinguish. What it does guarantee is that
    whatever arrives is a bare declared name that stated both its reach and its
    bounds, and that a supervised run or a non-document role composes nothing at
    all regardless.

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
