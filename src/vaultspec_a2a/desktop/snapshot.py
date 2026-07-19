"""Consistency-group snapshot and restore for the desktop updater transaction.

The dashboard's external updater never replaces desktop state file by file. After
it drains and stops the owned gateway, it snapshots the whole schema-bearing
*consistency group* as one receipt-verifiable unit, stages and activates the new
generation, and -- if anything fails before acceptance -- restores that same group
back to the captured content. This module is the single authority for that group
snapshot and restore.

The consistency group is the set of mutable, schema-bearing SQLite stores whose
contents must move together or not at all: the primary application database (the
Alembic-versioned store) and the checkpoint database (the LangGraph checkpointer
plus the state-driven-development state it carries). Neither store is derivable
from the other, so both are mandatory members; a store may be omitted from a
group only when a release manifest declares and proves it derivable, which
neither of these is.

Coherence comes from SQLite's own online-backup API rather than a byte copy. A
byte copy of a live-format database can straddle a write-ahead-log boundary and
capture a torn page; ``sqlite3.Connection.backup`` instead reads one consistent
view -- main file plus every committed WAL frame -- through a real connection and
writes a standalone, sidecar-free database. Because the updater snapshots only
after quiescence there are no in-flight frames to lose, and the backup never
mutates the source store it captures.

Durability and atomicity are layered on top. Each captured store is written to a
temp file, flushed with ``fsync``, and only then renamed into place; the group is
*committed* by writing exactly one descriptor -- a JSON document carrying each
store's source path, digest, size, and schema-revision facts, plus the group
identity -- through the same temp-fsync-atomic-rename discipline. Until that
descriptor lands the snapshot is invisible: :func:`inspect_snapshot` reports a
group only when its descriptor is committed and every captured store still
matches its recorded digest.

Restore is governed by a *quiesced-restore marker*. The marker is written before
any live store is touched and cleared only after every store is restored and
flushed. Its presence is the durable signal that a restore was interrupted
part-way; recovery rolls forward deterministically, re-restoring every member
from the immutable captured copies (an idempotent operation, because the source
of truth is the committed snapshot), so no partially restored pair is ever left
looking healthy.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, cast

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from .profile import DesktopProfileError, DesktopStatePaths, derive_state_paths

if TYPE_CHECKING:
    from typing import BinaryIO

__all__ = [
    "ConsistencyGroupStore",
    "ConsistencyGroupStoreSpecification",
    "GroupDescriptor",
    "RestoreMarker",
    "RestoreOutcome",
    "RestorePendingError",
    "SnapshotError",
    "SnapshotIntegrityError",
    "SnapshotStoreLockedError",
    "StoreMember",
    "StoreSnapshot",
    "consistency_group_members",
    "consistency_group_specifications",
    "create_snapshot",
    "descriptor_path",
    "inspect_snapshot",
    "list_snapshots",
    "pending_restore",
    "restore_marker_path",
    "restore_snapshot",
]

DESCRIPTOR_VERSION: Final = "1"
MARKER_VERSION: Final = "1"
DESCRIPTOR_NAME: Final = "group.json"
RESTORE_MARKER_NAME: Final = "restore.marker.json"

_GROUP_ID_MAX: Final = 128
_MAX_DESCRIPTOR_BYTES: Final = 1 << 20
_MAX_MARKER_BYTES: Final = 1 << 16
_DIGEST_CHUNK: Final = 1 << 20
_TEMP_SUFFIX: Final = ".tmp"

# LangGraph/aiosqlite write these sidecars beside a WAL-mode database. A restored
# standalone copy must not inherit stale sidecars from the store it overwrites,
# so they are removed atomically-adjacent to the rename.
_SQLITE_SIDECARS: Final = ("-wal", "-shm")


class ConsistencyGroupStore(StrEnum):
    """The schema-bearing stores that snapshot and restore as one group.

    ``PRIMARY`` is the Alembic-versioned application database. ``CHECKPOINT`` is
    the LangGraph checkpoint database carrying the state-driven-development state.
    Both are mandatory: neither is derivable from the other.
    """

    PRIMARY = "primary"
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True, slots=True)
class ConsistencyGroupStoreSpecification:
    """One path-independent mutable-store declaration for the desktop profile.

    Runtime seating and component-manifest generation both consume this type.
    The wire values live here as data, while the contract module owns only their
    validation grammar.
    """

    store: ConsistencyGroupStore
    manifest_kind: Literal["primary-database", "checkpoint-database"]
    state_path_attribute: Literal["database_path", "checkpoint_path"]
    schema_authority: Literal["alembic-migration-range", "checkpointer-schema"]
    derivable: Literal[False] = False


_CONSISTENCY_GROUP_SPECIFICATIONS: Final = (
    ConsistencyGroupStoreSpecification(
        store=ConsistencyGroupStore.PRIMARY,
        manifest_kind="primary-database",
        state_path_attribute="database_path",
        schema_authority="alembic-migration-range",
    ),
    ConsistencyGroupStoreSpecification(
        store=ConsistencyGroupStore.CHECKPOINT,
        manifest_kind="checkpoint-database",
        state_path_attribute="checkpoint_path",
        schema_authority="checkpointer-schema",
    ),
)


def consistency_group_specifications() -> tuple[
    ConsistencyGroupStoreSpecification, ...
]:
    """Return the profile's sole path-independent mutable-store declaration."""
    return _CONSISTENCY_GROUP_SPECIFICATIONS


class SnapshotError(RuntimeError):
    """Base class for every fail-closed consistency-group snapshot failure."""


class SnapshotIntegrityError(SnapshotError):
    """A snapshot is missing, uncommitted, malformed, or digest-inconsistent.

    Raised when a group descriptor cannot be read or validated, when a committed
    descriptor references a captured store file that is absent, or when a captured
    store's bytes no longer match the digest the descriptor recorded.
    """


class SnapshotStoreLockedError(SnapshotError):
    """A consistency-group store is live or locked and cannot be captured/restored.

    The updater snapshots and restores only after quiescence. A reserved or
    exclusive lock held by a live gateway (or any other writer) means the group is
    not quiescent, so the operation fails closed rather than capturing or
    overwriting a store beneath a live connection.
    """


class RestorePendingError(SnapshotError):
    """A restore marker from an interrupted restore blocks a fresh restore.

    Raised when :func:`restore_snapshot` is asked to start a new restore while a
    quiesced-restore marker still exists. The interrupted restore must be rolled
    forward (``resume=True``) so the group reaches a consistent state before any
    unrelated restore begins.
    """


@dataclass(frozen=True, slots=True)
class StoreMember:
    """One declared consistency-group store and where it lives on disk.

    ``derivable`` records whether the store may be omitted from a snapshot group
    because a release manifest proves it reconstructable. Both current members are
    non-derivable, so absence is always an integrity failure; the field exists so
    the membership declaration -- consumed by the component manifest layer -- has
    one authority rather than two.
    """

    specification: ConsistencyGroupStoreSpecification
    source_path: Path

    @property
    def store(self) -> ConsistencyGroupStore:
        """Return the runtime store identity from the shared specification."""
        return self.specification.store

    @property
    def derivable(self) -> Literal[False]:
        """Return the omission policy from the shared specification."""
        return self.specification.derivable

    @property
    def snapshot_filename(self) -> str:
        """Return the captured-copy filename for this store within a group dir."""
        return f"{self.store.value}.db"


class StoreSnapshot(BaseModel):
    """The recorded facts binding one captured store copy to its source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    store: ConsistencyGroupStore = Field(description="Which group member this is.")
    source_path: Path = Field(
        description="Absolute source store path this copy was captured from."
    )
    snapshot_filename: str = Field(
        min_length=1,
        max_length=64,
        description="Captured-copy filename within the group directory.",
    )
    digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 digest of the captured standalone database bytes.",
    )
    size_bytes: int = Field(ge=0, description="Byte length of the captured copy.")
    sqlite_schema_version: int = Field(
        ge=0,
        description="Captured store's SQLite schema cookie (PRAGMA schema_version).",
    )
    alembic_revision: str | None = Field(
        default=None,
        max_length=64,
        description="Recorded Alembic revision for the primary store, if any.",
    )


class GroupDescriptor(BaseModel):
    """The single atomic commit record for one consistency-group snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    descriptor_version: Literal["1"] = Field(
        description="Descriptor grammar version; only '1' is accepted."
    )
    group_id: str = Field(
        min_length=1,
        max_length=_GROUP_ID_MAX,
        pattern=r"^[A-Za-z0-9._-]+$",
        description="Opaque identity of this snapshot group.",
    )
    app_home: Path = Field(
        description="Absolute desktop application home the group was captured from."
    )
    created_at: AwareDatetime = Field(
        description="Timezone-aware instant the group descriptor was committed."
    )
    stores: tuple[StoreSnapshot, ...] = Field(
        min_length=1,
        description="Per-store capture facts, one per consistency-group member.",
    )


class RestoreMarker(BaseModel):
    """The durable quiesced-restore marker written before any store is touched."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    marker_version: Literal["1"] = Field(
        description="Marker grammar version; only '1' is accepted."
    )
    group_id: str = Field(
        min_length=1,
        max_length=_GROUP_ID_MAX,
        description="Group identity the interrupted restore was applying.",
    )
    app_home: Path = Field(description="Absolute application home the restore targets.")
    started_at: AwareDatetime = Field(
        description="Timezone-aware instant the restore began."
    )
    stores: tuple[ConsistencyGroupStore, ...] = Field(
        min_length=1, description="Group members the restore intends to apply."
    )


@dataclass(frozen=True, slots=True)
class RestoreOutcome:
    """The result of a completed group restore."""

    group_id: str
    restored: tuple[ConsistencyGroupStore, ...]
    resumed: bool


def consistency_group_members(state: DesktopStatePaths) -> tuple[StoreMember, ...]:
    """Return the declared consistency-group membership for one app home.

    The membership is fixed by the desktop profile's own path derivation: the
    primary database and the checkpoint database. Both are non-derivable, so both
    are mandatory. This is the single authority the snapshot, restore, and
    component-manifest layers consult so membership is declared exactly once.
    """
    return tuple(
        StoreMember(
            specification=specification,
            source_path=cast(
                "Path", getattr(state, specification.state_path_attribute)
            ),
        )
        for specification in consistency_group_specifications()
    )


def _group_dir(state: DesktopStatePaths, group_id: str) -> Path:
    return state.snapshots_dir / group_id


def descriptor_path(state: DesktopStatePaths, group_id: str) -> Path:
    """Return the committed group-descriptor path for ``group_id``."""
    return _group_dir(state, group_id) / DESCRIPTOR_NAME


def restore_marker_path(state: DesktopStatePaths) -> Path:
    """Return the quiesced-restore marker path for the app home.

    The marker is app-home global -- one restore transaction at a time -- so it
    lives at the snapshots-directory root rather than inside any group folder.
    """
    return state.snapshots_dir / RESTORE_MARKER_NAME


def _validate_group_id(group_id: str) -> str:
    if (
        not group_id
        or len(group_id) > _GROUP_ID_MAX
        or any(char in group_id for char in "/\\")
        or group_id in {".", ".."}
        or Path(group_id).name != group_id
    ):
        raise SnapshotError(
            f"snapshot group id {group_id!r} must be a single non-empty path "
            "component of bounded portable characters."
        )
    return group_id


def _resolve_state(app_home: Path) -> DesktopStatePaths:
    try:
        return derive_state_paths(app_home)
    except DesktopProfileError as exc:
        raise SnapshotError(str(exc)) from exc


def _fsync_file(handle: BinaryIO) -> None:
    """Flush a file object and force its bytes to stable storage."""
    handle.flush()
    os.fsync(handle.fileno())


def _fsync_path(path: Path) -> None:
    """Force an already-written file's bytes to stable storage.

    Used after a separate writer (SQLite's backup) has produced and closed the
    file; a writable descriptor is required because some platforms refuse to
    ``fsync`` a read-only handle.
    """
    fd = os.open(path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Force a directory entry to stable storage where the platform supports it.

    POSIX fsyncs the directory handle so a rename within it is durable. Windows
    cannot fsync a directory handle; there ``os.replace`` is itself an atomic
    metadata operation, so directory durability rides on the rename.
    """
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink_temp(path: Path) -> None:
    """Remove a temp staging file and any SQLite sidecars it may have left.

    A SQLite backup destination can leave ``-wal``/``-shm`` sidecars beside its
    temp file on an error path; cleaning the whole set keeps a failed capture from
    stranding partial WAL state in the snapshots directory.
    """
    for suffix in ("", *_SQLITE_SIDECARS):
        candidate = path.with_name(path.name + suffix)
        if candidate.exists():
            candidate.unlink()


def _digest_and_size(path: Path) -> tuple[str, int]:
    """Return the SHA-256 digest and byte length of ``path``."""
    hasher = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_DIGEST_CHUNK), b""):
            total += len(block)
            hasher.update(block)
    return hasher.hexdigest(), total


def _ensure_quiesced(path: Path) -> None:
    """Refuse a store another connection holds live or locked.

    Probes with a zero busy-timeout ``BEGIN IMMEDIATE``: a reserved or exclusive
    lock held by a live writer makes SQLite raise immediately rather than block. A
    missing file is trivially unlocked -- absence is handled separately.
    """
    if not path.is_file():
        return
    conn = sqlite3.connect(str(path), timeout=0)
    try:
        conn.execute("PRAGMA busy_timeout=0")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            raise SnapshotStoreLockedError(
                f"store {path} is live or locked; drain and stop the gateway "
                "before snapshotting or restoring the consistency group."
            ) from exc
        raise SnapshotError(f"cannot probe store {path}: {exc}") from exc
    finally:
        conn.close()


def _read_schema_facts(db_path: Path) -> tuple[int, str | None]:
    """Return (SQLite schema cookie, Alembic revision) for a captured copy.

    The schema cookie is a coherent per-store DDL revision counter carried in the
    SQLite header; the Alembic revision is present only on the primary store.
    Both are read with plain synchronous reads that never write.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            row = None
    finally:
        conn.close()
    revision = None if row is None else str(row[0])
    return schema_version, revision


def _backup_store(source: Path, destination: Path) -> None:
    """Capture ``source`` into a standalone sidecar-free copy at ``destination``.

    Reads a single consistent view through SQLite's online-backup API -- main file
    plus every committed WAL frame -- and writes a fresh database with no ``-wal``
    or ``-shm`` sidecar. The backup only reads the source, so its committed content
    is never altered; the destination is checkpointed so the captured copy is a
    single self-contained file.
    """
    try:
        src = sqlite3.connect(str(source), timeout=0)
    except sqlite3.OperationalError as exc:
        raise SnapshotError(
            f"cannot open consistency-group store {source} for capture: {exc}"
        ) from exc
    try:
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
            dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dst.close()
    finally:
        src.close()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` via temp file, fsync, and atomic rename."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}{_TEMP_SUFFIX}")
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
            _fsync_file(handle)
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def _stage_store(member: StoreMember, group_dir: Path) -> StoreSnapshot:
    """Capture one member into the group directory and record its facts."""
    if not member.source_path.is_file():
        raise SnapshotIntegrityError(
            f"consistency-group store {member.store.value} is missing at "
            f"{member.source_path}; a non-derivable member cannot be omitted."
        )
    _ensure_quiesced(member.source_path)
    final = group_dir / member.snapshot_filename
    tmp = group_dir / f"{member.snapshot_filename}.{os.getpid()}{_TEMP_SUFFIX}"
    _unlink_temp(tmp)
    try:
        _backup_store(member.source_path, tmp)
        _fsync_path(tmp)
        digest, size = _digest_and_size(tmp)
        schema_version, revision = _read_schema_facts(tmp)
        os.replace(tmp, final)
        _fsync_dir(group_dir)
    finally:
        _unlink_temp(tmp)
    return StoreSnapshot(
        store=member.store,
        source_path=member.source_path,
        snapshot_filename=member.snapshot_filename,
        digest=digest,
        size_bytes=size,
        sqlite_schema_version=schema_version,
        alembic_revision=revision,
    )


def create_snapshot(
    app_home: Path,
    group_id: str,
    *,
    now: datetime | None = None,
) -> GroupDescriptor:
    """Capture the whole consistency group under ``group_id`` and commit it.

    Every declared member is captured to a temp file, fsynced, and renamed into
    the group directory; the group is then committed by writing exactly one
    descriptor through temp-fsync-atomic-rename. Until that descriptor lands the
    snapshot is invisible to :func:`inspect_snapshot`.

    Args:
        app_home: Absolute desktop application home whose stores to capture.
        group_id: Single-component identity for the new group; must not already
            be committed.
        now: Reference instant recorded as ``created_at``; defaults to current
            UTC. Must be timezone-aware when provided.

    Returns:
        The committed :class:`GroupDescriptor`.

    Raises:
        SnapshotError: If ``group_id`` is malformed or already committed, or the
            reference instant is naive.
        SnapshotIntegrityError: If a non-derivable member store is absent.
        SnapshotStoreLockedError: If a member store is live or locked.
    """
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        raise SnapshotError("snapshot reference instant must be timezone-aware.")
    _validate_group_id(group_id)
    state = _resolve_state(app_home)
    group_dir = _group_dir(state, group_id)
    committed = group_dir / DESCRIPTOR_NAME
    if committed.exists():
        raise SnapshotError(
            f"snapshot group {group_id!r} is already committed at {committed}; "
            "choose a fresh group id."
        )
    group_dir.mkdir(parents=True, exist_ok=True)

    stores = tuple(
        _stage_store(member, group_dir) for member in consistency_group_members(state)
    )
    descriptor = GroupDescriptor(
        descriptor_version=DESCRIPTOR_VERSION,
        group_id=group_id,
        app_home=state.app_home,
        created_at=reference,
        stores=stores,
    )
    _atomic_write_bytes(
        committed,
        descriptor.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )
    return descriptor


def _read_descriptor_document(path: Path) -> GroupDescriptor:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SnapshotIntegrityError(
            f"snapshot group descriptor {path} is not committed or not accessible."
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise SnapshotIntegrityError(
            f"snapshot group descriptor {path} must be a regular file."
        )
    if info.st_size > _MAX_DESCRIPTOR_BYTES:
        raise SnapshotIntegrityError(
            f"snapshot group descriptor {path} exceeds its size bound."
        )
    try:
        document = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SnapshotIntegrityError(
            f"snapshot group descriptor {path} is not valid UTF-8 JSON."
        ) from exc
    try:
        descriptor = GroupDescriptor.model_validate(document)
    except ValidationError as exc:
        raise SnapshotIntegrityError(
            f"snapshot group descriptor {path} is malformed: "
            f"{exc.error_count()} error(s)."
        ) from exc
    if descriptor.descriptor_version != DESCRIPTOR_VERSION:
        raise SnapshotIntegrityError(
            f"snapshot group descriptor {path} has unsupported version "
            f"{descriptor.descriptor_version!r}."
        )
    return descriptor


def _verify_captured_stores(group_dir: Path, descriptor: GroupDescriptor) -> None:
    """Confirm every captured store file is present and digest-consistent."""
    for snapshot in descriptor.stores:
        captured = group_dir / snapshot.snapshot_filename
        if not captured.is_file():
            raise SnapshotIntegrityError(
                f"snapshot group {descriptor.group_id!r} is missing captured store "
                f"{snapshot.store.value} at {captured}."
            )
        digest, size = _digest_and_size(captured)
        if digest != snapshot.digest or size != snapshot.size_bytes:
            raise SnapshotIntegrityError(
                f"snapshot group {descriptor.group_id!r} captured store "
                f"{snapshot.store.value} does not match its recorded digest; the "
                "snapshot is corrupt."
            )


def inspect_snapshot(app_home: Path, group_id: str) -> GroupDescriptor:
    """Load and integrity-check a committed consistency-group snapshot.

    A group is reported only when its descriptor is committed and every captured
    store still matches the digest and size the descriptor recorded. An
    uncommitted (descriptor-absent) or corrupt group raises rather than returning
    a partial view.

    Raises:
        SnapshotIntegrityError: If the descriptor is absent, malformed, or any
            captured store is missing or digest-inconsistent.
    """
    _validate_group_id(group_id)
    state = _resolve_state(app_home)
    group_dir = _group_dir(state, group_id)
    descriptor = _read_descriptor_document(group_dir / DESCRIPTOR_NAME)
    if descriptor.group_id != group_id:
        raise SnapshotIntegrityError(
            f"snapshot group descriptor at {group_dir} declares id "
            f"{descriptor.group_id!r}, not {group_id!r}."
        )
    _verify_captured_stores(group_dir, descriptor)
    return descriptor


def list_snapshots(app_home: Path) -> tuple[str, ...]:
    """Return the ids of every committed snapshot group, sorted.

    Only groups whose descriptor is committed are listed; a directory left behind
    by an interrupted, never-committed snapshot is omitted.
    """
    state = _resolve_state(app_home)
    root = state.snapshots_dir
    if not root.is_dir():
        return ()
    committed = tuple(
        sorted(
            child.name
            for child in root.iterdir()
            if child.is_dir() and (child / DESCRIPTOR_NAME).is_file()
        )
    )
    return committed


def pending_restore(app_home: Path) -> RestoreMarker | None:
    """Return the marker of an interrupted restore, or ``None`` when quiescent.

    A returned marker is the durable, fail-closed signal that a previous restore
    did not run to completion and the consistency group may be half-applied. A
    caller must treat the live group as not-healthy until the restore is rolled
    forward.
    """
    state = _resolve_state(app_home)
    marker = restore_marker_path(state)
    if not marker.is_file():
        return None
    if marker.stat().st_size > _MAX_MARKER_BYTES:
        raise SnapshotIntegrityError(f"restore marker {marker} exceeds its size bound.")
    try:
        document = json.loads(marker.read_bytes())
        return RestoreMarker.model_validate(document)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise SnapshotIntegrityError(f"restore marker {marker} is malformed.") from exc


def _restore_store(snapshot: StoreSnapshot, group_dir: Path) -> None:
    """Restore one member from its captured copy, replacing any stale sidecars."""
    captured = group_dir / snapshot.snapshot_filename
    target = snapshot.source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    _ensure_quiesced(target)

    tmp = target.with_name(f"{target.name}.{os.getpid()}{_TEMP_SUFFIX}")
    if tmp.exists():
        tmp.unlink()
    try:
        with captured.open("rb") as source, tmp.open("xb") as handle:
            for block in iter(lambda: source.read(_DIGEST_CHUNK), b""):
                handle.write(block)
            _fsync_file(handle)
        for suffix in _SQLITE_SIDECARS:
            sidecar = target.with_name(target.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(tmp, target)
        _fsync_dir(target.parent)
    finally:
        if tmp.exists():
            tmp.unlink()

    digest, _ = _digest_and_size(target)
    if digest != snapshot.digest:
        raise SnapshotIntegrityError(
            f"restored store {snapshot.store.value} at {target} does not match the "
            "snapshot digest; the restore did not converge."
        )


def restore_snapshot(
    app_home: Path,
    group_id: str,
    *,
    resume: bool = False,
    now: datetime | None = None,
) -> RestoreOutcome:
    """Restore the whole consistency group from a committed snapshot, atomically.

    Writes a quiesced-restore marker before touching any store, restores every
    member from its verified captured copy, then clears the marker only after all
    members are restored and flushed. The marker's presence is the durable signal
    of an interrupted restore.

    If a marker from an earlier interrupted restore is present, a fresh restore is
    refused unless ``resume`` is set. Resuming re-restores every member from the
    immutable captured copies -- an idempotent roll-forward -- and clears the
    marker, so the group always converges to the committed snapshot content and no
    half-restored pair is left behind.

    Args:
        app_home: Absolute desktop application home to restore into.
        group_id: The committed group to restore from.
        resume: Roll forward an interrupted restore instead of refusing.
        now: Reference instant recorded on the marker; defaults to current UTC.

    Returns:
        A :class:`RestoreOutcome` naming the restored members.

    Raises:
        RestorePendingError: If an interrupted restore exists and ``resume`` is
            not set.
        SnapshotIntegrityError: If the snapshot is uncommitted or corrupt, or a
            restored store fails digest verification.
        SnapshotStoreLockedError: If a target store is live or locked.
    """
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        raise SnapshotError("restore reference instant must be timezone-aware.")
    state = _resolve_state(app_home)
    descriptor = inspect_snapshot(app_home, group_id)
    group_dir = _group_dir(state, group_id)

    existing = pending_restore(app_home)
    if existing is not None and not resume:
        raise RestorePendingError(
            f"an interrupted restore of group {existing.group_id!r} is pending; "
            "resume it before starting another restore."
        )
    if existing is not None and existing.group_id != group_id:
        raise RestorePendingError(
            f"cannot resume restore of group {group_id!r}: an interrupted restore of "
            f"a different group {existing.group_id!r} is pending; resume that group "
            "instead so its half-applied stores are not abandoned."
        )
    resumed = existing is not None

    # Refuse a live group before writing the marker or touching any store.
    for snapshot in descriptor.stores:
        _ensure_quiesced(snapshot.source_path)

    marker = RestoreMarker(
        marker_version=MARKER_VERSION,
        group_id=group_id,
        app_home=state.app_home,
        started_at=reference,
        stores=tuple(snapshot.store for snapshot in descriptor.stores),
    )
    marker_file = restore_marker_path(state)
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(
        marker_file, marker.model_dump_json(indent=2).encode("utf-8") + b"\n"
    )

    for snapshot in descriptor.stores:
        _restore_store(snapshot, group_dir)

    marker_file.unlink()
    _fsync_dir(marker_file.parent)
    return RestoreOutcome(
        group_id=group_id,
        restored=tuple(snapshot.store for snapshot in descriptor.stores),
        resumed=resumed,
    )
