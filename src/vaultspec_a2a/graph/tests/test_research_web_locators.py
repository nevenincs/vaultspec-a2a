"""The research producer emits the web citation channel's typed locators.

Every test here drives the REAL producer over a real ``AcpChatModel`` talking
the real ACP protocol to the simulator subprocess, through the real researcher
branch (whose validation is the contract's enforcement point) and into a real
file-backed checkpoint that is then reopened on a fresh connection. No finding
is ever assigned onto state directly: a direct field-set would prove only that a
dict can be stored, and the defect this Step closes was precisely a channel with
no production emitter behind it.

The malformation tests carry a matching NEGATIVE CONTROL apiece, driving the
un-normalised shape through the same branch validation to prove it is genuinely
refused there. Without the control, a test asserting "the run completed" proves
nothing - it would pass just as well if the malformation were harmless.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ...thread.state import TeamState
from ..compiler import _make_research_producer, _wire_diverge_stage
from ..nodes.diverge import (
    MAX_WEB_LOCATOR_EXCERPT_CHARS,
    MAX_WEB_LOCATOR_URL_CHARS,
    MAX_WEB_LOCATORS_PER_FINDING,
    WEB_LOCATOR_KIND,
    create_researcher_node,
)

if TYPE_CHECKING:
    from ..nodes.diverge import ResearchFindingProducer

SIMULATOR_PATH = Path(__file__).parent / "acp_simulator.py"
PYTHON_EXE = sys.executable

_THREAD_ID = "web-grounding"


def _base_state() -> TeamState:
    return {
        "active_agent": "dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the citation channel.")],
        "next": "",
        "thread_id": "research-web-locators",
        "token_usage": {},
    }


def _researcher_producer(tmp_path: Path, prose: str) -> ResearchFindingProducer:
    """Build the production producer over a simulator that answers with *prose*.

    The prose rides a file rather than argv: the Windows spawn path renders the
    command through ``cmd.exe``, so multi-line or punctuation-heavy agent output
    could not survive as an argument.
    """
    from ...providers.acp_chat_model import AcpChatModel

    response_file = tmp_path / "researcher-turn.txt"
    response_file.write_text(prose, encoding="utf-8")
    model = AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response-file",
            str(response_file),
        ],
        workspace_root=str(tmp_path),
    )
    return _make_research_producer(model, "You are the researcher.")


def _build_graph(producer: ResearchFindingProducer) -> StateGraph:
    """Wire the real diverge stage around a single researcher branch."""
    builder: StateGraph = StateGraph(cast("Any", TeamState))
    dispatch = _wire_diverge_stage(
        builder,
        dispatch_name="research_dispatch",
        synthesis_name="synthesis",
        specs=[{"thread_id": _THREAD_ID, "topic": "web grounding", "instructions": ""}],
        make_researcher=lambda spec: create_researcher_node(spec, producer),
    )

    async def synthesis_node(state: TeamState) -> dict[str, Any]:
        return {"messages": [AIMessage(content="synthesised", name="synthesist")]}

    builder.add_node("synthesis", synthesis_node)
    builder.add_edge(START, dispatch)
    builder.add_edge("synthesis", END)
    return builder


async def _checkpointed_finding(tmp_path: Path, prose: str) -> dict[str, Any]:
    """Run one researcher turn and read its finding back out of the checkpoint.

    The run and the read-back use two different connections to the same on-disk
    checkpoint file, so what is asserted survived the checkpointer's real
    serialisation rather than living in the process that produced it.
    """
    checkpoint_path = tmp_path / "web-locator-checkpoints.sqlite"
    config: dict[str, Any] = {"configurable": {"thread_id": "web-locator-run"}}
    producer = _researcher_producer(tmp_path, prose)

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        await (
            _build_graph(producer)
            .compile(checkpointer=saver)
            .ainvoke(_base_state(), config=cast("Any", config))
        )

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as reopened:
        replayed = (
            await _build_graph(producer)
            .compile(checkpointer=reopened)
            .aget_state(cast("Any", config))
        )

    findings = replayed.values["research_findings"]
    assert len(findings) == 1
    return cast("dict[str, Any]", findings[0])


def _web_locators(finding: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        locator
        for locator in finding["locators"]
        if isinstance(locator, dict) and locator.get("kind") == WEB_LOCATOR_KIND
    ]


def _verbatim_producer(locators: list[Any]) -> ResearchFindingProducer:
    """A producer that emits *locators* untouched, for the negative controls."""

    async def producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "claim": "un-normalised finding",
            "locators": locators,
            "source_thread": spec["thread_id"],
        }

    return producer


async def _drive_verbatim(locators: list[Any]) -> dict[str, Any]:
    """Push *locators* through the real branch validation, unmodified."""
    node = create_researcher_node(
        {"thread_id": _THREAD_ID}, _verbatim_producer(locators)
    )
    return await node(_base_state())


# ---------------------------------------------------------------------------
# Acceptance: a cited retrieval reaches checkpointed state as a typed locator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cited_sources_reach_checkpointed_state_as_typed_locators(
    tmp_path: Path,
) -> None:
    """The producer turns a researcher's cited sources into typed locators.

    This is the Step's acceptance driver. The channel had no production emitter:
    the producer returned an empty locator list unconditionally, so the contract
    admitted a shape nothing produced and the submit refusal could not fire in a
    real run. Here a real turn's cited URLs arrive as contract-conformant
    locators in checkpointed state, which is what the disclosure refusal reads.
    """
    prose = "\n".join(
        [
            "Send is the framework-native map-reduce primitive.",
            "Source: https://example.invalid/langgraph/send explains the fan-out.",
            "The events endpoint streams updates (https://example.invalid/engine).",
            "Confirmed again in https://example.invalid/langgraph/send, same page.",
            "Internal grounding stays a bare string: compiler.py:402.",
        ]
    )

    finding = await _checkpointed_finding(tmp_path, prose)

    locators = _web_locators(finding)
    assert [locator["url"] for locator in locators] == [
        "https://example.invalid/langgraph/send",
        "https://example.invalid/engine",
    ], "distinct URLs in first-seen order; a repeat is the same evidence"

    # The trailing ')' closed the prose parenthetical, not the URL: a URL that is
    # not the URL retrieved would send a reader somewhere nobody went.
    assert locators[1]["url"].endswith("/engine")

    # Every locator is contract-shaped, and the branch validation it passed on
    # the way into the checkpoint is what says so.
    for locator in locators:
        assert set(locator) <= {"kind", "url", "retrieved_at", "excerpt"}
        stamped = datetime.fromisoformat(locator["retrieved_at"])
        assert stamped.tzinfo is not None, "retrieved_at is an absolute instant"

    assert locators[0]["excerpt"].startswith("Source: https://example.invalid")
    assert finding["source_thread"] == _THREAD_ID
    assert "map-reduce primitive" in finding["claim"]


@pytest.mark.asyncio
async def test_turn_citing_nothing_produces_no_locators(tmp_path: Path) -> None:
    """A turn with no cited source yields no evidence, not an empty-shaped one."""
    finding = await _checkpointed_finding(
        tmp_path, "The phase machine is documented in compiler.py:402."
    )
    assert finding["locators"] == []


# ---------------------------------------------------------------------------
# Malformation class 1: over-cap excerpt - normalised by truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_cap_excerpt_is_truncated_at_the_producer(tmp_path: Path) -> None:
    """An over-long citing line is elided by the producer, deliberately.

    The validator refuses an over-cap excerpt rather than shortening it, on the
    reasoning that only the producer knows which part of a retrieval carries the
    claim. This is the producer discharging that: the head is kept and the
    elision is marked, so a reader sees that the tail was dropped.
    """
    filler = "the citation channel is capped for a reason " * 80
    prose = f"Source: https://example.invalid/long {filler}"
    assert len(prose) > MAX_WEB_LOCATOR_EXCERPT_CHARS

    finding = await _checkpointed_finding(tmp_path, prose)

    excerpt = _web_locators(finding)[0]["excerpt"]
    assert len(excerpt) <= MAX_WEB_LOCATOR_EXCERPT_CHARS
    assert excerpt.endswith("…"), "the elision is visible, not silent"
    assert excerpt.startswith("Source: https://example.invalid/long")


@pytest.mark.asyncio
async def test_control_over_cap_excerpt_is_refused_by_the_branch() -> None:
    """Negative control: un-truncated, the same excerpt aborts the branch."""
    with pytest.raises(ValueError, match="cap is"):
        await _drive_verbatim(
            [
                {
                    "kind": WEB_LOCATOR_KIND,
                    "url": "https://example.invalid/long",
                    "retrieved_at": "2026-08-01T09:30:00+00:00",
                    "excerpt": "x" * (MAX_WEB_LOCATOR_EXCERPT_CHARS + 1),
                }
            ]
        )


# ---------------------------------------------------------------------------
# Malformation class 2: scheme-less host - normalised by declining to promote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheme_less_host_is_not_promoted_and_no_scheme_is_invented(
    tmp_path: Path,
) -> None:
    """A bare domain-and-path never becomes a locator, and never gains a scheme.

    This is the likelier malformation of the two, and the one where normalising
    by repair would be wrong: http and https are different origins with
    different security properties, so prefixing one asserts a retrieval the run
    never made. Declining to promote costs a weaker disclosure obligation;
    inventing an origin puts a false claim into checkpointed evidence.
    """
    prose = "\n".join(
        [
            "See example.invalid/guide for the walkthrough.",
            "Also www.example.invalid/x and ftp://example.invalid/archive.",
            "Retrieved: https://example.invalid/spec carries the contract.",
        ]
    )

    finding = await _checkpointed_finding(tmp_path, prose)

    # The scheme-bearing source IS promoted in the same turn, so this proves the
    # extractor discriminates rather than merely staying silent.
    assert [locator["url"] for locator in _web_locators(finding)] == [
        "https://example.invalid/spec"
    ]
    assert "example.invalid/guide" in finding["claim"], (
        "the citation survives in the claim prose; only the typed channel abstains"
    )


@pytest.mark.asyncio
async def test_control_scheme_less_host_is_refused_by_the_branch() -> None:
    """Negative control: promoted as-is, a scheme-less URL aborts the branch."""
    with pytest.raises(ValueError, match="url scheme"):
        await _drive_verbatim(
            [
                {
                    "kind": WEB_LOCATOR_KIND,
                    "url": "example.invalid/guide",
                    "retrieved_at": "2026-08-01T09:30:00+00:00",
                }
            ]
        )


# ---------------------------------------------------------------------------
# Malformation class 3: over-cap URL - normalised by declining to promote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_cap_url_is_not_promoted(tmp_path: Path) -> None:
    """An over-cap URL is dropped, never truncated: a prefix is a different URL."""
    long_url = "https://example.invalid/" + "p" * MAX_WEB_LOCATOR_URL_CHARS
    prose = "\n".join(
        [
            f"Retrieved from {long_url} which is absurdly long.",
            "Retrieved from https://example.invalid/short which is not.",
        ]
    )

    finding = await _checkpointed_finding(tmp_path, prose)

    # The in-cap source from the same turn IS promoted: the drop is targeted at
    # the over-cap URL, not the turn.
    assert [locator["url"] for locator in _web_locators(finding)] == [
        "https://example.invalid/short"
    ]


@pytest.mark.asyncio
async def test_control_over_cap_url_is_refused_by_the_branch() -> None:
    """Negative control: an over-cap URL aborts the branch when promoted."""
    with pytest.raises(ValueError, match="cap is"):
        await _drive_verbatim(
            [
                {
                    "kind": WEB_LOCATOR_KIND,
                    "url": "https://example.invalid/" + "p" * MAX_WEB_LOCATOR_URL_CHARS,
                    "retrieved_at": "2026-08-01T09:30:00+00:00",
                }
            ]
        )


# ---------------------------------------------------------------------------
# Malformation class 4: more sources than the per-finding cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locator_count_is_capped_in_first_seen_order(tmp_path: Path) -> None:
    """Beyond the per-finding cap the producer keeps the first sources cited.

    The cap matches the per-branch fetch budget, so a turn citing more sources
    than it could have fetched is citing recall past that point. First-seen order
    makes the kept set deterministic and therefore replay-exact.
    """
    over_cap = MAX_WEB_LOCATORS_PER_FINDING + 4
    prose = "\n".join(
        f"Source {index}: https://example.invalid/s{index:02d}"
        for index in range(over_cap)
    )

    finding = await _checkpointed_finding(tmp_path, prose)

    urls = [locator["url"] for locator in _web_locators(finding)]
    assert len(urls) == MAX_WEB_LOCATORS_PER_FINDING
    assert urls == [
        f"https://example.invalid/s{index:02d}"
        for index in range(MAX_WEB_LOCATORS_PER_FINDING)
    ]


@pytest.mark.asyncio
async def test_control_over_cap_locator_count_is_refused_by_the_branch() -> None:
    """Negative control: one locator past the cap aborts the branch."""
    with pytest.raises(ValueError, match="cap is"):
        await _drive_verbatim(
            [
                {
                    "kind": WEB_LOCATOR_KIND,
                    "url": f"https://example.invalid/s{index:02d}",
                    "retrieved_at": "2026-08-01T09:30:00+00:00",
                }
                for index in range(MAX_WEB_LOCATORS_PER_FINDING + 1)
            ]
        )
