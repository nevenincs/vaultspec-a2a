"""Real-store tests for non-mutating desktop schema-compatibility validation.

Every test drives a real SQLite file through the production migration runner and
the real LangGraph SQLite checkpointer. No mock, monkeypatch, stub, skip, or
expected failure is used: compatibility is proved by reading real
``alembic_version`` rows and real ``sqlite_master`` schema dumps before and after
validation, and incompatibility is proved by validation raising against genuinely
empty, stale, or incoherent stores.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from ..compatibility import (
    SchemaCompatibilityError,
    supported_migration_head,
    validate_desktop_schema,
)
from ..migrate import run_migrations
from ..session import init_db

_ALEMBIC_INI = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "alembic.ini"
)


def _url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _schema_dump(db_path: Path) -> list[tuple[object, ...]]:
    """Return the store's full object schema (tables, indexes, triggers)."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    finally:
        conn.close()


async def _make_checkpoint_store(path: Path) -> None:
    """Create a real LangGraph SQLite checkpointer schema at ``path``."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        await checkpointer.setup()


async def _make_compatible_stores(runtime_dir: Path) -> tuple[Path, Path]:
    """Build a fully migrated primary DB and an initialised checkpoint DB."""
    primary = runtime_dir / "vaultspec.db"
    checkpoint = runtime_dir / "checkpoints.db"
    await run_migrations(_url(primary))
    await _make_checkpoint_store(checkpoint)
    return primary, checkpoint


class TestCompatibleStoresValidateWithoutMutation:
    @pytest.mark.asyncio
    async def test_head_store_validates_and_mutates_nothing(
        self, runtime_dir: Path
    ) -> None:
        """A pre-migrated store passes validation and its schema is untouched."""
        primary, checkpoint = await _make_compatible_stores(runtime_dir)

        primary_before = _schema_dump(primary)
        checkpoint_before = _schema_dump(checkpoint)
        version_before = (
            sqlite3.connect(str(primary))
            .execute("SELECT version_num FROM alembic_version")
            .fetchone()
        )

        await validate_desktop_schema(
            database_url=_url(primary), checkpoint_path=checkpoint
        )

        assert _schema_dump(primary) == primary_before
        assert _schema_dump(checkpoint) == checkpoint_before
        version_after = (
            sqlite3.connect(str(primary))
            .execute("SELECT version_num FROM alembic_version")
            .fetchone()
        )
        assert version_after == version_before
        assert version_after is not None
        assert version_after[0] == supported_migration_head(_url(primary))


class TestIncompatibleStoresFailLoud:
    @pytest.mark.asyncio
    async def test_empty_primary_store_fails_loud(self, runtime_dir: Path) -> None:
        """A never-migrated primary database is rejected with the remedy."""
        primary = runtime_dir / "vaultspec.db"
        checkpoint = runtime_dir / "checkpoints.db"
        primary.touch()
        await _make_checkpoint_store(checkpoint)

        with pytest.raises(SchemaCompatibilityError, match="no Alembic revision"):
            await validate_desktop_schema(
                database_url=_url(primary), checkpoint_path=checkpoint
            )

    @pytest.mark.asyncio
    async def test_stale_primary_store_fails_loud(self, runtime_dir: Path) -> None:
        """A store behind the package head is rejected as behind, not migrated."""
        primary = runtime_dir / "vaultspec.db"
        checkpoint = runtime_dir / "checkpoints.db"
        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", _url(primary))
        # Alembic's env.py drives an async engine via asyncio.run, so the
        # synchronous command must run off the test's event loop.
        await asyncio.to_thread(command.upgrade, cfg, "0002")
        await _make_checkpoint_store(checkpoint)

        with pytest.raises(SchemaCompatibilityError, match="behind"):
            await validate_desktop_schema(
                database_url=_url(primary), checkpoint_path=checkpoint
            )

    @pytest.mark.asyncio
    async def test_unrecognised_primary_revision_fails_loud(
        self, runtime_dir: Path
    ) -> None:
        """A foreign/newer revision the package cannot resolve is rejected."""
        primary = runtime_dir / "vaultspec.db"
        checkpoint = runtime_dir / "checkpoints.db"
        await run_migrations(_url(primary))
        conn = sqlite3.connect(str(primary))
        try:
            conn.execute("UPDATE alembic_version SET version_num = '9999_future'")
            conn.commit()
        finally:
            conn.close()
        await _make_checkpoint_store(checkpoint)

        with pytest.raises(SchemaCompatibilityError, match="does not recognise"):
            await validate_desktop_schema(
                database_url=_url(primary), checkpoint_path=checkpoint
            )

    @pytest.mark.asyncio
    async def test_missing_checkpoint_schema_fails_loud(
        self, runtime_dir: Path
    ) -> None:
        """A migrated primary with no checkpointer schema is rejected."""
        primary = runtime_dir / "vaultspec.db"
        checkpoint = runtime_dir / "checkpoints.db"
        await run_migrations(_url(primary))

        with pytest.raises(SchemaCompatibilityError, match="no checkpointer schema"):
            await validate_desktop_schema(
                database_url=_url(primary), checkpoint_path=checkpoint
            )

    @pytest.mark.asyncio
    async def test_incoherent_sdd_state_fails_loud(self, runtime_dir: Path) -> None:
        """Checkpoint rows missing SDD state fields are rejected."""
        primary = runtime_dir / "vaultspec.db"
        checkpoint = runtime_dir / "checkpoints.db"
        await run_migrations(_url(primary))

        # A real checkpoints table carrying a channel_values row that predates the
        # SDD fields: the store exists but is not coherent for desktop boot.
        conn = sqlite3.connect(str(checkpoint))
        try:
            conn.execute(
                "CREATE TABLE checkpoints (rowid INTEGER, channel_values TEXT)"
            )
            conn.execute("INSERT INTO checkpoints VALUES (1, '{\"unrelated\": true}')")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(SchemaCompatibilityError, match="missing SDD state"):
            await validate_desktop_schema(
                database_url=_url(primary), checkpoint_path=checkpoint
            )


class TestInitDbMigrationGate:
    @pytest.mark.asyncio
    async def test_apply_migrations_false_leaves_store_unmigrated(
        self, runtime_dir: Path
    ) -> None:
        """Non-mutating init creates the engine but stamps no schema."""
        db = runtime_dir / "unarmed.db"
        try:
            await init_db(_url(db), apply_migrations=False)
        finally:
            from ..session import close_db

            await close_db()

        # No alembic_version table: the store carries no schema mutation.
        with pytest.raises(SchemaCompatibilityError, match="no Alembic revision"):
            await validate_desktop_schema(
                database_url=_url(db), checkpoint_path=runtime_dir / "absent.db"
            )

    @pytest.mark.asyncio
    async def test_apply_migrations_true_migrates_to_head(
        self, runtime_dir: Path
    ) -> None:
        """Ordinary (unarmed) init still migrates the store to head."""
        db = runtime_dir / "armed_off.db"
        try:
            await init_db(_url(db), apply_migrations=True)
        finally:
            from ..session import close_db

            await close_db()

        conn = sqlite3.connect(str(db))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()
        assert version is not None
        assert version[0] == supported_migration_head(_url(db))
