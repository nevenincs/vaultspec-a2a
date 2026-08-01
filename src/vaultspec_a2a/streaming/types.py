"""Streaming types, protocols, and stateless classification helpers.

Extracted from the monolithic ``aggregator.py`` during the aggregator
decomposition.  Contains no mutable state — pure data definitions
and lookup tables only.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from langgraph.types import Command

from ..graph.enums import PermissionOptionKind, ToolKind
from ..graph.events import DomainEvent

__all__ = [
    "SequencedEvent",
    "StreamableGraph",
    "classify_tool_kind",
]


@dataclass
class SequencedEvent:
    """Pairs a domain event with its per-thread monotonic sequence number.

    The sequence is a wire-protocol concern and does not belong
    on the domain event itself.  This lightweight wrapper carries both values
    through the subscriber queue so the API boundary can translate to wire
    format via ``api.event_adapter.domain_to_wire()``.
    """

    event: DomainEvent
    sequence: int


@runtime_checkable
class StreamableGraph(Protocol):
    """Structural protocol for a compiled LangGraph graph with astream_events."""

    def astream_events(
        self,
        graph_input: dict[str, Any] | Command | None,
        config: dict[str, Any],
        *,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw LangGraph event dicts."""
        ...

    async def aget_state(self, config: dict[str, Any]) -> object:
        """Return the current checkpointer state snapshot."""
        ...


# ---------------------------------------------------------------------------
# Tool name → ToolKind classification
# ---------------------------------------------------------------------------
_TOOL_KIND_MAP: dict[str, ToolKind] = {
    # Read / inspect
    "read": ToolKind.READ,
    "read_file": ToolKind.READ,
    "cat": ToolKind.READ,
    "view": ToolKind.READ,
    "head": ToolKind.READ,
    "tail": ToolKind.READ,
    # Edit / write
    "edit": ToolKind.EDIT,
    "edit_file": ToolKind.EDIT,
    "write": ToolKind.EDIT,
    "write_file": ToolKind.EDIT,
    "create": ToolKind.EDIT,
    "insert": ToolKind.EDIT,
    "replace": ToolKind.EDIT,
    "patch": ToolKind.EDIT,
    "save": ToolKind.EDIT,
    # Delete
    "delete": ToolKind.DELETE,
    "remove": ToolKind.DELETE,
    "rm": ToolKind.DELETE,
    # Move / rename
    "move": ToolKind.MOVE,
    "rename": ToolKind.MOVE,
    "mv": ToolKind.MOVE,
    # Search
    "search": ToolKind.SEARCH,
    "grep": ToolKind.SEARCH,
    "find": ToolKind.SEARCH,
    "glob": ToolKind.SEARCH,
    "rg": ToolKind.SEARCH,
    "ripgrep": ToolKind.SEARCH,
    # Execute / shell
    "execute": ToolKind.EXECUTE,
    "bash": ToolKind.EXECUTE,
    "shell": ToolKind.EXECUTE,
    "run": ToolKind.EXECUTE,
    "terminal": ToolKind.EXECUTE,
    "exec": ToolKind.EXECUTE,
    # Think
    "think": ToolKind.THINK,
    # Fetch / network
    "fetch": ToolKind.FETCH,
    "curl": ToolKind.FETCH,
    "http": ToolKind.FETCH,
    "download": ToolKind.FETCH,
    "web": ToolKind.FETCH,
    # Mode switching
    "switch_mode": ToolKind.SWITCH_MODE,
}

# Substring fallbacks for tool names that don't match exactly
_TOOL_KIND_SUBSTRING_RULES: list[tuple[str, ToolKind]] = [
    ("read", ToolKind.READ),
    ("edit", ToolKind.EDIT),
    ("write", ToolKind.EDIT),
    ("delete", ToolKind.DELETE),
    ("remove", ToolKind.DELETE),
    ("move", ToolKind.MOVE),
    ("rename", ToolKind.MOVE),
    ("search", ToolKind.SEARCH),
    ("grep", ToolKind.SEARCH),
    ("glob", ToolKind.SEARCH),
    ("exec", ToolKind.EXECUTE),
    ("bash", ToolKind.EXECUTE),
    ("shell", ToolKind.EXECUTE),
    ("terminal", ToolKind.EXECUTE),
    ("think", ToolKind.THINK),
    ("fetch", ToolKind.FETCH),
    ("curl", ToolKind.FETCH),
]


def classify_tool_kind(tool_name: str) -> ToolKind:
    """Classify a tool name into a ``ToolKind`` category.

    Two-pass: exact match on lowered name, then substring scan.
    Defaults to ``ToolKind.OTHER``.
    """
    lower = tool_name.lower()
    # Exact match
    kind = _TOOL_KIND_MAP.get(lower)
    if kind is not None:
        return kind
    # Substring fallback
    for keyword, kind in _TOOL_KIND_SUBSTRING_RULES:
        if keyword in lower:
            return kind
    return ToolKind.OTHER


def map_acp_option_kind(option_id: str) -> PermissionOptionKind:
    """Derive a ``PermissionOptionKind`` from an ACP option ID string.

    Heuristic matching: looks for ``always`` + ``deny``/``reject`` keywords to
    classify the option kind.  Defaults to ``ALLOW_ONCE`` for unrecognised ids.

    The default is deliberately permissive and must stay that way: the keywords
    only detect *rejecting* spellings, so every approving id this system mints --
    ``"approve"``, ``"approve_for_session"``, ``"allow_once"`` -- carries no
    keyword at all and reaches the default. Failing closed here would classify
    every one of them as a denial.

    This is the *derivation*, not the authority. Prefer
    :func:`resolve_acp_option_kind`, which consults the kind the provider actually
    declared and reaches for this only when there is none to consult.

    Args:
        option_id: The raw ACP option ID string (e.g. ``"allow_always"``).

    Returns:
        The matching ``PermissionOptionKind`` member.
    """
    oid = option_id.lower()
    if "always" in oid and ("deny" in oid or "reject" in oid):
        return PermissionOptionKind.REJECT_ALWAYS
    if "always" in oid:
        return PermissionOptionKind.ALLOW_ALWAYS
    if "deny" in oid or "reject" in oid:
        return PermissionOptionKind.REJECT_ONCE
    return PermissionOptionKind.ALLOW_ONCE


def resolve_acp_option_kind(
    declared_kind: object,
    option_id: str,
) -> PermissionOptionKind:
    """Resolve an ACP option's kind, preferring what the provider declared.

    The ACP schema has the agent declare each option's ``kind`` alongside its id,
    and that declaration is the only authority on whether the option denies. An id
    is free-form and provider-defined, so deriving the kind from it discards the
    one field that carries the answer: an agent offering a rejecting option under
    an id spelling neither ``deny`` nor ``reject`` -- and nothing obliges it to use
    either -- was persisted as an approval, with no way for any later reader to
    recover the denial.

    The declaration is validated rather than trusted: a value outside
    :class:`PermissionOptionKind` is not written through to the durable column but
    routed to :func:`map_acp_option_kind`, so a malformed or unknown kind degrades
    to the id heuristic instead of poisoning the record with an unreadable status.

    Args:
        declared_kind: The option's ``kind`` field as the provider sent it. A
                       ``PermissionOptionKind``, its bare string value, ``None``,
                       or any other type -- only a schema-valid string is honoured.
        option_id:     The option's resolved id, used for the fallback derivation.

    Returns:
        The declared kind when it is schema-valid, else the kind derived from the id.
    """
    if isinstance(declared_kind, str) and declared_kind:
        try:
            return PermissionOptionKind(declared_kind)
        except ValueError:
            pass
    return map_acp_option_kind(option_id)


def evict_oldest(d: dict, max_entries: int) -> None:
    """Remove oldest entries (by value = timestamp) until at max_entries."""
    to_remove = len(d) - max_entries
    if to_remove <= 0:
        return
    # Sort by timestamp (value), evict the oldest.
    for key in sorted(d, key=d.__getitem__)[:to_remove]:
        del d[key]


# ---------------------------------------------------------------------------
# LangGraph event filtering — research §1.2
# ---------------------------------------------------------------------------
PASSTHROUGH_EVENTS = frozenset(
    {
        "on_chat_model_stream",
        "on_chat_model_end",
        "on_tool_start",
        "on_tool_end",
        "on_tool_error",
        "on_custom_event",
    }
)

NODE_BOUNDARY_EVENTS = frozenset(
    {
        "on_chain_start",
        "on_chain_end",
        "on_chain_error",
    }
)
