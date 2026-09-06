"""Read the initial accepted executable program for later run actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import get_control_action_by_idempotency_key
from ..thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ..thread.enums import ControlActionType
from ..thread.executable_graph import FrozenGraphDefinition
from .accepted_input import AcceptedActionInput

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def read_accepted_graph_definition(
    db: AsyncSession, thread_id: str
) -> FrozenGraphDefinition:
    action = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=f"thread-create:{thread_id}",
    )
    if (
        action is None
        or action.action_type != ControlActionType.INGEST
        or action.payload_json is None
    ):
        raise ValueError("run has no current initial graph authority")
    accepted = AcceptedActionInput.model_validate_json(action.payload_json)
    if action.graph_receipt_json is None:
        raise ValueError("initial graph authority has no immutable receipt")
    receipt = GraphActionReceipt.model_validate_json(action.graph_receipt_json)
    if (
        receipt.action_id != action.id
        or receipt.action_type != ControlActionType.INGEST
        or receipt.thread_id != thread_id
        or receipt.dispatch_id != action.dispatch_id
        or receipt.payload_fingerprint
        != control_action_payload_fingerprint(accepted.model_dump(mode="json"))
    ):
        raise ValueError("initial graph authority does not match its receipt")
    if accepted.dispatch["thread_id"] != thread_id:
        raise ValueError("initial graph authority belongs to a different run")
    return FrozenGraphDefinition.model_validate(accepted.dispatch["graph_definition"])
