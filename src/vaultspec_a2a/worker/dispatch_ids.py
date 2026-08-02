"""Bounded worker-local admission for stable dispatch identities."""

from __future__ import annotations

from collections import deque

__all__ = ["DEFAULT_DISPATCH_ID_CAPACITY", "DispatchIdAdmission"]

DEFAULT_DISPATCH_ID_CAPACITY = 10_000


class DispatchIdAdmission:
    """Synchronously admit each dispatch ID once within a bounded FIFO window.

    The worker endpoint calls this without an ``await`` between the membership
    check and insertion, making admission indivisible on its event-loop thread.
    State is intentionally process-local and therefore clears on worker restart;
    durable recovery remains the gateway journal's responsibility.
    """

    def __init__(self, capacity: int = DEFAULT_DISPATCH_ID_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._ordered: deque[str] = deque()
        self._ids: set[str] = set()

    def __contains__(self, dispatch_id: str) -> bool:
        return dispatch_id in self._ids

    def admit(self, dispatch_id: str) -> bool:
        """Return true once for an ID, false while that ID remains retained."""
        if not dispatch_id:
            raise ValueError("dispatch_id must not be empty")
        if dispatch_id in self._ids:
            return False
        if len(self._ordered) == self._capacity:
            expired = self._ordered.popleft()
            self._ids.remove(expired)
        self._ordered.append(dispatch_id)
        self._ids.add(dispatch_id)
        return True

    def __len__(self) -> int:
        return len(self._ordered)
