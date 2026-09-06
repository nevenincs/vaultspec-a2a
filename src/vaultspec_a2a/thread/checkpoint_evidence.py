"""One bounded interpretation of current durable graph-action evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import ValidationError

from .action_receipts import GraphActionReceipt, GraphCompletionReceipt

if TYPE_CHECKING:
    from ..database.checkpoints import Checkpointer


class CheckpointEvidenceKind(StrEnum):
    ABSENT = "checkpoint_absent"
    PRIOR_ACTION = "prior_action_checkpoint"
    PENDING = "checkpoint_pending"
    COMPLETED = "checkpoint_completed"
    INTERRUPTED = "checkpoint_interrupted"
    FAILED = "checkpoint_failed"
    INCOMPATIBLE = "incompatible_checkpoint"
    UNAVAILABLE = "checkpoint_unavailable"


@dataclass(frozen=True, slots=True)
class CheckpointEvidence:
    kind: CheckpointEvidenceKind
    checkpoint_id: str | None
    incorporated: bool


async def read_checkpoint_evidence(
    checkpointer: Checkpointer,
    receipt: GraphActionReceipt,
    *,
    timeout_seconds: float,
    checkpoint_id: str | None = None,
) -> CheckpointEvidence:
    """Read terminal truth without compiling providers or guessing scheduled work."""
    requested_checkpoint_id = checkpoint_id
    configurable = {"thread_id": receipt.thread_id}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    try:
        checkpoint = await asyncio.wait_for(
            checkpointer.aget_tuple({"configurable": configurable}),
            timeout=timeout_seconds,
        )
    except Exception:
        return CheckpointEvidence(CheckpointEvidenceKind.UNAVAILABLE, None, False)
    if checkpoint is None:
        return CheckpointEvidence(CheckpointEvidenceKind.ABSENT, None, False)
    checkpoint_id = checkpoint.checkpoint.get("id")
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        return CheckpointEvidence(CheckpointEvidenceKind.INCOMPATIBLE, None, False)
    if requested_checkpoint_id is not None and checkpoint_id != requested_checkpoint_id:
        return CheckpointEvidence(
            CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
        )
    values = checkpoint.checkpoint.get("channel_values", {})
    if not isinstance(values, dict) or not isinstance(checkpoint.metadata, dict):
        return CheckpointEvidence(
            CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
        )
    try:
        active = GraphActionReceipt.model_validate(
            values.get("active_graph_action_receipt")
        )
    except ValidationError:
        return CheckpointEvidence(
            CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
        )
    if active.thread_id != receipt.thread_id:
        return CheckpointEvidence(
            CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
        )
    incorporated_values = values.get("graph_action_receipts")
    if not isinstance(incorporated_values, dict) or incorporated_values.get(
        active.dispatch_id
    ) != active.model_dump(mode="json"):
        return CheckpointEvidence(
            CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
        )
    if active != receipt:
        kind = (
            CheckpointEvidenceKind.PRIOR_ACTION
            if active.writer_generation < receipt.writer_generation
            else CheckpointEvidenceKind.INCOMPATIBLE
        )
        return CheckpointEvidence(kind, checkpoint_id, False)
    incorporated = checkpoint.metadata.get("source") == "loop"
    completions = values.get("graph_completion_receipts")
    if completions is not None and not isinstance(completions, dict):
        return CheckpointEvidence(
            CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
        )
    if isinstance(completions, dict) and receipt.dispatch_id in completions:
        try:
            completion = GraphCompletionReceipt.model_validate(
                completions[receipt.dispatch_id]
            )
        except ValidationError:
            return CheckpointEvidence(
                CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
            )
        if completion.action != receipt:
            return CheckpointEvidence(
                CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
            )
        return CheckpointEvidence(CheckpointEvidenceKind.COMPLETED, checkpoint_id, True)
    writes = checkpoint.pending_writes
    if writes is not None and any(
        not isinstance(write, (tuple, list))
        or len(write) != 3
        or not isinstance(write[1], str)
        for write in writes
    ):
        return CheckpointEvidence(
            CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False
        )
    channels = {write[1] for write in writes or ()}
    if "__error__" in channels:
        return CheckpointEvidence(
            CheckpointEvidenceKind.FAILED, checkpoint_id, incorporated
        )
    if "__interrupt__" in channels:
        return CheckpointEvidence(
            CheckpointEvidenceKind.INTERRUPTED, checkpoint_id, incorporated
        )
    return CheckpointEvidence(
        CheckpointEvidenceKind.PENDING, checkpoint_id, incorporated
    )
