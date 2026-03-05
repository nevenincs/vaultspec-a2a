"""Full 6-dimension evaluation suite (ADR-027).

Intended for nightly CI runs. Requires ``LANGSMITH_API_KEY`` and
model API keys in environment.

Usage::

    uv run python -m evals.suites.nightly
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_nightly() -> None:
    """Execute all 6 evaluation dimensions against LangSmith datasets."""
    logger.info("Nightly evaluation suite starting...")
    logger.info(
        "Dimensions: routing, gate_compliance, plan_quality, "
        "code_correctness, reviewer_completeness, e2e"
    )

    # TODO: Wire aevaluate() calls once LangSmith datasets are populated.
    # Each dimension follows the pattern:
    #
    #   from langsmith import aevaluate
    #   results = await aevaluate(
    #       target_fn,
    #       data="vaultspec-{dimension}-v1",
    #       evaluators=[dimension_evaluator],
    #       num_repetitions=3,
    #   )
    #
    # See ADR-027 section 2.2 for full specification.

    logger.info(
        "Nightly suite scaffold complete. "
        "Populate LangSmith datasets to enable live evaluation."
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_nightly())
    except KeyboardInterrupt:
        sys.exit(130)
