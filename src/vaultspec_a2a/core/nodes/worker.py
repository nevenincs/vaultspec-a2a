"""Backwards-compatibility shim — delegates to graph.nodes.worker.

New code should import from ``vaultspec_a2a.graph.nodes.worker`` directly.
"""

from vaultspec_a2a.graph.nodes.worker import WorkerNode as WorkerNode
from vaultspec_a2a.graph.nodes.worker import (
    _build_worker_messages as _build_worker_messages,
)
from vaultspec_a2a.graph.nodes.worker import (
    _finalize_worker_response as _finalize_worker_response,
)
from vaultspec_a2a.graph.nodes.worker import _first_option_id as _first_option_id
from vaultspec_a2a.graph.nodes.worker import (
    _interrupt_permission_callback as _interrupt_permission_callback,
)
from vaultspec_a2a.graph.nodes.worker import (
    _resolve_effective_worker_model as _resolve_effective_worker_model,
)
from vaultspec_a2a.graph.nodes.worker import (
    _validate_option_id as _validate_option_id,
)
from vaultspec_a2a.graph.nodes.worker import (
    _wrap_worker_exception as _wrap_worker_exception,
)
from vaultspec_a2a.graph.nodes.worker import create_worker_node as create_worker_node

__all__ = ["create_worker_node"]
