"""The replay log expires on its own bound, and on nothing else's.

Two claims, and they are asserted in one module because they are one claim
seen from either side. The replay sweep must remove a settled run's retained
frames while leaving its checkpoints alone, and the settled-checkpoint prune
must remove that history while leaving the retained frames alone. Either
coupling would make one store's lifetime quietly decide the other's: a run
whose checkpoints were pruned would lose a resumable window it was promised,
or a run whose window expired would lose the state it resumes execution from.

The sweep itself runs against both backends this service ships, because it is
application schema and a bound proved on one of them is half a proof. The
pair of directions above runs on the SQLite saver, which is the one whose
store this project writes retention statements against directly.
"""

from __future__ import annotations

import operator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START
from sqlalchemy import update

from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..checkpoint_retention import prune_settled_checkpoints
from ..models import ThreadModel
from ..run_event_repository import RunEventRecord, RunEventStore
from ..run_event_retention import sweep_replay_log
from ..thread_repository import create_thread
from ._backends import BACKENDS, migrated_session_factory
from ._checkpoint_history import config_for, stored_history

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..checkpoints import Checkpointer

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_BOUND_HOURS = 24.0
_SETTLED_LONG_AGO = "replay-retention-settled"
_SETTLED_JUST_NOW = "replay-retention-fresh"
_STILL_RUNNING = "replay-retention-running"


class _Log(TypedDict):
    log: Annotated[list[str], operator.add]


def _append(entry: str) -> Any:
    async def node(state: _Log) -> dict[str, list[str]]:
        del state
        return {"log": [entry]}

    return node


def _two_step_graph(saver: Checkpointer) -> Any:
    """A real graph whose run leaves more than one checkpoint behind."""
    builder = new_state_graph(_Log)
    add_test_node(builder, "first", _append("first"))
    add_test_node(builder, "second", _append("second"))
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    return compile_test_graph(builder, checkpointer=saver)


def _frame(thread_id: str, sequence: int, *, age_hours: float) -> RunEventRecord:
    return RunEventRecord(
        thread_id=thread_id,
        sequence=sequence,
        event_type="agent_status",
        payload_json=f'{{"type":"agent_status","sequence":{sequence}}}',
        created_at=_NOW - timedelta(hours=age_hours),
    )


async def _seed_run(
    factory: async_sessionmaker[AsyncSession],
    thread_id: str,
    *,
    status: ThreadStatus,
    settled_hours_ago: float | None = None,
) -> None:
    """Create a run, and backdate its last write when it settled long ago.

    ``updated_at`` is what says when a run last changed, so a settled run
    that ended before the bound is one whose last write is old. It is set
    explicitly rather than waited for, which keeps the bound a statement
    about the data instead of a race against the clock.
    """
    async with factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=status,
        )
        if settled_hours_ago is not None:
            await session.execute(
                update(ThreadModel)
                .where(ThreadModel.id == thread_id)
                .values(updated_at=_NOW - timedelta(hours=settled_hours_ago))
            )
        await session.commit()


async def _retained(store: RunEventStore, thread_id: str) -> list[int]:
    return [
        record.sequence
        for record in await store.read_after(
            thread_id=thread_id, after_sequence=0, limit=100
        )
    ]


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_sweep_expires_a_window_by_age_and_by_settlement(
    tmp_path: Path, backend_name: str
) -> None:
    """Both bounds, and the frames each one alone would miss.

    The long-settled run carries a frame stamped AFTER the cutoff - a late
    relay arriving past its own terminal - which the age bound cannot reach
    and which nobody will ever resume. The still-running run carries frames
    on both sides of the cutoff, which is the case the settlement bound
    cannot reach: a week-long run must not accumulate a week of frames just
    because it has not ended.
    """
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_run(
            factory,
            _SETTLED_LONG_AGO,
            status=ThreadStatus.COMPLETED,
            settled_hours_ago=48,
        )
        await _seed_run(
            factory,
            _SETTLED_JUST_NOW,
            status=ThreadStatus.COMPLETED,
            settled_hours_ago=1,
        )
        await _seed_run(factory, _STILL_RUNNING, status=ThreadStatus.RUNNING)

        store = RunEventStore(factory)
        await store.append(
            [
                _frame(_SETTLED_LONG_AGO, 1, age_hours=50),
                _frame(_SETTLED_LONG_AGO, 2, age_hours=0.5),
                _frame(_SETTLED_JUST_NOW, 1, age_hours=1),
                _frame(_STILL_RUNNING, 1, age_hours=200),
                _frame(_STILL_RUNNING, 2, age_hours=1),
            ]
        )

        deleted = await sweep_replay_log(
            factory, retention_hours=_BOUND_HOURS, now=_NOW
        )

        assert await _retained(store, _SETTLED_LONG_AGO) == []
        assert await _retained(store, _SETTLED_JUST_NOW) == [1]
        assert await _retained(store, _STILL_RUNNING) == [2]
        assert deleted == 3


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_sweep_with_nothing_to_expire_deletes_nothing(
    tmp_path: Path, backend_name: str
) -> None:
    """The counterweight: a sweep that deletes a live run's window is a bug."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        await _seed_run(factory, _STILL_RUNNING, status=ThreadStatus.RUNNING)
        store = RunEventStore(factory)
        await store.append(
            [_frame(_STILL_RUNNING, sequence, age_hours=1) for sequence in (1, 2, 3)]
        )

        swept = await sweep_replay_log(factory, retention_hours=_BOUND_HOURS, now=_NOW)
        assert swept == 0
        assert await _retained(store, _STILL_RUNNING) == [1, 2, 3]


@pytest.mark.asyncio(loop_scope="function")
async def test_the_replay_sweep_leaves_every_checkpoint_where_it_was(
    tmp_path: Path,
) -> None:
    """One store's retention must not become the other's.

    The run below is settled past the bound, so the sweep removes its whole
    window; its checkpoints are what a resumed EXECUTION reads, and they are
    on their own schedule. A sweep that reached them would silently shorten
    checkpoint retention to the replay bound.
    """
    async with (
        migrated_session_factory("sqlite", tmp_path) as (_target, factory),
        AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver,
    ):
        await _two_step_graph(saver).ainvoke(
            {"log": []}, cast("Any", config_for(_SETTLED_LONG_AGO))
        )
        before = await stored_history(saver, _SETTLED_LONG_AGO)
        assert sum(len(ids) for ids in before.values()) > 1, (
            "the run left too little history for the claim to mean anything"
        )

        await _seed_run(
            factory,
            _SETTLED_LONG_AGO,
            status=ThreadStatus.COMPLETED,
            settled_hours_ago=48,
        )
        store = RunEventStore(factory)
        await store.append([_frame(_SETTLED_LONG_AGO, 1, age_hours=50)])

        assert await sweep_replay_log(factory, retention_hours=_BOUND_HOURS, now=_NOW)
        assert await _retained(store, _SETTLED_LONG_AGO) == []
        assert await stored_history(saver, _SETTLED_LONG_AGO) == before


@pytest.mark.asyncio(loop_scope="function")
async def test_the_checkpoint_prune_leaves_every_retained_frame_where_it_was(
    tmp_path: Path,
) -> None:
    """The same independence, read from the other side.

    The frames here are old enough that the replay sweep WOULD delete them,
    which is what makes the assertion about ownership rather than about
    timing: the checkpoint prune leaves them because they are not its rows,
    not because they are young.
    """
    async with (
        migrated_session_factory("sqlite", tmp_path) as (_target, factory),
        AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver,
    ):
        await _two_step_graph(saver).ainvoke(
            {"log": []}, cast("Any", config_for(_SETTLED_LONG_AGO))
        )
        before = await stored_history(saver, _SETTLED_LONG_AGO)

        await _seed_run(
            factory,
            _SETTLED_LONG_AGO,
            status=ThreadStatus.COMPLETED,
            settled_hours_ago=48,
        )
        store = RunEventStore(factory)
        await store.append(
            [
                _frame(_SETTLED_LONG_AGO, sequence, age_hours=50)
                for sequence in (1, 2, 3)
            ]
        )

        assert await prune_settled_checkpoints(saver, _SETTLED_LONG_AGO) is True

        after = await stored_history(saver, _SETTLED_LONG_AGO)
        assert sum(len(ids) for ids in after.values()) < sum(
            len(ids) for ids in before.values()
        ), "the prune removed nothing, so it proves nothing about what it kept"
        assert await _retained(store, _SETTLED_LONG_AGO) == [1, 2, 3]
