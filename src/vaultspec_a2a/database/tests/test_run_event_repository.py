"""Every replay-log operation, on a real SQLite file and a real PostgreSQL.

The store is the whole durable surface the resumable stream stands on, so each
of its five operations is asserted against both backends this service ships
rather than against whichever one is cheaper to reach: an append that is one
statement, a read strictly after a cursor, the per-run high-water mark, the
newest-N trim, and the age-bounded delete.

One property here is not about SQL at all. A replay read must give its pooled
connection back BEFORE it returns, because the caller is an SSE generator that
then stays attached for as long as the viewer watches; a read that handed back
a live connection is how a handful of viewers once exhausted the pool and
stalled every other request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import QueuePool

from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..models import RunEventModel, ThreadModel
from ..run_event_repository import RunEventRecord, RunEventStore
from ..thread_repository import create_thread
from ._backends import BACKENDS, migrated_engine, migrated_session_factory

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

_RUN = "replay-store-proof"
_OTHER = "replay-store-neighbour"
_ORIGIN = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _record(sequence: int, *, thread_id: str = _RUN, age: int = 0) -> RunEventRecord:
    return RunEventRecord(
        thread_id=thread_id,
        sequence=sequence,
        event_type="message_chunk",
        payload_json=f'{{"type":"message_chunk","sequence":{sequence}}}',
        created_at=_ORIGIN - timedelta(minutes=age),
        trace_id="0" * 32,
        span_id="1" * 16,
    )


async def _seed_threads(
    factory: async_sessionmaker[AsyncSession], *thread_ids: str
) -> None:
    async with factory() as session:
        for thread_id in thread_ids:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=thread_id,
                status=ThreadStatus.RUNNING,
            )
        await session.commit()


async def _sequences(
    factory: async_sessionmaker[AsyncSession], thread_id: str
) -> list[int]:
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(RunEventModel.sequence)
                    .where(RunEventModel.thread_id == thread_id)
                    .order_by(RunEventModel.sequence)
                )
            ).scalars()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_batch_is_appended_and_read_strictly_after_a_cursor(
    backend_name: str, tmp_path: Path
) -> None:
    """One append call stores the whole batch; a read resumes past the cursor."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_threads(factory, _RUN, _OTHER)
        store = RunEventStore(factory)

        assert await store.append([_record(index) for index in range(1, 6)]) == 5
        assert await store.append([_record(1, thread_id=_OTHER)]) == 1

        after_two = await store.read_after(thread_id=_RUN, after_sequence=2, limit=10)
        assert [record.sequence for record in after_two] == [3, 4, 5]
        assert {record.thread_id for record in after_two} == {_RUN}
        assert after_two[0].payload_json == ('{"type":"message_chunk","sequence":3}')
        assert after_two[0].created_at == _ORIGIN
        assert after_two[0].trace_id == "0" * 32
        assert after_two[0].span_id == "1" * 16

        from_start = await store.read_after(thread_id=_RUN, after_sequence=0, limit=10)
        assert [record.sequence for record in from_start] == [1, 2, 3, 4, 5]

        bounded = await store.read_after(thread_id=_RUN, after_sequence=0, limit=2)
        assert [record.sequence for record in bounded] == [1, 2]

        assert await store.read_after(thread_id=_RUN, after_sequence=5, limit=10) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_retried_batch_leaves_exactly_one_frame_per_sequence(
    backend_name: str, tmp_path: Path
) -> None:
    """A flush replayed after a partial failure recovers instead of failing."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_threads(factory, _RUN)
        store = RunEventStore(factory)
        batch = [_record(index) for index in range(1, 4)]

        await store.append(batch[:2])
        await store.append(batch)

        assert await _sequences(factory, _RUN) == [1, 2, 3]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_high_water_mark_is_per_run_and_absent_when_nothing_is_retained(
    backend_name: str, tmp_path: Path
) -> None:
    """The mark answers for one run, and says nothing rather than zero when empty."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_threads(factory, _RUN, _OTHER)
        store = RunEventStore(factory)

        assert await store.high_water_mark(_RUN) is None

        await store.append([_record(index) for index in (1, 2, 7)])
        await store.append([_record(3, thread_id=_OTHER)])

        assert await store.high_water_mark(_RUN) == 7
        assert await store.high_water_mark(_OTHER) == 3
        assert await store.high_water_mark("never-ran") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_settled_cursor_is_readable_when_the_log_holds_nothing(
    backend_name: str, tmp_path: Path
) -> None:
    """The second seed source answers for a run whose window has already expired."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_threads(factory, _RUN)
        store = RunEventStore(factory)

        assert await store.settled_sequence(_RUN) is None

        async with factory() as session:
            await session.execute(
                update(ThreadModel)
                .where(ThreadModel.id == _RUN)
                .values(last_sequence=412)
            )
            await session.commit()

        assert await store.high_water_mark(_RUN) is None
        assert await store.settled_sequence(_RUN) == 412
        assert await store.settled_sequence("never-ran") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_window_trim_keeps_the_newest_rows_of_one_run(
    backend_name: str, tmp_path: Path
) -> None:
    """The bound applies per run, in the appending batch, and never over-deletes."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_threads(factory, _RUN, _OTHER)
        store = RunEventStore(factory)

        await store.append([_record(index) for index in range(1, 6)], window=3)
        await store.append([_record(index, thread_id=_OTHER) for index in (1, 2)])

        assert await _sequences(factory, _RUN) == [3, 4, 5]
        assert await _sequences(factory, _OTHER) == [1, 2]

        # A run shorter than its window keeps every row it has.
        assert await store.trim_to_window(_OTHER, 10) == 0
        assert await _sequences(factory, _OTHER) == [1, 2]

        assert await store.trim_to_window(_RUN, 1) == 2
        assert await _sequences(factory, _RUN) == [5]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_age_bound_deletes_only_frames_produced_before_the_cutoff(
    backend_name: str, tmp_path: Path
) -> None:
    """Deletion is by the frame's own allocation stamp, across every run."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_threads(factory, _RUN, _OTHER)
        store = RunEventStore(factory)

        await store.append(
            [
                _record(1, age=120),
                _record(2, age=90),
                _record(3, age=5),
                _record(1, thread_id=_OTHER, age=200),
                _record(2, thread_id=_OTHER, age=1),
            ]
        )

        deleted = await store.delete_produced_before(_ORIGIN - timedelta(minutes=60))
        assert deleted == 3
        assert await _sequences(factory, _RUN) == [3]
        assert await _sequences(factory, _OTHER) == [2]

        async with factory() as session:
            assert (
                await session.execute(select(func.count()).select_from(RunEventModel))
            ).scalar_one() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_whole_batch_is_appended_as_one_executemany(
    backend_name: str, tmp_path: Path
) -> None:
    """The flush costs one round trip, which is what puts it behind the fan-out.

    Counted off the real cursor-execute event rather than inferred: an append
    that degraded to one statement per frame would still pass every assertion
    above while putting a per-frame write on the same WAL the worker holds.
    """
    statements: list[tuple[str, bool]] = []

    def _record_statement(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        executemany: bool,
    ) -> None:
        statements.append((statement, executemany))

    async with migrated_engine(backend_name, tmp_path) as (_target, engine):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        await _seed_threads(factory, _RUN)
        store = RunEventStore(factory)

        event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
        try:
            await store.append([_record(index) for index in range(1, 6)])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)

        assert await _sequences(factory, _RUN) == [1, 2, 3, 4, 5]

    inserts = [
        (statement, executemany)
        for statement, executemany in statements
        if "INSERT INTO run_events" in statement
    ]
    assert len(inserts) == 1, statements
    assert inserts[0][1] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_replay_read_releases_its_pooled_connection_before_returning(
    backend_name: str, tmp_path: Path
) -> None:
    """The stream's own read must not pin a connection for the viewer's lifetime."""
    async with migrated_engine(backend_name, tmp_path) as (_target, engine):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        await _seed_threads(factory, _RUN)
        store = RunEventStore(factory)
        await store.append([_record(index) for index in range(1, 4)])

        pool = engine.pool
        # Asserted, not assumed: a pool that does not COUNT checkouts would
        # make every claim below vacuously true.
        assert isinstance(pool, QueuePool)
        checked_out_before = pool.checkedout()
        replayed = await store.read_after(thread_id=_RUN, after_sequence=0, limit=10)

        assert [record.sequence for record in replayed] == [1, 2, 3]
        assert pool.checkedout() == checked_out_before == 0
