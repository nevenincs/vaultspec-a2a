"""Tests for the deterministic in-process research_adr acceptance provider."""

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from ...graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Provider
from ...team.team_config import AgentConfig, AgentPersonaConfig
from ..deterministic_chat_model import DeterministicResearchAdrChatModel
from ..factory import ProviderFactory


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
    """The factory dispatches Provider.DETERMINISTIC to a BaseChatModel."""
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
