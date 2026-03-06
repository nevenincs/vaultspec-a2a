"""Mock LLM Provider for deterministic offline testing and UI development."""

import logging
import os
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import Field, PrivateAttr

from ..core.team_config import AgentConfig

logger = logging.getLogger(__name__)

__all__ = ["MockChatModel"]


class MockChatModel(ChatOpenAI):
    """A mock chat model that proxies requests to a local VidaiMock instance.

    It inherits from ChatOpenAI to gain full payload compatibility and SSE chunk parsing.
    The model name is overwritten dynamically based on the AgentConfig ID to trigger
    the correct VidaiMock 'tape' configuration.
    """

    _agent_config: AgentConfig | None = PrivateAttr(default=None)
    permission_callback: Any | None = Field(default=None, exclude=True)

    def __init__(self, **kwargs: Any):
        # Disable retries for fast failing in tests
        kwargs.setdefault("api_key", "dummy-mock-key")
        kwargs.setdefault("max_retries", 0)
        # ADR-032: Force streaming to ensure _astream delay physics run on .ainvoke()
        kwargs.setdefault("streaming", True)

        agent_config = kwargs.pop("agent_config", None)

        # PROV-M2: Route to the right tape via URL path matching (e.g. /mock-planner/v1).
        # Matchers in YAML tapes (e.g. ^/mock-planner/v1/chat/completions$) depend on this suffix.
        if agent_config:
            kwargs.setdefault("model", agent_config.id)
            default_base_url = f"http://localhost:8100/{agent_config.id}/v1"
        else:
            kwargs.setdefault("model", "mock-success-single")
            default_base_url = "http://localhost:8100/mock-success-single/v1"

        # If MOCK_API_BASE is set (e.g. in Docker), append the agent id suffix to it.
        env_base = os.environ.get("MOCK_API_BASE")
        if env_base:
            # Strip trailing /v1 if present to avoid double-suffixing
            env_base = env_base.rstrip("/").removesuffix("/v1")
            agent_id = agent_config.id if agent_config else "mock-success-single"
            kwargs["base_url"] = f"{env_base}/{agent_id}/v1"
        else:
            kwargs["base_url"] = default_base_url

        super().__init__(**kwargs)
        # PrivateAttr must be set after super().__init__() in Pydantic v2
        self._agent_config = agent_config

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        """Force LangGraph's .ainvoke() to consume our artificial _astream logic."""
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_core.messages import AIMessage
        
        generation = None
        async for chunk in self._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            if generation is None:
                generation = chunk
            else:
                generation += chunk
                
        # Return a valid ChatResult built from the accumulated chunk stream
        message = generation.message if generation else AIMessage(content="")
        chat_gen = ChatGeneration(message=message)
        return ChatResult(generations=[chat_gen])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        """Proxies to VidaiMock via native SSE streaming (ADR-032 §2).

        Sends `stream: true` and iterates `data:` lines from the SSE response.
        VidaiMock v0.1.2 sends tool calls as complete single chunks (not deltas),
        so no delta accumulation is required.
        """
        from langchain_core.messages import (
            AIMessage, AIMessageChunk, HumanMessage,
            SystemMessage, ToolMessage
        )
        from langchain_core.outputs import ChatGenerationChunk
        import json
        import httpx

        base_url = str(self.openai_api_base)
        logger.debug("MockChatModel starting _astream to %s", base_url)

        # Convert messages to standard OpenAI format for the mock endpoint.
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

            entry = {"role": role, "content": m.content}
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
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    json=payload,
                    timeout=30.0,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            logger.debug("Skipping unparseable SSE line: %r", data_str)
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        # Text content delta
                        text = delta.get("content")
                        if text:
                            yield ChatGenerationChunk(
                                message=AIMessageChunk(content=text)
                            )

                        # Tool call chunks — VidaiMock v0.1.2 sends complete tool calls
                        tool_calls = delta.get("tool_calls", [])
                        if tool_calls:
                            tc_chunks = []
                            for t_idx, tc in enumerate(tool_calls):
                                func = tc.get("function", {})
                                tc_chunks.append({
                                    "index": tc.get("index", t_idx),
                                    "id": tc.get("id"),
                                    "name": func.get("name"),
                                    "args": func.get("arguments", ""),
                                })
                            yield ChatGenerationChunk(
                                message=AIMessageChunk(
                                    content="", tool_call_chunks=tc_chunks
                                )
                            )

            logger.debug("SSE stream from VidaiMock completed")

        except Exception as e:
            logger.debug("MockChatModel hit an error in _astream: %s", e)
            raise


