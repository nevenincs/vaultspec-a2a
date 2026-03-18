"""LangGraph checkpointer factory helpers."""

from __future__ import annotations

import asyncio
import builtins
import inspect
import logging
import sys
import threading

from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future as ConcurrentFuture
from contextlib import asynccontextmanager
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver

from ..core.config import settings


logger = logging.getLogger(__name__)


# Type alias: every LangGraph checkpointer (SQLite, Postgres, in-memory) is a
# BaseCheckpointSaver subclass.  Using the concrete base rather than a Protocol
# lets ty verify structural compatibility without manual casting.
Checkpointer = BaseCheckpointSaver[Any]


class _SelectorThreadPostgresCheckpointer(BaseCheckpointSaver[Any]):
    """Run AsyncPostgresSaver on a dedicated selector loop on Windows.

    Psycopg's async connection layer rejects the default Proactor event loop on
    Windows, while the ACP/provider subprocess path requires Proactor support.
    Keeping the saver on its own selector loop avoids forcing the entire
    gateway/worker runtime onto the wrong loop policy.
    """

    def __init__(self, conn_string: str) -> None:
        super().__init__()
        self._conn_string = conn_string
        self._loop_ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ctx: Any = None
        self._saver: Any = None

    async def start(self) -> None:
        """Start the selector-loop thread and enter AsyncPostgresSaver."""
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run_loop,
                name="vaultspec-postgres-checkpointer",
                daemon=True,
            )
            self._thread.start()
            await asyncio.to_thread(self._loop_ready.wait)
        await self._run_async("_open")

    def _run_loop(self) -> None:
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _open(self) -> None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        self._ctx = AsyncPostgresSaver.from_conn_string(self._conn_string)
        self._saver = await self._ctx.__aenter__()
        self.serde = self._saver.serde

    async def close(self) -> None:
        """Exit the saver context and stop the selector loop thread."""
        if self._loop is None:
            return
        try:
            await self._run_async("_close")
        except Exception:
            logger.warning(
                "Error while closing AsyncPostgresSaver on selector thread; "
                "selector loop will still be stopped.",
                exc_info=True,
            )
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                await asyncio.to_thread(self._thread.join, 5.0)
            self._thread = None
            self._loop = None

    async def _close(self) -> None:
        if self._ctx is not None:
            await self._ctx.__aexit__(None, None, None)
        self._ctx = None
        self._saver = None

    def _submit(
        self, method_name: str, *args: object, **kwargs: object
    ) -> ConcurrentFuture:
        if self._loop is None:
            raise RuntimeError("Selector thread loop is not running")

        async def _invoke() -> object:
            target = self._resolve_target(method_name)
            if callable(target):
                fn = cast(Callable[..., object], target)
                result = fn(*args, **kwargs)
            else:
                if args or kwargs:
                    raise TypeError(
                        f"{method_name} does not accept call arguments: "
                        f"{args!r} {kwargs!r}"
                    )
                result = target
            if inspect.isawaitable(result):
                return await result
            return result

        return asyncio.run_coroutine_threadsafe(_invoke(), self._loop)

    def _resolve_target(self, method_name: str) -> object:
        if method_name.startswith("_"):
            return getattr(self, method_name)
        if self._saver is None:
            raise RuntimeError("AsyncPostgresSaver is not initialized")
        return getattr(self._saver, method_name)

    async def _run_async(
        self, method_name: str, *args: object, **kwargs: object
    ) -> object:
        return await asyncio.wrap_future(self._submit(method_name, *args, **kwargs))

    def _run_sync(self, method_name: str, *args: object, **kwargs: object) -> object:
        return self._submit(method_name, *args, **kwargs).result()

    @property
    def config_specs(self) -> Any:  # noqa: ANN401
        return self._run_sync("config_specs")

    async def setup(self) -> None:
        await self._run_async("setup")

    async def aget(self, config: Any) -> Any:  # noqa: ANN401
        return await self._run_async("aget", config)

    async def aget_tuple(self, config: Any) -> Any:  # noqa: ANN401
        return await self._run_async("aget_tuple", config)

    async def alist(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:  # noqa: ANN401
        items = cast(
            list[Any],
            await self._run_async("_collect_alist", *args, **kwargs),
        )
        for item in items:
            yield item

    async def aput(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return await self._run_async("aput", *args, **kwargs)

    async def aput_writes(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return await self._run_async("aput_writes", *args, **kwargs)

    async def acopy_thread(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return await self._run_async("acopy_thread", *args, **kwargs)

    async def adelete_for_runs(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return await self._run_async("adelete_for_runs", *args, **kwargs)

    async def adelete_thread(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return await self._run_async("adelete_thread", *args, **kwargs)

    async def aprune(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return await self._run_async("aprune", *args, **kwargs)

    async def _collect_alist(
        self, *args: object, **kwargs: object
    ) -> builtins.list[Any]:
        if self._saver is None:
            raise RuntimeError("AsyncPostgresSaver is not initialized")
        return [item async for item in self._saver.alist(*args, **kwargs)]

    def get(self, config: Any) -> Any:  # noqa: ANN401
        return self._run_sync("get", config)

    def get_tuple(self, config: Any) -> Any:  # noqa: ANN401
        return self._run_sync("get_tuple", config)

    def get_next_version(self, current: Any, channel: Any) -> Any:  # noqa: ANN401
        return self._run_sync("get_next_version", current, channel)

    def list(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self._run_sync("list", *args, **kwargs)

    def put(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self._run_sync("put", *args, **kwargs)

    def put_writes(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self._run_sync("put_writes", *args, **kwargs)

    def copy_thread(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self._run_sync("copy_thread", *args, **kwargs)

    def delete_for_runs(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self._run_sync("delete_for_runs", *args, **kwargs)

    def delete_thread(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self._run_sync("delete_thread", *args, **kwargs)

    def prune(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self._run_sync("prune", *args, **kwargs)

    def with_allowlist(
        self, *args: object, **kwargs: object
    ) -> _SelectorThreadPostgresCheckpointer:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        new_saver = self._run_sync("with_allowlist", *args, **kwargs)
        if new_saver is not None:
            self._saver = cast(AsyncPostgresSaver, new_saver)
        if self._saver is not None:
            self.serde = self._saver.serde
        return self


@asynccontextmanager
async def open_checkpointer() -> AsyncIterator[Checkpointer]:
    """Open the configured LangGraph checkpointer backend."""
    if settings.resolved_checkpoint_backend == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(
            settings.checkpoint_connection_string
        ) as checkpointer:
            await checkpointer.setup()
            yield checkpointer
        return

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        msg = (
            "Postgres checkpoint backend selected but "
            "`langgraph-checkpoint-postgres` is not installed."
        )
        raise RuntimeError(msg) from exc

    if sys.platform == "win32":
        checkpointer = _SelectorThreadPostgresCheckpointer(
            settings.checkpoint_connection_string
        )
        await checkpointer.start()
        await checkpointer.setup()
        try:
            yield checkpointer
        finally:
            await checkpointer.close()
        return

    async with AsyncPostgresSaver.from_conn_string(
        settings.checkpoint_connection_string
    ) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
