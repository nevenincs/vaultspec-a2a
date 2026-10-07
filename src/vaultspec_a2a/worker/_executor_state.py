"""Mutable state groups owned by the worker executor."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langgraph.runtime import RunControl

from ..streaming import RunEventProducer
from ._dispatch_receipts import DispatchReceiptReporter
from ._run_registry import RunScopedRegistry
from .catalog_store import RunCatalogStore
from .token_store import RunTokenStore

if TYPE_CHECKING:
    from ..database import Checkpointer
    from ._dispatch_contract import DispatchCapacityReservation
    from ._dispatch_settlement import TerminalArbitration

__all__ = [
    "CheckpointAccess",
    "DispatchCapacityState",
    "RunControlRegistry",
    "RunResources",
]


@dataclass(slots=True)
class CheckpointAccess:
    """A checkpointer handle paired with the read timeout bound to it.

    Grouped so ``Executor`` threads one collaborator, not two, through to
    every delegate and call site that reads a checkpoint.
    """

    checkpointer: Checkpointer
    read_timeout_seconds: float


@dataclass(slots=True)
class DispatchCapacityState:
    """Mutable admission, cancellation, and reservation state for one worker.

    The per-thread terminal arbitrations belong here with the admission slots
    they bracket: both are keyed by thread, and a thread's arbitration is what
    serializes the settlement that releases its slot.

    A reservation is the one value here held for a run's active window, so
    ``active_ingests`` is a run-scoped registry; its count, membership, key
    snapshot and identity-checked drop are all read and written under ``lock``.
    The other two maps stay plain dicts because neither is held for a run's
    window: a pending cancellation is written by a cancel that may find no run
    at all and is consumed by whichever terminal settles next, and an
    arbitration entry lives while it has waiters, not while a run does.
    """

    active_ingests: RunScopedRegistry[DispatchCapacityReservation] = field(
        default_factory=RunScopedRegistry
    )
    pending_cancellations: dict[str, str] = field(default_factory=dict)
    terminal_arbitrations: dict[str, TerminalArbitration] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_generation: int = 0
    reservation: ContextVar[DispatchCapacityReservation | None] = field(
        default_factory=lambda: ContextVar(
            "dispatch_capacity_reservation", default=None
        )
    )


@dataclass(slots=True)
class RunResources:
    """Worker-scoped event and provider state shared with graph execution.

    All four live for the worker rather than for one run, and all four are
    pruned on the same per-run boundary, so they are held together.
    """

    producer: RunEventProducer = field(default_factory=RunEventProducer)
    token_store: RunTokenStore = field(default_factory=RunTokenStore)
    catalog_store: RunCatalogStore = field(default_factory=RunCatalogStore)
    receipts: DispatchReceiptReporter = field(default_factory=DispatchReceiptReporter)


class RunControlRegistry(RunScopedRegistry[RunControl]):
    """The drain handles of every run executing on one worker.

    A drain is one-way, so the reason is held for the whole remaining life of
    the registry rather than only for the runs that happened to hold a control
    when it was asked for: a run whose control opens afterwards starts drained
    and stops before its first node, and the owner refuses further dispatch.

    Callers use ``open`` and ``close`` rather than the inherited ``register``
    and ``drop``, because each of those also moves the idle signal ``drain``
    waits on.
    """

    def __init__(self) -> None:
        super().__init__()
        self._idle = asyncio.Event()
        self._idle.set()
        self._drain_reason: str | None = None

    @property
    def draining(self) -> bool:
        """Whether a drain has been requested of this registry."""
        return self._drain_reason is not None

    def open(self, thread_id: str) -> RunControl:
        """Open one run's control, already drained when a drain is in force."""
        control = RunControl()
        if self._drain_reason is not None:
            control.request_drain(self._drain_reason)
        self.register(thread_id, control)
        self._idle.clear()
        return control

    def close(self, thread_id: str) -> None:
        """Drop one run's control and signal idle once none is left."""
        self.drop(thread_id)
        if not self._entries:
            self._idle.set()

    async def drain(self, reason: str) -> None:
        """Ask every open control to drain, and wait until none is left.

        A node already mid-turn finishes first, so a caller bounds this with
        its own deadline and cancels what remains; a run that did drain left a
        resumable checkpoint and no terminal status, so its open action is
        delivered again after restart.
        """
        self._drain_reason = reason
        for control in tuple(self._entries.values()):
            control.request_drain(reason)
        await self._idle.wait()
