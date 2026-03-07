"""ACP probe for the Claude Code agent (``claude-agent-acp``).

Runs the full ACP protocol lifecycle — ``initialize`` -> ``session/new`` ->
``session/prompt`` — against a real ``claude-agent-acp`` subprocess using the
``CLAUDE_CODE_OAUTH_TOKEN`` from the VaultSpec settings.

Run directly::

    uv run python -m vaultspec_a2a.providers.probes.claude
    uv run python -m vaultspec_a2a.providers.probes.claude --backend binary
    uv run python -m vaultspec_a2a.providers.probes.claude --debug

Exit code 0 on success, 1 on failure.  All protocol traffic is logged at DEBUG.
"""

import argparse
import asyncio
import logging
import shutil
import sys

from ...core.config import settings
from ...core.exceptions import ConfigError
from ...utils.logging import setup_logging
from ..factory import _build_acp_command
from ._protocol import ProbeResult, run_probe


__all__ = ["main"]

logger = logging.getLogger(__name__)

_PROMPT = "Reply with only the single word 'Hello'. No other text."


async def main(backend: str | None = None, *, debug: bool = False) -> ProbeResult:
    """Run the Claude ACP probe and return the result.

    Args:
        backend: ACP gateway backend — ``"node"`` or ``"binary"``.
            Defaults to ``settings.acp_backend`` when ``None``.
        debug: When True, sets ``ANTHROPIC_LOG=debug`` in the subprocess
            environment for verbose SDK output on stderr.

    Reads the OAuth token from
    :attr:`~vaultspec_a2a.core.config.Settings.claude_code_oauth_token`.
    Returns a failing :class:`~vaultspec_a2a.providers.probes._protocol.ProbeResult`
    when the token is not configured rather than raising.
    """
    resolved_backend = backend or settings.acp_backend

    if not settings.claude_code_oauth_token:
        logger.error(
            "CLAUDE_CODE_OAUTH_TOKEN is not configured — "
            "set VAULTSPEC_CLAUDE_CODE_OAUTH_TOKEN in .env"
        )
        return ProbeResult(success=False, error="CLAUDE_CODE_OAUTH_TOKEN not set")

    try:
        command = _build_acp_command(resolved_backend)
    except ConfigError as exc:
        logger.error("ACP command resolution failed: %s", exc)
        return ProbeResult(success=False, error=str(exc))

    env_overrides: dict[str, str] = {
        "CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token,
    }
    if resolved_backend == "binary":
        env_overrides["CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN"] = "1"
        # The bun binary spawns the system claude CLI internally for the actual
        # session. CLAUDE_CODE_EXECUTABLE must be set unconditionally so it
        # can locate the binary — unlike the node path where resolve_env_vars()
        # handles this, the probe builds from os.environ directly.
        _system_claude = shutil.which("claude")
        if _system_claude is None:
            logger.error(
                "System claude binary not found on PATH — "
                "required for binary ACP backend (CLAUDE_CODE_EXECUTABLE)"
            )
            return ProbeResult(
                success=False,
                error=(
                    "System claude binary not found — required for binary ACP backend"
                ),
            )
        env_overrides["CLAUDE_CODE_EXECUTABLE"] = _system_claude
        logger.debug("Binary mode: CLAUDE_CODE_EXECUTABLE=%s", _system_claude)

    logger.info(
        "Starting Claude ACP probe (backend=%s, debug=%s)...",
        resolved_backend,
        debug,
    )
    result = await run_probe(
        command=command,
        env_overrides=env_overrides,
        prompt=_PROMPT,
        timeout=180.0,  # Claude session/new is slower than Gemini on Windows
        debug=debug,
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

    if result.rate_limit_events:
        logger.warning(
            "Rate limit events observed: %d event(s)", len(result.rate_limit_events)
        )

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ACP probe for the Claude Code agent (claude-agent-acp).",
    )
    parser.add_argument(
        "--backend",
        choices=["node", "binary"],
        default=None,
        help=(
            "ACP gateway backend. "
            "'node' uses the npm-installed index.js (default). "
            "'binary' uses the precompiled Bun executable in src/vaultspec_a2a/bin/."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Set ANTHROPIC_LOG=debug in the subprocess for verbose SDK output.",
    )
    args = parser.parse_args()

    setup_logging("debug")
    outcome = asyncio.run(main(backend=args.backend, debug=args.debug))
    sys.exit(0 if outcome.success else 1)
