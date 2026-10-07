"""Conditional persistence of the original graph-action dispatch receipt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import exists, select, update

from ..thread.action_receipts import GraphActionReceipt
from .models import ControlActionModel, ThreadModel
from .thread_repository import thread_owned_by

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread import ThreadWriteExpectation


def _matches_original_receipt(
    stored: GraphActionReceipt,
    receipt: GraphActionReceipt,
    expectation: ThreadWriteExpectation,
) -> bool:
    return (
        stored.thread_id == receipt.thread_id
        and stored.action_id == receipt.action_id
        and stored.action_type == receipt.action_type
        and stored.dispatch_id == receipt.dispatch_id
        and stored.payload_fingerprint == receipt.payload_fingerprint
        and expectation.authority.owned_by(
            stored.action_type,
            stored.dispatch_id,
            writer_generation=stored.writer_generation,
            run_revision=stored.run_revision,
            exact_revision=False,
        )
    )


async def persist_graph_action_receipt(
    session: AsyncSession,
    *,
    receipt: GraphActionReceipt,
    expectation: ThreadWriteExpectation,
) -> GraphActionReceipt | None:
    """Persist once under exact ownership; every retry returns the same receipt."""
    authority = expectation.authority
    if not authority.owned_by(
        receipt.action_type,
        receipt.dispatch_id,
        writer_generation=receipt.writer_generation,
        run_revision=receipt.run_revision,
    ):
        return None
    owns_thread = exists(
        select(ThreadModel.id).where(
            ThreadModel.id == receipt.thread_id,
            ThreadModel.status == expectation.status.value,
            thread_owned_by(
                authority.action_type,
                authority.action_receipt_id,
                writer_generation=authority.writer_generation,
                run_revision=authority.run_revision,
            ),
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
    if not _matches_original_receipt(stored, receipt, expectation):
        return None
    return stored
