"""Mock LLM Provider for deterministic offline testing and UI development."""

import logging
import os
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import Field

from ..core.team_config import AgentConfig

logger = logging.getLogger(__name__)


class MockChatModel(ChatOpenAI):
    """A mock chat model that proxies requests to a local VidaiMock instance.
    
    It inherits from ChatOpenAI to gain full payload compatibility and SSE chunk parsing.
    The model name is overwritten dynamically based on the AgentConfig ID to trigger
    the correct VidaiMock 'tape' configuration.
    """

    def __init__(self, **kwargs: Any):
        # Disable retries for fast failing in tests
        kwargs.setdefault("api_key", "dummy-mock-key")
        kwargs.setdefault("max_retries", 0) 
        
        agent_config = kwargs.pop("agent_config", None)
        if agent_config:
            # Route to the right tape via URL path matching
            kwargs.setdefault("model", agent_config.id)
            base_url = os.environ.get("MOCK_API_BASE", f"http://localhost:8100/{agent_config.id}/v1")
        else:
            kwargs.setdefault("model", "mock-success-single")
            base_url = os.environ.get("MOCK_API_BASE", "http://localhost:8100/mock-success-single/v1")
            
        kwargs["base_url"] = base_url
        super().__init__(**kwargs)

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
        from langchain_core.messages.tool import tool_call_chunk
        from langchain_core.outputs import ChatGenerationChunk
        import copy

        current_messages = list(messages)
        
        while True:
            # We must intercept the stream to see if it emitted tool calls
            collected_chunks = []
            final_message = None
            
            async for chunk in super()._astream(current_messages, stop=stop, run_manager=run_manager, **kwargs):
                collected_chunks.append(chunk)
                if final_message is None:
                    final_message = chunk.message
                else:
                    final_message += chunk.message
                yield chunk
                
            if not final_message or not final_message.tool_calls:
                break
                
            # If we received tool calls, append the AI response and dummy tool outcomes, then loop
            current_messages.append(final_message)
            
            for tc in final_message.tool_calls:
                tc_id = tc["id"]
                tool_name = tc["name"]
                # Provide a fake successful result to satisfy the loop
                mock_tool_msg = ToolMessage(
                    content=f"Mock outcome for {tool_name}",
                    tool_call_id=tc_id
                )
                current_messages.append(mock_tool_msg)
                
            # Yield an artificial separator to let the UI/trace know we are recursing loops
            if run_manager:
                await run_manager.on_llm_new_token("\\n\\n[MockChatModel: Tool Execution Loop Resolved. Continuing...]\\n\\n")
            yield ChatGenerationChunk(message=AIMessageChunk(content="\\n\\n[MockChatModel: Tool Execution Loop Resolved. Continuing...]\\n\\n"))
