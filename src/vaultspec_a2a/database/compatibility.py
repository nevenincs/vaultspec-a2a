"""Non-mutating schema-compatibility validation for the desktop profile.

Ordinary desktop gateway boot must perform no schema mutation: no Alembic
upgrade, no checkpointer table creation, and no state-driven-development (SDD)
backfill. Instead it validates that the seated stores are already compatible
with the running package and fails loud with an actionable remedy when they are
not. The staged-generation migration entrypoint owns every mutation under a
one-time transaction descriptor; ordinary boot only reads.

This module is the single authority for that read-only validation. It compares
the primary database's recorded Alembic revision against the package's migration
script head, validates the checkpoint store's semantic schema identity, and
confirms the SDD state fields are already present. Every check is a plain
synchronous SQLite read; no connection ever issues a write.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from .checkpoint_schema import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointSchemaError,
    open_checkpoint_read_only,
    validate_checkpoint_schema_connection,
)
from .control_action_schema import recovery_deadline_checks_match
from .migrate import build_migration_config
from .migrations import (
    CheckpointStateMigrationError,
    count_pending_sdd_backfill_connection,
)
from .write_authority_schema import (
    WRITE_ACTION_TYPES,
    WRITE_AUTHORITY_COLUMNS,
    extract_named_check_predicates,
    write_authority_checks_match,
    write_authority_receipt_index_matches,
)

__all__ = [
    "SchemaCompatibilityError",
    "supported_migration_head",
    "validate_desktop_schema",
]

_REMEDY = (
    "Run the desktop staged-generation migration entrypoint "
    "(the internal `vaultspec-a2a desktop migrate` command) under a valid "
    "one-time transaction descriptor to bring this application home to the "
    "current schema; ordinary desktop boot never migrates."
)


class SchemaCompatibilityError(RuntimeError):
    """The seated desktop stores are incompatible with the running package.

    Raised by :func:`validate_desktop_schema` when the primary database is
    unmigrated, at an unrecognised or non-head revision, when the checkpointer
    schema is absent, or when the SDD state fields have not been backfilled. The
    message always names the offending store and the staged-migration remedy so
    the failure is actionable rather than a bare boot crash.
    """


def _sqlite_path_from_url(database_url: str) -> Path:
    """Extract the on-disk file path from a SQLite SQLAlchemy URL."""
    if ":///" not in database_url:
        raise SchemaCompatibilityError(
            f"desktop schema validation requires a file-backed SQLite URL, got "
            f"{database_url!r}."
        )
    raw = database_url.split("///", 1)[1]
    if raw == ":memory:":
        raise SchemaCompatibilityError(
            "desktop schema validation cannot target an in-memory SQLite database."
        )
    return Path(raw)


def supported_migration_head(database_url: str) -> str:
    """Return the package's Alembic migration head revision.

    Resolved from the installed migration package through the same programmatic
    Alembic configuration the runner uses, so a clean installed capsule reports
    the head it actually carries.
    """
    from alembic.script import ScriptDirectory

    cfg = build_migration_config(database_url)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        raise SchemaCompatibilityError(
            "the packaged Alembic migration graph declares no head revision; "
            "reinstall vaultspec-a2a from a complete distribution."
        )
    return head


def _known_revisions(database_url: str) -> set[str]:
    """Return every revision identifier the package's migration graph defines."""
    from alembic.script import ScriptDirectory

    cfg = build_migration_config(database_url)
    script = ScriptDirectory.from_config(cfg)
    return {revision.revision for revision in script.walk_revisions()}


def _read_alembic_version(db_path: Path) -> str | None:
    """Return the primary database's recorded Alembic revision, or ``None``.

    ``None`` means the ``alembic_version`` table is absent (an empty or never
    migrated store) or carries no row.
    """
    if not db_path.is_file():
        return None
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
    finally:
        conn.close()
    if not rows:
        return None
    return str(rows[0][0])


def _validate_write_authority(db_path: Path) -> None:
    """Reject stamped, malformed, or receipt-incoherent current thread stores."""
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        columns = {
            str(row[1]): (str(row[2]).upper(), bool(row[3]), row[4])
            for row in conn.execute("PRAGMA table_info(threads)")
        }
        for name, expected_type in WRITE_AUTHORITY_COLUMNS.items():
            actual = columns.get(name)
            if actual != (expected_type, True, None):
                raise SchemaCompatibilityError(
                    f"desktop primary database at {db_path} has invalid current "
                    f"write-authority column {name!r}; expected required "
                    f"{expected_type} with no default. {_REMEDY}"
                )
        indexes: list[dict[str, object]] = []
        for row in conn.execute("PRAGMA index_list(threads)"):
            name = str(row[1])
            indexes.append(
                {
                    "name": name,
                    "unique": bool(row[2]),
                    "column_names": tuple(
                        str(info[0])
                        for info in conn.execute(
                            "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                            (name,),
                        )
                    ),
                }
            )
        if not write_authority_receipt_index_matches(indexes):
            raise SchemaCompatibilityError(
                f"desktop primary database at {db_path} lacks the unique current "
                f"write-authority receipt index. {_REMEDY}"
            )
        table_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'threads'"
        ).fetchone()
        table_sql = "" if table_sql_row is None else str(table_sql_row[0])
        if not write_authority_checks_match(extract_named_check_predicates(table_sql)):
            raise SchemaCompatibilityError(
                f"desktop primary database at {db_path} lacks required current "
                f"write-authority checks. {_REMEDY}"
            )
        action_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'control_actions'"
        ).fetchone()
        action_sql = "" if action_sql_row is None else str(action_sql_row[0])
        if not recovery_deadline_checks_match(
            extract_named_check_predicates(action_sql)
        ):
            raise SchemaCompatibilityError(
                f"desktop primary database at {db_path} lacks the exact current "
                f"control-action recovery deadline check. {_REMEDY}"
            )
        placeholders = ", ".join("?" for _ in WRITE_ACTION_TYPES)
        invalid = conn.execute(
            f"""SELECT id FROM threads
                 WHERE run_revision < 0
                    OR writer_generation < 1
                    OR writer_action_type NOT IN ({placeholders})
                    OR length(trim(writer_action_receipt_id)) < 1
                    OR length(writer_action_receipt_id) > 64
                 LIMIT 1""",
            WRITE_ACTION_TYPES,
        ).fetchone()
        if invalid is not None:
            raise SchemaCompatibilityError(
                f"desktop primary database at {db_path} contains invalid current "
                f"write authority for thread {invalid[0]!r}. {_REMEDY}"
            )
        incoherent = conn.execute(
            """SELECT t.id FROM threads AS t
               LEFT JOIN control_actions AS a
                 ON a.thread_id = t.id
                AND a.dispatch_id = t.writer_action_receipt_id
                AND a.action_type = t.writer_action_type
               WHERE a.id IS NULL
               LIMIT 1"""
        ).fetchone()
        if incoherent is not None:
            raise SchemaCompatibilityError(
                f"desktop primary database at {db_path} has no matching action "
                f"receipt for thread {incoherent[0]!r}. {_REMEDY}"
            )
    finally:
        conn.close()


def _validate_primary_schema(database_url: str) -> None:
    """Validate the primary database sits exactly at the package migration head."""
    db_path = _sqlite_path_from_url(database_url)
    head = supported_migration_head(database_url)
    try:
        current = _read_alembic_version(db_path)
    except sqlite3.Error as exc:
        raise SchemaCompatibilityError(
            f"desktop primary database at {db_path} is unreadable or corrupt; "
            f"expected packaged Alembic head {head}. {_REMEDY}"
        ) from exc

    if current is None:
        raise SchemaCompatibilityError(
            f"desktop primary database at {db_path} has no Alembic revision "
            f"(expected head {head}); the store is empty or has never been "
            f"migrated. {_REMEDY}"
        )
    if current == head:
        try:
            _validate_write_authority(db_path)
        except sqlite3.Error as exc:
            raise SchemaCompatibilityError(
                f"desktop primary database at {db_path} has unreadable current "
                f"write-authority state. {_REMEDY}"
            ) from exc
        return
    if current in _known_revisions(database_url):
        raise SchemaCompatibilityError(
            f"desktop primary database at {db_path} is at Alembic revision "
            f"{current}, behind the package head {head}. {_REMEDY}"
        )
    raise SchemaCompatibilityError(
        f"desktop primary database at {db_path} is at Alembic revision {current}, "
        f"which this package's migration graph (head {head}) does not recognise; "
        f"the store was written by a newer or foreign generation. {_REMEDY}"
    )


def _validate_checkpoint_schema(checkpoint_path: Path) -> None:
    """Validate the checkpointer schema and SDD state are already present."""
    try:
        connection = open_checkpoint_read_only(checkpoint_path)
        try:
            validate_checkpoint_schema_connection(connection)
            pending = count_pending_sdd_backfill_connection(connection)
        finally:
            connection.close()
    except (
        CheckpointSchemaError,
        CheckpointStateMigrationError,
        sqlite3.Error,
    ) as exc:
        raise SchemaCompatibilityError(
            f"desktop checkpoint database at {checkpoint_path} does not carry "
            f"compatible semantic schema version {CHECKPOINT_SCHEMA_VERSION}: "
            f"{exc}. {_REMEDY}"
        ) from exc
    if pending:
        raise SchemaCompatibilityError(
            f"desktop checkpoint database at {checkpoint_path} has {pending} "
            f"checkpoint row(s) missing SDD state fields. {_REMEDY}"
        )


async def validate_desktop_schema(*, database_url: str, checkpoint_path: Path) -> None:
    """Validate seated desktop stores are schema-compatible without mutating them.

    Confirms three facts and mutates nothing:

    - the primary database sits exactly at the package's Alembic migration head,
    - the checkpointer schema has the exact supported semantic identity, and
    - the SDD state fields are already backfilled.

    Args:
        database_url: The primary database's SQLite SQLAlchemy URL.
        checkpoint_path: On-disk path to the SQLite checkpoint database.

    Raises:
        SchemaCompatibilityError: If any store is missing, stale, unrecognised,
            or incoherent. The message names the store and the staged-migration
            remedy.
    """
    await asyncio.to_thread(_validate_primary_schema, database_url)
    await asyncio.to_thread(_validate_checkpoint_schema, checkpoint_path)
