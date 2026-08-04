"""Tests that the scripted failure scenario preset really fails.

The preset exists to be DRIVEN, so it is exercised here by compiling the real
graph from the shipped TOML and invoking it, rather than by asserting on the
TOML's own fields. A scenario preset asserted only against its own declaration
proves nothing a typo could not also satisfy - which is exactly how the older
tool-failure scenario came to advertise a failure while completing successfully.

Nothing here is armed: the preset names the in-process deterministic provider,
so these run with no credential, no network, and no tape server.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from ...graph.compiler import CompiledTeamGraph, compile_team_graph
from ...providers.factory import ProviderFactory
from ...team.team_config import (
    discover_team_preset_ids,
    load_agent_config,
    load_team_config,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

_PRESET = "deterministic-failure"


class _StreamingGraph(Protocol):
    """The compiled graph's event-stream surface, as this module reads it.

    The compiler's own protocol declares only what production invokes, and
    production drives a graph through ingest rather than through this stream.
    Declared here rather than widened there, so observing a turn from the test
    side does not enlarge the contract the compiler promises.
    """

    def astream_events(
        self,
        input: Mapping[str, Any],
        config: Mapping[str, Any] | None = None,
        *,
        version: str,
    ) -> AsyncIterator[Mapping[str, Any]]: ...


def _compiled_graph() -> CompiledTeamGraph:
    """Compile the shipped preset exactly as the production compile path does."""
    team_config = load_team_config(_PRESET)
    agent_configs = {
        ref.agent_id: load_agent_config(ref.agent_id) for ref in team_config.workers
    }
    return compile_team_graph(
        team_config,
        agent_configs,
        provider_factory=ProviderFactory(),
        workspace_root=Path.cwd(),
    )


def test_the_preset_is_discoverable() -> None:
    """A scenario preset a caller cannot name is not a scenario."""
    assert _PRESET in discover_team_preset_ids()


def test_every_worker_runs_on_the_serverless_in_process_lane() -> None:
    """The scenario must fail identically on an unarmed host.

    Admission as an in-process lane is deliberately NOT the assertion here, and
    would be too weak to make the claim: the mock lane is admitted in-process
    yet proxies the in-repo tape server, so a scenario on that lane needs a
    service running and behaves differently when it is not. Only the
    deterministic lane runs with no server at all, so the assertion names it.

    Read from the shipped preset rather than hardcoded, so a later edit that
    points a stage at another lane fails here instead of quietly turning the
    scenario into something only a provisioned machine can run.
    """
    from ...graph.enums import Provider
    from ...providers.lane_admission import IN_PROCESS_LANES

    team_config = load_team_config(_PRESET)
    lanes = {
        ref.model.provider or team_config.defaults.provider
        for ref in team_config.workers
    }

    assert lanes == {Provider.DETERMINISTIC}
    assert lanes <= IN_PROCESS_LANES


@pytest.mark.asyncio
async def test_the_run_terminates_in_a_real_graph_failure() -> None:
    """Driving the preset raises a real graph failure, not a reported one.

    The assertion is on what the graph DOES, so a preset that merely narrates a
    failure in its model output - the defect this scenario replaces - fails this
    test by completing.
    """
    graph = _compiled_graph()
    team_config = load_team_config(_PRESET)

    with pytest.raises(GraphRecursionError):
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="Drive the failure scenario.")],
                "team_config": team_config,
            },
            config={
                "configurable": {"thread_id": "failure-scenario-terminates"},
                "recursion_limit": team_config.graph.recursion_limit,
            },
        )


@pytest.mark.asyncio
async def test_a_real_turn_completes_before_the_budget_is_exhausted() -> None:
    """Real agent activity precedes the failure, which is what makes it drivable.

    A scenario that dies before any model speaks exercises only the terminal
    path; this one has to show a consumer a working run that then fails, so the
    completed turn is part of the contract rather than an accident of the
    budget. Counted from real streamed model-end events.

    The turn's content is compared against what the in-process provider itself
    produces for that role, asked for directly. That is the empirical half of
    the unarmed claim - it shows the turn was served in process rather than by
    a tape server that happened to be running on the developer's machine - and
    the expectation is derived from the production model rather than pasted
    from an observed run, so it cannot drift into asserting whatever the code
    currently emits.
    """
    from ...providers.deterministic_chat_model import (
        DeterministicResearchAdrChatModel,
    )

    first_worker = load_team_config(_PRESET).workers[0].agent_id
    in_process_turn = await DeterministicResearchAdrChatModel(
        agent_config=load_agent_config(first_worker)
    ).ainvoke([HumanMessage(content="Drive the failure scenario.")])

    graph = cast("_StreamingGraph", _compiled_graph())
    team_config = load_team_config(_PRESET)

    completed_turns: list[str] = []
    with pytest.raises(GraphRecursionError):
        async for event in graph.astream_events(
            {
                "messages": [HumanMessage(content="Drive the failure scenario.")],
                "team_config": team_config,
            },
            config={
                "configurable": {"thread_id": "failure-scenario-turn-first"},
                "recursion_limit": team_config.graph.recursion_limit,
            },
            version="v2",
        ):
            if event["event"] == "on_chat_model_end":
                output = event["data"].get("output")
                completed_turns.append(str(getattr(output, "content", "")))

    assert completed_turns
    assert all(turn.strip() for turn in completed_turns)
    assert completed_turns[0] == in_process_turn.content


def test_the_description_claims_no_provider_condition() -> None:
    """The preset must not advertise a refusal an in-process lane cannot make.

    Provider conditions are resolved from a discriminator a real provider puts
    on the wire. No in-process lane emits one, so a description promising one
    here would be a served claim this repository does not permit. Asserted on
    the shipped text because that text is what a client is shown.
    """
    description = load_team_config(_PRESET).description.lower()

    assert "graph budget" in description
    assert "not a provider failure" in description
    assert "no provider condition" in description
