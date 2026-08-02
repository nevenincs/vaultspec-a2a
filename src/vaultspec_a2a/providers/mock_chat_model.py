"""Mock LLM provider for deterministic offline testing and UI development."""

import logging
from collections.abc import AsyncIterator
from typing import Literal, override

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.tool import ToolCallChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, TypeAdapter, ValidationError

from ..control.config import settings
from ..team.team_config import AgentConfig
from ._json_contract import JsonObject, JsonValue

logger = logging.getLogger(__name__)

__all__ = ["MockChatModel"]

_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_DEFAULT_MODEL_NAME = "mock-success-single"
_DEFAULT_LOCAL_BASE = "http://localhost:8100"


def _validated_json_object(value: object, *, context: str) -> JsonObject:
    """Return one strictly validated JSON object or raise a boundary error."""
    try:
        return _JSON_OBJECT.validate_python(value, strict=True)
    except ValidationError as exc:
        raise ValueError(f"{context} must be a JSON object") from exc


def _validated_json_value(value: object, *, context: str) -> JsonValue:
    """Return one strictly validated JSON value or raise a boundary error."""
    try:
        return _JSON_VALUE.validate_python(value, strict=True)
    except ValidationError as exc:
        raise ValueError(f"{context} must be JSON serialisable") from exc


def _normalize_chunk(chunk: object) -> JsonValue | None:
    """Decode up to two VidaiMock JSON-string wrappers without coercion."""
    try:
        current = _JSON_VALUE.validate_python(chunk, strict=True)
    except ValidationError:
        return None

    for _ in range(2):
        if not isinstance(current, str):
            return current
        text = current.strip()
        if not text or text[0] not in "[{":
            return current
        try:
            current = _JSON_VALUE.validate_json(text, strict=True)
        except ValidationError:
            return current
    return current


def _extract_text_content(content: JsonValue) -> str:
    """Return concatenated display text from string or structured blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        text = block.get("text")
        if block_type in {"text", "output_text"} and isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _extract_choice_payload(chunk: JsonObject) -> JsonObject:
    """Return the delta/message payload from an OpenAI-style chunk."""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    choice = choices[0]
    if not isinstance(choice, dict):
        return {}
    payload = choice.get("delta")
    if isinstance(payload, dict):
        return payload
    payload = choice.get("message")
    return payload if isinstance(payload, dict) else {}


def _tool_calls(value: JsonValue) -> list[JsonObject]:
    """Keep only object-shaped tool calls with an object ``function`` payload."""
    if not isinstance(value, list):
        return []
    calls: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("function"), dict):
            calls.append(item)
    return calls


def _extract_tool_calls(chunk: object) -> list[JsonObject]:
    """Return tool calls from an OpenAI or VidaiMock raw chunk."""
    normalized = _normalize_chunk(chunk)
    if isinstance(normalized, list):
        return _tool_calls(normalized)
    if not isinstance(normalized, dict):
        return []
    return _tool_calls(_extract_choice_payload(normalized).get("tool_calls"))


def _extract_chunk_text(chunk: object) -> str:
    """Return text content from an OpenAI or VidaiMock raw chunk."""
    normalized = _normalize_chunk(chunk)
    if isinstance(normalized, str):
        return normalized
    if isinstance(normalized, list):
        return _extract_text_content(normalized)
    if not isinstance(normalized, dict):
        return ""
    return _extract_text_content(_extract_choice_payload(normalized).get("content", ""))


def _message_role(message: BaseMessage) -> str:
    """Map each supported LangChain message to its OpenAI wire role."""
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, ChatMessage):
        return message.role
    raise ValueError(f"unsupported message type: {type(message).__name__}")


def _message_payload(message: BaseMessage) -> JsonObject:
    """Encode one LangChain message as a strictly JSON-shaped OpenAI object."""
    payload: JsonObject = {
        "role": _message_role(message),
        "content": _validated_json_value(message.content, context="message content"),
    }
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = message.tool_call_id
    if isinstance(message, AIMessage) and message.tool_calls:
        payload["tool_calls"] = _validated_json_value(
            message.tool_calls,
            context="AI message tool calls",
        )
    return _validated_json_object(payload, context="OpenAI message payload")


def _string_or_none(value: JsonValue | None) -> str | None:
    """Narrow a JSON field for the LangChain tool-call chunk contract."""
    return value if isinstance(value, str) else None


def _tool_call_chunks(tool_calls: list[JsonObject]) -> list[ToolCallChunk]:
    """Convert narrowed OpenAI tool calls to LangChain streaming chunks."""
    chunks: list[ToolCallChunk] = []
    for fallback_index, tool_call in enumerate(tool_calls):
        function = tool_call.get("function")
        if not isinstance(function, dict):
            continue
        index_value = tool_call.get("index", fallback_index)
        index = (
            index_value
            if isinstance(index_value, int) and not isinstance(index_value, bool)
            else fallback_index
        )
        chunks.append(
            ToolCallChunk(
                name=_string_or_none(function.get("name")),
                args=_string_or_none(function.get("arguments")),
                id=_string_or_none(tool_call.get("id")),
                index=index,
                type="tool_call_chunk",
            )
        )
    return chunks


class MockChatModel(BaseChatModel):
    """A ``BaseChatModel`` proxy to the local VidaiMock SSE service."""

    model_name: str = _DEFAULT_MODEL_NAME
    base_url: str = f"{_DEFAULT_LOCAL_BASE}/{_DEFAULT_MODEL_NAME}/v1"
    disable_streaming: bool | Literal["tool_calling"] = True
    agent_config: AgentConfig | None = Field(default=None, exclude=True)
    permission_callback: object | None = Field(default=None, exclude=True)

    @override
    def model_post_init(self, context: object, /) -> None:
        """Resolve implicit local tape routing after Pydantic field validation."""
        super().model_post_init(context)
        agent_id = self.agent_config.id if self.agent_config else _DEFAULT_MODEL_NAME
        fields_set = self.model_fields_set
        if "model_name" not in fields_set:
            self.model_name = agent_id

        configured_base = settings.mock_api_base
        if configured_base:
            root = configured_base.rstrip("/").removesuffix("/v1")
            self.base_url = f"{root}/{agent_id}/v1"
        elif "base_url" not in fields_set:
            self.base_url = f"{_DEFAULT_LOCAL_BASE}/{agent_id}/v1"

    @property
    @override
    def _llm_type(self) -> str:
        return "mock-chat-model"

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Synchronous generation is unsupported; use the asynchronous path."""
        del messages, stop, run_manager, kwargs
        raise NotImplementedError(
            "MockChatModel only supports async via _astream/_agenerate"
        )

    @override
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Accumulate the native streaming chunks into a single chat result."""
        generation: ChatGenerationChunk | None = None
        async for chunk in self._astream(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        ):
            generation = chunk if generation is None else generation + chunk

        message = generation.message if generation else AIMessage(content="")
        return ChatResult(generations=[ChatGeneration(message=message)])

    @override
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Proxy an OpenAI-compatible native SSE stream from VidaiMock."""
        del stop, run_manager
        url = self.base_url
        logger.debug("MockChatModel starting _astream to %s", url)
        request_overrides = _validated_json_object(kwargs, context="request overrides")
        payload: JsonObject = {
            "model": self.model_name,
            "messages": [_message_payload(message) for message in messages],
            "stream": True,
        }
        payload.update(request_overrides)
        request_payload = _validated_json_object(
            payload, context="chat completion request"
        )

        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                f"{url}/chat/completions",
                json=request_payload,
                timeout=30.0,
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = _JSON_VALUE.validate_json(data, strict=True)
                except ValidationError:
                    logger.debug("Skipping unparseable SSE line: %r", data)
                    continue

                text = _extract_chunk_text(chunk)
                if text:
                    yield ChatGenerationChunk(message=AIMessageChunk(content=text))

                chunks = _tool_call_chunks(_extract_tool_calls(chunk))
                if chunks:
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(content="", tool_call_chunks=chunks)
                    )

        logger.debug("SSE stream from VidaiMock completed")
