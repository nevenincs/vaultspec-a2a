"""Thread state snapshot assembly service.

Extracts the 95-line orchestration from the ``/threads/{id}/state``
endpoint into a testable, protocol-agnostic function.  The route
handler validates input and converts the result to a Pydantic wire model.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..control.projection import (
    apply_checkpoint_projection,
    enrich_snapshot_from_durable_state,
    enrich_snapshot_from_execution_state,
)
from ..control.snapshot import (
    MinimalState,
    enrich_snapshot_from_state,
    load_checkpoint_history_depth,
)
from ..database import get_thread
from ..thread.enums import RepairStatus
from ..thread.snapshots import (
    ThreadStateData,
    finalize_snapshot_replay_status,
    project_checkpoint_tuple,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.checkpoints import Checkpointer
    from ..streaming.aggregator import EventAggregator

__all__ = ["build_thread_state"]

logger = logging.getLogger(__name__)


async def build_thread_state(
    db: AsyncSession,
    *,
    thread_id: str,
    aggregator: EventAggregator,
    checkpointer: Checkpointer,
) -> ThreadStateData | None:
    """Assemble a complete thread state snapshot for client reconnection.

    Returns a ``ThreadStateData`` (Layer 1 dataclass), or ``None`` if the
    thread does not exist.  Does **not** raise ``HTTPException`` — the route
    handler owns HTTP response mapping.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return None
    last_seq = aggregator.get_sequence(thread_id)

    snapshot = ThreadStateData(
        thread_id=thread_id,
        status=thread.status,
        last_sequence=last_seq,
        repair_status=thread.repair_status,
        execution_readiness=thread.execution_readiness,
        approval_status=thread.approval_status,
        approval_request_id=thread.approval_request_id,
    )
    snapshot = await enrich_snapshot_from_durable_state(
        db, thread=thread, snapshot=snapshot
    )
    checkpoint_loaded = False
    checkpoint_present = False
    checkpoint_error = False

    try:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config),
            timeout=10.0,
        )
        if checkpoint_tuple is not None:
            checkpoint_present = True
            history_depth: int | None = None
            try:
                history_depth = await asyncio.wait_for(
                    load_checkpoint_history_depth(checkpointer, config),
                    timeout=10.0,
                )
            except TimeoutError:
                if "checkpoint_history_timeout" not in snapshot.degraded_reasons:
                    snapshot.degraded_reasons.append("checkpoint_history_timeout")
            except Exception:
                if "checkpoint_history_unavailable" not in snapshot.degraded_reasons:
                    snapshot.degraded_reasons.append("checkpoint_history_unavailable")
            projection = project_checkpoint_tuple(
                checkpoint_tuple,
                thread_id=thread_id,
                history_depth=history_depth,
            )

            minimal_state = MinimalState(
                values=projection.channel_values,
                cfg=projection.config,
            )
            snapshot = enrich_snapshot_from_state(
                snapshot,
                minimal_state,
                aggregator=aggregator,
            )
            snapshot = apply_checkpoint_projection(snapshot, projection)
            checkpoint_loaded = True
    except TimeoutError:
        logger.warning(
            "Timed out loading checkpoint for thread %s after 10s; "
            "returning partial snapshot",
            thread_id,
        )
        checkpoint_error = True
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_timeout")
        snapshot.replay_status = "unknown"
        snapshot.repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value
    except Exception:
        logger.warning(
            "Could not load checkpoint for thread %s; returning partial snapshot",
            thread_id,
            exc_info=True,
        )
        checkpoint_error = True
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_unavailable")
        snapshot.replay_status = "unknown"
        snapshot.repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value

    snapshot = await enrich_snapshot_from_execution_state(
        db,
        thread=thread,
        snapshot=snapshot,
        checkpoint_present=checkpoint_present,
        checkpoint_id=snapshot.checkpoint_id,
    )

    return finalize_snapshot_replay_status(
        snapshot,
        checkpoint_loaded=checkpoint_loaded,
        checkpoint_present=checkpoint_present,
        checkpoint_error=checkpoint_error,
        thread_status=thread.status,
    )
