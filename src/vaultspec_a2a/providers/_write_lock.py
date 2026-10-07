"""Per-path serialization for the writes an agent lane makes to the workspace.

Two provider writes can corrupt each other only when they name the SAME file:
each opens its own confined descriptor, truncates it and writes the payload, so
two writers of one path interleave while writers of different paths are
independent. The lock is therefore keyed by the target file, and a write waits
only on the file it is about to replace.

The lock is carried on the run's :class:`~._acp_types.AcpModelConfig` rather
than read from module state at the point of use, so every writer names the lock
it acquires and a test holds the same object the handler will.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ProviderWriteLock", "provider_write_lock"]


@dataclass(slots=True)
class _PathEntry:
    """One file's lock and the number of writers that still need it."""

    lock: asyncio.Lock
    users: int = 0


def _write_lock_key(path: Path) -> str:
    """Return the one spelling two writers of a file agree on.

    A write arrives already sandbox-resolved, but the key is minted here anyway:
    the lock is only as good as the agreement between two spellings of one file,
    and that agreement cannot depend on each caller having normalized first.
    Symlinks are collapsed, and the result is case-normalized the way the
    platform's own path convention is - folded on Windows, unchanged elsewhere,
    where folding would merge distinct files.

    Raises:
        ValueError: If *path* is relative. It would otherwise be resolved
            against the serving process's working directory, keying one agent's
            write on a file outside the run's workspace entirely.
    """
    if not path.is_absolute():
        msg = f"a provider write lock keys an absolute file path, got: {str(path)!r}"
        raise ValueError(msg)
    return os.path.normcase(os.path.realpath(path))


class ProviderWriteLock:
    """Serialize provider writes by target file, holding no lock when idle.

    Entries are created on demand and dropped when their last writer leaves. A
    long run writes thousands of files, and a registry that only grew would
    retain one lock per file written for the life of the process.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _PathEntry] = {}

    @asynccontextmanager
    async def hold(self, path: Path) -> AsyncGenerator[None]:
        """Hold the lock for *path* for the duration of the block."""
        key = _write_lock_key(path)
        entry = self._claim(key)
        try:
            async with entry.lock:
                yield
        finally:
            self._release(key, entry)

    def _claim(self, key: str) -> _PathEntry:
        """Register one writer against *key*'s lock, creating it if needed.

        INVARIANT: no ``await`` between the lookup, the insert and the count.
        The event loop cannot interleave another writer inside a coroutine that
        never suspends, which is what lets a plain dict carry the registry with
        no lock of its own. Adding an ``await`` here would let two writers each
        create an entry and acquire a different lock for one file.
        """
        entry = self._entries.get(key)
        if entry is None:
            entry = _PathEntry(lock=asyncio.Lock())
            self._entries[key] = entry
        entry.users += 1
        return entry

    def _release(self, key: str, entry: _PathEntry) -> None:
        """Drop one writer, and the entry once no writer is left.

        The identity check keeps a late release from evicting a successor entry:
        the key may have been re-created after this entry was dropped.
        """
        entry.users -= 1
        if entry.users <= 0 and self._entries.get(key) is entry:
            del self._entries[key]


# One registry per process. The reach has to match the sharing: the roles of a
# team run are separate model instances over ONE workspace, so a registry per
# model or per session would let two roles replace one file at the same time.
_PROCESS_WRITE_LOCK = ProviderWriteLock()


def provider_write_lock() -> ProviderWriteLock:
    """Return the write lock a provider config takes when none is supplied."""
    return _PROCESS_WRITE_LOCK
