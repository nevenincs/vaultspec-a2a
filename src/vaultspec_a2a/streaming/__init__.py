"""Provide ordered runtime event streaming.

A run's event stream has two halves, one per process.
:class:`vaultspec_a2a.streaming.aggregator.RunEventProducer` is the worker's:
it ingests a graph run, buffers and emits its domain events, and hands each to
the relay hooks. :class:`vaultspec_a2a.streaming.subscribers.RelayHub` is the
gateway's: it projects and numbers every relayed payload, fans it out to the
run's subscribers, and keeps the
:class:`vaultspec_a2a.streaming._run_state.RunLiveStateMirror` the read surfaces
serve live agent, tool-call and node state from. Both record that state through
one set of mutations. :mod:`vaultspec_a2a.streaming.types` defines the
streamable graph protocol and tool-kind classification.

Events enter from :mod:`vaultspec_a2a.graph.events`. Workers publish through
:mod:`vaultspec_a2a.worker`. Server-Sent Events consumers live in
:mod:`vaultspec_a2a.api`.
"""

from ._interrupt_projection import emit_interrupt_events
from ._run_state import RunLiveStateMirror
from .aggregator import RunEventProducer
from .ingest import INGEST_DRAINED, GraphInvocation, IngestRequest
from .node_metadata import (
    NODE_METADATA_FIELDS,
    node_metadata_fields,
    node_metadata_from_graph,
)
from .run_event_writer import FrameProjector, RunEventWriter
from .sse_frames import catalog_json_schema
from .subscribers import (
    AllocationSink,
    HeldFrame,
    RelayHub,
    RunSequenceAllocator,
    RunSequenceSeedSource,
    SequenceAllocation,
)
from .types import SequencedEvent, StreamableGraph, classify_tool_kind

__all__ = [
    "INGEST_DRAINED",
    "NODE_METADATA_FIELDS",
    "AllocationSink",
    "FrameProjector",
    "GraphInvocation",
    "HeldFrame",
    "IngestRequest",
    "RelayHub",
    "RunEventProducer",
    "RunEventWriter",
    "RunLiveStateMirror",
    "RunSequenceAllocator",
    "RunSequenceSeedSource",
    "SequenceAllocation",
    "SequencedEvent",
    "StreamableGraph",
    "catalog_json_schema",
    "classify_tool_kind",
    "emit_interrupt_events",
    "node_metadata_fields",
    "node_metadata_from_graph",
]
