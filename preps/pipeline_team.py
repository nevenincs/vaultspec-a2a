"""Scenario: planner + coder + reviewer pipeline_loop team."""

import asyncio
import logging

from ._runner import print_trace_url, run_scenario, setup_graph


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    print("=== preps: pipeline_team ===")
    print("Team: mock-autonomous | Topology: pipeline_loop | autonomous=False\n")

    graph, checkpointer = await setup_graph("mock-autonomous", autonomous=False)
    try:
        await run_scenario(
            graph,
            "Design and implement a URL shortener service.",
            thread_id="preps-pipeline-team-001",
        )
    finally:
        print_trace_url("preps-pipeline-team-001")


if __name__ == "__main__":
    asyncio.run(main())
