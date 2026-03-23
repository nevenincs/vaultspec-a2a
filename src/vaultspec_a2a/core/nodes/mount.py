"""Backwards-compatibility shim — delegates to graph.nodes.vault_reader.

New code should import from ``vaultspec_a2a.graph.nodes.vault_reader`` directly.
"""

from vaultspec_a2a.graph.nodes.vault_reader import (
    create_mount_node as create_mount_node,
)

__all__ = ["create_mount_node"]
