"""The clarification nudge, emitted by the real producer for a really-parked run.

Real objects end to end: the production clarification node pair drives a real
``StateGraph`` to a real ``interrupt()`` over a real ``InMemorySaver``, the real
``emit_interrupt_events`` inspects it through the real ``aget_state`` read, and a
real ``EventAggregator`` subscriber receives whatever comes out. Nothing here
stands in for production code, so an assertion about what a subscriber receives
is an assertion about what a dashboard receives.

The point of the frame is what it does NOT carry. The interrupt payload sitting
in the checkpoint holds every prompt and option; the frame is allowed to say only
that one exists. So the central test does not check a field list - it takes the
question text that provably reached the producer and asserts that none of it
reached the subscriber.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ...graph.compiler import _clarification_request_id
from ...graph.enums import AgentLifecycleState
from ...graph.events import AgentStatus, ClarificationPending
from ...graph.nodes.clarification import (
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ...thread.clarification import (
    MAX_REQUEST_ID_CHARS,
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
)
from ...thread.state import TeamState
from ..aggregator import EventAggregator
from ..sse_frames import enforce_progress_allowlist
from ..transformer import emit_interrupt_events

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..types import SequencedEvent, StreamableGraph

# The distinctive strings the questionnaire carries. Every one of them reaches
# the producer inside the interrupt payload; none may reach a subscriber.
_PROMPT = "Which side should the monitor panel dock to?"
_NOTES_PROMPT = "Anything the panel must respect?"
_OPTIONS = ["dock-right", "dock-left"]
_REQUEST_ID = "clarify-relay"


def _add_node(builder: StateGraph[Any, None, Any, Any], name: str, node: Any) -> None:
    """Add a node through a cast seam.

    ``StateGraph.add_node`` resolves against langgraph's own internal node
    types, which strict checking treats as partially unknown because
    ``langgraph.graph`` ships no type stubs. This pins the call to a known
    shape once instead of repeating the cast at every call site below.
    """
    typed_add_node = cast("Callable[[str, Any], None]", builder.add_node)
    typed_add_node(name, node)


def _compile(builder: StateGraph[Any, None, Any, Any]) -> Any:
    """Compile through the same cast seam ``_add_node`` uses."""
    typed_compile = cast("Callable[..., Any]", builder.compile)
    return typed_compile(checkpointer=InMemorySaver())


def _question_set(request_id: str = _REQUEST_ID) -> ClarificationRequest:
    return ClarificationRequest(
        request_id=request_id,
        questions=[
            ClarificationQuestion(
                id="dock_side",
                prompt=_PROMPT,
                kind=ClarificationKind.CHOICE,
                options=_OPTIONS,
            ),
            ClarificationQuestion(
                id="notes",
                prompt=_NOTES_PROMPT,
                kind=ClarificationKind.TEXT,
                required=False,
            ),
        ],
    )


async def _park_on_clarification(
    thread_id: str,
    request_id: str = _REQUEST_ID,
) -> tuple[StreamableGraph, dict[str, Any]]:
    """Drive the PRODUCTION node pair to a real clarification interrupt."""
    request = _question_set(request_id)

    async def _producer(state: TeamState) -> ClarificationRequest | None:
        return request

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))
    _add_node(
        builder,
        "clarification_request",
        create_clarification_request_node(
            _producer, gate_target="clarification_gate", proceed_target="proceed"
        ),
    )
    _add_node(
        builder,
        "clarification_gate",
        create_clarification_gate_node(proceed_target="proceed"),
    )
    _add_node(builder, "proceed", proceed)
    builder.add_edge(START, "clarification_request")
    builder.add_edge("proceed", END)
    graph = _compile(builder)

    config = RunnableConfig(configurable={"thread_id": thread_id})
    result = await graph.ainvoke(
        {
            "active_agent": "clarify",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Plan the monitor panel.")],
            "next": "",
            "thread_id": thread_id,
            "active_feature": "agent-panel",
            "token_usage": {},
        },
        config,
    )
    assert "__interrupt__" in result  # the graph really did suspend
    return cast("StreamableGraph", graph), cast("dict[str, Any]", config)


def _drain(queue: Any) -> list[SequencedEvent]:
    drained: list[SequencedEvent] = []
    while not queue.empty():
        drained.append(queue.get_nowait())
    return drained


async def _relay(
    thread_id: str, request_id: str = _REQUEST_ID
) -> tuple[EventAggregator, list[SequencedEvent]]:
    """Park a real run, project it, and return everything a subscriber got."""
    aggregator = EventAggregator()
    queue = aggregator.add_subscriber("client-1")
    aggregator.subscribe("client-1", [thread_id])

    graph, config = await _park_on_clarification(thread_id, request_id)
    emitted = await emit_interrupt_events(
        thread_id, "supervisor", graph, config, aggregator._emitters
    )
    assert emitted

    return aggregator, _drain(queue)


@pytest.mark.asyncio
async def test_a_parked_run_puts_a_clarification_nudge_on_the_relay() -> None:
    """The real producer emits the frame for a really-parked run.

    A frame kind nothing emits is a dead declaration, so this drives the actual
    interrupt-inspection seam rather than calling the emitter directly.
    """
    _aggregator, received = await _relay("relay-emits")

    nudges = [s for s in received if isinstance(s.event, ClarificationPending)]
    assert len(nudges) == 1
    nudge = cast("ClarificationPending", nudges[0].event)
    assert nudge.thread_id == "relay-emits"
    assert nudge.request_id == _REQUEST_ID
    assert nudges[0].sequence > 0


@pytest.mark.asyncio
async def test_no_question_text_reaches_the_relay() -> None:
    """The frame is a nudge, not the questionnaire.

    Asserted against the whole of what the subscriber received, not just the
    nudge's own fields: if any path - the nudge, the agent-status detail, or a
    future addition - leaked a prompt or an option onto the droppable channel, a
    client could render the questionnaire from relay memory, which is exactly the
    reload bug the authoritative status disclosure exists to prevent.
    """
    _aggregator, received = await _relay("relay-silent")

    everything = repr([s.event for s in received])
    assert _PROMPT not in everything
    assert _NOTES_PROMPT not in everything
    for option in _OPTIONS:
        assert option not in everything
    # The correlation handle IS allowed through - that is the whole payload.
    assert _REQUEST_ID in everything


@pytest.mark.asyncio
async def test_the_run_is_reported_as_awaiting_input() -> None:
    """A parked run must not look like it is still working."""
    _aggregator, received = await _relay("relay-status")

    statuses = [s.event for s in received if isinstance(s.event, AgentStatus)]
    assert any(s.state is AgentLifecycleState.INPUT_REQUIRED for s in statuses)


@pytest.mark.asyncio
async def test_a_clarification_is_not_filed_as_a_pending_permission() -> None:
    """A question is not a tool approval, and must not appear as one.

    The pending-permission registry backs surfaces that offer an answerable
    option list and reconcile against durable permission rows. A clarification
    has neither, so filing it there would strand an unanswerable entry on
    team-status that no permission verb could ever resolve.
    """
    aggregator, _received = await _relay("relay-not-permission")

    assert aggregator.get_pending_permissions("relay-not-permission") == []


@pytest.mark.asyncio
async def test_a_run_parked_on_nothing_emits_no_nudge() -> None:
    """No interrupt, no frame - the emission is genuinely interrupt-driven."""

    async def _silent(state: TeamState) -> ClarificationRequest | None:
        return None

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))
    _add_node(
        builder,
        "clarification_request",
        create_clarification_request_node(
            _silent, gate_target="clarification_gate", proceed_target="proceed"
        ),
    )
    _add_node(
        builder,
        "clarification_gate",
        create_clarification_gate_node(proceed_target="proceed"),
    )
    _add_node(builder, "proceed", proceed)
    builder.add_edge(START, "clarification_request")
    builder.add_edge("proceed", END)
    graph = _compile(builder)

    aggregator = EventAggregator()
    queue = aggregator.add_subscriber("client-2")
    aggregator.subscribe("client-2", ["relay-unparked"])

    config = RunnableConfig(configurable={"thread_id": "relay-unparked"})
    await graph.ainvoke(
        {
            "active_agent": "clarify",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Just go.")],
            "next": "",
            "thread_id": "relay-unparked",
            "active_feature": "agent-panel",
            "token_usage": {},
        },
        config,
    )
    emitted = await emit_interrupt_events(
        "relay-unparked",
        "supervisor",
        cast("StreamableGraph", graph),
        cast("dict[str, Any]", config),
        aggregator._emitters,
    )

    assert not emitted
    assert not [s for s in _drain(queue) if isinstance(s.event, ClarificationPending)]


def test_the_catalog_strips_question_material_from_the_frame() -> None:
    """Even a producer that attached the questionnaire could not ship it.

    The wire catalog rebuilds a frame from the fields it enumerates, so the
    guarantee does not depend on every current and future emitter remembering to
    leave the questions out. This drives that boundary with a frame that carries
    them anyway.
    """
    projected = enforce_progress_allowlist(
        {
            "api_version": "v1",
            "type": "clarification_pending",
            "thread_id": "catalog-thread",
            "request_id": _REQUEST_ID,
            "questions": [{"id": "dock_side", "prompt": _PROMPT, "options": _OPTIONS}],
            "prompt": _PROMPT,
        }
    )

    assert projected["type"] == "clarification_pending"
    assert projected["thread_id"] == "catalog-thread"
    assert projected["request_id"] == _REQUEST_ID
    assert "questions" not in projected
    assert "prompt" not in projected


@pytest.mark.asyncio
async def test_a_handle_minted_at_the_ceiling_survives_the_relay_intact() -> None:
    """The longest handle a run can mint reaches a subscriber unshortened.

    Correlation is the entire purpose of this frame: it carries the request id and
    nothing else, and a consumer re-reads the questionnaire from run-status by that
    id. So the outbound bound on it must never be the shorter of the two numbers.
    It TRUNCATES rather than refuses, which is what makes the failure quiet - the
    nudge still arrives, still looks well-formed, and points at a request id that
    was never issued.

    Both halves are the production ones: the id is minted by the real minting
    function rather than written out at the length it happens to have, and it is
    carried by a really-parked run through the real emitter and then through the
    real outbound catalog. Neither number is restated here, so this follows the
    declaration wherever it moves and fails the moment the two stop agreeing.
    """
    # A thread id far past the cap, so the minting function is driven to its
    # ceiling rather than merely near it.
    minted = _clarification_request_id("t" * (MAX_REQUEST_ID_CHARS * 2))
    assert len(minted) == MAX_REQUEST_ID_CHARS, (
        "the trap must be live: this test proves nothing unless the minted handle "
        "actually reaches the ceiling the outbound bound has to cover"
    )

    _aggregator, received = await _relay("relay-ceiling", minted)

    nudges = [s for s in received if isinstance(s.event, ClarificationPending)]
    assert len(nudges) == 1
    assert cast("ClarificationPending", nudges[0].event).request_id == minted

    projected = enforce_progress_allowlist(
        {
            "api_version": "v1",
            "type": "clarification_pending",
            "thread_id": "relay-ceiling",
            "request_id": minted,
        }
    )

    assert projected["request_id"] == minted
