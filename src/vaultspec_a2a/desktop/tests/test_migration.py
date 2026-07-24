"""Real-store tests for the dashboard-spawnable desktop migration authority.

Every test drives the production entrypoints against real SQLite stores. No
mock, monkeypatch, stub, skip, or expected failure is used: success is proved
by reading the real migrated schema, and refusals are proved by holding a real
SQLite lock and by asserting against the real packaged migration graph.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from vaultspec_a2a.database.checkpoint_schema import (
    CHECKPOINT_SCHEMA_DIGEST,
    CHECKPOINT_SCHEMA_VERSION,
)

from ..migration import (
    MigrationStage,
    StoreName,
    StoreStatus,
    initialize_fresh_stores,
    migrate_stores,
    package_migration_range,
)
from ..profile import derive_state_paths

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig


def _table_present(db_path: Path, table: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def _primary_revision(db_path: Path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError as exc:
            assert "no such table" in str(exc).lower()
            return None
    finally:
        conn.close()
    return None if row is None else str(row[0])


class TestMigrateStores:
    @pytest.mark.asyncio
    async def test_fresh_home_migrates_all_three_stores(self, tmp_path: Path) -> None:
        """A fresh app home migrates the primary, checkpoint, and SDD state."""
        home = tmp_path / "app"
        state = derive_state_paths(home)
        packaged = package_migration_range()

        result = await migrate_stores(home)

        assert result.status == "succeeded"
        assert result.target_head == packaged.head
        assert result.failed_stage is None
        outcomes = {outcome.store: outcome for outcome in result.stores}
        assert outcomes[StoreName.PRIMARY].status is StoreStatus.MIGRATED
        assert outcomes[StoreName.PRIMARY].from_revision is None
        assert outcomes[StoreName.PRIMARY].to_revision == packaged.head
        assert outcomes[StoreName.CHECKPOINT].status is StoreStatus.INITIALIZED
        assert (
            outcomes[StoreName.CHECKPOINT].schema_version == CHECKPOINT_SCHEMA_VERSION
        )
        assert outcomes[StoreName.SDD].status is StoreStatus.BACKFILLED

        # Real schema landed.
        assert _primary_revision(state.database_path) == packaged.head
        assert _table_present(state.checkpoint_path, "checkpoints")
        checkpoint_identity = (
            sqlite3.connect(str(state.checkpoint_path))
            .execute(
                "SELECT schema_version, schema_digest "
                "FROM vaultspec_checkpoint_schema WHERE singleton = 1"
            )
            .fetchone()
        )
        assert checkpoint_identity == (
            CHECKPOINT_SCHEMA_VERSION,
            CHECKPOINT_SCHEMA_DIGEST,
        )

    @pytest.mark.asyncio
    async def test_migrate_is_idempotent_at_head(self, tmp_path: Path) -> None:
        """A second migrate against a head-revision store succeeds as a no-op."""
        home = tmp_path / "app"
        packaged = package_migration_range()
        first = await migrate_stores(home)
        assert first.status == "succeeded"

        second = await migrate_stores(home, expect_from=packaged.head)

        assert second.status == "succeeded"
        outcomes = {outcome.store: outcome for outcome in second.stores}
        assert outcomes[StoreName.PRIMARY].from_revision == packaged.head
        assert outcomes[StoreName.PRIMARY].to_revision == packaged.head

    @pytest.mark.asyncio
    async def test_legacy_serialized_state_is_backfilled_before_identity_stamp(
        self, tmp_path: Path
    ) -> None:
        """The semantic marker is written only after real state migration."""
        home = tmp_path / "app"
        state = derive_state_paths(home)
        state.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        legacy = empty_checkpoint()
        legacy["channel_values"] = {"messages": []}
        config: RunnableConfig = {
            "configurable": {"thread_id": "legacy-thread", "checkpoint_ns": ""}
        }
        async with AsyncSqliteSaver.from_conn_string(
            str(state.checkpoint_path)
        ) as checkpointer:
            stored_config = await checkpointer.aput(config, legacy, {}, {})

        result = await migrate_stores(home)

        assert result.status == "succeeded"
        outcomes = {outcome.store: outcome for outcome in result.stores}
        assert outcomes[StoreName.SDD].rows_affected == 1
        assert (
            outcomes[StoreName.CHECKPOINT].schema_version == CHECKPOINT_SCHEMA_VERSION
        )
        async with AsyncSqliteSaver.from_conn_string(
            str(state.checkpoint_path)
        ) as checkpointer:
            stored = await checkpointer.aget_tuple(stored_config)
        assert stored is not None
        assert stored.checkpoint["channel_values"]["vault_index"] == {}


class TestRefusals:
    @pytest.mark.asyncio
    async def test_live_store_is_refused(self, tmp_path: Path) -> None:
        """A store held under a real write lock is refused, mutating nothing."""
        home = tmp_path / "app"
        state = derive_state_paths(home)
        state.database_path.parent.mkdir(parents=True, exist_ok=True)

        holder = sqlite3.connect(str(state.database_path))
        try:
            holder.execute("BEGIN IMMEDIATE")
            result = await migrate_stores(home)
        finally:
            holder.rollback()
            holder.close()

        assert result.status == "failed"
        assert result.failed_stage is MigrationStage.LOCK
        assert result.error_class == "StoreLockedError"
        # The refused store was not mutated.
        assert _primary_revision(state.database_path) is None

    @pytest.mark.asyncio
    async def test_expect_from_mismatch_is_refused(self, tmp_path: Path) -> None:
        """A base assertion that does not match the store refuses up front."""
        home = tmp_path / "app"
        state = derive_state_paths(home)

        result = await migrate_stores(home, expect_from="0001_not_the_base")

        assert result.status == "failed"
        assert result.failed_stage is MigrationStage.PRECONDITION
        assert result.error_class == "BaseMismatchError"
        assert not state.database_path.exists() or (
            _primary_revision(state.database_path) is None
        )

    @pytest.mark.asyncio
    async def test_expect_head_mismatch_is_refused(self, tmp_path: Path) -> None:
        """A head assertion that does not match the package refuses up front."""
        home = tmp_path / "app"

        result = await migrate_stores(home, expect_head="9999_future")

        assert result.status == "failed"
        assert result.failed_stage is MigrationStage.PRECONDITION
        assert result.error_class == "HeadMismatchError"


class TestInitializeFreshStores:
    @pytest.mark.asyncio
    async def test_fresh_init_then_refusal_on_initialised_home(
        self, tmp_path: Path
    ) -> None:
        """Fresh init reaches head; a second init refuses at the precondition."""
        home = tmp_path / "app"
        state = derive_state_paths(home)
        packaged = package_migration_range()

        first = await initialize_fresh_stores(home)
        assert first.status == "succeeded"
        assert _primary_revision(state.database_path) == packaged.head

        second = await initialize_fresh_stores(home)
        assert second.status == "failed"
        assert second.failed_stage is MigrationStage.PRECONDITION
        assert second.error_class == "StoreAlreadyInitializedError"
