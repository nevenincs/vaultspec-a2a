"""The journal can hold one waiting continuation, and says what that means.

Four properties, each asserted on a real SQLite file and a real PostgreSQL
database rather than on one of them:

* the revision that adds the queue position also removes it, so an operator who
  needs to step back is not stranded at head, and the live model agrees with
  the migrated table on both backends;
* a queued reservation must carry a position and must own nothing - no bound
  graph receipt, no application - which is what keeps "reserved" and "accepted
  for delivery" from being the same row shape;
* two rows cannot wait at the same position on one run, while a run whose
  continuation was already promoted may admit the next one at that number;
* stepping back past the revision refuses while a continuation is still
  waiting, because the earlier schema would release it as ordinary work.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, insert, inspect, select
from sqlalchemy.exc import IntegrityError

from ...tests._write_authority import make_test_write_authority
from ...thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ..models import ControlActionModel, ThreadModel
from ..permission_repository import create_control_action
from ..thread_repository import create_thread
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

_REVISION = "0024"
_PREDECESSOR = "0023"
_RUN = "continuation-queue-schema-proof"
_COLUMN = "queue_position"
_INDEX = "ux_control_actions_queued_position"


def _deadline() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


async def _seed_run(session: AsyncSession, thread_id: str = _RUN) -> None:
    await create_thread(
        session,
        write_authority=make_test_write_authority(),
        thread_id=thread_id,
        status=ThreadStatus.RUNNING,
    )
    await session.commit()


async def _queued_action(
    session: AsyncSession,
    *,
    key: str,
    position: int | None,
    thread_id: str = _RUN,
    result_status: ControlActionResultStatus = ControlActionResultStatus.QUEUED,
) -> ControlActionModel:
    action = await create_control_action(
        session,
        thread_id=thread_id,
        action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        idempotency_key=key,
        dispatch_id=f"dispatch-{key}",
        recovery_deadline_at=_deadline(),
    )
    action.result_status = result_status.value
    action.queue_position = position
    return action


def _control_action_schema(url: str) -> tuple[set[str], dict[str, bool]]:
    """Return the table's column names and each index name's uniqueness."""
    engine = create_engine(synchronous_url(url))
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            return (
                {column["name"] for column in inspector.get_columns("control_actions")},
                {
                    str(index["name"]): bool(index["unique"])
                    for index in inspector.get_indexes("control_actions")
                },
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("backend_name", BACKENDS)
def test_the_revision_adds_the_queue_position_and_its_downgrade_removes_it(
    backend_name: str, tmp_path: Path
) -> None:
    """The queue revision is reachable, complete, and fully reversible."""
    with backend(backend_name, tmp_path) as target:
        upgrade(target.url, _PREDECESSOR)
        before, before_indexes = _control_action_schema(target.url)
        assert _COLUMN not in before
        assert _INDEX not in before_indexes

        upgrade(target.url, _REVISION)
        after, after_indexes = _control_action_schema(target.url)
        assert _COLUMN in after
        # The rebuild SQLite needs for a CHECK must not cost the table its
        # earlier identity: every pre-revision column and index survives.
        assert before <= after
        assert after_indexes[_INDEX] is True
        assert set(before_indexes) <= set(after_indexes)

        downgrade(target.url, _PREDECESSOR)
        stepped_back, stepped_back_indexes = _control_action_schema(target.url)
        assert _COLUMN not in stepped_back
        assert _INDEX not in stepped_back_indexes
        assert before <= stepped_back

        upgrade(target.url)
        at_head, _ = _control_action_schema(target.url)
        assert _COLUMN in at_head


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_live_model_and_the_migrated_table_agree(
    backend_name: str, tmp_path: Path
) -> None:
    """A row written through the ORM lands in the column the migration made."""
    async with migrated_session_factory(backend_name, tmp_path) as (target, factory):
        async with factory() as session:
            await _seed_run(session)
            await _queued_action(session, key="first", position=1)
            await session.commit()

        columns, _ = _control_action_schema(target.url)
        assert _COLUMN in columns
        async with factory() as session:
            stored = (
                await session.execute(
                    select(
                        ControlActionModel.queue_position,
                        ControlActionModel.result_status,
                    ).where(ControlActionModel.thread_id == _RUN)
                )
            ).all()
            assert [tuple(row) for row in stored] == [
                (1, ControlActionResultStatus.QUEUED.value)
            ]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
@pytest.mark.parametrize(
    "flaw",
    ["no_position", "zero_position", "bound_receipt", "already_applied"],
)
async def test_a_queued_reservation_owning_anything_is_refused(
    backend_name: str, tmp_path: Path, flaw: str
) -> None:
    """Queued means reserved: a position, no receipt, nothing applied."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_run(session)

        async with factory() as session:
            action = await _queued_action(
                session,
                key=f"flawed-{flaw}",
                position=None if flaw == "no_position" else 1,
            )
            if flaw == "zero_position":
                action.queue_position = 0
            if flaw == "bound_receipt":
                action.graph_receipt_json = "{}"
            if flaw == "already_applied":
                action.applied_at = datetime.now(UTC)
            with pytest.raises(IntegrityError):
                await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_only_a_still_waiting_continuation_holds_its_position(
    backend_name: str, tmp_path: Path
) -> None:
    """Two rows cannot wait at one position; a promoted row frees its number."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_run(session)
            await _queued_action(session, key="waiting", position=1)
            await session.commit()

        async with factory() as session:
            await _queued_action(session, key="second-waiting", position=1)
            with pytest.raises(IntegrityError):
                await session.commit()

        async with factory() as session:
            promoted = await session.scalar(
                select(ControlActionModel).where(
                    ControlActionModel.idempotency_key == "waiting"
                )
            )
            assert promoted is not None
            promoted.result_status = (
                ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value
            )
            await _queued_action(session, key="after-promotion", position=1)
            await session.commit()

        async with factory() as session:
            positions = (
                await session.execute(
                    select(
                        ControlActionModel.idempotency_key,
                        ControlActionModel.queue_position,
                    ).order_by(ControlActionModel.idempotency_key)
                )
            ).all()
            assert [tuple(row) for row in positions] == [
                ("after-promotion", 1),
                ("waiting", 1),
            ]


@pytest.mark.parametrize("backend_name", BACKENDS)
def test_stepping_back_refuses_while_a_continuation_is_still_waiting(
    backend_name: str, tmp_path: Path
) -> None:
    """The earlier schema cannot hold a queued row, so it is never dropped."""
    with backend(backend_name, tmp_path) as target:
        upgrade(target.url)
        engine = create_engine(synchronous_url(target.url))
        try:
            with engine.begin() as connection:
                connection.execute(
                    insert(ThreadModel).values(
                        id=_RUN,
                        status=ThreadStatus.RUNNING.value,
                        is_active=True,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                        run_revision=0,
                        writer_generation=1,
                        writer_action_type=ControlActionType.INGEST.value,
                        writer_action_receipt_id="seed-receipt",
                    )
                )
                connection.execute(
                    insert(ControlActionModel).values(
                        [
                            # The run's own writer, without which the chain's
                            # populated-store guard refuses before this
                            # revision is reached at all.
                            {
                                "id": "writer-action",
                                "thread_id": _RUN,
                                "action_type": ControlActionType.INGEST.value,
                                "idempotency_key": "writer",
                                "requested_at": datetime.now(UTC),
                                "result_status": (
                                    ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value
                                ),
                                "worker_generation": 0,
                                "dispatch_id": "seed-receipt",
                                "recovery_deadline_at": _deadline(),
                                "queue_position": None,
                            },
                            {
                                "id": "waiting-action",
                                "thread_id": _RUN,
                                "action_type": (
                                    ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value
                                ),
                                "idempotency_key": "waiting",
                                "requested_at": datetime.now(UTC),
                                "result_status": (
                                    ControlActionResultStatus.QUEUED.value
                                ),
                                "worker_generation": 0,
                                "dispatch_id": "waiting-dispatch",
                                "recovery_deadline_at": _deadline(),
                                "queue_position": 1,
                            },
                        ]
                    )
                )
        finally:
            engine.dispose()

        with pytest.raises(Exception, match="queued continuation"):
            downgrade(target.url, _PREDECESSOR)

        # The refusal left the store at head rather than half torn down.
        columns, indexes = _control_action_schema(target.url)
        assert _COLUMN in columns
        assert _INDEX in indexes
