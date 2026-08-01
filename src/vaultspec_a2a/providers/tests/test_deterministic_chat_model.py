"""Tests for the deterministic in-process research_adr acceptance provider."""

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from ...authoring.contract import DOCUMENT_AUTHORING_ROLE_SET, DOCUMENT_AUTHORING_ROLES
from ...graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Provider
from ...team.team_config import AgentConfig, AgentPersonaConfig
from ..deterministic_chat_model import (
    _ROLE_DISPATCH_KEYS,
    CLARIFICATION_TRIGGER_MARKER,
    DeterministicResearchAdrChatModel,
    _role_of,
)
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
async def test_researcher_emits_clarification_sentinel_when_triggered() -> None:
    """The CLARIFICATION_TRIGGER_MARKER in any message forces the ground-stage
    clarification sentinel + a parseable two-question array (one choice, one
    text; one required, one optional), so a live drive exercises the choice-
    option surface, the free-text surface, the required-vs-optional gate, and
    the multi-question recap in one park - not just a text input, which alone
    would render identically whether choice-option handling works or not."""
    import json

    result = await _model("vaultspec-researcher", topic="layout").ainvoke(
        [HumanMessage(content=f"research it. {CLARIFICATION_TRIGGER_MARKER}")]
    )
    body = str(result.content)
    lines = body.splitlines()
    assert lines[0] == "CLARIFICATION NEEDED"
    questions = json.loads("\n".join(lines[1:]))
    assert isinstance(questions, list) and len(questions) == 2

    choice, text = questions
    assert choice["kind"] == "choice"
    assert choice["required"] is True
    assert isinstance(choice["options"], list) and len(choice["options"]) >= 2

    assert text["kind"] == "text"
    assert text["required"] is False

    assert {q["id"] for q in questions} == {choice["id"], text["id"]}
    assert all(q["id"] and q["prompt"] for q in questions)


@pytest.mark.asyncio
async def test_researcher_ignores_trigger_absent_marker() -> None:
    """Without the marker, the researcher's ordinary findings text is unchanged."""
    result = await _model("vaultspec-researcher", topic="layout").ainvoke(
        [HumanMessage(content="research it, nothing special")]
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
    code-truth DOCUMENT_AUTHORING_ROLE_SET.
    """
    assert frozenset(_ROLE_DISPATCH_KEYS) == DOCUMENT_AUTHORING_ROLE_SET


def test_role_of_resolves_every_contract_role() -> None:
    """Every contract role resolves from its namespaced agent id via _role_of."""
    for role in DOCUMENT_AUTHORING_ROLES:
        assert _role_of(f"vaultspec-{role}") == role
