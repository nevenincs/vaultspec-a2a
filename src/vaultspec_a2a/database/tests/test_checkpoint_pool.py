"""The PostgreSQL checkpointer holds a pool, not one connection.

Against a real PostgreSQL server through the production ``open_checkpointer``
entry point, because both properties under test are properties of what that
factory builds: a saver on one connection serialized every run's checkpoint
writes behind each other, and it stayed broken for the life of the process once
that connection dropped.

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
from langgraph.checkpoint.base import empty_checkpoint

from ...domain_config import domain_config
from ...testing.environment import settings_override
from ..checkpoints import open_checkpointer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ...conftest import ExternalPrerequisiteRule
    from ..checkpoints import Checkpointer

_POSTGRES_URL_ENV = "VAULTSPEC_A2A_TEST_POSTGRES_URL"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


async def _write_checkpoint(saver: Checkpointer, thread_id: str) -> None:
    """Put one checkpoint through the saver's own public write path."""
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{uuid4().hex}"
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
async def test_the_saver_is_backed_by_a_pool_sized_from_the_run_bound(
    postgres_checkpointer: Checkpointer,
) -> None:
    """Every run in flight can be writing a checkpoint, so all of them fit.

    The ceiling follows the configured concurrency rather than a number written
    here, and carries headroom for the reads that are not a run's own.
    """
    from psycopg_pool import AsyncConnectionPool

    pool = cast("Any", postgres_checkpointer).conn

    assert isinstance(pool, AsyncConnectionPool)
    assert pool.max_size == domain_config.max_concurrent_threads + 2
    assert pool.max_size > domain_config.max_concurrent_threads


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_a_busy_connection_does_not_hold_up_another_run(
    postgres_checkpointer: Checkpointer,
) -> None:
    """One connection made every run's checkpoint write wait for the others.

    A connection is held in an open transaction for the duration - which is what
    a run mid-write looks like from the outside - and the other runs' writes have
    to complete anyway. On a single-connection saver they could not: there was
    nothing else to write on.
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
