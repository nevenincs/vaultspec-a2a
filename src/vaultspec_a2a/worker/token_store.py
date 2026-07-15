"""Worker-scoped registry of per-run actor token bundles (ADR R7).

A run's engine-provisioned :class:`~vaultspec_a2a.thread.actor_tokens.ActorTokenBundle`
reaches the worker process on the dispatch payload. This store holds it in memory
only, keyed by thread id, for the active window of a dispatch: the executor
registers the bundle when a run's ingest/resume begins and drops it when that
window ends. Tokens therefore never outlive an active worker turn, are never
checkpointed, and — via the bundle's redacting repr — never reach a log line.

Every read is scoped to a single role (:meth:`actor_token`), so the authoring
bridge for one worker can only ever obtain that worker's own token; a bug in one
role's binding cannot hand another role's principal across (R7: roles never
share). The store is the single injection seam the per-run authoring binding
consumes when it assembles a worker's tool surface.

The worker process runs a single asyncio event loop, so the plain-dict backing
needs no lock: register/drop happen at executor await boundaries and each dict
operation is atomic between them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..thread.actor_tokens import ActorTokenBundle

__all__ = ["RunTokenStore"]


class RunTokenStore:
    """In-memory, per-thread holder of actor token bundles for active runs."""

    def __init__(self) -> None:
        self._bundles: dict[str, ActorTokenBundle] = {}

    def register(self, thread_id: str, bundle: ActorTokenBundle | None) -> None:
        """Hold *bundle* for *thread_id*'s active window.

        A ``None`` or empty bundle registers nothing, so a run started without
        engine tokens leaves the store untouched rather than holding a shell.
        """
        if bundle is None or bundle.is_empty():
            return
        self._bundles[thread_id] = bundle

    def actor_token(self, thread_id: str, role: str) -> str | None:
        """Return *role*'s actor token for *thread_id*, or ``None`` if unheld."""
        bundle = self._bundles.get(thread_id)
        return bundle.actor_token(role) if bundle is not None else None

    def engine_bearer(self, thread_id: str) -> str | None:
        """Return the machine bearer for *thread_id*, or ``None`` if unheld."""
        bundle = self._bundles.get(thread_id)
        return bundle.engine_bearer if bundle is not None else None

    def has(self, thread_id: str) -> bool:
        """Return ``True`` while a bundle is held for *thread_id*."""
        return thread_id in self._bundles

    def active_run_count(self) -> int:
        """Number of runs currently holding a bundle (for diagnostics/tests)."""
        return len(self._bundles)

    def drop(self, thread_id: str) -> None:
        """Drop *thread_id*'s bundle at run end. Idempotent."""
        self._bundles.pop(thread_id, None)

    def __repr__(self) -> str:
        """Redacted representation — reports only the active-run count (R7)."""
        return f"RunTokenStore(active_runs={len(self._bundles)})"

    __str__ = __repr__
