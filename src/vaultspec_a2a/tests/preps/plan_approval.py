"""Scenario: plan approval interrupt + human resume."""

import asyncio
import logging

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from ._runner import print_trace_url, setup_graph


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    print("=== preps: plan_approval ===")
    print("Team: vaultspec-adaptive-coder | Topology: star | autonomous=False")
    print("Expects GraphInterrupt on plan approval — will resume with approved=True\n")

    async with setup_graph("vaultspec-adaptive-coder", autonomous=False) as graph:
        thread_id = "preps-plan-approval-001"
        config = {"configurable": {"thread_id": thread_id}}
        input_state = {
            "messages": [
                HumanMessage(content="Implement a REST API for user authentication.")
            ]
        }

        try:
            print("--- Streaming until interrupt ---")
            async for chunk in graph.astream(
                input_state, config, stream_mode=["updates"]
            ):
                if isinstance(chunk, tuple):
                    mode_name, data = chunk
                    print(f"\n[{mode_name}]")
                    if isinstance(data, dict):
                        for key, value in data.items():
                            print(f"  {key}: {str(value)[:200]}")
                else:
                    print(f"\n{chunk}")

        except GraphInterrupt as exc:
            print("\n--- GraphInterrupt received ---")
            print(f"Payload: {exc.args}")
            print("\n--- Resuming with approved=True ---")

            resume_result = await graph.ainvoke(
                Command(resume={"approved": True}),
                config,
            )
            print(f"\nResume result messages: {len(resume_result.get('messages', []))}")

        finally:
            print_trace_url(thread_id)


if __name__ == "__main__":
    asyncio.run(main())
