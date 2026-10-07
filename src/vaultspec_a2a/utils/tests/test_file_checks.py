"""The directory refusal the journal and index owners share.

A symlink or junction to a directory answers ``is_dir`` as true, so a caller that
owns the directory cannot ask that question alone. These cases run against a
real filesystem: the aliasing is the behavior under test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import is_real_directory

if TYPE_CHECKING:
    from pathlib import Path


def test_a_plain_directory_is_real(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()

    assert is_real_directory(directory)


def test_a_file_and_an_absent_name_are_not_real_directories(tmp_path: Path) -> None:
    file = tmp_path / "file"
    file.write_bytes(b"")

    assert not is_real_directory(file)
    assert not is_real_directory(tmp_path / "absent")


def test_a_link_to_a_directory_is_not_a_real_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    assert link.is_dir()
    assert not is_real_directory(link)
