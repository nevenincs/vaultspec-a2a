"""Callback delivery for streamed ACP chat chunks."""

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.outputs import ChatGenerationChunk


async def notify_chunk(
    run_manager: AsyncCallbackManagerForLLMRun | None,
    chunk: ChatGenerationChunk,
) -> None:
    """Notify a LangChain run manager when one ACP chunk is ready."""
    if run_manager is not None:
        token = chunk.message.content
        await run_manager.on_llm_new_token(
            token if isinstance(token, str) else "", chunk=chunk
        )
