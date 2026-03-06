"""Scenario: fully autonomous team (no interrupts, star topology)."""

import asyncio
import logging

from ._runner import print_trace_url, run_scenario, setup_graph


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    print("=== preps: autonomous ===")
    print("Team: vaultspec-adaptive-coder | Topology: star | autonomous=True\n")

    async with setup_graph("vaultspec-adaptive-coder", autonomous=True) as graph:
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
