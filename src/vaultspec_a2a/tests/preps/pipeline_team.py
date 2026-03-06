"""Scenario: planner + coder + reviewer pipeline team."""

import asyncio
import logging

from ._runner import print_trace_url, run_scenario, setup_graph


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    print("=== preps: pipeline_team ===")
    print("Team: vaultspec-structured-coder | Topology: pipeline | autonomous=False\n")

    async with setup_graph("vaultspec-structured-coder", autonomous=False) as graph:
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
