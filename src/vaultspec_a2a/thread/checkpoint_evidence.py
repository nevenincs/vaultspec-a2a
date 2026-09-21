"""One bounded interpretation of current durable graph-action evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

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


def _incompatible(checkpoint_id: str | None) -> CheckpointEvidence:
    return CheckpointEvidence(CheckpointEvidenceKind.INCOMPATIBLE, checkpoint_id, False)


def _checkpoint_values(
    checkpoint: Any, requested_checkpoint_id: str | None
) -> tuple[str, dict[str, object]] | CheckpointEvidence:
    # Durable storage is untrusted despite the saver's declared TypedDict.
    checkpoint_id_raw = cast("object", checkpoint.checkpoint.get("id"))
    if not isinstance(checkpoint_id_raw, str) or not checkpoint_id_raw:
        return _incompatible(None)
    if (
        requested_checkpoint_id is not None
        and checkpoint_id_raw != requested_checkpoint_id
    ):
        return _incompatible(checkpoint_id_raw)
    values_raw = cast("object", checkpoint.checkpoint.get("channel_values", {}))
    metadata_raw = cast("object", checkpoint.metadata)
    if not isinstance(values_raw, dict) or not isinstance(metadata_raw, dict):
        return _incompatible(checkpoint_id_raw)
    return checkpoint_id_raw, cast("dict[str, object]", values_raw)


def _action_evidence(
    values: dict[str, object], receipt: GraphActionReceipt, checkpoint_id: str
) -> CheckpointEvidence | None:
    try:
        active = GraphActionReceipt.model_validate(
            values.get("active_graph_action_receipt")
        )
    except ValidationError:
        return _incompatible(checkpoint_id)
    if active.thread_id != receipt.thread_id:
        return _incompatible(checkpoint_id)
    incorporated_raw = values.get("graph_action_receipts")
    if not isinstance(incorporated_raw, dict):
        return _incompatible(checkpoint_id)
    incorporated = cast("dict[str, object]", incorporated_raw)
    if incorporated.get(active.dispatch_id) != active.model_dump(mode="json"):
        return _incompatible(checkpoint_id)
    if active != receipt:
        kind = (
            CheckpointEvidenceKind.PRIOR_ACTION
            if active.writer_generation < receipt.writer_generation
            else CheckpointEvidenceKind.INCOMPATIBLE
        )
        return CheckpointEvidence(kind, checkpoint_id, False)
    return None


def _completion_evidence(
    values: dict[str, object], receipt: GraphActionReceipt, checkpoint_id: str
) -> CheckpointEvidence | None:
    completions = values.get("graph_completion_receipts")
    if completions is not None and not isinstance(completions, dict):
        return _incompatible(checkpoint_id)
    if not isinstance(completions, dict) or receipt.dispatch_id not in completions:
        return None
    try:
        completion = GraphCompletionReceipt.model_validate(
            completions[receipt.dispatch_id]
        )
    except ValidationError:
        return _incompatible(checkpoint_id)
    if completion.action != receipt:
        return _incompatible(checkpoint_id)
    return CheckpointEvidence(CheckpointEvidenceKind.COMPLETED, checkpoint_id, True)


def _pending_evidence(
    checkpoint: Any, checkpoint_id: str, incorporated: bool
) -> CheckpointEvidence:
    writes = checkpoint.pending_writes
    if writes is not None and any(
        not isinstance(cast("object", write), tuple | list)
        or len(write) != 3
        or not isinstance(cast("object", write[1]), str)
        for write in writes
    ):
        return _incompatible(checkpoint_id)
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
    parsed = _checkpoint_values(checkpoint, requested_checkpoint_id)
    if isinstance(parsed, CheckpointEvidence):
        return parsed
    current_checkpoint_id, values = parsed
    action_evidence = _action_evidence(values, receipt, current_checkpoint_id)
    if action_evidence is not None:
        return action_evidence
    completion_evidence = _completion_evidence(values, receipt, current_checkpoint_id)
    if completion_evidence is not None:
        return completion_evidence
    incorporated = checkpoint.metadata.get("source") == "loop"
    return _pending_evidence(checkpoint, current_checkpoint_id, incorporated)
