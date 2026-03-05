"""Scenario: fully autonomous team (no interrupts, pipeline_loop)."""

import asyncio
import logging

from ._runner import print_trace_url, run_scenario, setup_graph


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    print("=== preps: autonomous ===")
    print("Team: mock-autonomous | Topology: pipeline_loop | autonomous=True\n")

    graph, checkpointer = await setup_graph("mock-autonomous", autonomous=True)
    try:
        await run_scenario(
            graph,
            "Refactor the database layer to use connection pooling.",
            thread_id="preps-autonomous-001",
        )
    finally:
        print_trace_url("preps-autonomous-001")


if __name__ == "__main__":
    asyncio.run(main())
