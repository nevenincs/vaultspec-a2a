"""Tests for the supervisor node routing logic."""

from typing import Any

import pytest

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.constants import TAG_NOSTREAM

from ..context import CONTEXT_LIMIT
from ..nodes.supervisor import create_supervisor_node
from ..state import TeamState


class _StubChatModel(BaseChatModel):
    """Minimal real BaseChatModel subclass that returns a fixed response.

    Uses the real LangChain base class — no mocking involved.
    """

    response_text: str
    # Captures tags from the last invocation config for TAG_NOSTREAM assertions
    captured_tags: list[str] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Capture tags from run_manager config if available
        if run_manager is not None:
            tags = getattr(run_manager, "tags", [])
            # Store on class so tests can inspect without instance reference
            _StubChatModel.captured_tags = list(tags)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response_text))]
        )

    @property
    def _llm_type(self) -> str:
        return "stub"


def _make_state() -> TeamState:
    return {  # type: ignore[return-value]
        "messages": [HumanMessage(content="do something")],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test",
        "token_usage": {},
        "next": "",
    }


# ---------------------------------------------------------------------------
# T02 — substring routing collision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_routing_substring_collision() -> None:
    """Longer option wins when one worker name is a substring of another.

    T02: with workers ["code", "coder"], a supervisor response containing
    "the coder should handle this" must route to "coder" (longer match),
    not "code" (which is a substring of "coder").
    """
    model = _StubChatModel(response_text="the coder should handle this")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["code", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "coder", (
        f"Expected 'coder' but got {result['next']!r} — "
        "substring collision: 'code' must not shadow 'coder'"
    )


@pytest.mark.asyncio
async def test_supervisor_routing_exact_match_preferred() -> None:
    """Exact match always wins over substring scan."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["code", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "coder"


@pytest.mark.asyncio
async def test_supervisor_routing_finish() -> None:
    """FINISH exact match routes to FINISH."""
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "FINISH"


@pytest.mark.asyncio
async def test_supervisor_routing_unparseable_defaults_to_finish() -> None:
    """Unparseable response defaults to FINISH."""
    model = _StubChatModel(response_text="I have no idea what to do next!")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "FINISH"
    assert "routing_error" in result
    assert "supervisor could not parse route from" in result["routing_error"]


# ---------------------------------------------------------------------------
# T03 — routing_error field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_sets_routing_error_on_parse_failure() -> None:
    """routing_error is set in state when supervisor response is unparseable.

    T03: on FINISH fallback caused by parse failure (not an intentional FINISH),
    the supervisor must return routing_error containing the raw response text.
    """
    gibberish = "xyzzy forty-two blorp"
    model = _StubChatModel(response_text=gibberish)
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())

    assert result["next"] == "FINISH"
    assert "routing_error" in result, "routing_error key must be present on parse failure"
    assert gibberish in result["routing_error"], (
        f"routing_error should contain the raw response; got: {result['routing_error']!r}"
    )


@pytest.mark.asyncio
async def test_supervisor_no_routing_error_on_clean_finish() -> None:
    """routing_error must NOT be set when the supervisor intentionally responds FINISH."""
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())

    assert result["next"] == "FINISH"
    assert "routing_error" not in result, (
        "routing_error must not be set when FINISH is an exact match"
    )


# ---------------------------------------------------------------------------
# T06 — context compaction in supervisor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_compacts_on_large_state() -> None:
    """Supervisor compacts messages when state exceeds 80% of CONTEXT_LIMIT.

    T06: When the conversation history is large, compact_context is applied
    before building the messages list. After compaction the supervisor still
    routes correctly (compaction is transparent to routing).
    """
    # Build a state whose messages exceed the 80% threshold.
    # CONTEXT_LIMIT = 120_000 tokens; threshold = 96_000 tokens.
    # estimate_tokens uses 4 chars/token, so we need > 96_000 * 4 = 384_000 chars.
    large_content = "x" * 400_000  # ~100_000 tokens — above threshold
    large_state: TeamState = {  # type: ignore[assignment]
        "messages": [HumanMessage(content=large_content)],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test",
        "token_usage": {},
        "next": "",
    }

    model = _StubChatModel(response_text="planner")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    # Must not raise and must route correctly despite large state
    result = await node(large_state)
    assert result["next"] == "planner"


# ---------------------------------------------------------------------------
# T07 — TAG_NOSTREAM applied to supervisor routing invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_routing_uses_tag_nostream() -> None:
    """Supervisor invokes the routing model with TAG_NOSTREAM to suppress streaming.

    T07: model.with_config({"tags": [TAG_NOSTREAM]}) is called before ainvoke,
    so the routing tokens do not appear in on_chat_model_stream events emitted
    to the UI. We verify TAG_NOSTREAM is present in the run_manager tags
    captured during _generate.
    """
    _StubChatModel.captured_tags = []  # reset before test
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "coder"

    # TAG_NOSTREAM must have been present in the config tags during ainvoke
    assert TAG_NOSTREAM in _StubChatModel.captured_tags, (
        f"Expected TAG_NOSTREAM ({TAG_NOSTREAM!r}) in captured tags, "
        f"got: {_StubChatModel.captured_tags!r}"
    )


# ---------------------------------------------------------------------------
# ADR-022 — validation error gate blocks FINISH
# ---------------------------------------------------------------------------


def _make_state_with_errors(errors: list[str]) -> TeamState:
    state = _make_state()
    state["validation_errors"] = errors  # type: ignore[typeddict-unknown-key]
    return state


@pytest.mark.asyncio
async def test_supervisor_validation_error_gate_blocks_finish() -> None:
    """When validation_errors are present, FINISH is blocked and rerouted to workers[0].

    ADR-022: supervisor must not allow FINISH while validation errors remain.
    """
    model = _StubChatModel(response_text="FINISH")
    workers = ["planner", "coder"]
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=workers,
    )

    state = _make_state_with_errors(["missing return type", "unused import"])
    result = await node(state)

    assert result["next"] == "planner", (
        f"Expected reroute to first worker 'planner', got {result['next']!r}"
    )
    assert "routing_error" in result
    assert "FINISH blocked" in result["routing_error"]
    assert "2 validation error(s)" in result["routing_error"]


@pytest.mark.asyncio
async def test_supervisor_validation_error_gate_allows_finish_when_no_errors() -> None:
    """FINISH proceeds normally when validation_errors is empty or absent."""
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    # No validation_errors key at all
    result = await node(_make_state())
    assert result["next"] == "FINISH"
    assert "routing_error" not in result

    # Empty validation_errors list
    state = _make_state_with_errors([])
    result = await node(state)
    assert result["next"] == "FINISH"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_supervisor_validation_error_gate_does_not_block_worker_route() -> None:
    """Routing to a worker (not FINISH) is unaffected by validation errors."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    state = _make_state_with_errors(["some error"])
    result = await node(state)
    assert result["next"] == "coder"
    assert "routing_error" not in result
