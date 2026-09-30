"""One advisory file lock, so two processes can agree on who holds a resource.

The operating-system primitive differs by platform (``msvcrt.locking`` on Windows,
``fcntl.flock`` elsewhere) and the lock is taken on byte zero of an open
descriptor, which the kernel releases when the holder exits - crash included.
That shape had two copies in this service: the runtime singleton's non-blocking
claim on an application home, and a provider's bounded wait for another run's
credential. The primitive is the same in both; only the waiting policy differs, so
the primitive lives here once and each caller states its own policy.

It lives under ``utils`` rather than beside either caller for the reason
``atomic_write`` does: a provider leaf must be able to import it without
executing the lifecycle package.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "held_exclusive_lock",
    "open_lock_file",
    "release_lock",
    "try_lock",
]


def open_lock_file(path: Path) -> int:
    """Open (creating if needed) the owner-only file a lock is taken on."""
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)


def try_lock(fd: int) -> bool:
    """Take a non-blocking exclusive lock on byte zero; ``True`` when granted."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def release_lock(fd: int) -> None:
    """Release the byte-zero lock. POSIX ``flock`` also releases on close."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def held_exclusive_lock(
    path: Path, *, timeout_seconds: float, poll_seconds: float = 0.05
) -> Iterator[None]:
    """Hold the lock at *path*, or raise ``TimeoutError`` naming the wait.

    Polled rather than blocking on the OS call: the Windows and POSIX primitives
    disagree about what a blocking acquisition does to a process that dies
    holding one, and a bounded wait that gives up loudly is preferable to a
    caller that can hang. A caller with no use for waiting takes the descriptor
    itself and calls :func:`try_lock` once.
    """
    fd = open_lock_file(path)
    deadline = time.monotonic() + timeout_seconds
    try:
        while not try_lock(fd):
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"another process held the lock at {path} for "
                    f"{timeout_seconds:.1f}s"
                )
            time.sleep(poll_seconds)
        yield
    finally:
        release_lock(fd)
        os.close(fd)
