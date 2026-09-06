"""Current-only migration proofs for durable thread write authority."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ...thread.enums import ControlActionType
from ..migrate import run_migrations
from ..models import RunWriteAuthority
from ..permission_repository import create_control_action
from ..thread_repository import create_thread
from ._write_authority_schema_cases import (
    point_receipt_index_at_thread_id,
    replace_authority_checks_with_true,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_ALEMBIC_INI = Path(__file__).resolve().parents[4] / "alembic.ini"


def _config(path: Path) -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    return config


def _version(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return str(row[0])


def _schema_dump(path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()


def test_empty_store_installs_required_authority_without_defaults(
    runtime_dir: Path,
) -> None:
    db = runtime_dir / "empty-0017.db"
    config = _config(db)
    command.upgrade(config, "0016")
    command.upgrade(config, "0017")

    with sqlite3.connect(db) as connection:
        columns = {
            str(row[1]): (str(row[2]), int(row[3]), row[4])
            for row in connection.execute("PRAGMA table_info(threads)")
        }
        indexes = {
            str(row[1]): int(row[2])
            for row in connection.execute("PRAGMA index_list(threads)")
        }

    assert columns["run_revision"] == ("INTEGER", 1, None)
    assert columns["writer_generation"] == ("INTEGER", 1, None)
    assert columns["writer_action_type"] == ("VARCHAR(32)", 1, None)
    assert columns["writer_action_receipt_id"] == ("VARCHAR(64)", 1, None)
    assert indexes["ux_threads_writer_action_receipt_id"] == 1
    assert _version(db) == "0017"


def test_database_enforces_authority_constraints(runtime_dir: Path) -> None:
    db = runtime_dir / "authority-constraints.db"
    config = _config(db)
    command.upgrade(config, "0017")
    with sqlite3.connect(db) as connection:
        statement = """INSERT INTO threads (
               id, created_at, updated_at, status, run_revision,
               writer_generation, writer_action_type,
               writer_action_receipt_id
           ) VALUES (
               ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'running',
               ?, ?, ?, ?
           )"""
        invalid_values = [
            (-1, 1, "ingest", "receipt-negative"),
            (0, 0, "ingest", "receipt-generation"),
            (0, 1, "unknown", "receipt-action"),
            (0, 1, "ingest", " "),
            (0, 1, "ingest", "r" * 65),
        ]
        for index, values in enumerate(invalid_values):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement, (f"invalid-{index}", *values))
        connection.execute(statement, ("one", 0, 1, "ingest", "same-receipt"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement, ("two", 0, 1, "ingest", "same-receipt"))


def test_populated_precurrent_store_is_refused_without_partial_schema(
    runtime_dir: Path,
) -> None:
    db = runtime_dir / "populated-0016.db"
    config = _config(db)
    command.upgrade(config, "0016")
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO threads (id, created_at, updated_at, status) "
            "VALUES ('existing', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'running')"
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="populated store"):
        command.upgrade(config, "0017")

    with sqlite3.connect(db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
        row = connection.execute("SELECT id FROM threads").fetchone()
    assert _version(db) == "0016"
    assert "run_revision" not in columns
    assert row == ("existing",)


@pytest.mark.asyncio
async def test_runtime_runner_refuses_older_populated_store_before_any_revision(
    runtime_dir: Path,
) -> None:
    db = runtime_dir / "populated-0007.db"
    config = _config(db)
    await asyncio.to_thread(command.upgrade, config, "0007")
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO threads (id, created_at, updated_at, status) "
            "VALUES ('older', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'running')"
        )
        connection.commit()
        before_schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
        before_rows = connection.execute("SELECT * FROM threads").fetchall()

    with pytest.raises(CommandError, match="complete current write authority"):
        await run_migrations(f"sqlite+aiosqlite:///{db}")

    with sqlite3.connect(db) as connection:
        after_schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
        after_rows = connection.execute("SELECT * FROM threads").fetchall()
    assert _version(db) == "0007"
    assert after_schema == before_schema
    assert after_rows == before_rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_name", "forge_schema"),
    [
        ("permissive-checks", replace_authority_checks_with_true),
        ("wrong-index-column", point_receipt_index_at_thread_id),
    ],
)
async def test_runtime_runner_refuses_forged_empty_current_schema(
    runtime_dir: Path,
    case_name: str,
    forge_schema: Callable[[Path], None],
) -> None:
    db = runtime_dir / f"forged-{case_name}.db"
    await run_migrations(f"sqlite+aiosqlite:///{db}")
    forge_schema(db)
    before = _schema_dump(db)

    with pytest.raises(CommandError, match="complete current write authority"):
        await run_migrations(f"sqlite+aiosqlite:///{db}")

    assert _schema_dump(db) == before


@pytest.mark.asyncio
async def test_runtime_runner_accepts_populated_valid_current_schema(
    runtime_dir: Path,
) -> None:
    db = runtime_dir / "valid-current.db"
    url = f"sqlite+aiosqlite:///{db}"
    await run_migrations(url)
    engine = create_async_engine(url)
    receipt = "valid-current-receipt"
    async with AsyncSession(engine) as session:
        await create_thread(
            session,
            write_authority=RunWriteAuthority(
                run_revision=0,
                writer_generation=1,
                action_type=ControlActionType.INGEST,
                action_receipt_id=receipt,
            ),
            thread_id="valid-current",
        )
        await create_control_action(
            session,
            thread_id="valid-current",
            action_type=ControlActionType.INGEST,
            idempotency_key="valid-current-ingest",
            dispatch_id=receipt,
        )
        await session.commit()
    await engine.dispose()

    await run_migrations(url)
    assert _version(db) == "0017"


def test_populated_current_store_cannot_erase_authority(runtime_dir: Path) -> None:
    db = runtime_dir / "populated-0017.db"
    config = _config(db)
    command.upgrade(config, "0017")
    with sqlite3.connect(db) as connection:
        connection.execute(
            """INSERT INTO threads (
                   id, created_at, updated_at, status, run_revision,
                   writer_generation, writer_action_type,
                   writer_action_receipt_id
               ) VALUES (
                   'current', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'running',
                   0, 1, 'ingest', 'receipt-current'
               )"""
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="populated store"):
        command.downgrade(config, "0016")

    assert _version(db) == "0017"


def test_empty_current_store_can_downgrade(runtime_dir: Path) -> None:
    db = runtime_dir / "empty-downgrade.db"
    config = _config(db)
    command.upgrade(config, "0017")
    command.downgrade(config, "0016")
    assert _version(db) == "0016"
