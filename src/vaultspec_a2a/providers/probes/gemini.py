"""ACP probe for the Gemini CLI agent (``gemini --experimental-acp``).

Runs the full ACP protocol lifecycle — ``initialize`` -> ``session/new`` ->
``session/prompt`` — against a real Gemini CLI subprocess.  Refreshes the
local OAuth credentials via :func:`~vaultspec_a2a.providers.gemini_auth.refresh_gemini_token`
before spawning so that an expired token never causes a silent hang.

Run directly::

    python -m vaultspec_a2a.providers.probes.gemini

Exit code 0 on success, 1 on failure.  All protocol traffic is logged at DEBUG.
"""

import asyncio
import logging
import sys

from ...utils.enums import MODEL_MAP, Model, Provider
from ...utils.logging import setup_logging
from ..gemini_auth import refresh_gemini_token
from ._protocol import ProbeResult, run_probe


__all__ = ["main"]

logger = logging.getLogger(__name__)

_PROMPT = "Reply with only the single word 'Hello'. No other text."


async def main() -> ProbeResult:
    """Run the Gemini ACP probe and return the result.

    Refreshes the Gemini OAuth token before spawning so that an expired token
    is detected immediately rather than causing a 300-second timeout.
    """
    logger.info("Refreshing Gemini OAuth token...")
    await refresh_gemini_token()
    logger.info("Token OK.")

    model_id = MODEL_MAP[Provider.GEMINI][Model.MID]
    command = ["gemini", "--model", model_id, "--experimental-acp"]
    logger.info("Starting Gemini ACP probe (model=%s)...", model_id)

    result = await run_probe(
        command=command,
        env_overrides={},
        prompt=_PROMPT,
    )

    if result.success:
        logger.info(
            "PROBE PASSED — stopReason=%s text=%r elapsed=%.0fms",
            result.stop_reason,
            result.full_text,
            result.elapsed_ms,
        )
    else:
        logger.error("PROBE FAILED — error=%s", result.error)

    return result


if __name__ == "__main__":
    setup_logging("debug")
    outcome = asyncio.run(main())
    sys.exit(0 if outcome.success else 1)
