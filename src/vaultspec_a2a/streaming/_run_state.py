"""The live state of a run's agents, tool calls and graph nodes, kept in one place.

The worker records that state as it emits a run's events, and the gateway
rebuilds the same state from the payloads the worker relays. Both apply the
mutations defined here, so a relayed event moves the gateway's copy exactly as
emitting it moved the worker's, and neither side carries its own reading of what
a tool-call update or a node registration means.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from ..graph.enums import AgentLifecycleState, ToolCallStatus, ToolKind
from .node_metadata import node_metadata_fields

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

__all__ = ["RunLiveState", "RunLiveStateMirror"]

#: Settled tool calls one run keeps for snapshot enrichment before the oldest go.
_SETTLED_TOOL_CALL_CAP = 50

_SETTLED_TOOL_CALL_STATUSES = (ToolCallStatus.COMPLETED, ToolCallStatus.FAILED)


class RunLiveState:
    """Agent lifecycle, tool-call and node-metadata state, keyed by run.

    A tool call is addressed by its *key*, ``(thread_id, tool_call_id)``, the
    same pair the emitters debounce its updates under.
    """

    def __init__(self) -> None:
        # Keyed by (thread_id, agent_id), never agent_id alone: one instance
        # serves every run its process handles, and an agent_id-only key let a
        # later run report a role state that an earlier run sharing the
        # agent_id left behind.
        self._agent_states: dict[tuple[str, str], AgentLifecycleState] = {}
        self._tool_call_states: dict[tuple[str, str], dict[str, str]] = {}
        self._node_metadata: dict[str, dict[str, dict[str, str]]] = {}

    def record_agent_state(
        self, thread_id: str, agent_id: str, state: AgentLifecycleState
    ) -> None:
        """Record one agent's current lifecycle state in one run."""
        self._agent_states[(thread_id, agent_id)] = state

    def get_agent_states(self, thread_id: str) -> dict[str, AgentLifecycleState]:
        """Return each agent's current lifecycle state in *thread_id*.

        The required run identity keeps a per-run projection from silently
        becoming a cross-run last-write-wins aggregate.
        """
        return {
            agent_id: state
            for (tid, agent_id), state in self._agent_states.items()
            if tid == thread_id
        }

    def start_tool_call(
        self, key: tuple[str, str], *, title: str, kind: ToolKind, agent_id: str
    ) -> None:
        """Register a tool call as pending under the id its provider gave it."""
        self._tool_call_states[key] = {
            "title": title,
            "kind": kind.value,
            "status": ToolCallStatus.PENDING.value,
            "agent_id": agent_id,
        }

    def update_tool_call(
        self,
        key: tuple[str, str],
        *,
        agent_id: str,
        status: ToolCallStatus | None,
        title: str | None,
    ) -> None:
        """Merge one update into a tool call's state.

        A call not seen before is registered when the update names a status or
        a title. A call that settles bounds how many settled calls its run keeps.
        """
        existing = self._tool_call_states.get(key)
        if existing is not None:
            if status is not None:
                existing["status"] = status.value
            if title is not None:
                existing["title"] = title
        elif status is not None or title is not None:
            self._tool_call_states[key] = {
                "title": title or "unknown_tool",
                "kind": ToolKind.OTHER.value,
                "status": (status or ToolCallStatus.PENDING).value,
                "agent_id": agent_id,
            }
        if status in _SETTLED_TOOL_CALL_STATUSES:
            self._prune_settled_tool_calls(key[0])

    def _prune_settled_tool_calls(self, thread_id: str) -> None:
        settled = [
            key
            for key, call in self._tool_call_states.items()
            if key[0] == thread_id and call.get("status") in _SETTLED_TOOL_CALL_STATUSES
        ]
        for key in settled[:-_SETTLED_TOOL_CALL_CAP]:
            self._tool_call_states.pop(key, None)

    def get_tool_call_states(self, thread_id: str) -> dict[str, dict[str, str]]:
        """Return a copy of each tool call's state in *thread_id*."""
        return {
            tool_call_id: dict(state)
            for (tid, tool_call_id), state in self._tool_call_states.items()
            if tid == thread_id
        }

    def record_node_metadata(
        self, thread_id: str, metadata: dict[str, dict[str, str]]
    ) -> None:
        """Replace the per-node team-status descriptors of one run."""
        self._node_metadata[thread_id] = metadata

    def get_node_metadata(self, thread_id: str) -> dict[str, dict[str, str]]:
        """Return the per-node team-status descriptors of *thread_id*."""
        return self._node_metadata.get(thread_id, {})

    def get_node_summaries(self, thread_id: str) -> list[dict[str, str]]:
        """Return one team-status summary per described node of *thread_id*."""
        return [
            {"node_name": name, "agent_id": name, **meta}
            for name, meta in self._node_metadata.get(thread_id, {}).items()
        ]

    def prune_tool_calls(self, active_thread_ids: set[str]) -> None:
        """Drop the tool-call state of every run outside *active_thread_ids*."""
        stale = [
            key for key in self._tool_call_states if key[0] not in active_thread_ids
        ]
        for key in stale:
            del self._tool_call_states[key]

    def clear_thread_state(self, thread_id: str) -> None:
        """Drop everything held for *thread_id*."""
        for agent_key in [key for key in self._agent_states if key[0] == thread_id]:
            del self._agent_states[agent_key]
        for call_key in [key for key in self._tool_call_states if key[0] == thread_id]:
            del self._tool_call_states[call_key]
        self._node_metadata.pop(thread_id, None)

    def clear(self) -> None:
        """Drop the state of every run."""
        self._agent_states.clear()
        self._tool_call_states.clear()
        self._node_metadata.clear()


class RunLiveStateMirror(RunLiveState):
    """The gateway's copy of the live run state, rebuilt from relayed worker events.

    Holds what the worker's own emissions recorded - agents, tool calls and
    graph nodes - and nothing else. It keeps no sequence, because a relayed
    frame is numbered where it enters subscriber queues, and no pending
    permission, because the durable permission row is the one served.
    """

    def sync_worker_event(self, thread_id: str, payload: Mapping[str, Any]) -> None:
        """Apply one relayed worker event to the mirrored state.

        An event type that carries no state to mirror is ignored.
        """
        match payload.get("type"):
            case "agent_status":
                self._sync_agent_status(thread_id, payload)
            case "graph_registered":
                self._sync_graph_registered(thread_id, payload)
            case "tool_call_start":
                self._sync_tool_call_start(thread_id, payload)
            case "tool_call_update":
                self._sync_tool_call_update(thread_id, payload)

    def _sync_agent_status(self, thread_id: str, payload: Mapping[str, Any]) -> None:
        agent_id = payload.get("agent_id", "")
        raw_state = payload.get("state", "")
        if not (agent_id and raw_state):
            return
        try:
            state = AgentLifecycleState(raw_state)
        except ValueError:
            logger.warning("Unknown agent state %r in relayed event", raw_state)
            return
        self.record_agent_state(thread_id, agent_id, state)

    def _sync_graph_registered(
        self, thread_id: str, payload: Mapping[str, Any]
    ) -> None:
        nodes_raw: object = payload.get("nodes", {})
        if not isinstance(nodes_raw, dict):
            return
        nodes = cast("dict[str, object]", nodes_raw)
        self.record_node_metadata(
            thread_id,
            {
                name: node_metadata_fields(cast("dict[str, object]", meta))
                for name, meta in nodes.items()
                if isinstance(meta, dict)
            },
        )
        logger.debug("sync_worker_event: cached metadata for %d nodes", len(nodes))

    def _sync_tool_call_start(self, thread_id: str, payload: Mapping[str, Any]) -> None:
        tool_call_id = payload.get("tool_call_id", "")
        if tool_call_id:
            self.start_tool_call(
                (thread_id, tool_call_id),
                title=payload.get("title", "unknown_tool"),
                kind=_relayed_tool_kind(payload.get("kind")),
                agent_id=payload.get("agent_id", ""),
            )

    def _sync_tool_call_update(
        self, thread_id: str, payload: Mapping[str, Any]
    ) -> None:
        tool_call_id = payload.get("tool_call_id", "")
        if tool_call_id:
            self.update_tool_call(
                (thread_id, tool_call_id),
                agent_id=payload.get("agent_id", ""),
                status=_relayed_tool_status(payload.get("status")),
                title=payload.get("title") or None,
            )


def _relayed_tool_kind(raw: object) -> ToolKind:
    """Read a relayed tool kind, taking the catch-all for one it does not name."""
    try:
        return ToolKind(raw)
    except ValueError:
        return ToolKind.OTHER


def _relayed_tool_status(raw: object) -> ToolCallStatus | None:
    """Read a relayed tool-call status, or ``None`` where the update carries none."""
    if not raw:
        return None
    try:
        return ToolCallStatus(raw)
    except ValueError:
        logger.warning("Unknown tool-call status %r in relayed event", raw)
        return None
