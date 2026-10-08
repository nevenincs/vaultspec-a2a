"""The journaled park seats the journal the relay would have written.

A tool permission's durable journal is two rows, not one: the request row, and
the ``permission-request:`` creation action whose existence is how the relay
tells a FRESH ask from one the run is making AGAIN. A helper that wrote only the
request row seated a state production never reaches, and every test built on it
replayed the fresh-ask path where production would have taken the re-park one -
so the branch that reopens a re-asked request was unreachable from the kit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from ...control.event_handlers import RelayServices, relay_event
from ...database import (
    ControlActionModel,
    decode_allowed_options,
    get_control_action_by_idempotency_key,
    get_permission_request,
)
from ...testing import park_journaled_permission, seed_accepted_thread
from ...thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
)
from ...thread.idempotency import permission_request_action_key

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _creation_action_count(session: AsyncSession, thread_id: str) -> int:
    """How many request-creation actions the run's journal holds."""
    return (
        await session.execute(
            select(func.count())
            .select_from(ControlActionModel)
            .where(
                ControlActionModel.thread_id == thread_id,
                ControlActionModel.action_type
                == ControlActionType.PERMISSION_REQUEST_CREATED.value,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_a_journaled_park_seats_the_applied_request_creation_action(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The creation action is there, applied, under the key the relay reserves.

    Applied rather than merely written, because nothing dispatches a request
    creation: the recovery reads that tell a settled action from one still owed a
    delivery match on the instant, not on the status.
    """
    async with session_factory() as session:
        thread_id, _receipt = await seed_accepted_thread(session, status="running")
        await session.commit()

    request_id = await park_journaled_permission(
        checkpointer, session_factory, thread_id=thread_id
    )

    async with session_factory() as session:
        created = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=permission_request_action_key(request_id),
        )
        assert created is not None, "the journaled park seated no creation action"
        assert created.request_id == request_id
        assert created.result_status == ControlActionResultStatus.APPLIED.value
        assert created.applied_at is not None
        assert created.claim_token is None


@pytest.mark.asyncio
async def test_the_relay_reads_a_journaled_park_as_a_request_already_asked(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A frame for a helper-seated request takes the re-park path, not a new ask.

    This is what the creation action buys. The relay reserves that action to tell
    a fresh ask from one it has already journaled; a frame for a request the kit
    seated must find the reservation taken and go to the reopen, which leaves an
    outstanding row alone. Without the action the relay reserved it itself, took
    the fresh-ask path, and rewrote the row from the frame - so the frame below
    carries a DIFFERENT question and offer, and the row keeping the park's own is
    the proof of which path ran.
    """
    async with session_factory() as session:
        thread_id, _receipt = await seed_accepted_thread(session, status="running")
        await session.commit()

    parked_offer: list[dict[str, object]] = [
        {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"}
    ]
    request_id = await park_journaled_permission(
        checkpointer, session_factory, thread_id=thread_id, options=parked_offer
    )
    async with session_factory() as session:
        parked = await get_permission_request(session, request_id)
        assert parked is not None
        parked_description = parked.description

    await relay_event(
        thread_id,
        {
            "type": "permission_request",
            "request_id": request_id,
            "description": "A different question under the same request id",
            "options": [
                {
                    "optionId": "reject_once",
                    "name": "Reject once",
                    "kind": "reject_once",
                }
            ],
            "tool_call": "bash",
        },
        services=RelayServices(
            session_factory=session_factory, checkpointer=checkpointer
        ),
    )

    async with session_factory() as session:
        assert await _creation_action_count(session, thread_id) == 1
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.request_status == PermissionRequestStatus.PENDING.value
        assert permission.description == parked_description
        assert decode_allowed_options(permission.allowed_options_json) == parked_offer
