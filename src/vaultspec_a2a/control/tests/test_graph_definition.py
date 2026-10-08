"""The accepted graph definition is read only behind its own immutable receipt.

The journal row and the receipt it carries can diverge in exactly the way a
tamper would leave them: the row is untouched, but the stored receipt no
longer names the fingerprint of what the row actually holds. Reading the
initial graph authority past that divergence would compile and run a program
that was never the one this run was accepted under, so the read refuses
instead - the same typed refusal a dispatch rebuild (``build_followon_dispatch``)
turns into ``FailureType.INCOMPATIBLE_STATE``, which the published refusal map
serves as HTTP 409.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...control.graph_definition import read_accepted_graph_definition
from ...control.leased_dispatch import build_followon_dispatch
from ...database import create_thread, get_control_action_by_idempotency_key
from ...ipc.schemas import DispatchRequest
from ...testing import current_execution_metadata, seed_create_action
from ...thread import RunWriteAuthority
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionType
from ...thread.idempotency import thread_create_action_key

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: The SHA-256 fingerprint of an empty payload: syntactically a valid
#: :data:`~vaultspec_a2a.thread.action_receipts.Fingerprint`, but never the
#: fingerprint of this run's real accepted input, so the tamper trips the
#: receipt's own match check rather than a shape check.
_WRONG_FINGERPRINT = (
    "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


@pytest.mark.asyncio
async def test_a_tampered_receipt_refuses_the_graph_definition_read(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    thread_id = "tampered-graph-receipt"
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, "accepted"
            ),
            thread_id=thread_id,
            metadata=current_execution_metadata(tmp_path),
        )
        receipt = await seed_create_action(session, thread_id, workspace=tmp_path)
        await session.commit()

    # Confirmed untampered first: the same read the dispatch rebuild relies on
    # succeeds while the receipt still names what the row holds.
    async with session_factory() as session:
        await read_accepted_graph_definition(session, thread_id)

    tampered = receipt.model_copy(update={"payload_fingerprint": _WRONG_FINGERPRINT})
    async with session_factory() as session:
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=thread_create_action_key(thread_id),
        )
        assert action is not None
        action.graph_receipt_json = tampered.model_dump_json()
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ValueError, match="does not match its receipt"):
            await read_accepted_graph_definition(session, thread_id)

    async with session_factory() as session:
        dispatch = await build_followon_dispatch(
            session,
            thread_id=thread_id,
            thread_metadata=current_execution_metadata(tmp_path),
            action=ControlActionType.RESUME,
        )
    assert not isinstance(dispatch, DispatchRequest)
    assert dispatch.failure_type is FailureType.INCOMPATIBLE_STATE
    assert "does not match its receipt" in dispatch.reason
