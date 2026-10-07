"""A resume that only asks again has still been applied.

LangGraph holds a resume's input writes against the checkpoint the run is
parked on and commits them when a superstep consumes them. A gate that asks
again on an answer which did not settle it consumes nothing, so the run stays
on the same checkpoint: the resume's action receipt is durable, but it is a
held write and the committed channels still name the action before it. Reading
only the committed channels reported the answer as a prior action, and a
recovery keyed on incorporation then redelivered an answer that had already
landed.

A real gate parks, re-parks and settles over a real ``AsyncSqliteSaver``, and
the evidence is read through a SECOND saver over the same file, so what is
asserted is what the store holds rather than what the run still had in hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START
from langgraph.types import Command, interrupt

from ...database import read_latest_checkpoint
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..action_receipts import GraphActionReceipt, control_action_payload_fingerprint
from ..checkpoint_evidence import (
    CheckpointEvidenceKind,
    classify_checkpoint_evidence,
)
from ..enums import ControlActionType

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from ..state import TeamState

_THREAD = "repark-evidence"
_READ_TIMEOUT_SECONDS = 10.0

#: The answer the gate accepts. Anything else leaves it parked, which is the
#: whole point: the resume applied, and the run did not move on.
_SETTLING_ANSWER = "approved"


def _receipt(dispatch_id: str, *, generation: int) -> GraphActionReceipt:
    return GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=_THREAD,
        action_id=f"action-{dispatch_id}",
        action_type=(
            ControlActionType.INGEST
            if generation == 1
            else ControlActionType.PERMISSION_RESPONSE_SUBMITTED
        ),
        payload_fingerprint=control_action_payload_fingerprint(
            {"dispatch": dispatch_id}
        ),
        dispatch_id=dispatch_id,
        run_revision=generation,
        writer_generation=generation,
    )


def _gate(state: TeamState) -> dict[str, str]:
    """Ask, and ask again until the answer settles the question.

    The re-park is the production shape: a gate handed a verdict it cannot act
    on raises a fresh interrupt rather than failing the run.
    """
    del state
    while (
        interrupt({"type": "plan_approval_request", "request_id": "repark-approval"})
        != _SETTLING_ANSWER
    ):
        pass
    return {"active_agent": "settled"}


def _resume(receipt: GraphActionReceipt, answer: str) -> Command[str]:
    """The shape a dispatched resume carries: the answer, bound to its receipt."""
    return Command[str](
        resume=answer,
        update={
            "graph_action_receipts": {
                receipt.dispatch_id: receipt.model_dump(mode="json")
            },
            "active_graph_action_receipt": receipt.model_dump(mode="json"),
        },
    )


def _graph(saver: AsyncSqliteSaver) -> Any:
    builder = new_state_graph()
    add_test_node(builder, "gate", _gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    return compile_test_graph(builder, checkpointer=saver)


def _ingest_input(receipt: GraphActionReceipt) -> dict[str, Any]:
    return {
        "thread_id": _THREAD,
        "active_agent": "worker",
        "active_graph_action_receipt": receipt.model_dump(mode="json"),
        "graph_action_receipts": {receipt.dispatch_id: receipt.model_dump(mode="json")},
    }


@pytest.mark.asyncio
async def test_a_resume_that_only_parks_again_reads_as_incorporated(
    tmp_path: Path,
) -> None:
    """The answer the gate could not act on is still the action that landed."""
    path = str(tmp_path / "repark.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": _THREAD}}
    ingest = _receipt("ingest", generation=1)
    reparking = _receipt("resume-repark", generation=2)
    undelivered = _receipt("resume-never-sent", generation=3)

    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        await saver.setup()
        graph = _graph(saver)
        await graph.ainvoke(_ingest_input(ingest), config)
        await graph.ainvoke(_resume(reparking, "revise"), config)

    async with AsyncSqliteSaver.from_conn_string(path) as reader:
        stored = await reader.aget_tuple(cast("Any", config))
        assert stored is not None
        committed = stored.checkpoint["channel_values"]
        # The reason a committed-only read was wrong: the superstep that would
        # have taken the resume's receipt never ran.
        assert committed["active_graph_action_receipt"]["dispatch_id"] == "ingest"

        latest = await read_latest_checkpoint(
            reader, _THREAD, timeout=_READ_TIMEOUT_SECONDS
        )
        evidence = classify_checkpoint_evidence(latest, reparking)
        assert evidence.kind is CheckpointEvidenceKind.INTERRUPTED
        assert evidence.incorporated is True
        assert evidence.checkpoint_id == stored.checkpoint["id"]

        # The held writes must not make every receipt look applied: an action
        # this thread never received is still the prior-action answer that
        # lets recovery deliver it.
        never_sent = classify_checkpoint_evidence(latest, undelivered)
        assert never_sent.kind is CheckpointEvidenceKind.PRIOR_ACTION
        assert never_sent.incorporated is False


@pytest.mark.asyncio
async def test_the_settling_resume_commits_what_the_re_park_only_held(
    tmp_path: Path,
) -> None:
    """The held receipt is the same one the next superstep commits.

    Reading a held write as incorporated is only sound if the store really
    does commit it, so the same run is carried through to the answer that
    settles the gate and the committed channels are compared against what the
    evidence claimed one step earlier.
    """
    path = str(tmp_path / "settled.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": _THREAD}}
    ingest = _receipt("ingest", generation=1)
    reparking = _receipt("resume-repark", generation=2)

    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        await saver.setup()
        graph = _graph(saver)
        await graph.ainvoke(_ingest_input(ingest), config)
        await graph.ainvoke(_resume(reparking, "revise"), config)
        held = classify_checkpoint_evidence(
            await read_latest_checkpoint(saver, _THREAD, timeout=_READ_TIMEOUT_SECONDS),
            reparking,
        )
        assert held.incorporated is True

        settling = _receipt("resume-settles", generation=3)
        await graph.ainvoke(_resume(settling, _SETTLING_ANSWER), config)

    async with AsyncSqliteSaver.from_conn_string(path) as reader:
        stored = await reader.aget_tuple(cast("Any", config))
        assert stored is not None
        committed = stored.checkpoint["channel_values"]
        assert committed["active_graph_action_receipt"] == settling.model_dump(
            mode="json"
        )
        # Both resumes are in the committed union, so the receipt the evidence
        # read off a held write was the one that landed and not a guess.
        assert set(committed["graph_action_receipts"]) == {
            "ingest",
            "resume-repark",
            "resume-settles",
        }
        assert committed["active_agent"] == "settled"


@pytest.mark.asyncio
async def test_a_receipt_write_the_store_cannot_parse_is_not_read_as_evidence(
    tmp_path: Path,
) -> None:
    """Held writes come out of untrusted storage like every other value here.

    The fold reads what the next superstep will commit, so a write whose shape
    no reducer accepts must end the read as an incompatible checkpoint rather
    than be quietly skipped and answered on the committed channels alone.
    """
    path = str(tmp_path / "corrupt.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": _THREAD}}
    ingest = _receipt("ingest", generation=1)
    reparking = _receipt("resume-repark", generation=2)

    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        await saver.setup()
        graph = _graph(saver)
        await graph.ainvoke(_ingest_input(ingest), config)
        await graph.ainvoke(_resume(reparking, "revise"), config)
        parked = await saver.aget_tuple(cast("Any", config))
        assert parked is not None
        await saver.aput_writes(
            cast("Any", parked.config),
            [("active_graph_action_receipt", {"schema_version": "nonsense"})],
            "corrupting-task",
        )

    async with AsyncSqliteSaver.from_conn_string(path) as reader:
        evidence = classify_checkpoint_evidence(
            await read_latest_checkpoint(
                reader, _THREAD, timeout=_READ_TIMEOUT_SECONDS
            ),
            reparking,
        )
        assert evidence.kind is CheckpointEvidenceKind.INCOMPATIBLE
        assert evidence.incorporated is False
