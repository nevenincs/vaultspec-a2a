"""In-memory registry of one value per run, held for the run's active window.

The owner registers a value when a run's dispatch begins and drops it when that
window ends, so an entry never outlives an active worker turn and is never
checkpointed. The ``repr`` reports only the active-run count, so a registry
that holds secret material never widens a log line, and a subclass inherits that
guarantee under its own name.

The worker process runs a single asyncio event loop, so the plain-dict backing
needs no lock: register/drop happen at await boundaries and each dict operation
is atomic between them.
"""

from __future__ import annotations

from typing import override

__all__ = ["RunScopedRegistry"]


class RunScopedRegistry[T]:
    """In-memory, per-thread holder of one value for each active run."""

    def __init__(self) -> None:
        self._entries: dict[str, T] = {}

    def register(self, thread_id: str, value: T | None) -> None:
        """Hold *value* for *thread_id*'s active window.

        A ``None`` value registers nothing, so a caller whose value has not
        resolved leaves the registry untouched rather than holding a shell that
        a later reader would mistake for a resolved one.
        """
        if value is None:
            return
        self._entries[thread_id] = value

    def get(self, thread_id: str) -> T | None:
        """Return the value held for *thread_id*, or ``None`` if unheld."""
        return self._entries.get(thread_id)

    def drop(self, thread_id: str) -> None:
        """Drop *thread_id*'s value at run end. Idempotent."""
        self._entries.pop(thread_id, None)

    @override
    def __repr__(self) -> str:
        """Redacted representation: reports only the active-run count."""
        return f"{type(self).__name__}(active_runs={len(self._entries)})"

    __str__ = __repr__
