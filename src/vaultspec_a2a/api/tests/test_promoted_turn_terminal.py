"""A turn that hands its run to a queued continuation shows no terminal.

The property is only real where a viewer can see it, so everything here is
live: a real uvicorn gateway on a real socket, a real migrated SQLite
application database, a real ``AsyncSqliteSaver``, a real LangGraph run for
each turn's completion evidence, a real journal reservation through the
production continuation queue for the continuation, and a real SSE client on
the published stream. The run and its queue are built by the helper the
control-plane continuation suites use, through the same production verbs: a
promotion staged by hand would prove nothing about the one the service
reaches.

Two places are checked, because the defect this closes reached both. The
frame was fanned out to the subscriber, and it became a row in the replay
log - each ahead of the control plane deciding whether the run was ending at
all. The row is the worse of the two, since every later reconnect is served
it again.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import pytest_asyncio

from ...control.tests._continuation import (
    RUN,
    finish_turn,
    journal_action,
    queue_continuation,
    seed_busy_run,
)
from ...database import get_thread
from ...database.run_event_repository import RunEventStore
from ...streaming import RelayHub
from ...testing import SseFrame, SseReader, serve_on_loopback
from ...thread.action_receipts import GraphActionReceipt
from ...thread.enums import ThreadStatus
from .._replay_writer_seat import replay_writer_seat
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from pathlib import Path

    from fastapi import FastAPI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

#: Hands one already-shaped worker payload to the gateway. The route reports
#: nothing of what the relay then did with it, which is why the assertions
#: below read durable state.
type Relay = Callable[[dict[str, Any]], Awaitable[None]]


def _progress_payload(index: int) -> dict[str, Any]:
    """One ordinary progress frame, numbered as the WORKER numbers it."""
    return {
        "type": "agent_status",
        "event_type": "agent_status",
        "thread_id": RUN,
        "agent_id": "coder",
        "state": "working",
        "detail": f"step {index}",
        "sequence": index,
    }


def _terminal_payload(index: int) -> dict[str, Any]:
    """The frame the worker sends when a turn's graph reaches its end."""
    return {
        "type": "thread_terminal",
        "event_type": "thread_terminal",
        "thread_id": RUN,
        "status": ThreadStatus.COMPLETED.value,
        "sequence": index,
    }


async def _run_status(session_factory: SessionFactory) -> str:
    async with session_factory() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        return thread.status


async def _retained(session_factory: SessionFactory) -> list[tuple[int, str]]:
    """The run's replay log, as the positions and types a resume would serve."""
    records = await RunEventStore(session_factory).read_after(
        thread_id=RUN, after_sequence=0, limit=100
    )
    return [(record.sequence, record.event_type) for record in records]


async def _await_promotion(
    session_factory: SessionFactory, dispatch_id: str, *, timeout: float = 10.0
) -> GraphActionReceipt:
    """Wait for the queued turn to own the run, and return its bound receipt.

    Promotion is what binds the graph receipt to the waiting journal row, so
    the row carrying one is the durable fact that the first turn's terminal
    has been decided - and the receipt the next turn must be proven under.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as reader:
            promoted = await journal_action(reader, dispatch_id)
            if promoted.graph_receipt_json is not None:
                return GraphActionReceipt.model_validate_json(
                    promoted.graph_receipt_json
                )
        await asyncio.sleep(0.02)
    raise AssertionError(f"the continuation on {RUN} was never promoted")


def _types(frames: list[SseFrame]) -> list[str]:
    return [frame.type for frame in frames]


def _sequences(frames: list[SseFrame]) -> list[int]:
    return [frame.sequence for frame in frames if frame.sequence is not None]


async def _watch_two_turns(
    base: str,
    relay: Relay,
    *,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    continuation: str,
) -> list[SseFrame]:
    """Watch one subscribed viewer across a promotion and a real settlement.

    The order of the assertions is the proof. Reading the SECOND turn's
    progress frame off the stream is what shows the first turn's terminal was
    never queued for this viewer: a delivered terminal would be the next
    frame, and would have closed the stream behind it.
    """
    async with (
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/v1/runs/{RUN}/stream") as stream,
    ):
        assert stream.status_code == 200, stream.reason_phrase
        reader = SseReader(stream.aiter_lines())
        assert (await reader.next_frame()).type == "stream_snapshot"

        await relay(_progress_payload(1))
        await relay(_terminal_payload(2))
        receipt = await _await_promotion(session_factory, continuation)
        assert await _run_status(session_factory) == ThreadStatus.RUNNING.value

        first = await reader.next_frame()
        assert first.type == "agent_status", "an ordinary frame must still arrive"
        assert first.sequence == 1

        await finish_turn(checkpointer, receipt)
        await relay(_progress_payload(3))
        second = await reader.next_frame()
        assert second.type == "agent_status", (
            "the terminal of a promoted turn reached the viewer"
        )
        # Not 3: the withheld frame took no number, so the run's positions
        # stay consecutive and a resume reads a window with no hole in it.
        assert second.sequence == 2
        assert await _retained(session_factory) == [
            (1, "agent_status"),
            (2, "agent_status"),
        ], "the terminal of a promoted turn was retained for replay"

        await relay(_terminal_payload(4))
        last = await reader.next_frame()

    assert last.type == "thread_terminal"
    assert last.sequence == 3
    assert await _run_status(session_factory) == ThreadStatus.COMPLETED.value
    assert await _retained(session_factory) == [
        (1, "agent_status"),
        (2, "agent_status"),
        (3, "thread_terminal"),
    ]
    return [*reader.received]


@pytest_asyncio.fixture(loop_scope="function")
async def staged_run(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, str]]:
    """A live-ready gateway over a run whose first turn is finished and queued.

    Yields the app and the continuation's dispatch identity. The recorder the
    relay seats on first use is closed afterwards, so neither case leaves a
    flush ticker running past its database.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    async with session_factory() as db:
        receipt = await seed_busy_run(db, tmp_path)
    await finish_turn(checkpointer, receipt)
    continuation = await queue_continuation(session_factory, tmp_path)
    yield app, continuation
    writer = replay_writer_seat(app)
    if writer is not None:
        await writer.aclose()


@pytest.mark.asyncio(loop_scope="function")
async def test_the_http_relay_withholds_a_promoted_turn_s_terminal(
    staged_run: tuple[FastAPI, str],
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """One terminal per run, at the last turn's end, over the batch route."""
    app, continuation = staged_run
    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as worker,
    ):

        async def relay(payload: dict[str, Any]) -> None:
            posted = await worker.post(
                "/internal/events/batch",
                json={"events": [{"thread_id": RUN, "ts": 1.0, "payload": payload}]},
            )
            assert posted.status_code == 200, posted.text

        received = await _watch_two_turns(
            base,
            relay,
            session_factory=session_factory,
            checkpointer=checkpointer,
            continuation=continuation,
        )

    assert _types(received).count("thread_terminal") == 1
    assert _sequences(received) == [1, 2, 3]
