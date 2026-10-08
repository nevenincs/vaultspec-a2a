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
fsyncs before the rename so the bytes are durable, always retries a denied rename
over a bounded contention window AND from a source the denier has never seen, and
always removes the temporary file when the publication does not complete -
including when the interruption is a ``KeyboardInterrupt`` or a ``SystemExit``
rather than an error.  And it never opens a temporary that is a link, on either of
its two write paths, so a temporary name an attacker can predict cannot be used
to redirect a write elsewhere.  Service discovery, the process registry, and the
runtime singleton OAuth refresh all publish through it.

It lives under ``utils`` rather than beside its first callers in ``lifecycle``
for a reason worth stating, because it used to live there and the move removed a
documented exception.  Python has no way to import a leaf without executing its
package, so importing this from ``lifecycle`` executed the whole lifecycle
package - the process registry, service discovery, and the configuration they
pull, whose import latency can sit on a coding
agent's tool-discovery window, kept its own copy of the loop rather than pay
that.  Measured, the cost was +27 modules and ~62ms; from ``utils``, which that
provider leaf already loads in full, it is +1 module and unmeasurable.  A home
nothing can reach is not a canonical home.

The desktop worker interprocess-communication mint publishes here too.  It kept
its own copy of this loop for as long as it had nowhere to say the one thing it
needs: its owner-restriction has to land on the temporary file *between* the
fsync and the rename, and on Windows that restriction is a discretionary
access-control list rather than permission bits, which no integer parameter can
carry.  The hardening callable is that seam.  There is now no second copy of this
pattern, and a new one would belong here instead.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack

from ._file_checks import path_is_link_like

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["atomic_write_text"]

REPLACE_RETRY_SECONDS = 2.0
"""How long to ride out a transient Windows sharing violation on the rename.

``os.replace`` is atomic, but on Windows an opener holding either end of it can
deny it.  Retrying over a short window turns a spurious failure into a
successful publication; the operation stays all-or-nothing either way.

This budget is time this process spends WAITING between attempts, not elapsed
wall-clock time.  The distinction is not academic: a denied rename on a volume
with a filesystem filter driver attached does not return promptly, and a single
call measured at over twenty seconds inside the kernel.  Charged against the
wall clock, one such call spends the whole budget before a second attempt is
ever made, and the publication fails having retried exactly once - which is how
a two-second window still produced the intermittent ``WinError 5``.
"""

_REPLACE_FIRST_PAUSE = 0.001
_REPLACE_MAX_PAUSE = 0.05
"""Growth bounds for the pause between rename attempts.

A denial usually clears within a few milliseconds, so the first pauses are short
and the budget buys many of them; the cap keeps a long denial from turning into
one idle wait that outlasts the contention it was waiting on.
"""

_BYTE_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
"""Descriptor flags for the write path that carries explicit permission bits.

``O_BINARY`` is not redundant despite the write going through a descriptor:
Windows opens a descriptor in text mode by default and would expand every
newline, so without it this path would not write the bytes it was given.  The
refusal to follow a link is deliberately NOT here - it belongs to the opener
both write paths share, so the two cannot drift into different postures again.
"""


def _open_refusing_a_link(
    path: str | os.PathLike[str], flags: int, mode: int = 0o666
) -> int:
    """Open *path* for writing, refusing it if it is a link.

    The first attempt's temporary name is predictable - the target's name plus
    the writing process id - so anything able to create a file beside the target
    can plant a link there first and have the write land on that link's target
    instead.  A retry's name is unguessable, which narrows the window but does not
    close it: whatever can create a file beside the target can also observe one
    appear, so the refusal applies to every source either path opens.  A
    credential written through such a link is disclosed to whoever chose it, and
    a record written through one silently destroys an unrelated file.

    Two mechanisms, because neither platform is covered by one.  ``O_NOFOLLOW``
    refuses atomically inside the open itself and DOES NOT EXIST ON WINDOWS, so
    the path is inspected first as well: that inspection is what every Windows
    host actually has, and a racer could still swap the path between the
    inspection and the open, which is the gap ``O_NOFOLLOW`` closes where it
    exists.  Both are applied and neither is sufficient alone.

    This is the only place either write path opens its temporary file.
    """
    if path_is_link_like(Path(path)):
        raise OSError(f"refusing to write through a link planted at {path}")
    return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), mode)


class _AtomicWriteOptions(TypedDict, total=False):
    encoding: str
    retry_seconds: float
    mode: int | None
    harden: Callable[[Path], None] | None
    newline: str | None


def atomic_write_text(
    path: Path, text: str, **options: Unpack[_AtomicWriteOptions]
) -> None:
    """Publish *text* at *path* atomically, leaving no temporary file behind.

    Writes a sibling temporary file, flushes it to disk, then renames it over
    *path*.  The temporary file is removed if any stage fails, so an interrupted
    publication leaves the filesystem as it found it rather than accumulating
    residue nothing collects.

    The temporary name carries the writing process id so two processes
    publishing to the same target cannot collide on the temporary itself.  A
    RETRY after a denied rename claims a fresh randomly named source rather than
    re-offering the one that was just refused; see :func:`_temporary_for` for why
    the source, not the wait, is the variable that matters.  Each attempt writes,
    fsyncs and hardens its own source, so *harden* runs once per attempt.

    The first attempt's name is therefore predictable, so NEITHER write path will
    open a temporary that is a link: one planted there would redirect the write -
    of a credential, or over an unrelated file - to a place the writer never
    chose.  The refusal is atomic where the platform offers it and a
    pre-open inspection where it does not, and it does not depend on which
    arguments were passed.

    Args:
        path: Destination to publish atomically.
        text: Content to write.
        encoding: Text encoding for the temporary file.
        retry_seconds: How long to WAIT, in total, across repeated attempts at a
            transient rename denial.  Time spent inside a slow attempt is not
            charged against it, so zero still attempts the rename exactly once.
            Only a denied RENAME is retried; a failure before it is the answer.
        mode: POSIX permission bits to create the temporary file with.  Pass
            this for a credential-bearing record so the bytes are never briefly
            world-readable between creation and rename; omitting it takes the
            process umask.  Ignored on Windows, where access is governed by the
            parent directory's access-control list rather than mode bits.  This
            path writes without line-ending translation, so the bytes land
            exactly as given.
        harden: Applied to each attempt's temporary file once its bytes are
            durable and before that attempt's rename, so the published file is
            already restricted at the instant it becomes reachable under its real
            name.  It exists
            because owner-restriction is not always an integer: on Windows it
            is a discretionary access-control list, which *mode* cannot carry.
            Raising from here fails the publication and removes the temporary,
            so a file that could not be protected is never published.
        newline: Line-ending translation for the temporary file, as ``open``
            takes it.  The default writes a line feed through untranslated,
            which is what a record this service both writes and reads wants.
            Pass ``None`` to take the platform translation instead - only
            meaningful for a file CO-OWNED by another program, where matching
            what that program expects to find outranks this service's own
            preference.  Ignored when *mode* is set, since that path writes
            bytes directly.

    Raises:
        OSError: If the temporary path is a link or cannot be inspected, or the
            write or the rename fails; the temporary file is removed before the
            error propagates.
    """
    encoding = options.get("encoding", "utf-8")
    retry_seconds = options.get("retry_seconds", REPLACE_RETRY_SECONDS)
    mode = options.get("mode")
    harden = options.get("harden")
    newline = options.get("newline", "")
    waited = 0.0
    pause = _REPLACE_FIRST_PAUSE
    attempt = 0
    while True:
        tmp = _temporary_for(path, attempt)
        try:
            if mode is None:
                with open(
                    tmp,
                    "w",
                    encoding=encoding,
                    newline=newline,
                    opener=_open_refusing_a_link,
                ) as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
            else:
                descriptor = _open_refusing_a_link(tmp, _BYTE_WRITE_FLAGS, mode)
                try:
                    os.write(descriptor, text.encode(encoding))
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if harden is not None:
                harden(tmp)
        except BaseException:
            # Includes KeyboardInterrupt and SystemExit: an interrupted
            # publication must not be the one case that leaves residue behind.
            # A failure on THIS side of the rename is the caller's answer as it
            # stands; only a denied rename is retried.
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            if waited >= retry_seconds:
                raise
            slept = min(pause, retry_seconds - waited)
            time.sleep(slept)
            waited += slept
            pause = min(pause * 2, _REPLACE_MAX_PAUSE)
            attempt += 1
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise


def _temporary_for(path: Path, attempt: int) -> Path:
    """Name the temporary file for publication *attempt* of *path*.

    The first attempt uses the stable ``{name}.{pid}.tmp``: the process id is
    what keeps two publishers to the same target from colliding on the temporary
    itself, and it is the name a test can plant a link at to prove the link
    refusal is real.

    Every RETRY claims a brand-new randomly named source instead, and that is the
    load-bearing part.  On Windows a rename is a delete-class operation on its
    SOURCE, so any other opener holding that file without delete sharing denies
    it; what remains after this service's own such openers were fixed is a
    filesystem filter driver that samples a brand-new file and latches onto that
    exact one.  Retrying the rename from the same source keeps asking the same
    holder about the same file, which is why a longer budget never helped - the
    wait was never the variable.  A source the holder has never seen is.
    """
    if attempt == 0:
        return path.with_name(f"{path.name}.{os.getpid()}.tmp")
    return path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
