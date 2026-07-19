"""Non-mutating schema-compatibility validation for the desktop profile.

Ordinary desktop gateway boot must perform no schema mutation: no Alembic
upgrade, no checkpointer table creation, and no state-driven-development (SDD)
backfill. Instead it validates that the seated stores are already compatible
with the running package and fails loud with an actionable remedy when they are
not. The staged-generation migration entrypoint owns every mutation under a
one-time transaction descriptor; ordinary boot only reads.

This module is the single authority for that read-only validation. It compares
the primary database's recorded Alembic revision against the package's migration
script head, confirms the checkpointer schema exists, and confirms the SDD state
fields are already present. Every check is a plain synchronous SQLite read; no
connection ever issues a write.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from .migrate import build_migration_config
from .migrations import count_pending_sdd_backfill

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
    conn = sqlite3.connect(str(db_path))
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


def _validate_primary_schema(database_url: str) -> None:
    """Validate the primary database sits exactly at the package migration head."""
    db_path = _sqlite_path_from_url(database_url)
    head = supported_migration_head(database_url)
    current = _read_alembic_version(db_path)

    if current is None:
        raise SchemaCompatibilityError(
            f"desktop primary database at {db_path} has no Alembic revision "
            f"(expected head {head}); the store is empty or has never been "
            f"migrated. {_REMEDY}"
        )
    if current == head:
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


def _checkpoint_table_present(checkpoint_path: Path) -> bool:
    """Return whether the LangGraph ``checkpoints`` table exists."""
    if not checkpoint_path.is_file():
        return False
    conn = sqlite3.connect(str(checkpoint_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def _validate_checkpoint_schema(checkpoint_path: Path) -> None:
    """Validate the checkpointer schema and SDD state are already present."""
    if not _checkpoint_table_present(checkpoint_path):
        raise SchemaCompatibilityError(
            f"desktop checkpoint database at {checkpoint_path} has no checkpointer "
            f"schema; the store is empty or has never been initialised. {_REMEDY}"
        )
    pending = count_pending_sdd_backfill(checkpoint_path)
    if pending:
        raise SchemaCompatibilityError(
            f"desktop checkpoint database at {checkpoint_path} has {pending} "
            f"checkpoint row(s) missing SDD state fields. {_REMEDY}"
        )


async def validate_desktop_schema(*, database_url: str, checkpoint_path: Path) -> None:
    """Validate seated desktop stores are schema-compatible without mutating them.

    Confirms three facts and mutates nothing:

    - the primary database sits exactly at the package's Alembic migration head,
    - the checkpointer schema is present, and
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
