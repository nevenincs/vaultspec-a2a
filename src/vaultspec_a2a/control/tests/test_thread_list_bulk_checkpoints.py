"""Listing threads must read checkpoints concurrently and bound the whole batch.

The assembly loop read each thread's checkpoint sequentially, each under its own
timeout, so a page of N slow threads cost N times that timeout with no overall
limit. The reads are batched now: bounded concurrency, one wall-clock budget.

The three states the sequential path distinguished must survive the change -
present, absent, and unverified - because a thread whose read timed out is
uncertain, not a thread with no checkpoint, and only a certain read may drive a
resumability claim.
"""

from __future__ import annotations

import asyncio
import time

from vaultspec_a2a.control.thread_service import (
    _bulk_read_checkpoints,
    _CheckpointProbe,
)


class _Checkpointer:
    """A real awaitable checkpointer over an in-memory map, no mocks.

    ``delay`` models a slow store so the batch deadline can be exercised against
    genuine concurrency rather than a patched clock.
    """

    def __init__(self, present: dict[str, object], *, delay: float = 0.0) -> None:
        self._present = present
        self._delay = delay

    async def aget_tuple(self, config: dict[str, dict[str, str]]) -> object | None:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._present.get(config["configurable"]["thread_id"])


def _read(
    checkpointer: object, ids: list[str], *, concurrency: int = 8, deadline: float = 5.0
) -> dict[str, _CheckpointProbe]:
    return asyncio.run(
        _bulk_read_checkpoints(
            checkpointer, ids, concurrency=concurrency, deadline=deadline
        )
    )


def test_present_and_absent_are_distinguished() -> None:
    """Found reports present; missing reports absent, not uncertain."""
    checkpointer = _Checkpointer({"t1": object()})

    probes = _read(checkpointer, ["t1", "t2"])

    assert probes["t1"].tuple is not None
    assert probes["t1"].unverified is False
    assert probes["t2"].tuple is None
    assert probes["t2"].unverified is False


def test_a_read_error_is_unverified_not_absent() -> None:
    """A store that raises yields uncertainty, which must not read as no checkpoint."""

    class _Failing:
        async def aget_tuple(self, config: object) -> object:
            raise RuntimeError("store down")

    probes = _read(_Failing(), ["t1"])

    assert probes["t1"].unverified is True
    assert probes["t1"].tuple is None


def test_the_batch_is_bounded_by_one_deadline_not_the_per_read_sum() -> None:
    """Many slow threads must not cost N times a per-read timeout."""
    slow = _Checkpointer({}, delay=0.3)
    ids = [f"t{i}" for i in range(12)]

    started = time.monotonic()
    probes = _read(slow, ids, concurrency=4, deadline=0.4)
    elapsed = time.monotonic() - started

    # Sequential would be ~12 * 0.3 = 3.6s; concurrent-with-deadline stays near 0.4.
    assert elapsed < 1.5, f"batch took {elapsed:.2f}s, not bounded"
    # The deadline fired: threads that could not resolve within the budget are
    # reported uncertain rather than absent. Some early reads may legitimately
    # resolve first - the point is that the batch does not wait for all N.
    assert any(p.unverified for p in probes.values()), probes


def test_concurrency_is_capped() -> None:
    """No more than the configured number of reads run at once."""
    live = 0
    peak = 0

    class _Counting:
        async def aget_tuple(self, config: object) -> object | None:
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.05)
            live -= 1
            return None

    _read(_Counting(), [f"t{i}" for i in range(20)], concurrency=3, deadline=5.0)

    assert peak <= 3, f"peak concurrency {peak} exceeded the cap"


def test_an_empty_thread_list_reads_nothing() -> None:
    """No threads, no reads, no error."""
    assert _read(_Checkpointer({}), []) == {}
