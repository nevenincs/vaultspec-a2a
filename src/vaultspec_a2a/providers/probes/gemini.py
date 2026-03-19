"""ACP probe for the Gemini CLI agent.

Runs the full ACP protocol lifecycle — ``initialize`` -> ``session/new`` ->
``session/prompt`` — against a real Gemini CLI subprocess. Uses the official
non-interactive auth paths when configured (`GEMINI_API_KEY`,
`GOOGLE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`), otherwise refreshes the
local OAuth credentials before spawning so that an expired token never causes a
silent hang.

Run directly::

    python -m vaultspec_a2a.providers.probes.gemini

Exit code 0 on success, 1 on failure.  All protocol traffic is logged at DEBUG.
"""

import asyncio
import logging
import sys

from ...core.config import settings
from ...utils.enums import MODEL_MAP, Model, Provider
from ...utils.logging import setup_logging
from ..factory import _build_gemini_command, _build_gemini_env
from ..gemini_auth import refresh_gemini_token
from ._protocol import ProbeResult, run_probe

__all__ = ["main"]

logger = logging.getLogger(__name__)

_PROMPT = "Reply with only the single word 'Hello'. No other text."


async def main() -> ProbeResult:
    """Run the Gemini ACP probe and return the result.

    Refreshes the Gemini OAuth token only when env-based auth is absent so an
    expired local token is detected immediately rather than causing a timeout.
    """
    env_overrides = _build_gemini_env(
        gemini_api_key=settings.gemini_api_key,
        google_api_key=settings.google_api_key,
        google_application_credentials=settings.google_application_credentials,
        gemini_cli_home=settings.gemini_cli_home,
    )
    logger.info("Checking Gemini auth readiness...")
    await refresh_gemini_token(env=env_overrides)
    logger.info("Gemini auth ready.")

    model_id = MODEL_MAP[Provider.GEMINI][Model.MID]
    command = _build_gemini_command(model_id)
    logger.info("Starting Gemini ACP probe (model=%s)...", model_id)

    result = await run_probe(
        command=command,
        env_overrides=env_overrides,
        prompt=_PROMPT,
        auth_timeout=settings.acp_interactive_auth_timeout_seconds,
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
