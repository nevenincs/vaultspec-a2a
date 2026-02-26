import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...providers.factory import ProviderFactory
from ...utils.enums import Provider
from ..graph import compile_team_graph


@pytest_asyncio.fixture
async def checkpointer():
    """Provide an in-memory SQLite checkpointer for tests."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


@pytest.mark.asyncio
async def test_compile_team_graph(checkpointer: AsyncSqliteSaver) -> None:
    """Verify that the graph compiles with the given models and checkpointer."""
    supervisor_model = ProviderFactory.create(Provider.GEMINI)
    worker_model = ProviderFactory.create(Provider.GEMINI)

    graph = compile_team_graph(
        supervisor_model=supervisor_model,
        worker_models={"test_worker": worker_model},
        checkpointer=checkpointer,
    )
    assert graph is not None


@pytest.mark.asyncio
async def test_graph_execution_routing(checkpointer: AsyncSqliteSaver) -> None:
    """Verify end-to-end execution, routing, and checkpointer state persistence."""
    supervisor_model = ProviderFactory.create(Provider.GEMINI)
    # Use Gemini for core routing test
    worker_model = ProviderFactory.create(Provider.GEMINI)

    graph = compile_team_graph(
        supervisor_model=supervisor_model,
        worker_models={"echo_worker": worker_model},
        checkpointer=checkpointer,
    )

    initial_state = {
        "messages": [
            HumanMessage(
                content="Tell the echo_worker to say exactly 'HelloWorldFromGraph' and then you should FINISH the task."
            )
        ],
    }

    config = {"configurable": {"thread_id": "test_routing_thread"}, "recursion_limit": 5}

    # Execute the graph and collect nodes that finished
    executed_nodes = []
    try:
        async for event in graph.astream_events(initial_state, config, version="v2"):
            if event["event"] == "on_chain_end":
                node_name = event["name"]
                if node_name in ("supervisor", "echo_worker"):
                    print(f"Node {node_name} finished!")
                    executed_nodes.append(node_name)
    except Exception as e:
        print(f"Graph execution stopped: {e}")

    # Validate state was checkpointed
    saved_state = await checkpointer.aget(config)
    assert saved_state is not None
    channel_values = saved_state["channel_values"]
    assert "messages" in channel_values

    # We expect supervisor to run, then worker, then maybe supervisor evaluates FINISH
    assert "supervisor" in executed_nodes
    assert "echo_worker" in executed_nodes

    messages = channel_values["messages"]
    assert len(messages) > 1

    # Check that the worker successfully emitted the phrase
    found_phrase = any(
        "helloworldfromgraph" in str(msg.content).lower()
        for msg in messages
        if msg.type == "ai"
    )
    assert found_phrase, f"Expected phrase not found in generated messages: {messages}"
