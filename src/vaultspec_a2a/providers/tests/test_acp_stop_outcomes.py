"""ACP terminal responses retain their meaning through the chunk consumer."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from langchain_core.language_models.chat_models import generate_from_stream
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from .._acp_protocol import handle_client_response, handle_session_update
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


def test_prompt_result_carries_accounting_usage_by_model_to_final_message() -> None:
    async def exercise() -> None:
        ctx = _context()
        future = cast("AcpResponseFuture", asyncio.get_running_loop().create_future())
        ctx.response_futures[7] = future
        await ctx.chunk_queue.put(
            ChatGenerationChunk(message=AIMessageChunk(content="reply"))
        )
        await handle_client_response(
            {
                "id": 7,
                "result": {
                    "stopReason": "end_turn",
                    "usage": {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                    "_meta": {
                        "quota": {
                            "model_usage": [
                                {
                                    "model": "sonnet",
                                    "token_count": {
                                        "inputTokens": 3,
                                        "outputTokens": 2,
                                        "cachedInputTokens": 4,
                                        "cachedWriteTokens": 1,
                                        "totalTokens": 10,
                                        "reasoningOutputTokens": 0,
                                    },
                                },
                                {
                                    "model": "haiku",
                                    "token_count": {
                                        "inputTokens": 5,
                                        "outputTokens": 1,
                                        "cachedInputTokens": 0,
                                        "cachedWriteTokens": 2,
                                        "totalTokens": 8,
                                        "reasoningOutputTokens": 0,
                                    },
                                },
                            ]
                        }
                    },
                },
            },
            ctx,
        )

        model = AcpChatModel(command=["unused"])
        chunks = [chunk async for chunk in model._yield_chunks(ctx, future, None)]
        final = generate_from_stream(iter(chunks)).generations[0].message

        assert isinstance(final, AIMessage)
        assert final.content == "reply"
        assert final.usage_metadata == {
            "input_tokens": 15,
            "output_tokens": 3,
            "total_tokens": 18,
            "input_token_details": {"cache_read": 4, "cache_creation": 3},
            "output_token_details": {"reasoning": 0},
            "model_usage": {
                "sonnet": {
                    "input_tokens": 8,
                    "output_tokens": 2,
                    "total_tokens": 10,
                    "input_token_details": {
                        "cache_read": 4,
                        "cache_creation": 1,
                    },
                    "output_token_details": {"reasoning": 0},
                },
                "haiku": {
                    "input_tokens": 7,
                    "output_tokens": 1,
                    "total_tokens": 8,
                    "input_token_details": {
                        "cache_read": 0,
                        "cache_creation": 2,
                    },
                    "output_token_details": {"reasoning": 0},
                },
            },
        }

    asyncio.run(exercise())


def test_prompt_result_without_model_rows_keeps_main_loop_usage() -> None:
    async def exercise() -> None:
        ctx = _context()
        future = cast("AcpResponseFuture", asyncio.get_running_loop().create_future())
        ctx.response_futures[7] = future
        await handle_client_response(
            {
                "id": 7,
                "result": {
                    "stopReason": "end_turn",
                    "usage": {
                        "inputTokens": 2,
                        "outputTokens": 3,
                        "cachedReadTokens": 4,
                        "cachedWriteTokens": 1,
                        "totalTokens": 10,
                    },
                },
            },
            ctx,
        )
        model = AcpChatModel(command=["unused"])
        chunks = [chunk async for chunk in model._yield_chunks(ctx, future, None)]
        final = generate_from_stream(iter(chunks)).generations[0].message
        assert isinstance(final, AIMessage)
        usage = final.usage_metadata
        assert usage is not None
        assert usage["input_tokens"] == 7
        assert usage["output_tokens"] == 3
        assert usage["total_tokens"] == 10

    asyncio.run(exercise())


def test_invalid_prompt_usage_fails_instead_of_recording_wrong_tokens() -> None:
    async def exercise() -> None:
        ctx = _context()
        future = cast("AcpResponseFuture", asyncio.get_running_loop().create_future())
        ctx.response_futures[7] = future
        await handle_client_response(
            {
                "id": 7,
                "result": {
                    "stopReason": "end_turn",
                    "usage": {
                        "inputTokens": True,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                },
            },
            ctx,
        )
        model = AcpChatModel(command=["unused"])
        with pytest.raises(AcpPromptError, match="invalid usage"):
            async for _chunk in model._yield_chunks(ctx, future, None):
                pass

    asyncio.run(exercise())


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


@pytest.mark.parametrize(
    "stop_reason", ["refusal", "cancelled", "max_tokens", "max_turn_requests"]
)
def test_failed_terminal_turn_preserves_reported_usage_on_error(
    stop_reason: str,
) -> None:
    async def exercise() -> None:
        ctx = _context()
        future = cast("AcpResponseFuture", asyncio.get_running_loop().create_future())
        ctx.response_futures[7] = future
        await handle_client_response(
            {
                "id": 7,
                "result": {
                    "stopReason": stop_reason,
                    "usage": {
                        "inputTokens": 3,
                        "outputTokens": 2,
                        "cachedReadTokens": 4,
                        "cachedWriteTokens": 1,
                        "totalTokens": 10,
                    },
                },
            },
            ctx,
        )
        model = AcpChatModel(command=["unused"])
        with pytest.raises(AcpPromptError) as caught:
            async for _chunk in model._yield_chunks(ctx, future, None):
                pass
        assert caught.value.usage_metadata == {
            "input_tokens": 8,
            "output_tokens": 2,
            "total_tokens": 10,
            "input_token_details": {"cache_read": 4, "cache_creation": 1},
            "output_token_details": {"reasoning": 0},
        }

    asyncio.run(exercise())


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


def test_tool_activity_prevents_retry_after_terminal_failure() -> None:
    async def exercise() -> None:
        ctx = _context()
        await handle_session_update(
            {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "effect-1",
                    "title": "write",
                    "rawInput": {"path": "result.txt"},
                }
            },
            ctx,
        )
        future = cast("AcpResponseFuture", asyncio.get_running_loop().create_future())
        ctx.response_futures[7] = future
        await handle_client_response(
            {"id": 7, "result": {"stopReason": "max_tokens"}}, ctx
        )
        model = AcpChatModel(command=["unused"])
        with pytest.raises(AcpPromptError) as caught:
            async for _chunk in model._yield_chunks(ctx, future, None):
                pass
        assert caught.value.effects_may_have_occurred is True

    asyncio.run(exercise())
