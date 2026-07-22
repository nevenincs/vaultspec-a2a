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


# Fields excluded from every request digest, with the reason each is excluded.
# Named rather than derived: a field added later must be classified by a person.
# Deriving the set would silently fold a new field in - making previously valid
# replays conflict - and defaulting new fields out would let a behaviour change
# replay as identical. Both failures are quiet.
#
# ``stage`` and ``reservation_id`` identify the request rather than describe the
# work: a prepare and its own commit differ on both while driving one run, so
# including them would make the staged path conflict with itself.
_ALWAYS_EXCLUDED: frozenset[str] = frozenset({"stage", "reservation_id"})

# Additionally excluded when digesting a PREPARE, which carries no opening
# prompt and no tokens yet. Comparing them would make every commit differ from
# the prepare it binds to.
_PREPARE_EXCLUDED: frozenset[str] = frozenset({"message", "actor_tokens"})


def request_digest(body: RunStartRequest, *, prepared: bool) -> str:
    """Hash one canonical request shape without persisting any raw token.

    Two requests that would produce the same run share a digest; any difference
    in what the run would do produces a different one. That is what lets a
    replayed run id be answered with the original outcome when the body matches,
    and refused when it does not - a replay carrying a different prompt or preset
    is a new intention wearing an old id.

    Serialisation is canonical - keys sorted, separators fixed - so the digest
    depends on the values rather than on dictionary ordering or formatting.
    """
    excluded = set(_ALWAYS_EXCLUDED)
    if prepared:
        excluded.update(_PREPARE_EXCLUDED)
    payload = body.model_dump(mode="json", exclude=excluded)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
