"""The checkpoint store reads back only the types it is configured to admit.

A checkpoint store is an execution surface on the READ side: the permissive
default imports and calls whatever type a stored value names, so anything able
to write the store decides what this process constructs on load. Configuring
the saver against that makes one claim with two halves, and neither half is
worth anything alone - a store that refuses everything is safe and useless.
So the store is held to both: the shipped research preset parks at a real
human gate, is read back through a SECOND saver over the same store, and must
come back whole with nothing blocked; and the same store must decline to
rebuild a type the graph never writes.

Everything runs through the production ``open_checkpointer`` factory, over the
real SQLite file the desktop profile uses.
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any, TypedDict, cast
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.serde.event_hooks import register_serde_event_listener
from langgraph.graph import END, START
from langgraph.types import Command

from ...graph.compiler import compile_team_graph
from ...providers import ProviderFactory
from ...team.team_config import (
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from ...testing import (
    add_test_node,
    compile_test_graph,
    deterministic_model_assignment,
    new_state_graph,
)
from ...testing import settings_override as _settings_override
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ..checkpoints import open_checkpointer

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from langgraph.checkpoint.serde.event_hooks import SerdeEvent

    from ..checkpoints import Checkpointer

_PRESET = "vaultspec-adr-research-deterministic"


@contextmanager
def _recorded_serde_events() -> Generator[list[SerdeEvent]]:
    """Collect what the serializer reports about the types it reads back.

    The serializer's own listener hook, not a log scrape: its warnings are
    deduplicated for the life of the process, so an earlier test in the same
    worker would silence the one this test depends on.
    """
    events: list[SerdeEvent] = []
    unregister = register_serde_event_listener(events.append)
    try:
        yield events
    finally:
        unregister()


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


# ---------------------------------------------------------------------------
# What the store must still hand back: a real preset parked at a real gate
# ---------------------------------------------------------------------------


class _Submitter:
    async def __call__(self, state: Any, phase: str) -> str:
        del state
        return f"prop-{phase}"


def _research_graph(saver: Checkpointer) -> Any:
    """Compile the shipped research preset over *saver* on the deterministic lane.

    The lane's reviewer passes every draft, so the run reaches its first human
    gate. ``Any`` because the compiler's supported surface is invoke-and-inspect,
    and reading a parked run's state back is what this asks of it.
    """
    team = load_team_config(_PRESET)
    topology = team.topology.model_copy(
        update={"research_threads": [ResearchThreadSpec(thread_id="primary")]}
    )
    team = team.model_copy(update={"topology": topology})
    return compile_team_graph(
        team_config=team,
        agent_configs={w.agent_id: load_agent_config(w.agent_id) for w in team.workers},
        checkpointer=saver,
        provider_factory=ProviderFactory(),
        proposal_submitter=_Submitter(),
        model_assignment=deterministic_model_assignment(team),
    )


def _preset_input(thread_id: str) -> dict[str, Any]:
    # The completion node applies the dispatch receipt, so a run needs a real
    # one seeded to get anywhere at all.
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=thread_id,
        action_id="ingest",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint({"run": thread_id}),
        dispatch_id="ingest",
        run_revision=1,
        writer_generation=1,
    ).model_dump(mode="json")
    return {
        "active_agent": "",
        "active_feature": "conformance",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Carry the feature forward.")],
        "next": "",
        "thread_id": thread_id,
        "token_usage": {},
        "active_graph_action_receipt": receipt,
        "graph_action_receipts": {"ingest": receipt},
    }


async def _park_the_research_preset(saver: Checkpointer, thread_id: str) -> Any:
    """Run the preset to its first human gate and return the interrupt payload."""
    parked = await _research_graph(saver).ainvoke(
        cast("Any", _preset_input(thread_id)), cast("Any", _config(thread_id))
    )
    payload = parked["__interrupt__"][0].value
    assert payload["type"] == "document_approval_request"
    return payload


async def _resume_the_parked_preset(
    saver: Checkpointer, thread_id: str, request_id: str
) -> Any:
    """Approve the gate the run is parked on, off the checkpoint as stored."""
    advanced = await _research_graph(saver).ainvoke(
        Command[str](
            resume={"verdict": "approved", "notes": None, "request_id": request_id}
        ),
        cast("Any", _config(thread_id)),
    )
    return advanced["__interrupt__"][0].value


# ---------------------------------------------------------------------------
# What the store must decline: a type the graph never writes
# ---------------------------------------------------------------------------


class _LeakedPhase(Enum):
    """A type outside the safe set, of the kind a node leaks into state."""

    RESEARCH = "research"


class _Leak(TypedDict):
    # Deliberately untyped: what a store must refuse is the value it was
    # handed, not the value a schema promised, and a declared type is what a
    # graph would register for itself.
    phase: Any


async def _write_leak(state: _Leak) -> dict[str, Any]:
    del state
    return {"phase": _LeakedPhase.RESEARCH}


def _leaking_graph(saver: Checkpointer) -> Any:
    builder = new_state_graph(_Leak)
    add_test_node(builder, "leak", _write_leak)
    builder.add_edge(START, "leak")
    builder.add_edge("leak", END)
    return compile_test_graph(builder, checkpointer=saver)


async def _prove_the_store_will_not_rebuild_an_unsafe_type(
    saver: Checkpointer,
) -> None:
    """A checkpointed value of an unlisted type must not come back as that type."""
    thread_id = f"strict-leak-{uuid4().hex}"
    graph = _leaking_graph(saver)
    try:
        with _recorded_serde_events() as events:
            await graph.ainvoke(
                cast("Any", {"phase": ""}), cast("Any", _config(thread_id))
            )
            stored = (await graph.aget_state(cast("Any", _config(thread_id)))).values
    finally:
        await saver.adelete_thread(thread_id)

    # The library's strict path degrades rather than raising: the blocked value
    # comes back as the raw argument its type was built from.
    assert not isinstance(stored["phase"], _LeakedPhase), repr(stored["phase"])
    assert stored["phase"] == _LeakedPhase.RESEARCH.value
    assert {
        (event["module"], event["name"])
        for event in events
        if event["kind"] == "msgpack_blocked"
    } == {(_LeakedPhase.__module__, _LeakedPhase.__name__)}
    assert not [
        event for event in events if event["kind"] == "msgpack_unregistered_allowed"
    ]


async def _prove_the_store_hands_a_parked_preset_back_whole(
    saver: Checkpointer, reader: Checkpointer, thread_id: str
) -> None:
    """Park the preset through *saver*, then read and resume through *reader*."""
    with _recorded_serde_events() as events:
        payload = await _park_the_research_preset(saver, thread_id)
        hydrated = (
            await _research_graph(reader).aget_state(cast("Any", _config(thread_id)))
        ).values
        next_payload = await _resume_the_parked_preset(
            reader, thread_id, payload["request_id"]
        )

    assert hydrated["gate_phase"] == "research"
    assert set(hydrated["review_revisions"]) == {"research"}
    assert hydrated["thread_id"] == thread_id
    assert hydrated["active_graph_action_receipt"]["dispatch_id"] == "ingest"
    assert hydrated["messages"][0].content == "Carry the feature forward."
    # A gate the store gave back is a gate that still answers: the approval
    # read off the checkpoint advances the machine to the next phase.
    assert next_payload["phase"] == "adr"
    assert not events, f"the preset run wrote types the store cannot admit: {events}"


# ---------------------------------------------------------------------------
# The desktop store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_desktop_store_admits_the_preset_and_refuses_what_it_never_wrote(
    tmp_path: Path,
) -> None:
    """The SQLite saver the desktop profile opens, held to both halves."""
    database = tmp_path / "checkpoints.sqlite"
    thread_id = f"strict-desktop-{uuid4().hex}"
    with _settings_override(checkpoint_database_url=f"sqlite+aiosqlite:///{database}"):
        async with open_checkpointer() as saver, open_checkpointer() as reader:
            await _prove_the_store_hands_a_parked_preset_back_whole(
                saver, reader, thread_id
            )
            await _prove_the_store_will_not_rebuild_an_unsafe_type(saver)
