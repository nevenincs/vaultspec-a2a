"""Tests for Alembic migration framework.

Verifies:
1. Upgrade head creates all 4 app-owned tables
2. Downgrade base removes all app-owned tables
3. LangGraph checkpoint tables are excluded from migrations
4. run_migrations() programmatic API works
5. No revision script describes the schema through the application package
"""

import ast
import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from .. import migrations as _migrations_package
from .._write_authority_check_parser import extract_named_check_predicates
from ..migrate import (
    build_migration_config,
    migration_script_location,
    run_migrations,
)
from ..write_authority_schema import normalize_schema_expression

_APP_TABLES = {
    "threads",
    "permission_logs",
    "cost_tracking",
    "thread_execution_state",
    "thread_deletion_saga",
    "permission_requests",
    "control_actions",
}
#: Revision 0026 retired these; head must not carry them.
_RETIRED_TABLES = {"artifacts", "task_queue_entries"}
_RETIRED_COLUMNS = {
    "threads": {"approval_reason", "repair_generation", "recovery_epoch"},
    "thread_execution_state": {
        "snapshot_created_at",
        "recovery_epoch",
        "interrupt_types_json",
    },
    "control_actions": {"worker_generation"},
    "permission_requests": {"worker_generation"},
}
_ACTIVE_INDEX_ORDERING = {
    "ix_threads_active_order": "(created_at DESC, id DESC)",
    "ix_threads_active_workspace_order": "(workspace_key, created_at DESC, id DESC)",
    "ix_threads_active_feature_order": "(feature_tag, created_at DESC, id DESC)",
    "ix_threads_active_workspace_feature_order": (
        "(workspace_key, feature_tag, created_at DESC, id DESC)"
    ),
}
_LANGGRAPH_TABLES = {"checkpoints", "writes"}
_ALEMBIC_INI = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "alembic.ini"
)


def _make_config(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def _resolve_head_revision() -> str:
    """Return the head revision declared by the packaged migration chain.

    Reading the revision graph opens no database: ``ScriptDirectory`` consults
    only ``script_location``. The URL below satisfies the config builder and is
    never connected. Deriving head from the chain — through the project's own
    ``build_migration_config``, the single source of truth for where migrations
    live — is what keeps the "reached head" assertions true for every future
    revision instead of turning each new migration into a test edit.

    Raises:
        RuntimeError: If the chain does not resolve to exactly one head, which
            is how two revisions sharing a ``down_revision`` present. That is a
            broken chain, and it fails here with the branch named rather than
            as an opaque error from whichever test upgraded first.
    """
    heads = ScriptDirectory.from_config(
        build_migration_config("sqlite+aiosqlite:///:memory:")
    ).get_heads()
    if len(heads) != 1:
        msg = (
            "the packaged migration chain must resolve to exactly one head; "
            f"found {sorted(heads)}"
        )
        raise RuntimeError(msg)
    return heads[0]


def test_migration_config_carries_the_sqlite_busy_timeout() -> None:
    """The migration engine receives the configured lock-wait budget."""
    config = build_migration_config(
        "sqlite+aiosqlite:///:memory:", sqlite_busy_timeout_ms=73
    )

    assert config.attributes["sqlite_busy_timeout_ms"] == 73


#: The revision an ``upgrade``/``stamp`` to ``head`` must land on. Derived from
#: the chain rather than hardcoded, so adding a migration needs no edit here.
_HEAD_REVISION = _resolve_head_revision()


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


def _get_columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            str(row[0])
            for row in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))
        }
    finally:
        conn.close()


def _deadline_check(db_path: Path) -> str:
    """Return the journal's recovery-deadline CHECK as the store holds it.

    Read as a named predicate rather than as whole-table DDL: a batch rebuild
    reorders a table's constraints, so comparing the CREATE statement text would
    fail a round trip that restored the invariant exactly.
    """
    checks = extract_named_check_predicates(
        _stored_sql(db_path, "table", "control_actions")
    )
    predicate = checks.get("ck_control_actions_recovery_deadline_required")
    assert predicate is not None, checks
    return normalize_schema_expression(predicate)


def _insert_refusal_row(
    db_path: Path,
    *,
    deadline: str,
    action_id: str = "refusal-action",
    key: str = "permission-rejection:refusal-key",
    result_status: str = "rejected_invalid_state",
) -> None:
    """Write one journal row of a recovery type straight through the CHECK."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO control_actions (id, thread_id, action_type, "
            "idempotency_key, requested_at, result_status, recovery_deadline_at) "
            f"VALUES (?, 'refusal-run', 'permission_response_submitted', ?, "
            f"'2026-10-07 00:00:00', ?, {deadline})",
            (action_id, key, result_status),
        )
        conn.commit()
    finally:
        conn.close()


def _delete_refusal_row(db_path: Path, action_id: str = "refusal-action") -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM control_actions WHERE id = ?", (action_id,))
        conn.commit()
    finally:
        conn.close()


def _stored_sql(db_path: Path, kind: str, name: str) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?", (kind, name)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"{kind} {name} is absent"
    return str(row[0])


class TestAlembicUpgradeDowngrade:
    def test_control_action_lease_columns_upgrade_and_downgrade(
        self, runtime_dir: Path
    ) -> None:
        """0012 is additive over historical rows and fully reversible."""
        db = runtime_dir / "control-action-leases.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0011")
        conn = sqlite3.connect(str(db))
        before = {row[1] for row in conn.execute("PRAGMA table_info(control_actions)")}
        conn.close()
        assert not {"dispatch_id", "claim_token", "claim_expires_at"} & before

        command.upgrade(cfg, "0012")
        conn = sqlite3.connect(str(db))
        upgraded = {
            row[1] for row in conn.execute("PRAGMA table_info(control_actions)")
        }
        indexes = {
            row[1]: bool(row[2])
            for row in conn.execute("PRAGMA index_list(control_actions)")
        }
        conn.close()
        assert {"dispatch_id", "claim_token", "claim_expires_at"} <= upgraded
        assert indexes["ux_control_actions_dispatch_id"] is True

        command.downgrade(cfg, "0011")
        conn = sqlite3.connect(str(db))
        downgraded = {
            row[1] for row in conn.execute("PRAGMA table_info(control_actions)")
        }
        conn.close()
        assert not {"dispatch_id", "claim_token", "claim_expires_at"} & downgraded

    def test_schema_retirement_drops_and_restores_its_schema(
        self, runtime_dir: Path
    ) -> None:
        """0026 retires dead schema, keeps run order descending, and reverses.

        Stepping on down to 0016 proves the restored write-authority CHECKs sit
        where 0017 put them: 0017's downgrade drops those columns natively,
        which SQLite refuses while a table-level CHECK names them.
        """
        db = runtime_dir / "schema-retirement.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0025")
        assert _get_tables(db) >= _RETIRED_TABLES

        command.upgrade(cfg, "0026")
        assert not (_RETIRED_TABLES & _get_tables(db))
        for table, retired in _RETIRED_COLUMNS.items():
            assert not (retired & _get_columns(db, table)), table
        for index, ordering in _ACTIVE_INDEX_ORDERING.items():
            ddl = _stored_sql(db, "index", index)
            assert ordering in ddl, ddl
            assert "WHERE is_active IS 1" in ddl, ddl
        for table in ("threads", "control_actions"):
            assert "repair_started" not in _stored_sql(db, "table", table)

        command.downgrade(cfg, "0025")
        assert _get_tables(db) >= _RETIRED_TABLES
        for table, retired in _RETIRED_COLUMNS.items():
            assert retired <= _get_columns(db, table), table
        for index, ordering in _ACTIVE_INDEX_ORDERING.items():
            assert ordering in _stored_sql(db, "index", index)
        for table in ("threads", "control_actions"):
            assert "repair_started" in _stored_sql(db, "table", table)

        command.downgrade(cfg, "0016")
        assert "writer_action_type" not in _get_columns(db, "threads")

    def test_schema_retirement_refuses_a_stored_retired_action(
        self, runtime_dir: Path
    ) -> None:
        """A journal row naming a retired action type stops 0026 before any DDL."""
        db = runtime_dir / "retired-action.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0025")
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "INSERT INTO control_actions (id, thread_id, action_type, "
                "idempotency_key, requested_at, result_status, worker_generation) "
                "VALUES ('retired-action', 'retired-run', 'repair_started', "
                "'retired-key', '2026-10-07 00:00:00', 'applied', 0)"
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(RuntimeError, match="repair action type"):
            command.upgrade(cfg, "0026")

        conn = sqlite3.connect(str(db))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()
        assert version == ("0025",)
        assert _get_tables(db) >= _RETIRED_TABLES
        assert "worker_generation" in _get_columns(db, "control_actions")

    def test_dispatchable_deadline_narrows_and_reverses(
        self, runtime_dir: Path
    ) -> None:
        """0027 binds the deadline to a dispatchable row and steps back.

        The narrowed predicate only ADMITS what 0021 rejected, so a refusal row
        with no deadline is storable at 0027 and not at 0021. The downgrade
        therefore refuses such a store before any DDL, and reverses cleanly once
        the row is gone.
        """
        db = runtime_dir / "dispatchable-deadline.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0026")
        before = _deadline_check(db)
        assert "result_status" not in before, before

        command.upgrade(cfg, "0027")
        assert "'accepted_not_applied','queued'" in _deadline_check(db)

        _insert_refusal_row(db, deadline="NULL")
        with pytest.raises(RuntimeError, match="carries no recovery deadline"):
            command.downgrade(cfg, "0026")
        assert "'accepted_not_applied','queued'" in _deadline_check(db)

        _delete_refusal_row(db)
        command.downgrade(cfg, "0026")
        assert _deadline_check(db) == before

    def test_a_refusal_row_without_a_deadline_is_storable_only_at_head(
        self, runtime_dir: Path
    ) -> None:
        """The CHECK itself, exercised by the write the old invariant refused."""
        db = runtime_dir / "deadlineless-refusal.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0026")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_refusal_row(db, deadline="NULL")

        command.upgrade(cfg, "0027")
        _insert_refusal_row(db, deadline="NULL")
        # A row still owed a delivery keeps the deadline requirement.
        with pytest.raises(sqlite3.IntegrityError):
            _insert_refusal_row(
                db,
                deadline="NULL",
                action_id="still-owed",
                key="still-owed-key",
                result_status="accepted_not_applied",
            )

    def test_upgrade_head_creates_all_app_tables(self, runtime_dir: Path) -> None:
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")

        tables = _get_tables(db)
        assert tables >= _APP_TABLES
        assert not (tables & _RETIRED_TABLES)
        # alembic_version is also expected
        assert "alembic_version" in tables

    def test_downgrade_base_removes_all_app_tables(self, runtime_dir: Path) -> None:
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

        tables = _get_tables(db)
        # Only alembic_version should remain (Alembic's own tracking table)
        assert not ((_APP_TABLES | _RETIRED_TABLES) & tables)

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
        assert row[0] == _HEAD_REVISION

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
            "approval_response_action_id",
            "approval_updated_at",
        } <= columns
        assert "approval_reason" not in columns

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
            "recorded_at",
            "task_count",
            "interrupt_count",
            "next_nodes_json",
            "tasks_json",
            "degraded_reasons_json",
        } <= columns
        assert (
            not {
                "snapshot_created_at",
                "recovery_epoch",
                "interrupt_types_json",
            }
            & columns
        )

    def test_upgrade_head_adds_thread_deletion_saga_table(
        self,
        runtime_dir: Path,
    ) -> None:
        """Upgrading head should add the cross-store deletion saga table."""
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db))
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(thread_deletion_saga)"
            ).fetchall()
        }
        conn.close()

        assert {
            "thread_id",
            "created_at",
            "updated_at",
            "claimed_at",
            "manifest_json",
            "result_json",
        } <= columns

    def test_downgrade_from_head_removes_deletion_saga_table(
        self,
        runtime_dir: Path,
    ) -> None:
        """Downgrading one revision removes only the deletion saga table."""
        db = runtime_dir / "test.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "head")
        assert "thread_deletion_saga" in _get_tables(db)

        command.downgrade(cfg, "0009")

        tables = _get_tables(db)
        assert "thread_deletion_saga" not in tables
        assert "threads" in tables

    def test_revision_0009_projects_active_run_selectors(
        self, runtime_dir: Path
    ) -> None:
        """The selector migration projects metadata and terminal lifecycle state."""
        db = runtime_dir / "active-run-selectors.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0007")
        workspace = str((runtime_dir / "workspace").resolve())
        canonical_workspace = os.path.normcase(os.path.realpath(workspace))

        conn = sqlite3.connect(str(db))
        conn.executemany(
            """
            INSERT INTO threads (
                id, created_at, updated_at, status, thread_metadata
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "active-run",
                    "2026-07-19 00:00:00",
                    "2026-07-19 00:00:00",
                    "running",
                    json.dumps({"workspace_root": workspace, "feature_tag": "a2a"}),
                ),
                (
                    "completed-run",
                    "2026-07-19 00:00:01",
                    "2026-07-19 00:00:01",
                    "completed",
                    None,
                ),
            ],
        )
        conn.commit()
        conn.close()

        command.upgrade(cfg, "0009")

        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT id, workspace_root, workspace_key, feature_tag, is_active "
            "FROM threads ORDER BY id"
        ).fetchall()
        index_rows = conn.execute("PRAGMA index_list(threads)").fetchall()
        indexes = {row[1] for row in index_rows}
        partial_indexes = {row[1] for row in index_rows if row[4] == 1}
        conn.close()

        assert rows == [
            (
                "active-run",
                canonical_workspace,
                hashlib.sha256(canonical_workspace.encode("utf-8")).hexdigest(),
                "a2a",
                1,
            ),
            ("completed-run", None, None, None, 0),
        ]
        assert {
            "ix_threads_active_order",
            "ix_threads_active_workspace_order",
            "ix_threads_active_workspace_feature_order",
        } <= indexes
        assert {
            "ix_threads_active_order",
            "ix_threads_active_workspace_order",
            "ix_threads_active_feature_order",
            "ix_threads_active_workspace_feature_order",
        } <= partial_indexes


class TestRevisionsAreSelfContained:
    """No revision describes the schema through the application package.

    A version script states the schema at ONE moment in the chain. Importing the
    application package replaces that statement with whatever the package means
    today: deleting a model symbol breaks a historical revision outright, and
    changing one silently rewrites the DDL history already replayed into every
    existing store. So every structural fact a revision needs - a constant, a
    predicate, a custom column type - is spelled inside the revision, frozen at
    the moment it describes, even when that duplicates a live symbol.

    Asserted over the whole chain rather than over one script, because the rule
    is the chain's and a new revision is exactly where it gets broken next.
    """

    @staticmethod
    def _package_references(script: Path) -> list[str]:
        """Return every import in *script* that reaches the application package.

        A relative import counts as a reference even though Alembic loads these
        scripts by location and would raise on one: the rule is about reaching
        into the package at all, not about which spelling happens to fail.
        """
        root = _migrations_package.__name__.partition(".")[0]
        found: list[str] = []
        for node in ast.walk(ast.parse(script.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.extend(
                    alias.name
                    for alias in node.names
                    if alias.name.partition(".")[0] == root
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    found.append("." * node.level + module)
                elif module.partition(".")[0] == root:
                    found.append(module)
        return sorted(found)

    def test_no_revision_imports_the_application_package(self) -> None:
        """Every packaged revision is self-contained."""
        versions = migration_script_location() / "versions"
        scripts = sorted(
            path for path in versions.glob("*.py") if path.name != "__init__.py"
        )
        assert len(scripts) >= 27, (
            f"only {len(scripts)} revision scripts were found under {versions}; "
            "this guard compared almost nothing"
        )

        offenders = {
            script.name: references
            for script in scripts
            if (references := self._package_references(script))
        }

        assert offenders == {}, (
            "these revisions re-describe the schema through the application "
            f"package instead of freezing what they ship: {offenders}"
        )


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

    def test_runtime_config_preserves_percent_encoded_urls(self) -> None:
        """Alembic interpolation preserves Windows URL escapes."""
        database_url = "sqlite+aiosqlite:///C:/Vault%20Spec/runtime%25.db"
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
        assert version[0] == _HEAD_REVISION

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
        assert version[0] == _HEAD_REVISION

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
            assert version[0] == _HEAD_REVISION
            assert _get_tables(database) >= _APP_TABLES
