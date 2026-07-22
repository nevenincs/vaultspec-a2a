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
from typing import TYPE_CHECKING, Any

from ..thread.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Literal

    from langchain_core.language_models import BaseChatModel

__all__ = [
    "HarnessMcpCapabilityUnavailable",
    "HarnessMcpResolution",
    "HarnessMcpRuntimeProfile",
    "codex_mcp_server_specs",
    "compose_harness_mcp_servers",
    "config_home_mcp_servers",
    "harness_allowed_tool_names",
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
# ``uvx --from vaultspec-rag[mcp]==0.3.2 vaultspec-search-mcp`` is used rather
# than the repo ``.mcp.json``'s ``uv run vaultspec-search-mcp`` because the ACP
# subprocess is spawned in the run workspace with no uv project cwd. The exact
# package extra and version deliberately reproduce the project lock's MCP
# capability while remaining independent of the cwd.
#
# ``tools`` is registry metadata, NOT part of the ACP ``session/new`` mcpServer
# shape: it names the server's READ-ONLY tools that may join the autonomous
# allowlist (``mcp__<server>__<tool>``). It is stripped from the launch spec in
# ``resolve_harness_mcp_servers`` so it never leaks into the session payload. The
# write verbs the rag server also exposes (``reindex_vault``/``reindex_codebase``)
# are deliberately omitted, honoring the read-only composition boundary.
# ``read_only`` is the registry's trust-root marker: only an entry explicitly
# flagged read-only may ever be written into the surfacing config home. It is
# asserted fail-loud at :func:`config_home_mcp_servers` build time so a future
# drifted or write-capable entry cannot be silently surfaced. The default is
# unsafe-by-omission (a missing/false flag fails), never silently permissive.
# WARNING: the config home is written with user-scope env expansion, so a literal
# ``${...}`` placed in a future registry ``env`` value would be expanded by the
# CLI from its process environment at parse time (the same mechanism the
# authoring bridge relies on) — registry env values must be literals, never
# accidental ``${...}`` strings.
_LAUNCH_SPEC_KEYS = ("name", "command", "args", "env")
_LOCKED_RAG_MCP_REQUIREMENT = "vaultspec-rag[mcp]==0.3.2"
_KNOWN_MCP_SERVERS: dict[str, dict[str, Any]] = {
    "vaultspec-rag": {
        "name": "vaultspec-rag",
        "command": "uvx",
        "args": ["--from", _LOCKED_RAG_MCP_REQUIREMENT, "vaultspec-search-mcp"],
        "tools": ("search_vault", "search_codebase", "get_code_file"),
        "read_only": True,
        "runtime_acquisition": True,
        "desktop_available": False,
    },
}

_DESKTOP_ACQUISITION_REASON = "runtime acquisition is disabled for the desktop profile"
_DESKTOP_CAPABILITY_ACTIONS = {
    "vaultspec-rag": (
        "Install the separately packaged vaultspec-rag desktop capability, then retry."
    ),
}


def _launch_spec(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the ACP-shape launch spec, stripped of registry-only metadata."""
    return {k: entry[k] for k in _LAUNCH_SPEC_KEYS if k in entry}


def _desktop_available(entry: dict[str, Any]) -> bool:
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
        _require_read_only(name)
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

    The single trust-root guard shared by both delivery shapes (Claude config
    home and Codex config.toml): registry drift toward a write-capable entry can
    never be silently composed into a surfacing config, on either transport.
    """
    if not _KNOWN_MCP_SERVERS[name].get("read_only"):
        raise ConfigError(
            f"refusing to compose non-read-only harness server {name!r} into a "
            "surfacing config; only read-only servers may be composed"
        )


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
    the same fail-loud guards as the ACP path: an unknown name and a non-read-only
    entry both raise :class:`ConfigError`, so one registry stays the single trust
    root across both transports.
    """
    reject_duplicate_names(names)
    resolution = resolve_harness_mcp_capabilities(names, profile=profile)
    specs: list[dict[str, Any]] = []
    for name in resolution.available_servers:
        entry = _KNOWN_MCP_SERVERS[name]
        _require_read_only(name)
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
    # Validate the declared names FIRST, so an unknown name is refused loudly
    # regardless of model type - a configuration error is an error even when
    # composition is inapplicable (a non-ACP model) and would otherwise swallow
    # it silently.
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
    if not resolved and not unavailable_names:
        return model
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
