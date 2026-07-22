"""Bounded relay delivery drops the oldest event, not the newest.

Three relay call sites had grown their own copy of this policy. The rule they
share is lossy on purpose, so which event is lost matters: a viewer that cannot
keep up is better served by recent state than by a stale prefix, and what was
dropped is recovered by checkpoint re-projection rather than from the stream.

Real queues throughout - the behaviour under test is queue behaviour.
"""

from __future__ import annotations

import asyncio

from ..fanout import deliver_bounded


def _drain(queue: asyncio.Queue[object]) -> list[object]:
    items: list[object] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_a_payload_reaches_a_queue_with_room() -> None:
    """The ordinary case enqueues and reports success."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=4)

    assert deliver_bounded(queue, "event-1", client_id="c1") is True
    assert _drain(queue) == ["event-1"]


def test_a_full_queue_loses_its_oldest_event_not_the_new_one() -> None:
    """The newest event survives; the stalest is evicted."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=2)
    queue.put_nowait("oldest")
    queue.put_nowait("middle")

    assert deliver_bounded(queue, "newest", client_id="slow") is True
    assert _drain(queue) == ["middle", "newest"]


def test_delivery_into_a_full_queue_keeps_it_at_capacity() -> None:
    """Eviction makes room for exactly one event, so depth is stable."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=3)
    for index in range(3):
        queue.put_nowait(f"event-{index}")

    for index in range(3, 6):
        assert deliver_bounded(queue, f"event-{index}", client_id="slow") is True

    assert queue.qsize() == 3
    assert _drain(queue) == ["event-3", "event-4", "event-5"]


def test_an_unbounded_queue_never_drops() -> None:
    """A queue with no maximum is never full, so nothing is evicted."""
    queue: asyncio.Queue[object] = asyncio.Queue()

    for index in range(50):
        assert deliver_bounded(queue, index, client_id="fast") is True

    assert queue.qsize() == 50


def test_structured_context_is_accepted_without_changing_the_outcome() -> None:
    """The richer WebSocket logging path shares the policy, not a fork of it."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=1)
    queue.put_nowait("oldest")

    delivered = deliver_bounded(
        queue,
        "newest",
        client_id="c1",
        log_extra={"thread_id": "t1", "queue_maxsize": 1},
    )

    assert delivered is True
    assert _drain(queue) == ["newest"]
