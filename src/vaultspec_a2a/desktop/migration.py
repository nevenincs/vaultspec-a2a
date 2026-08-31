"""Dashboard-driven desktop store migration and fresh-store initialisation.

The dashboard owns the update transaction - drain, snapshot, migrate,
activate, rollback - and performs snapshot and rollback itself as byte-level
file copies. What it cannot author is a2a's schema work, so after quiescence
it spawns this entrypoint as a bounded child. The entrypoint runs the three
schema mutations ordinary desktop boot refuses - the Alembic upgrade to the
packaged head, the checkpointer schema setup, and the state-driven-development
(SDD) backfill - against the application home's own stores, refusing any
store that is live or locked, and returns a bounded, machine-readable result.
It performs no network access and never touches a store the caller did not
quiesce; rollback belongs to the dashboard's own snapshot, never to this
module.

The result is a strict Pydantic model so the migrate command can emit it as
JSON. On failure it names the failing stage and the exception class only; it
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
from ..database.migrate import migration_script_location, run_migrations
from ..database.migrations import backfill_teamstate_sdd_fields

if TYPE_CHECKING:
    from pathlib import Path

    from .contract import MigrationRange

__all__ = [
    "MigrationGraphError",
    "MigrationResult",
    "MigrationStage",
    "StoreLockedError",
    "StoreName",
    "StoreOutcome",
    "StoreStatus",
    "initialize_fresh_stores",
    "migrate_stores",
    "package_migration_range",
]


class StoreName(StrEnum):
    """The stores a migration touches, in application order."""

    PRIMARY = "primary"
    CHECKPOINT = "checkpoint"
    SDD = "sdd"


class StoreStatus(StrEnum):
    """The terminal status of one store within a migration."""

    MIGRATED = "migrated"
    INITIALIZED = "initialized"
    BACKFILLED = "backfilled"
    FAILED = "failed"


class MigrationStage(StrEnum):
    """The bounded stage vocabulary reported on a failed migration."""

    PRECONDITION = "precondition"
    LOCK = "lock"
    PRIMARY = "primary"
    CHECKPOINT = "checkpoint"
    SDD = "sdd"
    CHECKPOINT_IDENTITY = "checkpoint-identity"


class StoreLockedError(RuntimeError):
    """A targeted store is live or otherwise locked and cannot be migrated."""


class MigrationGraphError(RuntimeError):
    """The packaged Alembic migration graph is unreadable or malformed."""


class _StageError(RuntimeError):
    """Internal carrier binding a failing stage to its underlying error class."""

    def __init__(self, stage: MigrationStage, error_class: str) -> None:
        super().__init__(f"{stage.value} stage failed")
        self.stage = stage
        self.error_class = error_class


class StoreOutcome(BaseModel):
    """The bounded outcome of one store within a migration."""

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
    """The bounded, JSON-serialisable result of a migration attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["succeeded", "failed"] = Field(
        description="Overall migration outcome."
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
    detail: str | None = Field(
        default=None,
        description="Bounded operator-facing detail for a refused precondition.",
    )


def package_migration_range() -> MigrationRange:
    """Return the packaged Alembic migration graph's base and head revisions."""
    from alembic.script import ScriptDirectory

    from .contract import MigrationRange

    try:
        script = ScriptDirectory(str(migration_script_location()))
        heads = script.get_heads()
        bases = script.get_bases()
    except Exception as exc:
        raise MigrationGraphError(
            "cannot read the packaged Alembic migration graph; reinstall "
            "vaultspec-a2a from a complete distribution."
        ) from exc
    if len(heads) != 1 or len(bases) != 1:
        raise MigrationGraphError(
            "the packaged Alembic migration graph must have exactly one base and "
            "one head."
        )
    return MigrationRange(base=bases[0], head=heads[0])


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
            "unreadable); drain and stop the gateway before migrating."
        ) from exc
    finally:
        conn.close()


async def _setup_checkpointer(checkpoint_path: Path) -> None:
    """Create the real LangGraph tables without claiming migration completion."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..control.config import settings
    from ..database.checkpoint_schema import checkpoint_pragmas

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        await checkpointer.setup()
        # The connection posture comes from the one place that owns it, which
        # exists precisely so the checkpoint writers cannot drift apart again.
        # This path had restated it and drifted anyway: it hardcoded the busy
        # timeout instead of reading the configured one, and omitted the
        # foreign-key pragma the owner documents as per-connection and therefore
        # required on every connection.
        for statement in checkpoint_pragmas(settings.sqlite_busy_timeout_ms):
            await checkpointer.conn.execute(statement)


async def _apply_mutations(
    database_path: Path, checkpoint_path: Path, target_head: str
) -> tuple[StoreOutcome, ...]:
    """Run the three schema mutations in order against the given stores.

    The single mutation core shared by the dashboard-spawned migration and the
    fresh-install initialisation: Alembic upgrade of the primary store,
    checkpointer schema setup plus identity, and the SDD backfill. Refuses any
    live or locked target before mutating either store.
    """
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    # Refuse any live or locked target before mutating either store.
    _ensure_unlocked(database_path)
    _ensure_unlocked(checkpoint_path)

    try:
        from_revision = _read_revision(database_path)
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
        await _setup_checkpointer(checkpoint_path)
    except Exception as exc:
        raise _StageError(MigrationStage.CHECKPOINT, type(exc).__name__) from exc
    checkpoint = StoreOutcome(
        store=StoreName.CHECKPOINT, status=StoreStatus.INITIALIZED
    )

    try:
        patched = backfill_teamstate_sdd_fields(checkpoint_path)
    except Exception as exc:
        raise _StageError(MigrationStage.SDD, type(exc).__name__) from exc
    sdd = StoreOutcome(
        store=StoreName.SDD, status=StoreStatus.BACKFILLED, rows_affected=patched
    )
    try:
        await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint_path)
    except Exception as exc:
        raise _StageError(
            MigrationStage.CHECKPOINT_IDENTITY, type(exc).__name__
        ) from exc
    checkpoint = checkpoint.model_copy(
        update={"schema_version": CHECKPOINT_SCHEMA_VERSION}
    )
    return (primary, checkpoint, sdd)


def _failed_result(
    started: float,
    stage: MigrationStage,
    error_class: str,
    *,
    target_head: str | None = None,
    detail: str | None = None,
) -> MigrationResult:
    return MigrationResult(
        status="failed",
        target_head=target_head,
        duration_seconds=time.monotonic() - started,
        failed_stage=stage,
        error_class=error_class,
        detail=detail,
    )


async def _run_mutations_bounded(
    started: float, database_path: Path, checkpoint_path: Path, target_head: str
) -> MigrationResult:
    """Run the mutation core and fold every expected failure into the result."""
    try:
        stores = await _apply_mutations(database_path, checkpoint_path, target_head)
    except StoreLockedError as exc:
        return _failed_result(
            started,
            MigrationStage.LOCK,
            type(exc).__name__,
            target_head=target_head,
            detail=str(exc),
        )
    except _StageError as exc:
        return _failed_result(
            started, exc.stage, exc.error_class, target_head=target_head
        )
    except Exception as exc:
        return _failed_result(
            started, MigrationStage.PRIMARY, type(exc).__name__, target_head=target_head
        )
    return MigrationResult(
        status="succeeded",
        target_head=target_head,
        stores=stores,
        duration_seconds=time.monotonic() - started,
    )


async def migrate_stores(
    app_home: Path,
    *,
    expect_from: str | None = None,
    expect_head: str | None = None,
) -> MigrationResult:
    """Upgrade the application home's quiesced stores to the packaged head.

    The dashboard-spawnable migrate entrypoint: after the caller drains and
    stops the gateway (and takes its own snapshot), this brings the primary
    store to the packaged Alembic head and completes the checkpointer and SDD
    schema work. *expect_from* and *expect_head* are optional fail-closed
    assertions of the observed current revision and the packaged head, so an
    updater that computed a base→head plan can refuse a store or a package
    that is not the one it planned against. Rollback is the caller's snapshot;
    this function only refuses (live/locked or failed preconditions) or
    completes.
    """
    from .profile import derive_state_paths

    started = time.monotonic()
    try:
        target_head = package_migration_range().head
    except MigrationGraphError as exc:
        return _failed_result(
            started, MigrationStage.PRECONDITION, type(exc).__name__, detail=str(exc)
        )
    if expect_head is not None and expect_head != target_head:
        return _failed_result(
            started,
            MigrationStage.PRECONDITION,
            "HeadMismatchError",
            target_head=target_head,
            detail=(
                f"packaged head {target_head!r} does not match expected head "
                f"{expect_head!r}"
            ),
        )
    state = derive_state_paths(app_home)
    if expect_from is not None:
        observed = _read_revision(state.database_path)
        if observed != expect_from:
            return _failed_result(
                started,
                MigrationStage.PRECONDITION,
                "BaseMismatchError",
                target_head=target_head,
                detail=(
                    f"primary store is at revision {observed!r}, not the expected "
                    f"{expect_from!r}"
                ),
            )
    return await _run_mutations_bounded(
        started, state.database_path, state.checkpoint_path, target_head
    )


async def initialize_fresh_stores(app_home: Path) -> MigrationResult:
    """Initialise a fresh application home's stores to the packaged schema head.

    The fresh-install companion to :func:`migrate_stores`: the same mutation
    core, but authorised by store absence. A primary store that already
    records an Alembic revision is an UPGRADE, not a fresh install, and is
    refused (``precondition`` stage) so setup can never silently migrate a
    store the dashboard has not snapshotted. Desktop boot itself remains
    non-mutating; this is the setup verb's seam.
    """
    from .profile import derive_state_paths

    started = time.monotonic()
    state = derive_state_paths(app_home)
    observed = _read_revision(state.database_path)
    if observed is not None:
        return _failed_result(
            started,
            MigrationStage.PRECONDITION,
            "StoreAlreadyInitializedError",
            detail=(
                f"primary store already records revision {observed!r}; upgrading "
                "an initialised home is the migrate verb, not setup"
            ),
        )
    try:
        target_head = package_migration_range().head
    except MigrationGraphError as exc:
        return _failed_result(
            started, MigrationStage.PRECONDITION, type(exc).__name__, detail=str(exc)
        )
    return await _run_mutations_bounded(
        started, state.database_path, state.checkpoint_path, target_head
    )
