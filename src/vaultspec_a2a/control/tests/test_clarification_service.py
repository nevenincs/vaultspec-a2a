"""The claimed-action decision refuses a resolution once the run has settled.

``_claimed_action_result`` is the one place that combines three independent
facts about a claimed clarification resume - whether the payload still matches,
whether it is already applied, and whether the checkpoint still parks this
exact request - with a fourth the caller snapshots separately: the run's own
lifecycle status. A run that reaches a terminal status while its resume is
still an unapplied, matching, correctly-parked claim must still be refused:
nothing may dispatch into a run that is no longer there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from ...control.action_lease import ControlActionClaim
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.clarification_service import (
    ClarificationRuntime,
    _ClaimContext,
    _claimed_action_result,
)
from ...control.leased_dispatch import DispatchTransport
from ...database import create_control_action, create_thread
from ...testing import adopted_spawner
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.idempotency import clarification_response_action_key

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_status",
    [ThreadStatus.CANCELLED, ThreadStatus.FAILED, ThreadStatus.COMPLETED],
)
async def test_a_matching_unapplied_claim_is_refused_once_the_run_is_not_active(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    terminal_status: ThreadStatus,
) -> None:
    """Every other check passes; only the run's own status refuses it.

    This is the exact shape a retrying dispatcher sees when its own lease on an
    already-reserved, unapplied resume is still held by itself (or has lapsed to
    nobody) while the run it addresses settled terminal in between: the payload
    it reserved still matches, the action is not yet applied, and the checkpoint
    still parks the same request. Reaching ``_claimed_action_result`` in that
    exact state and getting anything OTHER than "Run is not active" would let a
    stale resume settle a run that already ended.
    """
    thread_id = f"settled-clarification-{terminal_status.value}"
    request_id = "clarification-settled-request"
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=ThreadStatus.RUNNING,
            title="Settled while a matching resume claim is still held",
        )
        action = await create_control_action(
            session,
            thread_id=thread_id,
            action_type=ControlActionType.RESUME,
            request_id=request_id,
            idempotency_key=clarification_response_action_key(request_id),
            payload={"answers": {"provider": "codex"}},
            dispatch_id=f"dispatch-{thread_id}",
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.commit()

    assert action.dispatch_id is not None
    claim = ControlActionClaim(
        action_id=action.id,
        dispatch_id=action.dispatch_id,
        created=True,
        payload_matches=True,
        acquired=False,
        authority_matches=True,
        applied=False,
        result_status=action.result_status,
        claim_token=None,
    )

    async with (
        httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client,
        session_factory() as session,
    ):
        context = _ClaimContext(
            runtime=ClarificationRuntime(
                checkpointer,
                DispatchTransport(
                    worker_client=client,
                    circuit_breaker=WorkerCircuitBreaker(
                        failure_threshold=1, recovery_timeout=30.0
                    ),
                    worker_spawner=adopted_spawner(),
                ),
            ),
            fingerprint="irrelevant-to-this-decision",
            payload={},
            idempotency_key=clarification_response_action_key(request_id),
            thread_id=thread_id,
            request_id=request_id,
            parked_matches=True,
        )
        result = await _claimed_action_result(
            session, action, claim, context, terminal_status.value
        )

    assert result is not None
    assert result.accepted is False
    assert result.applied is False
    assert result.error_detail == "Run is not active"
    assert result.error_status_code == 409
