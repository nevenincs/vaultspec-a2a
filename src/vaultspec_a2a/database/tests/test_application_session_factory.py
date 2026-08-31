"""Initialising the database makes the process REPORT that it has one.

The event-relay handlers persist a run's terminal status, permission journal,
control settlements, and execution-state projections through whatever session
factory they can find. When no factory is injected they ask the process for its
application factory, and a ``None`` answer means "this process owns no database"
- at which point they skip the durable write rather than perform it against an
engine invented from ambient settings.

That skip is only correct while ``init_db`` actually seats the singleton. It did
not: it passed an explicit engine, and ``get_session_factory`` deliberately
leaves the singleton alone for an explicit engine, so a fully booted gateway
reported no database and every durable projection would have been skipped in
silence. These pin both halves of that contract, because either one alone is
satisfied by the broken arrangement.

Real engines against real SQLite files; the module singletons are restored
afterwards so the process is left as it was found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .. import session as session_module
from ..session import application_session_factory, get_session_factory, init_db

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio(loop_scope="function")
async def test_init_db_seats_the_application_session_factory(tmp_path: Path) -> None:
    """After ``init_db``, the process reports the database it just initialised.

    This is the invariant the relay handlers' skip depends on. Without it they
    read a booted gateway as having no database and drop every durable write
    without raising - the quietest possible data loss.
    """
    saved_engine = session_module._engine
    saved_factory = session_module._session_factory
    session_module._engine = None
    session_module._session_factory = None
    try:
        assert application_session_factory() is None, (
            "the fixture must start from a process that owns no database, or the "
            "assertion below passes on a factory it did not seat"
        )

        engine = await init_db(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
        try:
            seated = application_session_factory()
            assert seated is not None, (
                "a booted process must report the database init_db just opened"
            )
            # Bound to THAT engine, not to some other one that merely exists.
            assert seated.kw["bind"] is engine
        finally:
            await engine.dispose()
    finally:
        session_module._engine = saved_engine
        session_module._session_factory = saved_factory


@pytest.mark.asyncio(loop_scope="function")
async def test_an_explicit_engine_still_does_not_adopt_the_process(
    tmp_path: Path,
) -> None:
    """``get_session_factory(engine)`` remains a local factory, not an adoption.

    The counterpart that keeps the fix honest. Seating the singleton from
    ``init_db`` must not become "any explicit engine takes over the process":
    callers pass one to get a factory bound to a database of their own, and
    hijacking the singleton from there would point every uninjected durable
    write at whichever engine was constructed last.
    """
    saved_engine = session_module._engine
    saved_factory = session_module._session_factory
    session_module._engine = None
    session_module._session_factory = None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        local = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'local.db'}")
        try:
            factory = get_session_factory(local)
            assert factory.kw["bind"] is local
            assert application_session_factory() is None, (
                "an explicit engine must not become the process-wide database"
            )
        finally:
            await local.dispose()
    finally:
        session_module._engine = saved_engine
        session_module._session_factory = saved_factory
