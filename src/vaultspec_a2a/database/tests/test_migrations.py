"""Tests for Alembic migration framework (ADR-029).

Verifies:
1. Upgrade head creates all 4 app-owned tables
2. Downgrade base removes all app-owned tables
3. LangGraph checkpoint tables are excluded from migrations
4. run_migrations() programmatic API works
5. (Postgres) upgrade/downgrade/column/data-migration on a real Postgres instance
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from ..migrate import run_migrations

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
