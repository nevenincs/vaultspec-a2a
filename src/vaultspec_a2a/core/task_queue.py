"""Backwards-compatibility shim — delegates to graph.tools.task_queue.

New code should import from ``vaultspec_a2a.graph.tools.task_queue`` directly.
"""

from vaultspec_a2a.graph.tools.task_queue import (
    _filter_queue_content as _filter_queue_content,
)
from vaultspec_a2a.graph.tools.task_queue import (
    create_mark_task_complete_tool as create_mark_task_complete_tool,
)

__all__ = ["create_mark_task_complete_tool"]
