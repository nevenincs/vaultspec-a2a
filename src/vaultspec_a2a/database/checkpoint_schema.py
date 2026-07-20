"""Versioned structural authority for the desktop checkpoint database.

LangGraph creates SQLite tables but publishes no durable schema revision inside
the store. The desktop updater needs that identity before it can decide whether
a seated checkpoint database belongs to the generation it is about to run.
Version ``1.0.0`` therefore binds the complete normalized SQLite DDL closure,
column and primary-key facts, and a durable project-owned marker.

The staged migration entrypoint may install the marker only after real
``AsyncSqliteSaver.setup()`` and state migration succeed. Ordinary boot opens
the store read-only and validates through the already-open database authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CHECKPOINT_SCHEMA_DIGEST",
    "CHECKPOINT_SCHEMA_VERSION",
    "CheckpointSchemaError",
    "install_checkpoint_schema_identity",
    "open_checkpoint_read_only",
    "validate_checkpoint_schema_connection",
    "validate_checkpoint_schema_identity",
]

CHECKPOINT_SCHEMA_VERSION: Final = "1.0.0"
"""Semantic version of the exact checkpoint-store structure below."""

_MARKER_TABLE: Final = "vaultspec_checkpoint_schema"
_CHECKPOINTS_SQL: Final = """
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BLOB,
    metadata BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
)
""".strip()
_WRITES_SQL: Final = """
CREATE TABLE writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
)
""".strip()
_MARKER_SQL: Final = f"""
CREATE TABLE {_MARKER_TABLE} (
    singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    schema_digest TEXT NOT NULL
)
""".strip()

type ColumnSignature = tuple[str, str, bool, str | None, int]
type TableSignature = tuple[ColumnSignature, ...]
type ObjectSignature = tuple[str, str, str | None]

# Column order is significant. Each tuple is
# (name, declared type, not-null, default SQL, primary-key position).
_LANGGRAPH_TABLES: Final[dict[str, TableSignature]] = {
    "checkpoints": (
        ("thread_id", "TEXT", True, None, 1),
        ("checkpoint_ns", "TEXT", True, "''", 2),
        ("checkpoint_id", "TEXT", True, None, 3),
        ("parent_checkpoint_id", "TEXT", False, None, 0),
        ("type", "TEXT", False, None, 0),
        ("checkpoint", "BLOB", False, None, 0),
        ("metadata", "BLOB", False, None, 0),
    ),
    "writes": (
        ("thread_id", "TEXT", True, None, 1),
        ("checkpoint_ns", "TEXT", True, "''", 2),
        ("checkpoint_id", "TEXT", True, None, 3),
        ("task_id", "TEXT", True, None, 4),
        ("idx", "INTEGER", True, None, 5),
        ("channel", "TEXT", True, None, 0),
        ("type", "TEXT", False, None, 0),
        ("value", "BLOB", False, None, 0),
    ),
}
_MARKER_SIGNATURE: Final[TableSignature] = (
    ("singleton", "INTEGER", True, None, 1),
    ("schema_version", "TEXT", True, None, 0),
    ("schema_digest", "TEXT", True, None, 0),
)
_EXPECTED_TABLES: Final[dict[str, TableSignature]] = {
    **_LANGGRAPH_TABLES,
    _MARKER_TABLE: _MARKER_SIGNATURE,
}


def _normalize_sql(sql: str) -> str:
    """Normalize irrelevant whitespace and keyword case, preserving semantics."""
    return " ".join(sql.split()).lower()


_LANGGRAPH_OBJECTS: Final[dict[tuple[str, str], ObjectSignature]] = {
    ("table", "checkpoints"): (
        "table",
        "checkpoints",
        _normalize_sql(_CHECKPOINTS_SQL),
    ),
    ("table", "writes"): ("table", "writes", _normalize_sql(_WRITES_SQL)),
    ("index", "sqlite_autoindex_checkpoints_1"): (
        "index",
        "checkpoints",
        None,
    ),
    ("index", "sqlite_autoindex_writes_1"): ("index", "writes", None),
}
_EXPECTED_OBJECTS: Final[dict[tuple[str, str], ObjectSignature]] = {
    **_LANGGRAPH_OBJECTS,
    ("table", _MARKER_TABLE): (
        "table",
        _MARKER_TABLE,
        _normalize_sql(_MARKER_SQL),
    ),
}


def _schema_digest() -> str:
    canonical = json.dumps(
        {
            "objects": [
                [object_type, name, *signature]
                for (object_type, name), signature in sorted(_EXPECTED_OBJECTS.items())
            ],
            "tables": {
                name: list(columns)
                for name, columns in sorted(_EXPECTED_TABLES.items())
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


CHECKPOINT_SCHEMA_DIGEST: Final = _schema_digest()
"""SHA-256 identity of the complete structure governed by the version."""


class CheckpointSchemaError(RuntimeError):
    """The checkpoint database lacks or contradicts its schema identity."""


def open_checkpoint_read_only(checkpoint_path: Path) -> sqlite3.Connection:
    """Open an existing checkpoint database with SQLite-enforced read-only mode."""
    if not checkpoint_path.is_file():
        raise CheckpointSchemaError(
            f"checkpoint database does not exist at {checkpoint_path}"
        )
    uri = f"{checkpoint_path.resolve().as_uri()}?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise CheckpointSchemaError(
            f"checkpoint database is not readable at {checkpoint_path}"
        ) from exc


def _object_signatures(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], ObjectSignature]:
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' OR name LIKE 'sqlite_autoindex_%'"
    ).fetchall()
    return {
        (str(object_type), str(name)): (
            str(object_type),
            str(table_name),
            None if sql is None else _normalize_sql(str(sql)),
        )
        for object_type, name, table_name, sql in rows
    }


def _table_signature(connection: sqlite3.Connection, table_name: str) -> TableSignature:
    quoted = '"' + table_name.replace('"', '""') + '"'
    rows = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    return tuple(
        (
            str(name),
            str(declared_type).upper(),
            bool(not_null),
            None if default_sql is None else str(default_sql),
            int(primary_key_position),
        )
        for _, name, declared_type, not_null, default_sql, primary_key_position in rows
    )


def _assert_exact_structure(
    connection: sqlite3.Connection,
    expected_tables: dict[str, TableSignature],
    expected_objects: dict[tuple[str, str], ObjectSignature],
) -> None:
    actual_objects = _object_signatures(connection)
    if actual_objects != expected_objects:
        missing = sorted(set(expected_objects) - set(actual_objects))
        unexpected = sorted(set(actual_objects) - set(expected_objects))
        changed = sorted(
            key
            for key in set(actual_objects) & set(expected_objects)
            if actual_objects[key] != expected_objects[key]
        )
        raise CheckpointSchemaError(
            "checkpoint schema object closure differs from version "
            f"{CHECKPOINT_SCHEMA_VERSION}: missing={missing}, "
            f"unexpected={unexpected}, changed={changed}"
        )
    for table_name, expected_signature in expected_tables.items():
        if _table_signature(connection, table_name) != expected_signature:
            raise CheckpointSchemaError(
                f"checkpoint table {table_name!r} does not match semantic schema "
                f"version {CHECKPOINT_SCHEMA_VERSION}"
            )


def install_checkpoint_schema_identity(checkpoint_path: Path) -> None:
    """Install the identity over an exact unversioned LangGraph schema.

    An existing identity is validated, never overwritten. This prevents a
    staged generation from silently relabelling a newer or foreign store.
    """
    connection = sqlite3.connect(str(checkpoint_path))
    try:
        if ("table", _MARKER_TABLE) in _object_signatures(connection):
            validate_checkpoint_schema_connection(connection)
            return
        _assert_exact_structure(connection, _LANGGRAPH_TABLES, _LANGGRAPH_OBJECTS)
        connection.execute(_MARKER_SQL)
        connection.execute(
            f"INSERT INTO {_MARKER_TABLE} "
            "(singleton, schema_version, schema_digest) VALUES (1, ?, ?)",
            (CHECKPOINT_SCHEMA_VERSION, CHECKPOINT_SCHEMA_DIGEST),
        )
        connection.commit()
        validate_checkpoint_schema_connection(connection)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def validate_checkpoint_schema_connection(connection: sqlite3.Connection) -> None:
    """Validate identity through an already-open SQLite database authority."""
    _assert_exact_structure(connection, _EXPECTED_TABLES, _EXPECTED_OBJECTS)
    rows = connection.execute(
        f"SELECT singleton, schema_version, schema_digest FROM {_MARKER_TABLE}"
    ).fetchall()
    expected = [(1, CHECKPOINT_SCHEMA_VERSION, CHECKPOINT_SCHEMA_DIGEST)]
    if rows != expected:
        raise CheckpointSchemaError(
            "checkpoint schema identity is missing, malformed, or incompatible; "
            f"expected semantic version {CHECKPOINT_SCHEMA_VERSION} and digest "
            f"{CHECKPOINT_SCHEMA_DIGEST}"
        )


def validate_checkpoint_schema_identity(checkpoint_path: Path) -> None:
    """Read and validate the exact checkpoint schema without mutating the store."""
    connection = open_checkpoint_read_only(checkpoint_path)
    try:
        validate_checkpoint_schema_connection(connection)
    except sqlite3.Error as exc:
        raise CheckpointSchemaError(
            f"checkpoint schema identity is unreadable at {checkpoint_path}"
        ) from exc
    finally:
        connection.close()
