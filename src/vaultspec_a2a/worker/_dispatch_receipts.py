"""Checkpoint-backed dispatch application receipt emission."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from ..ipc.schemas import DispatchApplicationReceiptPayload

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from .ipc import WorkerBridge

logger = logging.getLogger("vaultspec_a2a.worker.executor")


async def emit_dispatch_application_receipt(
    req: DispatchRequest,
    checkpointer: Checkpointer,
    bridge: WorkerBridge,
    checkpoint_read_timeout_seconds: float,
    dispatch_log_extra: Callable[..., dict[str, Any]],
) -> None:
    """Report incorporation only after reading its committed checkpoint proof."""
    if req.action != "ingest" and req.action != "resume":
        return
    try:
        receipt = req.require_graph_action_receipt()
        checkpoint = await asyncio.wait_for(
            checkpointer.aget_tuple({"configurable": {"thread_id": req.thread_id}}),
            timeout=checkpoint_read_timeout_seconds,
        )
        if checkpoint is None or checkpoint.metadata.get("source") != "loop":
            return
        values = checkpoint.checkpoint.get("channel_values", {})
        receipts: object = values.get("graph_action_receipts")
        if not isinstance(receipts, dict):
            return
        if cast("dict[str, object]", receipts).get(
            req.dispatch_id
        ) != receipt.model_dump(mode="json"):
            return
        await bridge.send_event(
            req.thread_id,
            DispatchApplicationReceiptPayload(
                dispatch_id=req.dispatch_id,
                action=req.action,
                graph_action_receipt=receipt,
                checkpoint_id=checkpoint.checkpoint["id"],
            ).model_dump(mode="json"),
        )
    except Exception:
        # Receipt transport must never abort graph execution after it began.
        logger.warning(
            "Could not queue dispatch application receipt",
            exc_info=True,
            extra=dispatch_log_extra(
                req,
                action="dispatch_application_receipt_failed",
            ),
        )
