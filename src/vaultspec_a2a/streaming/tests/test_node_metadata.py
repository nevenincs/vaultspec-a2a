"""Every reader of a graph node's team-status metadata agrees on the fields.

The four readers - the worker's ``graph_registered`` payload builder, the
subscriber cache, the relayed-payload sync that rebuilds that cache, and the
team-status emitter - used to spell the same six fields out independently.
They agreed only by repetition, so the direct path and the relayed path could
drift apart on a field added to one. These tests drive the real seams (no
mocks) and pin that agreement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest

from ...graph.enums import AgentLifecycleState
from ...graph.events import TeamStatus
from ..aggregator import EventAggregator
from ..node_metadata import (
    NODE_METADATA_FIELDS,
    node_metadata_fields,
    node_metadata_from_graph,
)

if TYPE_CHECKING:
    from ..types import StreamableGraph


class _Node:
    def __init__(self, **metadata: str) -> None:
        self.metadata = metadata


class _BareNode:
    """A structural graph node carrying no metadata at all."""

    metadata: ClassVar[dict[str, str]] = {}


class _Graph:
    """Minimal duck-typed stand-in for a compiled graph's ``nodes`` mapping.

    Matches the duck typing ``register_graph`` itself uses (``getattr(graph,
    "nodes", {})`` then ``getattr(node_spec, "metadata", None)``), so this
    exercises the production access path rather than substituting for it.
    """

    def __init__(self, nodes: dict[str, Any]) -> None:
        self.nodes = nodes


def _graph() -> _Graph:
    return _Graph(
        {
            "reviewer": _Node(
                role="reviewer",
                display_name="Code Reviewer",
                description="Reviews code for correctness",
                provider="claude",
                model="opus",
            ),
            "__start__": _BareNode(),
        }
    )


class TestNodeMetadataFields:
    """The single field-list definition behaves as every reader expects."""

    def test_extracts_exactly_the_declared_fields(self) -> None:
        fields = node_metadata_fields(
            {
                "role": "reviewer",
                "display_name": "Code Reviewer",
                "description": "Reviews code",
                "provider": "claude",
                "model": "opus",
                "unrelated": "ignored",
            }
        )
        assert set(fields) == set(NODE_METADATA_FIELDS)
        assert fields["role"] == "reviewer"
        assert fields["model"] == "opus"
        assert "unrelated" not in fields

    def test_missing_keys_become_empty_strings_not_omissions(self) -> None:
        fields = node_metadata_fields({"role": "reviewer"})
        assert set(fields) == set(NODE_METADATA_FIELDS)
        assert fields["display_name"] == ""

    def test_non_string_values_are_coerced(self) -> None:
        # Node metadata is author-supplied; the wire contract is str-valued.
        fields = node_metadata_fields({"role": 7, "model": None})
        assert fields["role"] == "7"
        assert fields["model"] == "None"

    def test_graph_walk_skips_nodes_without_metadata(self) -> None:
        extracted = node_metadata_from_graph(_graph())
        assert set(extracted) == {"reviewer"}
        assert extracted["reviewer"]["display_name"] == "Code Reviewer"

    def test_graph_without_nodes_yields_empty(self) -> None:
        assert node_metadata_from_graph(object()) == {}


def test_direct_and_relayed_registration_agree_field_for_field() -> None:
    """The in-process path and the worker-relayed path build the same cache.

    This is the anti-drift property: the worker sends ``graph_registered`` built
    from the same extraction the local ``register_graph`` performs, and the
    control surface rebuilds its cache from that payload. A field reaching one
    path and not the other would show up here as unequal caches.
    """
    graph = _graph()

    direct = EventAggregator()
    direct.register_graph(cast("StreamableGraph", graph))

    # Exactly the payload vaultspec_a2a.worker.graph_lifecycle relays.
    relayed = EventAggregator()
    relayed.sync_worker_event(
        "thread-1",
        {"type": "graph_registered", "nodes": node_metadata_from_graph(graph)},
    )

    direct_summaries = direct.get_node_summaries()
    assert direct_summaries == relayed.get_node_summaries()
    # Pinned literally rather than only against each other: the two paths now
    # share one extraction, so a same-direction change to that extraction would
    # keep them equal while still breaking the wire contract.
    assert direct_summaries == [
        {
            "node_name": "reviewer",
            "agent_id": "reviewer",
            "role": "reviewer",
            "display_name": "Code Reviewer",
            "description": "Reviews code for correctness",
            "provider": "claude",
            "model": "opus",
            # Empty, not absent: this fixture's node carries no frozen catalog
            # entry, and every summary keeps the same shape so no consumer has
            # to guard a key.
            "model_name": "",
        }
    ]
    assert set(direct_summaries[0]) == {
        "node_name",
        "agent_id",
        *NODE_METADATA_FIELDS,
    }


@pytest.mark.asyncio
async def test_team_status_defaults_every_field_but_keeps_caller_values() -> None:
    """emit_team_status fills all six fields, without clobbering supplied ones."""
    aggregator = EventAggregator()
    queue = aggregator.add_subscriber("client-1")
    aggregator.subscribe("client-1", ["thread-1"])
    aggregator.register_graph(cast("StreamableGraph", _graph()))

    await aggregator.emit_team_status(
        thread_id="thread-1",
        agents=[
            {
                "agent_id": "a1",
                "node_name": "reviewer",
                "state": AgentLifecycleState.WORKING,
                # Caller-supplied: must survive the metadata defaulting.
                "model": "caller-pinned",
            }
        ],
    )

    event = queue.get_nowait().event
    assert isinstance(event, TeamStatus)
    summary = event.agents[0]
    for field in NODE_METADATA_FIELDS:
        assert field in summary, f"{field} missing from the team-status summary"
    assert summary["role"] == "reviewer"
    assert summary["display_name"] == "Code Reviewer"
    assert summary["provider"] == "claude"
    assert summary["model"] == "caller-pinned"
