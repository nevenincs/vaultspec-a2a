"""Private ownership inventory for deletion of canonical replay journals."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from ..desktop._platform_acl import harden_credential_path
from ..utils import is_single_regular_file, path_is_link_like
from ._ids import derive_idempotency_key

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

__all__ = [
    "JournalIndex",
    "closed_marker_name",
    "flush_directory",
    "is_unlinked_regular_file",
    "journal_name",
]

_STORE = (
    "CREATE TABLE store (id INTEGER PRIMARY KEY CHECK (id=1), "
    "version INTEGER NOT NULL, root TEXT NOT NULL, inventoried INTEGER NOT NULL)"
)
_JOURNALS = (
    "CREATE TABLE journals (run_id TEXT NOT NULL, scope TEXT NOT NULL, "
    "filename TEXT NOT NULL UNIQUE, PRIMARY KEY(run_id, scope))"
)


def journal_name(run_id: str, scope: str) -> str:
    return (
        derive_idempotency_key(json.dumps([run_id, scope])).removeprefix("idk:") + ".db"
    )


def closed_marker_name(run_id: str) -> str:
    return derive_idempotency_key(json.dumps([run_id])).removeprefix("idk:") + ".closed"


def flush_directory(directory: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def is_unlinked_regular_file(path: Path) -> bool:
    """Return whether *path* names one regular, singly linked, unaliased file.

    The name itself must not be a link or junction, and what it names must be a
    regular file with no second hard link. A name that cannot be inspected once
    it has passed the link test does not qualify.
    """
    if path_is_link_like(path):
        return False
    try:
        metadata = path.stat()
    except (OSError, ValueError):
        return False
    return is_single_regular_file(metadata)


class JournalIndex:
    """An agent-writable store cannot alter its service-owned cleanup inventory."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(os.path.abspath(directory))
        self._root = os.path.normcase(str(self.directory))

    def _path(self) -> Path:
        from ..control.config import settings

        root = settings.prepare_state_dir(
            settings.state_layout.authoring_calls_dir / "indexes"
        )
        if path_is_link_like(root) or not root.is_dir():
            raise ValueError("authoring index root is not a real directory")
        if os.name == "posix":
            if root.stat().st_uid != os.getuid():
                raise ValueError("authoring index must be owned by the service")
            harden_credential_path(root)
        identity = derive_idempotency_key(self._root).removeprefix("idk:")
        return root / (identity + ".db")

    def _check_existing(self, path: Path) -> None:
        if (
            path_is_link_like(path)
            or not path.is_file()
            # The exclusive publisher briefly keeps its private staging
            # hardlink; both names remain beneath the service-only root.
            or path.stat().st_nlink not in (1, 2)
        ):
            raise ValueError("authoring index must be a private regular file")

    def _publish(self, path: Path) -> None:
        if os.path.lexists(path):
            self._check_existing(path)
            return
        # Publish a complete schema exclusively. An interrupted initializer must
        # not leave an empty file that a later caller mistakes for a valid index.
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute(_STORE)
            db.execute(_JOURNALS)
            db.execute("INSERT INTO store VALUES (1, 1, ?, 0)", (self._root,))
            db.commit()
            header = db.serialize()
        descriptor, name = tempfile.mkstemp(prefix=".index-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(header)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                self._check_existing(path)
        finally:
            temporary.unlink(missing_ok=True)
        flush_directory(path.parent)

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[aiosqlite.Connection]:
        path = self._path()
        self._publish(path)
        async with aiosqlite.connect(path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT version, root, inventoried FROM store"
            ) as cur:
                owner = tuple(await cur.fetchall())
            if len(owner) != 1 or owner[0][:2] != (1, self._root):
                raise ValueError("authoring index version or ownership mismatch")
            if owner[0][2] not in (0, 1):
                raise ValueError("authoring index inventory state is invalid")
            if owner[0][2] == 0:
                await self._inventory(db)
                await db.execute("UPDATE store SET inventoried=1 WHERE id=1")
            yield db
            await db.commit()

    async def _inventory(self, db: aiosqlite.Connection) -> None:
        # This adoption pass runs once per store. The source filename is checked
        # against its single owner before it grants any deletion authority.
        for candidate in self.directory.glob("*.db"):
            try:
                if not is_unlinked_regular_file(candidate):
                    continue
                async with (
                    aiosqlite.connect(
                        candidate.as_uri() + "?mode=ro", uri=True, timeout=0
                    ) as source,
                    source.execute("SELECT version, run_id, scope FROM owner") as cur,
                ):
                    owners = tuple(await cur.fetchall())
            except (OSError, sqlite3.Error):
                # An unreadable, unindexed file proves no run ownership. It is
                # preserved; known indexed files never take this error branch.
                continue
            if (
                len(owners) != 1
                or type(owners[0][0]) is not int
                or owners[0][0] not in (1, 2)
                or not isinstance(owners[0][1], str)
                or not isinstance(owners[0][2], str)
            ):
                continue
            _version, run_id, scope = owners[0]
            if candidate.name == journal_name(run_id, scope):
                await db.execute(
                    "INSERT OR IGNORE INTO journals VALUES (?, ?, ?)",
                    (run_id, scope, candidate.name),
                )

    async def register(self, run_id: str, scope: str) -> None:
        marker = self.directory / closed_marker_name(run_id)
        async with self._transaction() as db:
            if os.path.lexists(marker):
                raise ValueError("authoring run has been retired; replay is closed")
            await db.execute(
                "INSERT OR IGNORE INTO journals VALUES (?, ?, ?)",
                (run_id, scope, journal_name(run_id, scope)),
            )
            if os.path.lexists(marker):
                raise ValueError("authoring run has been retired; replay is closed")

    async def scopes(self, run_id: str) -> tuple[str, ...]:
        async with (
            self._transaction() as db,
            db.execute(
                "SELECT scope, filename FROM journals WHERE run_id=?", (run_id,)
            ) as cur,
        ):
            rows = tuple(await cur.fetchall())
        for scope, filename in rows:
            if not isinstance(scope, str) or filename != journal_name(run_id, scope):
                raise ValueError("authoring index filename ownership mismatch")
        return tuple(scope for scope, _filename in rows)

    async def forget(self, run_id: str) -> None:
        async with self._transaction() as db:
            await db.execute("DELETE FROM journals WHERE run_id=?", (run_id,))
