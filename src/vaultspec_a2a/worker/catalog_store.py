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
tiers), so this store is not a token-hygiene surface.
"""

from __future__ import annotations

from ..authoring import CatalogSnapshot
from ._run_registry import RunScopedRegistry

__all__ = ["RunCatalogStore"]


class RunCatalogStore(RunScopedRegistry[CatalogSnapshot]):
    """In-memory, per-thread holder of engine catalog snapshots for active runs."""
