"""Worker-scoped registry of per-run actor token bundles.

A run's engine-provisioned :class:`~vaultspec_a2a.thread.actor_tokens.ActorTokenBundle`
reaches the worker process on the dispatch payload. This store holds it in memory
only, keyed by thread id, for the active window of a dispatch: the executor
registers the bundle when a run's ingest/resume begins and drops it when that
window ends. Tokens therefore never outlive an active worker turn, are never
checkpointed, and — via the bundle's redacting repr — never reach a log line.

The reads the authoring bridge uses are scoped to a single role
(:meth:`actor_token`), so a worker asks only for its own token and a bug in one
role's binding cannot hand another role's principal across. The store is the
single injection seam the per-run authoring binding
consumes when it assembles a worker's tool surface.
"""

from __future__ import annotations

from typing import override

from ..thread import ActorTokenBundle
from ._run_registry import RunScopedRegistry

__all__ = ["RunTokenStore"]


class RunTokenStore(RunScopedRegistry[ActorTokenBundle]):
    """In-memory, per-thread holder of actor token bundles for active runs."""

    @override
    def register(self, thread_id: str, value: ActorTokenBundle | None) -> None:
        """Hold *value* for *thread_id*'s active window.

        A ``None`` or empty bundle registers nothing, so a run started without
        engine tokens leaves the store untouched rather than holding a shell.
        """
        if value is None or value.is_empty():
            return
        super().register(thread_id, value)

    def actor_token(self, thread_id: str, role: str) -> str | None:
        """Return *role*'s actor token for *thread_id*, or ``None`` if unheld."""
        bundle = self.get(thread_id)
        return bundle.actor_token(role) if bundle is not None else None

    def engine_bearer(self, thread_id: str) -> str | None:
        """Return the machine bearer for *thread_id*, or ``None`` if unheld."""
        bundle = self.get(thread_id)
        return bundle.engine_bearer if bundle is not None else None
