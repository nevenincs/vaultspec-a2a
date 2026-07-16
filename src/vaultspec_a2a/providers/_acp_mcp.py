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

__all__ = ["compose_harness_mcp_servers", "resolve_harness_mcp_servers"]

# Known MCP server name -> ACP ``session/new`` stdio launch spec. Explicit and
# closed by design. ``uvx --from vaultspec-rag vaultspec-search-mcp`` is used
# rather than the repo ``.mcp.json``'s ``uv run vaultspec-search-mcp`` because
# the ACP subprocess is spawned in the run workspace with no uv project cwd; uvx
# resolves the published package's console script independent of the cwd.
_KNOWN_MCP_SERVERS: dict[str, dict[str, Any]] = {
    "vaultspec-rag": {
        "name": "vaultspec-rag",
        "command": "uvx",
        "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
    },
}


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
            specs.append(dict(spec))
    if unknown:
        raise ConfigError(
            f"unknown harness MCP server(s) {unknown}; known servers are "
            f"{sorted(_KNOWN_MCP_SERVERS)}"
        )
    return specs


def compose_harness_mcp_servers(
    model: BaseChatModel, names: Sequence[str]
) -> BaseChatModel:
    """Return a model advertising the declared harness MCP servers, or *model*.

    ADD-only: the resolved specs are UNIONED (by server name) with any the model
    already advertises - e.g. the per-run authoring bridge - never replacing
    them, so composition only ever widens the session's declared surface by
    exactly the harness declaration. A model with no ACP ``with_mcp_servers``
    surface (mock, hosted API) is returned unchanged, and an empty *names* is a
    no-op. Raises :class:`ConfigError` on an unknown declared name.
    """
    if not names:
        return model
    attach = getattr(model, "with_mcp_servers", None)
    if attach is None:
        return model
    resolved = resolve_harness_mcp_servers(names)
    existing = list(getattr(model, "mcp_servers", []) or [])
    seen = {s.get("name") for s in existing}
    combined = existing + [s for s in resolved if s.get("name") not in seen]
    return attach(combined)
