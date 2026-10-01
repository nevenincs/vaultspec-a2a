"""Reading a thread's stored checkpoint history, for the retention suites.

Retention is asserted the same way wherever it is asserted: by the checkpoint
ids a thread has per namespace, before and after. Both suites read that the
same way through the saver's own listing, so the read lives here once rather
than as a copy in each.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..checkpoints import Checkpointer

__all__ = ["config_for", "stored_history"]


def config_for(thread_id: str) -> dict[str, Any]:
    """The runnable config addressing *thread_id*'s checkpoints."""
    return {"configurable": {"thread_id": thread_id}}


async def stored_history(saver: Checkpointer, thread_id: str) -> dict[str, list[str]]:
    """The checkpoint ids *saver* holds for *thread_id*, keyed by namespace."""
    by_namespace: dict[str, list[str]] = defaultdict(list)
    async for item in saver.alist(cast("Any", config_for(thread_id))):
        configurable = cast("Mapping[str, Mapping[str, str]]", item.config)[
            "configurable"
        ]
        by_namespace[configurable["checkpoint_ns"]].append(
            configurable["checkpoint_id"]
        )
    return dict(by_namespace)
