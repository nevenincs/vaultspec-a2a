"""A failed publication must leave the filesystem as it found it.

The success path of write-and-rename is easy and was never the problem.  What
went wrong in this service was the failure path: three implementations each left
their temporary file behind when a publication did not complete, and one such
orphan sat beside a live discovery record for six days.

So these tests force real failures against real files - a target directory that
disappears, a rename denied for longer than the retry window, an interruption
mid-write - and assert on what is left on disk afterwards.  No mocks: the
failures are produced by genuinely unwritable or contended filesystem state.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ..atomic_write import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


def _temporaries(directory: Path) -> list[Path]:
    """Return every temporary-file residue in *directory*."""
    return sorted(directory.glob("*.tmp"))


def test_content_is_published_and_no_temporary_survives(tmp_path: Path) -> None:
    """The ordinary case publishes the bytes and cleans up after itself."""
    target = tmp_path / "record.json"

    atomic_write_text(target, '{"port": 18000}')

    assert target.read_text(encoding="utf-8") == '{"port": 18000}'
    assert _temporaries(tmp_path) == []


def test_publication_replaces_existing_content_wholesale(tmp_path: Path) -> None:
    """A republish overwrites rather than appending or merging."""
    target = tmp_path / "record.json"
    atomic_write_text(target, "first-and-longer-content")

    atomic_write_text(target, "second")

    assert target.read_text(encoding="utf-8") == "second"
    assert _temporaries(tmp_path) == []


def test_a_failed_write_leaves_no_temporary_behind(tmp_path: Path) -> None:
    """When the destination directory does not exist, nothing is left behind.

    This is the failure the previous implementations mishandled: the temporary
    is created in the same directory as the target, so a directory problem
    surfaces mid-publication rather than before it.
    """
    missing = tmp_path / "absent-directory"
    target = missing / "record.json"

    with pytest.raises(OSError):
        atomic_write_text(target, "never-lands")

    assert not missing.exists()
    assert _temporaries(tmp_path) == []


def test_a_denied_rename_removes_the_temporary_before_propagating(
    tmp_path: Path,
) -> None:
    """A rename that stays denied past the retry window must not leak residue.

    A directory standing where the target file belongs makes ``os.replace``
    fail on every platform, which is a genuine unrecoverable rename rather than
    the transient contention the retry exists for.
    """
    target = tmp_path / "record.json"
    target.mkdir()

    with pytest.raises(OSError):
        atomic_write_text(target, "cannot-replace-a-directory", retry_seconds=0.0)

    assert target.is_dir()
    assert _temporaries(tmp_path) == []


def test_a_non_os_failure_mid_write_still_removes_the_temporary(
    tmp_path: Path,
) -> None:
    """A failure that is not an OSError must clean up too.

    An unpaired surrogate cannot be encoded as UTF-8, so the write raises a
    UnicodeEncodeError after the temporary file already exists.  Catching only
    OSError would leak residue here, which is why the helper catches every
    exception type on its way out.
    """
    target = tmp_path / "record.json"

    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(target, "\ud800")

    assert not target.exists()
    assert _temporaries(tmp_path) == []


def test_the_temporary_is_named_for_the_writing_process(tmp_path: Path) -> None:
    """Two publishers must not collide on the temporary file itself.

    Occupying the expected temporary name with a directory makes the write fail,
    which proves the helper targets exactly that name rather than asserting on
    an implementation detail from the outside.
    """
    target = tmp_path / "record.json"
    expected_temporary = tmp_path / f"record.json.{os.getpid()}.tmp"
    expected_temporary.mkdir()

    with pytest.raises(OSError):
        atomic_write_text(target, "blocked-by-the-occupied-temporary")

    assert not target.exists()
    assert expected_temporary.is_dir()
