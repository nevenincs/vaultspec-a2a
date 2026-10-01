"""The two ways an ACP turn ends without the agent finishing it.

Both are read from the same evidence - the child's redacted stderr tail and the
session the turn belonged to - and neither is recoverable afterwards, so they
are raised here with that evidence attached rather than left for a caller to
reconstruct from a closed pipe.
"""

import logging

from ..control.config import settings
from ._acp_auth import runtime_log_extra
from ._acp_stderr import redacted_stderr_tail
from ._acp_types import AcpModelConfig, AcpSessionContext
from .acp_exceptions import AcpError, AcpErrorCode, AcpPromptError

__all__: list[str] = []

logger = logging.getLogger(__name__)


def enforce_turn_deadline(
    ctx: AcpSessionContext, config: AcpModelConfig, *, session_id: str | None
) -> None:
    """Fail the turn once the subprocess has gone silent for too long.

    The caller's queue poll only ends on a sentinel or on ``prompt_done``, both
    of which require the subprocess to say something. An agent that stays alive
    but stops emitting frames - a wedged tool call, a lost upstream connection -
    therefore parks the caller forever. Bound that by silence rather than by
    total turn length, so a genuinely long run is never cut off: every frame
    resets the clock.
    """
    idle_limit = settings.acp_turn_idle_timeout_seconds
    if idle_limit <= 0:
        return
    idle_seconds = ctx.seconds_since_activity()
    if idle_seconds < idle_limit:
        return
    # A hang is where the child's own account matters most: nothing arrived
    # over the protocol, so the only thing that can say what the agent was
    # doing is what it wrote to its log before it went quiet.
    tail = redacted_stderr_tail(ctx)
    logger.error(
        "ACP turn exceeded the idle deadline; redacted stderr tail:\n%s",
        tail,
        extra=runtime_log_extra(
            config,
            process=ctx.process,
            handshake_step="session/prompt",
            timeout_seconds=idle_limit,
            session_id=session_id,
            stderr_event_count=ctx.stderr_event_count,
        ),
    )
    raise AcpPromptError(
        f"ACP turn produced no protocol activity for {idle_seconds:.0f}s "
        f"(deadline {idle_limit:.0f}s); treating the session as hung; "
        f"redacted stderr tail:\n{tail}",
        code=AcpErrorCode.INTERNAL_ERROR,
        data={"acp_outcome": "turn_idle_deadline_expired"},
    )


def abnormal_exit_error(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    *,
    session_id: str | None,
    cause: BaseException | None = None,
) -> AcpError:
    """Describe a child that left mid-turn, in its own redacted words.

    The lines were written at DEBUG under an INFO default and the failure
    carried a line COUNT, so the one account of what happened was discarded
    exactly when it was needed. Reported at WARNING and carried on the error,
    because the reader of the log and the caller of the turn are different
    people with the same question.
    """
    tail = redacted_stderr_tail(ctx)
    detail = f" ({cause})" if cause is not None else ""
    logger.warning(
        "ACP subprocess exited before end_turn%s; redacted stderr tail:\n%s",
        detail,
        tail,
        extra=runtime_log_extra(
            config,
            process=ctx.process,
            handshake_step="session/prompt",
            session_id=session_id,
            stderr_event_count=ctx.stderr_event_count,
            exit_code=ctx.process.returncode,
        ),
    )
    return AcpError(
        f"ACP subprocess exited before end_turn{detail}; redacted stderr tail:\n{tail}",
        effects_may_have_occurred=ctx.effects_may_have_occurred,
    )
