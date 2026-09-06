"""ACP terminal responses retain their meaning through the chunk consumer."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from .._acp_protocol import handle_client_response
from .._acp_types import AcpResponseFuture, AcpSessionContext
from ..acp_chat_model import AcpChatModel
from ..acp_exceptions import AcpPromptCancelledError, AcpPromptError
from ..conditions import ProviderCondition


def _context() -> AcpSessionContext:
    return AcpSessionContext(
        process=cast("asyncio.subprocess.Process", None),
        stdin=cast("asyncio.StreamWriter", None),
        stdout=asyncio.StreamReader(),
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[7],
        interrupt_exc=[],
    )


async def _consume(stop_reason: str) -> None:
    ctx = _context()
    future = cast("AcpResponseFuture", asyncio.get_running_loop().create_future())
    ctx.response_futures[7] = future
    await handle_client_response({"id": 7, "result": {"stopReason": stop_reason}}, ctx)
    model = AcpChatModel(command=["unused"])
    async for _chunk in model._yield_chunks(ctx, future, None):
        pass


def test_end_turn_is_the_only_successful_terminal_reason() -> None:
    asyncio.run(_consume("end_turn"))


@pytest.mark.parametrize(
    ("stop_reason", "condition"),
    [
        ("max_tokens", ProviderCondition.INVALID_REQUEST),
        ("max_turn_requests", ProviderCondition.BUDGET_EXHAUSTED),
        ("refusal", ProviderCondition.INVALID_REQUEST),
    ],
)
def test_non_success_terminal_reasons_raise_with_preserved_meaning(
    stop_reason: str, condition: ProviderCondition
) -> None:
    with pytest.raises(AcpPromptError) as caught:
        asyncio.run(_consume(stop_reason))
    assert caught.value.condition is condition
    assert caught.value.data == {"acp_stop_reason": stop_reason}


def test_provider_cancel_has_a_distinct_outcome() -> None:
    with pytest.raises(AcpPromptCancelledError) as caught:
        asyncio.run(_consume("cancelled"))
    assert caught.value.data == {"acp_stop_reason": "cancelled"}


def test_partial_output_does_not_turn_refusal_into_success() -> None:
    async def exercise() -> None:
        ctx = _context()
        await ctx.chunk_queue.put(
            ChatGenerationChunk(message=AIMessageChunk(content="partial"))
        )
        future = cast("AcpResponseFuture", asyncio.get_running_loop().create_future())
        ctx.response_futures[7] = future
        await handle_client_response(
            {"id": 7, "result": {"stopReason": "refusal"}}, ctx
        )
        seen: list[str] = []
        model = AcpChatModel(command=["unused"])
        with pytest.raises(AcpPromptError) as caught:
            async for chunk in model._yield_chunks(ctx, future, None):
                seen.append(str(chunk.message.content))
        assert seen == ["partial"]
        assert caught.value.data == {"acp_stop_reason": "refusal"}

    asyncio.run(exercise())
