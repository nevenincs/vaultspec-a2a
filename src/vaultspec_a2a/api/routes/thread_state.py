"""GET /threads/{thread_id}/state -- Thread state snapshot for reconnection."""

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.thread_state_service import build_thread_state
from ...database import get_thread
from ...database.checkpoints import Checkpointer
from ...database.session import get_db
from ...streaming.aggregator import EventAggregator
from ...thread.snapshots import ThreadStateData
from ..dependencies import get_aggregator, get_checkpointer
from ..schemas.snapshots import ThreadStateSnapshot

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_pydantic(data: ThreadStateData) -> ThreadStateSnapshot:
    """Convert a Layer 1 ``ThreadStateData`` to a Pydantic wire model."""
    return ThreadStateSnapshot.model_validate(asdict(data))


@router.get("/threads/{thread_id}/state", response_model=ThreadStateSnapshot)
async def get_thread_state_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> ThreadStateSnapshot:
    """Return a complete thread state snapshot for client reconnection.

    The ``last_sequence`` field enables gap detection: the client discards
    any subsequent WebSocket events with ``sequence <= last_sequence``
    (ADR-011 section 2.3).
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    snapshot = await build_thread_state(
        db,
        thread=thread,
        aggregator=aggregator,
        checkpointer=checkpointer,
    )
    return _to_pydantic(snapshot)
