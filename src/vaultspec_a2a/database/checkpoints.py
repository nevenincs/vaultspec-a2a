"""LangGraph checkpointer factory helpers."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import logging
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncGenerator, AsyncIterator, Collection
    from concurrent.futures import Future as ConcurrentFuture

    from langgraph.checkpoint.serde.base import SerializerProtocol

from ..control.config import settings
from ..domain_config import domain_config
from .checkpoint_retention import prune_settled_checkpoints, scalar
from .checkpoint_schema import checkpoint_pragmas

logger = logging.getLogger(__name__)

__all__ = [
    "Checkpointer",
    "concurrent_checkpointer",
    "open_checkpointer",
    "prune_settled_thread",
    "setup_postgres_checkpointer",
]

# Headroom over the worker's concurrent-run bound. Every run in flight can be
# writing a checkpoint at a superstep boundary, so the bound is the floor; the
# spare pair serves the reads that are not a run's own - status enrichment,
# recovery reconciliation, retention - without queueing them behind the writers.
# Reaching either bound takes a saver per concurrent caller: see
# ``concurrent_checkpointer``.
_CHECKPOINT_POOL_HEADROOM = 2

# One connection is opened up front and the rest on demand. A checkpoint pool
# sized for peak concurrency would otherwise hold that many idle server
# connections in a desktop profile that runs one thread at a time.
_CHECKPOINT_POOL_MIN_SIZE = 1

# The advisory-lock key every process of this package uses to serialize
# checkpoint schema setup. Derived from a stable name rather than chosen by
# hand, so the two processes agree on it and an unrelated application sharing
# the database is vanishingly unlikely to pick the same number.
_CHECKPOINT_SETUP_LOCK_KEY = int.from_bytes(
    hashlib.blake2b(b"vaultspec-a2a:checkpoint-setup", digest_size=8).digest(),
    "big",
    signed=True,
)

# Setup is four small DDL statements and three index builds on tables that are
# empty the one time this contends, so a process still waiting after this long
# is not waiting for a peer that is making progress.
_CHECKPOINT_SETUP_LOCK_TIMEOUT_SECONDS = 120.0
_CHECKPOINT_SETUP_LOCK_POLL_SECONDS = 0.05

# What a saver says when it is asked to close resources it only borrows.
_BORROWED_SAVER_CLOSE_REFUSAL = (
    "This checkpointer borrows the selector thread, event loop and connection "
    "pool of the one it was taken from, so closing it would close the "
    "checkpoint store for every holder. Close the checkpointer that opened "
    "them instead."
)


def strict_checkpoint_serde() -> SerializerProtocol:
    """Return the serializer that reads back only the safe set of types.

    Deserialization is where a checkpoint store becomes an execution surface.
    The permissive default imports and calls whatever type a stored value names,
    so anything able to write the store chooses what this process constructs on
    load; it only logs that it did so. An empty allowlist - which is how the
    library states strict mode - leaves its own safe set, and that set already
    covers every type this graph checkpoints: JSON primitives and LangChain
    messages.

    Configured on each saver rather than through ``LANGGRAPH_STRICT_MSGPACK``,
    so the posture belongs to the store this package opens and not to whichever
    process happens to host it.

    Strict deserialization DEGRADES rather than refuses: a blocked value comes
    back as the raw argument its type was built from - a plain string where an
    enum member was written - and is logged. Writing plain values in the first
    place is what keeps that substitution from reaching a node.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=None)


def _postgres_checkpoint_pool_size() -> int:
    """Return the connection ceiling for the checkpoint pool.

    The same factory builds the pool in both processes, so the ceiling covers
    whichever of them holds it: the worker's concurrent runs plus their
    out-of-band reads, or the gateway's page of parallel checkpoint probes.
    """
    return max(
        _CHECKPOINT_POOL_MIN_SIZE,
        domain_config.max_concurrent_threads + _CHECKPOINT_POOL_HEADROOM,
        domain_config.thread_list_checkpoint_concurrency,
    )


def _postgres_checkpoint_pool(conninfo: str) -> Any:
    """Build the unopened checkpoint connection pool for the Postgres backend.

    The saver used to run on ONE connection opened from a connection string,
    which left checkpointing dead until a restart if that connection dropped. A
    pool replaces a broken connection and bounds how many the process can hold.
    It does NOT by itself make one saver concurrent: ``AsyncPostgresSaver`` holds
    a single lock around every statement it issues, so each saver uses one
    connection at a time and concurrency comes from taking a saver per caller
    (``concurrent_checkpointer``) over this shared pool.

    The connection keywords are not defaults worth inheriting - they are what the
    saver requires. It issues its own transactions, so a connection must be in
    autocommit; it builds statements whose text varies, so server-side prepared
    statements are disabled rather than accumulating one plan per variant; and it
    reads rows by column name. ``check`` is what makes a pooled connection
    trustworthy after an idle period: a connection the server has since dropped is
    discarded and replaced at checkout instead of failing the caller's write.
    """
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    return AsyncConnectionPool(
        conninfo=conninfo,
        min_size=_CHECKPOINT_POOL_MIN_SIZE,
        max_size=_postgres_checkpoint_pool_size(),
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        check=AsyncConnectionPool.check_connection,
        open=False,
    )


# Type alias: every LangGraph checkpointer (SQLite, Postgres, in-memory) is a
# BaseCheckpointSaver subclass.  Using the concrete base rather than a Protocol
# lets ty verify structural compatibility without manual casting.
Checkpointer = BaseCheckpointSaver[Any]


class _SelectorThreadPostgresCheckpointer(BaseCheckpointSaver[Any]):  # pylint: disable=too-many-public-methods
    """Run AsyncPostgresSaver on a dedicated selector loop on Windows.

    Psycopg's async connection layer rejects the default Proactor event loop on
    Windows, while the ACP/provider subprocess path requires Proactor support.
    Keeping the saver on its own selector loop avoids forcing the entire
    gateway/worker runtime onto the wrong loop policy.
    The methods implement the required synchronous and asynchronous saver API.
    """

    def __init__(self, conn_string: str) -> None:
        super().__init__()
        self._conn_string = conn_string
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pool: Any = None
        self._saver: Any = None
        # Set on the clones below, which run on this bridge's thread, loop and
        # pool without owning any of them.
        self._borrowed = False

    async def start(self) -> None:
        """Start the selector-loop thread and enter AsyncPostgresSaver."""
        if self._thread is None:
            # The handshake belongs to the start that performs it, not to the
            # bridge: a bridge started again after a close must wait for the
            # new loop, not read an event the previous one already set.
            ready = threading.Event()
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(ready,),
                name="vaultspec-postgres-checkpointer",
                daemon=True,
            )
            self._thread.start()
            await asyncio.to_thread(ready.wait)
        await self._run_async("_open")

    def _run_loop(self, ready: threading.Event) -> None:
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _open(self) -> None:
        # The pool is created AND opened on the selector loop, not in ``start``:
        # its background maintenance tasks bind to the running loop, so a pool
        # opened on the caller's loop would put psycopg's async layer back on the
        # very event loop this class exists to keep it off.
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        self._pool = _postgres_checkpoint_pool(self._conn_string)
        await self._pool.open(wait=True)
        self._saver = AsyncPostgresSaver(
            conn=self._pool, serde=strict_checkpoint_serde()
        )
        self.serde = self._saver.serde

    async def close(self) -> None:
        """Exit the saver context and stop the selector loop thread.

        A borrowed saver refuses instead. Its thread, loop and pool belong to
        the checkpointer it was cloned from, and closing it would take the
        store away from every other holder - runs mid-superstep included -
        while the owner went on believing its store was open.
        """
        if self._borrowed:
            raise RuntimeError(_BORROWED_SAVER_CLOSE_REFUSAL)
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
        if self._pool is not None:
            await self._pool.close()
        self._pool = None
        self._saver = None

    def _submit(
        self, method_name: str, *args: object, **kwargs: object
    ) -> ConcurrentFuture[object]:
        if self._loop is None:
            raise RuntimeError("Selector thread loop is not running")

        async def _invoke() -> object:
            target = self._resolve_target(method_name)
            if callable(target):
                fn = target
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
        """Run the inner saver's ASYNC *method_name* and block until it answers.

        Never the inner saver's own synchronous method: those marshal onto the
        loop they were given at construction, which is the selector loop this
        submits to, so they either refuse the call outright or wait on the loop
        that would have to run them.
        """
        return self._submit(method_name, *args, **kwargs).result()

    def _inner(self) -> Any:
        if self._saver is None:
            raise RuntimeError("AsyncPostgresSaver is not initialized")
        return self._saver

    @property
    @override
    def config_specs(self) -> Any:
        # Answered here rather than on the selector thread: it is a constant
        # the saver reports about itself, and the Pregel loop reads it while
        # building a run's config, on the caller's loop.
        return self._inner().config_specs

    async def setup(self) -> None:
        await self._run_async("_setup")

    async def _setup(self) -> None:
        if self._saver is None or self._pool is None:
            raise RuntimeError("AsyncPostgresSaver is not initialized")
        await setup_postgres_checkpointer(self._saver, self._pool)

    @override
    async def aget(self, config: Any) -> Any:
        return await self._run_async("aget", config)

    @override
    async def aget_tuple(self, config: Any) -> Any:
        return await self._run_async("aget_tuple", config)

    @override
    async def alist(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        items = cast(
            "list[Any]",
            await self._run_async("_collect_alist", *args, **kwargs),
        )
        for item in items:
            yield item

    @override
    async def aput(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run_async("aput", *args, **kwargs)

    @override
    async def aput_writes(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run_async("aput_writes", *args, **kwargs)

    @override
    async def adelete_thread(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run_async("adelete_thread", *args, **kwargs)

    # ``aprune``, ``adelete_for_runs``, ``acopy_thread`` and their synchronous
    # counterparts are deliberately NOT proxied. The saver behind this bridge
    # implements none of them, so a proxy would only carry the base class's
    # refusal across a thread - and, worse, would answer yes to a caller asking
    # whether this saver implements them before choosing how to do the work.

    async def concurrent_sibling(self) -> _SelectorThreadPostgresCheckpointer:
        """Return a bridge to a second saver on the same pool and selector loop.

        The sibling borrows this bridge's thread, loop and pool, so it must not
        outlive it and cannot be closed: closing stops the loop and closes the
        pool both of them are using, so it refuses.
        """
        sibling: Any = await self._run_async("_pooled_sibling_saver")
        clone = copy.copy(self)
        clone._saver = sibling
        clone._borrowed = True
        clone.serde = sibling.serde
        return clone

    async def _pooled_sibling_saver(self) -> Any:
        # Constructed ON the selector loop: AsyncPostgresSaver binds the running
        # loop at construction and marshals its own sync calls onto it.
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        if self._pool is None:
            raise RuntimeError("AsyncPostgresSaver is not initialized")
        return AsyncPostgresSaver(conn=self._pool, serde=self.serde)

    async def prune_settled_thread(self, thread_id: str) -> bool:
        """Prune a settled thread on the selector loop that owns the connection."""
        return bool(await self._run_async("_prune_settled_thread", thread_id))

    async def _prune_settled_thread(self, thread_id: str) -> bool:
        if self._saver is None:
            raise RuntimeError("AsyncPostgresSaver is not initialized")
        return await prune_settled_checkpoints(self._saver, thread_id)

    async def _collect_alist(
        self, *args: object, **kwargs: object
    ) -> builtins.list[Any]:
        if self._saver is None:
            raise RuntimeError("AsyncPostgresSaver is not initialized")
        return [item async for item in self._saver.alist(*args, **kwargs)]

    @override
    def get(self, config: Any) -> Any:
        tuple_ = self.get_tuple(config)
        return None if tuple_ is None else tuple_.checkpoint

    @override
    def get_tuple(self, config: Any) -> Any:
        return self._run_sync("aget_tuple", config)

    @override
    def get_next_version(self, current: Any, channel: Any) -> Any:
        # Answered here, NOT across the selector thread. It is pure arithmetic
        # on *current*, and the Pregel loop calls it once per channel per
        # superstep from the caller's event loop: bridging it cost that loop a
        # cross-thread round trip each time, and stalled it outright whenever
        # the selector loop was busy with a statement.
        return self._inner().get_next_version(current, channel)

    @override
    def list(self, *args: Any, **kwargs: Any) -> Any:
        return iter(
            cast(
                "builtins.list[Any]",
                self._run_sync("_collect_alist", *args, **kwargs),
            )
        )

    @override
    def put(self, *args: Any, **kwargs: Any) -> Any:
        return self._run_sync("aput", *args, **kwargs)

    @override
    def put_writes(self, *args: Any, **kwargs: Any) -> Any:
        return self._run_sync("aput_writes", *args, **kwargs)

    @override
    def delete_thread(self, *args: Any, **kwargs: Any) -> Any:
        return self._run_sync("adelete_thread", *args, **kwargs)

    @override
    def with_allowlist(
        self, extra_allowlist: Collection[tuple[str, ...]]
    ) -> _SelectorThreadPostgresCheckpointer:
        """Return a clone carrying the derived allowlist, as the base does.

        The base contract is a shallow clone with a narrowed serializer; this
        used to swap its own inner saver and hand back itself, so every holder
        of the bridge - including runs already compiled against it - silently
        acquired one caller's allowlist. The clone borrows this bridge's
        thread, loop and pool, so it refuses to be closed.
        """
        inner = self._inner()
        narrowed = inner.with_allowlist(extra_allowlist)
        if narrowed is inner:
            return self
        clone = copy.copy(self)
        clone._saver = narrowed
        clone._borrowed = True
        clone.serde = narrowed.serde
        return clone


async def _take_setup_lock(connection: Any) -> None:
    """Hold the checkpoint setup lock on *connection*, waiting between tries."""
    deadline = time.monotonic() + _CHECKPOINT_SETUP_LOCK_TIMEOUT_SECONDS
    while True:
        cursor = await connection.execute(
            "SELECT pg_try_advisory_lock(%s)", (_CHECKPOINT_SETUP_LOCK_KEY,)
        )
        if scalar(await cursor.fetchone()):
            return
        if time.monotonic() >= deadline:
            msg = (
                "Another process has held the checkpoint schema setup lock for "
                f"{_CHECKPOINT_SETUP_LOCK_TIMEOUT_SECONDS:.0f}s; refusing to set "
                "up the schema alongside it."
            )
            raise TimeoutError(msg)
        await asyncio.sleep(_CHECKPOINT_SETUP_LOCK_POLL_SECONDS)


async def setup_postgres_checkpointer(saver: Any, pool: Any) -> None:
    """Create the saver's schema under a lock no other process can cross.

    ``AsyncPostgresSaver.setup`` issues its ``CREATE TABLE IF NOT EXISTS``
    statements and migration inserts unguarded, and ``IF NOT EXISTS`` is not
    atomic against a concurrent creator: two processes starting against a fresh
    database collide inside PostgreSQL's own catalog, and the loser fails on
    ``pg_type_typname_nsp_index`` rather than on anything the statements test
    for. Shipped start ordering hides it; a second worker or a saver migration
    would not.

    The saver's last migrations are ``CREATE INDEX CONCURRENTLY``, which waits
    out every transaction already running on the database, and that dictates
    the shape of the lock twice over. It is session-scoped rather than
    transaction-scoped, so the holder sits idle rather than keeping a
    transaction the index build would wait for; and the loser POLLS for it
    instead of blocking in ``pg_advisory_lock``, because a connection parked
    inside that statement is itself a transaction the winner's index build
    would wait for - the two would wait for each other. Between polls the
    waiter holds nothing. A process that dies instead of unlocking drops its
    session, and the lock with it.
    """
    async with pool.connection() as connection:
        await _take_setup_lock(connection)
        try:
            await saver.setup()
        finally:
            try:
                await connection.execute(
                    "SELECT pg_advisory_unlock(%s)", (_CHECKPOINT_SETUP_LOCK_KEY,)
                )
            except Exception:
                # Returning it to the pool still locked would stall the next
                # process to start for as long as this one lives. Ending the
                # session is the release of last resort, and it must not
                # replace a failure from setup itself.
                logger.warning(
                    "Could not release the checkpoint setup lock; discarding "
                    "the connection so the session ends.",
                    exc_info=True,
                )
                await connection.close()


def _pooled_postgres_saver(checkpointer: object) -> Any | None:
    """Return *checkpointer* when it is a native Postgres saver over a pool.

    A saver built from a connection STRING owns one connection and relies on its
    own lock to keep statements off each other; only a pooled saver can safely
    have a sibling. Both imports are lazy: the PostgreSQL driver belongs to the
    optional server profile.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool
    except ImportError:
        return None
    if not isinstance(checkpointer, AsyncPostgresSaver):
        return None
    return checkpointer if isinstance(checkpointer.conn, AsyncConnectionPool) else None


async def concurrent_checkpointer(checkpointer: Checkpointer) -> Checkpointer:
    """Return a saver that does not queue behind *checkpointer*'s own lock.

    ``AsyncPostgresSaver`` holds one lock around every statement it issues, so a
    single saver uses one pooled connection at a time however large the pool is.
    A caller that needs real concurrency - a run writing its own checkpoints, one
    of a page of parallel status probes - takes a saver of its own over the SAME
    pool. The pool stays the bound on how many connections the process holds.

    The result borrows the caller's pool and must not outlive it: closing it
    belongs to whoever opened the checkpointer, never to a sibling. Where the
    sibling has a ``close`` to call - the selector bridge - it refuses one; the
    pooled saver has none, and its pool is the caller's to close. A backend
    that cannot benefit returns itself - SQLite has one connection to serialize
    on, and a Postgres saver on a bare connection has nothing else to run on.
    """
    if isinstance(checkpointer, _SelectorThreadPostgresCheckpointer):
        return await checkpointer.concurrent_sibling()
    saver = _pooled_postgres_saver(checkpointer)
    if saver is None:
        return checkpointer
    return cast("Checkpointer", type(saver)(conn=saver.conn, serde=saver.serde))


async def prune_settled_thread(checkpointer: Checkpointer, thread_id: str) -> bool:
    """Drop a settled thread's superseded checkpoints from the saver backing it.

    Returns:
        ``True`` when the history was pruned, ``False`` when the saver is one
        the retention statements do not cover and was left untouched.
    """
    if isinstance(checkpointer, _SelectorThreadPostgresCheckpointer):
        return await checkpointer.prune_settled_thread(thread_id)
    return await prune_settled_checkpoints(checkpointer, thread_id)


@asynccontextmanager
async def _open_selector_thread_checkpointer(
    conn_string: str,
) -> AsyncGenerator[Checkpointer]:
    """Open the selector-thread bridge and release it however the block ends.

    ``start`` and ``setup`` are inside the block on purpose: both can fail with
    the selector thread already running and the pool already open, and outside
    it a refused setup left that thread and every connection behind for the
    life of the process.
    """
    checkpointer = _SelectorThreadPostgresCheckpointer(conn_string)
    try:
        await checkpointer.start()
        await checkpointer.setup()
        yield checkpointer
    finally:
        await checkpointer.close()


@asynccontextmanager
async def open_checkpointer() -> AsyncGenerator[Checkpointer]:
    """Open the configured LangGraph checkpointer backend."""
    opener = (
        _open_sqlite_checkpointer()
        if settings.resolved_checkpoint_backend == "sqlite"
        else _open_postgres_checkpointer()
    )
    async with opener as checkpointer:
        yield checkpointer


@asynccontextmanager
async def _open_sqlite_checkpointer() -> AsyncGenerator[Checkpointer]:
    """Open the SQLite checkpoint store with the concurrency posture it needs."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    connection = settings.checkpoint_connection_string
    if connection != ":memory:":
        # The store's directory is part of the state layout, not something an
        # operator creates first - the same courtesy the application database
        # engine extends to its own file.
        settings.prepare_state_dir(Path(connection).parent)
    async with AsyncSqliteSaver.from_conn_string(connection) as checkpointer:
        # ``from_conn_string`` owns the connection but forwards no
        # serializer, so the posture is set on the saver it yields; the
        # saver derives nothing from ``serde`` at construction.
        checkpointer.serde = strict_checkpoint_serde()
        # Desktop profile boot must not mutate schema: ``setup()`` creates the
        # checkpointer tables, so it is suppressed when the profile is armed.
        # The staged-generation migration entrypoint runs setup instead, and
        # ordinary armed boot has already validated the schema is present.
        if settings.desktop_profile_armed:
            # Not calling setup() does not prevent it: the saver runs it
            # itself before its first read or write, so skipping the call
            # here only deferred the same DDL to the first checkpoint.
            # ``is_setup`` is how the saver records that it has nothing to
            # create, and the validation that ran before this said so.
            checkpointer.is_setup = True
        else:
            await checkpointer.setup()
        await _apply_sqlite_concurrency_pragmas(checkpointer)
        yield checkpointer


async def _apply_sqlite_concurrency_pragmas(checkpointer: Any) -> None:
    """Put the SQLite store in WAL mode, and say so when it refuses.

    WAL lets the gateway's status reads run concurrently with the worker's
    checkpoint writes on the shared file, instead of blocking on a writer's
    lock (the recurring checkpoint_unavailable/missing degradations);
    busy_timeout bounds any residual lock wait rather than failing fast.
    """
    for statement in checkpoint_pragmas(settings.sqlite_busy_timeout_ms):
        await checkpointer.conn.execute(statement)
    journal_row = await (
        await checkpointer.conn.execute("PRAGMA journal_mode")
    ).fetchone()
    if journal_row is None or str(journal_row[0]).lower() != "wal":
        logger.warning(
            "Failed to enable WAL journal mode on the checkpoint store; "
            "actual mode: %r. Gateway status reads will contend with "
            "worker checkpoint writes.",
            None if journal_row is None else journal_row[0],
        )


@asynccontextmanager
async def _open_postgres_checkpointer() -> AsyncGenerator[Checkpointer]:
    """Open the Postgres checkpoint store on a loop psycopg accepts."""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        msg = (
            "Postgres checkpoint backend selected but "
            "`langgraph-checkpoint-postgres` is not installed."
        )
        raise RuntimeError(msg) from exc

    if sys.platform == "win32":
        async with _open_selector_thread_checkpointer(
            settings.checkpoint_connection_string
        ) as checkpointer:
            yield checkpointer
        return

    pool = _postgres_checkpoint_pool(settings.checkpoint_connection_string)
    await pool.open(wait=True)
    try:
        checkpointer = AsyncPostgresSaver(conn=pool, serde=strict_checkpoint_serde())
        await setup_postgres_checkpointer(checkpointer, pool)
        yield checkpointer
    finally:
        # The pool owns real server connections, so shutdown closes it rather
        # than leaving them to the process exit: an abandoned pool also leaves its
        # maintenance tasks attached to a loop that is about to go away.
        await pool.close()
