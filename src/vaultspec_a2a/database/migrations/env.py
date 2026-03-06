"""Alembic async migration environment for SQLite + aiosqlite (ADR-029).

Uses the canonical async pattern: ``async_engine_from_config`` with
``run_sync`` bridge.  LangGraph checkpoint tables are excluded via
``include_name`` allowlist keyed to ``Base.metadata``.

References:
    - ADR-029: Database Migration Framework
    - Alembic async template: https://alembic.sqlalchemy.org/en/latest/cookbook.html
"""

import asyncio

from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from vaultspec_a2a.database.models import Base  # noqa: TID252 — Alembic loads env.py outside package context


# -- Alembic config object ---------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# -- Target metadata (app-owned tables only) ----------------------------------
target_metadata = Base.metadata


def include_name(name: str, type_: str, parent_names: dict) -> bool:  # noqa: ANN401, ARG001
    """Scope autogenerate to app-owned tables only.

    Uses allowlist form: only tables declared in ``Base.metadata`` are
    included.  This automatically excludes LangGraph checkpoint tables
    (``checkpoints``, ``writes``) and any other non-ORM tables that may
    appear in the SQLite file.

    ``include_name`` fires *before* reflection, avoiding the overhead of
    fully reflecting excluded tables.
    """
    if type_ == "table":
        return name in target_metadata.tables
    return True


# -- Offline mode -------------------------------------------------------------


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the database."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# -- Online mode (async) ------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Sync migration runner called inside ``run_sync``."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and bridge to sync Alembic context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
