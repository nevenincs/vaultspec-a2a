"""Durable replay identity and lifecycle references for bridged tool calls.

Only input fingerprints and engine identifiers are retained. Document content,
responses and actor credentials remain with their existing owners.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import tempfile
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import TYPE_CHECKING, cast
from weakref import WeakValueDictionary

import aiosqlite

from ..desktop._platform_acl import harden_credential_path
from ..utils import path_is_link_like
from ._ids import derive_idempotency_key
from ._journal_index import (
    JournalIndex,
    closed_marker_name,
    flush_directory,
    is_unlinked_regular_file,
    journal_name,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

__all__ = [
    "ToolCallJournal",
    "private_tool_call_journal_path",
    "retire_run_tool_calls",
    "tool_call_journal_directories",
    "tool_call_journal_path",
]

_OWNER_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS owner ("
    "id INTEGER PRIMARY KEY CHECK (id = 1), "
    "version INTEGER NOT NULL, run_id TEXT NOT NULL, scope TEXT NOT NULL)"
)
_CALLS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS calls ("
    "call_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
    "owned_fields TEXT NOT NULL, key TEXT NOT NULL, "
    "completed INTEGER NOT NULL DEFAULT 0)"
)
_LIFECYCLE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS lifecycle ("
    "id INTEGER PRIMARY KEY CHECK (id = 1), refs TEXT NOT NULL)"
)

_JOURNAL_LOCKS: WeakValueDictionary[Path, asyncio.Lock] = WeakValueDictionary()


def _journal_lock(path: Path) -> asyncio.Lock:
    return _JOURNAL_LOCKS.setdefault(Path(os.path.abspath(path)), asyncio.Lock())


def private_tool_call_journal_path(run_id: str, call_scope: str) -> Path:
    """Keep replay authority private even when provider identity is isolated."""
    from ..control.config import settings

    directory = settings.prepare_state_dir(settings.state_layout.authoring_calls_dir)
    if path_is_link_like(directory) or not directory.is_dir():
        raise ValueError("authoring journal directory is not a real directory")
    identity = derive_idempotency_key(json.dumps([run_id, call_scope]))
    path = directory / (identity.removeprefix("idk:") + ".db")
    workspace = settings.workspace_root
    if workspace is not None and not os.path.lexists(path):
        legacy = workspace / ".vaultspec-authoring-calls"
        if os.path.lexists(legacy / path.name) or os.path.lexists(
            _closed_run_marker(legacy, run_id)
        ):
            raise ValueError(
                "legacy shared replay state cannot authorize a private run"
            )
    if os.path.lexists(path) and not is_unlinked_regular_file(path):
        raise ValueError("authoring journal must be an unlinked regular file")
    if os.name == "posix":
        metadata = directory.stat()
        if metadata.st_uid != os.getuid():
            raise ValueError("private authoring journal must be owned by the service")
        harden_credential_path(directory)
    return path


def tool_call_journal_path(run_id: str, call_scope: str) -> Path:
    """Anchor bridge subprocess state in the parent's configured state home."""
    from ..control.config import settings

    if settings.provider_identity_launcher is None:
        directory = settings.prepare_state_dir(
            settings.state_layout.authoring_calls_dir
        )
    else:
        # Provider descendants cannot traverse the service's private state home.
        # Share only this credential-free store through their existing workspace.
        workspace = settings.workspace_root
        gid = settings.provider_agent_gid
        getuid = getattr(os, "getuid", None)
        chown = getattr(os, "chown", None)
        if (
            workspace is None
            or gid is None
            or not callable(getuid)
            or not callable(chown)
        ):
            raise ValueError(
                "isolated authoring bridge requires a POSIX workspace identity"
            )
        directory = settings.prepare_state_dir(workspace / ".vaultspec-authoring-calls")
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != getuid():
            raise ValueError("authoring journal directory must be owned by the service")
        chown(directory, -1, gid, follow_symlinks=False)
        directory.chmod(0o2770, follow_symlinks=False)
    identity = derive_idempotency_key(json.dumps([run_id, call_scope]))
    path = directory / (identity.removeprefix("idk:") + ".db")
    if settings.provider_identity_launcher is not None and not os.path.lexists(
        _closed_run_marker(directory, run_id)
    ):
        # SQLite's default file mode omits group write. Create the empty file
        # as the service before handing it to the isolated bridge, so both
        # identities can transact and the service can retire it later.
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o660)
        except FileExistsError:
            if not is_unlinked_regular_file(path):
                raise ValueError(
                    "authoring journal must be an unlinked regular file"
                ) from None
        else:
            try:
                os.fchmod(descriptor, 0o660)
            finally:
                os.close(descriptor)
    return path


def _closed_run_marker(directory: Path, run_id: str) -> Path:
    return directory / closed_marker_name(run_id)


def tool_call_journal_directories() -> tuple[Path, ...]:
    """Return existing storage locations without creating or sharing them."""
    from ..control.config import settings

    directories = [settings.state_layout.authoring_calls_dir]
    if settings.workspace_root is not None:
        directories.append(settings.workspace_root / ".vaultspec-authoring-calls")
    return tuple(directories)


async def retire_run_tool_calls(run_id: str, *, directory: Path | None = None) -> None:
    """Close replay only after the control plane durably elected run deletion.

    Keep the small run marker and closed owner headers. Removing them would
    allow a stale subprocess to create a fresh journal for the deleted run.
    """
    directories = (
        (directory,) if directory is not None else tool_call_journal_directories()
    )
    for directory in directories:
        if not os.path.lexists(directory):
            continue
        if path_is_link_like(directory) or not directory.is_dir():
            raise ValueError("authoring journal directory is not a real directory")
        marker = _closed_run_marker(directory, run_id)
        try:
            descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
        except FileExistsError:
            pass
        else:
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            flush_directory(directory)
        failures: list[Exception] = []
        index = JournalIndex(directory)
        for scope in await index.scopes(run_id):
            path = directory / journal_name(run_id, scope)
            try:
                await ToolCallJournal(path, run_id, scope).retire(indexed=True)
            except (OSError, ValueError, sqlite3.Error) as exc:
                failures.append(exc)
        if failures:
            raise failures[0]
        await index.forget(run_id)


class ToolCallJournal:
    """Keep the prepared identity before delivery, including ambiguous failures."""

    def __init__(self, path: Path, run_id: str, call_scope: str) -> None:
        self.path = path
        self._owner = (run_id, call_scope)

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[aiosqlite.Connection]:
        # Close admission before waiting for an existing transaction. Retirement
        # uses this same lock, so Windows never replaces our own open SQLite file.
        if os.path.lexists(_closed_run_marker(self.path.parent, self._owner[0])):
            raise ValueError("authoring run has been retired; replay is closed")
        async with _journal_lock(self.path), self._locked_transaction() as db:
            yield db

    @asynccontextmanager
    async def _locked_transaction(self) -> AsyncGenerator[aiosqlite.Connection]:
        marker = _closed_run_marker(self.path.parent, self._owner[0])
        if os.path.lexists(marker):
            raise ValueError("authoring run has been retired; replay is closed")
        if self.path.name == journal_name(*self._owner):
            await JournalIndex(self.path.parent).register(*self._owner)
        if os.path.lexists(marker):
            raise ValueError("authoring run has been retired; replay is closed")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            if os.path.lexists(marker):
                raise ValueError("authoring run has been retired; replay is closed")
            await db.execute(_OWNER_SCHEMA)
            await db.execute(
                "INSERT OR IGNORE INTO owner (id, version, run_id, scope) "
                "VALUES (1, 1, ?, ?)",
                self._owner,
            )
            async with db.execute("SELECT version, run_id, scope FROM owner") as cursor:
                owner = await cursor.fetchone()
            if owner != (1, *self._owner):
                raise ValueError("tool call journal version or ownership mismatch")
            await db.execute(_CALLS_SCHEMA)
            await db.execute(_LIFECYCLE_SCHEMA)
            yield db
            if os.path.lexists(marker):
                raise ValueError("authoring run has been retired; replay is closed")
            await db.commit()

    async def retire(self, *, indexed: bool = False) -> None:
        async with _journal_lock(self.path):
            await self._retire_closed(indexed=indexed)

    async def _retire_closed(self, *, indexed: bool) -> None:
        if not os.path.lexists(_closed_run_marker(self.path.parent, self._owner[0])):
            raise ValueError("authoring run must be closed before journal retirement")
        if indexed:
            if self.path.name != journal_name(*self._owner):
                raise ValueError("authoring journal filename ownership mismatch")
            if os.path.lexists(self.path) and not (
                path_is_link_like(self.path) or self.path.is_file()
            ):
                raise ValueError("authoring journal entry is not a file")
        else:
            if not is_unlinked_regular_file(self.path):
                raise ValueError("authoring journal must be an unlinked regular file")
            async with (
                aiosqlite.connect(self.path.as_uri() + "?mode=ro", uri=True) as db,
                db.execute("SELECT version, run_id, scope FROM owner") as cursor,
            ):
                owner = await cursor.fetchone()
            if owner not in ((1, *self._owner), (2, *self._owner)):
                raise ValueError("tool call journal version or ownership mismatch")

        # Older isolated bridges created group-readable files that the service
        # cannot write. After closing replay, replace the owned file atomically
        # with its empty closed header instead of changing that file's owner.
        # Serialize the small closed database in memory. Keep the exclusive
        # descriptor through the write instead of reopening a shared pathname.
        with closing(sqlite3.connect(":memory:")) as closed:
            for schema in (_OWNER_SCHEMA, _CALLS_SCHEMA, _LIFECYCLE_SCHEMA):
                closed.execute(schema)
            # Earlier bridge binaries refuse an unknown owner version too.
            closed.execute(
                "INSERT INTO owner (id, version, run_id, scope) VALUES (1, 2, ?, ?)",
                self._owner,
            )
            closed.commit()
            header = closed.serialize()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".retiring-", suffix=".db", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(header)
                file.flush()
                if os.name == "posix":
                    os.fchmod(file.fileno(), 0o640)
                os.fsync(file.fileno())
                opened = os.fstat(file.fileno())
                named = temporary.stat(follow_symlinks=False)
                if opened.st_ino != named.st_ino or opened.st_dev != named.st_dev:
                    raise ValueError("authoring retirement file identity changed")
            os.replace(temporary, self.path)
            # A hot rollback journal can otherwise restore the old owner/calls
            # over the new closed header. These names belong to this same
            # closed database; unlink entries without following their targets.
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = self.path.with_name(self.path.name + suffix)
                if os.path.lexists(sidecar):
                    if not (path_is_link_like(sidecar) or sidecar.is_file()):
                        raise ValueError("authoring journal sidecar is not a file")
                    sidecar.unlink()
            flush_directory(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    async def prepare(
        self,
        call_id: str,
        fingerprint: str,
        build: Callable[
            [dict[str, str | None]],
            Awaitable[tuple[dict[str, str | None], str]],
        ],
    ) -> tuple[dict[str, str | None], str]:
        """Bind a call to its original references before any execute request."""
        async with self._transaction() as db:
            async with db.execute(
                "SELECT fingerprint, owned_fields, key, completed "
                "FROM calls WHERE call_id = ?",
                (call_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is not None:
                if row[0] != fingerprint:
                    raise ValueError(
                        "logical tool call identity reused with different input"
                    )
                if row[3] == 2:
                    raise ValueError(
                        "logical tool call was rejected; use a new identity"
                    )
                return cast("dict[str, str | None]", json.loads(row[1])), row[2]
            async with db.execute(
                "SELECT 1 FROM calls WHERE completed = 0 LIMIT 1"
            ) as cursor:
                pending = await cursor.fetchone()
            if pending is not None:
                raise ValueError(
                    "retry the pending logical tool call before a new mutation"
                )
            refs = await self._read_lifecycle(db)
            owned_fields, key = await build(refs)
            await db.execute(
                "INSERT INTO calls (call_id, fingerprint, owned_fields, key) "
                "VALUES (?, ?, ?, ?)",
                (call_id, fingerprint, json.dumps(owned_fields), key),
            )
            await self._write_lifecycle(db, refs)
            return owned_fields, key

    async def complete(
        self, call_id: str, updates: dict[str, str], *, rejected: bool = False
    ) -> None:
        """Advance lifecycle once; a late replay must not roll it backward."""
        async with self._transaction() as db:
            async with db.execute(
                "SELECT completed FROM calls WHERE call_id = ?", (call_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None or row[0]:
                return
            refs = await self._read_lifecycle(db)
            refs.update(updates)
            await self._write_lifecycle(db, refs)
            await db.execute(
                "UPDATE calls SET completed = ? WHERE call_id = ?",
                (2 if rejected else 1, call_id),
            )

    @staticmethod
    async def _read_lifecycle(db: aiosqlite.Connection) -> dict[str, str | None]:
        async with db.execute("SELECT refs FROM lifecycle WHERE id = 1") as cursor:
            row = await cursor.fetchone()
        if row is None:
            return {"changeset_id": None, "revision": None, "approval_id": None}
        return cast("dict[str, str | None]", json.loads(row[0]))

    @staticmethod
    async def _write_lifecycle(
        db: aiosqlite.Connection, refs: dict[str, str | None]
    ) -> None:
        await db.execute(
            "INSERT INTO lifecycle (id, refs) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET refs = excluded.refs",
            (json.dumps(refs),),
        )
