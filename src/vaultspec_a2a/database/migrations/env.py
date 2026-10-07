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
from sqlalchemy import inspect, pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic loads this file by SCRIPT LOCATION rather than importing it as a
# module, so at runtime it has no parent package and a relative import would
# raise "attempted relative import with no known parent package". These are the
# intra-package imports that must stay absolute.
from vaultspec_a2a.database._write_authority_check_parser import (  # absolute-import-ok
    extract_named_check_predicates,
)
from vaultspec_a2a.database.models import (  # absolute-import-ok
    Base,
)
from vaultspec_a2a.database.thread_repository import (  # absolute-import-ok
    select_invalid_authority_thread,
    select_orphaned_writer_thread,
)
from vaultspec_a2a.database.write_authority_schema import (  # absolute-import-ok
    WRITE_AUTHORITY_CHECKS,
    WRITE_AUTHORITY_COLUMNS,
    named_checks_match,
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
    "or use the product entry point, which migrates the application home's "
    "stores for you:\n"
    "    vaultspec-a2a migrate"
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


#: The revision that installed run write authority.
_AUTHORITY_REVISION = "0017"
#: The revision that narrowed the run writer's action vocabulary.
_NARROWED_ACTIONS_REVISION = "0026"
_WRITER_ACTION_CHECK = "ck_threads_writer_action_type_current"
# Spelled literally, as the revisions spell it: this is the predicate every
# revision from 0017 up to 0026 left on ``threads``, and it must not follow
# whatever the package's action vocabulary means later.
_PRE_NARROWING_WRITER_ACTION_PREDICATE = (
    "writer_action_type IN "
    "('ingest', 'resume', 'cancel', 'permission_request_created', "
    "'permission_response_submitted', 'permission_response_applied', "
    "'message_followup_requested', 'message_followup_applied', "
    "'repair_started', 'repair_finished')"
)


def _store_reached(connection: Connection, tables: set[str], revision: str) -> bool:
    """Whether the store's recorded revision is *revision* or descends from it."""
    current_revision = None
    if "alembic_version" in tables:
        current_revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one_or_none()
    if current_revision is None:
        return False
    revisions = ScriptDirectory.from_config(config).iterate_revisions(
        str(current_revision), "base"
    )
    return any(candidate.revision == revision for candidate in revisions)


def _expected_write_authority_checks(narrowed: bool) -> dict[str, str]:
    """The write-authority CHECKs a store at its recorded revision must carry.

    A store that has not yet reached the narrowing revision still admits the
    retired repair actions in its writer CHECK; that revision rebuilds the
    CHECK, so holding such a store to the current predicate would refuse the
    very upgrade that brings it current. Its rows are still proven against the
    current vocabulary by the populated-store check.
    """
    if narrowed:
        return dict(WRITE_AUTHORITY_CHECKS)
    return {
        **WRITE_AUTHORITY_CHECKS,
        _WRITER_ACTION_CHECK: _PRE_NARROWING_WRITER_ACTION_PREDICATE,
    }


def _has_current_write_authority_structure(
    connection: Connection, inspector: Inspector, *, narrowed: bool
) -> bool:
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
    has_structure = all(actual.get(name) == shape for name, shape in expected.items())
    create_table_sql = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'threads'"
    ).scalar_one_or_none()
    checks = (
        extract_named_check_predicates(str(create_table_sql))
        if create_table_sql is not None
        else {}
    )
    return (
        has_structure
        and write_authority_receipt_index_matches(inspector.get_indexes("threads"))
        and named_checks_match(checks, _expected_write_authority_checks(narrowed))
    )


def _validate_populated_write_authority(
    connection: Connection, tables: set[str]
) -> None:
    invalid = connection.execute(select_invalid_authority_thread()).first()
    has_actions = "control_actions" in tables
    incoherent = None
    if has_actions:
        incoherent = connection.execute(select_orphaned_writer_thread()).first()
    if invalid is not None or not has_actions or incoherent is not None:
        connection.rollback()
        raise CommandError(
            "cannot migrate a populated store with invalid or unknown "
            "write authority; create a fresh current application home"
        )


def _validate_current_only_head(connection: Connection) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    populated = (
        "threads" in tables
        and connection.exec_driver_sql("SELECT 1 FROM threads LIMIT 1").first()
        is not None
    )
    authority_installed = _store_reached(connection, tables, _AUTHORITY_REVISION)
    if populated or authority_installed:
        narrowed = _store_reached(connection, tables, _NARROWED_ACTIONS_REVISION)
        if not _has_current_write_authority_structure(
            connection, inspector, narrowed=narrowed
        ):
            connection.rollback()
            raise CommandError(
                "cannot migrate a store without complete current "
                "write authority; create a fresh current application home"
            )
        if populated:
            _validate_populated_write_authority(connection, tables)
    connection.rollback()


def do_run_migrations(connection: Connection) -> None:
    """Sync migration runner called inside ``run_sync``."""
    if config.attributes.get("vaultspec_current_only_head"):
        _validate_current_only_head(connection)
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
    settings = dict(config.get_section(config.config_ini_section, {}))
    settings["sqlalchemy.url"] = resolve_database_url()
    engine_options: dict[str, object] = {}
    busy_timeout_ms = config.attributes.get("sqlite_busy_timeout_ms")
    if isinstance(busy_timeout_ms, int):
        engine_options["connect_args"] = {"timeout": busy_timeout_ms / 1000}
    connectable = async_engine_from_config(
        settings,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        **engine_options,
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
