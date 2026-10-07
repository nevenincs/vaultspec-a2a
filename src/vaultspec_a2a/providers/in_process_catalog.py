"""Static catalog serving for the in-process provider lanes.

An in-process lane has no external transport to interrogate. There is no
subprocess to spawn, no endpoint to enumerate, and no credential to present, so
there is no discovery round trip to perform - and this module deliberately does
not fake one. The catalog it returns is computed, not fetched: the entries are
the lane's own selectors, and the state is marked available because the lane is
held by this process and cannot be absent.

That honesty is the whole reason this module exists separately from the four
external discoverers. Their catalogs answer "what did the provider tell us just
now"; this one answers "what does this process hold", which is a different
question with a different truth condition. Rendering it through a synthetic
round trip would have made a static fact look like an observation.

**The lanes are registrations, not names.** An in-process lane is a
:class:`~.lane_registry.LaneRegistration`: the ones this build compiles in, plus
whatever the configured lane plugins register (:mod:`.lane_registry`). The
admission declaration, the factory and the catalog service all read the lane set
from :func:`in_process_lanes`, so they cannot drift into disagreeing about what
an in-process lane is called, and none of them names a lane it does not hold.

**Serving is armed, never ambient.** These lanes are constrained to stay
hidden, and the reason is a product one: a lane that returns fixed content would
otherwise appear in the composer beside real providers, and a user could select
canned output believing it was work. So the default posture is hidden, and a
deployment that wants these lanes must say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ..graph.enums import Provider
from ._catalog_discovery import ProviderCatalogDiscovery, available_catalog
from ._catalog_fields import local_id, model_list_revision
from .execution_modes import EXTERNAL_EXECUTION_MODES
from .lane_registry import LaneRegistration, registered_lanes
from .provider_catalog import (
    AuthenticationState,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from datetime import datetime

    from langchain_core.language_models import BaseChatModel

    from ..team.team_config import AgentConfig

__all__ = [
    "BUILT_IN_LANES",
    "build_in_process_catalog",
    "discover_in_process_catalog",
    "in_process_catalog_key",
    "in_process_lane",
    "in_process_lanes",
    "served_in_process_lanes",
]


@dataclass(frozen=True, slots=True)
class _MockLane:
    """The tape-replay lane this build compiles in."""

    provider: Provider = Provider.MOCK
    execution_mode: str = "in-process-mock"
    display_name: str = "Mock (in-process tape replay)"
    description: str = (
        "In-process mock provider; replays recorded tapes from the configured "
        "tape server with no live model spend."
    )
    model_values: tuple[str, ...] = ("mock-high", "mock-low", "mock-max", "mock-mid")

    def create_model(self, agent_config: AgentConfig | None) -> BaseChatModel:
        from .mock_chat_model import MockChatModel

        return MockChatModel(agent_config=agent_config)


_MOCK_LANE: Final = _MockLane()

#: The in-process lanes this build holds without any plugin. They are executable
#: whatever the arming; serving them is still armed by the deployment.
BUILT_IN_LANES: Final[tuple[LaneRegistration, ...]] = (_MOCK_LANE,)

_BUILT_IN_PROVIDERS: Final = frozenset(lane.provider for lane in BUILT_IN_LANES)


def in_process_lanes() -> tuple[LaneRegistration, ...]:
    """Return every in-process lane this process can execute, plugin lanes first.

    Raises:
        LanePluginError: If the configured lane plugins cannot be honoured.
    """
    return (*registered_lanes(reserved=_BUILT_IN_PROVIDERS), *BUILT_IN_LANES)


def in_process_lane(provider: Provider) -> LaneRegistration | None:
    """Return the in-process lane *provider* names, or ``None`` when it has none.

    An external provider is answered without resolving the lane set: no
    registration may claim one, so it can never be in-process.
    """
    if provider in EXTERNAL_EXECUTION_MODES:
        return None
    return next(
        (lane for lane in in_process_lanes() if lane.provider is provider), None
    )


def in_process_catalog_key(lane: LaneRegistration) -> ProviderCatalogKey:
    """Return the catalog identity *lane* is served under."""
    return ProviderCatalogKey(lane.provider.value, lane.execution_mode)


def served_in_process_lanes(
    *, armed: bool, mock_api_base: str | None
) -> tuple[ProviderCatalogKey, ...]:
    """Return the in-process lanes this deployment serves, in registry order.

    Unarmed serves nothing at all. Armed serves every plugin lane, which runs
    entirely inside this process and therefore cannot be unavailable. The mock
    lane additionally requires a configured tape server: it proxies one over
    HTTP, so serving it without a base URL would advertise a transport that does
    not exist, and a certification run that froze it would fail at its first
    turn rather than never having been offered the lane.
    """
    if not armed:
        return ()
    lanes = [
        in_process_catalog_key(lane)
        for lane in registered_lanes(reserved=_BUILT_IN_PROVIDERS)
    ]
    if mock_api_base and mock_api_base.strip():
        lanes.append(in_process_catalog_key(_MOCK_LANE))
    return tuple(lanes)


def _entry_id(key: ProviderCatalogKey, provider_value: str) -> str:
    return local_id(f"{key.provider_id}:{key.execution_mode}:model", provider_value)


def build_in_process_catalog(
    lane: LaneRegistration, *, checked_at: datetime | None = None
) -> ProviderCatalog:
    """Compute the static catalog for one in-process lane.

    The entries are exactly the selectors the lane implements and serves. They
    intentionally carry no capability mapping and no default.
    """
    key = in_process_catalog_key(lane)
    models = tuple(
        ModelCatalogEntry(
            entry_id=_entry_id(key, provider_value),
            provider_value=provider_value,
            display_name=provider_value,
            description=lane.description,
        )
        for provider_value in lane.model_values
    )
    return available_catalog(
        key,
        revision=model_list_revision(key, models),
        models=models,
        checked_at=checked_at,
    )


def _lane_for_key(key: ProviderCatalogKey) -> LaneRegistration:
    """Resolve the in-process lane *key* names, exactly.

    A provider matched under a foreign execution mode is refused here rather than
    served: catalog identity is the pair, and an in-process lane is only
    in-process under the mode it declares.

    Raises:
        ValueError: If *key* is not a held in-process lane identity.
    """
    for lane in in_process_lanes():
        if in_process_catalog_key(lane) == key:
            return lane
    raise ValueError("catalog key does not name an in-process provider lane")


def discover_in_process_catalog(key: ProviderCatalogKey) -> ProviderCatalogDiscovery:
    """Return the in-process lane's catalog without performing any round trip.

    Synchronous on purpose. The external discoverers are coroutines because they
    await a subprocess or a socket; this one computes, and wrapping it in an
    ``async def`` would suggest an I/O boundary that is not there. The factory
    adapts it to the registration's awaitable contract.

    ``authentication`` is always :data:`AuthenticationState.NOT_APPLICABLE`:
    there is no credential to hold and none to be missing, which is a different
    fact from ``UNKNOWN``.

    Raises:
        ValueError: If *key* does not name a held in-process lane identity.
    """
    return ProviderCatalogDiscovery(
        catalog=build_in_process_catalog(_lane_for_key(key)),
        authentication=AuthenticationState.NOT_APPLICABLE,
    )
