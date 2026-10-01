"""The replay log's table is reversible, idempotent, and bound to its thread.

Three properties, each asserted on a real SQLite file and a real PostgreSQL
database rather than on one of them:

* the revision that creates ``run_events`` also removes it, so an operator who
  needs to step back is not stranded at head;
* the composite primary key refuses a second write of the same
  ``(thread_id, sequence)``, which is what makes a retried flush idempotent
  instead of a duplicated frame in a consumer's replay;
* deleting a thread takes its retained frames with it, through the database's
  own cascade rather than through an ORM load of the whole retention window.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError

from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..models import RunEventModel, ThreadModel
from ..thread_repository import create_thread, delete_thread
from ._backends import (
    BACKENDS,
    backend,
    downgrade,
    migrated_session_factory,
    synchronous_url,
    upgrade,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

_REVISION = "0023"
_PREDECESSOR = "0022"
_RUN = "run-events-schema-proof"

_EXPECTED_COLUMNS = frozenset(
    {
        "thread_id",
        "sequence",
        "event_type",
        "payload_json",
        "created_at",
        "trace_id",
        "span_id",
    }
)


def _frame(sequence: int, *, thread_id: str = _RUN) -> RunEventModel:
    return RunEventModel(
        thread_id=thread_id,
        sequence=sequence,
        event_type="agent_status",
        payload_json='{"type":"agent_status"}',
        created_at=datetime.now(UTC),
    )


async def _seed_thread(session: AsyncSession, thread_id: str = _RUN) -> None:
    await create_thread(
        session,
        write_authority=make_test_write_authority(),
        thread_id=thread_id,
        status=ThreadStatus.RUNNING,
    )
    await session.commit()


def _table_names(url: str) -> set[str]:
    engine = create_engine(synchronous_url(url))
    try:
        with engine.connect() as connection:
            return set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.parametrize("backend_name", BACKENDS)
def test_the_revision_adds_the_replay_log_and_its_downgrade_removes_it(
    backend_name: str, tmp_path: Path
) -> None:
    """The replay-log revision is reachable, complete, and fully reversible."""
    with backend(backend_name, tmp_path) as target:
        upgrade(target.url, _PREDECESSOR)
        assert "run_events" not in _table_names(target.url)

        upgrade(target.url, _REVISION)
        engine = create_engine(synchronous_url(target.url))
        try:
            with engine.connect() as connection:
                inspector = inspect(connection)
                assert "run_events" in set(inspector.get_table_names())
                assert {
                    column["name"] for column in inspector.get_columns("run_events")
                } == _EXPECTED_COLUMNS
                assert tuple(
                    inspector.get_pk_constraint("run_events")["constrained_columns"]
                ) == ("thread_id", "sequence")
                assert "ix_run_events_created_at" in {
                    str(index["name"]) for index in inspector.get_indexes("run_events")
                }
                assert {
                    str(key.get("options", {}).get("ondelete") or "").upper()
                    for key in inspector.get_foreign_keys("run_events")
                } == {"CASCADE"}
        finally:
            engine.dispose()

        downgrade(target.url, _PREDECESSOR)
        after_downgrade = _table_names(target.url)
        assert "run_events" not in after_downgrade
        assert "threads" in after_downgrade

        # Head must carry the table too: the chain grows, and a revision that
        # only works when named explicitly is not the one production applies.
        upgrade(target.url)
        assert "run_events" in _table_names(target.url)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_repeated_sequence_is_refused_by_the_primary_key(
    backend_name: str, tmp_path: Path
) -> None:
    """A retried write of one allocation cannot duplicate a consumer's frame."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_thread(session)
            session.add(_frame(1))
            await session.commit()

        async with factory() as session:
            session.add(_frame(1))
            with pytest.raises(IntegrityError):
                await session.commit()

        async with factory() as session:
            stored = (
                await session.execute(
                    select(RunEventModel.sequence).where(
                        RunEventModel.thread_id == _RUN
                    )
                )
            ).scalars()
            assert list(stored) == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_deleting_a_thread_removes_its_retained_frames(
    backend_name: str, tmp_path: Path
) -> None:
    """The cascade is the database's, and it fires on the production delete path."""
    other = f"{_RUN}-survivor"
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_thread(session)
            await _seed_thread(session, other)
            session.add_all(
                [_frame(index) for index in (1, 2, 3)] + [_frame(1, thread_id=other)]
            )
            await session.commit()

        async with factory() as session:
            assert await delete_thread(session, _RUN) is True
            await session.commit()

        async with factory() as session:
            remaining = (
                await session.execute(
                    select(RunEventModel.thread_id, RunEventModel.sequence)
                )
            ).all()
            assert [tuple(row) for row in remaining] == [(other, 1)]
            assert (
                await session.execute(select(func.count()).select_from(ThreadModel))
            ).scalar_one() == 1
