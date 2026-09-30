"""Tool and model-completion lifecycle, taken from the callback surface.

A graph's public stream modes carry node boundaries, state updates, model
tokens, custom writes and checkpoints. Two things they do not carry are a
tool's own lifecycle and the end of a model turn: both are LangChain runs
rather than graph supersteps, so their start, end and failure reach an
application through the documented callback surface instead. This handler is
seated in the run's ``config["callbacks"]`` alongside the stream, and projects
those callbacks onto the same wire events the rest of the streaming module
emits.

Every event is keyed by the provider's own tool-call id, which each callback
carries. Keying on the LangChain run id instead described one tool call under
two identities - the provider id the model streamed, and the run id the tool
executed under - leaving a duplicate that could never leave PENDING.

A handler fault must never reach the graph. LangChain logs and swallows an
async handler's exception rather than failing the run, so this stays the
default: nothing here is allowed to make a tool call fail that succeeded.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.callbacks import AsyncCallbackHandler
from langgraph.constants import TAG_NOSTREAM

from ..graph.enums import ToolCallStatus
from .translation import (
    ToolEmission,
    emit_tool_completion,
    truncated_tool_content,
)
from .types import classify_tool_kind

if TYPE_CHECKING:
    from uuid import UUID

    from langchain_core.outputs import LLMResult

    from .buffering import BufferingManager
    from .emitters import EventEmitters

__all__ = ["RunLifecycleCallbacks"]

logger = logging.getLogger(__name__)


class RunLifecycleCallbacks(AsyncCallbackHandler):
    """Project one run's tool lifecycle and model completions onto the wire."""

    def __init__(
        self,
        thread_id: str,
        agent_id: str,
        emitters: EventEmitters,
        buffering: BufferingManager,
    ) -> None:
        self._thread_id = thread_id
        self._agent_id = agent_id
        self._emitters = emitters
        self._buffering = buffering
        # The tool name and input each in-flight call started with, so its end
        # can report what it was and whether it touched a file. Keyed by the
        # same tool-call id the wire uses, and dropped when the call resolves,
        # so a long run never accumulates finished calls.
        self._in_flight: dict[str, tuple[str, object]] = {}

    def _emission(self, tool_call_id: str, node: str | None) -> ToolEmission:
        return ToolEmission(
            thread_id=self._thread_id,
            agent_id=node or self._agent_id,
            tool_call_id=tool_call_id,
            emitters=self._emitters,
        )

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Register a starting tool call under the id the model gave it."""
        del input_str, parent_run_id, tags
        tool_call_id = _tool_call_id(kwargs, run_id)
        tool_name = _tool_name(serialized)
        self._in_flight[tool_call_id] = (tool_name, inputs)
        emission = self._emission(tool_call_id, _node(metadata))
        await self._emitters.emit_tool_call_start(
            thread_id=emission.thread_id,
            agent_id=emission.agent_id,
            tool_call_id=tool_call_id,
            title=tool_name,
            kind=classify_tool_kind(tool_name),
            input_args=inputs,
        )

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Resolve a finished tool call and publish any artifact it wrote."""
        del parent_run_id, tags
        tool_call_id = _tool_call_id(kwargs, run_id, output)
        tool_name, tool_input = self._in_flight.pop(tool_call_id, ("", None))
        await emit_tool_completion(
            self._emission(tool_call_id, None), tool_name, tool_input, output
        )

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Report a failed tool call under the identity it started with."""
        del parent_run_id, tags
        tool_call_id = _tool_call_id(kwargs, run_id)
        self._in_flight.pop(tool_call_id, None)
        error_msg = str(error) or "Tool call failed"
        logger.warning(
            "Tool error in thread %s call %s: %s",
            self._thread_id,
            tool_call_id,
            error_msg,
        )
        emission = self._emission(tool_call_id, None)
        await self._emitters.emit_tool_call_update(
            thread_id=emission.thread_id,
            agent_id=emission.agent_id,
            tool_call_id=tool_call_id,
            status=ToolCallStatus.FAILED,
            content=truncated_tool_content(error_msg),
        )

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Close a model turn: flush what it streamed, then why it stopped.

        The buffer is flushed here rather than left to its own timer because
        a turn's last partial chunk would otherwise sit unsent until the next
        one, or until the run ended - the end of a model turn is the point at
        which a client should have all of that turn's text.

        The stream layer drops a ``nostream`` model run's tokens but still
        completes the run, so the tag is checked here too: a routing decision
        the client was never shown must not end with a visible final chunk.
        """
        del parent_run_id, kwargs
        if TAG_NOSTREAM in (tags or ()):
            return
        await self._buffering.flush_chunk_buffer(self._thread_id)
        message = _final_message(response)
        finish_reason = _finish_reason(message)
        if not finish_reason:
            return
        await self._emitters.emit_message_chunk(
            thread_id=self._thread_id,
            agent_id=self._agent_id,
            content="",
            message_id=_message_id(message, run_id),
            finish_reason=finish_reason,
        )


def _tool_call_id(kwargs: dict[str, Any], run_id: UUID, output: object = None) -> str:
    """The provider's id for this call, falling back to the run that made it.

    Every tool callback carries ``tool_call_id`` when the tool was invoked from
    a model's tool call, and the returned ``ToolMessage`` carries it too. A
    tool invoked directly, with no model call behind it, has none; the run id
    is then the only identity there is, and it is at least stable across that
    call's own start and end.
    """
    declared = kwargs.get("tool_call_id")
    if isinstance(declared, str) and declared:
        return declared
    from_output = getattr(output, "tool_call_id", None)
    if isinstance(from_output, str) and from_output:
        return from_output
    return str(run_id)


def _tool_name(serialized: dict[str, Any] | None) -> str:
    name = (serialized or {}).get("name")
    return name if isinstance(name, str) and name else "unknown_tool"


def _node(metadata: dict[str, Any] | None) -> str | None:
    node = (metadata or {}).get("langgraph_node")
    return node if isinstance(node, str) and node else None


def _final_message(response: LLMResult) -> object:
    generations = response.generations
    if not generations or not generations[0]:
        return None
    return getattr(generations[0][0], "message", None)


def _finish_reason(message: object) -> str:
    raw: object = getattr(message, "response_metadata", None) or {}
    metadata = cast("dict[str, object]", raw if isinstance(raw, dict) else {})
    for key in ("finish_reason", "stop_reason"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _message_id(message: object, run_id: UUID) -> str:
    """Join the closing frame to the chunks of the same model turn."""
    message_id = getattr(message, "id", None)
    return message_id if isinstance(message_id, str) and message_id else str(run_id)
