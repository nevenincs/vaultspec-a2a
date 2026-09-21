"""Concurrency-safe refresh cache for provider-owned catalogs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from .provider_catalog import (
        CacheFreshness,
        CatalogRefreshSuppressedError,
        ProviderCatalog,
        ProviderCatalogKey,
    )


@dataclass(frozen=True, slots=True)
class CatalogCacheSnapshot:
    """A catalog plus local refresh-cache timing state."""

    catalog: ProviderCatalog
    refreshed_at: datetime
    expires_at: datetime
    freshness: CacheFreshness


@dataclass(frozen=True, slots=True)
class _StoredCatalog:
    catalog: ProviderCatalog
    refreshed_at: datetime
    expires_at: datetime
    deadline: float


@dataclass(frozen=True, slots=True)
class _StoredFailure:
    failure_type: str
    deadline: float


@dataclass(slots=True)
class _CatalogSnapshots:
    entries: dict[ProviderCatalogKey, _StoredCatalog]
    failures: dict[ProviderCatalogKey, _StoredFailure]


@dataclass(slots=True)
class _LaneLock:
    lock: asyncio.Lock
    users: int = 0


class CatalogLoader(Protocol):
    async def __call__(self, key: ProviderCatalogKey, /) -> ProviderCatalog: ...


# How long a lane whose discovery RAISED is left alone before it is attempted
# again. Deliberately far shorter than the success TTL: a failing lane is the
# expensive case (its cost is a subprocess spawn or a network call run to its own
# timeout), so it is the one that most needs a read to be warm, while a lane that
# has come back should be noticed in seconds rather than minutes.
DEFAULT_FAILURE_TTL: Final = timedelta(seconds=30)


class CatalogRefreshCacheBase:
    """Concurrency-safe, per-lane single-flight TTL cache for catalog discovery.

    A lane that SUCCEEDS is cached for ``ttl``. A lane whose loader RAISES is
    cached negatively for ``failure_ttl``: the failure is remembered so the next
    read re-raises immediately instead of re-running discovery. Without that, a
    failing lane is never stored at all and every subsequent read pays its full
    cost - so a "warm" read of a registry containing one failing lane is not warm.

    The two caches are separate on purpose. A negative entry never displaces a
    lane's last good catalog: :meth:`peek` keeps returning that snapshot, which is
    what lets a caller serve a stale-but-real catalog through an outage.
    """

    def __init__(
        self,
        ttl: timedelta,
        *,
        max_lanes: int = 128,
        failure_ttl: timedelta = DEFAULT_FAILURE_TTL,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        if max_lanes <= 0:
            raise ValueError("max_lanes must be positive")
        if failure_ttl < timedelta(0):
            raise ValueError("failure_ttl must not be negative")
        self._ttl = ttl
        self._max_lanes = max_lanes
        self._failure_ttl = failure_ttl
        self._snapshots = _CatalogSnapshots(entries={}, failures={})
        self._locks: dict[ProviderCatalogKey, _LaneLock] = {}
        self._generations: dict[ProviderCatalogKey, int] = {}
        self._index_lock = asyncio.Lock()

    async def _lock_for(self, key: ProviderCatalogKey) -> _LaneLock:
        async with self._index_lock:
            lane = self._locks.setdefault(key, _LaneLock(asyncio.Lock()))
            lane.users += 1
            return lane

    async def _release_lock(self, key: ProviderCatalogKey, lane: _LaneLock) -> None:
        async with self._index_lock:
            lane.users -= 1
            if lane.users == 0 and key not in self._snapshots.entries:
                self._locks.pop(key, None)
                self._generations.pop(key, None)

    def _make_capacity(self, key: ProviderCatalogKey, now: float) -> None:
        if (
            key in self._snapshots.entries
            or len(self._snapshots.entries) < self._max_lanes
        ):
            return
        candidates: list[tuple[float, ProviderCatalogKey]] = []
        for lane_key, entry in self._snapshots.entries.items():
            lane = self._locks.get(lane_key)
            if entry.deadline <= now and (lane is None or lane.users == 0):
                candidates.append((entry.deadline, lane_key))
        if not candidates:
            from .provider_catalog import CatalogCacheCapacityError

            raise CatalogCacheCapacityError(
                "catalog cache capacity reached with no expired inactive lane"
            )
        _, evicted = min(candidates, key=lambda item: item[0])
        self._snapshots.entries.pop(evicted, None)
        self._locks.pop(evicted, None)
        self._generations.pop(evicted, None)

    def _suppression(
        self, key: ProviderCatalogKey, now: float
    ) -> CatalogRefreshSuppressedError | None:
        """Return the error to raise for a lane still inside its failure TTL."""
        failure = self._snapshots.failures.get(key)
        if failure is None:
            return None
        if now >= failure.deadline:
            del self._snapshots.failures[key]
            return None
        from .provider_catalog import CatalogRefreshSuppressedError

        return CatalogRefreshSuppressedError(
            failure.failure_type, failure.deadline - now
        )

    def _record_failure(self, key: ProviderCatalogKey, failure_type: str) -> None:
        """Remember a failed lane, pruning expired records to stay bounded.

        A zero ``failure_ttl`` disables negative caching entirely (every read
        retries), which is why nothing is stored in that case rather than storing
        an entry that is born expired.
        """
        ttl = self._failure_ttl.total_seconds()
        if ttl <= 0:
            return
        now = monotonic()
        for expired in [
            k for k, v in self._snapshots.failures.items() if now >= v.deadline
        ]:
            del self._snapshots.failures[expired]
        if (
            key not in self._snapshots.failures
            and len(self._snapshots.failures) >= self._max_lanes
        ):
            oldest = min(
                self._snapshots.failures.items(), key=lambda item: item[1].deadline
            )[0]
            del self._snapshots.failures[oldest]
        self._snapshots.failures[key] = _StoredFailure(
            failure_type=failure_type, deadline=now + ttl
        )

    @staticmethod
    def _snapshot(entry: _StoredCatalog, now: float) -> CatalogCacheSnapshot:
        from .provider_catalog import CacheFreshness

        freshness = (
            CacheFreshness.FRESH if now < entry.deadline else CacheFreshness.STALE
        )
        return CatalogCacheSnapshot(
            catalog=entry.catalog,
            refreshed_at=entry.refreshed_at,
            expires_at=entry.expires_at,
            freshness=freshness,
        )

    def peek(self, key: ProviderCatalogKey) -> CatalogCacheSnapshot | None:
        """Return the snapshot, including stale data, without refreshing."""
        entry = self._snapshots.entries.get(key)
        return None if entry is None else self._snapshot(entry, monotonic())

    async def _load_catalog(
        self, key: ProviderCatalogKey, loader: CatalogLoader, generation: int
    ) -> ProviderCatalog:
        try:
            catalog = await loader(key)
        except Exception as exc:
            # Invalidation supersedes a failing in-flight refresh.
            if self._generations.get(key, 0) == generation:
                self._record_failure(key, type(exc).__name__)
            raise
        if catalog.key != key:
            raise ValueError("catalog loader returned a different provider lane")
        return catalog

    async def _store_catalog(
        self, key: ProviderCatalogKey, catalog: ProviderCatalog, generation: int
    ) -> CatalogCacheSnapshot:
        from .provider_catalog import CatalogStatus

        refreshed_at = datetime.now(UTC)
        expires_at = refreshed_at + self._ttl
        if catalog.state.expires_at is not None:
            expires_at = min(expires_at, catalog.state.expires_at)
        if catalog.state.status is CatalogStatus.STALE:
            expires_at = refreshed_at
        lifetime = max(0.0, (expires_at - refreshed_at).total_seconds())
        stored = _StoredCatalog(
            catalog=catalog,
            refreshed_at=refreshed_at,
            expires_at=expires_at,
            deadline=monotonic() + lifetime,
        )
        async with self._index_lock:
            if self._generations.get(key, 0) != generation:
                from .provider_catalog import CatalogRefreshInvalidatedError

                raise CatalogRefreshInvalidatedError(
                    "catalog lane was invalidated during refresh"
                )
            self._make_capacity(key, monotonic())
            self._snapshots.entries[key] = stored
            self._snapshots.failures.pop(key, None)
        return self._snapshot(stored, monotonic())

    def _available_snapshot(
        self, key: ProviderCatalogKey, now: float
    ) -> CatalogCacheSnapshot | None:
        current = self._snapshots.entries.get(key)
        if current is not None and now < current.deadline:
            return self._snapshot(current, now)
        suppressed = self._suppression(key, now)
        if suppressed is not None:
            raise suppressed
        return None

    async def get(
        self,
        key: ProviderCatalogKey,
        loader: CatalogLoader,
        *,
        force_refresh: bool = False,
    ) -> CatalogCacheSnapshot:
        """Return a fresh snapshot, coalescing concurrent refreshes per lane."""
        now = monotonic()
        current = self._snapshots.entries.get(key)
        observed = current
        # An explicit refresh is a caller asking to retry now, so it is never
        # suppressed; an ordinary read of a recently-failed lane is.
        if not force_refresh:
            available = self._available_snapshot(key, now)
            if available is not None:
                return available

        lane = await self._lock_for(key)
        try:
            async with lane.lock:
                now = monotonic()
                current = self._snapshots.entries.get(key)
                if force_refresh and current is not None and current is not observed:
                    return self._snapshot(current, now)
                # Re-checked under the lane lock: the whole point of negative
                # caching is that the loser of a single-flight race must not run
                # the discovery the winner just proved is failing.
                if not force_refresh:
                    available = self._available_snapshot(key, now)
                    if available is not None:
                        return available

                generation = self._generations.get(key, 0)
                catalog = await self._load_catalog(key, loader, generation)
                return await self._store_catalog(key, catalog, generation)
        finally:
            await self._release_lock(key, lane)

    def invalidate(self, key: ProviderCatalogKey) -> None:
        """Expire one lane without discarding its visible stale snapshot.

        Also drops any negative entry: invalidation is the explicit request to
        re-attempt a lane, which a retained failure record would silently refuse.
        """
        self._snapshots.failures.pop(key, None)
        if key not in self._snapshots.entries and key not in self._locks:
            return
        self._generations[key] = self._generations.get(key, 0) + 1
        current = self._snapshots.entries.get(key)
        if current is not None:
            self._snapshots.entries[key] = _StoredCatalog(
                catalog=current.catalog,
                refreshed_at=current.refreshed_at,
                expires_at=current.expires_at,
                deadline=float("-inf"),
            )
