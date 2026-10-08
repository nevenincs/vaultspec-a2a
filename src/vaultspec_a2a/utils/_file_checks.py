"""The filesystem refusals every local secret, journal and state file shares.

"Is this name a link?", "is this a regular file with exactly one name?" and "is
this a real directory?" are asked before this product trusts, hardens,
publishes or reads a file or directory it owns. They live under ``utils``
rather than beside the owner-restriction primitives in ``desktop`` because the
audited atomic writer, which is a ``utils`` module and cannot import
``desktop``, asks the first question too; a home the writer could not reach
would leave it holding its own copy.
"""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import os
    from pathlib import Path

__all__ = ["is_real_directory", "is_single_regular_file", "path_is_link_like"]


def path_is_link_like(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows junction.

    Both are asked of the name itself, without following it, and neither answer
    implies the other: a junction is not a symbolic link to ``is_symlink``. An
    absent path is not link-like, while a name that cannot be inspected for any
    other reason raises rather than answering that it is not a link.
    """
    return path.is_symlink() or path.is_junction()


def is_real_directory(path: Path) -> bool:
    """Return whether *path* names a directory itself, not a link to one.

    A symlink or junction to a directory answers ``is_dir`` as true, which is
    exactly the aliasing a caller that owns the directory refuses. An absent
    path, or a name that is not a directory, is not a real directory.
    """
    return not path_is_link_like(path) and path.is_dir()


def is_single_regular_file(metadata: os.stat_result) -> bool:
    """Return whether *metadata* describes a regular file with exactly one link.

    A directory, device or FIFO is never file content to trust, and a second
    hard link is a second name for the same bytes that some other directory
    entry, possibly one another principal controls, can reach or alter. The
    caller chooses where *metadata* comes from - a name, followed or not, or an
    open descriptor - because that choice is what binds the answer to the
    object the caller goes on to use.
    """
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
