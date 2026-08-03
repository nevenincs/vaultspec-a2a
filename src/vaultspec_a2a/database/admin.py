"""Database administration verbs: migrate, snapshot, restore, clear.

Invoked via::

    python -m vaultspec_a2a.database.admin <action> [args]

These operate on the store rather than on a domain, so they live beside
:mod:`vaultspec_a2a.database.migrate` — the migration-configuration authority
they route through — rather than in ``control``, whose other modules are domain
orchestration layered over the repository functions.

Actions
-------
migrate [--fix]
    Apply pending revisions.  With ``--fix`` also truncates the write-ahead log
    and runs ``VACUUM``, which is the only path in this project that returns
    freed pages to the operating system.

snapshot [list]
    Without a sub-command: copy the live database to a timestamped file beside
    it.  With ``list``: enumerate those copies.

restore --name FILE [--yes]
    Overwrite the live database from a named snapshot.  Refuses while a service
    is listening on a configured port.

clear --yes
    Delete every application row, and the checkpoint state, preserving schema.
"""

from __future__ import annotations

__all__ = ["main"]

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from alembic.config import Config as AlembicConfig
    from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(database_url: str) -> AlembicConfig:
    """Build the Alembic configuration for the migration action.

    Delegates to the database package's programmatic builder - the project's one
    migration-configuration authority, shared with service startup and the
    desktop path - which resolves the revision scripts from installed package
    data.  Reading a configuration file instead would tie this module to a
    checkout: the repo-root ``alembic.ini`` is not part of the distribution, and
    the script location it names is relative to the working directory rather
    than to the installed package.
    """
    from .migrate import build_migration_config

    return build_migration_config(database_url)


def _migrate_to_head(database_url: str) -> None:
    """Apply every pending revision to the database named by ``database_url``."""
    from alembic import command

    command.upgrade(_alembic_cfg(database_url), "head")


def _get_db_path() -> Path:
    from ..control.config import settings

    if settings.resolved_database_backend != "sqlite":
        print(
            "File-based database operations are only supported "
            "for SQLite fallback mode.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    db_path = settings.database_path
    if str(db_path) == ":memory:":
        print("Cannot operate on in-memory database.", file=sys.stderr)
        raise SystemExit(1)
    return db_path


def _apply_sqlite_pragmas(dbapi_conn: sqlite3.Connection, _record: object) -> None:
    """Enforce foreign keys and a busy timeout on an administrative connection.

    The application engine gets these from its own connect listener, which is
    bound to that engine and cannot be reused here - the verbs below need a
    SYNCHRONOUS engine, and the listener is attached to the async one.  Applying
    the same set explicitly keeps this path from being the one posture that
    differs, which matters most for the destructive verbs: ``foreign_keys`` is
    per-connection and OFF by default, so without it SQLite would silently
    orphan child rows if the delete order were ever wrong, and ``busy_timeout``
    decides whether a locked database waits or fails immediately.
    """
    from ..control.config import settings

    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms:d}")
    cursor.close()


def _administrative_engine(url: str) -> Engine:
    """Return a synchronous engine carrying the project's SQLite pragmas."""
    from sqlalchemy import create_engine, event

    engine = create_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


def _action_migrate(fix: bool) -> None:
    """Run pending Alembic migrations, optionally with WAL cleanup and VACUUM."""
    import sqlite3

    from ..control.config import settings

    _migrate_to_head(settings.database_url)
    print("Migrated to head.")

    if not fix:
        return

    db_path = _get_db_path()
    if not db_path.exists():
        print("Database file not found; skipping WAL fix.", file=sys.stderr)
        return

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.commit()
        print("WAL checkpoint and VACUUM complete.")
    finally:
        conn.close()


def _action_snapshot() -> None:
    """Create a timestamped SQLite snapshot alongside the live database."""
    import sqlite3
    from datetime import UTC, datetime

    db_path = _get_db_path()
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        raise SystemExit(1)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    dest = db_path.with_suffix(f".snapshot.{ts}")

    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    print(f"Snapshot: {dest}")


def _action_snapshot_list() -> None:
    """List available database snapshots."""
    db_path = _get_db_path()
    pattern = f"{db_path.stem}.snapshot.*"
    files = sorted(db_path.parent.glob(pattern), reverse=True)
    if not files:
        print("No snapshots found.")
        return
    for f in files:
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name}  ({size_kb:.0f} KB)")


def _action_restore(name: str, yes: bool) -> None:
    """Restore the database from a named snapshot.  Refuses if service is running."""
    if not yes:
        print(
            "This will overwrite the current database.  Pass --yes to confirm.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    import sqlite3
    from urllib import error, request

    from ..control.config import settings

    checks = [
        (settings.port, "/internal/health"),
        (settings.worker_port, "/health"),
    ]
    for check_port, path in checks:
        try:
            request.urlopen(f"http://127.0.0.1:{check_port}{path}", timeout=2.0)
            print(
                "Service is running.  Stop it first: just dev service stop",
                file=sys.stderr,
            )
            raise SystemExit(1)
        except (OSError, error.URLError):
            pass

    db_path = _get_db_path()
    snapshot_path = db_path.parent / name
    # Rejects both a ``..`` escape and an absolute path: joining an absolute
    # name replaces the base, and the resolved result then fails this check.
    if not snapshot_path.resolve().is_relative_to(db_path.parent.resolve()):
        print("Invalid snapshot name.", file=sys.stderr)
        raise SystemExit(1)
    if not snapshot_path.exists():
        print(f"Snapshot not found: {snapshot_path}", file=sys.stderr)
        raise SystemExit(1)

    src_conn = sqlite3.connect(str(snapshot_path))
    dst_conn = sqlite3.connect(str(db_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    print(f"Restored from {name}.")


# Child tables first, parent last: every table below except ``threads`` and
# ``authoring_event_cursor`` carries a foreign key to ``threads``, so deleting the
# parent first would be refused wherever foreign keys are enforced.
#
# A previous list covered four of these nine and no checkpoint state, so a
# "clear" left control actions, permission requests, queued tasks, execution
# state, the authoring cursor, and every conversation checkpoint in place - and
# reported success. An incomplete truncation that announces completion is worse
# than none, because the operator stops looking.
_CLEAR_ORDER: tuple[str, ...] = (
    "artifacts",
    "permission_logs",
    "permission_requests",
    "control_actions",
    "cost_tracking",
    "task_queue_entries",
    "thread_execution_state",
    "thread_deletion_saga",
    "authoring_event_cursor",
    "threads",
)

# LangGraph owns these; they hold the only durable copy of agent conversation
# content, so a clear that spares them leaves the bulk of the data behind.
_CHECKPOINT_TABLES: tuple[str, ...] = ("writes", "checkpoints")


def _action_clear(yes: bool) -> None:
    """Delete all application data rows (preserves schema)."""
    if not yes:
        print(
            "This is a destructive operation.  Pass --yes to confirm.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    from sqlalchemy import text

    from ..control.config import settings

    # The table names are this module's own constants and never reach here from
    # input, which is what makes interpolating them into the statement safe.
    engine = _administrative_engine(settings.database_sync_url)
    cleared: list[str] = []
    try:
        with engine.begin() as conn:
            for table in _CLEAR_ORDER:
                conn.execute(text(f"DELETE FROM {table}"))
                cleared.append(table)
    finally:
        engine.dispose()
    cleared.extend(_clear_checkpoint_store())
    print(f"Cleared {len(cleared)} tables.")


def _clear_checkpoint_store() -> list[str]:
    """Delete LangGraph checkpoint state, reporting which tables were cleared.

    The checkpoint store may live in the application database or in a database of
    its own, and it is created by LangGraph on first use rather than by this
    project's migrations - so a fresh installation legitimately has no such
    tables. A missing table is therefore skipped rather than treated as an error,
    while a present one is always cleared.
    """
    from sqlalchemy import inspect, text

    from ..control.config import settings

    engine = _administrative_engine(settings.checkpoint_sync_url)
    cleared: list[str] = []
    try:
        present = set(inspect(engine).get_table_names())
        with engine.begin() as conn:
            for table in _CHECKPOINT_TABLES:
                if table not in present:
                    continue
                conn.execute(text(f"DELETE FROM {table}"))
                cleared.append(table)
    finally:
        engine.dispose()
    return cleared


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vaultspec_a2a.database.admin",
        description="Database administration operations.",
    )
    sub = parser.add_subparsers(dest="action", metavar="ACTION")

    migrate_p = sub.add_parser("migrate", help="Run pending Alembic migrations.")
    migrate_p.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help=(
            "After migrating: clear stale WAL locks (PRAGMA wal_checkpoint(TRUNCATE)) "
            "and run VACUUM."
        ),
    )

    snapshot_p = sub.add_parser(
        "snapshot",
        help="Create a timestamped snapshot, or manage snapshots.",
    )
    snapshot_sub = snapshot_p.add_subparsers(dest="snapshot_cmd", metavar="SUBCMD")
    snapshot_sub.add_parser("list", help="List available snapshots.")

    restore_p = sub.add_parser("restore", help="Restore database from a snapshot.")
    restore_p.add_argument(
        "--name",
        required=True,
        metavar="FILE",
        help=(
            "Snapshot filename to restore (must live in the same directory as the DB)."
        ),
    )
    restore_p.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Confirm destructive operation.",
    )

    clear_p = sub.add_parser(
        "clear", help="Delete all application data (keeps schema)."
    )
    clear_p.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Confirm destructive operation.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.action is None:
        parser.print_help()
        return 1

    if args.action == "migrate":
        _action_migrate(fix=args.fix)

    elif args.action == "snapshot":
        if getattr(args, "snapshot_cmd", None) == "list":
            _action_snapshot_list()
        else:
            _action_snapshot()

    elif args.action == "restore":
        _action_restore(name=args.name, yes=args.yes)

    elif args.action == "clear":
        _action_clear(yes=args.yes)

    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
