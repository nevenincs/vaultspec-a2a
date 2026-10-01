"""One real compiled graph whose single node's behaviour is chosen by input.

Replaces seven hand-written ``StreamableGraph`` stubs this suite used to carry
(``_SilentGraph``, ``_InterruptingGraph``, ``_RecursingGraph``, ``_FailingGraph``,
``_ProviderCancelledGraph``, ``_StallingGraph``, ``_LongStepBudgetGraph``):
forcing a different failure used to mean swapping in a different hand-rolled
class, so a real protocol change was ten edits instead of one. Every scenario
below runs the SAME real ``StateGraph`` through a real ``InMemorySaver`` -
only the instruction the one node reads off its input changes, and every
error it raises (``RuntimeError``, ``AcpPromptCancelledError``,
``GraphRecursionError``, a real park via ``interrupt()``) is what LangGraph's
own runtime actually produces, not a stand-in for it.

Not a fit for every graph-shaped test in this package: ``_DelayedGraph``
(``worker/tests/test_state_projection_timeout_knob.py``) controls a
checkpoint READ's latency to a precise duration, which a real graph cannot
guarantee, and ``_cancellable_stalling_graph`` in this module's sibling test
file already drives a real blocked node. Neither is this fixture's job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from ...graph.nodes._config_contract import accepting_runnable_config
from ...graph.tests._state_graph_helpers import add_test_node, compile_test_graph
from ...providers import AcpPromptCancelledError
from ..custom_writes import emit_custom_node_write

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

__all__ = [
    "ERROR_INJECTION_NODE",
    "InjectedSignal",
    "build_error_injecting_graph",
]

#: The one node every scenario below runs. Real ``StateSnapshot``s this
#: fixture produces (an unresolved interrupt, a normal completion) name it
#: directly, so a caller asserting on task or agent identity asserts on this.
ERROR_INJECTION_NODE = "inject"


class InjectedSignal(BaseException):
    """A ``BaseException`` that is not an ``Exception``: a signal, not a failure.

    Python reserves that branch of the hierarchy for exceptions a handler of
    ordinary errors must let through, so this stands for any such signal a
    node's dependencies might raise.
    """


class InjectableGraphInput(TypedDict, total=False):
    """The node's own instructions, read directly off the graph input.

    Every field is optional and independent; a caller sets only the one its
    scenario needs. An input setting none of them completes the node
    normally, with an empty state update.
    """

    raise_message: str
    """Raise ``RuntimeError(raise_message)`` (or see ``raise_cancelled``)."""

    raise_cancelled: bool
    """Raise a real ``AcpPromptCancelledError`` instead of a plain ``RuntimeError``,
    carrying ``raise_message`` (defaulted when absent)."""

    interrupt_payload: object
    """Call the real ``interrupt()`` builtin with this value."""

    stall_seconds: float
    """``await asyncio.sleep`` this long before completing normally."""

    loop: bool
    """Route back to this same node instead of ending the graph, so a caller
    pairing this with a low ``recursion_limit`` in its run config gets a real
    ``GraphRecursionError`` from LangGraph's own Pregel loop."""

    custom_write: str
    """Push this text through :func:`emit_custom_node_write`, stamped with
    this node's own identity, before acting on any other field."""

    raise_signal: str
    """Raise :class:`InjectedSignal` carrying this text."""


async def _inject(
    state: InjectableGraphInput,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    custom_write = state.get("custom_write")
    if custom_write:
        emit_custom_node_write(custom_write, config=config)
    signal = state.get("raise_signal")
    if signal is not None:
        raise InjectedSignal(signal)
    if state.get("raise_cancelled"):
        raise AcpPromptCancelledError(
            state.get("raise_message", "ACP prompt was cancelled by the agent"),
            data={"acp_stop_reason": "cancelled"},
        )
    raise_message = state.get("raise_message")
    if raise_message is not None:
        raise RuntimeError(raise_message)
    payload = state.get("interrupt_payload")
    if payload is not None:
        interrupt(payload)
        return {}
    stall_seconds = state.get("stall_seconds")
    if stall_seconds is not None:
        import asyncio

        await asyncio.sleep(stall_seconds)
        return {}
    return {"loop": True} if state.get("loop") else {}


# ``from __future__ import annotations`` stringizes ``config``'s annotation to
# "RunnableConfig | None", which LangGraph's injector does not recognise (its
# own fixed set names only the ``Optional[...]`` spelling) - see
# ``graph/nodes/_config_contract.py``. Without this, ``config`` silently
# arrives as ``None`` and a custom write's node stamp would silently be
# ``None`` too, wrong for exactly the reason this fixture exists to catch.
_inject = accepting_runnable_config(_inject)


def build_error_injecting_graph() -> Any:
    """Compile a fresh instance of the one shared error-injecting graph.

    A fresh compile per call, not a shared singleton: a caller that sets the
    real compiled object's ``step_timeout`` attribute (the compiler's own
    convention, ``graph/compiler.py``) to reproduce a team preset's declared
    budget must not leak that value onto an unrelated test.
    """
    builder: StateGraph[Any, None, Any, Any] = StateGraph(
        cast("Any", InjectableGraphInput)
    )
    add_test_node(builder, ERROR_INJECTION_NODE, _inject)
    builder.set_entry_point(ERROR_INJECTION_NODE)
    builder.add_conditional_edges(
        ERROR_INJECTION_NODE,
        lambda state: ERROR_INJECTION_NODE if state.get("loop") else END,
    )
    return compile_test_graph(builder, checkpointer=InMemorySaver())
