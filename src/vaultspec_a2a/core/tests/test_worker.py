"""Tests for the worker node execution logic."""

from typing import Any

import pytest

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.outputs import ChatResult
from langgraph.errors import GraphBubbleUp, GraphInterrupt
from langgraph.types import Interrupt

from ..exceptions import WorkerExecutionError
from ..nodes.worker import create_worker_node
from ..state import TeamState


class _GraphInterruptModel(BaseChatModel):
    """Real BaseChatModel subclass that raises GraphInterrupt on ainvoke.

    Simulates a permission interrupt surfaced from inside a node.
    """

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise GraphInterrupt(
            (
                Interrupt(
                    value={"type": "permission_request"},
                    resumable=True,
                    ns=(),
                    when="during",
                ),
            )
        )

    @property
    def _llm_type(self) -> str:
        return "graph-interrupt"


class _AlwaysFailModel(BaseChatModel):
    """Real BaseChatModel subclass that always raises on ainvoke."""

    error_message: str = "simulated model failure"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise RuntimeError(self.error_message)

    @property
    def _llm_type(self) -> str:
        return "always-fail"


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
# T04 — WorkerExecutionError wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_exception_wraps_with_context() -> None:
    """Worker node wraps model errors as WorkerExecutionError with agent context.

    T04: When ainvoke raises, the worker re-raises as WorkerExecutionError
    carrying agent_id and model_type so callers can attribute the failure
    without inspecting the exception chain.
    """
    model = _AlwaysFailModel(error_message="boom")
    node = create_worker_node(
        model=model, system_prompt="You are a worker.", name="coder"
    )

    with pytest.raises(WorkerExecutionError) as exc_info:
        await node(_make_state())

    err = exc_info.value
    assert err.worker == "coder"
    assert err.model == "_AlwaysFailModel"
    assert "coder" in str(err)
    assert "_AlwaysFailModel" in str(err)


@pytest.mark.asyncio
async def test_worker_exception_chains_original_cause() -> None:
    """WorkerExecutionError.__cause__ is the original exception (raise ... from exc)."""
    original_message = "network timeout"
    model = _AlwaysFailModel(error_message=original_message)
    node = create_worker_node(
        model=model, system_prompt="You are a worker.", name="planner"
    )

    with pytest.raises(WorkerExecutionError) as exc_info:
        await node(_make_state())

    cause = exc_info.value.__cause__
    assert cause is not None, "WorkerExecutionError must chain the original exception"
    assert original_message in str(cause)


@pytest.mark.asyncio
async def test_worker_graphinterrupt_not_wrapped() -> None:
    """GraphBubbleUp (and GraphInterrupt) must propagate unwrapped through the worker.

    T04: The except GraphBubbleUp: raise guard ensures that LangGraph interrupt
    signals are never caught and re-raised as WorkerExecutionError. Without this
    guard, the human-in-the-loop permission flow would break — LangGraph would
    see WorkerExecutionError instead of GraphInterrupt and attempt to retry
    rather than surfacing the interrupt to the client.
    """
    model = _GraphInterruptModel()
    node = create_worker_node(
        model=model, system_prompt="You are a worker.", name="coder"
    )

    # GraphInterrupt must pass through unwrapped — NOT caught as WorkerExecutionError
    with pytest.raises(GraphBubbleUp) as exc_info:
        await node(_make_state())

    # Must NOT be wrapped in WorkerExecutionError
    assert not isinstance(exc_info.value, WorkerExecutionError), (
        "GraphBubbleUp must not be wrapped in WorkerExecutionError"
    )
    # Must be the original GraphInterrupt type
    assert isinstance(exc_info.value, GraphInterrupt)


@pytest.mark.asyncio
async def test_worker_execution_error_is_importable_from_core() -> None:
    """WorkerExecutionError is exported from vaultspec_a2a.core (public API)."""
    from vaultspec_a2a.core import WorkerExecutionError as WorkerExecErr

    assert WorkerExecErr is WorkerExecutionError
