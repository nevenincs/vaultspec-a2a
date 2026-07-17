"""Worker-scoped registry of per-run engine agent-tool catalog snapshots.

The engine owns the agent-tool catalog and versions it with itself; the authoring
bridge needs that catalog to advertise the run's propose/read tools. Fetching it
once per run and caching it here — keyed by thread id — means every worker in the
same run shares one snapshot rather than each re-fetching (the drift window the
stdio bridge's independent re-fetch opens, ``authoring_stdio.py``). The
:class:`~vaultspec_a2a.worker.authoring_binding.AuthoringBindingProvider`
populates the store on the first binding of a run and reads it for every
subsequent worker; the executor drops the entry when the dispatch window ends, so
a snapshot never outlives an active run and is never checkpointed.

The catalog snapshot carries no secret material (tool names, schemas, risk
tiers), so this store is not a token-hygiene surface; its ``repr`` still reports
only the active-run count, mirroring :class:`RunTokenStore` so neither store ever
widens a log line. The worker process runs a single asyncio event loop, so the
plain-dict backing needs no lock: register/drop happen at await boundaries and
each dict operation is atomic between them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..authoring import CatalogSnapshot

__all__ = ["RunCatalogStore"]


class RunCatalogStore:
    """In-memory, per-thread holder of engine catalog snapshots for active runs."""

    def __init__(self) -> None:
        self._snapshots: dict[str, CatalogSnapshot] = {}

    def register(self, thread_id: str, snapshot: CatalogSnapshot | None) -> None:
        """Hold *snapshot* for *thread_id*'s active window.

        A ``None`` snapshot registers nothing, so a run whose catalog fetch has
        not resolved leaves the store untouched rather than caching a shell that a
        later reader would mistake for a completed fetch.
        """
        if snapshot is None:
            return
        self._snapshots[thread_id] = snapshot

    def get(self, thread_id: str) -> CatalogSnapshot | None:
        """Return the cached snapshot for *thread_id*, or ``None`` if unheld."""
        return self._snapshots.get(thread_id)

    def has(self, thread_id: str) -> bool:
        """Return ``True`` while a snapshot is held for *thread_id*."""
        return thread_id in self._snapshots

    def active_run_count(self) -> int:
        """Number of runs currently holding a snapshot (for diagnostics/tests)."""
        return len(self._snapshots)

    def drop(self, thread_id: str) -> None:
        """Drop *thread_id*'s snapshot at run end. Idempotent."""
        self._snapshots.pop(thread_id, None)

    def __repr__(self) -> str:
        """Report only the active-run count (mirrors RunTokenStore's redacting repr)."""
        return f"RunCatalogStore(active_runs={len(self._snapshots)})"

    __str__ = __repr__
