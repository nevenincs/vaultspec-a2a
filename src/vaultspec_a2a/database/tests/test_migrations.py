"""Tests for Alembic migration framework (ADR-029).

Verifies:
1. Upgrade head creates all 4 app-owned tables
2. Downgrade base removes all app-owned tables
3. LangGraph checkpoint tables are excluded from migrations
4. run_migrations() programmatic API works
5. (Postgres) upgrade/downgrade/column/data-migration on a real Postgres instance
"""

import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import psycopg.sql
import pytest
from alembic import command
from alembic.config import Config

from ..migrate import run_migrations
from .conftest import resolve_postgres_dsn

_APP_TABLES = {
    "threads",
    "artifacts",
    "permission_logs",
    "cost_tracking",
    "thread_execution_state",
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
        assert row[0] == "0005"

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


class TestRunMigrations:
    @pytest.mark.asyncio
    async def test_run_migrations_programmatic(self, runtime_dir: Path) -> None:
        db = runtime_dir / "test.db"
        url = f"sqlite+aiosqlite:///{db}"
        await run_migrations(url)

        tables = _get_tables(db)
        assert tables >= _APP_TABLES


# ---------------------------------------------------------------------------
# Postgres migration variants
# ---------------------------------------------------------------------------


def _maintenance_dsn(dsn: str) -> str:
    """Return a DSN targeting the 'postgres' maintenance DB on the same host."""
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path="/postgres"))


def _temp_dsn(dsn: str, dbname: str) -> str:
    """Return a DSN targeting a named database on the same host as ``dsn``."""
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path=f"/{dbname}"))


def _make_temp_db(base_dsn: str) -> tuple[str, str]:
    """Create a fresh temporary Postgres database.

    Returns ``(maintenance_dsn, temp_dbname)``.
    """
    maintenance = _maintenance_dsn(base_dsn)
    dbname = f"vaultspec_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(maintenance, autocommit=True) as conn:
        conn.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(dbname))
        )
    return maintenance, dbname


def _drop_temp_db(maintenance_dsn: str, dbname: str) -> None:
    """Terminate connections to ``dbname`` then drop it."""
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (dbname,),
        )
        conn.execute(
            psycopg.sql.SQL("DROP DATABASE IF EXISTS {}").format(
                psycopg.sql.Identifier(dbname)
            )
        )


def _get_postgres_tables(dsn: str) -> set[str]:
    """Return all user table names in the public schema."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ).fetchall()
    return {row[0] for row in rows}


def _make_postgres_config(dsn: str) -> Config:
    """Build an Alembic Config targeting a Postgres DSN via psycopg (sync)."""
    sa_url = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", sa_url)
    return cfg


@pytest.mark.requires_postgres
class TestAlembicUpgradeDowngradePostgres:
    """Mirror of TestAlembicUpgradeDowngrade running against a real Postgres instance.

    Each test creates a fresh temporary database for isolation and drops it
    on teardown.  The ``requires_postgres`` marker hard-fails the entire class
    when Postgres is unreachable (see conftest.py).
    """

    def _setup(self) -> tuple[str, str, str]:
        """Create temp DB; return (maintenance_dsn, dbname, temp_dsn)."""
        base_dsn = resolve_postgres_dsn()
        maintenance, dbname = _make_temp_db(base_dsn)
        temp = _temp_dsn(maintenance, dbname)
        return maintenance, dbname, temp

    def test_upgrade_head_creates_all_app_tables(self) -> None:
        maintenance, dbname, temp = self._setup()
        try:
            command.upgrade(_make_postgres_config(temp), "head")
            tables = _get_postgres_tables(temp)
            assert tables >= _APP_TABLES
            assert "alembic_version" in tables
        finally:
            _drop_temp_db(maintenance, dbname)

    def test_downgrade_base_removes_all_app_tables(self) -> None:
        maintenance, dbname, temp = self._setup()
        try:
            cfg = _make_postgres_config(temp)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "base")
            tables = _get_postgres_tables(temp)
            assert not (_APP_TABLES & tables)
        finally:
            _drop_temp_db(maintenance, dbname)

    def test_upgrade_head_adds_plan_approval_columns(self) -> None:
        maintenance, dbname, temp = self._setup()
        try:
            command.upgrade(_make_postgres_config(temp), "head")
            with psycopg.connect(temp) as conn:
                rows = conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='threads'"
                ).fetchall()
            columns = {row[0] for row in rows}
            assert {
                "approval_status",
                "approval_request_id",
                "approval_reason",
                "approval_response_action_id",
                "approval_updated_at",
            } <= columns
        finally:
            _drop_temp_db(maintenance, dbname)

    def test_upgrade_head_rewrites_legacy_created_status(self) -> None:
        maintenance, dbname, temp = self._setup()
        try:
            cfg = _make_postgres_config(temp)
            command.upgrade(cfg, "0002")
            with psycopg.connect(temp) as conn:
                conn.execute(
                    "INSERT INTO threads (id, created_at, updated_at, status) "
                    "VALUES (%s, %s, %s, %s)",
                    (
                        "legacy-created-thread",
                        "2026-03-09 00:00:00",
                        "2026-03-09 00:00:00",
                        "created",
                    ),
                )
                conn.commit()
            command.upgrade(cfg, "head")
            with psycopg.connect(temp) as conn:
                row = conn.execute(
                    "SELECT status FROM threads WHERE id = %s",
                    ("legacy-created-thread",),
                ).fetchone()
            assert row is not None
            assert row[0] == "submitted"
        finally:
            _drop_temp_db(maintenance, dbname)
