"""Per-run construction of the authoring-bridge tool binding for a worker.

This is the production construction site the S18/S19 bridge mechanism was missing:
S19 wired the binding into the worker/session but left no code that BUILDS one, so
a real run never armed the bridge. The provider closes that gap for CLI-coder
presets that opt in via ``[team.harness] authoring_bridge = true``.

For a given ``(thread_id, agent_id)`` it assembles a stdio-transport
:class:`~vaultspec_a2a.providers._acp_authoring.AuthoringToolBinding` from three
run-scoped inputs: the machine bearer and the role's actor token from the
:class:`RunTokenStore`, and the engine's agent-tool catalog snapshot fetched once
per run and cached in the :class:`RunCatalogStore`. The engine origin is resolved
fail-closed at graph-compile time (the caller passes ``engine_base_url``), so the
provider never starts a run against an unreachable engine; a bearer rotation
mid-run is tolerated by the client's ``bearer_resolver`` re-resolve, matching the
submitter precedent.

Token hygiene (R7): the bearer and actor token live only in the returned binding
(which redacts them from ``repr`` and is never checkpointed) and in the
``RunTokenStore`` the executor drops at run end. The provider holds no token state
of its own.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..providers._acp_authoring import AuthoringToolBinding
    from .catalog_store import RunCatalogStore
    from .token_store import RunTokenStore

__all__ = ["AuthoringBindingProvider"]


class AuthoringBindingProvider:
    """Builds a worker's per-run authoring binding, or ``None`` when unarmed."""

    def __init__(
        self,
        *,
        engine_base_url: str,
        token_store: RunTokenStore,
        catalog_store: RunCatalogStore,
    ) -> None:
        self._engine_base_url = engine_base_url
        self._token_store = token_store
        self._catalog_store = catalog_store
        # Per-thread fetch locks so concurrent workers under a star fan-out do not
        # each fetch the catalog on a check-then-act race; the first fetches and
        # caches, the rest await and read the cache.
        self._fetch_locks: dict[str, asyncio.Lock] = {}

    async def binding_for(
        self, thread_id: str, agent_id: str
    ) -> AuthoringToolBinding | None:
        """Return the run's authoring binding for *agent_id*, or ``None``.

        Returns ``None`` when the run holds no token coverage for this role — the
        worker then advertises no bridge, which is the correct posture for a run
        that was never armed (the armed path guarantees coverage via the run-start
        eligibility policy). When coverage is present, the engine catalog is
        fetched once per run (cached in the :class:`RunCatalogStore`) and reused
        for every subsequent role in the same run.
        """
        bearer = self._token_store.engine_bearer(thread_id)
        actor_token = self._token_store.actor_token(thread_id, agent_id)
        if not bearer or not actor_token:
            return None

        snapshot = self._catalog_store.get(thread_id)
        if snapshot is None:
            # Double-checked under a per-thread lock: the first concurrent worker
            # fetches and caches; the rest re-read the cache after awaiting it.
            lock = self._fetch_locks.setdefault(thread_id, asyncio.Lock())
            async with lock:
                snapshot = self._catalog_store.get(thread_id)
                if snapshot is None:
                    snapshot = await self._fetch_catalog(bearer, actor_token)
                    self._catalog_store.register(thread_id, snapshot)
            # Once cached, the lock is spent for this run; drop it so the map does
            # not accumulate one entry per thread over a long-lived worker. Waiters
            # already hold their own reference and complete on the cached read.
            self._fetch_locks.pop(thread_id, None)

        from ..providers._acp_authoring import AuthoringToolBinding

        return AuthoringToolBinding(
            snapshot=snapshot,
            bearer_token=bearer,
            actor_token=actor_token,
            engine_base_url=self._engine_base_url,
            run_id=thread_id,
        )

    async def _fetch_catalog(self, bearer: str, actor_token: str):
        """Fetch the engine agent-tool catalog under the run's credentials."""
        from ..authoring import AuthoringClient
        from ..authoring.catalog import fetch_catalog
        from ..authoring.discovery import resolve_engine

        async with AuthoringClient(
            self._engine_base_url,
            bearer,
            actor_token=actor_token,
            bearer_resolver=resolve_engine,
        ) as client:
            return await fetch_catalog(client)

    def __repr__(self) -> str:
        """Redacted representation — reports only the engine origin."""
        return f"AuthoringBindingProvider(engine_base_url={self._engine_base_url!r})"
