"""Backwards-compatibility shim — delegates to graph.nodes.supervisor.

New code should import from ``vaultspec_a2a.graph.nodes.supervisor`` directly.
"""

from vaultspec_a2a.graph.nodes.supervisor import (
    _build_supervisor_messages as _build_supervisor_messages,
)
from vaultspec_a2a.graph.nodes.supervisor import (
    _evaluate_supervisor_response as _evaluate_supervisor_response,
)
from vaultspec_a2a.graph.nodes.supervisor import (
    create_supervisor_node as create_supervisor_node,
)

__all__ = ["create_supervisor_node"]
