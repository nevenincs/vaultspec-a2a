"""A run's own staged input is evidence of that run, not of a foreign one.

LangGraph commits a checkpoint for a run's input before the first superstep
distributes it into the state's channels. A process killed in that window
leaves a checkpoint whose committed channels carry no action receipt at all,
and reading those channels alone called the run's own first input foreign to
the action that sent it - so the redelivered first ingest was refused instead
of continued.

The checkpoint under test is one a real compiled graph wrote, replayed into
the scenario's own store through the saver's own API, and the readings are
taken through a real SQLite saver.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ...database import read_latest_checkpoint
from ...tests._checkpoint_seeding import real_input_checkpoint
from ..action_receipts import GraphActionReceipt, control_action_payload_fingerprint
from ..checkpoint_evidence import CheckpointEvidenceKind, classify_checkpoint_evidence
from ..enums import ControlActionType

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_THREAD = "input-checkpoint-evidence"
_READ_TIMEOUT_SECONDS = 10.0


def _receipt(
    dispatch_id: str, *, generation: int, thread_id: str
) -> GraphActionReceipt:
    return GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=thread_id,
        action_id=f"action-{dispatch_id}",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint(
            {"dispatch": dispatch_id}
        ),
        dispatch_id=dispatch_id,
        run_revision=generation,
        writer_generation=generation,
    )


def _ingest_input(receipt: GraphActionReceipt) -> dict[str, Any]:
    """The input an ingest dispatch carries, receipts included."""
    return {
        "thread_id": receipt.thread_id,
        "active_agent": "worker",
        "active_graph_action_receipt": receipt.model_dump(mode="json"),
        "graph_action_receipts": {receipt.dispatch_id: receipt.model_dump(mode="json")},
    }


async def _seed_crashed_input(saver: Any, receipt: GraphActionReceipt) -> str:
    """Leave the store holding only what the crash window had committed."""
    checkpoint, metadata = await real_input_checkpoint(_ingest_input(receipt))
    config: RunnableConfig = {
        "configurable": {"thread_id": receipt.thread_id, "checkpoint_ns": ""}
    }
    await saver.aput(config, checkpoint, metadata, checkpoint["channel_versions"])
    return checkpoint["id"]


@pytest.mark.asyncio
async def test_the_staged_input_names_the_action_that_sent_it(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The crash window's checkpoint is this action's, part-way, and not applied."""
    receipt = _receipt("ingest", generation=1, thread_id=_THREAD)
    checkpoint_id = await _seed_crashed_input(checkpointer, receipt)

    stored = await checkpointer.aget_tuple(
        cast("Any", {"configurable": {"thread_id": _THREAD}})
    )
    assert stored is not None
    # The reason a committed-only read was wrong: the superstep that would
    # have taken the input's receipt never ran.
    assert "active_graph_action_receipt" not in stored.checkpoint["channel_values"]

    evidence = classify_checkpoint_evidence(
        await read_latest_checkpoint(
            checkpointer, _THREAD, timeout=_READ_TIMEOUT_SECONDS
        ),
        receipt,
    )

    assert evidence.kind is CheckpointEvidenceKind.PENDING
    assert evidence.checkpoint_id == checkpoint_id
    # Nothing was committed by a superstep, so the action is not yet applied:
    # the gateway must not settle it off this reading.
    assert evidence.incorporated is False


@pytest.mark.asyncio
async def test_an_action_the_staged_input_does_not_name_is_still_a_new_turn(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Reading the staged input must not make every arriving action look applied."""
    staged = _receipt("ingest", generation=1, thread_id=_THREAD)
    await _seed_crashed_input(checkpointer, staged)
    later = _receipt("follow-up", generation=2, thread_id=_THREAD)

    evidence = classify_checkpoint_evidence(
        await read_latest_checkpoint(
            checkpointer, _THREAD, timeout=_READ_TIMEOUT_SECONDS
        ),
        later,
    )

    assert evidence.kind is CheckpointEvidenceKind.PRIOR_ACTION
    assert evidence.incorporated is False
