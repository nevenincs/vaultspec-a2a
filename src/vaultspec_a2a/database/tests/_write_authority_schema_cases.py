"""Adversarial real-SQLite authority-schema cases."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Literal

from ..write_authority_schema import WRITE_AUTHORITY_CHECKS

if TYPE_CHECKING:
    from pathlib import Path


CheckTextCarrier = Literal["block-comment", "line-comment", "string-literal"]


def hide_authority_checks_in_non_code(path: Path, carrier: CheckTextCarrier) -> None:
    """Replace real authority checks while retaining their text outside SQL code."""
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'threads'"
        ).fetchone()
        assert row is not None
        forged = str(row[0])
        for index, (name, predicate) in enumerate(WRITE_AUTHORITY_CHECKS.items()):
            original = f"CONSTRAINT {name} CHECK ({predicate})"
            replacement = f"CONSTRAINT forged_authority_{index} CHECK (1)"
            if carrier == "block-comment":
                replacement += f" /* {original} */"
            elif carrier == "line-comment":
                replacement += f" -- {original}\n"
            else:
                literal = original.replace("'", "''")
                replacement = (
                    f"CONSTRAINT forged_authority_{index} "
                    f"CHECK ('{literal}' IS NOT NULL)"
                )
            assert original in forged
            forged = forged.replace(original, replacement, 1)
        assert forged != row[0]
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_master SET sql = ? "
            "WHERE type = 'table' AND name = 'threads'",
            (forged,),
        )
        connection.execute("PRAGMA writable_schema = OFF")
        connection.commit()


def replace_authority_checks_with_true(path: Path) -> None:
    """Keep every required CHECK name while replacing its predicate with true."""
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'threads'"
        ).fetchone()
        assert row is not None
        forged = str(row[0])
        for predicate in WRITE_AUTHORITY_CHECKS.values():
            forged = forged.replace(predicate, "1")
        assert forged != row[0]
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_master SET sql = ? "
            "WHERE type = 'table' AND name = 'threads'",
            (forged,),
        )
        connection.execute("PRAGMA writable_schema = OFF")
        connection.commit()


def point_receipt_index_at_thread_id(path: Path) -> None:
    """Keep the required unique index name while changing its indexed column."""
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX ux_threads_writer_action_receipt_id")
        connection.execute(
            "CREATE UNIQUE INDEX ux_threads_writer_action_receipt_id ON threads (id)"
        )
        connection.commit()
