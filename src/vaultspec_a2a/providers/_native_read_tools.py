"""Declared native read and web tool bounds for ACP composition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..authoring.contract import is_document_authoring_role
from ..thread.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from langchain_core.language_models import BaseChatModel

__all__ = [
    "NATIVE_READ_TOOL_NAMES",
    "NATIVE_TOOL_EGRESS",
    "NATIVE_WEB_TOOL_BOUNDS",
    "NativeToolBoundHolder",
    "NativeToolDomainPosture",
    "NativeWebToolBounds",
    "_require_bounds_match_the_egress_axis",
    "compose_native_read_tools",
]

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


def _declared_native_tool_names(extra_tool_names: Sequence[str] | None) -> list[str]:
    composed_names = list(NATIVE_READ_TOOL_NAMES)
    composed_names += [
        name for name in (extra_tool_names or ()) if name not in composed_names
    ]
    _require_declared_native_egress(composed_names)
    return composed_names


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
    composed_names = _declared_native_tool_names(extra_tool_names)
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
