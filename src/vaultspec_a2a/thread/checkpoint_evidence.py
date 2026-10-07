"""One bounded interpretation of current durable graph-action evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.serde.types import ERROR
from pydantic import ValidationError

from .action_receipts import (
    ACTIVE_RECEIPT_CHANNEL,
    COMPLETION_RECEIPTS_CHANNEL,
    INCORPORATED_RECEIPTS_CHANNEL,
    GraphActionReceipt,
    GraphCompletionReceipt,
    merge_active_graph_action_receipt,
    merge_graph_action_receipts,
)
from .snapshots import unanswered_interrupt_values

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ..database.checkpoints import Checkpointer

__all__ = [
    "CheckpointEvidence",
    "CheckpointEvidenceKind",
    "read_checkpoint_evidence",
]

# The channels a dispatch's receipt is written to, each with the reducer its
# state field declares. Folding a pending write with the channel's own reducer
# is what makes this read the value the next superstep will commit rather than
# a second opinion about it.
_RECEIPT_REDUCERS: dict[str, Callable[[Any, Any], object]] = {
    ACTIVE_RECEIPT_CHANNEL: merge_active_graph_action_receipt,
    INCORPORATED_RECEIPTS_CHANNEL: merge_graph_action_receipts,
}

# The channel a run's input is staged in, and the metadata source of the
# checkpoint that holds it. LangGraph commits that checkpoint before the first
# superstep distributes the input into the state's own channels, so between the
# two a run's receipt is durable in the staging channel alone.
_INPUT_STAGING_CHANNEL = "__start__"
_INPUT_SOURCE = "input"


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
        active = GraphActionReceipt.model_validate(values.get(ACTIVE_RECEIPT_CHANNEL))
    except ValidationError:
        return _incompatible(checkpoint_id)
    if active.thread_id != receipt.thread_id:
        return _incompatible(checkpoint_id)
    incorporated_raw = values.get(INCORPORATED_RECEIPTS_CHANNEL)
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
    completions = values.get(COMPLETION_RECEIPTS_CHANNEL)
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


def _pending_writes(checkpoint: Any) -> list[tuple[str, object]] | None:
    """Return the checkpoint's held writes as channel/value pairs.

    ``None`` when the stored shape is not what the saver's type promises;
    durable storage is untrusted here as everywhere else in this module.
    """
    rows: list[tuple[str, object]] = []
    for write in checkpoint.pending_writes or ():
        if (
            not isinstance(cast("object", write), tuple | list)
            or len(write) != 3
            or not isinstance(cast("object", write[1]), str)
        ):
            return None
        rows.append((cast("str", write[1]), cast("object", write[2])))
    return rows


def _fold_pending_receipts(
    values: dict[str, object], writes: Sequence[tuple[str, object]]
) -> dict[str, object] | None:
    """Overlay the receipt writes held against this checkpoint onto its values.

    A resume that suspends again never advances the checkpoint: its receipt
    stays a write held against the checkpoint it answered, durably, while the
    committed channels still name the action before it. Reading the committed
    channels alone therefore reports an applied resume as a prior action, and
    a recovery keyed on incorporation redelivers an answer that already landed.

    ``None`` when a write or the value it folds onto is not the shape its
    channel takes, which the caller reads as an incompatible checkpoint.
    """
    folded = dict(values)
    for channel, value in writes:
        reducer = _RECEIPT_REDUCERS.get(channel)
        if reducer is None:
            continue
        existing = folded.get(channel, {})
        if not isinstance(existing, dict) or not isinstance(value, dict):
            return None
        try:
            folded[channel] = reducer(existing, value)
        except (ValidationError, ValueError):
            return None
    return folded


def _staged_input_receipts(values: dict[str, object]) -> list[tuple[str, object]]:
    """Return the receipt writes an input checkpoint stages but has not committed.

    A first ingest redelivered after a crash in that window used to be refused:
    the committed channels carry no receipt at all, which reads as a checkpoint
    belonging to some other action. The staged input is the same action's own,
    so it is folded in the way a pending write is, and the redelivery continues
    from the checkpoint instead of delivering the input a second time.
    """
    staged = values.get(_INPUT_STAGING_CHANNEL)
    if not isinstance(staged, dict):
        return []
    staged_values = cast("dict[str, object]", staged)
    return [
        (channel, staged_values[channel])
        for channel in _RECEIPT_REDUCERS
        if channel in staged_values
    ]


def _pending_evidence(
    writes: Sequence[tuple[str, object]],
    checkpoint_id: str,
    incorporated: bool,
    *,
    parked: bool,
) -> CheckpointEvidence:
    channels = {channel for channel, _ in writes}
    if ERROR in channels:
        return CheckpointEvidence(
            CheckpointEvidenceKind.FAILED, checkpoint_id, incorporated
        )
    if parked:
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
    checkpoint = await _read_checkpoint(
        checkpointer,
        receipt.thread_id,
        checkpoint_id,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(checkpoint, CheckpointEvidence):
        return checkpoint
    return _classify_checkpoint(
        checkpoint, receipt, requested_checkpoint_id=checkpoint_id
    )


async def _read_checkpoint(
    checkpointer: Checkpointer,
    thread_id: str,
    checkpoint_id: str | None,
    *,
    timeout_seconds: float,
) -> Any | CheckpointEvidence:
    """The stored checkpoint, or the evidence that stands in for not having one.

    A read that failed and a thread with nothing stored are both answers in
    themselves, and neither leaves anything to classify.
    """
    configurable = {"thread_id": thread_id}
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
    return checkpoint


def _classify_checkpoint(
    checkpoint: Any,
    receipt: GraphActionReceipt,
    *,
    requested_checkpoint_id: str | None,
) -> CheckpointEvidence:
    """What one stored checkpoint says about the action the receipt names."""
    parsed = _checkpoint_values(checkpoint, requested_checkpoint_id)
    if isinstance(parsed, CheckpointEvidence):
        return parsed
    current_checkpoint_id, values = parsed
    writes = _pending_writes(checkpoint)
    if writes is None:
        return _incompatible(current_checkpoint_id)
    source = checkpoint.metadata.get("source")
    staged = _staged_input_receipts(values) if source == _INPUT_SOURCE else []
    folded = _fold_pending_receipts(values, [*staged, *writes])
    if folded is None:
        return _incompatible(current_checkpoint_id)
    action_evidence = _action_evidence(folded, receipt, current_checkpoint_id)
    if action_evidence is not None:
        return action_evidence
    # Completion is read off the committed channels alone: a completion write
    # still held against a checkpoint means some other task parked the
    # superstep that would have committed it, so the run has not completed.
    completion_evidence = _completion_evidence(values, receipt, current_checkpoint_id)
    if completion_evidence is not None:
        return completion_evidence
    # Parked means a task is still asking: an answered fan-out branch's
    # interrupt write outlives its answer until the superstep commits, and on
    # its own it is work part-way, not a question waiting on anyone.
    return _pending_evidence(
        writes,
        current_checkpoint_id,
        source == "loop",
        parked=bool(unanswered_interrupt_values(checkpoint.pending_writes)),
    )
