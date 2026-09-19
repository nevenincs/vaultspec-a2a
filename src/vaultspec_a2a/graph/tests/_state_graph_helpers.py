"""One typed call boundary for langgraph ``StateGraph`` construction in tests.

langgraph's ``add_node``/``compile``/``ainvoke`` overloads default several
parameters (``cache_policy: CachePolicy[Unknown]``,
``checkpointer: BaseCheckpointSaver[Unknown]``, and similar) to a bare,
unparametrized generic in their own shipped source -- not a stub gap, so it
cannot be fixed by annotating the arguments a given call passes. Every test
that builds a ``StateGraph`` routes through these three helpers instead of the
library methods directly, so that irreducible diagnostic is paid once, here,
rather than at every call site across the test tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph import StateGraph
    from langgraph.types import Command, RetryPolicy

__all__ = ["add_test_node", "ainvoke_test_graph", "compile_test_graph"]


class _TypedBuilder(Protocol):
    """The exact ``StateGraph`` surface these helpers use, precisely typed.

    langgraph declares ``cache_policy``/``checkpointer`` as bare unparametrized
    generics in its own source, so the member itself reads as partially unknown
    no matter what a caller passes. Declaring the subset we depend on, and
    viewing the builder through it, is what makes every call below checked
    instead of unknown. It is a narrower claim than langgraph's real signature,
    never a wider one, so a call that type-checks here type-checks there.
    """

    def add_node(
        self,
        node: str,
        action: Callable[..., Any],
        *,
        metadata: dict[str, str] | None = ...,
        retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = ...,
    ) -> object: ...

    def compile(
        self,
        checkpointer: BaseCheckpointSaver[str] | bool | None = ...,
        *,
        interrupt_before: list[str] | None = ...,
    ) -> Any: ...


def add_test_node(
    builder: StateGraph[Any, None, Any, Any],
    name: str,
    node: Callable[..., Any],
    *,
    metadata: dict[str, str] | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = None,
) -> None:
    """Add a node to ``builder`` behind one fully-typed call boundary."""
    cast("_TypedBuilder", builder).add_node(
        name, node, metadata=metadata, retry_policy=retry_policy
    )


def compile_test_graph(
    builder: StateGraph[Any, None, Any, Any],
    *,
    checkpointer: BaseCheckpointSaver[str] | bool | None = None,
    interrupt_before: list[str] | None = None,
) -> Any:
    """Compile ``builder`` behind one fully-typed call boundary."""
    return cast("_TypedBuilder", builder).compile(
        checkpointer, interrupt_before=interrupt_before
    )


async def ainvoke_test_graph(
    graph: Any,
    state: dict[str, Any] | Command[str],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Invoke a compiled test graph behind one fully-typed call boundary."""
    result = await graph.ainvoke(state, config)
    return cast("dict[str, Any]", result)
