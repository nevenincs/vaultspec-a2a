"""Conditional persistence of the original graph-action dispatch receipt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import exists, select, update

from ..thread.action_receipts import GraphActionReceipt
from .models import ControlActionModel, ThreadModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .thread_repository import ThreadWriteExpectation


async def persist_graph_action_receipt(
    session: AsyncSession,
    *,
    receipt: GraphActionReceipt,
    expectation: ThreadWriteExpectation,
) -> GraphActionReceipt | None:
    """Persist once under exact ownership; every retry returns the same receipt."""
    authority = expectation.authority
    if (
        receipt.dispatch_id != authority.action_receipt_id
        or receipt.action_type != authority.action_type
        or receipt.run_revision != authority.run_revision
        or receipt.writer_generation != authority.writer_generation
    ):
        return None
    owns_thread = exists(
        select(ThreadModel.id).where(
            ThreadModel.id == receipt.thread_id,
            ThreadModel.status == expectation.status.value,
            ThreadModel.run_revision == authority.run_revision,
            ThreadModel.writer_generation == authority.writer_generation,
            ThreadModel.writer_action_type == authority.action_type.value,
            ThreadModel.writer_action_receipt_id == authority.action_receipt_id,
        )
    )
    identity = (
        ControlActionModel.id == receipt.action_id,
        ControlActionModel.thread_id == receipt.thread_id,
        ControlActionModel.dispatch_id == receipt.dispatch_id,
        ControlActionModel.action_type == receipt.action_type,
    )
    await session.execute(
        update(ControlActionModel)
        .where(
            *identity,
            ControlActionModel.graph_receipt_json.is_(None),
            owns_thread,
        )
        .values(graph_receipt_json=receipt.model_dump_json())
        .execution_options(synchronize_session=False)
    )
    encoded = await session.scalar(
        select(ControlActionModel.graph_receipt_json).where(*identity, owns_thread)
    )
    if encoded is None:
        return None
    try:
        stored = GraphActionReceipt.model_validate_json(encoded)
    except ValidationError:
        return None
    # State-only elections may advance revision while this action remains the
    # writer. They cannot change the original dispatch or its graph evidence.
    if (
        stored.thread_id != receipt.thread_id
        or stored.action_id != receipt.action_id
        or stored.action_type != receipt.action_type
        or stored.dispatch_id != receipt.dispatch_id
        or stored.payload_fingerprint != receipt.payload_fingerprint
        or stored.writer_generation != authority.writer_generation
        or stored.run_revision > authority.run_revision
    ):
        return None
    return stored
