"""The single definition of a graph node's team-status metadata fields.

Four sites read the same five fields off a compiled graph node's ``metadata``
mapping and flatten them to strings: the worker's ``graph_registered`` payload
builder, this package's subscriber cache, the relayed-payload sync that
rebuilds that cache on the control surface, and the team-status emitter that
defaults them into an agent summary. They agreed field-for-field only by
repetition, so a field added to one would have silently gone missing from the
others - the direct-vs-relayed split is exactly where that drift hides.

Home rationale: three of the four readers live in this package, and the fourth
(``vaultspec_a2a.worker.graph_lifecycle``) already imports from
``vaultspec_a2a.streaming``, so this adds no dependency edge. Nothing here
imports ``worker``, so the direction stays one-way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "NODE_METADATA_FIELDS",
    "node_metadata_fields",
    "node_metadata_from_graph",
]

NODE_METADATA_FIELDS = (
    "role",
    "display_name",
    "description",
    "provider",
    "model",
)
"""The team-status fields carried per graph node, in wire order.

Adding a field here reaches every reader at once — which is the whole point of
this module having one home.
"""


def node_metadata_fields(meta: Mapping[str, Any]) -> dict[str, str]:
    """Flatten one node's metadata to the team-status fields, as strings.

    A missing key yields ``""`` rather than being omitted, so every node
    summary carries the same shape and no consumer has to guard a key.
    """
    return {field: str(meta.get(field, "")) for field in NODE_METADATA_FIELDS}


def node_metadata_from_graph(graph: Any) -> dict[str, dict[str, str]]:
    """Extract per-node team-status metadata from a compiled graph.

    Nodes carrying no metadata are skipped entirely: an all-empty summary tells
    a consumer nothing and would pad the team-status payload with the graph's
    structural nodes. Tolerates a graph without a ``nodes`` mapping so a caller
    holding a partially-built or foreign graph object degrades to an empty
    result rather than raising.
    """
    extracted: dict[str, dict[str, str]] = {}
    for node_name, node_spec in getattr(graph, "nodes", {}).items():
        meta = getattr(node_spec, "metadata", None) or {}
        if meta:
            extracted[node_name] = node_metadata_fields(meta)
    return extracted
