"""Scenario: single coder agent (pipeline topology)."""

import asyncio
import logging

from ._runner import print_trace_url, run_scenario, setup_graph


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    print("=== preps: solo_coder ===")
    print("Team: vaultspec-solo-coder | Topology: pipeline | autonomous=False\n")

    async with setup_graph("vaultspec-solo-coder", autonomous=False) as graph:
        try:
            await run_scenario(
                graph,
                "Write a Python function that checks if a string is a palindrome.",
                thread_id="preps-solo-coder-001",
            )
        finally:
            print_trace_url("preps-solo-coder-001")


if __name__ == "__main__":
    asyncio.run(main())
