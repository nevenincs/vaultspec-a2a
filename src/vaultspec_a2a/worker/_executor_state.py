"""Mutable state groups owned by the worker executor."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..streaming.aggregator import EventAggregator
from .catalog_store import RunCatalogStore
from .token_store import RunTokenStore

if TYPE_CHECKING:
    from ._dispatch_contract import DispatchCapacityReservation


@dataclass(slots=True)
class DispatchCapacityState:
    """Mutable admission, cancellation, and reservation state for one worker."""

    active_ingests: dict[str, DispatchCapacityReservation] = field(default_factory=dict)
    pending_cancellations: dict[str, str] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_generation: int = 0
    reservation: ContextVar[DispatchCapacityReservation | None] = field(
        default_factory=lambda: ContextVar(
            "dispatch_capacity_reservation", default=None
        )
    )


@dataclass(slots=True)
class RunResources:
    """Worker-scoped event and provider state shared with graph execution."""

    aggregator: EventAggregator = field(default_factory=EventAggregator)
    token_store: RunTokenStore = field(default_factory=RunTokenStore)
    catalog_store: RunCatalogStore = field(default_factory=RunCatalogStore)
