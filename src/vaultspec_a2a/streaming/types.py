"""Streaming types, protocols, and stateless classification helpers.

Extracted from the monolithic ``aggregator.py`` during the aggregator
decomposition.  Contains no mutable state — pure data definitions
and lookup tables only.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from langgraph.types import Command

from ..graph.enums import PermissionOptionKind, ToolCallStatus, ToolKind
from ..graph.events import DomainEvent

__all__ = [
    "SequencedEvent",
    "StreamableGraph",
    "action_detail_projection",
    "classify_tool_kind",
    "map_action_item_status",
    "parse_action_detail",
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


# ---------------------------------------------------------------------------
# Provider action items (F17) — a provider-internal action (an ACP CLI's own
# built-in tools; Codex's commandExecution/fileChange/mcpToolCall) never goes
# through a real LangChain BaseTool/ToolNode, so it never produces the
# on_tool_start/on_tool_end pair or a ToolMessage a genuine tool call would.
# Codex's own model (``codex_chat_model._completed_action_chunk``) instead
# rides the model's own stream: it encodes the item's terminal outcome
# directly into a synthetic tool_call_chunk's ``args``, deliberately so it
# lands in checkpointed state the same way a real tool call's arguments do.
# These helpers are the ONE place that shape is read, so the live stream
# (streaming.transformer, watching astream_events as it happens) and a
# settled run's REST snapshot (control.snapshot, reading the same shape back
# out of checkpointed AIMessage.tool_calls after the aggregator's in-memory
# state has been pruned) classify the identical detail identically — a
# provider action can never be reported COMPLETED on one surface and PENDING
# on the other because it was reached through two independent guesses.
# ---------------------------------------------------------------------------

#: Recognised terminal/near-terminal item statuses this repo's own
#: ``ToolCallStatus`` already names. A provider action item's status
#: vocabulary is owned by that provider's own schema (e.g. the Codex
#: app-server's generated protocol), not enumerated here.
_KNOWN_ACTION_ITEM_STATUSES = frozenset({status.value for status in ToolCallStatus})


def map_action_item_status(raw_status: object) -> ToolCallStatus:
    """Map a provider action item's status onto the closed ``ToolCallStatus`` set.

    A value this repo already recognises (``completed``, ``failed``,
    ``in_progress``, ``pending``) is honoured directly. Anything else -- a
    policy rejection, an abort, a spelling this lane has not been observed
    using yet -- is treated as FAILED rather than risking a silent COMPLETED
    on a call that did not succeed. That silent-success risk is the exact
    shape of F17: one of the 15 stuck-pending tool calls in the reference
    incident was a policy-rejected command the model narrated but the record
    never showed as anything but pending.
    """
    if isinstance(raw_status, str) and raw_status in _KNOWN_ACTION_ITEM_STATUSES:
        return ToolCallStatus(raw_status)
    return ToolCallStatus.FAILED


def parse_action_detail(raw_args: object) -> dict[str, Any] | None:
    """Parse a tool-call chunk's ``args`` as a JSON object, or return ``None``.

    Two shapes reach here through the same field: a plain tool's raw input
    (ACP's initial registration, or a partial ``tool_call_chunk`` arg-delta -
    just the tool's own arguments, no ``status`` key) and Codex's one-shot
    completed-action report (``{"command", "status", "exit_code", ...}`` -
    see ``codex_chat_model._completed_action_chunk``). Both are returned as a
    parsed dict when parseable; the caller distinguishes them by the presence
    of ``status``. A non-JSON or non-object payload returns ``None`` rather
    than raising, since malformed args must not stop live tool-call
    registration.
    """
    if not isinstance(raw_args, str) or not raw_args:
        return None
    try:
        parsed = json.loads(raw_args)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def action_detail_projection(
    item_type: str, detail: dict[str, Any]
) -> tuple[list[dict[str, str | None]], list[dict[str, str | int | None]]]:
    """Project a Codex completed-action detail onto (content, locations).

    Each action item type carries different REQUIRED fields (see
    ``codex_chat_model._completed_action_chunk``, which reads only the
    schema-required fields per variant); this mirrors that per-type shape
    rather than guessing at a common one. ``fileChange`` is the only variant
    that names a location a frontend could jump to, so it is the only one
    that returns non-empty locations.
    """
    if item_type == "commandExecution":
        command = detail.get("command")
        exit_code = detail.get("exit_code")
        parts = [f"$ {command}"] if command else []
        if exit_code is not None:
            parts.append(f"(exit {exit_code})")
        text = "\n".join(parts)
        return ([{"content_type": "text", "text": text}] if text else []), []
    if item_type == "fileChange":
        changes = detail.get("changes")
        locations: list[dict[str, str | int | None]] = []
        if isinstance(changes, list):
            for change in changes:
                if isinstance(change, dict):
                    path = change.get("path")
                    if isinstance(path, str) and path:
                        locations.append({"path": path, "line": None})
        text = f"{len(locations)} file(s) changed" if locations else ""
        return ([{"content_type": "text", "text": text}] if text else []), locations
    if item_type == "mcpToolCall":
        server = detail.get("server")
        tool = detail.get("tool")
        text = f"{server}:{tool}" if server and tool else str(tool or server or "")
        return ([{"content_type": "text", "text": text}] if text else []), []
    return [], []


def _map_acp_option_kind(option_id: str) -> PermissionOptionKind:
    # PRIVATE on purpose. This id-substring heuristic is the resolver's LAST
    # RESORT, not a peer it can be chosen instead of. It was public once, and a
    # second consumer picked it over the resolver and classified a declared
    # denial as an approval - the same failure the resolver had already been
    # written to end. Reaching it now means going through
    # `resolve_acp_option_kind`, which is the only caller that knows when the
    # declaration is unusable.
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
    routed to :func:`_map_acp_option_kind`, so a malformed or unknown kind degrades
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
    return _map_acp_option_kind(option_id)


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
