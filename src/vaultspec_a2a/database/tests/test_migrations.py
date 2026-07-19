"""Tests for Alembic migration framework.

Verifies:
1. Upgrade head creates all 4 app-owned tables
2. Downgrade base removes all app-owned tables
3. LangGraph checkpoint tables are excluded from migrations
4. run_migrations() programmatic API works
5. (Postgres) upgrade/downgrade/column/data-migration on a real Postgres instance
"""

import asyncio
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from .. import migrations as _migrations_package
from ..migrate import (
    build_migration_config,
    migration_script_location,
    run_migrations,
)

_APP_TABLES = {
    "threads",
    "artifacts",
    "permission_logs",
    "cost_tracking",
    "thread_execution_state",
    "task_queue_entries",
}
_LANGGRAPH_TABLES = {"checkpoints", "writes"}
_ALEMBIC_INI = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "alembic.ini"
)


def _make_config(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def _get_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()


class TestAlembicUpgradeDowngrade:
    def test_upgrade_head_creates_all_app_tables(self, runtime_dir: Path) -> None:
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")

        tables = _get_tables(db)
        assert tables >= _APP_TABLES
        # alembic_version is also expected
        assert "alembic_version" in tables

    def test_downgrade_base_removes_all_app_tables(self, runtime_dir: Path) -> None:
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

        tables = _get_tables(db)
        # Only alembic_version should remain (Alembic's own tracking table)
        assert not (_APP_TABLES & tables)

    def test_langgraph_tables_excluded(self, runtime_dir: Path) -> None:
        """Pre-create LangGraph tables, run upgrade, verify they are untouched."""
        db = runtime_dir / "test.db"
        # Pre-create LangGraph tables
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT, data BLOB)"
        )
        conn.execute(
            "CREATE TABLE writes (thread_id TEXT, checkpoint_id TEXT, data BLOB)"
        )
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'c1', X'DEADBEEF')")
        conn.commit()
        conn.close()

        # Run migrations
        cfg = _make_config(db)
        command.upgrade(cfg, "head")

        # Verify LangGraph tables still exist with data intact
        tables = _get_tables(db)
        assert tables >= _LANGGRAPH_TABLES
        assert tables >= _APP_TABLES

        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT data FROM checkpoints WHERE thread_id='t1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == b"\xde\xad\xbe\xef"

    def test_stamp_head_on_existing_db(self, runtime_dir: Path) -> None:
        """Stamp an existing DB without running DDL."""
        db = runtime_dir / "test.db"
        # Create a DB with the threads table already present (simulating existing)
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        cfg = _make_config(db)
        command.stamp(cfg, "head")

        # Verify stamp wrote alembic_version
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "0007"

    def test_upgrade_head_rewrites_legacy_created_status(
        self, runtime_dir: Path
    ) -> None:
        """Upgrading head should normalize legacy created rows to submitted."""
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0002")

        conn = sqlite3.connect(str(db))
        conn.execute(
            """
            INSERT INTO threads (id, created_at, updated_at, status)
            VALUES (?, ?, ?, ?)
            """,
            (
                "legacy-created-thread",
                "2026-03-09 00:00:00",
                "2026-03-09 00:00:00",
                "created",
            ),
        )
        conn.commit()
        conn.close()

        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT status FROM threads WHERE id = ?",
            ("legacy-created-thread",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "submitted"

    def test_upgrade_head_adds_plan_approval_columns(self, runtime_dir: Path) -> None:
        """Upgrading head should add durable plan-approval columns to threads."""
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db))
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(threads)").fetchall()
        }
        conn.close()

        assert {
            "approval_status",
            "approval_request_id",
            "approval_reason",
            "approval_response_action_id",
            "approval_updated_at",
        } <= columns

    def test_upgrade_head_adds_thread_execution_state_table(
        self,
        runtime_dir: Path,
    ) -> None:
        """Upgrading head should add the latest execution-state projection table."""
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db))
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(thread_execution_state)"
            ).fetchall()
        }
        conn.close()

        assert {
            "thread_id",
            "checkpoint_id",
            "parent_checkpoint_id",
            "snapshot_created_at",
            "recorded_at",
            "recovery_epoch",
            "task_count",
            "interrupt_count",
            "next_nodes_json",
            "interrupt_types_json",
            "tasks_json",
            "degraded_reasons_json",
        } <= columns


class TestPackageResourceResolution:
    """The runtime migration path resolves scripts from installed package data."""

    def test_script_location_is_the_migrations_package(self) -> None:
        """``migration_script_location`` resolves the packaged scripts directory."""
        expected = Path(next(iter(_migrations_package.__path__))).resolve()
        location = migration_script_location().resolve()

        assert location == expected
        assert location.is_dir()
        assert (location / "env.py").is_file()
        assert (location / "versions").is_dir()

    def test_runtime_config_consults_no_repo_root_file(self) -> None:
        """The runtime config attaches no ``alembic.ini`` and binds package scripts."""
        cfg = build_migration_config("sqlite+aiosqlite:///runtime.db")

        # A programmatic config reads no ini file: env.py's fileConfig branch is
        # skipped and no repo-root alembic.ini is required at runtime.
        assert cfg.config_file_name is None
        script_location = cfg.get_main_option("script_location")
        assert script_location is not None
        assert Path(script_location).resolve() == migration_script_location().resolve()
        assert cfg.get_main_option("sqlalchemy.url") == (
            "sqlite+aiosqlite:///runtime.db"
        )

    @pytest.mark.parametrize(
        "database_url",
        [
            "sqlite+aiosqlite:///C:/Vault%20Spec/runtime%25.db",
            (
                "postgresql+asyncpg://operator:p%40ss@localhost/vaultspec"
                "?application_name=desktop%25capsule"
            ),
        ],
    )
    def test_runtime_config_preserves_percent_encoded_urls(
        self, database_url: str
    ) -> None:
        """Alembic interpolation preserves Windows and PostgreSQL URL escapes."""
        cfg = build_migration_config(database_url)

        assert cfg.get_main_option("sqlalchemy.url") == database_url
        assert cfg.get_main_option("script_location") == str(
            migration_script_location()
        )


class TestRunMigrations:
    @pytest.mark.asyncio
    async def test_run_migrations_programmatic(self, runtime_dir: Path) -> None:
        db = runtime_dir / "test.db"
        url = f"sqlite+aiosqlite:///{db}"
        await run_migrations(url)

        tables = _get_tables(db)
        assert tables >= _APP_TABLES

    @pytest.mark.asyncio
    async def test_run_migrations_upgrades_to_head_from_package_scripts(
        self, runtime_dir: Path
    ) -> None:
        """A real upgrade applied through the package-resolved scripts reaches head."""
        db = runtime_dir / "package_resolved.db"
        url = f"sqlite+aiosqlite:///{db}"
        await run_migrations(url)

        conn = sqlite3.connect(str(db))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()

        assert version is not None
        assert version[0] == "0007"

    @pytest.mark.asyncio
    async def test_run_migrations_with_percent_directory_reaches_head(
        self, runtime_dir: Path
    ) -> None:
        """A real SQLite migration accepts a literal percent in its directory."""
        percent_dir = runtime_dir / "capsule%runtime"
        percent_dir.mkdir()
        db = percent_dir / "vaultspec.db"

        await run_migrations(f"sqlite+aiosqlite:///{db}")

        conn = sqlite3.connect(str(db))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()

        assert version is not None
        assert version[0] == "0007"

    @pytest.mark.asyncio
    async def test_concurrent_run_migrations_upgrades_both_databases(
        self, runtime_dir: Path
    ) -> None:
        """Concurrent callers cannot cross-wire Alembic's global command context."""
        databases = [runtime_dir / "first.db", runtime_dir / "second.db"]

        await asyncio.gather(
            *(
                run_migrations(f"sqlite+aiosqlite:///{database}")
                for database in databases
            )
        )

        for database in databases:
            conn = sqlite3.connect(str(database))
            try:
                version = conn.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()
            finally:
                conn.close()

            assert version is not None
            assert version[0] == "0007"
            assert _get_tables(database) >= _APP_TABLES
