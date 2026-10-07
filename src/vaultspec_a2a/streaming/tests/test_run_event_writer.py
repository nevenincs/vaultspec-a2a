"""The write lands behind the fan-out, and stays bounded when it cannot land.

The ordering under test is the one the decision fixes: allocate, ring, fan
out, flush. Its observable consequence is that a subscriber holds a frame
while the table still does not, and the proofs below assert exactly that
rather than the absence of a delay, which cannot be measured honestly.

A flush that fails is the other half. It must cost the replay window nothing
except timeliness: the records stay where a resume can still read them, the
failure is reported with a count, and the next flush carries them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest
import pytest_asyncio
from sqlalchemy import delete, text

from ...database.models import Base, ThreadModel
from ...database.run_event_repository import RunEventStore
from ...database.thread_repository import create_thread
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..aggregator import EventAggregator
from ..run_event_writer import RunEventWriter
from ..subscribers import RunSequenceAllocator, SequenceAllocation

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_RUN = "replay-writer-proof"
_ARTIFACT_BODY = "# Decision record\n\nEvery word of the document body.\n"
_DIFF_BODY = "the whole replacement text of an edited file"
_PROMPT = "the operator's private instruction to the agent"
_ACTOR_TOKEN = "role-actor-token-must-never-be-stored"


class _Harness:
    """A real store, a real aggregator, and the writer bound between them."""

    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        window: int,
        interval: float,
    ) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self.store = RunEventStore(self.session_factory)
        self.writer = RunEventWriter(
            self.store, window=window, flush_interval_seconds=interval
        )
        self.aggregator = EventAggregator()
        self.aggregator.bind_sequence_allocator(
            RunSequenceAllocator(self.store), sink=self.writer
        )

    async def seed_thread(self, thread_id: str = _RUN) -> None:
        async with self.session_factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=thread_id,
                status=ThreadStatus.RUNNING,
            )
            await session.commit()

    def attach(self, thread_id: str = _RUN) -> asyncio.Queue[Any]:
        client_id = "writer-proof-viewer"
        queue = self.aggregator.add_subscriber(client_id)
        self.aggregator.subscribe(client_id, [thread_id])
        return cast("asyncio.Queue[Any]", queue)

    async def stored(self, thread_id: str = _RUN) -> list[dict[str, Any]]:
        rows = await self.store.read_after(
            thread_id=thread_id, after_sequence=0, limit=1000
        )
        return [
            {
                "sequence": row.sequence,
                "event_type": row.event_type,
                "payload": cast("dict[str, Any]", json.loads(row.payload_json)),
            }
            for row in rows
        ]

    async def break_the_replay_log(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP TABLE run_events"))

    async def restore_the_replay_log(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.tables["run_events"].create, checkfirst=True
            )


#: A cadence no test reaches by waiting, so every write below is one a test
#: asked for. The one proof that is ABOUT the cadence states its own.
_IDLE_CADENCE = 30.0


@pytest_asyncio.fixture
async def make_harness(
    migrated_engine: AsyncEngine,
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Callable[..., Awaitable[_Harness]]]:
    """Bind a writer, with the cadence and window a proof asks for, to the store."""
    built: list[_Harness] = []

    async def _make(*, window: int = 3, interval: float = _IDLE_CADENCE) -> _Harness:
        harness = _Harness(
            migrated_engine,
            migrated_session_factory,
            window=window,
            interval=interval,
        )
        built.append(harness)
        await harness.seed_thread()
        return harness

    try:
        yield _make
    finally:
        for harness in built:
            await harness.writer.aclose()


def _frame(index: int, *, thread_id: str = _RUN) -> dict[str, object]:
    return {
        "type": "agent_status",
        "event_type": "agent_status",
        "thread_id": thread_id,
        "agent_id": "coder",
        "state": "working",
        "sequence": index,
    }


@pytest.mark.asyncio
async def test_a_frame_reaches_a_subscriber_before_its_row_is_durable(
    make_harness: Callable[..., Awaitable[_Harness]],
) -> None:
    """The write is behind the fan-out, so the queue has it and the table does not."""
    harness = await make_harness()
    queue = harness.attach()
    await harness.aggregator.prepare_run(_RUN)

    harness.aggregator.relay_payload(_RUN, _frame(1))

    delivered = cast("dict[str, Any]", queue.get_nowait())
    assert delivered["sequence"] == 1
    assert await harness.stored() == []
    assert [record.sequence for record in harness.writer.pending(_RUN)] == [1]

    assert await harness.writer.flush() == 1
    assert [row["sequence"] for row in await harness.stored()] == [1]


@pytest.mark.asyncio
async def test_a_flush_writes_the_batch_and_trims_the_run_in_the_same_pass(
    make_harness: Callable[..., Awaitable[_Harness]],
) -> None:
    """One batch per ingest, and the window applied by the writer that breached it."""
    harness = await make_harness(window=3)
    harness.attach()
    await harness.aggregator.prepare_run(_RUN)
    for index in range(1, 6):
        harness.aggregator.relay_payload(_RUN, _frame(index))

    assert await harness.writer.flush() == 5

    # window=3 on the harness: the newest three survive the same statement batch.
    assert [row["sequence"] for row in await harness.stored()] == [3, 4, 5]
    # Nothing left to offer, so a second flush is free.
    assert await harness.writer.flush() == 0


@pytest.mark.asyncio
async def test_a_failed_flush_degrades_to_the_ring_and_reports_its_count(
    make_harness: Callable[..., Awaitable[_Harness]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A store that refuses the write costs timeliness, never the window."""
    harness = await make_harness()
    harness.attach()
    await harness.aggregator.prepare_run(_RUN)
    for index in range(1, 4):
        harness.aggregator.relay_payload(_RUN, _frame(index))
    await harness.break_the_replay_log()

    with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.streaming"):
        assert await harness.writer.flush() == 0

    failures = [
        record
        for record in caplog.records
        if getattr(record, "action", None) == "run_event_flush_failed"
    ]
    assert len(failures) == 1
    assert getattr(failures[0], "pending", None) == 3
    assert "3 progress frame(s)" in failures[0].getMessage()

    # The records are still exactly where a resume taken now would read them.
    assert [record.sequence for record in harness.writer.pending(_RUN)] == [1, 2, 3]

    await harness.restore_the_replay_log()
    assert await harness.writer.flush() == 3
    assert [row["sequence"] for row in await harness.stored()] == [1, 2, 3]
    assert await harness.writer.flush() == 0


@pytest.mark.asyncio
async def test_the_cadence_writes_a_frame_no_batch_ever_asked_about(
    make_harness: Callable[..., Awaitable[_Harness]],
) -> None:
    """A frame produced outside an ingested batch still becomes durable."""
    harness = await make_harness(interval=0.02)
    harness.attach()
    await harness.aggregator.prepare_run(_RUN)
    harness.aggregator.relay_payload(_RUN, _frame(1))

    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if await harness.stored():
            break
        await asyncio.sleep(0.01)

    assert [row["sequence"] for row in await harness.stored()] == [1]


@pytest.mark.asyncio
async def test_closing_the_writer_drains_what_the_cadence_had_not(
    make_harness: Callable[..., Awaitable[_Harness]],
) -> None:
    """A shutdown writes the ring rather than discarding it."""
    harness = await make_harness()
    harness.attach()
    await harness.aggregator.prepare_run(_RUN)
    harness.aggregator.relay_payload(_RUN, _frame(1))
    harness.aggregator.relay_payload(_RUN, _frame(2))

    await harness.aggregator.shutdown()

    assert [row["sequence"] for row in await harness.stored()] == [1, 2]


@pytest.mark.asyncio
async def test_an_authoring_shaped_run_stores_no_body_diff_prompt_or_token(
    make_harness: Callable[..., Awaitable[_Harness]],
) -> None:
    """What is stored is the frame a subscriber was handed, and nothing more.

    The exclusion is by construction rather than by filtering at the write:
    the writer records the frame the chokepoint already projected, so a body
    the progress catalog omits was never in the object it serialised.
    """
    harness = await make_harness(window=10)
    harness.attach()
    await harness.aggregator.prepare_run(_RUN)

    harness.aggregator.relay_payload(
        _RUN,
        {
            "type": "artifact_update",
            "event_type": "artifact_update",
            "thread_id": _RUN,
            "artifact_id": "art-1",
            "filename": "2026-10-01-decision-adr.md",
            "content": _ARTIFACT_BODY,
            "append": False,
            "last_chunk": True,
        },
    )
    harness.aggregator.relay_payload(
        _RUN,
        {
            "type": "tool_call_update",
            "event_type": "tool_call_update",
            "thread_id": _RUN,
            "tool_call_id": "call-1",
            "title": "Edit the record",
            "kind": "edit",
            "status": "completed",
            "content": [
                {
                    "content_type": "diff",
                    "path": "2026-10-01-decision-adr.md",
                    "old_text": "old",
                    "new_text": _DIFF_BODY,
                }
            ],
        },
    )
    harness.aggregator.relay_payload(
        _RUN,
        {
            "type": "agent_status",
            "event_type": "agent_status",
            "thread_id": _RUN,
            "agent_id": "doc-editor",
            "state": "working",
            "prompt": _PROMPT,
            "actor_token": _ACTOR_TOKEN,
            "metadata": {"prompt": _PROMPT, "actor_token": _ACTOR_TOKEN},
        },
    )

    assert await harness.writer.flush() == 3
    rows = await harness.stored()
    assert [row["sequence"] for row in rows] == [1, 2, 3]

    stored_text = json.dumps([row["payload"] for row in rows])
    for forbidden in (_ARTIFACT_BODY, _DIFF_BODY, _PROMPT, _ACTOR_TOKEN):
        assert forbidden not in stored_text

    # The identity the catalog does permit is present, so an empty payload
    # cannot be mistaken for a clean one.
    assert rows[0]["payload"]["artifact_id"] == "art-1"
    assert rows[0]["event_type"] == "artifact_update"
    assert rows[1]["payload"]["tool_call_id"] == "call-1"
    assert rows[2]["payload"]["agent_id"] == "doc-editor"


_HEALTHY = "replay-writer-healthy-run"
_DELETED = "replay-writer-deleted-run"


def _hold(writer: RunEventWriter, thread_id: str, sequence: int) -> None:
    """Put one allocation in a run's ring through the writer's front door."""
    writer.record(
        SequenceAllocation(
            thread_id=thread_id, sequence=sequence, allocated_at=datetime.now(UTC)
        ),
        {
            "type": "agent_status",
            "event_type": "agent_status",
            "thread_id": thread_id,
            "sequence": sequence,
        },
    )


async def _seed_runs(factory: async_sessionmaker[AsyncSession], *runs: str) -> None:
    async with factory() as session:
        for thread_id in runs:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=thread_id,
                status=ThreadStatus.RUNNING,
            )
        await session.commit()


async def _delete_run(
    factory: async_sessionmaker[AsyncSession], thread_id: str
) -> None:
    """Remove the run's thread row, exactly as the deletion saga leaves it."""
    async with factory() as session:
        await session.execute(delete(ThreadModel).where(ThreadModel.id == thread_id))
        await session.commit()


async def _retained_sequences(store: RunEventStore, thread_id: str) -> list[int]:
    return [
        record.sequence
        for record in await store.read_after(
            thread_id=thread_id, after_sequence=0, limit=1000
        )
    ]


@pytest.mark.asyncio
async def test_a_deleted_run_cannot_stop_the_replay_log_of_every_other_run(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One run's doomed rows must not be another run's permanent outage.

    The refusal arrives as a SQLite foreign-key failure, and the consequence
    to guard against is that a run deleted with frames still held can never
    take those rows, and a flush that batched every run together therefore
    failed for every run, for as long as the gateway lived.

    The delete here is the real one: the thread row goes, and the schema's
    cascade takes its retained rows with it, which is the state the deletion
    saga leaves behind.
    """
    store = RunEventStore(migrated_session_factory)
    await _seed_runs(migrated_session_factory, _HEALTHY, _DELETED)
    writer = RunEventWriter(store, window=100, flush_interval_seconds=_IDLE_CADENCE)
    _hold(writer, _HEALTHY, 1)
    _hold(writer, _DELETED, 1)
    await _delete_run(migrated_session_factory, _DELETED)

    with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.streaming"):
        written = await writer.flush()

    assert written == 1, "the healthy run's frame did not reach the table"
    assert await _retained_sequences(store, _HEALTHY) == [1]
    abandoned = [
        record
        for record in caplog.records
        if getattr(record, "action", None) == "run_event_flush_abandoned"
    ]
    assert [getattr(record, "thread_id", None) for record in abandoned] == [_DELETED]
    # Dropped rather than retried forever: nothing of the deleted run is
    # held, so no later flush carries it and no resume is offered it.
    assert writer.pending(_DELETED) == []

    _hold(writer, _HEALTHY, 2)
    assert await writer.flush() == 1
    assert await _retained_sequences(store, _HEALTHY) == [1, 2]
    await writer.aclose()
