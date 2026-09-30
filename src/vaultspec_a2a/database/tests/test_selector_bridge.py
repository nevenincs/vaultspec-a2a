"""The Windows selector-thread saver must behave like the saver it wraps.

Windows runs the Proactor event loop for the provider subprocesses, and psycopg
refuses it, so the PostgreSQL saver lives on a selector loop of its own and the
rest of the runtime talks to it through this bridge. Everything the bridge gets
wrong is invisible on the platform that never loads it, so the bridge is
exercised here on whatever platform the suite runs on, against the real server.

Four contracts, each one a way the bridge stopped being a drop-in saver: the
answers it can compute itself must not cross the thread boundary, its
synchronous surface must actually answer, narrowing the allowlist must clone
rather than rewrite the bridge everyone else is holding, and a start that fails
must leave neither the thread nor the connections behind.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint

from ..checkpoints import (
    _open_selector_thread_checkpointer,
    _SelectorThreadPostgresCheckpointer,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from ...conftest import ExternalPrerequisiteRule

_POSTGRES_URL_ENV = "VAULTSPEC_A2A_TEST_POSTGRES_URL"
_SELECTOR_THREAD_NAME = "vaultspec-postgres-checkpointer"

# Long enough that a call which really does cross to the selector loop cannot
# finish inside it, short enough not to drag the suite.
_STALL_SECONDS = 0.5


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _selector_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == _SELECTOR_THREAD_NAME]


@pytest_asyncio.fixture
async def bridge(
    external_prerequisite: ExternalPrerequisiteRule,
) -> AsyncIterator[_SelectorThreadPostgresCheckpointer]:
    """The bridge, opened through the same block the Windows branch uses."""
    external_prerequisite("postgres")
    async with _open_selector_thread_checkpointer(
        os.environ[_POSTGRES_URL_ENV]
    ) as checkpointer:
        yield cast("_SelectorThreadPostgresCheckpointer", checkpointer)


def _stall_selector_loop(bridge: _SelectorThreadPostgresCheckpointer) -> None:
    """Occupy the selector loop with a step that does not await.

    Stands in for any long non-awaiting moment on that loop. Anything the bridge
    forwards there is stuck behind it; anything it answers itself is not.
    """
    loop = bridge._loop
    assert loop is not None
    loop.call_soon_threadsafe(time.sleep, _STALL_SECONDS)


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_the_next_channel_version_is_computed_without_the_selector_loop(
    bridge: _SelectorThreadPostgresCheckpointer,
) -> None:
    """The Pregel loop calls this per channel per superstep, from its own loop.

    It is arithmetic on the argument - no connection, no state - so forwarding
    it bought nothing and cost the caller's loop a stall for as long as the
    selector loop was busy.
    """
    _stall_selector_loop(bridge)
    await asyncio.sleep(0.01)

    started = time.perf_counter()
    first = bridge.get_next_version(None, None)
    second = bridge.get_next_version(first, None)
    elapsed = time.perf_counter() - started

    assert elapsed < _STALL_SECONDS / 2, (
        f"get_next_version waited {elapsed:.3f}s on the selector loop"
    )
    # Still the wrapped saver's own scheme, not one invented here: the same
    # zero-padded counter, and monotonic across calls as the contract requires.
    assert (
        first.split(".")[0]
        == bridge._inner().get_next_version(None, None).split(".")[0]
    )
    assert second > first


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_the_config_specs_are_answered_without_the_selector_loop(
    bridge: _SelectorThreadPostgresCheckpointer,
) -> None:
    """A constant the saver reports about itself, read while building a config."""
    _stall_selector_loop(bridge)
    await asyncio.sleep(0.01)

    started = time.perf_counter()
    specs = bridge.config_specs
    elapsed = time.perf_counter() - started

    assert elapsed < _STALL_SECONDS / 2, (
        f"config_specs waited {elapsed:.3f}s on the selector loop"
    )
    assert specs == bridge._inner().config_specs


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_the_synchronous_surface_answers_instead_of_refusing_itself(
    bridge: _SelectorThreadPostgresCheckpointer,
) -> None:
    """A synchronous caller must get a checkpoint back, not the saver's refusal.

    The wrapped saver's own synchronous methods marshal onto the loop they were
    built on - which is the selector loop the bridge hands them to - so calling
    them there either refused outright or waited on the loop that had to run
    them. Driven from a worker thread, which is where a synchronous caller
    lives.
    """
    thread_id = f"selector-sync-{uuid4().hex}"
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{uuid4().hex}"

    def synchronous_round_trip() -> tuple[Any, list[Any]]:
        stored_config = bridge.put(
            _config(thread_id),
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            checkpoint["channel_versions"],
        )
        bridge.put_writes(stored_config, [("log", "one")], f"task-{uuid4().hex}")
        return bridge.get_tuple(_config(thread_id)), list(
            bridge.list(_config(thread_id))
        )

    try:
        stored, listed = await asyncio.wait_for(
            asyncio.to_thread(synchronous_round_trip), 30.0
        )

        assert stored is not None
        assert stored.checkpoint["id"] == checkpoint["id"]
        assert stored.pending_writes
        assert [item.checkpoint["id"] for item in listed] == [checkpoint["id"]]
        assert await asyncio.to_thread(bridge.get, _config(thread_id)) is not None
    finally:
        await bridge.adelete_thread(thread_id)

    assert await bridge.aget_tuple(_config(thread_id)) is None


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_narrowing_the_allowlist_clones_the_bridge(
    bridge: _SelectorThreadPostgresCheckpointer,
) -> None:
    """Compilation narrows the allowlist per graph; it must not rewrite the bridge.

    The bridge is shared by every run in the process. Swapping its inner saver
    in place and returning itself gave one caller's allowlist to all of them,
    including runs already compiled against it.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    # An allowlist that can actually be narrowed: the default serializer admits
    # every type, so the base contract correctly returns the saver unchanged
    # and there would be nothing to clone.
    restricted = JsonPlusSerializer(allowed_msgpack_modules=None)
    bridge._inner().serde = restricted
    bridge.serde = restricted

    original_inner = bridge._inner()
    original_serde = bridge.serde

    narrowed = bridge.with_allowlist([("builtins", "set")])

    assert narrowed is not bridge
    assert isinstance(narrowed, _SelectorThreadPostgresCheckpointer)
    assert bridge._inner() is original_inner
    assert bridge.serde is original_serde
    assert narrowed.serde is not original_serde

    # The clone is a working saver, on the same thread and pool.
    thread_id = f"selector-allowlist-{uuid4().hex}"
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{uuid4().hex}"
    try:
        await narrowed.aput(
            cast("Any", _config(thread_id)),
            checkpoint,
            cast("Any", {"source": "loop", "step": 1, "parents": {}}),
            checkpoint["channel_versions"],
        )
        # Written through the clone, readable through the original: one store.
        assert await bridge.aget_tuple(cast("Any", _config(thread_id))) is not None
    finally:
        await bridge.adelete_thread(thread_id)


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_the_bridge_does_not_claim_what_the_saver_behind_it_cannot_do(
    bridge: _SelectorThreadPostgresCheckpointer,
) -> None:
    """Proxying an unimplemented method makes the bridge lie about itself.

    A caller choosing between a saver's own pruning and a fallback asks whether
    the method is overridden. The wrapped saver implements none of these, so a
    proxy answered yes on its behalf and the caller took the path that refuses.
    """
    for name in ("aprune", "adelete_for_runs", "acopy_thread", "prune", "copy_thread"):
        assert getattr(type(bridge), name) is getattr(BaseCheckpointSaver, name), name
        assert getattr(type(bridge._inner()), name) is getattr(
            BaseCheckpointSaver, name
        ), name

    with pytest.raises(NotImplementedError):
        await bridge.aprune([f"selector-prune-{uuid4().hex}"])


@pytest.fixture
def database_that_refuses_setup(
    external_prerequisite: ExternalPrerequisiteRule,
) -> Iterator[str]:
    """A reachable database whose checkpoint migration ledger is unusable.

    The pool opens and the selector thread starts; ``setup`` then fails reading
    a migration table that exists with the wrong shape, which is the failure
    mode that used to strand both.
    """
    external_prerequisite("postgres")
    import psycopg
    from psycopg import sql

    server = os.environ[_POSTGRES_URL_ENV]
    name = f"a2a_bridge_{uuid4().hex[:12]}"
    database = sql.Identifier(name)

    async def create() -> None:
        async with await psycopg.AsyncConnection.connect(
            server, autocommit=True
        ) as admin:
            await admin.execute(sql.SQL("CREATE DATABASE {}").format(database))
        async with await psycopg.AsyncConnection.connect(
            _with_database(server, name), autocommit=True
        ) as connection:
            await connection.execute(
                "CREATE TABLE checkpoint_migrations (other_column INT PRIMARY KEY)"
            )

    async def drop() -> None:
        async with await psycopg.AsyncConnection.connect(
            server, autocommit=True
        ) as admin:
            await admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database)
            )

    asyncio.run(create())
    try:
        yield _with_database(server, name)
    finally:
        asyncio.run(drop())


async def _backend_count(url: str) -> int:
    import psycopg

    database = urlsplit(url).path.lstrip("/")
    async with await psycopg.AsyncConnection.connect(
        os.environ[_POSTGRES_URL_ENV], autocommit=True
    ) as admin:
        cursor = await admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (database,)
        )
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_a_failed_setup_releases_the_selector_thread_and_the_pool(
    database_that_refuses_setup: str,
) -> None:
    """A gateway that cannot start must not keep a thread and connections.

    Setup ran outside the block that closes the bridge, so a refusal here left
    the selector thread running and its connections checked out on the server
    until the process exited - and the process was exiting because of this very
    failure only when nothing retried.
    """
    threads_before = len(_selector_threads())

    with pytest.raises(Exception, match=r"(?i)column|does not exist"):
        async with _open_selector_thread_checkpointer(database_that_refuses_setup):
            pytest.fail("setup should have refused this database")

    assert len(_selector_threads()) == threads_before
    assert await _backend_count(database_that_refuses_setup) == 0
