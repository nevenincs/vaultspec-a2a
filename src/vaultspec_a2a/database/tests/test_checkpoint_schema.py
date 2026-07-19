"""Real-store tests for the checkpoint semantic-schema authority."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

import pytest

from ..checkpoint_schema import (
    CHECKPOINT_SCHEMA_DIGEST,
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointSchemaError,
    install_checkpoint_schema_identity,
    validate_checkpoint_schema_identity,
)

if TYPE_CHECKING:
    from pathlib import Path


async def _create_langgraph_store(path: Path) -> None:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        await checkpointer.setup()


def _schema_dump(path: Path) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_exact_unstamped_store_is_rejected_then_installed(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoints.db"
    await _create_langgraph_store(checkpoint)

    with pytest.raises(CheckpointSchemaError, match="object closure"):
        validate_checkpoint_schema_identity(checkpoint)

    await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)
    validate_checkpoint_schema_identity(checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        identity = connection.execute(
            "SELECT schema_version, schema_digest "
            "FROM vaultspec_checkpoint_schema WHERE singleton = 1"
        ).fetchone()
    finally:
        connection.close()
    assert identity == (CHECKPOINT_SCHEMA_VERSION, CHECKPOINT_SCHEMA_DIGEST)


@pytest.mark.asyncio
async def test_validation_is_read_only_and_ignores_sqlite_ddl_cookie(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoints.db"
    await _create_langgraph_store(checkpoint)
    await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        connection.execute("PRAGMA schema_version = 999")
        connection.commit()
    finally:
        connection.close()
    before = _schema_dump(checkpoint)

    validate_checkpoint_schema_identity(checkpoint)

    assert _schema_dump(checkpoint) == before


@pytest.mark.asyncio
async def test_install_refuses_foreign_version_without_downgrade(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoints.db"
    await _create_langgraph_store(checkpoint)
    await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        connection.execute(
            "UPDATE vaultspec_checkpoint_schema SET schema_version = '9.0.0'"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CheckpointSchemaError, match="incompatible"):
        await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        version = connection.execute(
            "SELECT schema_version FROM vaultspec_checkpoint_schema"
        ).fetchone()
    finally:
        connection.close()
    assert version == ("9.0.0",)


@pytest.mark.asyncio
async def test_install_refuses_structural_drift_before_stamping(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoints.db"
    await _create_langgraph_store(checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        connection.execute("ALTER TABLE writes ADD COLUMN foreign_value TEXT")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CheckpointSchemaError, match="object closure"):
        await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        marker = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'vaultspec_checkpoint_schema'"
        ).fetchone()
    finally:
        connection.close()
    assert marker is None


@pytest.mark.parametrize(
    "foreign_ddl",
    [
        "CREATE INDEX foreign_writes_channel ON writes(channel)",
        (
            "CREATE TRIGGER foreign_checkpoint_trigger AFTER INSERT ON checkpoints "
            "BEGIN DELETE FROM writes; END"
        ),
    ],
)
@pytest.mark.asyncio
async def test_identity_rejects_foreign_indexes_and_triggers(
    tmp_path: Path, foreign_ddl: str
) -> None:
    checkpoint = tmp_path / "checkpoints.db"
    await _create_langgraph_store(checkpoint)
    await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        connection.execute(foreign_ddl)
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CheckpointSchemaError, match="object closure"):
        validate_checkpoint_schema_identity(checkpoint)
