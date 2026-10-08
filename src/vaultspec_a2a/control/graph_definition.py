"""Read the initial accepted executable program for later run actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import get_control_action_by_idempotency_key
from ..thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ..thread.enums import ControlActionType
from ..thread.idempotency import thread_create_action_key
from ..utils.coercion import decode_json_object
from .accepted_input import AcceptedActionInput, read_accepted_input

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread.executable_graph import FrozenGraphDefinition

__all__ = ["read_accepted_graph_definition", "read_initial_accepted_input"]


async def read_accepted_graph_definition(
    db: AsyncSession, thread_id: str
) -> FrozenGraphDefinition:
    """Return the executable program the run was accepted under.

    The initial input reader validates the immutable receipt before this
    projection exposes the program to a later action or read surface.
    """
    accepted = await read_initial_accepted_input(db, thread_id)
    definition = accepted.graph_definition
    if definition is None:
        raise ValueError("initial graph authority carries no graph definition")
    return definition


async def read_initial_accepted_input(
    db: AsyncSession, thread_id: str
) -> AcceptedActionInput:
    """Read the initial non-secret run input behind its immutable receipt.

    The receipt is matched against the payload AS THE ROW STORES IT, which is
    what the other reader of a stored accepted action does. Re-dumping the model
    this read validated was a second derivation of one digest: equal to the
    stored bytes for every payload that validates today, and a divergence
    nobody would see until a run refused to resume on a receipt that is sound.

    Raises:
        ValueError: The run has no current initial graph authority, its payload
            or receipt is unreadable, the receipt does not match the row, or the
            accepted authority belongs to another run.
    """
    action = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=thread_create_action_key(thread_id),
    )
    if (
        action is None
        or action.action_type != ControlActionType.INGEST
        or action.payload_json is None
    ):
        raise ValueError("run has no current initial graph authority")
    stored_payload = decode_json_object(action.payload_json)
    if stored_payload is None:
        raise ValueError("initial graph authority stores no readable payload")
    accepted = read_accepted_input(action)
    if action.graph_receipt_json is None:
        raise ValueError("initial graph authority has no immutable receipt")
    receipt = GraphActionReceipt.model_validate_json(action.graph_receipt_json)
    if not receipt.matches(
        thread_id=thread_id,
        action_id=action.id,
        action_type=ControlActionType.INGEST,
        dispatch_id=action.dispatch_id,
        payload_fingerprint=control_action_payload_fingerprint(stored_payload),
    ):
        raise ValueError("initial graph authority does not match its receipt")
    if accepted.dispatch["thread_id"] != thread_id:
        raise ValueError("initial graph authority belongs to a different run")
    return accepted
