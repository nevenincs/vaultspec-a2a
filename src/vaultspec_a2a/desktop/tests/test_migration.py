"""Real-store tests for the staged-generation desktop migration entrypoint.

Every test writes a real transaction descriptor and drives the production
entrypoint against real SQLite stores. No mock, monkeypatch, stub, skip, or
expected failure is used: success is proved by reading the real migrated schema,
consumption is proved by the durable marker file, and refusals are proved by
holding a real SQLite lock and by supplying a genuinely inconsistent descriptor.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ..migration import (
    MigrationStage,
    StoreName,
    StoreStatus,
    run_staged_migration,
)
from ..profile import derive_state_paths
from ..transaction import package_migration_range

if TYPE_CHECKING:
    from pathlib import Path

_DIGEST = "b" * 64


def _write_descriptor(descriptor_path: Path, home: Path, **overrides: object) -> Path:
    """Write a well-formed migration descriptor targeting ``home``."""
    state = derive_state_paths(home)
    packaged = package_migration_range()
    document: dict[str, object] = {
        "descriptor_version": "1",
        "transaction_id": "txn-migrate-1",
        "app_home": str(home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": _DIGEST, "component_version": "2.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    document.update(overrides)
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    return descriptor_path


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


class TestFreshStoreMigration:
    @pytest.mark.asyncio
    async def test_fresh_store_migrates_all_three(self, tmp_path: Path) -> None:
        """A fresh app home migrates the primary, checkpoint, and SDD state."""
        home = tmp_path / "app"
        descriptor = _write_descriptor(tmp_path / "txn.json", home)
        state = derive_state_paths(home)
        packaged = package_migration_range()

        result = await run_staged_migration(descriptor)

        assert result.status == "succeeded"
        assert result.target_head == packaged.head
        assert result.failed_stage is None
        outcomes = {outcome.store: outcome for outcome in result.stores}
        assert outcomes[StoreName.PRIMARY].status is StoreStatus.MIGRATED
        assert outcomes[StoreName.PRIMARY].from_revision is None
        assert outcomes[StoreName.PRIMARY].to_revision == packaged.head
        assert outcomes[StoreName.CHECKPOINT].status is StoreStatus.INITIALIZED
        assert outcomes[StoreName.SDD].status is StoreStatus.BACKFILLED

        # Real schema landed and the transaction is durably consumed.
        version = (
            sqlite3.connect(str(state.database_path))
            .execute("SELECT version_num FROM alembic_version")
            .fetchone()
        )
        assert version is not None
        assert version[0] == packaged.head
        assert _table_present(state.checkpoint_path, "checkpoints")
        assert (
            state.receipts_dir / "migration-transaction-txn-migrate-1.consumed"
        ).is_file()

    @pytest.mark.asyncio
    async def test_consumed_descriptor_is_refused_on_replay(
        self, tmp_path: Path
    ) -> None:
        """Re-running a consumed descriptor is refused at the descriptor stage."""
        home = tmp_path / "app"
        descriptor = _write_descriptor(tmp_path / "txn.json", home)

        first = await run_staged_migration(descriptor)
        assert first.status == "succeeded"

        second = await run_staged_migration(descriptor)
        assert second.status == "failed"
        assert second.failed_stage is MigrationStage.DESCRIPTOR
        assert second.error_class == "TransactionDescriptorError"


class TestRefusals:
    @pytest.mark.asyncio
    async def test_live_store_is_refused(self, tmp_path: Path) -> None:
        """A store held under a real write lock is refused, mutating nothing."""
        home = tmp_path / "app"
        descriptor = _write_descriptor(tmp_path / "txn.json", home)
        state = derive_state_paths(home)
        state.database_path.parent.mkdir(parents=True, exist_ok=True)

        holder = sqlite3.connect(str(state.database_path))
        try:
            holder.execute("BEGIN IMMEDIATE")
            result = await run_staged_migration(descriptor)
        finally:
            holder.rollback()
            holder.close()

        assert result.status == "failed"
        assert result.failed_stage is MigrationStage.LOCK
        assert result.error_class == "StoreLockedError"
        # The refused transaction is not consumed and may be retried.
        assert not (
            state.receipts_dir / "migration-transaction-txn-migrate-1.consumed"
        ).exists()

    @pytest.mark.asyncio
    async def test_descriptor_mismatch_is_refused(self, tmp_path: Path) -> None:
        """A descriptor whose migration range is wrong is refused up front."""
        home = tmp_path / "app"
        descriptor = _write_descriptor(
            tmp_path / "txn.json",
            home,
            migration_range={"base": "0001", "head": "9999_future"},
        )

        result = await run_staged_migration(descriptor)

        assert result.status == "failed"
        assert result.failed_stage is MigrationStage.DESCRIPTOR
        assert result.error_class == "TransactionDescriptorError"
