"""The PostgreSQL checkpointer holds a pool, and really uses more of it than one.

Against a real PostgreSQL server through the production ``open_checkpointer``
entry point, because every property under test is a property of what that
factory builds: a saver on one connection stayed broken for the life of the
process once that connection dropped, and a single saver over a pool still
serializes every statement behind its own lock, so concurrency takes a saver per
caller. The concurrency claims are measured in connections actually checked out,
not inferred from the pool's size.

Each test gets its own database. One of them terminates every backend on it to
prove the pool recovers, which no shared database could tolerate.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
import pytest_asyncio

from ...domain_config import domain_config
from ...testing import settings_override
from ...tests._checkpoint_seeding import real_checkpoint
from ..checkpoints import concurrent_checkpointer, open_checkpointer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable

    from ...conftest import ExternalPrerequisiteRule
    from ..checkpoints import Checkpointer

_POSTGRES_URL_ENV = "VAULTSPEC_A2A_TEST_POSTGRES_URL"

# Enough writers to exceed the pool, and a payload big enough that a write is
# still in flight when the next one starts. A checkpoint small enough to finish
# within one scheduling turn would show one connection in use whether or not the
# savers can run in parallel, and prove nothing either way.
_WRITERS = 12
_PAYLOAD_BYTES = 400_000


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


async def _write_checkpoint(
    saver: Checkpointer, thread_id: str, *, payload_bytes: int = 0
) -> None:
    """Put one checkpoint through the saver's own public write path."""
    checkpoint = await real_checkpoint()
    checkpoint["id"] = f"cp-{uuid4().hex}"
    if payload_bytes:
        checkpoint["channel_values"] = {"payload": "x" * payload_bytes}
        checkpoint["channel_versions"] = {
            "payload": saver.get_next_version(None, cast("Any", None))
        }
    await saver.aput(
        cast("Any", _config(thread_id)),
        checkpoint,
        cast("Any", {"source": "loop", "step": 1, "parents": {}}),
        checkpoint["channel_versions"],
    )


def _with_database(url: str, name: str) -> str:
    """Point *url* at another database on the same server."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


@pytest_asyncio.fixture
async def postgres_url(
    external_prerequisite: ExternalPrerequisiteRule,
) -> AsyncIterator[str]:
    """Create a database this module may disrupt, and drop it afterwards."""
    external_prerequisite("postgres")
    import psycopg
    from psycopg import sql

    server = os.environ[_POSTGRES_URL_ENV]
    name = f"a2a_pool_{uuid4().hex[:12]}"
    # The database name is composed as an identifier rather than interpolated, so
    # the quoting is the driver's rather than this test's.
    database = sql.Identifier(name)
    async with await psycopg.AsyncConnection.connect(server, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE DATABASE {}").format(database))
    try:
        yield _with_database(server, name)
    finally:
        async with await psycopg.AsyncConnection.connect(
            server, autocommit=True
        ) as admin:
            await admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database)
            )


@pytest_asyncio.fixture
async def postgres_checkpointer(postgres_url: str) -> AsyncIterator[Checkpointer]:
    """Open the production checkpointer against the live PostgreSQL server."""
    with settings_override(
        checkpoint_backend="postgres",
        checkpoint_database_url=postgres_url,
    ):
        async with open_checkpointer() as checkpointer:
            yield checkpointer


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_the_saver_is_backed_by_a_pool_sized_for_both_its_holders(
    postgres_checkpointer: Checkpointer,
) -> None:
    """The same factory serves the worker's runs and the gateway's probes.

    The ceiling follows the configured concurrency rather than a number written
    here: every run in flight can be writing a checkpoint, with headroom for the
    reads that are not a run's own, and a page of parallel status probes must
    fit too.
    """
    from psycopg_pool import AsyncConnectionPool

    pool = cast("Any", postgres_checkpointer).conn

    assert isinstance(pool, AsyncConnectionPool)
    assert pool.max_size >= domain_config.max_concurrent_threads + 2
    assert pool.max_size >= domain_config.thread_list_checkpoint_concurrency


async def _peak_checked_out(pool: Any, work: Awaitable[Any]) -> int:
    """Run *work*, sampling how many of *pool*'s connections are checked out."""
    peak = 0
    stop = asyncio.Event()

    async def sample() -> None:
        nonlocal peak
        while not stop.is_set():
            stats = pool.get_stats()
            peak = max(peak, stats.get("pool_size", 0) - stats.get("pool_available", 0))
            await asyncio.sleep(0)

    sampler = asyncio.create_task(sample())
    try:
        await work
    finally:
        stop.set()
        await sampler
    return peak


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_one_saver_uses_one_connection_however_many_writers_it_has(
    postgres_checkpointer: Checkpointer,
) -> None:
    """The lock, not the pool, is what decides a saver's concurrency.

    This is the property that makes a saver per caller necessary rather than a
    nicety, and it is measured rather than assumed: sharing one saver between
    concurrent writers keeps exactly one connection checked out at a time, so a
    pool sized for every run in flight would sit idle behind it.
    """
    pool = cast("Any", postgres_checkpointer).conn
    threads = [f"pool-shared-{uuid4().hex}" for _ in range(_WRITERS)]

    peak = await _peak_checked_out(
        pool,
        asyncio.gather(
            *(
                _write_checkpoint(
                    postgres_checkpointer, thread, payload_bytes=_PAYLOAD_BYTES
                )
                for thread in threads
            )
        ),
    )

    assert peak == 1, pool.get_stats()


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_a_saver_per_caller_really_writes_on_several_connections(
    postgres_checkpointer: Checkpointer,
) -> None:
    """Concurrent runs each get a saver, and the pool is then really used.

    Proven in connections the server actually handed out at the same moment -
    the claim a shared saver cannot make - and every write must still land.
    """
    pool = cast("Any", postgres_checkpointer).conn
    threads = [f"pool-per-run-{uuid4().hex}" for _ in range(_WRITERS)]
    savers = [await concurrent_checkpointer(postgres_checkpointer) for _ in threads]

    assert len({id(saver) for saver in savers}) == len(threads)

    peak = await _peak_checked_out(
        pool,
        asyncio.gather(
            *(
                _write_checkpoint(saver, thread, payload_bytes=_PAYLOAD_BYTES)
                for saver, thread in zip(savers, threads, strict=True)
            )
        ),
    )

    assert peak > 1, pool.get_stats()
    for thread in threads:
        assert (
            await postgres_checkpointer.aget_tuple(cast("Any", _config(thread)))
            is not None
        )


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_a_busy_connection_does_not_hold_up_another_run(
    postgres_checkpointer: Checkpointer,
) -> None:
    """A connection held open elsewhere must not stop a run checkpointing.

    A connection is held in an open transaction for the duration - which is what
    an unrelated reader mid-statement looks like from the outside - and the runs'
    writes have to complete anyway. On a single-connection saver they could not:
    there was nothing else to write on.
    """
    pool = cast("Any", postgres_checkpointer).conn
    threads = [f"pool-concurrent-{uuid4().hex}" for _ in range(3)]

    async with pool.connection() as held:
        await held.execute("SELECT 1")

        await asyncio.gather(
            *(_write_checkpoint(postgres_checkpointer, thread) for thread in threads)
        )

        # The occupied connection is still checked out, so the writes above cannot
        # have borrowed it.
        assert pool.get_stats()["pool_size"] > 1, pool.get_stats()

    for thread in threads:
        assert (
            await postgres_checkpointer.aget_tuple(cast("Any", _config(thread)))
            is not None
        )


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_a_dropped_connection_is_replaced_instead_of_ending_checkpointing(
    postgres_checkpointer: Checkpointer, postgres_url: str
) -> None:
    """A server that hangs up must cost one write at most, not the process.

    On one connection a drop disabled checkpointing until a restart: every later
    write met the same dead socket. Here the server terminates every backend this
    saver holds, for real, and the next write goes through on a replacement -
    which is what the pool's connection check buys.
    """
    import psycopg

    thread_id = f"pool-reconnect-{uuid4().hex}"
    await _write_checkpoint(postgres_checkpointer, thread_id)

    database = urlsplit(postgres_url).path.lstrip("/")
    server = os.environ[_POSTGRES_URL_ENV]
    # Terminated from a connection to ANOTHER database, so every session left on
    # this one belongs to the saver and the count below cannot flatter itself.
    async with await psycopg.AsyncConnection.connect(server, autocommit=True) as admin:
        terminated = await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (database,),
        )
        assert len(await terminated.fetchall()) >= 1, (
            "no backend was terminated, so this proves nothing about recovery"
        )

    await _write_checkpoint(postgres_checkpointer, thread_id)

    stored = await postgres_checkpointer.aget_tuple(cast("Any", _config(thread_id)))
    assert stored is not None


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_shutdown_closes_the_pool_it_opened(postgres_url: str) -> None:
    """The pool owns real server connections, so leaving it open leaks them."""
    from psycopg_pool import AsyncConnectionPool

    with settings_override(
        checkpoint_backend="postgres", checkpoint_database_url=postgres_url
    ):
        async with open_checkpointer() as checkpointer:
            pool = cast("Any", checkpointer).conn
            assert isinstance(pool, AsyncConnectionPool)
            assert pool.closed is False

    assert pool.closed is True
