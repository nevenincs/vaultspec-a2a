"""Planting a filesystem link a test needs the operating system to refuse.

Two suites certify that production code refuses to follow a reparse point: the
atomic writer must not write through one planted at its temporary name, and the
credential loader must not read a secret through one. Both needed the same
thing - a link standing where a regular file is expected - and each grew its own
planter, which is how the two ended up proving DIFFERENT strengths of the same
guarantee without either call site saying so.

The strength difference is the whole reason this has one home. A symbolic link
to a FILE is the case worth proving, because a write that follows one lands on
that file's bytes and destroys them. Creating one on Windows needs
``SeCreateSymbolicLinkPrivilege`` - Developer Mode or an elevated shell - which
not every host grants, so a refusing host falls back to a directory junction:
the privilege-free reparse point. The junction still proves the refusal, but it
cannot demonstrate the destruction, because a junction cannot point at a file at
all and so has no bytes behind it to lose.

That is why the kind is RETURNED rather than swallowed. A weaker host's pass
must never be mistakable for the strong one, so the caller names the planted
kind in its assertion message and a failure report says which guarantee was
actually under test.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["plant_link_to_file"]

JUNCTION_TARGET_NAME = "junction-target"
"""Directory the junction fallback plants beside the link and points at.

A junction resolves only to a directory, so the fallback cannot aim at the
caller's file target and creates this stand-in instead.
"""


def plant_link_to_file(link: Path, file_target: Path) -> str:
    """Plant the strongest link this host can create at *link*; name its kind.

    Returns ``"symlink"`` when the host granted a real symbolic link to
    *file_target* - the arm with teeth, where following the link reaches that
    file's bytes - and ``"junction"`` when it refused and a directory junction
    was planted instead. The junction points at a stand-in directory beside the
    link rather than at *file_target*, which is exactly why the two arms are not
    interchangeable and why callers must report which one ran.

    Raises ``OSError`` if neither can be planted, so a host that can produce no
    reparse point fails loudly rather than certifying a refusal that was never
    asked for.
    """
    try:
        os.symlink(file_target, link)
    except OSError:
        junction_target = link.parent / JUNCTION_TARGET_NAME
        junction_target.mkdir(exist_ok=True)
        interpreter = os.environ.get("COMSPEC", "cmd.exe")
        completed = subprocess.run(
            [interpreter, "/c", "mklink", "/J", str(link), str(junction_target)],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not link.is_junction():
            raise OSError(
                f"could not plant a link: {completed.stderr.strip()}"
            ) from None
        return "junction"
    return "symlink"
