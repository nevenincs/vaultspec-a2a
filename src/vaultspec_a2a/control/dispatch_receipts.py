"""Bind worker graph input to the exact accepted durable action."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

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
from .accepted_input import AcceptedActionInput, dispatch_matches_accepted_input

if TYPE_CHECKING:
    from ..database.models import ControlActionModel
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


def validate_current_graph_receipt(
    thread: ThreadModel,
    action: ControlActionModel | None,
) -> GraphActionReceipt | None:
    """Validate stored evidence against the current writer without creating it."""
    if (
        action is None
        or action.graph_receipt_json is None
        or action.payload_json is None
    ):
        return None
    try:
        receipt = GraphActionReceipt.model_validate_json(action.graph_receipt_json)
        accepted = AcceptedActionInput.model_validate_json(action.payload_json)
        if accepted.dispatch["thread_id"] != thread.id or accepted.dispatch[
            "action"
        ] != _GRAPH_ACTIONS.get(receipt.action_type):
            return None
        fingerprint = control_action_payload_fingerprint(
            _PAYLOAD.validate_json(action.payload_json)
        )
        expectation = thread_write_expectation(thread)
    except (ValueError, ValidationError):
        return None
    if (
        receipt.thread_id != thread.id
        or receipt.action_id != action.id
        or receipt.payload_fingerprint != fingerprint
        or action.action_type != receipt.action_type
        or receipt.action_type != expectation.authority.action_type
        or receipt.dispatch_id != expectation.authority.action_receipt_id
        or receipt.writer_generation != expectation.authority.writer_generation
        or receipt.run_revision > expectation.authority.run_revision
    ):
        return None
    return receipt


async def prepare_graph_action_receipt(
    db: AsyncSession,
    *,
    thread_id: str,
    dispatch_id: str,
    install_from: ThreadWriteExpectation | None = None,
) -> GraphActionReceipt | None:
    """Attach evidence only when this action owns the exact current run.

    A new resume may install its accepted action using the witness captured
    before claiming its lease. Recovery supplies no witness and cannot promote
    an older action over a newer writer. Missing evidence stays absent so the
    dispatch boundary returns its typed incompatible-authority refusal.
    """
    thread = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == thread_id)
        .execution_options(populate_existing=True)
    )
    action = await get_control_action_by_dispatch_id(
        db, thread_id=thread_id, dispatch_id=dispatch_id
    )
    if (
        thread is None
        or action is None
        or thread.status in NON_ACTIVE_STATUSES
        or action.payload_json is None
    ):
        return None
    try:
        action_type = ControlActionType(action.action_type)
        payload = _PAYLOAD.validate_json(action.payload_json)
        accepted = AcceptedActionInput.model_validate(payload)
        if accepted.dispatch["thread_id"] != thread_id or accepted.dispatch[
            "action"
        ] != _GRAPH_ACTIONS.get(action_type):
            return None
    except (ValueError, ValidationError):
        return None
    if action_type not in _GRAPH_ACTIONS:
        return None
    expectation = thread_write_expectation(thread)
    matches = (
        expectation.authority.action_type == action_type
        and expectation.authority.action_receipt_id == dispatch_id
    )
    if not matches:
        if install_from is None:
            return None
        election = await elect_thread_status(
            db,
            thread_id,
            expectation=install_from,
            status=install_from.status,
            successor=successor_thread_write_authority(
                install_from,
                action_type=action_type,
                action_receipt_id=dispatch_id,
            ),
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            return None
        expectation = thread_write_expectation(thread)
    try:
        receipt = GraphActionReceipt.model_validate(
            {
                "schema_version": "graph-action-v1",
                "thread_id": thread_id,
                "action_id": action.id,
                "action_type": action_type,
                "payload_fingerprint": control_action_payload_fingerprint(payload),
                "dispatch_id": dispatch_id,
                "run_revision": expectation.authority.run_revision,
                "writer_generation": expectation.authority.writer_generation,
            }
        )
    except ValidationError:
        logger.warning("Refused graph receipt for dispatch %s", dispatch_id)
        return None
    return await persist_graph_action_receipt(
        db,
        receipt=receipt,
        expectation=expectation,
    )


async def bind_graph_action_receipt(
    db: AsyncSession,
    dispatch: DispatchRequest,
) -> DispatchRequest:
    """Read committed acceptance evidence; delivery creates no receipt or writer."""
    if dispatch.action == "cancel":
        return dispatch
    bind = cast("AsyncEngine | AsyncConnection | None", db.bind)
    if bind is None:
        raise RuntimeError("receipt delivery requires a bound durable database")
    # A separate read transaction sees only committed acceptance and is closed
    # before network delivery. It cannot publish or discard the caller's writes.
    async with AsyncSession(bind=db.bind) as reader:
        thread = await reader.get(ThreadModel, dispatch.thread_id)
        action = await get_control_action_by_dispatch_id(
            reader,
            thread_id=dispatch.thread_id,
            dispatch_id=dispatch.dispatch_id,
        )
        receipt = (
            validate_current_graph_receipt(thread, action)
            if thread is not None and thread.status not in NON_ACTIVE_STATUSES
            else None
        )
        if (
            receipt is not None
            and action is not None
            and action.payload_json is not None
        ):
            accepted = AcceptedActionInput.model_validate_json(action.payload_json)
            if not dispatch_matches_accepted_input(dispatch, accepted):
                receipt = None
    if receipt is not None and _GRAPH_ACTIONS[receipt.action_type] != dispatch.action:
        receipt = None
    return dispatch.model_copy(update={"graph_action_receipt": receipt})
