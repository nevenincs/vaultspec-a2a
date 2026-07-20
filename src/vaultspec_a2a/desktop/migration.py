"""Staged-generation desktop migration entrypoint.

The dashboard's external updater never migrates a live desktop store during
ordinary boot. After quiescence it invokes this dedicated entrypoint with a
validated one-time transaction descriptor. Given that descriptor, the entrypoint
runs the three schema mutations desktop boot refuses -- the Alembic upgrade to
the packaged head, the checkpointer schema setup, and the state-driven-development
(SDD) backfill -- against the descriptor's own stores only, refusing any store
that is live or locked, and returns a bounded, machine-readable result. It
performs no network access.

The result is a strict Pydantic model so the internal migrate command can emit it
as JSON. On failure it names the failing stage and the exception class only; it
never leaks free-form internals or store contents.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..database.checkpoint_schema import (
    CHECKPOINT_SCHEMA_VERSION,
    install_checkpoint_schema_identity,
)
from ..database.migrate import run_migrations
from ..database.migrations import backfill_teamstate_sdd_fields
from .transaction import (
    TransactionDescriptorError,
    ValidatedTransaction,
    load_transaction_descriptor,
    mark_transaction_consumed,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "MigrationResult",
    "MigrationStage",
    "StoreLockedError",
    "StoreName",
    "StoreOutcome",
    "StoreStatus",
    "run_staged_migration",
]


class StoreName(StrEnum):
    """The stores a staged migration touches, in application order."""

    PRIMARY = "primary"
    CHECKPOINT = "checkpoint"
    SDD = "sdd"


class StoreStatus(StrEnum):
    """The terminal status of one store within a staged migration."""

    MIGRATED = "migrated"
    INITIALIZED = "initialized"
    BACKFILLED = "backfilled"
    FAILED = "failed"


class MigrationStage(StrEnum):
    """The bounded stage vocabulary reported on a failed migration."""

    DESCRIPTOR = "descriptor"
    LOCK = "lock"
    PRIMARY = "primary"
    CHECKPOINT = "checkpoint"
    SDD = "sdd"
    CHECKPOINT_IDENTITY = "checkpoint-identity"
    CONSUME = "consume"


class StoreLockedError(RuntimeError):
    """A targeted store is live or otherwise locked and cannot be migrated."""


class _StageError(RuntimeError):
    """Internal carrier binding a failing stage to its underlying error class."""

    def __init__(self, stage: MigrationStage, error_class: str) -> None:
        super().__init__(f"{stage.value} stage failed")
        self.stage = stage
        self.error_class = error_class


class StoreOutcome(BaseModel):
    """The bounded outcome of one store within a staged migration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    store: StoreName = Field(description="The store this outcome describes.")
    status: StoreStatus = Field(description="The store's terminal status.")
    from_revision: str | None = Field(
        default=None, description="Alembic revision before migration, if applicable."
    )
    to_revision: str | None = Field(
        default=None, description="Alembic revision after migration, if applicable."
    )
    rows_affected: int | None = Field(
        default=None, description="Rows patched by the SDD backfill, if applicable."
    )
    schema_version: str | None = Field(
        default=None,
        description="Installed semantic schema version, when the store owns one.",
    )


class MigrationResult(BaseModel):
    """The bounded, JSON-serialisable result of a staged migration attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["succeeded", "failed"] = Field(
        description="Overall migration outcome."
    )
    transaction_id: str | None = Field(
        default=None, description="Consumed transaction id, when the descriptor parsed."
    )
    target_head: str | None = Field(
        default=None, description="Packaged Alembic head the migration targeted."
    )
    stores: tuple[StoreOutcome, ...] = Field(
        default=(), description="Per-store outcomes in application order."
    )
    duration_seconds: float = Field(
        description="Wall-clock duration of the migration attempt."
    )
    failed_stage: MigrationStage | None = Field(
        default=None, description="The stage that failed, when status is failed."
    )
    error_class: str | None = Field(
        default=None,
        description="Exception class name on failure; no free-form internals.",
    )


def _read_revision(db_path: Path) -> str | None:
    """Return the store's recorded Alembic revision, or ``None`` when absent."""
    if not db_path.is_file():
        return None
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
    finally:
        conn.close()
    return None if row is None else str(row[0])


def _ensure_unlocked(db_path: Path) -> None:
    """Refuse a store that another connection holds live or locked.

    Probes with a zero busy-timeout ``BEGIN IMMEDIATE``: a reserved or exclusive
    lock held by a live gateway (or any other writer) makes SQLite raise
    immediately rather than block. A missing file is unlocked; the migration
    creates it.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=0)
    try:
        conn.execute("PRAGMA busy_timeout=0")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
    except sqlite3.Error as exc:
        # Fail closed: a held lock, or any inability to acquire the immediate write
        # lock, means the store cannot be proven safe to migrate. Both refuse.
        raise StoreLockedError(
            f"store {db_path} could not be confirmed free (it is live, locked, or "
            "unreadable); drain and stop the gateway before staging a migration."
        ) from exc
    finally:
        conn.close()


async def _setup_checkpointer(checkpoint_path: Path) -> None:
    """Create the real LangGraph tables without claiming migration completion."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        await checkpointer.setup()
        await checkpointer.conn.execute("PRAGMA journal_mode=WAL")
        await checkpointer.conn.execute("PRAGMA busy_timeout=5000")


async def _execute(
    transaction: ValidatedTransaction, target_head: str
) -> tuple[StoreOutcome, ...]:
    """Run the three schema mutations in order against the descriptor's stores."""
    state = transaction.state
    database_url = f"sqlite+aiosqlite:///{state.database_path.as_posix()}"

    # Refuse any live or locked target before mutating either store.
    _ensure_unlocked(state.database_path)
    _ensure_unlocked(state.checkpoint_path)

    try:
        from_revision = _read_revision(state.database_path)
        await run_migrations(database_url)
    except Exception as exc:
        raise _StageError(MigrationStage.PRIMARY, type(exc).__name__) from exc
    primary = StoreOutcome(
        store=StoreName.PRIMARY,
        status=StoreStatus.MIGRATED,
        from_revision=from_revision,
        to_revision=target_head,
    )

    try:
        await _setup_checkpointer(state.checkpoint_path)
    except Exception as exc:
        raise _StageError(MigrationStage.CHECKPOINT, type(exc).__name__) from exc
    checkpoint = StoreOutcome(
        store=StoreName.CHECKPOINT, status=StoreStatus.INITIALIZED
    )

    try:
        patched = backfill_teamstate_sdd_fields(state.checkpoint_path)
    except Exception as exc:
        raise _StageError(MigrationStage.SDD, type(exc).__name__) from exc
    sdd = StoreOutcome(
        store=StoreName.SDD, status=StoreStatus.BACKFILLED, rows_affected=patched
    )
    try:
        await asyncio.to_thread(
            install_checkpoint_schema_identity, state.checkpoint_path
        )
    except Exception as exc:
        raise _StageError(
            MigrationStage.CHECKPOINT_IDENTITY, type(exc).__name__
        ) from exc
    checkpoint = checkpoint.model_copy(
        update={"schema_version": CHECKPOINT_SCHEMA_VERSION}
    )
    return (primary, checkpoint, sdd)


async def run_staged_migration(descriptor_path: Path) -> MigrationResult:
    """Run the staged-generation migration authorised by a descriptor file.

    Loads and validates the one-time transaction descriptor, refuses live or
    locked stores, upgrades the primary database to the packaged Alembic head,
    initialises the checkpointer schema, backfills SDD state, and marks the
    transaction consumed. Every failure is captured into the returned result;
    this function does not raise for an expected migration failure.

    Args:
        descriptor_path: Filesystem path to the transaction descriptor JSON.

    Returns:
        A bounded :class:`MigrationResult` describing per-store outcomes and, on
        failure, the failing stage and exception class.
    """
    started = time.monotonic()

    def _failed(
        stage: MigrationStage,
        error_class: str,
        *,
        transaction_id: str | None = None,
        target_head: str | None = None,
        stores: tuple[StoreOutcome, ...] = (),
    ) -> MigrationResult:
        return MigrationResult(
            status="failed",
            transaction_id=transaction_id,
            target_head=target_head,
            stores=stores,
            duration_seconds=time.monotonic() - started,
            failed_stage=stage,
            error_class=error_class,
        )

    try:
        transaction = load_transaction_descriptor(descriptor_path)
    except TransactionDescriptorError as exc:
        return _failed(MigrationStage.DESCRIPTOR, type(exc).__name__)

    transaction_id = transaction.descriptor.transaction_id
    # The descriptor's claimed head is validated equal to the packaged Alembic head
    # at load time, so it is authoritative here without re-reading the migration
    # graph (which would be an unguarded pre-mutation failure path).
    target_head = transaction.descriptor.migration_range.head

    try:
        stores = await _execute(transaction, target_head)
    except StoreLockedError as exc:
        return _failed(
            MigrationStage.LOCK,
            type(exc).__name__,
            transaction_id=transaction_id,
            target_head=target_head,
        )
    except _StageError as exc:
        return _failed(
            exc.stage,
            exc.error_class,
            transaction_id=transaction_id,
            target_head=target_head,
        )
    except Exception as exc:
        # Safety net: no unexpected mutation-phase error escapes as a traceback;
        # the entrypoint's result contract holds on every path.
        return _failed(
            MigrationStage.PRIMARY,
            type(exc).__name__,
            transaction_id=transaction_id,
            target_head=target_head,
        )

    # The stores are mutated; a consume failure (concurrent double-consume or a
    # marker-directory OS error) must still return a bounded result, not a
    # traceback. The mutations are idempotent, so the transaction can be retried.
    try:
        mark_transaction_consumed(transaction)
    except Exception as exc:
        return _failed(
            MigrationStage.CONSUME,
            type(exc).__name__,
            transaction_id=transaction_id,
            target_head=target_head,
            stores=stores,
        )

    return MigrationResult(
        status="succeeded",
        transaction_id=transaction_id,
        target_head=target_head,
        stores=stores,
        duration_seconds=time.monotonic() - started,
    )
