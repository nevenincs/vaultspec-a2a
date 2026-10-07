"""The team status never advertises a question left open on a settled run.

A permission row can outlive the run it was asked on - the respond path writes
the answer before the settlement that closes the run reads it, a crash can
leave a stale row behind - and ``build_team_status`` must read past it exactly
as the shared ``actionable_pending_permissions`` query does: a run that has
already reached a terminal status contributes no thread id and no pending
permission, however pending its own row still reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...control.team_service import build_team_status
from ...database import create_thread, record_permission_request
from ...streaming import RelayHub
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: A once-only approval and refusal - a usable option set, so the live run's
#: request is read as actionable rather than filtered out for offering nothing.
_OFFERED: list[dict[str, object]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


async def _seed_pending_request(
    session: AsyncSession, *, thread_id: str, status: ThreadStatus, request_id: str
) -> None:
    await create_thread(
        session,
        write_authority=make_test_write_authority(),
        thread_id=thread_id,
        status=status,
    )
    await record_permission_request(
        session,
        request_id=request_id,
        thread_id=thread_id,
        pause_reason_type="bash",
        description="Allow the command?",
        allowed_options=_OFFERED,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_status",
    [ThreadStatus.CANCELLED, ThreadStatus.FAILED, ThreadStatus.COMPLETED],
)
async def test_a_pending_request_left_open_on_a_settled_run_is_excluded(
    session_factory: async_sessionmaker[AsyncSession],
    terminal_status: ThreadStatus,
) -> None:
    async with session_factory() as session:
        await _seed_pending_request(
            session,
            thread_id="live-run",
            status=ThreadStatus.INPUT_REQUIRED,
            request_id="live-request",
        )
        await _seed_pending_request(
            session,
            thread_id=f"settled-run-{terminal_status.value}",
            status=terminal_status,
            request_id=f"stale-request-{terminal_status.value}",
        )
        await session.commit()

    async with session_factory() as session:
        status = await build_team_status(
            db=session, relay_hub=RelayHub(), heartbeat_threads=[]
        )

    assert status.active_threads == ["live-run"]
    assert [p.request_id for p in status.pending_permissions] == ["live-request"]
    assert [p.thread_id for p in status.pending_permissions] == ["live-run"]
