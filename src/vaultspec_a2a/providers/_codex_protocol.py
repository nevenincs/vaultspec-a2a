"""Codex app-server prompt, turn error, and usage protocol projections."""

import json
from typing import Final

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.ai import (
    InputTokenDetails,
    OutputTokenDetails,
    UsageMetadata,
)
from langchain_core.outputs import ChatGenerationChunk

from ._json_contract import JsonObject, JsonValue, lenient_json_object
from .conditions import ProviderCondition, condition_from_codex_turn_error

__all__ = [
    "_ACTION_ITEM_TYPES",
    "_CodexProtocolError",
    "_carry_condition",
    "_completed_action_chunk",
    "_failed_turn_error",
    "_messages_to_prompt",
    "_required_object_field",
    "_required_string_field",
    "_response_error_message",
    "_turn_failure",
    "_usage_metadata",
]


def _messages_to_prompt(messages: list[BaseMessage]) -> str:
    """Flatten LangChain messages into a single Codex turn prompt.

    ``turn/start`` takes one ``UserInput`` array, not role-separated messages, so
    the conversation is rendered to labelled text blocks. System content leads as
    a preamble; human turns pass through verbatim; assistant/tool turns are kept
    with a role label so multi-turn context survives.
    """
    blocks: list[str] = []
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if not content.strip():
            continue
        if isinstance(msg, SystemMessage):
            blocks.append(f"# System\n{content}")
        elif isinstance(msg, HumanMessage):
            blocks.append(content)
        elif isinstance(msg, ToolMessage):
            blocks.append(f"# Tool result\n{content}")
        elif isinstance(msg, (AIMessage, AIMessageChunk)):
            blocks.append(f"# Assistant\n{content}")
        else:
            blocks.append(content)
    return "\n\n".join(blocks)


class _CodexProtocolError(RuntimeError):
    """A JSON-RPC error frame or an unexpected turn failure from the app-server."""

    def __init__(
        self,
        message: str,
        *,
        condition: ProviderCondition = ProviderCondition.UNKNOWN,
        will_retry: bool | None = None,
        effects_may_have_occurred: bool = False,
    ) -> None:
        """Initialize the protocol failure.

        Args:
            message: Human-safe description of what failed.
            condition: The provider condition this failure resolves to, carried
                as a field so a reporting site classifies without re-parsing a
                vendor-shaped payload. Defaults to the unknown member for the
                failures raised where no discriminator exists.
            will_retry: Whether the lane itself said it would retry. ``None``
                means the lane said nothing, which is deliberately distinct from
                a stated ``False``: only the notification that carries the flag
                can answer, and inferring it elsewhere is exactly the guess this
                field exists to replace.
            effects_may_have_occurred: Whether action activity preceded the
                failure, making a fresh turn unsafe to replay blindly.
        """
        super().__init__(message)
        self.message = message
        self.condition = condition
        self.will_retry = will_retry
        self.effects_may_have_occurred = effects_may_have_occurred


def _response_error_message(error: JsonValue) -> str:
    """Return the human-safe message from one JSON-RPC error payload."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return "codex app-server request failed"


def _turn_error_message(error: JsonValue) -> str:
    """Return the human-safe message from one Codex turn error."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return "codex app-server reported an error"


#: The item kinds that record an ACTION rather than speech. Taken from the
#: app-server's own generated protocol schema (``codex app-server
#: generate-json-schema``), whose thread-item union discriminates on this field,
#: rather than from a guess at the wire vocabulary.
_ACTION_ITEM_TYPES: Final = frozenset({"commandExecution", "fileChange", "mcpToolCall"})


def _completed_action_chunk(params: JsonObject) -> ChatGenerationChunk | None:
    """Project a completed action item onto a tool-call chunk, or None.

    This lane consumed only speech - message deltas, usage, errors - so a run
    that executed a command left no durable trace of having done so. The ACP
    family already records its actions, and it does it by riding the model's own
    stream: a tool-call chunk aggregates into the response message, the worker
    node returns that message as state, and state is checkpointed. Emitting the
    same shape here is PARITY with a mechanism already proven durable, not a new
    store - which is why no retention declaration accompanies it. A separate
    action log would have been a third at-rest copy of what one lane already
    checkpoints.

    ``item/completed`` is the seam rather than ``item/started`` because a
    completed item carries the outcome. A started command has no exit code, and
    a record of "a command began" that never says whether it succeeded answers
    the question worse than not recording it.

    Returns ``None`` for speech items and for anything unrecognised. The item
    union carries eighteen variants and gains more over time; a lane that
    guessed at unknown kinds would put invented structure into a checkpoint,
    which is worse than the silence this replaces.
    """
    item = lenient_json_object(params.get("item"))
    item_type = item.get("type")
    if not isinstance(item_type, str) or item_type not in _ACTION_ITEM_TYPES:
        return None
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id:
        return None
    # Only the fields the schema marks REQUIRED for each variant are read, so a
    # payload that grows optional fields cannot change what is recorded here.
    if item_type == "commandExecution":
        detail: JsonObject = {
            "command": item.get("command"),
            "cwd": item.get("cwd"),
            "status": item.get("status"),
            "exit_code": item.get("exitCode"),
        }
    elif item_type == "fileChange":
        detail = {"changes": item.get("changes"), "status": item.get("status")}
    else:
        detail = {
            "server": item.get("server"),
            "tool": item.get("tool"),
            "arguments": item.get("arguments"),
            "status": item.get("status"),
        }
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "id": item_id,
                    "name": item_type,
                    "args": json.dumps(detail),
                    "index": 0,
                }
            ],
        )
    )


def _turn_failure(
    error: JsonValue, *, message: str | None = None, will_retry: JsonValue = None
) -> _CodexProtocolError:
    """Build a protocol failure from one Codex turn error.

    The turn error carries a categorical discriminator beside its message, and
    the notification that delivers it additionally states whether the lane will
    retry. Both were previously dropped in favour of the message alone, which is
    what left a client with prose it had to pattern-match to learn anything.
    """
    return _CodexProtocolError(
        message if message is not None else _turn_error_message(error),
        condition=condition_from_codex_turn_error(error),
        will_retry=will_retry if isinstance(will_retry, bool) else None,
    )


def _carry_condition(
    failure: _CodexProtocolError, observed: _CodexProtocolError | None
) -> _CodexProtocolError:
    """Return *failure*, restoring a discriminator its own frame does not carry.

    The app-server's error union splits in two: a handful of variants are
    objects that forward the provider's HTTP status, and the rest are bare
    strings with no payload at all. A provider refusal routinely arrives as one
    of the payload-free ones, so the frame that ENDS the turn can be
    unclassifiable while the attempts that preceded it forwarded the actual
    status. Taking the terminal frame's word alone in that case reports the
    floor member for a refusal whose cause was observed moments earlier.

    So the message always comes from the terminal frame, which is the truthful
    account of how the turn ended, and the condition falls back to what an
    earlier frame actually forwarded - never the reverse, and never when the
    terminal frame classified itself.
    """
    if (
        observed is None
        or failure.condition is not ProviderCondition.UNKNOWN
        or observed.condition is ProviderCondition.UNKNOWN
    ):
        return failure
    return _CodexProtocolError(
        failure.message,
        condition=observed.condition,
        will_retry=failure.will_retry,
        effects_may_have_occurred=(
            failure.effects_may_have_occurred or observed.effects_may_have_occurred
        ),
    )


def _failed_turn_error(turn: JsonObject, status: JsonValue) -> _CodexProtocolError:
    """Build a protocol failure from one non-completed turn.

    A turn that did not complete carries its own error object, populated by the
    app-server exactly when the turn failed. Reading it is what separates "the
    turn failed" from "the turn failed BECAUSE the credential was rejected": the
    status alone is the same four words for every cause. The status is still
    reported, because it also covers the interrupted case, where there is no
    error object to explain and none should be invented.
    """
    error = turn.get("error")
    ended = f"codex turn ended with status {status!r}"
    detail = error.get("message") if isinstance(error, dict) else None
    return _turn_failure(
        error,
        message=(f"{ended}: {detail}" if isinstance(detail, str) and detail else ended),
    )


def _required_object_field(
    message: JsonObject, field: str, *, context: str
) -> JsonObject:
    """Read one required JSON-object field from a protocol frame."""
    value = message.get(field)
    if not isinstance(value, dict):
        raise _CodexProtocolError(f"codex {context} field {field!r} must be an object")
    return value


def _required_string_field(message: JsonObject, field: str, *, context: str) -> str:
    """Read one required non-blank string from a protocol object."""
    value = message.get(field)
    if not isinstance(value, str) or not value:
        raise _CodexProtocolError(
            f"codex {context} field {field!r} must be a non-blank string"
        )
    return value


def _token_count(breakdown: JsonObject, field: str) -> int:
    """Read one non-negative token counter, treating absence as zero.

    Absent optional counters (``cacheWriteInputTokens`` carries a schema
    default) are genuinely zero. A present but non-integer or negative value is
    a protocol violation and is refused rather than silently coerced, because a
    wrong token count becomes a wrong persisted accounting row.
    """
    value = breakdown.get(field)
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _CodexProtocolError(
            f"codex token usage field {field!r} must be a non-negative integer"
        )
    return value


def _usage_metadata(breakdown: JsonObject) -> UsageMetadata:
    """Map a codex ``TokenUsageBreakdown`` onto LangChain's usage contract.

    ``totalTokens`` is carried through as reported rather than recomputed: it is
    the provider's own accounting, and substituting a local sum would quietly
    paper over a disagreement worth seeing. The cache and reasoning counters are
    preserved in the standard detail sub-dicts instead of being discarded — they
    are exactly the fields that explain a surprising bill.
    """
    return UsageMetadata(
        input_tokens=_token_count(breakdown, "inputTokens"),
        output_tokens=_token_count(breakdown, "outputTokens"),
        total_tokens=_token_count(breakdown, "totalTokens"),
        input_token_details=InputTokenDetails(
            cache_read=_token_count(breakdown, "cachedInputTokens"),
            cache_creation=_token_count(breakdown, "cacheWriteInputTokens"),
        ),
        output_token_details=OutputTokenDetails(
            reasoning=_token_count(breakdown, "reasoningOutputTokens"),
        ),
    )
