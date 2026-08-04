"""One audited write-and-rename, so a failed publication leaves nothing behind.

Publishing a record by writing a sibling temporary file and renaming it over the
target is the right shape: a concurrent reader never observes a half-written
file, because the rename is atomic.  The failure path is where the shape usually
goes wrong.  If anything between creating the temporary file and completing the
rename raises - a crash, a full disk, a denied permission - the temporary file
survives, and nothing ever collects it.  This service accumulated exactly that:
an orphaned temporary sitting beside a discovery record for six days, left by a
publication that never completed.

This module is the audited version and the only copy of the pattern: it always
fsyncs before the rename so the bytes are durable, always retries the rename over
a bounded contention window, and always removes the temporary file when the
publication does not complete - including when the interruption is a
``KeyboardInterrupt`` or a ``SystemExit`` rather than an error.  Service
discovery, the process registry, the runtime singleton, and the Gemini OAuth
refresh all publish through it.

It lives under ``utils`` rather than beside its first callers in ``lifecycle``
for a reason worth stating, because it used to live there and the move removed a
documented exception.  Python has no way to import a leaf without executing its
package, so importing this from ``lifecycle`` executed the whole lifecycle
package - the process registry, service discovery, and the configuration they
pull - and the Gemini OAuth refresh, whose import latency sits on a coding
agent's tool-discovery window, kept its own copy of the loop rather than pay
that.  Measured, the cost was +27 modules and ~62ms; from ``utils``, which that
provider leaf already loads in full, it is +1 module and unmeasurable.  A home
nothing can reach is not a canonical home.

ONE writer elsewhere still keeps its own copy, for a reason this cannot solve by
moving: the desktop worker interprocess-communication mint has to apply an
owner-restricting access-control list to the temporary file *between* the fsync
and the rename, and this deliberately offers no seam there.  That is the
documented exception, not drift - and any second copy without a reason of its own
belongs here instead.
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["REPLACE_RETRY_SECONDS", "atomic_write_text"]

REPLACE_RETRY_SECONDS = 2.0
"""How long to ride out a transient Windows sharing violation on the rename.

``os.replace`` is atomic, but on Windows a reader holding the target open can
briefly deny it.  Retrying over a short window turns a spurious failure into a
successful publication; the operation stays all-or-nothing either way.
"""


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    retry_seconds: float = REPLACE_RETRY_SECONDS,
    mode: int | None = None,
    newline: str | None = "",
) -> None:
    """Publish *text* at *path* atomically, leaving no temporary file behind.

        Writes a sibling temporary file, flushes it to disk, then renames it over
        *path*.  The temporary file is removed if any stage fails, so an interrupted
        publication leaves the filesystem as it found it rather than accumulating
        residue nothing collects.

        The temporary name carries the writing process id so two processes
        publishing to the same target cannot collide on the temporary itself.

        Args:
            path: Destination to publish atomically.
            text: Content to write.
            encoding: Text encoding for the temporary file.
            retry_seconds: How long to ride out a transient rename denial.  Zero
                attempts the rename exactly once.
            mode: POSIX permission bits to create the temporary file with.  Pass
                this for a credential-bearing record so the bytes are never briefly
                world-readable between creation and rename; omitting it takes the
                process umask.  Ignored on Windows, where access is governed by the
                parent directory's access-control list rather than mode bits.
            newline: Line-ending translation for the temporary file, as ``open``
                takes it.  The default writes ``
    `` through untranslated, which is
                what a record this service both writes and reads wants.  Pass
                ``None`` to take the platform translation instead - only meaningful
                for a file CO-OWNED by another program, where matching what that
                program expects to find outranks this service's own preference.
                Ignored when *mode* is set, since that path writes bytes directly.

        Raises:
            OSError: If the write or the rename fails; the temporary file is removed
                before the error propagates.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        if mode is None:
            with open(tmp, "w", encoding=encoding, newline=newline) as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
            try:
                os.write(descriptor, text.encode(encoding))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _replace_with_retry(tmp, path, retry_seconds=retry_seconds)
    except BaseException:
        # Includes KeyboardInterrupt and SystemExit: an interrupted publication
        # must not be the one case that leaves residue behind.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def _replace_with_retry(tmp: Path, path: Path, *, retry_seconds: float) -> None:
    """Rename *tmp* over *path*, riding out a transient sharing violation."""
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
