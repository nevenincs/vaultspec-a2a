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


class DispatchReceiptReporter:
    """Report each dispatch's incorporation to the gateway exactly once.

    A run reports incorporation from the first committed checkpoint of its own
    loop, which is the earliest moment the proof exists, and again when it
    settles. Both are the same report about the same dispatch, so the first
    one that finds its proof is the one that is sent: the gateway learns of
    the incorporation while the run is still executing rather than only at the
    end, and learns of it once.

    The reported dispatch is remembered per thread, and its owner drops the
    entry when the run's control closes, so nothing accumulates across runs.
    """

    def __init__(self) -> None:
        self._reported: dict[str, str] = {}

    def forget(self, thread_id: str) -> None:
        """Drop what this thread reported, once its run is over."""
        self._reported.pop(thread_id, None)

    async def report(
        self,
        req: DispatchRequest,
        checkpointer: Checkpointer,
        bridge: WorkerBridge,
        checkpoint_read_timeout_seconds: float,
        dispatch_log_extra: Callable[..., dict[str, Any]],
    ) -> None:
        """Report incorporation after reading its committed checkpoint proof."""
        if req.action != "ingest" and req.action != "resume":
            return
        if self._reported.get(req.thread_id) == req.dispatch_id:
            return
        try:
            receipt = req.require_graph_action_receipt()
            checkpoint = await asyncio.wait_for(
                checkpointer.aget_tuple({"configurable": {"thread_id": req.thread_id}}),
                timeout=checkpoint_read_timeout_seconds,
            )
            if checkpoint is None or checkpoint.metadata.get("source") != "loop":
                logger.debug(
                    "No committed loop checkpoint yet for thread %s; the "
                    "dispatch application receipt is not due",
                    req.thread_id,
                )
                return
            values = checkpoint.checkpoint.get("channel_values", {})
            receipts: object = values.get("graph_action_receipts")
            if not isinstance(receipts, dict):
                return
            if cast("dict[str, object]", receipts).get(
                req.dispatch_id
            ) != receipt.model_dump(mode="json"):
                return
            self._reported[req.thread_id] = req.dispatch_id
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
