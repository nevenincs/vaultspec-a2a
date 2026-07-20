"""Bounded run-start request identity and per-run single-flight ordering."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

    from .schemas.gateway import RunStartRequest

__all__ = ["commit_singleflight", "request_digest"]


@dataclass(slots=True)
class _CommitLockEntry:
    lock: asyncio.Lock
    users: int = 0


class _CommitSingleFlight:
    """Self-cleaning per-identity serialization for commit/release ordering."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._entries: dict[str, _CommitLockEntry] = {}

    @asynccontextmanager
    async def hold(self, identity: str) -> AsyncIterator[None]:
        async with self._guard:
            entry = self._entries.get(identity)
            if entry is None:
                entry = _CommitLockEntry(lock=asyncio.Lock())
                self._entries[identity] = entry
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._guard:
                entry.users -= 1
                if entry.users == 0:
                    self._entries.pop(identity, None)


def commit_singleflight(app: FastAPI) -> _CommitSingleFlight:
    """Return the process-wide self-cleaning commit/release stripe map."""
    singleflight = getattr(app.state, "run_commit_singleflight", None)
    if singleflight is None:
        singleflight = _CommitSingleFlight()
        app.state.run_commit_singleflight = singleflight
    return singleflight


def request_digest(body: RunStartRequest, *, prepared: bool) -> str:
    """Hash one canonical request shape without persisting any raw token."""
    excluded = {"stage", "reservation_id"}
    if prepared:
        excluded.update({"message", "actor_tokens"})
    payload = body.model_dump(mode="json", exclude=excluded)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
