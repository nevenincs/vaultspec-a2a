"""Negotiating one provider-native slash command over an ordinary ACP prompt.

A native command is not a protocol verb: it is prompt text the agent only
honours when it has advertised the command for this exact session. The
admission check, the prompt text it produces, and the bounded result an
invocation reports are one concern, kept together so a command cannot be sent
on an advertisement the session never made.
"""

import asyncio
import logging

from ._acp_model_state import (
    AcpSessionBusyError,
    NativeCommandRequest,
    NativeCommandUnavailableError,
)
from ._acp_prompt_outcomes import is_executable_native_command_name
from ._acp_types import (
    AcpSessionContext,
    NativeCommandDisposition,
    NativeCommandOutcome,
    NativeCommandResult,
)
from ._json_contract import JsonObject
from .acp_exceptions import AcpError, AcpPromptCancelledError

__all__: list[str] = []

logger = logging.getLogger(__name__)

COMMAND_ADVERTISEMENT_TIMEOUT_SECONDS = 5.0
MAX_NATIVE_COMMAND_ARGUMENT_LENGTH = 8192


def validate_native_command(name: str, arguments: str | None) -> None:
    """Refuse a command identity or argument string the lane will not carry."""
    if not is_executable_native_command_name(name):
        raise ValueError("native command name is not an executable exact identity")
    if arguments is not None and (
        len(arguments) > MAX_NATIVE_COMMAND_ARGUMENT_LENGTH
        or not arguments.isprintable()
    ):
        raise ValueError("native command arguments are invalid")


async def native_command_prompt_blocks(
    ctx: AcpSessionContext,
    native_command: NativeCommandRequest | None,
    prompt_blocks: list[JsonObject],
    session_id: str,
) -> list[JsonObject]:
    """Return the prompt blocks one turn sends, command-negotiated or as given."""
    if native_command is None:
        return prompt_blocks
    catalog = ctx.native_commands_for(session_id)
    if not catalog.received:
        try:
            await asyncio.wait_for(
                catalog.updated.wait(),
                timeout=COMMAND_ADVERTISEMENT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            raise NativeCommandUnavailableError(
                native_command.name,
                NativeCommandDisposition.BLOCKED,
                ("the provider did not advertise commands before the deadline"),
            ) from None
    availability = catalog.resolve(native_command.name)
    if availability.disposition is not NativeCommandDisposition.SUPPORTED:
        raise NativeCommandUnavailableError(
            native_command.name,
            availability.disposition,
            availability.reason or "native command is unavailable",
        )
    text = f"/{native_command.name}"
    if native_command.arguments:
        text = f"{text} {native_command.arguments}"
    ctx.effects_may_have_occurred = True
    return [{"type": "text", "text": text}]


def native_command_error_result(name: str, exc: Exception) -> NativeCommandResult:
    """Report one failed invocation as a bounded outcome rather than a raise."""
    if isinstance(exc, AcpSessionBusyError):
        return NativeCommandResult(
            name=name, outcome=NativeCommandOutcome.BUSY, reason=str(exc)
        )
    if isinstance(exc, NativeCommandUnavailableError):
        outcome = (
            NativeCommandOutcome.UNSUPPORTED
            if exc.disposition is NativeCommandDisposition.UNSUPPORTED
            else NativeCommandOutcome.BLOCKED
        )
        return NativeCommandResult(name=name, outcome=outcome, reason=str(exc))
    if isinstance(exc, AcpPromptCancelledError):
        return NativeCommandResult(
            name=name,
            outcome=NativeCommandOutcome.CANCELLED,
            reason=str(exc),
            effects_may_have_occurred=exc.effects_may_have_occurred,
        )
    if isinstance(exc, AcpError):
        return NativeCommandResult(
            name=name,
            outcome=NativeCommandOutcome.FAILED,
            reason=str(exc),
            effects_may_have_occurred=exc.effects_may_have_occurred,
        )
    logger.error("ACP native command failed", exc_info=exc)
    return NativeCommandResult(
        name=name,
        outcome=NativeCommandOutcome.FAILED,
        reason=f"provider command failed ({type(exc).__name__})",
        effects_may_have_occurred=True,
    )
