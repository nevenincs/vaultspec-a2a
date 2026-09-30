"""A parked run survives every resume delivered against its checkpoint.

Real executors resume real graphs over a real ``AsyncSqliteSaver`` and relay
through a real in-process gateway. A resume carries its action receipt into
the graph as an input write, and LangGraph holds every input write against the
checkpoint the run is parked on until a superstep consumes it. Two approvals in
one worker turn, and one resume delivered twice, therefore both put two
receipts on the same channel in the same step. Neither may fail the run, and
neither may leave the thread's durable state unreadable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...api.tests.clarification_harness import new_state_graph
from ...control.accepted_input import freeze_accepted_input
from ...control.permission_dispatch import permission_resume_value
from ...graph.nodes.worker import _interrupt_permission_callback
from ...providers.team_selection import model_assignment_digest
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
    merge_active_graph_action_receipt,
)
from ...thread.enums import ControlActionType
from ..executor import Executor
from .test_executor import (
    _current_ingest_dispatch,
    _make_bridge,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...ipc.schemas import DispatchRequest
    from ..graph_lifecycle import RegisteredCompiledGraph

_OPTIONS: list[dict[str, Any]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


def _install_two_permission_graph(
    executor: Executor, request: DispatchRequest, answered: dict[str, str]
) -> RegisteredCompiledGraph:
    """Compile a real graph whose single node asks for two tool permissions.

    The node calls the production permission callback, so the interrupt
    payloads, their request ids and the option validation are the ones a
    worker turn really raises. Answers are recorded per call rather than
    appended, because an interrupted task replays its node body from the top
    on every resume and an append would record the replay rather than the
    answers the turn obtained.
    """

    async def worker_node(state: Any) -> dict[str, Any]:
        del state
        answered["Edit"] = await _interrupt_permission_callback(
            "Edit", {"path": "a.py"}, _OPTIONS
        )
        answered["Bash"] = await _interrupt_permission_callback(
            "Bash", {"command": "pytest"}, _OPTIONS
        )
        return {"messages": [AIMessage(content="done")], "next": "FINISH"}

    builder = new_state_graph()
    builder.add_node("worker", worker_node)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(
        checkpointer=executor._checkpointer
    )
    executor.register_compiled_graph(
        request.thread_id,
        (
            request.require_graph_definition().team_id,
            request.workspace_root,
            request.autonomous,
            model_assignment_digest(request.model_assignment),
            request.require_graph_definition().digest(),
        ),
        graph,
    )
    return graph


def _resume_dispatch(
    ingest: DispatchRequest,
    *,
    ordinal: int,
    resume_value: object,
) -> DispatchRequest:
    """One accepted resume action, identified as the gateway identifies it."""
    request = ingest.model_copy(
        update={
            "action": "resume",
            "dispatch_id": f"{ingest.thread_id}-resume-{ordinal}",
            "content": None,
            "option_id": resume_value,
            "graph_action_receipt": None,
        }
    )
    accepted = freeze_accepted_input(request, intent={"option_id": resume_value})
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=request.thread_id,
        action_id=f"{request.thread_id}-resume-action-{ordinal}",
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        payload_fingerprint=control_action_payload_fingerprint(accepted),
        dispatch_id=request.dispatch_id,
        run_revision=ordinal,
        writer_generation=ordinal + 1,
    )
    return request.model_copy(update={"graph_action_receipt": receipt})


def _answer_for(parked: Any) -> object:
    """The typed answer a client sends for the request now on display."""
    payload = parked.value
    return permission_resume_value(
        "permission_request",
        "allow_once",
        None,
        request_id=payload["request_id"],
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_two_approvals_in_one_worker_turn_both_apply() -> None:
    """A turn needing a second tool approval finishes it."""
    thread_id = "resume-two-approvals"
    answered: dict[str, str] = {}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        bridge = _make_bridge()
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            ingest = _current_ingest_dispatch(thread_id)
            graph = _install_two_permission_graph(executor, ingest, answered)
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            await executor.handle_dispatch(ingest)
            first_park = (await graph.aget_state(config)).interrupts
            assert [park.value["tool_name"] for park in first_park] == ["Edit"]

            await executor.handle_dispatch(
                _resume_dispatch(
                    ingest, ordinal=1, resume_value=_answer_for(first_park[0])
                )
            )
            second_park = (await graph.aget_state(config)).interrupts
            assert [park.value["tool_name"] for park in second_park] == ["Bash"]

            second = _resume_dispatch(
                ingest, ordinal=2, resume_value=_answer_for(second_park[0])
            )
            await executor.handle_dispatch(second)

            # The run finished, so both calls were answered and neither
            # resume was refused by the channel the receipts land on.
            final = await graph.aget_state(config)
            assert final.next == ()
            assert final.interrupts == ()
            assert answered == {"Edit": "allow_once", "Bash": "allow_once"}

            # The checkpoint names the action that last reached the graph,
            # and holds an incorporation receipt for every action that did.
            durable = await checkpointer.aget_tuple(config)
            assert durable is not None
            values = durable.checkpoint["channel_values"]
            receipt = second.require_graph_action_receipt()
            assert values["active_graph_action_receipt"] == receipt.model_dump(
                mode="json"
            )
            assert set(values["graph_action_receipts"]) == {
                ingest.dispatch_id,
                f"{thread_id}-resume-1",
                f"{thread_id}-resume-2",
            }
        finally:
            await bridge.close()
            await executor.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_a_resume_redelivered_after_its_turn_died_leaves_state_readable() -> None:
    """A redelivered resume neither fails the run nor wedges its state.

    The worker that took the resume parks again on the turn's second request
    and then dies before the gateway learns the action applied, so the gateway
    hands the same action to a restarted worker. The redelivery lands on the
    same parked checkpoint as the first delivery.
    """
    thread_id = "resume-redelivered"
    answered: dict[str, str] = {}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        ingest = _current_ingest_dispatch(thread_id)
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        before_bridge = _make_bridge()
        before = Executor(checkpointer=checkpointer, bridge=before_bridge)
        try:
            graph = _install_two_permission_graph(before, ingest, answered)
            await before.handle_dispatch(ingest)
            parked = (await graph.aget_state(config)).interrupts
            resume = _resume_dispatch(
                ingest, ordinal=1, resume_value=_answer_for(parked[0])
            )
            await before.handle_dispatch(resume)
            assert answered == {"Edit": "allow_once"}
            assert [
                park.value["tool_name"]
                for park in (await graph.aget_state(config)).interrupts
            ] == ["Bash"]
        finally:
            await before_bridge.close()
            await before.shutdown()

        after_bridge = _make_bridge()
        after = Executor(checkpointer=checkpointer, bridge=after_bridge)
        try:
            graph = _install_two_permission_graph(after, ingest, answered)
            await after.handle_dispatch(resume)

            # The thread's durable state is still readable, which is what the
            # gateway, recovery and every status read depend on, and the run
            # is still waiting on the request no human has answered.
            state = await graph.aget_state(config)
            assert [park.value["tool_name"] for park in state.interrupts] == ["Bash"]

            # The redelivery was applied, not dropped: its receipt is held
            # against the checkpoint the run is parked on, alongside the one
            # the first delivery left there. The channel that carries them
            # reduces, so the pair is a merge rather than a refusal, and the
            # receipt that survives names one real accepted action.
            durable = await checkpointer.aget_tuple(config)
            assert durable is not None
            receipt = resume.require_graph_action_receipt().model_dump(mode="json")
            held = [
                write[2]
                for write in durable.pending_writes or ()
                if write[1] == "active_graph_action_receipt"
            ]
            assert held == [receipt, receipt]
            assert merge_active_graph_action_receipt(held[0], held[1]) == receipt
        finally:
            await after_bridge.close()
            await after.shutdown()
