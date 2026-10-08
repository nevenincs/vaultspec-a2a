"""Bounded relay delivery drops the oldest event, not the newest.

One drop rule serves every bounded relay queue. It is lossy on purpose, so which
event is lost matters: a viewer that cannot keep up is better served by recent
state than by a stale prefix, and what was dropped is recovered by checkpoint
re-projection rather than from the stream.

Real queues throughout - the behaviour under test is queue behaviour.
"""

from __future__ import annotations

import asyncio

from ...graph.enums import ProviderCondition
from ..fanout import deliver_bounded


def _drain(queue: asyncio.Queue[object]) -> list[object]:
    items: list[object] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_a_payload_reaches_a_queue_with_room() -> None:
    """The ordinary case enqueues and reports success."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=4)

    assert deliver_bounded(queue, "event-1", client_id="c1").delivered is True
    assert _drain(queue) == ["event-1"]


def test_a_full_queue_loses_its_oldest_event_not_the_new_one() -> None:
    """The newest event survives; the stalest is evicted."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=2)
    queue.put_nowait("oldest")
    queue.put_nowait("middle")

    assert deliver_bounded(queue, "newest", client_id="slow").delivered is True
    assert _drain(queue) == ["middle", "newest"]


def test_delivery_into_a_full_queue_keeps_it_at_capacity() -> None:
    """Eviction makes room for exactly one event, so depth is stable."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=3)
    for index in range(3):
        queue.put_nowait(f"event-{index}")

    for index in range(3, 6):
        assert (
            deliver_bounded(queue, f"event-{index}", client_id="slow").delivered is True
        )

    assert queue.qsize() == 3
    assert _drain(queue) == ["event-3", "event-4", "event-5"]


def test_an_unbounded_queue_never_drops() -> None:
    """A queue with no maximum is never full, so nothing is evicted."""
    queue: asyncio.Queue[object] = asyncio.Queue()

    for index in range(50):
        assert deliver_bounded(queue, index, client_id="fast").delivered is True

    assert queue.qsize() == 50


def _error_event(sequence: int) -> dict[str, object]:
    """Build the relayed failure payload, in the wire shape it arrives in."""
    return {
        "type": "error",
        "event_type": "error",
        "thread_id": "t1",
        "agent_id": "supervisor",
        "timestamp": float(sequence),
        "sequence": sequence,
        "code": ProviderCondition.THROTTLED.value,
        "message": "RateLimitError: too many requests",
        "recoverable": False,
    }


def _terminal_frame() -> dict[str, object]:
    """Build the relayed terminal payload, in the wire shape it arrives in."""
    return {
        "type": "thread_terminal",
        "event_type": "thread_terminal",
        "thread_id": "t1",
        "status": "failed",
        "error_detail": "RateLimitError: too many requests",
    }


def test_a_terminal_outlives_a_flood_of_progress() -> None:
    """The outcome survives a client falling arbitrarily far behind.

    A terminal is emitted once and nothing restates it on this stream, so losing
    it to backpressure leaves a client watching a run that never appears to end.
    The flood is an order of magnitude past the bound, and the bound holds
    throughout.
    """
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=4)
    queue.put_nowait(_terminal_frame())

    for index in range(40):
        assert (
            deliver_bounded(queue, f"chunk-{index}", client_id="slow").delivered is True
        )
        assert queue.qsize() <= 4, "the bound must hold on every delivery"

    drained = _drain(queue)
    assert queue.maxsize == 4
    assert len(drained) == 4
    assert drained[0] == _terminal_frame(), (
        "the terminal must survive, and keep its position ahead of what followed"
    )
    assert drained[1:] == ["chunk-37", "chunk-38", "chunk-39"]


def test_an_error_outlives_a_flood_of_progress() -> None:
    """The failure that explains the terminal survives on the same terms."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=3)
    failure = _error_event(1)
    queue.put_nowait(failure)

    for index in range(30):
        assert (
            deliver_bounded(queue, f"chunk-{index}", client_id="slow").delivered is True
        )

    drained = _drain(queue)
    assert queue.qsize() == 0
    assert drained[0] is failure
    assert drained[1:] == ["chunk-28", "chunk-29"]


def test_progress_ahead_of_an_outcome_is_evicted_before_it() -> None:
    """Eviction takes the oldest DROPPABLE entry, not simply the oldest.

    The distinction only shows when an outcome frame sits at the head with
    ordinary progress behind it: drop-oldest would take the outcome, and the
    ordering of what remains would be unchanged either way.
    """
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=3)
    failure = _error_event(1)
    queue.put_nowait(failure)
    queue.put_nowait("chunk-a")
    queue.put_nowait("chunk-b")

    assert deliver_bounded(queue, "chunk-c", client_id="slow").delivered is True

    assert _drain(queue) == [failure, "chunk-b", "chunk-c"]


def test_a_queue_of_outcomes_still_yields_its_oldest() -> None:
    """The bound wins when nothing droppable is left.

    Refusing to evict here would let one slow client grow its queue without
    limit, which is the failure this module exists to prevent. The newest
    outcome is the one kept, consistent with the policy everywhere else.
    """
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=2)
    first = _error_event(1)
    second = _error_event(2)
    queue.put_nowait(first)
    queue.put_nowait(second)

    assert deliver_bounded(queue, _terminal_frame(), client_id="slow").delivered is True

    assert queue.qsize() == 2
    assert _drain(queue) == [second, _terminal_frame()]


def test_an_eviction_is_reported_to_the_caller_not_only_to_the_log() -> None:
    """A drop the consumer is never told about reads as a complete history."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=1)
    queue.put_nowait("oldest")

    outcome = deliver_bounded(queue, "newest", client_id="slow")

    assert outcome.delivered is True
    assert outcome.dropped == 1


def test_a_delivery_with_room_costs_the_client_nothing() -> None:
    """A client keeping up must never be told it lost something."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=4)

    outcome = deliver_bounded(queue, "event", client_id="fast")

    assert outcome.delivered is True
    assert outcome.dropped == 0
