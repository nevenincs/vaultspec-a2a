"""Checkpoint-backed dispatch application receipt emission."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..ipc.schemas import DispatchApplicationReceiptPayload
from ..thread.action_receipts import GRAPH_ACTION_VERB
from ..thread.checkpoint_evidence import (
    CheckpointEvidenceKind,
    read_checkpoint_evidence,
)
from ._run_registry import RunScopedRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from .ipc import WorkerBridge

__all__ = ["DispatchReceiptReporter"]

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
        self._reported = RunScopedRegistry[str]()

    def forget(self, thread_id: str) -> None:
        """Drop what this thread reported, once its run is over."""
        self._reported.drop(thread_id)

    async def report(
        self,
        req: DispatchRequest,
        checkpointer: Checkpointer,
        bridge: WorkerBridge,
        checkpoint_read_timeout_seconds: float,
        dispatch_log_extra: Callable[..., dict[str, Any]],
    ) -> None:
        """Report incorporation after reading its committed checkpoint proof."""
        if not req.requires_graph_receipt:
            return
        if self._reported.get(req.thread_id) == req.dispatch_id:
            return
        try:
            receipt = req.require_graph_action_receipt()
            # The same evidence the gateway reads before it settles the
            # action. A resume that asks again commits no superstep, so its
            # receipt is only a write held against the parked checkpoint;
            # reading committed channels alone would never report it, and
            # recovery would redeliver an answer the run already consumed.
            evidence = await read_checkpoint_evidence(
                checkpointer,
                receipt,
                timeout_seconds=checkpoint_read_timeout_seconds,
            )
            if evidence.kind is CheckpointEvidenceKind.UNAVAILABLE:
                # A read that failed says nothing about the checkpoint, and if
                # both reads a run makes fail the gateway never settles the
                # action, so this is a failure to report, not a receipt that
                # is merely not due yet.
                logger.warning(
                    "Could not read the checkpoint to prove dispatch %s for "
                    "thread %s was applied",
                    req.dispatch_id,
                    req.thread_id,
                    extra=dispatch_log_extra(
                        req,
                        action="dispatch_application_receipt_failed",
                    ),
                )
                return
            if not evidence.incorporated or evidence.checkpoint_id is None:
                logger.debug(
                    "No committed loop checkpoint carries dispatch %s for "
                    "thread %s yet; the application receipt is not due",
                    req.dispatch_id,
                    req.thread_id,
                )
                return
            self._reported.register(req.thread_id, req.dispatch_id)
            await bridge.send_event(
                req.thread_id,
                DispatchApplicationReceiptPayload(
                    dispatch_id=req.dispatch_id,
                    action=GRAPH_ACTION_VERB[receipt.action_type],
                    graph_action_receipt=receipt,
                    checkpoint_id=evidence.checkpoint_id,
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
