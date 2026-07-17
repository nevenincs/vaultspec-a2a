"""Resolve and compose team-harness-declared MCP servers into an ACP session.

A team's ``[team.harness]`` declares MCP server NAMES (e.g. ``"vaultspec-rag"``);
this module maps each known name to its stdio launch spec and unions the specs
into an ACP session model's ``mcp_servers`` surface, which ``setup_session``
advertises in the CLI's ``session/new`` params. The registry is explicit and
closed: a declared name with no entry is a configuration error refused at
composition time, never a silent no-op, and there is no plugin/discovery
machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..thread.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.language_models import BaseChatModel

__all__ = [
    "codex_mcp_server_specs",
    "compose_harness_mcp_servers",
    "config_home_mcp_servers",
    "harness_allowed_tool_names",
    "resolve_harness_mcp_servers",
]

# Known MCP server name -> registry entry. Explicit and closed by design.
# ``uvx --from vaultspec-rag vaultspec-search-mcp`` is used rather than the repo
# ``.mcp.json``'s ``uv run vaultspec-search-mcp`` because the ACP subprocess is
# spawned in the run workspace with no uv project cwd; uvx resolves the published
# package's console script independent of the cwd.
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
_LAUNCH_SPEC_KEYS = ("name", "command", "args", "env")
_KNOWN_MCP_SERVERS: dict[str, dict[str, Any]] = {
    "vaultspec-rag": {
        "name": "vaultspec-rag",
        "command": "uvx",
        "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
        "tools": ("search_vault", "search_codebase", "get_code_file"),
        "read_only": True,
    },
}


def _launch_spec(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the ACP-shape launch spec, stripped of registry-only metadata."""
    return {k: entry[k] for k in _LAUNCH_SPEC_KEYS if k in entry}


def resolve_harness_mcp_servers(names: Sequence[str]) -> list[dict[str, Any]]:
    """Resolve declared harness MCP server names to their launch specs.

    Raises :class:`ConfigError` naming every unknown server plus the known set,
    so a mistyped or unsupported declaration fails loudly here rather than
    silently dropping a server the run was told it would have.
    """
    specs: list[dict[str, Any]] = []
    unknown: list[str] = []
    for name in names:
        spec = _KNOWN_MCP_SERVERS.get(name)
        if spec is None:
            unknown.append(name)
        else:
            specs.append(_launch_spec(spec))
    if unknown:
        raise ConfigError(
            f"unknown harness MCP server(s) {unknown}; known servers are "
            f"{sorted(_KNOWN_MCP_SERVERS)}"
        )
    return specs


def harness_allowed_tool_names(names: Sequence[str]) -> list[str]:
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
    unknown: list[str] = []
    for name in names:
        entry = _KNOWN_MCP_SERVERS.get(name)
        if entry is None:
            unknown.append(name)
            continue
        for tool in entry.get("tools", ()):
            qualified = f"mcp__{name}__{tool}"
            if qualified not in seen:
                seen.add(qualified)
                tool_names.append(qualified)
    if unknown:
        raise ConfigError(
            f"unknown harness MCP server(s) {unknown}; known servers are "
            f"{sorted(_KNOWN_MCP_SERVERS)}"
        )
    return tool_names


def config_home_mcp_servers(
    mcp_servers: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Select the registry-known harness servers and shape them for ``.claude.json``.

    Given the session's advertised ``mcp_servers`` (which may also carry the per-run
    authoring bridge), keep ONLY those whose name is a known harness server and
    transform each ACP launch spec into the CLI user-global config shape keyed by
    name: ``{"<name>": {"type": "stdio", "command": ..., "args": [...], "env": ...}}``.
    Servers not in the registry (e.g. the authoring bridge) are excluded, so the
    isolated config home surfaces exactly the declared read-only harness servers.
    Returns an empty mapping when none match.
    """
    home: dict[str, dict[str, Any]] = {}
    for spec in mcp_servers:
        name = spec.get("name")
        if name not in _KNOWN_MCP_SERVERS:
            continue
        _require_read_only(name)
        entry: dict[str, Any] = {"type": "stdio", "command": spec["command"]}
        if spec.get("args"):
            entry["args"] = list(spec["args"])
        if spec.get("env"):
            entry["env"] = dict(spec["env"])
        home[name] = entry
    return home


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


def codex_mcp_server_specs(names: Sequence[str]) -> list[dict[str, Any]]:
    """Resolve declared harness names to full read-only registry specs for Codex.

    The registry's second serialization consumer (Codex ``config.toml`` vs the
    Claude ACP session): returns, per declared server, the fields the Codex
    ``[mcp_servers.<name>]`` block needs - ``name``, ``command``, ``args``,
    ``env``, and the read ``tools`` (for the ``enabled_tools`` allowlist). Applies
    the same fail-loud guards as the ACP path: an unknown name and a non-read-only
    entry both raise :class:`ConfigError`, so one registry stays the single trust
    root across both transports.
    """
    specs: list[dict[str, Any]] = []
    unknown: list[str] = []
    for name in names:
        entry = _KNOWN_MCP_SERVERS.get(name)
        if entry is None:
            unknown.append(name)
            continue
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
    if unknown:
        raise ConfigError(
            f"unknown harness MCP server(s) {unknown}; known servers are "
            f"{sorted(_KNOWN_MCP_SERVERS)}"
        )
    return specs


def compose_harness_mcp_servers(
    model: BaseChatModel,
    names: Sequence[str],
    *,
    allowed_tools: Sequence[str] | None = None,
) -> BaseChatModel:
    """Return a model advertising the declared harness MCP servers, or *model*.

    ADD-only: the resolved specs are UNIONED (by server name) with any the model
    already advertises - e.g. the per-run authoring bridge - never replacing
    them, so composition only ever widens the session's declared surface by
    exactly the harness declaration. A model with no ACP ``with_mcp_servers``
    surface (mock, hosted API) is returned unchanged, and an empty *names* is a
    no-op. Raises :class:`ConfigError` on an unknown declared name.

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
    if not names:
        return model
    # Validate the declared names FIRST, so an unknown name is refused loudly
    # regardless of model type - a configuration error is an error even when
    # composition is inapplicable (a non-ACP model) and would otherwise swallow
    # it silently.
    resolved = resolve_harness_mcp_servers(names)
    attach = getattr(model, "with_mcp_servers", None)
    if attach is None:
        # Codex lane: no ACP session surface, but its own config.toml delivery.
        codex_attach = getattr(model, "with_harness_mcp_servers", None)
        if codex_attach is not None:
            return codex_attach(names)
        return model
    existing = list(getattr(model, "mcp_servers", []) or [])
    seen = {s.get("name") for s in existing}
    combined = existing + [s for s in resolved if s.get("name") not in seen]
    if not allowed_tools:
        return attach(combined)
    existing_allowed = list(getattr(model, "allowed_tools", []) or [])
    allow_seen = set(existing_allowed)
    merged_allowed = existing_allowed + [
        t for t in allowed_tools if t not in allow_seen
    ]
    return attach(combined, merged_allowed)
