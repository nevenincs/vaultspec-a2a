"""One vocabulary names an approval pause from the graph to the journal.

A plan gate and a document gate park on different interrupt kinds, and the
out-of-run verdict subscriber reaches a parked document gate through its journal
row alone. These tests drive the whole producer chain the gateway really runs -
the real gate node's ``interrupt()``, the real projection, the real emitter, the
real worker serialization, the real relay - and then read what the journal and
the document-approval lookup say about the pause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from langgraph.graph import END, START

from ...database import (
    get_permission_request,
    pending_document_approval_thread,
)
from ...graph.events import PermissionRequest
from ...graph.nodes.phase_gate import create_phase_gate_node
from ...graph.nodes.supervisor import create_plan_approval_node
from ...ipc.serializers import sequenced_to_dict
from ...streaming._interrupt_projection import emit_interrupt_events
from ...streaming.aggregator import RunEventProducer
from ...streaming.tests._relay_capture import relayed_events
from ...testing import (
    add_test_node,
    ainvoke_test_graph,
    compile_test_graph,
    new_state_graph,
    seed_accepted_thread,
)
from ...thread.enums import InterruptType
from ..event_handlers import RelayServices, relay_event

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_PROPOSAL_ID = "proposal-research-vocabulary"


def _gate_state(thread_id: str, **extra: Any) -> dict[str, Any]:
    """The run state a gate node needs to reach its own interrupt."""
    state: dict[str, Any] = {
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "messages": [],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "sse-reconnection",
        "token_usage": {},
    }
    state.update(extra)
    return state


async def _relayed_permission_payload(
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    node_name: str,
    node: Any,
    state: dict[str, Any],
) -> dict[str, object]:
    """Park on *node*'s real interrupt and return the payload the worker relays.

    The chain is the production one end to end: the gate node raises its own
    ``interrupt()``, ``emit_interrupt_events`` projects what the checkpoint
    holds, the run's event producer emits the frame, and
    ``sequenced_to_dict`` serializes exactly what the worker POSTs to the
    gateway's internal relay.
    """
    builder = new_state_graph()
    add_test_node(builder, node_name, node)
    builder.add_edge(START, node_name)
    builder.add_edge(node_name, END)
    graph = compile_test_graph(builder, checkpointer=checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    parked = await ainvoke_test_graph(graph, state, config)
    assert "__interrupt__" in parked, parked

    producer = RunEventProducer()
    relayed = relayed_events(producer)
    assert await emit_interrupt_events(
        thread_id, graph, dict(config), producer._emitters
    )
    requests = [
        sequenced
        for sequenced in relayed
        if isinstance(sequenced.event, PermissionRequest)
    ]
    assert len(requests) == 1, relayed
    return sequenced_to_dict(requests[0])


@pytest.mark.asyncio
async def test_a_real_document_approval_is_journaled_as_a_document_approval(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The phase gate's pause reaches the journal under its own interrupt kind.

    The out-of-run verdict subscriber correlates an engine verdict to a parked
    run through ``pending_document_approval_thread``, which matches on the
    journal row's ``pause_reason_type``. A document approval journaled under
    the plan-approval cause is a pause no verdict can reach.
    """
    async with session_factory() as session:
        thread_id, _receipt = await seed_accepted_thread(session, status="running")
        await session.commit()

    payload = await _relayed_permission_payload(
        checkpointer,
        thread_id=thread_id,
        node_name="gate",
        node=create_phase_gate_node(
            "research", approved_target="approved", revision_target="revise"
        ),
        state=_gate_state(thread_id, gate_pending_proposal_id=_PROPOSAL_ID),
    )

    await relay_event(
        thread_id,
        payload,
        services=RelayServices(
            session_factory=session_factory, checkpointer=checkpointer
        ),
    )

    async with session_factory() as session:
        journaled = await get_permission_request(session, _PROPOSAL_ID)
        assert journaled is not None, "the relay journaled no request for the gate"
        found = await pending_document_approval_thread(
            session, request_ids=[_PROPOSAL_ID]
        )

    assert (
        journaled.pause_reason_type,
        found,
    ) == (InterruptType.DOCUMENT_APPROVAL_REQUEST.value, thread_id)


@pytest.mark.asyncio
async def test_a_real_plan_approval_is_journaled_as_a_plan_approval(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The plan gate keeps its own cause, and is not a document approval."""
    async with session_factory() as session:
        thread_id, _receipt = await seed_accepted_thread(session, status="running")
        await session.commit()

    payload = await _relayed_permission_payload(
        checkpointer,
        thread_id=thread_id,
        node_name="plan_approval",
        node=create_plan_approval_node(["coder"]),
        state=_gate_state(
            thread_id,
            next="coder",
            vault_index={"plan": [".vault/plan/2026-10-01-agent-panel-plan.md"]},
        ),
    )
    request_id = str(payload["request_id"])

    await relay_event(
        thread_id,
        payload,
        services=RelayServices(
            session_factory=session_factory, checkpointer=checkpointer
        ),
    )

    async with session_factory() as session:
        journaled = await get_permission_request(session, request_id)
        assert journaled is not None, "the relay journaled no request for the gate"
        found = await pending_document_approval_thread(
            session, request_ids=[request_id]
        )

    assert journaled.pause_reason_type == InterruptType.PLAN_APPROVAL_REQUEST.value
    assert found is None
