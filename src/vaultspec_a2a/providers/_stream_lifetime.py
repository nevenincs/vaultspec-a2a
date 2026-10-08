"""Join provider generations hidden inside the framework's streaming wrappers."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from contextlib import AsyncExitStack, aclosing
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast, overload, override

from langchain_core.language_models.base import LanguageModelInput
from langchain_core.language_models.chat_model_stream import AsyncChatModelStream
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableBinding

from ..utils.async_cleanup import complete_cleanup

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
    )

    from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
    from langchain_core.messages import AIMessageChunk, BaseMessage
    from langchain_core.outputs import ChatGenerationChunk, ChatResult
    from langchain_core.runnables import RunnableConfig
    from langchain_core.runnables.schema import StreamEvent
    from langchain_core.tracers.schemas import Run
    from langchain_protocol.protocol import MessagesData

__all__ = ["ProcessChatModel"]

type _Listener = Callable[[Run], None] | Callable[[Run, RunnableConfig], None] | None


@dataclass(slots=True)
class _StreamOwner:
    model: BaseChatModel = field(repr=False)
    releases: AsyncExitStack = field(default_factory=AsyncExitStack, repr=False)


_STREAM_OWNER: ContextVar[tuple[_StreamOwner, asyncio.Task[Any] | None] | None] = (
    ContextVar("provider_stream_owner", default=None)
)


class _JoinedChatModelStream(AsyncChatModelStream):
    def __init__(self, source: AsyncChatModelStream) -> None:
        # The pinned framework producer closes over the original resource. Share
        # its live state so projections, callbacks and lazy startup stay identical.
        self.__dict__ = source.__dict__

    @override
    async def aclose(self) -> None:
        await complete_cleanup(super().aclose())


class _JoinedModelBinding(RunnableBinding[LanguageModelInput, AIMessage]):
    @classmethod
    @override
    def lc_id(cls) -> list[str]:
        return RunnableBinding.lc_id()

    @override
    async def astream(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[AIMessageChunk]:
        upstream = cast(
            "AsyncGenerator[AIMessageChunk]",
            self.bound.astream(
                input, self._merge_configs(config), **{**self.kwargs, **kwargs}
            ),
        )
        try:
            async for chunk in upstream:
                yield chunk
        finally:
            await complete_cleanup(upstream.aclose())

    @overload
    def astream_events(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2"] = "v2",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]: ...

    @overload
    def astream_events(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v3"],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> Awaitable[AsyncChatModelStream]: ...

    @override
    def astream_events(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent] | Awaitable[AsyncChatModelStream]:
        return cast(
            "AsyncIterator[StreamEvent] | Awaitable[AsyncChatModelStream]",
            super().astream_events(input, config, **kwargs),
        )


def _joined_binding(
    source: RunnableBinding[LanguageModelInput, AIMessage],
) -> _JoinedModelBinding:
    return _JoinedModelBinding(
        bound=source.bound,
        kwargs=source.kwargs,
        config=source.config,
        config_factories=source.config_factories,
        custom_input_type=source.custom_input_type,
        custom_output_type=source.custom_output_type,
    )


class ProcessChatModel(BaseChatModel):
    """Keep exact provider cleanup owned by each asynchronous model invocation."""

    @override
    def with_config(
        self, config: RunnableConfig | None = None, **kwargs: Any
    ) -> _JoinedModelBinding:
        return _joined_binding(
            cast(
                "RunnableBinding[LanguageModelInput, AIMessage]",
                super().with_config(config, **kwargs),
            )
        )

    @override
    def with_types(
        self,
        *,
        input_type: type[LanguageModelInput] | None = None,
        output_type: type[AIMessage] | None = None,
    ) -> _JoinedModelBinding:
        return _joined_binding(
            cast(
                "RunnableBinding[LanguageModelInput, AIMessage]",
                super().with_types(input_type=input_type, output_type=output_type),
            )
        )

    @override
    def with_listeners(
        self,
        *,
        on_start: _Listener = None,
        on_end: _Listener = None,
        on_error: _Listener = None,
    ) -> _JoinedModelBinding:
        return _joined_binding(
            cast(
                "RunnableBinding[LanguageModelInput, AIMessage]",
                super().with_listeners(
                    on_start=on_start, on_end=on_end, on_error=on_error
                ),
            )
        )

    async def _iterate_owned[T](self, upstream: AsyncGenerator[T]) -> AsyncGenerator[T]:
        owner = _StreamOwner(self)
        async with aclosing(upstream):
            try:
                while True:
                    token = _STREAM_OWNER.set((owner, asyncio.current_task()))
                    try:
                        chunk = await anext(upstream)
                    except StopAsyncIteration:
                        return
                    finally:
                        # A yield can resume or close in another task/context.
                        _STREAM_OWNER.reset(token)
                    yield chunk
            finally:
                await complete_cleanup(owner.releases.aclose())

    @override
    async def astream(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[AIMessageChunk]:
        upstream = cast(
            "AsyncGenerator[AIMessageChunk]",
            super().astream(input, config=config, stop=stop, **kwargs),
        )
        async with aclosing(self._iterate_owned(upstream)) as owned:
            async for chunk in owned:
                yield chunk

    @override
    async def _agenerate_with_cache(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        owner = _StreamOwner(self)
        token = _STREAM_OWNER.set((owner, asyncio.current_task()))
        try:
            return await super()._agenerate_with_cache(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        finally:
            _STREAM_OWNER.reset(token)
            await complete_cleanup(owner.releases.aclose())

    @override
    async def _achat_model_stream_v3(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncChatModelStream:
        stream = await super()._achat_model_stream_v3(
            input, config=config, stop=stop, **kwargs
        )
        return _JoinedChatModelStream(stream)

    @override
    async def _aiter_v2_events(
        self,
        messages: list[BaseMessage],
        *,
        run_manager: AsyncCallbackManagerForLLMRun,
        stream: AsyncChatModelStream,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[MessagesData]:
        upstream = cast(
            "AsyncGenerator[MessagesData]",
            super()._aiter_v2_events(
                messages,
                run_manager=run_manager,
                stream=stream,
                stop=stop,
                **kwargs,
            ),
        )
        async with aclosing(self._iterate_owned(upstream)) as owned:
            async for event in owned:
                yield event

    @override
    def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatGenerationChunk]:
        generation = self._provider_astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )
        binding = _STREAM_OWNER.get()
        if (
            binding is not None
            and binding[0].model is self
            and binding[1] is asyncio.current_task()
        ):
            binding[0].releases.push_async_callback(generation.aclose)
        return generation

    @abstractmethod
    def _provider_astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatGenerationChunk]:
        raise NotImplementedError
