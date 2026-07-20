"""Bounded run-admission drain gate.

A single authority for the two facts the gateway shutdown and update transaction
need: "may a new run be admitted right now?" and "have all in-flight runs
drained?". Closing admission is atomic with respect to admission itself, so no
run can slip in after a drain begins, and the gate reports quiescence the moment
its last active run is released.

The gate holds no run state beyond the set of active run ids; it neither cancels
runs nor terminates processes. Cancellation of the runs it reports still active,
and reaping their owned descendants, belong to the cancel verb and the process
containment reaper respectively. The gate only serialises admission against the
close, counts what is live, and signals when the count reaches zero after a
close.

The worker process the gateway owns runs a single asyncio event loop, so the
lock guards ordering rather than cross-thread access: admit, release, and close
all mutate the active set at await boundaries and the quiescence event is only
observed between them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "AdmissionResult",
    "AdmissionState",
    "DrainGate",
    "DrainResult",
]


class AdmissionState(StrEnum):
    """Whether the gate is admitting new runs or draining in-flight ones."""

    OPEN = "open"
    DRAINING = "draining"


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """Outcome of an :meth:`DrainGate.admit` request.

    ``admitted`` is ``True`` only when the run was registered as active; a
    refused admission carries the drain reason so the caller can surface it
    verbatim. ``active_runs`` is the live count observed under the same lock the
    decision was taken under, so it never lags the decision.
    """

    admitted: bool
    state: AdmissionState
    active_runs: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DrainResult:
    """Outcome of a bounded drain wait.

    ``quiescent`` is ``True`` when no run remained active before the deadline.
    ``active_runs`` is the count still live when the wait returned, so a
    non-quiescent result names exactly how many runs the caller must still cancel
    and reap.
    """

    quiescent: bool
    active_runs: int
    waited_seconds: float


_DRAINING_REASON = "gateway admission is closed for drain"


class DrainGate:
    """Serialise run admission against a close and report drained quiescence."""

    def __init__(self) -> None:
        self._closed = False
        self._active: set[str] = set()
        self._lock = asyncio.Lock()
        # Set exactly while the active set is empty. Starts set (nothing active),
        # cleared on the transition to a non-empty set, and re-set on the
        # transition back to empty. A drain waiter awaits this event.
        self._quiescent = asyncio.Event()
        self._quiescent.set()

    async def admit(self, run_id: str) -> AdmissionResult:
        """Register *run_id* as active unless admission is closed.

        Atomic against :meth:`close_admission`: once a drain has closed
        admission, every subsequent admit is refused, so no run is created after
        the gateway commits to draining. Admitting an already-active id is
        idempotent (the set absorbs it) and keeps the run active.
        """
        async with self._lock:
            if self._closed:
                return AdmissionResult(
                    admitted=False,
                    state=AdmissionState.DRAINING,
                    active_runs=len(self._active),
                    reason=_DRAINING_REASON,
                )
            self._active.add(run_id)
            self._quiescent.clear()
            return AdmissionResult(
                admitted=True,
                state=AdmissionState.OPEN,
                active_runs=len(self._active),
            )

    async def release(self, run_id: str) -> None:
        """Drop *run_id* from the active set; idempotent.

        Signals quiescence when the last active run is released, whether or not
        admission is closed, so a drain waiter wakes as soon as the gate is
        empty.
        """
        async with self._lock:
            self._active.discard(run_id)
            if not self._active:
                self._quiescent.set()

    async def close_admission(self) -> AdmissionState:
        """Close admission to new runs; idempotent.

        Returns the resulting :class:`AdmissionState` (always ``DRAINING``). If no
        run is active at close time the gate is already quiescent, so the
        quiescence signal is asserted here too and a following drain wait returns
        immediately.
        """
        async with self._lock:
            self._closed = True
            if not self._active:
                self._quiescent.set()
            return AdmissionState.DRAINING

    async def reopen(self) -> None:
        """Re-open admission after a completed drain; idempotent.

        Only a fresh runtime generation re-opens; a gateway that drains toward
        shutdown never calls this. Kept explicit so the closed flag is never
        cleared by a side effect of admit or release.
        """
        async with self._lock:
            self._closed = False

    async def wait_quiescent(self, timeout: float | None = None) -> DrainResult:
        """Wait until no run is active or *timeout* elapses.

        Does not close admission; a caller that wants the drain invariant closes
        first (or calls :meth:`drain`). A ``None`` timeout waits indefinitely.
        """
        loop = asyncio.get_running_loop()
        start = loop.time()
        quiescent = True
        if timeout is None:
            await self._quiescent.wait()
        else:
            try:
                await asyncio.wait_for(self._quiescent.wait(), timeout)
            except TimeoutError:
                quiescent = False
        async with self._lock:
            active = len(self._active)
        return DrainResult(
            quiescent=quiescent and active == 0,
            active_runs=active,
            waited_seconds=loop.time() - start,
        )

    async def drain(self, timeout: float | None = None) -> DrainResult:
        """Close admission, then wait for the active set to empty.

        The drain invariant in one call: admission is closed before the wait, so
        the count can only fall. Returns a non-quiescent :class:`DrainResult`
        naming the runs still live at the deadline; the caller cancels those and
        reaps their descendants.
        """
        await self.close_admission()
        return await self.wait_quiescent(timeout)

    @property
    def is_draining(self) -> bool:
        """Whether admission has been closed."""
        return self._closed

    @property
    def active_run_count(self) -> int:
        """Number of runs currently registered active."""
        return len(self._active)

    def is_active(self, run_id: str) -> bool:
        """Whether *run_id* is currently registered active."""
        return run_id in self._active
