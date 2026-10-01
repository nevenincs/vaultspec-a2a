"""Real SQLite and PostgreSQL targets for the dual-backend database proofs.

Both backends are first class for this service's application schema, and a
proof that runs on one of them proves half of what it claims. This module is
the single home of "give me a real, empty, migrated database on backend X", so
each suite states the property it asserts instead of re-deriving how to reach a
server.

Nothing here stands in for anything: the SQLite target is a real file carrying
the application's own engine posture (WAL, busy timeout, and the
``foreign_keys=ON`` without which SQLite silently ignores every cascade), the
PostgreSQL target is a real scratch database created on the configured server
and dropped afterwards, and both are brought to head by the packaged Alembic
chain rather than by ``create_all``.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...control.infra_config import _synchronous_url
from ..migrate import build_migration_config
from ..session import configure_sqlite_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

#: Only what a suite actually reaches for. The backend ids, the environment
#: name and the target record below are this module's own vocabulary; naming
#: them here would publish a surface nothing consumes.
__all__ = [
    "BACKENDS",
    "backend",
    "downgrade",
    "migrated_engine",
    "migrated_session_factory",
    "synchronous_url",
    "upgrade",
]

POSTGRES_URL_ENV = "VAULTSPEC_A2A_TEST_POSTGRES_URL"

#: Backend ids for the dual-backend proofs. Spelled here so a suite cannot
#: quietly parametrize over one backend and still read as covering both.
SQLITE = "sqlite"
POSTGRES = "postgres"

#: The parametrization every dual-backend proof uses. The PostgreSQL case
#: carries the prerequisite marker, so a run that does not declare a server
#: reports the backend as withheld rather than passing on half the evidence.
BACKENDS = (
    SQLITE,
    pytest.param(POSTGRES, marks=pytest.mark.requires_prerequisites(POSTGRES)),
)


@dataclass(frozen=True, slots=True)
class Backend:
    """One reachable, empty database and the async URL that opens it."""

    name: str
    url: str

    @property
    def is_sqlite(self) -> bool:
        """Whether this target is the file-backed SQLite lane."""
        return self.name == SQLITE


def _with_driver(url: str, drivername: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(scheme=drivername))


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def synchronous_url(url: str) -> str:
    """Return the synchronous equivalent of an async backend URL.

    Reflection is a synchronous API, and driving it through the production
    derivation keeps the test lane on the same drivers the service ships
    instead of naming psycopg2, which this project does not install.
    """
    return _synchronous_url(url, setting="the test backend URL")


def upgrade(url: str, revision: str = "head") -> None:
    """Drive the packaged Alembic chain against *url* up to *revision*.

    Synchronous on purpose: ``env.py`` opens an event loop of its own, so this
    must never be called from inside a running one.
    """
    command.upgrade(build_migration_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    """Drive the packaged Alembic chain against *url* down to *revision*."""
    command.downgrade(build_migration_config(url), revision)


@contextmanager
def _postgres_scratch_database() -> Generator[str]:
    """Create a uniquely named database on the configured server, then drop it."""
    import psycopg
    from psycopg import sql

    server = os.environ[POSTGRES_URL_ENV]
    name = f"a2a_scratch_{uuid4().hex[:12]}"
    identifier = sql.Identifier(name)
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
    try:
        yield _with_driver(_with_database(server, name), "postgresql+asyncpg")
    finally:
        with psycopg.connect(server, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(identifier)
            )


@contextmanager
def backend(name: str, directory: Path) -> Generator[Backend]:
    """Yield an empty, unmigrated database on the *name* backend.

    *directory* is used by the SQLite lane only and must be a test-owned
    temporary path; the PostgreSQL lane creates and drops a scratch database on
    the configured server instead.
    """
    if name == SQLITE:
        yield Backend(SQLITE, f"sqlite+aiosqlite:///{directory / 'application.db'}")
        return
    with _postgres_scratch_database() as url:
        yield Backend(POSTGRES, url)


@asynccontextmanager
async def migrated_engine(
    name: str, directory: Path
) -> AsyncGenerator[tuple[Backend, AsyncEngine]]:
    """Yield a migrated database on *name* and a pooled engine over it.

    The upgrade runs in a worker thread, exactly as the application's own
    startup runner does: Alembic's env opens an event loop of its own, which
    it cannot do on a loop that is already running.

    The engine carries the application's own SQLite posture, so a cascade this
    schema declares is enforced here exactly as production enforces it. It is
    disposed before the scratch database is dropped, because a live pooled
    connection is what makes ``DROP DATABASE`` fail.
    """
    with backend(name, directory) as target:
        await asyncio.to_thread(upgrade, target.url)
        engine = create_async_engine(target.url)
        if target.is_sqlite:
            configure_sqlite_engine(engine)
        try:
            yield target, engine
        finally:
            await engine.dispose()


@asynccontextmanager
async def migrated_session_factory(
    name: str, directory: Path
) -> AsyncGenerator[tuple[Backend, async_sessionmaker[AsyncSession]]]:
    """Yield a migrated database on *name* and a session factory over it."""
    async with migrated_engine(name, directory) as (target, engine):
        yield target, async_sessionmaker(engine, expire_on_commit=False)
