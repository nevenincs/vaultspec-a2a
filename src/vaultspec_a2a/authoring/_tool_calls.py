"""Durable replay identity and lifecycle references for bridged tool calls.

Only input fingerprints and engine identifiers are retained. Document content,
responses and actor credentials remain with their existing owners.
"""

from __future__ import annotations

import json
import os
import stat
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import aiosqlite

from ._ids import derive_idempotency_key

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable
    from pathlib import Path


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
    return directory / (identity.removeprefix("idk:") + ".db")


class ToolCallJournal:
    """Keep the prepared identity before delivery, including ambiguous failures."""

    def __init__(self, path: Path, run_id: str, call_scope: str) -> None:
        self.path = path
        self._owner = (run_id, call_scope)

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "CREATE TABLE IF NOT EXISTS owner ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), "
                "version INTEGER NOT NULL, run_id TEXT NOT NULL, scope TEXT NOT NULL)"
            )
            await db.execute(
                "INSERT OR IGNORE INTO owner (id, version, run_id, scope) "
                "VALUES (1, 1, ?, ?)",
                self._owner,
            )
            async with db.execute("SELECT version, run_id, scope FROM owner") as cursor:
                owner = await cursor.fetchone()
            if owner != (1, *self._owner):
                raise ValueError("tool call journal version or ownership mismatch")
            await db.execute(
                "CREATE TABLE IF NOT EXISTS calls ("
                "call_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
                "owned_fields TEXT NOT NULL, key TEXT NOT NULL, "
                "completed INTEGER NOT NULL DEFAULT 0)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS lifecycle ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), refs TEXT NOT NULL)"
            )
            yield db
            await db.commit()

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
