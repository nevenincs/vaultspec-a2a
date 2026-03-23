"""Backwards-compatibility shim — delegates to graph.nodes.

New code should import from ``vaultspec_a2a.graph.nodes`` directly.
"""

from vaultspec_a2a.graph.nodes.supervisor import (
    create_supervisor_node as create_supervisor_node,
)
from vaultspec_a2a.graph.nodes.worker import create_worker_node as create_worker_node

__all__ = ["create_supervisor_node", "create_worker_node"]
