"""Smoke evaluation suite -- dimensions 1 + 2 only (ADR-027).

Fast suite for PR-triggered runs. Tests only deterministic dimensions
(routing accuracy and phase gate compliance).

Usage::

    uv run python -m evals.suites.smoke
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_smoke() -> None:
    """Execute routing + gate compliance evaluations."""
    logger.info("Smoke evaluation suite starting...")
    logger.info("Dimensions: routing, gate_compliance")

    # TODO: Wire aevaluate() calls once LangSmith datasets are populated.

    logger.info(
        "Smoke suite scaffold complete. "
        "Populate LangSmith datasets to enable live evaluation."
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_smoke())
    except KeyboardInterrupt:
        sys.exit(130)
