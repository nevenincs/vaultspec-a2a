"""Bind worker graph input to the exact accepted durable action."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from ..database import (
    ThreadModel,
    ThreadStatusElectionOutcome,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ..database.graph_receipt_repository import persist_graph_action_receipt
from ..thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ..thread.enums import NON_ACTIVE_STATUSES, ControlActionType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.thread_repository import ThreadWriteExpectation
    from ..ipc.schemas import DispatchRequest

logger = logging.getLogger(__name__)
_PAYLOAD = TypeAdapter(dict[str, object])
_GRAPH_ACTIONS = {
    ControlActionType.INGEST: "ingest",
    ControlActionType.MESSAGE_FOLLOWUP_REQUESTED: "ingest",
    ControlActionType.RESUME: "resume",
    ControlActionType.PERMISSION_RESPONSE_SUBMITTED: "resume",
}


async def bind_graph_action_receipt(
    db: AsyncSession,
    dispatch: DispatchRequest,
    *,
    install_from: ThreadWriteExpectation | None = None,
) -> DispatchRequest:
    """Attach evidence only when this action owns the exact current run.

    A new resume may install its accepted action using the witness captured
    before claiming its lease. Recovery supplies no witness and cannot promote
    an older action over a newer writer. Missing evidence stays absent so the
    dispatch boundary returns its typed incompatible-authority refusal.
    """
    if dispatch.action == "cancel":
        return dispatch
    dispatch = dispatch.model_copy(update={"graph_action_receipt": None})
    thread = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == dispatch.thread_id)
        .execution_options(populate_existing=True)
    )
    action = await get_control_action_by_dispatch_id(
        db, thread_id=dispatch.thread_id, dispatch_id=dispatch.dispatch_id
    )
    if (
        thread is None
        or action is None
        or thread.status in NON_ACTIVE_STATUSES
        or action.payload_json is None
    ):
        await db.commit()
        return dispatch
    try:
        action_type = ControlActionType(action.action_type)
        payload = _PAYLOAD.validate_json(action.payload_json)
    except (ValueError, ValidationError):
        await db.commit()
        return dispatch
    if _GRAPH_ACTIONS.get(action_type) != dispatch.action:
        await db.commit()
        return dispatch
    expectation = thread_write_expectation(thread)
    matches = (
        expectation.authority.action_type == action_type
        and expectation.authority.action_receipt_id == dispatch.dispatch_id
    )
    if not matches:
        if install_from is None:
            await db.commit()
            return dispatch
        election = await elect_thread_status(
            db,
            dispatch.thread_id,
            expectation=install_from,
            status=install_from.status,
            successor=successor_thread_write_authority(
                install_from,
                action_type=action_type,
                action_receipt_id=dispatch.dispatch_id,
            ),
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            await db.commit()
            return dispatch
        expectation = thread_write_expectation(thread)
    try:
        receipt = GraphActionReceipt.model_validate(
            {
                "schema_version": "graph-action-v1",
                "thread_id": dispatch.thread_id,
                "action_id": action.id,
                "action_type": action_type,
                "payload_fingerprint": control_action_payload_fingerprint(payload),
                "dispatch_id": dispatch.dispatch_id,
                "run_revision": expectation.authority.run_revision,
                "writer_generation": expectation.authority.writer_generation,
            }
        )
    except ValidationError:
        logger.warning("Refused graph receipt for dispatch %s", dispatch.dispatch_id)
        await db.commit()
        return dispatch
    receipt = await persist_graph_action_receipt(
        db,
        receipt=receipt,
        expectation=expectation,
    )
    await db.commit()
    return dispatch.model_copy(update={"graph_action_receipt": receipt})
