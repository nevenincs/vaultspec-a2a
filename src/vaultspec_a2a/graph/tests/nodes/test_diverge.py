"""Tests for the Send-based diverge stage.

The fan-out/join structure is exercised over a real ``StateGraph`` with an
``InMemorySaver`` checkpointer -- no mocks. The researcher work is a small
deterministic producer so the test isolates the diverge structure (dispatch
fan-out, per-branch findings, reducer accumulation, synthesis join) from any
model.

The web-locator acceptance driver goes further and uses a file-backed
``AsyncSqliteSaver`` -- the checkpointer production actually runs -- so the
locator is proven to survive real serialisation to disk and back, not merely an
in-process dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.callbacks.manager import AsyncCallbackManager
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from ....graph.compiler import _wire_diverge_stage
from ....graph.nodes.diverge import (
    MAX_WEB_LOCATOR_EXCERPT_CHARS,
    MAX_WEB_LOCATORS_PER_FINDING,
    WEB_LOCATOR_KIND,
    create_research_dispatch_node,
    create_researcher_node,
    researcher_node_name,
)
from ....thread.state import TeamState

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig
_SPECS: list[dict[str, Any]] = [
    {"thread_id": "codebase", "locators": ["compiler.py:402"]},
    {"thread_id": "prior-art", "locators": ["Send docs"]},
    {"thread_id": "engine", "locators": ["events endpoint"]},
]


def _web_locator(url: str, **overrides: Any) -> dict[str, Any]:
    """Return a contract-conformant web locator, overridable field by field."""
    locator: dict[str, Any] = {
        "kind": WEB_LOCATOR_KIND,
        "url": url,
        "retrieved_at": "2026-08-01T09:30:00+00:00",
        "title": "Send is the map-reduce primitive",
        "excerpt": "Send launches one branch per item.",
    }
    locator.update(overrides)
    return locator


#: Specs whose findings mix an internal locator with a retrieved web locator,
#: which is the shape a web-grounded branch actually produces.
_WEB_SPECS: list[dict[str, Any]] = [
    {
        "thread_id": "codebase",
        "locators": ["compiler.py:402"],
    },
    {
        "thread_id": "prior-art",
        "locators": [
            "Send docs",
            _web_locator("https://example.invalid/langgraph/send"),
        ],
    },
    {
        "thread_id": "engine",
        "locators": [
            _web_locator(
                "https://example.invalid/engine/events",
                title="Events endpoint",
                excerpt="The events endpoint streams run updates.",
            )
        ],
    },
]


def _base_state() -> TeamState:
    return {
        "active_agent": "dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the phase machine.")],
        "next": "",
        "thread_id": "diverge-thread",
        "token_usage": {},
    }


async def _fake_producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
    """Deterministic finding producer derived solely from the thread spec."""
    return {
        "claim": f"finding from {spec['thread_id']}",
        "locators": spec["locators"],
        "source_thread": spec["thread_id"],
    }


@pytest.mark.asyncio
async def test_dispatch_emits_one_send_per_researcher() -> None:
    node = create_research_dispatch_node(["r00", "r01", "r02"])
    command = await node(_base_state())
    assert isinstance(command, Command)
    goto = command.goto
    # A Command's goto is a single node name OR a list of Sends; only the
    # list form fans out, and asserting the type is what this test means by
    # "one Send per researcher".
    assert isinstance(goto, list)
    sends = cast("list[Send]", goto)
    assert [send.node for send in sends] == ["r00", "r01", "r02"]


@pytest.mark.asyncio
async def test_researcher_node_appends_single_finding() -> None:
    node = create_researcher_node(_SPECS[0], _fake_producer)
    result = await node(_base_state())
    assert result == {
        "research_findings": [
            {
                "claim": "finding from codebase",
                "locators": ["compiler.py:402"],
                "source_thread": "codebase",
            }
        ]
    }


@pytest.mark.asyncio
async def test_compiled_researcher_forwards_config_to_config_aware_producer() -> None:
    """A public compiled graph injects its callback-bearing config into a producer."""
    observed_configs: list[RunnableConfig] = []
    passive_callback = BaseCallbackHandler()
    spec: dict[str, object] = {
        "thread_id": "config-aware",
        "locators": ["diverge.py:config"],
    }

    async def config_aware_producer(
        state: TeamState,
        spec: dict[str, object],
        *,
        config: RunnableConfig | None = None,
    ) -> dict[str, object]:
        assert config is not None
        observed_configs.append(config)
        return {
            "claim": "the compiled graph injected its runtime config",
            "locators": spec["locators"],
            "source_thread": spec["thread_id"],
        }

    builder: StateGraph = StateGraph(cast("Any", TeamState))
    builder.add_node("researcher", create_researcher_node(spec, config_aware_producer))
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {
        "callbacks": [passive_callback],
        "configurable": {"thread_id": "config-aware-run"},
    }

    result = await graph.ainvoke(_base_state(), config=config)

    assert result["research_findings"][0]["source_thread"] == "config-aware"
    assert observed_configs
    observed_callbacks = observed_configs[0].get("callbacks")
    assert isinstance(observed_callbacks, AsyncCallbackManager)
    assert passive_callback in observed_callbacks.handlers


@pytest.mark.asyncio
async def test_researcher_node_rejects_finding_missing_contract_key() -> None:
    """A producer output missing a contract key fails fast at the branch."""

    async def bad_producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
        return {"claim": "no locators or source_thread"}

    node = create_researcher_node(_SPECS[0], bad_producer)
    with pytest.raises(ValueError, match="missing required key"):
        await node(_base_state())


@pytest.mark.asyncio
async def test_researcher_node_rejects_finding_wrong_type() -> None:
    """A producer output with a wrong-typed field fails fast at the branch."""

    async def bad_producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
        return {"claim": "c", "locators": "not-a-list", "source_thread": "t"}

    node = create_researcher_node(_SPECS[0], bad_producer)
    with pytest.raises(TypeError, match="locators"):
        await node(_base_state())


@pytest.mark.asyncio
async def test_diverge_stage_accumulates_findings_and_joins() -> None:
    """All parallel branches accumulate into research_findings before synthesis.

    The synthesis node runs once (the join), and by the time it runs every
    researcher branch's finding is visible through the reducer.
    """
    builder: StateGraph = StateGraph(cast("Any", TeamState))

    seen_at_synthesis: dict[str, list[dict[str, Any]]] = {}

    async def synthesis_node(state: TeamState) -> dict[str, Any]:
        seen_at_synthesis["findings"] = list(state.get("research_findings") or [])
        return {"messages": [AIMessage(content="synthesised", name="synthesist")]}

    dispatch = _wire_diverge_stage(
        builder,
        dispatch_name="research_dispatch",
        synthesis_name="synthesis",
        specs=_SPECS,
        make_researcher=lambda spec: create_researcher_node(spec, _fake_producer),
        researcher_metadata={},
    )
    builder.add_node("synthesis", synthesis_node)
    builder.add_edge(START, dispatch)
    builder.add_edge("synthesis", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        _base_state(), config={"configurable": {"thread_id": "diverge-run"}}
    )

    threads = sorted(f["source_thread"] for f in result["research_findings"])
    assert threads == ["codebase", "engine", "prior-art"]
    # Synthesis observed the full accumulated set at the join, not a partial one.
    assert len(seen_at_synthesis["findings"]) == len(_SPECS)


@pytest.mark.asyncio
async def test_wire_diverge_stage_rejects_empty_specs() -> None:
    from ....thread.errors import ConfigError

    builder: StateGraph = StateGraph(cast("Any", TeamState))
    with pytest.raises(ConfigError, match="at least one research thread spec"):
        _wire_diverge_stage(
            builder,
            dispatch_name="research_dispatch",
            synthesis_name="synthesis",
            specs=[],
            make_researcher=lambda spec: create_researcher_node(spec, _fake_producer),
            researcher_metadata={},
        )


def test_researcher_node_name_is_deterministic() -> None:
    assert (
        researcher_node_name("research_dispatch", 0)
        == "research_dispatch_researcher_00"
    )
    assert researcher_node_name("research_dispatch", 12) == (
        "research_dispatch_researcher_12"
    )


# ---------------------------------------------------------------------------
# Typed web locators in the finding contract
# ---------------------------------------------------------------------------


def _web_urls(findings: list[dict[str, Any]]) -> list[str]:
    """Return every web-locator URL across *findings*, in encounter order."""
    urls: list[str] = []
    for finding in findings:
        locators = cast("list[str | dict[str, Any]]", finding["locators"])
        urls.extend(
            locator["url"]
            for locator in locators
            if isinstance(locator, dict) and locator.get("kind") == WEB_LOCATOR_KIND
        )
    return urls


@pytest.mark.asyncio
async def test_web_locators_reach_synthesis_and_survive_the_checkpoint(
    tmp_path: Path,
) -> None:
    """A web locator survives dispatch, the reducer, and a real checkpoint.

    This is the acceptance driver for the typed web locator, and it deliberately
    never sets ``research_findings`` on state: the locators are produced inside
    the branches, fan in through the append-only reducer, are observed at the
    synthesis join, and are then read back from a SECOND ``AsyncSqliteSaver``
    opened on the same file after the first connection closed. A direct
    field-set would prove only that a dict can be assigned; the reopen proves
    the locator round-tripped through the checkpointer's real serialisation to
    disk, which is the seam that rejects a shape it cannot serialise.
    """
    checkpoint_path = tmp_path / "diverge-checkpoints.sqlite"
    config: RunnableConfig = {"configurable": {"thread_id": "web-locator-run"}}
    seen_at_synthesis: dict[str, list[dict[str, Any]]] = {}

    async def synthesis_node(state: TeamState) -> dict[str, Any]:
        seen_at_synthesis["findings"] = list(state.get("research_findings") or [])
        return {"messages": [AIMessage(content="synthesised", name="synthesist")]}

    def _build() -> StateGraph:
        builder: StateGraph = StateGraph(cast("Any", TeamState))
        dispatch = _wire_diverge_stage(
            builder,
            dispatch_name="research_dispatch",
            synthesis_name="synthesis",
            specs=_WEB_SPECS,
            make_researcher=lambda spec: create_researcher_node(spec, _fake_producer),
            researcher_metadata={},
        )
        builder.add_node("synthesis", synthesis_node)
        builder.add_edge(START, dispatch)
        builder.add_edge("synthesis", END)
        return builder

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        graph = _build().compile(checkpointer=saver)
        result = await graph.ainvoke(_base_state(), config=config)

    expected_urls = sorted(
        [
            "https://example.invalid/engine/events",
            "https://example.invalid/langgraph/send",
        ]
    )
    assert sorted(_web_urls(result["research_findings"])) == expected_urls

    # The synthesis stage consumed the locators, not just the claims: web
    # evidence is available to the synthesist exactly where internal evidence is.
    assert sorted(_web_urls(seen_at_synthesis["findings"])) == expected_urls

    # Internal locators are untouched by the typed channel.
    assert "compiler.py:402" in [
        locator
        for finding in seen_at_synthesis["findings"]
        for locator in finding["locators"]
        if isinstance(locator, str)
    ]

    # Reopen the persisted checkpoint with a fresh connection and recompiled
    # graph: nothing from the first process-local run is in play here.
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as reopened:
        replayed = await _build().compile(checkpointer=reopened).aget_state(config)

    restored = cast("list[dict[str, Any]]", replayed.values["research_findings"])
    assert sorted(_web_urls(restored)) == expected_urls
    engine_locator = next(
        locator
        for finding in restored
        for locator in cast("list[str | dict[str, Any]]", finding["locators"])
        if isinstance(locator, dict)
        and locator["url"] == "https://example.invalid/engine/events"
    )
    assert engine_locator == {
        "kind": "web",
        "url": "https://example.invalid/engine/events",
        "retrieved_at": "2026-08-01T09:30:00+00:00",
        "title": "Events endpoint",
        "excerpt": "The events endpoint streams run updates.",
    }


async def _locator_producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
    """Emit a finding whose locators are taken verbatim from the spec."""
    return {
        "claim": f"finding from {spec['thread_id']}",
        "locators": spec["locators"],
        "source_thread": spec["thread_id"],
    }


async def _run_with_locators(locators: list[Any]) -> dict[str, Any]:
    """Drive a researcher branch whose producer emits exactly *locators*."""
    spec: dict[str, Any] = {"thread_id": "codebase", "locators": locators}
    node = create_researcher_node(spec, _locator_producer)
    result = await node(_base_state())
    # A researcher branch always contributes a state update, never routes via
    # Command; the assertion documents that invariant rather than widening
    # the helper's return type to the full WorkerNode union.
    assert isinstance(result, dict)
    return result


@pytest.mark.asyncio
async def test_minimal_web_locator_needs_no_optional_fields() -> None:
    """Title and excerpt are optional; kind, url, and retrieved_at are not."""
    result = await _run_with_locators(
        [
            {
                "kind": "web",
                "url": "https://example.invalid/a",
                "retrieved_at": "2026-08-01",
            }
        ]
    )
    assert result["research_findings"][0]["locators"][0]["retrieved_at"] == "2026-08-01"


@pytest.mark.asyncio
async def test_web_locator_accepts_zulu_retrieved_at() -> None:
    result = await _run_with_locators(
        [_web_locator("https://example.invalid/a", retrieved_at="2026-08-01T09:30:00Z")]
    )
    locator = result["research_findings"][0]["locators"][0]
    assert locator["retrieved_at"] == "2026-08-01T09:30:00Z"


@pytest.mark.asyncio
async def test_typed_locator_with_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="declares kind 'ftp'"):
        await _run_with_locators(
            [{"kind": "ftp", "url": "ftp://example.invalid/a", "retrieved_at": "2026"}]
        )


@pytest.mark.asyncio
async def test_typed_locator_without_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="declares kind None"):
        await _run_with_locators(
            [{"url": "https://example.invalid/a", "retrieved_at": "2026-08-01"}]
        )


@pytest.mark.asyncio
async def test_web_locator_missing_required_key_is_refused() -> None:
    with pytest.raises(
        ValueError, match=r"missing required key\(s\) \['retrieved_at'\]"
    ):
        await _run_with_locators([{"kind": "web", "url": "https://example.invalid/a"}])


@pytest.mark.asyncio
async def test_web_locator_with_unknown_key_is_refused() -> None:
    """The shape is closed: an undeclared field never reaches checkpointed state."""
    with pytest.raises(ValueError, match=r"unknown key\(s\) \['snippet'\]"):
        await _run_with_locators(
            [_web_locator("https://example.invalid/a", snippet="extra")]
        )


@pytest.mark.asyncio
async def test_web_locator_rejects_non_web_url_scheme() -> None:
    """A local-file URL must never enter a channel disclosed to a reader."""
    with pytest.raises(ValueError, match="url scheme 'file'"):
        await _run_with_locators([_web_locator("file:///etc/passwd")])


@pytest.mark.asyncio
async def test_web_locator_rejects_unparseable_retrieved_at() -> None:
    with pytest.raises(ValueError, match="is not ISO-8601"):
        await _run_with_locators(
            [_web_locator("https://example.invalid/a", retrieved_at="last Tuesday")]
        )


@pytest.mark.asyncio
async def test_web_locator_rejects_non_str_retrieved_at() -> None:
    with pytest.raises(TypeError, match="'retrieved_at'"):
        await _run_with_locators(
            [_web_locator("https://example.invalid/a", retrieved_at=1754039400)]
        )


@pytest.mark.asyncio
async def test_web_locator_excerpt_over_cap_is_refused() -> None:
    """The cap is enforced, not silently applied: the producer must elide."""
    with pytest.raises(ValueError, match="cap is"):
        await _run_with_locators(
            [
                _web_locator(
                    "https://example.invalid/a",
                    excerpt="x" * (MAX_WEB_LOCATOR_EXCERPT_CHARS + 1),
                )
            ]
        )


@pytest.mark.asyncio
async def test_web_locator_excerpt_at_cap_is_admitted() -> None:
    """The boundary is inclusive, so the cap refuses only genuine overflow."""
    excerpt = "x" * MAX_WEB_LOCATOR_EXCERPT_CHARS
    result = await _run_with_locators(
        [_web_locator("https://example.invalid/a", excerpt=excerpt)]
    )
    assert result["research_findings"][0]["locators"][0]["excerpt"] == excerpt


@pytest.mark.asyncio
async def test_web_locator_count_over_cap_is_refused() -> None:
    over_cap = [
        _web_locator(f"https://example.invalid/{index}")
        for index in range(MAX_WEB_LOCATORS_PER_FINDING + 1)
    ]
    with pytest.raises(ValueError, match="web locators; cap is"):
        await _run_with_locators(over_cap)


@pytest.mark.asyncio
async def test_internal_locator_count_is_not_capped() -> None:
    """The count cap bounds retrieved evidence only; internal locators are free."""
    internal = [f"compiler.py:{index}" for index in range(200)]
    result = await _run_with_locators(internal)
    assert result["research_findings"][0]["locators"] == internal


@pytest.mark.asyncio
async def test_locator_of_unsupported_type_is_refused() -> None:
    with pytest.raises(TypeError, match=r"must be a str .* or a dict"):
        await _run_with_locators([["compiler.py:402"]])
