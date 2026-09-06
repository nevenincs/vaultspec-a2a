"""Alembic async migration environment for SQLite + aiosqlite.

Uses the canonical async pattern: ``async_engine_from_config`` with
``run_sync`` bridge.  LangGraph checkpoint tables are excluded via
``include_name`` allowlist keyed to ``Base.metadata``.

References:
    - Alembic async template: https://alembic.sqlalchemy.org/en/latest/cookbook.html
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from alembic.runtime.environment import NameFilterParentNames, NameFilterType
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import inspect, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic loads this file by SCRIPT LOCATION rather than importing it as a
# module, so at runtime it has no parent package and a relative import would
# raise "attempted relative import with no known parent package". This is the
# one intra-package import that must stay absolute.
from vaultspec_a2a.database.models import (  # absolute-import-ok
    Base,
)
from vaultspec_a2a.database.write_authority_schema import (  # absolute-import-ok
    WRITE_ACTION_SQL_VALUES,
    WRITE_AUTHORITY_COLUMNS,
    write_authority_checks_match,
    write_authority_receipt_index_matches,
)

# -- Alembic config object ---------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# -- Target metadata (app-owned tables only) ----------------------------------
target_metadata = Base.metadata


def include_name(
    name: str | None,
    type_: NameFilterType,
    _parent_names: NameFilterParentNames,
) -> bool:
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


# -- Database URL resolution --------------------------------------------------

#: ``-x`` key through which the bare Alembic CLI names its target database.
_URL_ARGUMENT = "sqlalchemy_url"

_MISSING_URL_MESSAGE = (
    "No database URL was supplied. alembic.ini leaves sqlalchemy.url empty on "
    "purpose, so that a bare `alembic` run cannot migrate whatever database a "
    "stale default happens to name. Name the target explicitly:\n"
    "    alembic -x sqlalchemy_url=sqlite+aiosqlite:///path/to/vaultspec.db "
    "upgrade head\n"
    "or use the administrative entry point, which resolves the configured "
    "store for you:\n"
    "    python -m vaultspec_a2a.database.admin migrate"
)


def resolve_database_url() -> str:
    """Return the database URL this run must migrate.

    Two kinds of caller reach this file. ``database.migrate`` builds its config
    programmatically and sets ``sqlalchemy.url`` directly; a human on the bare
    CLI has only ``alembic.ini``, which ships that option empty and documents
    ``-x sqlalchemy_url=...`` as the way to fill it. Reading that argument here
    is what makes the documented invocation work; without it the empty string
    travels all the way to SQLAlchemy, whose "Could not parse SQLAlchemy URL"
    names neither the cause nor the remedy.

    The ``-x`` value wins over the config file so a CLI run can retarget a
    populated ``alembic.ini``, and an absent URL raises here rather than
    downstream.

    Raises:
        CommandError: When neither source names a database.
    """
    override = context.get_x_argument(as_dictionary=True).get(_URL_ARGUMENT)
    url = override or config.get_main_option("sqlalchemy.url")
    if not url:
        raise CommandError(_MISSING_URL_MESSAGE)
    return url


# -- Offline mode -------------------------------------------------------------


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the database."""
    url = resolve_database_url()
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
    if config.attributes.get("vaultspec_current_only_head"):
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        populated = (
            "threads" in tables
            and connection.exec_driver_sql("SELECT 1 FROM threads LIMIT 1").first()
            is not None
        )
        current_revision = None
        if "alembic_version" in tables:
            current_revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one_or_none()
        authority_installed = False
        if current_revision is not None:
            revisions = ScriptDirectory.from_config(config).iterate_revisions(
                str(current_revision), "base"
            )
            authority_installed = any(
                candidate.revision == "0017" for candidate in revisions
            )
        if populated or authority_installed:
            expected = {
                name: (column_type, False, None)
                for name, column_type in WRITE_AUTHORITY_COLUMNS.items()
            }
            actual = {
                str(column["name"]): (
                    str(column["type"]).upper(),
                    bool(column["nullable"]),
                    column["default"],
                )
                for column in inspector.get_columns("threads")
            }
            has_structure = all(
                actual.get(name) == shape for name, shape in expected.items()
            )
            checks = {
                str(check["name"]): str(check["sqltext"])
                for check in inspector.get_check_constraints("threads")
                if check.get("name") is not None
            }
            if (
                not has_structure
                or not write_authority_receipt_index_matches(
                    inspector.get_indexes("threads")
                )
                or not write_authority_checks_match(
                    checks, dialect=connection.dialect.name
                )
            ):
                connection.rollback()
                raise CommandError(
                    "cannot migrate a store without complete current "
                    "write authority; create a fresh current application home"
                )
            if populated:
                invalid = connection.execute(
                    text(
                        f"""SELECT id FROM threads
                             WHERE run_revision < 0
                                OR writer_generation < 1
                                OR writer_action_type NOT IN ({WRITE_ACTION_SQL_VALUES})
                                OR length(trim(writer_action_receipt_id)) < 1
                                OR length(writer_action_receipt_id) > 64
                             LIMIT 1"""
                    )
                ).first()
                has_actions = "control_actions" in tables
                incoherent = None
                if has_actions:
                    incoherent = connection.execute(
                        text(
                            """SELECT t.id FROM threads AS t
                               LEFT JOIN control_actions AS a
                                 ON a.thread_id = t.id
                                AND a.dispatch_id = t.writer_action_receipt_id
                                AND a.action_type = t.writer_action_type
                               WHERE a.id IS NULL
                               LIMIT 1"""
                        )
                    ).first()
                if invalid is not None or not has_actions or incoherent is not None:
                    connection.rollback()
                    raise CommandError(
                        "cannot migrate a populated store with invalid or unknown "
                        "write authority; create a fresh current application home"
                    )
        connection.rollback()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and bridge to sync Alembic context."""
    settings = dict(config.get_section(config.config_ini_section, {}))
    settings["sqlalchemy.url"] = resolve_database_url()
    connectable = async_engine_from_config(
        settings,
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
