"""Provide ordered runtime event streaming.

:class:`vaultspec_a2a.streaming.aggregator.EventAggregator` ingests, buffers,
sequences, and emits execution events. :mod:`vaultspec_a2a.streaming.types`
defines the streamable graph protocol and tool-kind classification.

Events enter from :mod:`vaultspec_a2a.graph.events`. Workers publish through
:mod:`vaultspec_a2a.worker`. Server-Sent Events and WebSocket consumers live in
:mod:`vaultspec_a2a.api`.

This package owns event aggregation. API and control modules consume its
sequenced output.
"""

from .aggregator import EventAggregator
from .custom_writes import emit_custom_node_write
from .node_metadata import (
    NODE_METADATA_FIELDS,
    node_metadata_fields,
    node_metadata_from_graph,
)
from .subscribers import (
    AllocationSink,
    RunSequenceAllocator,
    RunSequenceSeedSource,
    SequenceAllocation,
)
from .types import SequencedEvent, StreamableGraph, classify_tool_kind

__all__ = [
    "NODE_METADATA_FIELDS",
    "AllocationSink",
    "EventAggregator",
    "RunSequenceAllocator",
    "RunSequenceSeedSource",
    "SequenceAllocation",
    "SequencedEvent",
    "StreamableGraph",
    "classify_tool_kind",
    "emit_custom_node_write",
    "node_metadata_fields",
    "node_metadata_from_graph",
]
