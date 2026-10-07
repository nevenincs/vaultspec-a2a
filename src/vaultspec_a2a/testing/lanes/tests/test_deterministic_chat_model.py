"""Tests for the deterministic in-process research_adr acceptance provider."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ....authoring.contract import RESEARCH_ADR_ROLES
from ....graph.enums import Provider
from ....providers.factory import ProviderFactory
from ....providers.in_process_catalog import in_process_lane
from ....team.team_config import AgentConfig, AgentPersonaConfig, load_team_config
from ....thread.constants import DEFAULT_SUPERVISOR_ID
from .. import UNATTENDED_REPLY, DeterministicResearchAdrChatModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from langchain_core.messages import AIMessageChunk


def _agent(agent_id: str) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id,
        role=agent_id,
        description=f"{agent_id} role for the deterministic acceptance provider",
        persona=AgentPersonaConfig(system_prompt=f"{agent_id} deterministic persona"),
    )


def _model(agent_id: str) -> DeterministicResearchAdrChatModel:
    """Build the lane's model through the production factory and its plugin."""
    model = ProviderFactory().create(
        Provider.DETERMINISTIC,
        model="deterministic",
        execution_mode="in-process-deterministic",
        agent_config=_agent(agent_id),
    )
    assert isinstance(model, DeterministicResearchAdrChatModel)
    return model


def _authored(agent_id: str, **document: Any) -> DeterministicResearchAdrChatModel:
    """Build the model directly, for a feature tag or topic the factory never sets."""
    return DeterministicResearchAdrChatModel(agent_config=_agent(agent_id), **document)


def test_exact_provider_identity_is_wired() -> None:
    assert Provider.DETERMINISTIC.value == "deterministic"


def test_factory_returns_first_class_base_chat_model() -> None:
    """The production factory resolves the permanent completion floor."""
    assert in_process_lane(Provider.DETERMINISTIC) is not None
    model = _model("vaultspec-researcher")
    assert isinstance(model, BaseChatModel)


@pytest.mark.asyncio
async def test_doc_reviewer_returns_pass_sentinel() -> None:
    """The reviewer role emits the inner-review PASS sentinel to advance."""
    result = await _model("vaultspec-doc-reviewer").ainvoke([HumanMessage(content="x")])
    assert isinstance(result, AIMessage)
    assert result.content == "PASS"


@pytest.mark.asyncio
async def test_synthesist_returns_research_document() -> None:
    """The synthesist emits a valid research document with the feature tag."""
    result = await _authored(
        "vaultspec-synthesist", feature_tag="grid-layout", topic="layout"
    ).ainvoke([HumanMessage(content="x")])
    body = str(result.content)
    assert "'#research'" in body
    assert "'#grid-layout'" in body
    assert "# `grid-layout` research: `layout`" in body


@pytest.mark.asyncio
async def test_adr_author_returns_adr_document() -> None:
    """The adr-author emits a valid ADR document with the feature tag."""
    result = await _authored(
        "vaultspec-adr-author", feature_tag="grid-layout", topic="layout"
    ).ainvoke([HumanMessage(content="x")])
    body = str(result.content)
    assert "'#adr'" in body
    assert "'#grid-layout'" in body
    assert "adr:" in body


@pytest.mark.asyncio
async def test_researcher_returns_findings_not_a_document() -> None:
    """The researcher emits findings text (feeds synthesis), not a vault doc."""
    result = await _authored("vaultspec-researcher", topic="layout").ainvoke(
        [HumanMessage(content="x")]
    )
    body = str(result.content)
    assert "Research findings" in body
    assert "layout" in body
    assert not body.startswith("---")


@pytest.mark.asyncio
async def test_no_prompt_makes_this_provider_ask_a_question() -> None:
    """No input turns a research turn into a clarification, marker text included.

    Questions reach a run from its preset, so a model that could talk itself into
    asking one would be a second, undeclared source for "does this run stop?".
    This provider once had exactly that: a marker that flipped the researcher into
    emitting a clarification sentinel, read by a ground stage that no longer
    exists. The old marker string is passed here deliberately - it must now be
    ordinary prose, so a reintroduced trigger fails rather than passing unnoticed.
    """
    for prompt in (
        "research it, nothing special",
        "research it. DETERMINISTIC_FORCE_CLARIFICATION",
    ):
        result = await _authored("vaultspec-researcher", topic="layout").ainvoke(
            [HumanMessage(content=prompt)]
        )
        body = str(result.content)
        assert "CLARIFICATION NEEDED" not in body
        assert "Research findings" in body


@pytest.mark.asyncio
async def test_namespaced_and_bare_agent_ids_resolve_same_role() -> None:
    """Both `synthesist` and `vaultspec-synthesist` resolve the synthesist role."""
    bare = await _model("synthesist").ainvoke([HumanMessage(content="x")])
    namespaced = await _model("vaultspec-synthesist").ainvoke(
        [HumanMessage(content="x")]
    )
    assert str(bare.content).startswith("---")
    assert str(namespaced.content).startswith("---")


@pytest.mark.asyncio
async def test_stream_matches_generate() -> None:
    """The streaming path yields the same content as the accumulated result."""
    model = _model("vaultspec-adr-author")
    streamed = "".join(
        [str(c.content) async for c in model.astream([HumanMessage(content="x")])]
    )
    generated = str((await model.ainvoke([HumanMessage(content="x")])).content)
    assert streamed == generated


def test_sync_generate_unsupported() -> None:
    """Synchronous generation is explicitly unsupported (async-only)."""
    with pytest.raises(NotImplementedError, match="async"):
        _model("vaultspec-researcher").invoke([HumanMessage(content="x")])


@pytest.mark.asyncio
async def test_every_contract_role_resolves_from_its_namespaced_agent_id() -> None:
    """Every research_adr role answers with its own content, not the fallback.

    An agent id that resolves to no role is answered with a generic marker
    naming only the topic, so any other reply is the resolved role's content.
    """
    unresolved = "Deterministic content for `layout`."
    for role in RESEARCH_ADR_ROLES:
        reply = await _authored(f"vaultspec-{role}", topic="layout").ainvoke(
            [HumanMessage(content="x")]
        )
        assert str(reply.content) != unresolved, f"{role} did not resolve"


@pytest.mark.asyncio
async def test_supervisor_routes_to_its_worker_until_the_worker_answers() -> None:
    """The scripted supervisor routes a human turn once, then finishes it.

    The route is read off the bundled supervisor-routing team, so the script and
    the preset whose worker it routes to cannot drift apart unnoticed.
    """
    worker = load_team_config("deterministic-supervisor-routing").workers[0].agent_id
    supervisor = _model(DEFAULT_SUPERVISOR_ID)
    prompt = SystemMessage(content="Respond with the next route.")
    opened = HumanMessage(content="Do the task.")
    answered = AIMessage(content="Done.", name=worker)

    first = await supervisor.ainvoke([prompt, opened])
    finished = await supervisor.ainvoke([prompt, opened, answered])
    follow_up = await supervisor.ainvoke(
        [prompt, opened, answered, HumanMessage(content="And the next one.")]
    )

    assert first.content == worker
    assert finished.content == "FINISH"
    assert follow_up.content == worker


@pytest.mark.asyncio
async def test_permission_pause_without_a_callback_proceeds_unattended() -> None:
    """A turn with no permission callback is autonomous, so nothing is asked."""
    model = _model("deterministic-permission-pause")
    generated = await model.ainvoke([HumanMessage(content="x")])
    streamed = "".join(
        [str(c.content) async for c in model.astream([HumanMessage(content="x")])]
    )
    assert generated.content == UNATTENDED_REPLY
    assert streamed == UNATTENDED_REPLY


@pytest.mark.asyncio
async def test_looping_turn_keeps_generating_until_it_is_closed() -> None:
    """The looping scenario streams distinct output with no end of its own."""
    stream = _model("deterministic-looping").astream([HumanMessage(content="loop")])
    chunks: list[str] = []
    async for chunk in stream:
        chunks.append(str(chunk.content))
        if len(chunks) == 20:
            break
    # The loop never ends by itself and this one was broken off early, so the
    # generator is closed explicitly rather than left for the collector.
    await cast("AsyncGenerator[AIMessageChunk]", stream).aclose()

    assert len(set(chunks)) == 20
    assert all(chunks)


@pytest.mark.asyncio
async def test_held_turn_completes_only_after_its_gate_is_released(
    tmp_path: Path,
) -> None:
    """The hold-then-complete scenario blocks in-process on its own gate file.

    No worker, gateway or subprocess is involved: the turn is driven directly
    through the model's real async generation path, and the gate is a plain
    file this test creates and removes from its own process.
    """
    gate = tmp_path / "hold.gate"
    gate.touch()
    model = _authored("deterministic-hold-then-complete", hold_gate=gate)

    turn = asyncio.ensure_future(model.ainvoke([HumanMessage(content="x")]))
    try:
        # Several real gate-poll cycles, not a single scheduler tick: proves the
        # turn is actually blocked on the gate rather than merely not yet
        # scheduled.
        done, _pending = await asyncio.wait({turn}, timeout=0.3)
        assert not done, "the turn must stay in flight while the gate exists"

        gate.unlink()
        result = await asyncio.wait_for(turn, timeout=5.0)
    finally:
        if not turn.done():
            turn.cancel()

    assert isinstance(result, AIMessage)
    assert result.content == "Deterministic held turn completed after its release."


@pytest.mark.asyncio
async def test_a_held_turn_with_no_gate_configured_refuses_loudly() -> None:
    """A stack that forgot to configure the gate fails fast, not silently."""
    model = _authored("deterministic-hold-then-complete")
    with pytest.raises(RuntimeError, match="served without a hold gate"):
        await model.ainvoke([HumanMessage(content="x")])
