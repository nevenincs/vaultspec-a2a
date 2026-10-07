"""The config-injection contract every node in this package depends on.

LangGraph decides whether to pass ``config`` into a node by reading the
parameter's annotation off ``inspect.signature`` and testing membership in a
fixed set of accepted spellings. Every node module here carries
``from __future__ import annotations``, which stringizes annotations at
definition time, so a modern ``config: RunnableConfig | None`` reaches that
test as the string ``"RunnableConfig | None"`` - not a member, so injection is
silently dropped and the node runs with no config at all.

The symptom is easy to misattribute: with no config there are no callbacks, so
a graph turn emits no ``on_chat_model_*`` event even though the model runs and
returns real content, and the thread id, tags and run metadata never reach the
provider call either. ``accepting_runnable_config`` stamps the live union
object back onto ``__annotations__`` to restore it.

That workaround stands on a LangGraph internal, so this file pins the contract
from both sides: with the stamp a node really is handed its config, and
WITHOUT it the config really is dropped. If the library ever accepts the
stringized spelling, the second test fails and says the workaround is no
longer load-bearing; if it changes which spellings it accepts, the first fails
and says the stamp no longer works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langgraph.graph import END, START

from ....testing import (
    add_test_node,
    ainvoke_test_graph,
    compile_test_graph,
    new_state_graph,
)
from ...nodes._config_contract import (
    RUNNABLE_CONFIG_ANNOTATION,
    accepting_runnable_config,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ....thread.state import TeamState

_SEEN: dict[str, object] = {}


async def _stamped_node(
    state: TeamState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """A node whose ``config`` annotation was stamped back to a live union."""
    del state
    _SEEN["stamped"] = config
    return {}


async def _unstamped_node(
    state: TeamState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """The same node, left with the stringized annotation the source has."""
    del state
    _SEEN["unstamped"] = config
    return {}


_stamped_node = accepting_runnable_config(_stamped_node)


def _base_state() -> dict[str, Any]:
    return {
        "messages": [],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "config-contract",
        "token_usage": {},
    }


async def _run(node: Any, name: str) -> object:
    builder = new_state_graph()
    add_test_node(builder, name, node)
    builder.add_edge(START, name)
    builder.add_edge(name, END)
    graph = compile_test_graph(builder)
    await ainvoke_test_graph(
        graph, _base_state(), {"configurable": {"thread_id": "config-contract"}}
    )
    return _SEEN[name]


@pytest.mark.asyncio
async def test_a_stamped_node_is_handed_the_run_config() -> None:
    """The stamp restores injection: the node receives a real config."""
    received = await _run(_stamped_node, "stamped")

    assert isinstance(received, dict), (
        "config was not injected into a stamped node; the annotation LangGraph "
        "accepts has changed and accepting_runnable_config no longer restores it"
    )
    configurable: dict[str, Any] = (
        cast("dict[str, Any]", received).get("configurable") or {}
    )
    assert configurable.get("thread_id") == "config-contract"


@pytest.mark.asyncio
async def test_an_unstamped_node_is_handed_nothing() -> None:
    """Without the stamp the config really is dropped.

    This is the half that says the workaround is still needed. If LangGraph
    starts accepting the stringized ``"RunnableConfig | None"`` spelling this
    fails, and the stamp - and this file - can go.
    """
    with pytest.warns(UserWarning, match="config"):
        received = await _run(_unstamped_node, "unstamped")

    assert received is None, (
        "LangGraph now injects config for a stringized annotation; "
        "accepting_runnable_config is no longer load-bearing"
    )


def test_the_stamped_annotation_is_a_live_object_not_a_string() -> None:
    """What gets stamped is the type, not its source spelling.

    Stamping the string back would be a no-op: the string is exactly what the
    injector refuses. The live union is accepted because
    ``RunnableConfig | None == Optional[RunnableConfig]`` holds on the object.
    """
    assert not isinstance(RUNNABLE_CONFIG_ANNOTATION, str)
    assert _stamped_node.__annotations__["config"] is RUNNABLE_CONFIG_ANNOTATION
    assert _unstamped_node.__annotations__["config"] == "RunnableConfig | None"
