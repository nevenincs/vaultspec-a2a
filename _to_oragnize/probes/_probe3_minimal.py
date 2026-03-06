"""Minimal graph execution test - run directly to see errors."""
import asyncio
import sys
import traceback
sys.path.insert(0, ".")

async def main():
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langchain_core.messages import HumanMessage, AIMessage
    from lib.core import TeamDefaultsConfig, compile_team_graph, load_agent_config, load_team_config
    from lib.utils.enums import Model, Provider

    print("step 1: loading team config")
    team = load_team_config("vaultspec-structured-coder")
    team = team.model_copy(update={"defaults": TeamDefaultsConfig(provider=Provider.OPENAI, capability=Model.LOW)})
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    print("agents:", list(agent_configs))

    print("step 2: creating checkpointer")
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()

        print("step 3: compiling graph")
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            autonomous=True,
        )
        print("graph nodes:", sorted(k for k in graph.nodes if not k.startswith("__")))

        print("step 4: running astream_events")
        config = {"configurable": {"thread_id": "probe-minimal"}, "recursion_limit": 20}
        state = {"messages": [HumanMessage(content="Write a fibonacci function in Python. Be brief.")]}

        executed = []
        async for event in graph.astream_events(state, config, version="v2"):
            name = event["name"]
            ev = event["event"]
            if ev == "on_chain_start" and name in agent_configs:
                print(f"  >> node start: {name}")
            elif ev == "on_chain_end" and name in agent_configs:
                executed.append(name)
                print(f"  >> node done : {name}")

        print("executed:", executed)

        print("step 5: reading checkpoint")
        saved = await checkpointer.aget(config)
        msgs = saved["channel_values"]["messages"]
        ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]
        print(f"total messages: {len(msgs)}, AI messages: {len(ai_msgs)}")
        for i, m in enumerate(ai_msgs):
            print(f"  AI[{i}]: {str(m.content)[:300]}")

    print("DONE")

try:
    asyncio.run(main())
except Exception:
    traceback.print_exc()
    sys.exit(1)
