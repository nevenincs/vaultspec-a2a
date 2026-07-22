"""Workspace-wide concurrency primitives.

Holds the process-global mutex that serializes repository-wide operations so
concurrent writers never race on the same working tree. The lock lives here,
apart from any one writer, because more than one subsystem must share it: the
Git manager's destructive repo operations and the ACP RPC handler's authoring
writes both acquire it, and neither owns the other. Keeping it in a dedicated
module lets the ACP write path depend on the shared lock without depending on
the Git manager, so the Git manager can be removed without stranding the lock.
"""

import asyncio

__all__ = ["git_workspace_mutex"]

# Process-global mutex serializing repository-wide operations across every
# subsystem that writes the working tree. ``asyncio.Lock()`` at module level is
# safe in Python 3.10+ (PEP 641; the deprecation warning was removed before
# Python 3.13). There is no cross-loop risk: the orchestrator runs a single
# process uvicorn event loop.
git_workspace_mutex = asyncio.Lock()
