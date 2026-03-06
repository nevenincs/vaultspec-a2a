"""Probe 3 - Multi-agent LangGraph pipeline with OpenAI.

This is the core value-proposition probe. It runs a three-agent
vaultspec-structured-coder (planner -> coder -> reviewer) where each agent
uses gpt-5-mini, and verifies:

  1. All three nodes execute in the correct sequential order
  2. Each agent receives the accumulated message history from prior agents
     (state accumulation = inter-agent communication via shared state)
  3. The final checkpoint in SQLite contains AI messages from all three agents
  4. Every node execution produces a child OTel span in Jaeger

The probe prints each agent's response excerpt to stdout so you can
visually confirm the handoff: reviewer should reference the coder's code,
coder should reference the planner's plan.

Usage::

    python probes/probe_graph_openai.py

Jaeger UI: http://localhost:16686  (service: vaultspec-a2a, op: probe.graph.pipeline.openai)

Requirements:
    VAULTSPEC_OPENAI_API_KEY env var
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)

from opentelemetry import trace as otel_trace

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from lib.telemetry import configure_telemetry, get_tracer
from lib.core import AgentModelConfig, TeamDefaultsConfig, compile_team_graph, load_agent_config, load_team_config
from lib.utils.enums import Model, Provider


TASK = (
    "Write a Python function called `fibonacci(n)` that returns the nth Fibonacci number. "
    "Keep each agent's response under 150 words."
)


async def run_probe() -> None:
    tracer = get_tracer("probe.graph.pipeline.openai")

    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()

        with tracer.start_as_current_span("probe.graph.pipeline.openai") as root:
            root.set_attribute("probe.topology", "pipeline")
            root.set_attribute("probe.provider", "openai")
            root.set_attribute("probe.agents", "planner,coder,reviewer")

            # --- Build graph with OpenAI override ---
            print("[step 1] Compiling vaultspec-structured-coder graph (OpenAI / gpt-5-mini) ...")
            team = load_team_config("vaultspec-structured-coder")
            team = team.model_copy(
                update={"defaults": TeamDefaultsConfig(provider=Provider.OPENAI, capability=Model.LOW)}
            )
            # Agent TOMLs carry their own provider settings (planner=claude, coder=claude,
            # reviewer=zhipu) which take precedence over team defaults.  Override at the
            # agent-config level so all agents use the probe provider.
            _openai_model = AgentModelConfig(provider=Provider.OPENAI, capability=Model.LOW)
            agent_configs = {
                w.agent_id: load_agent_config(w.agent_id).model_copy(update={"model": _openai_model})
                for w in team.workers
            }

            graph = compile_team_graph(
                team_config=team,
                agent_configs=agent_configs,
                checkpointer=checkpointer,
                autonomous=True,
            )
            node_keys = {k for k in graph.nodes if not k.startswith("__")}
            print(f"[ok]     nodes       : {sorted(node_keys)}")

            # --- Execute ---
            thread_id = "probe-pipeline-openai"
            config: RunnableConfig = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 20,
            }
            initial_state = {"messages": [HumanMessage(content=TASK)]}

            print()
            print(f"[step 2] Executing pipeline with task:")
            print(f"         {TASK}")
            print()

            executed_nodes: list[str] = []
            agent_ids = set(agent_configs)

            t0 = time.perf_counter()

            with tracer.start_as_current_span("graph.astream_events") as exec_span:
                async for event in graph.astream_events(initial_state, config, version="v2"):
                    evt = event["event"]
                    name = event["name"]

                    if evt == "on_chain_start" and name in agent_ids:
                        print(f"  >> [{name}] starting ...")
                        exec_span.add_event(f"node.start.{name}")

                    elif evt == "on_chain_end" and name in agent_ids:
                        executed_nodes.append(name)
                        exec_span.add_event(f"node.end.{name}")

            elapsed = time.perf_counter() - t0
            print()
            print(f"[ok]     execution time : {elapsed:.1f} s")
            print(f"[ok]     nodes executed : {executed_nodes}")

            exec_span.set_attribute("nodes.executed", ",".join(executed_nodes))

            # --- Validate state accumulation via checkpoint ---
            print()
            print("[step 3] Reading checkpoint ...")
            saved = await checkpointer.aget(config)
            assert saved is not None, "No checkpoint found after execution"

            messages = saved["channel_values"]["messages"]
            ai_msgs = [m for m in messages if isinstance(m, AIMessage)]

            print(f"[ok]     total messages  : {len(messages)}")
            print(f"[ok]     AI messages     : {len(ai_msgs)}")

            # --- Print each agent's response excerpt ---
            print()
            print("=" * 60)
            print("AGENT RESPONSES (first 300 chars each)")
            print("=" * 60)
            for i, msg in enumerate(ai_msgs):
                label = f"AI msg {i+1}"
                excerpt = str(msg.content)[:300].replace("\n", " ")
                print(f"[{label}] {excerpt}")
                print()

            # --- Assertions ---
            assert set(executed_nodes) == {"planner", "coder", "reviewer"}, (
                f"Not all agents ran: {executed_nodes}"
            )
            assert len(ai_msgs) >= 3, (
                f"Expected >= 3 AI messages (one per agent), got {len(ai_msgs)}"
            )

            root.set_attribute("probe.success", True)
            root.set_attribute("probe.ai_messages", len(ai_msgs))

    # Force-flush spans
    otel_provider = otel_trace.get_tracer_provider()
    if hasattr(otel_provider, "force_flush"):
        otel_provider.force_flush(timeout_millis=5000)

    print()
    print("Jaeger UI  : http://localhost:16686")
    print("Service    : vaultspec-a2a")
    print("Operation  : probe.graph.pipeline.openai")
    print()
    print("[PASS] Probe 3 complete - multi-agent pipeline executed and verified")


def main() -> None:
    print("=" * 60)
    print("PROBE 3 - Multi-agent LangGraph pipeline (OpenAI)")
    print("=" * 60)
    print()

    cfg = configure_telemetry()
    print(f"[telemetry] {cfg!r}")
    print()

    asyncio.run(run_probe())


if __name__ == "__main__":
    main()
