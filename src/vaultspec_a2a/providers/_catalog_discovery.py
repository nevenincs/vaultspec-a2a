"""The result every catalog lane returns, and how a spawned lane's discovery ends.

Every lane answers the same question - which catalog, and what evidence about
authentication - so every lane returns :class:`ProviderCatalogDiscovery`, the
type the factory's registrations carry. The factory adds only the health
evidence it observes itself.

The catalog states are built here too. An enumerated catalog carries no expiry
of its own: the refresh cache stamps every stored catalog with the service TTL,
so a lane-side expiry could only restate that TTL or quietly disagree with it.

The subprocess lanes - ACP, Codex and Kimi - each end discovery the same way:
release every resource independently, then return the outcome or raise.
:func:`finish_discovery` is that ending once. The cleanup steps stay the
caller's, because which pipes a lane drains is the shape of that lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ._cleanup import run_independent_cleanups
from .provider_catalog import (
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    HealthState,
    ProviderCatalog,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ._cleanup import CleanupStep
    from .provider_catalog import (
        ModelCatalogEntry,
        NativeControl,
        ProviderCatalogKey,
    )

__all__ = [
    "ProviderCatalogDiscovery",
    "available_catalog",
    "finish_discovery",
    "unavailable_catalog",
    "unavailable_discovery",
]


@dataclass(frozen=True, slots=True)
class ProviderCatalogDiscovery:
    """One lane's catalog and the health evidence its discovery observed.

    ``configured`` and ``transport`` default to unknown because most lanes
    observe only the catalog and its authentication; the factory supplies the
    evidence it holds at the registration boundary.
    """

    catalog: ProviderCatalog
    authentication: AuthenticationState
    configured: HealthState = HealthState.UNKNOWN
    transport: HealthState = HealthState.UNKNOWN


def _checked(checked_at: datetime | None) -> datetime:
    return (checked_at or datetime.now(UTC)).astimezone(UTC)


def available_catalog(
    key: ProviderCatalogKey,
    *,
    revision: str,
    models: tuple[ModelCatalogEntry, ...],
    native_controls: tuple[NativeControl, ...] = (),
    checked_at: datetime | None = None,
) -> ProviderCatalog:
    """Return *key*'s enumerated catalog under *revision*."""
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=_checked(checked_at),
            revision=revision,
        ),
        models=models,
        native_controls=native_controls,
    )


def unavailable_catalog(
    key: ProviderCatalogKey, *, reason: str, checked_at: datetime | None = None
) -> ProviderCatalog:
    """Return *key*'s catalog as unavailable for *reason*, advertising nothing."""
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.UNAVAILABLE,
            checked_at=_checked(checked_at),
            reason=reason,
        ),
        models=(),
    )


def unavailable_discovery(
    key: ProviderCatalogKey,
    *,
    reason: str,
    authentication: AuthenticationState = AuthenticationState.UNKNOWN,
    configured: HealthState = HealthState.UNKNOWN,
    transport: HealthState = HealthState.UNKNOWN,
) -> ProviderCatalogDiscovery:
    """Return a discovery that enumerated nothing, with the evidence it did see."""
    return ProviderCatalogDiscovery(
        catalog=unavailable_catalog(key, reason=reason),
        authentication=authentication,
        configured=configured,
        transport=transport,
    )


async def finish_discovery(
    lane: str,
    outcome: ProviderCatalogDiscovery | None,
    failure: BaseException | None,
    cleanups: Iterable[CleanupStep],
    protocol_error_type: type[Exception],
) -> ProviderCatalogDiscovery:
    """Release every discovery resource, then return *outcome* or raise.

    Every cleanup runs even when discovery failed, because a failure that skips
    the reap leaks the provider's process tree. A cleanup that failed with the
    lane's own *protocol_error_type* outranks *failure*: that is a drain that
    refused the shared output budget and reaped the child, and the read failure
    that followed is its symptom rather than its cause.
    """
    cleanup_failures = await run_independent_cleanups(*cleanups)
    failed_steps = ", ".join(name for name, _ in cleanup_failures)
    if failure is not None:
        refusal = next(
            (
                exc
                for _, exc in cleanup_failures
                if isinstance(exc, protocol_error_type)
            ),
            None,
        )
        if refusal is not None:
            refusal.add_note(
                f"{lane} discovery also failed with {type(failure).__name__}"
            )
            raise refusal
        if cleanup_failures:
            failure.add_note(f"{lane} catalog cleanup also failed: {failed_steps}")
        raise failure
    if cleanup_failures:
        raise RuntimeError(f"{lane} catalog cleanup failed: {failed_steps}")
    if outcome is None:
        raise RuntimeError(f"{lane} catalog discovery completed without an outcome")
    return outcome
