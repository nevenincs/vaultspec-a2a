"""Static catalog serving for the in-process provider lanes.

An in-process lane has no external transport to interrogate. There is no
subprocess to spawn, no endpoint to enumerate, and no credential to present, so
there is no discovery round trip to perform - and this module deliberately does
not fake one. The catalog it returns is computed, not fetched: the entries are
the in-process provider's own selectors, and the state is marked available
because the provider is compiled into this process and cannot be absent.

That honesty is the whole reason this module exists separately from the four
external discoverers. Their catalogs answer "what did the provider tell us just
now"; this one answers "what does this build contain", which is a different
question with a different truth condition. Rendering it through a synthetic
round trip would have made a static fact look like an observation.

**Serving is armed, never ambient.** ``2026-08-02-provider-model-catalog-adr``
constrains internal deterministic test lanes to stay hidden, and the reason is a
product one: a lane that returns fixed content would otherwise appear in the
composer beside real providers, and a user could select canned output believing
it was work. So the default posture is hidden, and a deployment that wants these
lanes must say so - the certification stack does, because a run that must never
spend has nowhere else to go now that run start requires a served selection.

The execution modes declared here are the single source for that identity. The
admission declaration reads them to name the exact lanes it admits, and the
factory reads them to validate a frozen mode at construction, so the three sites
cannot drift into disagreeing about what an in-process lane is called.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from ..graph.enums import MODEL_MAP, Provider
from ._catalog_fields import local_id, model_list_revision
from .provider_catalog import (
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "IN_PROCESS_EXECUTION_MODES",
    "SERVE_IN_PROCESS_LANES_ENV",
    "InProcessCatalogDiscovery",
    "build_in_process_catalog",
    "discover_in_process_catalog",
    "in_process_catalog_key",
    "in_process_lane_serving_armed",
    "served_in_process_lanes",
]

# The environment declaration that arms in-process serving. Absent or falsey
# means hidden, which is the ADR's default posture; only a deployment that
# deliberately sets it sees these lanes.
SERVE_IN_PROCESS_LANES_ENV: Final = "VAULTSPEC_SERVE_IN_PROCESS_LANES"

_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})

# The catalog TTL matches the external lanes'. A static catalog cannot go stale
# in the sense a fetched one can, but selection revalidation requires a bounded
# expiry, and a lane whose entries never expire would be the only one in the
# service exempt from that rule.
_CATALOG_TTL: Final = timedelta(minutes=5)

# The exact execution mode each in-process lane is served under. Catalog identity
# is execution-mode specific by decision, so these strings are lane identity, not
# labels: changing one renames the lane everywhere it is admitted, frozen, and
# replayed.
IN_PROCESS_EXECUTION_MODES: Mapping[Provider, str] = MappingProxyType(
    {
        Provider.DETERMINISTIC: "in-process-deterministic",
        Provider.MOCK: "in-process-mock",
    }
)

_DESCRIPTIONS: Mapping[Provider, str] = MappingProxyType(
    {
        Provider.DETERMINISTIC: (
            "In-process deterministic provider; returns fixed role-keyed content "
            "with no external service and no spend."
        ),
        Provider.MOCK: (
            "In-process mock provider; replays recorded tapes from the configured "
            "tape server with no live model spend."
        ),
    }
)


@dataclass(frozen=True, slots=True)
class InProcessCatalogDiscovery:
    """One in-process catalog and its authentication evidence.

    Mirrors the external discoverers' result shape so the factory normalizes every
    lane through one boundary. ``authentication`` is always
    :data:`AuthenticationState.NOT_APPLICABLE`: there is no credential to hold and
    none to be missing, which is a different fact from ``UNKNOWN``.
    """

    catalog: ProviderCatalog
    authentication: AuthenticationState


def in_process_catalog_key(provider: Provider) -> ProviderCatalogKey:
    """Return the catalog identity *provider* is served under.

    Raises:
        ValueError: If *provider* is not an in-process lane.
    """
    execution_mode = IN_PROCESS_EXECUTION_MODES.get(provider)
    if execution_mode is None:
        raise ValueError(f"provider {provider.value} is not an in-process lane")
    return ProviderCatalogKey(provider.value, execution_mode)


def in_process_lane_serving_armed(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether this deployment has armed in-process lane serving.

    *environ* is explicit so the arming policy is callable without mutating the
    process environment; it defaults to the real one at the composition seam.
    """
    source = os.environ if environ is None else environ
    return source.get(SERVE_IN_PROCESS_LANES_ENV, "").strip().casefold() in _TRUE_VALUES


def served_in_process_lanes(
    *, armed: bool, mock_api_base: str | None
) -> tuple[ProviderCatalogKey, ...]:
    """Return the in-process lanes this deployment serves, in registry order.

    Unarmed serves nothing at all. Armed always serves the deterministic lane,
    which runs entirely inside this process and therefore cannot be unavailable.
    The mock lane additionally requires a configured tape server: it proxies one
    over HTTP, so serving it without a base URL would advertise a transport that
    does not exist, and a certification run that froze it would fail at its first
    turn rather than never having been offered the lane.
    """
    if not armed:
        return ()
    lanes = [in_process_catalog_key(Provider.DETERMINISTIC)]
    if mock_api_base and mock_api_base.strip():
        lanes.append(in_process_catalog_key(Provider.MOCK))
    return tuple(lanes)


def _entry_id(key: ProviderCatalogKey, provider_value: str) -> str:
    return local_id(f"{key.provider_id}:{key.execution_mode}:model", provider_value)


def _provider_values(provider: Provider) -> tuple[str, ...]:
    """Return the lane's distinct selectors, sorted.

    Read from the shared capability map rather than restated here: the model
    names an in-process provider answers to are already declared there, and a
    second copy would be a registry that can disagree with the executor. The
    deterministic lane maps every capability level to one inert selector, so it
    collapses to a single entry; the mock lane keeps its four distinct tape keys.
    """
    return tuple(sorted(set(MODEL_MAP[provider].values())))


def build_in_process_catalog(
    key: ProviderCatalogKey, *, checked_at: datetime | None = None
) -> ProviderCatalog:
    """Compute the static catalog for one in-process lane.

    Raises:
        ValueError: If *key* does not name a served in-process lane identity.
    """
    provider = _in_process_provider(key)
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    description = _DESCRIPTIONS[provider]
    models = tuple(
        ModelCatalogEntry(
            entry_id=_entry_id(key, provider_value),
            provider_value=provider_value,
            display_name=provider_value,
            description=description,
        )
        for provider_value in _provider_values(provider)
    )
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision=model_list_revision(key, models),
            expires_at=now + _CATALOG_TTL,
        ),
        models=models,
    )


def _in_process_provider(key: ProviderCatalogKey) -> Provider:
    """Resolve the in-process provider *key* names, exactly.

    A provider matched under a foreign execution mode is refused here rather than
    served: catalog identity is the pair, and an in-process provider is only
    in-process under the mode this module declares for it.

    Raises:
        ValueError: If *key* is not a declared in-process lane identity.
    """
    try:
        provider = Provider(key.provider_id)
    except ValueError:
        raise ValueError(
            "catalog key does not name an in-process provider lane"
        ) from None
    if IN_PROCESS_EXECUTION_MODES.get(provider) != key.execution_mode:
        raise ValueError("catalog key does not name an in-process provider lane")
    return provider


def discover_in_process_catalog(key: ProviderCatalogKey) -> InProcessCatalogDiscovery:
    """Return the in-process lane's catalog without performing any round trip.

    Synchronous on purpose. The external discoverers are coroutines because they
    await a subprocess or a socket; this one computes, and wrapping it in an
    ``async def`` would suggest an I/O boundary that is not there. The factory
    adapts it to the registration's awaitable contract.

    Raises:
        ValueError: If *key* does not name a served in-process lane identity.
    """
    return InProcessCatalogDiscovery(
        catalog=build_in_process_catalog(key),
        authentication=AuthenticationState.NOT_APPLICABLE,
    )
