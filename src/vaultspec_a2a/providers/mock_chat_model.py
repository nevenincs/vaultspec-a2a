"""Mock LLM Provider for deterministic offline testing and UI development."""

import json
import logging

from collections.abc import AsyncIterator
from typing import Any

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
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from ..core.config import settings
from ..core.team_config import AgentConfig


logger = logging.getLogger(__name__)

__all__ = ["MockChatModel"]


class MockChatModel(BaseChatModel):
    """A mock chat model that proxies requests to a local VidaiMock instance.

    Rebased on ``BaseChatModel`` (HIGH-03) instead of ``ChatOpenAI`` to
    avoid inheriting unused OpenAI internals.  The model name is set
    dynamically based on the ``AgentConfig`` ID to trigger the correct
    VidaiMock 'tape' configuration.
    """

    model_name: str = "mock-success-single"
    base_url: str = "http://localhost:8100/mock-success-single/v1"
    permission_callback: Any | None = Field(default=None, exclude=True)

    _agent_config: AgentConfig | None = PrivateAttr(default=None)

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        """Route to the correct VidaiMock tape based on agent config."""
        agent_config = kwargs.pop("agent_config", None)

        # PROV-M2: Route to the right tape via URL path matching.
        if agent_config:
            kwargs.setdefault("model_name", agent_config.id)
            default_base_url = f"http://localhost:8100/{agent_config.id}/v1"
        else:
            kwargs.setdefault("model_name", "mock-success-single")
            default_base_url = "http://localhost:8100/mock-success-single/v1"

        # If MOCK_API_BASE is set (e.g. in Docker), append the agent id suffix.
        env_base = settings.mock_api_base
        if env_base:
            env_base = env_base.rstrip("/").removesuffix("/v1")
            agent_id = agent_config.id if agent_config else "mock-success-single"
            kwargs["base_url"] = f"{env_base}/{agent_id}/v1"
        else:
            kwargs.setdefault("base_url", default_base_url)

        super().__init__(**kwargs)
        self._agent_config = agent_config

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> ChatResult:
        """Synchronous generation — not supported, use async."""
        raise NotImplementedError(
            "MockChatModel only supports async via _astream/_agenerate"
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> ChatResult:
        """Accumulate streaming chunks into a single ChatResult."""
        generation = None
        async for chunk in self._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            if generation is None:
                generation = chunk
            else:
                generation += chunk

        message = generation.message if generation else AIMessage(content="")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(  # noqa: PLR0912
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Proxy to VidaiMock via native SSE streaming (ADR-032 §2).

        Sends ``stream: true`` and iterates ``data:`` lines from the SSE
        response.  VidaiMock v0.1.2 sends tool calls as complete single
        chunks (not deltas), so no delta accumulation is required.
        """
        url = self.base_url
        logger.debug("MockChatModel starting _astream to %s", url)

        openai_messages = []
        for m in messages:
            role = "user"
            if isinstance(m, HumanMessage):
                role = "user"
            elif isinstance(m, AIMessage):
                role = "assistant"
            elif isinstance(m, SystemMessage):
                role = "system"
            elif isinstance(m, ToolMessage):
                role = "tool"

            entry: dict[str, Any] = {"role": role, "content": m.content}
            if isinstance(m, ToolMessage):
                entry["tool_call_id"] = m.tool_call_id
            if isinstance(m, AIMessage) and m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            openai_messages.append(entry)

        payload = {
            "model": self.model_name,
            "messages": openai_messages,
            "stream": True,
            **kwargs,
        }

        try:
            async with (
                httpx.AsyncClient() as client,
                client.stream(
                    "POST",
                    f"{url}/chat/completions",
                    json=payload,
                    timeout=30.0,
                ) as resp,
            ):
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Skipping unparseable SSE line: %r",
                            data_str,
                        )
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    text = delta.get("content")
                    if text:
                        yield ChatGenerationChunk(message=AIMessageChunk(content=text))

                    tool_calls = delta.get("tool_calls", [])
                    if tool_calls:
                        tc_chunks = []
                        for t_idx, tc in enumerate(tool_calls):
                            func = tc.get("function", {})
                            tc_chunks.append(
                                {
                                    "index": tc.get("index", t_idx),
                                    "id": tc.get("id"),
                                    "name": func.get("name"),
                                    "args": func.get("arguments", ""),
                                }
                            )
                        yield ChatGenerationChunk(
                            message=AIMessageChunk(
                                content="",
                                tool_call_chunks=tc_chunks,
                            )
                        )

            logger.debug("SSE stream from VidaiMock completed")

        except Exception as e:
            logger.debug("MockChatModel hit an error in _astream: %s", e)
            raise
