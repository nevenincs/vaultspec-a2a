"""Interrupt-to-frame projection of ACP permission options.

Real objects throughout: a real ``StateGraph`` compiled with LangGraph's
``InMemorySaver``, suspended by a real ``interrupt()`` call, inspected through
the real ``aget_state`` checkpointer read, and projected by the real
``emit_interrupt_events`` into a real ``EventAggregator``. Nothing here stands in
for production code, so the assertions describe what a dashboard client actually
receives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from ...graph.enums import PermissionOptionKind
from ..aggregator import EventAggregator
from ..transformer import emit_interrupt_events
from ..types import resolve_acp_option_kind

if TYPE_CHECKING:
    from ..types import StreamableGraph


class _GateState(TypedDict):
    """Minimal graph state: the offered options carried into the gate node."""

    acp_options: list[dict[str, Any]]


async def _suspend_on_permission(thread_id: str, acp_options: list[dict[str, Any]]):
    """Run a real graph to a real permission interrupt and return graph + config."""

    def gate(state: _GateState) -> _GateState:
        interrupt(
            {
                "type": "permission_request",
                "tool_name": "Edit",
                "tool_input": {"path": "src/a.py"},
                "options": state["acp_options"],
            }
        )
        return state

    builder = StateGraph(cast("Any", _GateState))
    builder.add_node("gate", gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    config = RunnableConfig(configurable={"thread_id": thread_id})
    result = await graph.ainvoke({"acp_options": acp_options}, config)
    assert "__interrupt__" in result  # the graph really did suspend

    return cast("StreamableGraph", graph), cast("dict[str, Any]", config)


async def _project(thread_id: str, acp_options: list[dict[str, Any]]) -> list[dict]:
    """Return the option list a client receives for the given ACP options."""
    aggregator = EventAggregator()
    graph, config = await _suspend_on_permission(thread_id, acp_options)

    emitted = await emit_interrupt_events(
        thread_id, "coder", graph, config, aggregator._emitters
    )
    assert emitted

    pending = aggregator.get_pending_permissions(thread_id)
    assert len(pending) == 1
    return pending[0].options


@pytest.mark.asyncio
async def test_both_option_id_spellings_reach_the_client_intact() -> None:
    """The projection normalises either wire spelling onto ``option_id``."""
    options = await _project(
        "thread-mixed",
        [
            {"option_id": "allow_always", "label": "Always allow"},
            {"optionId": "reject_once", "label": "Deny"},
        ],
    )

    assert [opt["option_id"] for opt in options] == ["allow_always", "reject_once"]
    assert [opt["name"] for opt in options] == ["Always allow", "Deny"]
    assert [str(opt["kind"]) for opt in options] == ["allow_always", "reject_once"]


@pytest.mark.asyncio
async def test_an_option_id_present_but_null_does_not_reach_the_client() -> None:
    """A present-but-null key defeated the old ``dict.get`` fallback chain.

    ``opt.get("optionId", ...)`` returns ``None`` when the key exists with a null
    value — the default never fires — so a null id was projected into the frame
    and offered to the dashboard as something a human could answer with.
    """
    options = await _project("thread-null", [{"optionId": None, "label": "Broken"}])

    assert options[0]["option_id"] == "allow_once"
    assert options[0]["option_id"] is not None


@pytest.mark.asyncio
async def test_an_options_list_the_agent_omits_falls_back_to_allow_and_deny() -> None:
    """An agent offering nothing still yields an answerable pair."""
    options = await _project("thread-empty", [])

    assert [opt["option_id"] for opt in options] == ["allow_once", "deny_once"]


@pytest.mark.asyncio
async def test_a_declared_denial_survives_an_id_that_does_not_spell_it() -> None:
    """The agent's declared kind decides, not a guess made from its id.

    This is the severe case. The id heuristic only recognises ``deny``/``reject``
    spellings and defaults everything else to allow-once, and nothing obliges an
    agent to use either word. An option the agent explicitly declared as rejecting
    was therefore projected -- and persisted -- as an approval, and because the
    re-derived kind carried no information the id did not, no later reader could
    recover the denial.
    """
    options = await _project(
        "thread-declared-denial",
        [
            {"optionId": "proceed", "label": "Go ahead", "kind": "allow_once"},
            {"optionId": "decline", "label": "Do not", "kind": "reject_once"},
        ],
    )

    assert [opt["option_id"] for opt in options] == ["proceed", "decline"]
    assert [str(opt["kind"]) for opt in options] == ["allow_once", "reject_once"]


@pytest.mark.asyncio
async def test_a_declared_always_kind_is_not_flattened_to_once() -> None:
    """Declaration wins for the scope of the grant, not only its polarity."""
    options = await _project(
        "thread-declared-always",
        [{"optionId": "trust_this_tool", "label": "Trust", "kind": "allow_always"}],
    )

    assert [str(opt["kind"]) for opt in options] == ["allow_always"]


@pytest.mark.asyncio
async def test_an_unrecognised_declared_kind_degrades_to_the_id_derivation() -> None:
    """A kind outside the schema is not written through to the durable column.

    Trusting the raw string would put an unreadable status on the record -- and
    would in fact fail loudly downstream, where the emitter re-validates every kind
    through ``PermissionOptionKind``. Routing it to the id heuristic keeps the
    projection total, and here the id still carries the denial.
    """
    options = await _project(
        "thread-bogus-kind",
        [{"optionId": "reject_once", "label": "Deny", "kind": "refuse"}],
    )

    assert [str(opt["kind"]) for opt in options] == ["reject_once"]


@pytest.mark.asyncio
async def test_an_agent_declaring_no_kind_still_derives_one_from_the_id() -> None:
    """The derivation remains the fallback for agents that declare nothing."""
    options = await _project(
        "thread-no-kind",
        [{"optionId": "allow_always"}, {"optionId": "reject_once"}],
    )

    assert [str(opt["kind"]) for opt in options] == ["allow_always", "reject_once"]


def test_resolve_prefers_a_declared_kind_over_the_id_heuristic() -> None:
    """The resolver's contract, exercised directly on every input shape."""
    # A schema-valid declaration is honoured even when the id disagrees.
    assert resolve_acp_option_kind("reject_once", "approve") is (
        PermissionOptionKind.REJECT_ONCE
    )
    # A PermissionOptionKind member is as valid as its bare string value.
    assert resolve_acp_option_kind(PermissionOptionKind.ALLOW_ALWAYS, "nope") is (
        PermissionOptionKind.ALLOW_ALWAYS
    )
    # Absent, empty, non-string, and unrecognised declarations all fall back.
    for declared in (None, "", "refuse", 7, {"kind": "reject_once"}):
        assert resolve_acp_option_kind(declared, "deny_always") is (
            PermissionOptionKind.REJECT_ALWAYS
        )
    # With nothing to go on at either end, the permissive default stands: the
    # heuristic recognises only rejecting spellings, so flipping it would classify
    # every approving id this system mints as a denial.
    assert resolve_acp_option_kind(None, "approve") is PermissionOptionKind.ALLOW_ONCE


def test_relayed_cache_keeps_a_denial_declared_under_an_approving_id() -> None:
    """The gateway's cache must not re-derive a kind the payload already carries.

    Two paths build a permission option. The transformer, reading a live ACP
    interrupt, resolves the kind from what the agent DECLARED. The relay path,
    rebuilding this cache from a worker payload, used to re-derive it from the
    option id instead - discarding the one field that says whether the option
    denies.

    That is not a hypothetical divergence. An id is free-form and
    provider-defined, and nothing obliges an agent to spell a rejecting option
    "deny" or "reject"; the resolver exists precisely because such an option was
    once persisted as an approval with no way for a later reader to recover the
    denial. Driven through the aggregator's real relay seam over a payload whose
    declared kind and id DISAGREE, which is the only shape that can tell the two
    derivations apart.
    """
    aggregator = EventAggregator()

    aggregator.sync_worker_event(
        "thread-denial-under-approving-id",
        {
            "type": "permission_request",
            "request_id": "req-1",
            "description": "Write to the repository",
            "options": [
                # Declared a denial, spelled like an acceptance.
                {"option_id": "approve", "name": "No", "kind": "reject_once"},
            ],
        },
    )

    pending = aggregator.get_pending_permissions("thread-denial-under-approving-id")
    assert pending, "the request never reached the cache"
    option = pending[0].options[0]
    assert option["kind"] == str(PermissionOptionKind.REJECT_ONCE), (
        "the cache re-derived the kind from the id and turned a declared "
        f"denial into {option['kind']}"
    )
