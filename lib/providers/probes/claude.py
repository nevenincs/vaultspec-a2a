"""ACP probe for the Claude Code agent (``claude-agent-acp``).

Runs the full ACP protocol lifecycle — ``initialize`` -> ``session/new`` ->
``session/prompt`` — against a real ``claude-agent-acp`` subprocess using the
``CLAUDE_CODE_OAUTH_TOKEN`` from the VaultSpec settings.

Run directly::

    python -m lib.providers.probes.claude

Exit code 0 on success, 1 on failure.  All protocol traffic is logged at DEBUG.
"""

import asyncio
import logging
import sys

from ...core.config import settings
from ...core.exceptions import ConfigError
from ...utils.logging import setup_logging
from ..factory import _CLAUDE_ACP_JS
from ._protocol import ProbeResult, run_probe


__all__ = ["main"]

logger = logging.getLogger(__name__)

_PROMPT = "Reply with only the single word 'Hello'. No other text."


async def main() -> ProbeResult:
    """Run the Claude ACP probe and return the result.

    Reads the OAuth token from
    :attr:`~lib.core.config.Settings.claude_code_oauth_token`.
    Returns a failing :class:`~lib.providers.probes._protocol.ProbeResult` when
    the token is not configured rather than raising.
    """
    if not settings.claude_code_oauth_token:
        logger.error(
            "CLAUDE_CODE_OAUTH_TOKEN is not configured — "
            "set VAULTSPEC_CLAUDE_CODE_OAUTH_TOKEN in .env"
        )
        return ProbeResult(success=False, error="CLAUDE_CODE_OAUTH_TOKEN not set")

    if not _CLAUDE_ACP_JS.exists():
        raise ConfigError(
            f"Claude ACP entry point not found: {_CLAUDE_ACP_JS}. "
            f"Run 'npm install' to install @zed-industries/claude-agent-acp."
        )

    logger.info("Starting Claude ACP probe...")
    result = await run_probe(
        command=["node", str(_CLAUDE_ACP_JS)],
        env_overrides={"CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token},
        prompt=_PROMPT,
        timeout=180.0,  # Claude session/new is slower than Gemini on Windows
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
