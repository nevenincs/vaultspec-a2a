"""Tests for the deterministic in-process research_adr acceptance provider."""

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from ...authoring.contract import RESEARCH_ADR_ROLES
from ...graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Provider
from ...team.team_config import AgentConfig, AgentPersonaConfig
from ..deterministic_chat_model import (
    _ROLE_DISPATCH_KEYS,
    DeterministicResearchAdrChatModel,
    _role_of,
)
from ..factory import ProviderFactory
from ..lane_admission import (
    IN_PROCESS_LANES,
)


def _agent(agent_id: str) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id,
        role=agent_id,
        description=f"{agent_id} role for the deterministic acceptance provider",
        persona=AgentPersonaConfig(system_prompt=f"{agent_id} deterministic persona"),
    )


def _model(agent_id: str, **kwargs: Any) -> DeterministicResearchAdrChatModel:
    model = ProviderFactory().create(
        Provider.DETERMINISTIC, agent_config=_agent(agent_id), **kwargs
    )
    assert isinstance(model, DeterministicResearchAdrChatModel)
    return model


def test_enum_and_maps_wired() -> None:
    """Provider.DETERMINISTIC resolves a default model through MODEL_MAP."""
    assert Provider.DETERMINISTIC.value == "deterministic"
    level = PROVIDER_DEFAULT_MODELS[Provider.DETERMINISTIC]
    assert MODEL_MAP[Provider.DETERMINISTIC][level] == "deterministic"


def test_factory_returns_first_class_base_chat_model() -> None:
    """The production factory resolves the permanent completion floor."""
    assert Provider.DETERMINISTIC in IN_PROCESS_LANES
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
    result = await _model(
        "vaultspec-synthesist", feature_tag="grid-layout", topic="layout"
    ).ainvoke([HumanMessage(content="x")])
    body = str(result.content)
    assert "'#research'" in body
    assert "'#grid-layout'" in body
    assert "# `grid-layout` research: `layout`" in body


@pytest.mark.asyncio
async def test_adr_author_returns_adr_document() -> None:
    """The adr-author emits a valid ADR document with the feature tag."""
    result = await _model(
        "vaultspec-adr-author", feature_tag="grid-layout", topic="layout"
    ).ainvoke([HumanMessage(content="x")])
    body = str(result.content)
    assert "'#adr'" in body
    assert "'#grid-layout'" in body
    assert "adr:" in body


@pytest.mark.asyncio
async def test_researcher_returns_findings_not_a_document() -> None:
    """The researcher emits findings text (feeds synthesis), not a vault doc."""
    result = await _model("vaultspec-researcher", topic="layout").ainvoke(
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
        result = await _model("vaultspec-researcher", topic="layout").ainvoke(
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


def test_role_dispatch_keys_match_authoring_contract() -> None:
    """The provider's role dispatch keys stay in sync with the authoring contract.

    Guards authoring-contract ADR binding (b): the deterministic provider keeps a
    private copy of the role names, so this asserts it never diverges from the
    code-truth research_adr roster it exists to drive. The solo doc-editor is
    deliberately absent - it is not a research_adr role, and this provider serves
    only that phase machine.
    """
    assert frozenset(_ROLE_DISPATCH_KEYS) == frozenset(RESEARCH_ADR_ROLES)


def test_role_of_resolves_every_contract_role() -> None:
    """Every research_adr role resolves from its namespaced agent id via _role_of."""
    for role in RESEARCH_ADR_ROLES:
        assert _role_of(f"vaultspec-{role}") == role
