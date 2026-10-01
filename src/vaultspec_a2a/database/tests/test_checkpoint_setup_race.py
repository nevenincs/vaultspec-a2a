"""Two processes may open the checkpointer on a fresh database at once.

The gateway and the worker both run the checkpointer's schema setup at start.
``CREATE TABLE IF NOT EXISTS`` is not atomic against a concurrent creator, so
on an empty database the two collide inside PostgreSQL's own catalog and the
loser fails on a unique index it never named. Shipped start ordering keeps them
apart today; a second worker or a saver migration would not.

Proven with two real OS processes against a real server, because a race between
two connections in one process is a different race. Each trial gets its own
freshly created database: the collision only exists while the schema is absent.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ...conftest import ExternalPrerequisiteRule

_POSTGRES_URL_ENV = "VAULTSPEC_A2A_TEST_POSTGRES_URL"

# The race reproduced on every attempt before the lock, so a handful of trials
# is enough to catch a regression without making the suite pay for a hundred
# process spawns.
_TRIALS = 3
_CHILD_TIMEOUT_SECONDS = 120.0


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _open_checkpointer_in_child(url: str, barrier: Any, results: Any) -> None:
    """Open the production checkpointer, in step with the sibling process.

    Module level and importable, because a spawned child re-imports this module
    rather than inheriting the parent's memory.
    """

    async def run() -> str:
        from ...testing.environment import settings_override
        from ..checkpoints import open_checkpointer

        try:
            with settings_override(
                checkpoint_backend="postgres", checkpoint_database_url=url
            ):
                barrier.wait()
                async with open_checkpointer():
                    return "ok"
        except Exception as exc:
            return f"{type(exc).__name__}: {str(exc).splitlines()[0]}"

    results.put(asyncio.run(run()))


async def _admin(statement: Any) -> None:
    import psycopg

    async with await psycopg.AsyncConnection.connect(
        os.environ[_POSTGRES_URL_ENV], autocommit=True
    ) as connection:
        await connection.execute(statement)


@pytest.fixture
def fresh_database(external_prerequisite: ExternalPrerequisiteRule) -> Iterator[str]:
    """Create an empty database for one trial and drop it afterwards."""
    external_prerequisite("postgres")
    from psycopg import sql

    name = f"a2a_setup_race_{uuid4().hex[:12]}"
    # Composed as an identifier rather than interpolated, so the quoting is the
    # driver's rather than this test's.
    database = sql.Identifier(name)
    asyncio.run(_admin(sql.SQL("CREATE DATABASE {}").format(database)))
    try:
        yield _with_database(os.environ[_POSTGRES_URL_ENV], name)
    finally:
        asyncio.run(
            _admin(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database))
        )


def _race_two_openers(url: str) -> list[str]:
    """Open the checkpointer from two processes released together."""
    context = mp.get_context("spawn")
    barrier = context.Barrier(2)
    results: Any = context.Queue()
    processes = [
        context.Process(
            target=_open_checkpointer_in_child, args=(url, barrier, results)
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    try:
        outcomes = [results.get(timeout=_CHILD_TIMEOUT_SECONDS) for _ in processes]
    finally:
        for process in processes:
            process.join(_CHILD_TIMEOUT_SECONDS)
    return outcomes


@pytest.mark.requires_prerequisites("postgres")
@pytest.mark.parametrize("trial", range(_TRIALS))
def test_two_processes_set_up_a_fresh_checkpoint_database_together(
    fresh_database: str, trial: int
) -> None:
    """Neither opener may fail, and the schema must exist once they are done."""
    del trial

    outcomes = _race_two_openers(fresh_database)

    assert outcomes == ["ok", "ok"], outcomes


@pytest.mark.requires_prerequisites("postgres")
def test_the_second_process_finds_the_schema_the_first_one_migrated(
    fresh_database: str,
) -> None:
    """Serializing setup must still leave one complete, migrated schema.

    A lock that made the race disappear by leaving the loser's setup half done
    would pass the test above and break every run afterwards, so the migration
    ledger is read back from the database itself.
    """
    import psycopg

    assert _race_two_openers(fresh_database) == ["ok", "ok"]

    async def read_versions() -> list[int]:
        async with await psycopg.AsyncConnection.connect(
            fresh_database, autocommit=True
        ) as connection:
            cursor = await connection.execute(
                "SELECT v FROM checkpoint_migrations ORDER BY v"
            )
            return [int(row[0]) for row in await cursor.fetchall()]

    versions = asyncio.run(read_versions())

    # Contiguous from zero and recorded once each: a partial or duplicated
    # migration run shows up here as a gap or a repeat.
    assert versions == list(range(len(versions)))
    assert len(versions) > 1
