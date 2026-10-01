"""The ACP child's standard error: draining it, and reading it back.

Separate from the chat model because two unrelated readers depend on the same
drain. Every failure that has to explain a turn which did not finish reads the
retained tail, and the browser-authorization handshake is announced on this
stream and nowhere in the protocol, so the loop below is the only place either
fact is observable.
"""

import logging

from ._acp_auth import runtime_log_extra
from ._acp_types import AcpModelConfig, AcpSessionContext

__all__: list[str] = []

logger = logging.getLogger(__name__)


def redacted_stderr_tail(ctx: AcpSessionContext) -> str:
    """Return the child's last words, redacted, or a marker when it said none.

    One reader for every failure that has to explain a turn which did not
    finish, because the question is the same whichever way it ended: a child
    that left mid-turn and one that stopped speaking both leave their log as
    the only account of why. The lines are redacted at capture, so reading them
    here cannot widen what a failure discloses.
    """
    return ctx.rendered_stderr_tail() or "<empty>"


async def read_stderr_loop(ctx: AcpSessionContext, config: AcpModelConfig) -> None:
    """Drain the child's standard error until the stream ends."""
    if ctx.process.stderr is None:
        return
    while line := await ctx.process.stderr.readline():
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            capture_auth_progress(text, ctx, config)
            ctx.stderr_event_count += 1
            ctx.retain_stderr_line(text)
            # Diagnostics are proof of life too. The turn deadline exists to
            # catch a silent hang, and the expensive mistake is felling an
            # agent that is genuinely working, so any sign of life resets it.
            # An agent wedged in a chatty retry loop survives longer as a
            # result - the deliberate trade, since that one is at least
            # visible in the log while a silent hang is not.
            ctx.mark_activity()
            logger.debug(
                "ACP STDERR: %s",
                text,
                extra=runtime_log_extra(
                    config,
                    process=ctx.process,
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )


def capture_auth_progress(
    text: str, ctx: AcpSessionContext, config: AcpModelConfig
) -> None:
    """Capture browser-auth progress from ACP stderr lines."""
    if "Please visit the following URL to authorize the application" in text:
        ctx.auth_prompt_active = True
        logger.info(
            "ACP browser authentication prompt detected",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step="authenticate",
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
        return
    if ctx.auth_prompt_active and text.startswith(("http://", "https://")):
        ctx.auth_url = text
        ctx.auth_prompt_active = False
        ctx.last_auth_url = text
        logger.info(
            "ACP browser authentication URL captured",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step="authenticate",
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
