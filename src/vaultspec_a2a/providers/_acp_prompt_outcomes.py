"""ACP prompt outcome and executable command validation."""

from __future__ import annotations

from typing import Never

from ._acp_types import MAX_NATIVE_COMMAND_NAME_LENGTH
from ._json_contract import JsonObject, lenient_json_object
from .acp_exceptions import (
    AcpError,
    AcpErrorCode,
    AcpPromptCancelledError,
    AcpPromptError,
)
from .conditions import ProviderCondition, condition_from_acp_error

__all__: list[str] = []


def required_session_id(result: JsonObject, *, operation: str) -> str:
    """Return the session id in one successful ACP response result."""
    session_id = result.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise AcpError(
            f"ACP {operation} succeeded without a sessionId",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    return session_id


def raise_prompt_error(
    response: JsonObject, *, effects_may_have_occurred: bool = False
) -> Never:
    """Raise a typed prompt failure from one JSON-RPC error response.

    The adapter attaches a categorical error kind to this frame precisely so a
    client can dispatch on it rather than pattern-match the message, and this is
    the one place that kind is still in hand. Resolving it here means the
    condition travels with the exception to every reporting site, instead of
    each of them re-deriving it from prose that has already been flattened.
    """
    raw_error = response.get("error")
    error = lenient_json_object(raw_error)
    code_value = error.get("code")
    code = (
        code_value
        if isinstance(code_value, int) and not isinstance(code_value, bool)
        else AcpErrorCode.INTERNAL_ERROR
    )
    raise AcpPromptError(
        f"ACP prompt failed: {raw_error}",
        code=code,
        data=error.get("data"),
        condition=condition_from_acp_error(error),
        effects_may_have_occurred=effects_may_have_occurred,
    )


def raise_for_prompt_stop_reason(
    stop_reason: str | None, *, effects_may_have_occurred: bool = False
) -> None:
    """Preserve every non-success ACP terminal outcome as a typed result."""
    if stop_reason == "end_turn":
        return
    data = {"acp_stop_reason": stop_reason}
    if stop_reason == "cancelled":
        raise AcpPromptCancelledError(
            "ACP prompt was cancelled by the agent",
            data=data,
            effects_may_have_occurred=effects_may_have_occurred,
        )
    if stop_reason == "max_turn_requests":
        raise AcpPromptError(
            "ACP prompt exhausted its turn-request budget",
            data=data,
            condition=ProviderCondition.BUDGET_EXHAUSTED,
            effects_may_have_occurred=effects_may_have_occurred,
        )
    if stop_reason == "max_tokens":
        raise AcpPromptError(
            "ACP prompt reached its output token limit",
            data=data,
            condition=ProviderCondition.INVALID_REQUEST,
            effects_may_have_occurred=effects_may_have_occurred,
        )
    if stop_reason == "refusal":
        raise AcpPromptError(
            "ACP agent refused the prompt",
            data=data,
            condition=ProviderCondition.INVALID_REQUEST,
            effects_may_have_occurred=effects_may_have_occurred,
        )
    raise AcpPromptError(
        f"ACP prompt ended without a supported stop reason: {stop_reason!r}",
        data=data,
        effects_may_have_occurred=effects_may_have_occurred,
    )


def is_executable_native_command_name(name: str) -> bool:
    if not name or name != name.strip() or not name.isprintable():
        return False
    return (
        not any(character.isspace() for character in name)
        and not name.startswith("/")
        and len(name) <= MAX_NATIVE_COMMAND_NAME_LENGTH
    )
